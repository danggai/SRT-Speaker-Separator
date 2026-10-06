"""자동 자막 품질 평가: 정답 SRT가 있는 미디어의 몇 구간을 설정별로 인식해 비교한다.

AI 부품 파이썬(whisperx·torch)으로 실행:
  <AI python> tools/eval_transcribe.py --media 원본.mp3 --ref 정답.srt [--configs "accurate;best;m=모델"] [--win 150]

지표 (구간 합산):
  CER      글자 오류율 (한글·영문·숫자만 비교)
  헛줄     정답 자막과 시간이 전혀 안 겹치는 인식 줄 수 (지어낸 문장 후보)
  빠진줄   인식 줄과 전혀 안 겹치는 정답 줄 수 (놓친 말)
  시작차   정답 줄 시작마다 가장 가까운 인식 줄 시작과의 차이 중앙값 (초)
"""
import argparse
import json
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from eval_accuracy import edit_distance, normalize, parse_srt  # noqa: E402
from srt_editor import speech, transcript_post  # noqa: E402

SR = 16000
PROPER = ["루시", "루파", "헥시아", "아구", "아빠킹", "아즈", "레비얀", "마무"]

# 이름 → (모드, 추가 asr_options, 추가 load 옵션)
CONFIGS = {
    "fast": ("fast", {}, {}),
    "balanced": ("balanced", {}, {}),
    "accurate": ("accurate", {}, {}),
    "best": ("best", {}, {}),
    "accurate+hint": ("accurate", {"hotwords": " ".join(PROPER), "initial_prompt": ", ".join(PROPER)}, {}),
    "accurate+chunk15": ("accurate", {}, {"chunk_size": 15}),
    "best+chunk15": ("best", {}, {"chunk_size": 15}),
    "best+beam10": ("best", {"beam_size": 10}, {}),
    "best+patience2": ("best", {"patience": 2.0}, {}),
    "best+prev": ("best", {"condition_on_previous_text": True}, {}),
}


def _ov(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def score(ref, hyp):
    rt = " ".join(r["text"] for r in ref)
    ht = " ".join(h["text"] for h in hyp)
    r, h = normalize(rt), normalize(ht)
    dist = edit_distance(r, h)
    ghost = sum(1 for x in hyp if not any(_ov(x["start"], x["end"], y["start"], y["end"]) > 0 for y in ref))
    miss = sum(1 for y in ref if y["speaker"] and not any(_ov(x["start"], x["end"], y["start"], y["end"]) > 0
                                                           for x in hyp))
    diffs = sorted(min((abs(x["start"] - y["start"]) for x in hyp), default=9.9) for y in ref)
    return {"dist": dist, "chars": len(r), "ghost": ghost, "miss": miss, "lines": len(hyp),
            "ref_lines": len(ref), "start_diffs": diffs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--media", required=True)
    ap.add_argument("--ref", required=True)
    ap.add_argument("--configs", default="accurate")
    ap.add_argument("--win", type=float, default=150.0)
    ap.add_argument("--starts", default="60,330,600,870")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    import warnings
    warnings.filterwarnings("ignore")
    import logging
    logging.disable(logging.WARNING)
    import torch
    import whisperx
    device = "cuda" if torch.cuda.is_available() else "cpu"
    audio = whisperx.load_audio(a.media)
    ref_all = parse_srt(a.ref)
    starts = [float(s) for s in a.starts.split(",") if float(s) + 10 < len(audio) / SR]   # 음성 밖 구간은 뺌
    results = {}
    for name in a.configs.split(";"):
        if name.startswith("m="):   # 다른 모델: m=<허깅페이스 이름 또는 변환한 폴더>, 설정은 '최고 정확'과 같게
            mode, extra_asr, extra_load = "best", {}, {}
            wmodel = name[2:]
            _, beam, onset, offset = speech._ASR_MODES[mode]
        else:
            mode, extra_asr, extra_load = CONFIGS[name]
            wmodel, beam, onset, offset = speech._ASR_MODES[mode]
        t0 = time.time()
        model = whisperx.load_model(wmodel, device, compute_type="float16" if device == "cuda" else "int8",
                                    language="ko", asr_options={"beam_size": beam, **extra_asr},
                                    vad_options={"vad_onset": onset, "vad_offset": offset})
        align_model, meta = whisperx.load_align_model(language_code="ko", device=device)
        tot = {"raw": [], "post": []}
        for s0 in starts:
            s1 = s0 + a.win
            chunk = audio[int(s0 * SR):int(s1 * SR)]
            res = model.transcribe(chunk, batch_size=16, language="ko", **extra_load)
            res = whisperx.align(res["segments"], align_model, meta, chunk, device, return_char_alignments=False)
            segs = [dict(sg, start=sg["start"] + s0, end=sg["end"] + s0,
                         words=[dict(w, **({"start": w["start"] + s0, "end": w["end"] + s0} if "start" in w else {}))
                                for w in sg.get("words", [])]) for sg in res["segments"]]
            ref = [r for r in ref_all if r["start"] >= s0 and r["end"] <= s1]
            raw = [{"start": sg["start"], "end": sg["end"], "text": sg["text"].strip()} for sg in segs]
            post = transcript_post.build_lines(segs)
            tot["raw"].append(score(ref, raw))
            tot["post"].append(score(ref, post))
        del model, align_model
        import gc
        gc.collect()
        if device == "cuda":
            torch.cuda.empty_cache()
        el = time.time() - t0
        row = {}
        for k, parts in tot.items():
            d = sum(p["dist"] for p in parts)
            c = sum(p["chars"] for p in parts)
            diffs = sorted(x for p in parts for x in p["start_diffs"])
            row[k] = {"CER": round(100 * d / max(1, c), 2), "헛줄": sum(p["ghost"] for p in parts),
                      "빠진줄": sum(p["miss"] for p in parts), "줄": sum(p["lines"] for p in parts),
                      "정답줄": sum(p["ref_lines"] for p in parts),
                      "시작차": round(diffs[len(diffs) // 2], 2) if diffs else None,
                      "구간별": [round(100 * p["dist"] / max(1, p["chars"]), 1) for p in parts]}
        row["초"] = round(el)
        results[name] = row
        print(name, json.dumps(row, ensure_ascii=False))
    if a.out:
        pathlib.Path(a.out).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
