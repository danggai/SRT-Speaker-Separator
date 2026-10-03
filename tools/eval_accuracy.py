"""자동 자막 / 화자 분리 정확도 평가 도구.

정답 SRT(`[화자] 내용` 형식)가 있는 미디어에서 일부 구간을 잘라 테스트 케이스로
만들고, 앱의 실제 인식·화자 분리 함수를 돌려 정확도를 잰다.

사용법:
  # 1) 테스트 케이스 생성 (eval_cases/<name>/audio.wav + ref.srt)
  python tools/eval_accuracy.py make-case --media 원본.mp3 --ref 정답.srt \
      --start 270.5 --end 333 --name sample01

  # 2) 평가 (--baseline: 개선 전 파이프라인도 같이 돌려 비교)
  python tools/eval_accuracy.py run --name sample01 [--mode accurate] [--baseline]

지표:
  CER          글자 오류율. 한글/영문/숫자만 남겨 비교 (ㅋㅋ·이모지·문장부호·띄어쓰기 무시)
  화자(시간)   정답 자막 구간 중 올바른 화자로 판정된 시간 비율
  화자(줄)     정답 자막 줄마다 화자를 하나씩 붙였을 때 맞힌 비율
  '자동 생성'  = 미디어만으로 자막+화자 생성 (자막 자동 생성 기능)
  'SRT 매핑'   = 정답 SRT 타이밍에 화자만 붙임 (화자 분석 기능)
  화자 라벨(SPEAKER_00 등)은 정답 화자명과 겹침이 최대가 되도록 1:1 매칭한 뒤 채점한다.
  태그 없는 자막(편집 자막, 효과음 설명 등)은 평가에서 제외한다.
"""
import argparse
import copy
import gc
import itertools
import json
import os
import pathlib
import re
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
CASES = ROOT / "eval_cases"
SR = 16000

# 앱의 음성 인식/화자 분리 로직(GUI 의존성 없음)을 그대로 가져와 검증한다
sys.path.insert(0, str(ROOT))
from srt_editor import speech  # noqa: E402


# ── SRT ────────────────────────────────────────────────────────────
_TS = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")
_TAG = re.compile(r"^\[(.+?)\]\s*(.*)$", re.S)


def _sec(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def parse_srt(path):
    subs = []
    for block in re.split(r"\n\s*\n", pathlib.Path(path).read_text(encoding="utf-8-sig")):
        lines = [l for l in block.strip().splitlines() if not l.startswith(";")]
        ts_i = next((i for i, l in enumerate(lines) if _TS.search(l)), None)
        if ts_i is None:
            continue
        g = _TS.search(lines[ts_i]).groups()
        text = "\n".join(lines[ts_i + 1:]).strip()
        m = _TAG.match(text)
        subs.append({"start": _sec(*g[:4]), "end": _sec(*g[4:]),
                     "speaker": m.group(1).strip() if m else "",
                     "text": (m.group(2) if m else text).strip()})
    return subs


def _fmt(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def write_srt(subs, path):
    with open(path, "w", encoding="utf-8") as f:
        for i, s in enumerate(subs, 1):
            tag = f"[{s['speaker']}] " if s.get("speaker") else ""
            f.write(f"{i}\n{_fmt(s['start'])} --> {_fmt(s['end'])}\n{tag}{s['text']}\n\n")


# ── 지표 ───────────────────────────────────────────────────────────
def normalize(text):
    """한글 음절·영문·숫자만 남긴다 (자모 ㅋㅋ, 이모지, 문장부호, 공백 제거)."""
    return re.sub(r"[^0-9a-z가-힣]", "", text.lower())


def edit_distance(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cer(ref_text, hyp_text):
    r, h = normalize(ref_text), normalize(hyp_text)
    return edit_distance(r, h) / max(1, len(r)), len(r)


def _ov(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def best_mapping(ref, turns):
    """화자 라벨 → 정답 화자명 1:1 매칭 (겹침 시간 합 최대)."""
    names = sorted({r["speaker"] for r in ref})
    ids = sorted({t[2] for t in turns})
    ov = {(i, n): sum(_ov(t[0], t[1], r["start"], r["end"])
                      for t in turns if t[2] == i for r in ref if r["speaker"] == n)
          for i in ids for n in names}
    best, best_score = {}, -1.0
    if len(ids) <= 8:
        k = min(len(ids), len(names))
        for chosen in itertools.permutations(ids, k):
            for perm in itertools.permutations(names, k):
                sc = sum(ov[(i, n)] for i, n in zip(chosen, perm))
                if sc > best_score:
                    best_score, best = sc, dict(zip(chosen, perm))
    else:   # 화자가 너무 많이 검출되면 탐욕적 매칭
        for (i, n), _ in sorted(ov.items(), key=lambda kv: -kv[1]):
            if i not in best and n not in best.values():
                best[i] = n
    return best


def time_speaker_acc(ref, turns, mapping):
    ok = tot = 0.0
    for r in ref:
        for t0, t1, sid in turns:
            o = _ov(t0, t1, r["start"], r["end"])
            tot += o
            ok += o if mapping.get(sid) == r["speaker"] else 0.0
    return ok / tot if tot else 0.0


def line_errors(ref, assigned, mapping):
    return [(r, mapping.get(a, a or "-")) for r, a in zip(ref, assigned)
            if mapping.get(a) != r["speaker"]]


# ── 이전(개선 전) 방식 재현 ───────────────────────────────────────
def legacy_assign(intervals, turns, samples=20):
    """개선 전 화자 매핑: 자막 구간을 20개 점으로 샘플링해, 각 시점에 '마지막으로
    시작한' 화자 구간 하나만 보고 투표 (동시 발화 구간은 놓침)."""
    import bisect
    ts = sorted(turns, key=lambda x: x[0])
    starts = [t[0] for t in ts]
    out = []
    for t_s, t_e in intervals:
        sc = {}
        for k in range(samples):
            r = (k + 0.5) / samples
            t = t_s + (t_e - t_s) * r
            i = bisect.bisect_right(starts, t) - 1
            if i >= 0 and ts[i][0] <= t <= ts[i][1]:
                sc[ts[i][2]] = sc.get(ts[i][2], 0.0) + (0.5 if r < 0.1 or r > 0.9 else 1.0)
        if sc:
            out.append(max(sc, key=sc.get))
        else:
            mid = (t_s + t_e) / 2
            out.append(min(ts, key=lambda d: abs(mid - (d[0] + d[1]) / 2))[2] if ts else None)
    return out


# ── 명령 ───────────────────────────────────────────────────────────
def make_case(a):
    ref = parse_srt(a.ref)
    sel = [dict(s, start=s["start"] - a.start, end=s["end"] - a.start)
           for s in ref if s["start"] >= a.start and s["end"] <= a.end]
    d = CASES / a.name
    d.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(a.start), "-to", str(a.end),
                    "-i", a.media, "-ac", "1", "-ar", str(SR), str(d / "audio.wav")], check=True)
    write_srt(sel, d / "ref.srt")
    (d / "case.json").write_text(json.dumps(
        {"media": os.path.basename(a.media), "start": a.start, "end": a.end},
        ensure_ascii=False, indent=2), encoding="utf-8")
    tagged = [s for s in sel if s["speaker"]]
    print(f"케이스 생성: {d}  ({a.end - a.start:.1f}초, 자막 {len(sel)}줄 / 화자 태그 {len(tagged)}줄, "
          f"화자 {sorted({s['speaker'] for s in tagged})})")


def _hf_token():
    tok = os.environ.get("HF_TOKEN", "")
    cfg = pathlib.Path.home() / ".srt_speaker_editor_config.json"
    if not tok and cfg.exists():
        tok = json.loads(cfg.read_text(encoding="utf-8")).get("hf_token", "")
    if not tok:
        sys.exit("HuggingFace 토큰이 없습니다 (HF_TOKEN 환경변수 또는 앱 설정).")
    return tok


def _free(device):
    gc.collect()
    if device == "cuda":
        import torch
        torch.cuda.empty_cache()


def _transcribe(whisperx, model, audio, device, language):
    bs = 16 if device == "cuda" else 1
    res = model.transcribe(audio, batch_size=bs, language=language)
    lang = res["language"]
    am, meta = whisperx.load_align_model(language_code=lang, device=device)
    res = whisperx.align(res["segments"], am, meta, audio, device, return_char_alignments=False)
    del am
    return res, lang


def _report(title, ref, hyp_text, auto_turns, auto_assigned, map_turns, map_assigned, secs, extra=""):
    c, n = cer(" ".join(r["text"] for r in ref), hyp_text)
    m_auto = best_mapping(ref, auto_turns)
    m_map = best_mapping(ref, map_turns)
    errs_auto = line_errors(ref, auto_assigned, m_auto)
    errs_map = line_errors(ref, map_assigned, m_map)
    row = {
        "title": title,
        "cer": c, "ref_chars": n,
        "auto_time_acc": time_speaker_acc(ref, auto_turns, m_auto),
        "auto_line_acc": 1 - len(errs_auto) / len(ref),
        "map_line_acc": 1 - len(errs_map) / len(ref),
        "n_spk": len({t[2] for t in map_turns}),
        "secs": secs, "extra": extra,
        "map_errors": [(_fmt(r["start"]), r["speaker"], h, r["text"]) for r, h in errs_map],
        "auto_errors": [(_fmt(r["start"]), r["speaker"], h, r["text"]) for r, h in errs_auto],
    }
    return row


def run(a):
    import warnings
    import logging
    warnings.filterwarnings("ignore")
    logging.disable(logging.WARNING)
    import whisperx
    import torch
    from whisperx.diarize import DiarizationPipeline, assign_word_speakers

    d = CASES / a.name
    ref = [r for r in parse_srt(d / "ref.srt") if r["speaker"]]
    audio = whisperx.load_audio(str(d / "audio.wav"))
    device = "cuda" if (a.device != "cpu" and torch.cuda.is_available()) else "cpu"
    print(f"케이스 {a.name}: {len(audio) / SR:.1f}초, 화자 태그 자막 {len(ref)}줄, 장치 {device}")

    diar = DiarizationPipeline(token=_hf_token(), device=device)
    speech._apply_diarize_sensitivity(diar, a.sensitivity)
    intervals = [(r["start"], r["end"]) for r in ref]
    rows = []

    if a.diarize_only:
        t0 = time.time()
        df = speech._diarize_exclusive(diar, audio, a.num_speakers, a.exact)
        turns = [(float(r.start), float(r.end), r.speaker) for r in df.itertuples(index=False)]
        m = best_mapping(ref, turns)
        errs = line_errors(ref, speech._assign_speakers_by_overlap(intervals, turns), m)
        print(f"화자수 설정={a.num_speakers or '자동'}{'(고정)' if a.exact else ''} "
              f"민감도={a.sensitivity} → 검출 화자 {len({t[2] for t in turns})}명, "
              f"SRT 매핑 화자(줄) {1 - len(errs) / len(ref):.1%}, "
              f"화자(시간) {time_speaker_acc(ref, turns, m):.1%}, {time.time() - t0:.0f}s")
        for r, h in errs:
            print(f"  {_fmt(r['start'])}  정답 {r['speaker']} → {h}  {r['text']}")
        return

    # ── 개선 후 (현재 앱 코드) ──
    t0 = time.time()
    model, wname = speech._load_asr_model(whisperx, a.mode, device, language="ko")
    aligned, _ = _transcribe(whisperx, model, audio, device, "ko")
    del model; _free(device)
    df = speech._diarize_exclusive(diar, audio, a.num_speakers, a.exact)
    segs = speech._split_segments_by_speaker(
        assign_word_speakers(df, copy.deepcopy(aligned))["segments"])
    auto_turns = [(s["start"], s["end"], s.get("speaker", "")) for s in segs if s.get("speaker")]
    map_turns = [(float(r.start), float(r.end), r.speaker) for r in df.itertuples(index=False)]
    rows.append(_report(
        f"개선 후 ({a.mode}: {wname}, 한국어 고정)", ref, " ".join(s["text"] for s in segs),
        auto_turns, speech._assign_speakers_by_overlap(intervals, auto_turns),
        map_turns, speech._assign_speakers_by_overlap(intervals, map_turns),
        time.time() - t0))
    write_srt([{"start": s["start"], "end": s["end"], "speaker": s.get("speaker", ""),
                "text": s["text"].strip()} for s in segs], d / "hyp_new.srt")

    # ── 개선 전 (이전 앱 동작 재현) ──
    if a.baseline:
        t0 = time.time()
        model = whisperx.load_model("large-v3-turbo", device,
                                    compute_type="float16" if device == "cuda" else "float32",
                                    asr_options={"beam_size": 3})
        aligned_old, lang = _transcribe(whisperx, model, audio, device, None)
        del model; _free(device)
        kw = {"num_speakers": a.num_speakers} if a.num_speakers else {}
        df_old = diar(audio, **kw)
        segs_old = assign_word_speakers(df_old, copy.deepcopy(aligned_old))["segments"]
        old_turns = [(s["start"], s["end"], s["speaker"]) for s in segs_old if s.get("speaker")]
        # 이전 버전은 자동 생성/SRT 매핑 모두 '세그먼트 대표 화자'를 사용했다
        rows.append(_report(
            "개선 전 (turbo, 언어 자동감지, 세그먼트 단위 화자)", ref,
            " ".join(s["text"] for s in segs_old),
            old_turns, speech._assign_speakers_by_overlap(intervals, old_turns),
            old_turns, legacy_assign(intervals, old_turns),
            time.time() - t0, extra=f"감지 언어={lang}"))
        write_srt([{"start": s["start"], "end": s["end"], "speaker": s.get("speaker", ""),
                    "text": s["text"].strip()} for s in segs_old], d / "hyp_old.srt")

    # ── 출력 ──
    print()
    print(f"{'구성':<44} {'CER':>6} {'자동생성 화자(시간)':>10} {'자동생성 화자(줄)':>10} "
          f"{'SRT매핑 화자(줄)':>10} {'화자수':>4} {'소요':>6}")
    for r in rows:
        print(f"{r['title']:<44} {r['cer']:6.1%} {r['auto_time_acc']:>17.1%} {r['auto_line_acc']:>16.1%} "
              f"{r['map_line_acc']:>15.1%} {r['n_spk']:>5} {r['secs']:5.0f}s  {r['extra']}")
    for r in rows:
        print(f"\n[{r['title']}] SRT 매핑 오답 {len(r['map_errors'])}줄:")
        for e in r["map_errors"]:
            print(f"  {e[0]}  정답 {e[1]} → {e[2]}  {e[3]}")
    (d / "result.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n결과 저장: {d / 'result.json'}  (인식 결과: hyp_new.srt"
          f"{', hyp_old.srt' if a.baseline else ''})")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make-case", help="원본 미디어+정답 SRT에서 테스트 케이스 생성")
    m.add_argument("--media", required=True)
    m.add_argument("--ref", required=True)
    m.add_argument("--start", type=float, required=True, help="시작(초)")
    m.add_argument("--end", type=float, required=True, help="끝(초)")
    m.add_argument("--name", required=True)
    r = sub.add_parser("run", help="테스트 케이스로 정확도 평가")
    r.add_argument("--name", required=True)
    r.add_argument("--mode", default="accurate", choices=["fast", "balanced", "accurate", "best"])
    r.add_argument("--device", default="auto", choices=["auto", "cpu"])
    r.add_argument("--num-speakers", type=int, default=0, help="0=자동")
    r.add_argument("--exact", action="store_true", help="화자 수를 정확히 고정")
    r.add_argument("--sensitivity", type=int, default=50, help="화자 분리 민감도 0~100 (50=기본)")
    r.add_argument("--diarize-only", action="store_true",
                   help="음성 인식 없이 SRT 매핑(화자 분석)만 평가 — 화자 설정 튜닝용")
    r.add_argument("--baseline", action="store_true", help="개선 전 파이프라인도 실행해 비교")
    a = p.parse_args()
    make_case(a) if a.cmd == "make-case" else run(a)


if __name__ == "__main__":
    main()
