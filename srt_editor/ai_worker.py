"""AI 작업 실행기. 앱과 분리된 파이썬(AI 부품)에서 whisperx·torch 작업을 하고 결과를 JSON 파일로 남긴다.

    python ai_worker.py job.json

진행 상황은 표준출력에 '@@{json}' 한 줄씩: {"type": "status", "msg": ..., "step": ..., "pct": ...}
결과는 job["result"] 경로에 JSON으로, 실패하면 {"type": "error", "msg": ...}를 내고 종료 코드 1.
이 파일과 같은 폴더의 speech·line_speakers·model_download·correction_audio를 그대로 불러 쓴다.
"""
import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")   # xet 방식은 끝날 때 한 번에 써서 진행도가 멈춰 보임
SR = 16000


def emit(**kw):
    sys.stdout.write("@@" + json.dumps(kw, ensure_ascii=False, default=float) + "\n")
    sys.stdout.flush()


def status(msg, step=None, pct=None):
    emit(type="status", msg=msg, step=step, pct=pct)


def _device(pref):
    import torch
    return "cuda" if pref != "cpu" and torch.cuda.is_available() else "cpu"


def _free(device):
    import gc
    gc.collect()
    if device == "cuda":
        import torch
        torch.cuda.empty_cache()


def _fetch(repo, label, patterns, lo, hi, step, token=None):
    import model_download

    def cb(done, total):
        pct = lo + (hi - lo) * (done / total) if total else lo
        status(f"{label} 내려받는 중  " + model_download.format_progress("", done, total).strip(), step, pct)
    model_download.download(repo, patterns, token=token, progress=cb)


def _diar_pipeline(job, device, step, lo, hi):
    import model_download
    import speech
    from whisperx.diarize import DiarizationPipeline
    _fetch(model_download.DIARIZE_REPO, "화자 분리 모델", None, lo, hi, step, token=job.get("hf_token"))
    status(f"화자 분리 모델 불러오는 중... ({device})", step, hi)
    pipe = DiarizationPipeline(token=job.get("hf_token") or None, device=device)
    speech._apply_diarize_sensitivity(pipe, job.get("sensitivity", 50))
    return pipe


EMB_CACHE_KEEP = 20   # 영상 수 (줄당 약 1KB)


def _emb_cache_path(job, model=""):
    import hashlib
    d = job.get("cache_dir")
    if not d:
        return None
    st = os.stat(job["media"])
    key = f"{os.path.abspath(job['media'])}|{st.st_size}|{st.st_mtime_ns}"
    return os.path.join(d, hashlib.sha1(key.encode("utf-8")).hexdigest() + (f"_{model}" if model else "") + ".npz")


def _emb_cache_load(path):
    import numpy as np
    try:
        with np.load(path) as z:
            return {(int(s), int(e)): row for (s, e), row in zip(z["keys"], z["emb"])}
    except Exception:
        return {}


def _emb_cache_save(path, cache):
    import numpy as np
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        keys = np.array(list(cache), dtype=np.int64).reshape(-1, 2)
        tmp = path + ".part.npz"
        np.savez(tmp, keys=keys, emb=np.vstack(list(cache.values())).astype(np.float32))
        os.replace(tmp, path)
        files = sorted((os.path.join(os.path.dirname(path), f) for f in os.listdir(os.path.dirname(path))
                        if f.endswith(".npz")), key=os.path.getmtime, reverse=True)
        for f in files[EMB_CACHE_KEEP:]:
            os.remove(f)
    except Exception:
        pass


def _campplus(device):
    """두 번째 목소리 모델 CAM++ (FunASR). 부품이 없으면 None → WeSpeaker만 씀."""
    try:
        from funasr import AutoModel
    except Exception:
        return None
    m = AutoModel(model="funasr/campplus", hub="hf", device="cuda:0" if device == "cuda" else "cpu",
                  disable_update=True, disable_pbar=True, disable_log=True)

    def emb(wav):
        out = m.generate(input=wav[0, 0].numpy(), disable_pbar=True)[0]["spk_embedding"]
        return out.cpu().numpy().reshape(1, -1)
    return emb


def _lines_result(job, device):
    """자막 줄마다 목소리를 뽑아 선지정 기준 분류 또는 군집. 이미 뽑은 줄은 모델별 캐시에서 재사용.
    WeSpeaker와 CAM++ 두 모델의 특징을 섞으면 여러 명이 나오는 영상에서 더 잘 구분된다."""
    import numpy as np
    import line_speakers
    intervals = [tuple(v) if v else (None, None) for v in job["intervals"]]
    keys = [(round(s * 1000), round(e * 1000)) if s is not None and e is not None else None for s, e in intervals]
    audio = None
    feats = []
    for model, load, lo in (("", lambda: _diar_pipeline(job, device, "model", 12, 25).model._embedding, 30),
                            ("campplus", lambda: _campplus(device), 62)):
        path = _emb_cache_path(job, model)
        cache = _emb_cache_load(path) if path else {}
        miss = [i for i, k in enumerate(keys) if k is not None and k not in cache]
        if miss:
            if audio is None:
                audio = _load_audio(job["media"], 3, 12)
            try:
                fn = load()
            except Exception:
                fn = None
            if fn is None:   # 두 번째 모델을 못 쓰면 첫 모델만
                continue
            status(f"자막 {len(miss)}줄의 목소리 분석 중...", "diarize", lo)
            sub = line_speakers.line_embeddings(fn, audio, [intervals[i] for i in miss])
            for i, row in zip(miss, sub):
                if not np.isnan(row).any():
                    cache[keys[i]] = row
            if path:
                _emb_cache_save(path, cache)
        dim = next((len(v) for v in cache.values()), 1)
        feats.append(np.vstack([cache[k] if k in cache else np.full(dim, np.nan) for k in keys])
                     if keys else np.zeros((0, dim)))
    emb = line_speakers.combine_embeddings(feats)
    status("화자 구분 중...", "map", 95)
    seeds = {int(k): v for k, v in (job.get("seeds") or {}).items()}
    if seeds:
        names, conf = line_speakers.assign_from_seeds(emb, seeds)
        return {"mode": "seeded", "names": names, "conf": [float(c) for c in conf]}
    num = int(job.get("num_speakers", 0))
    if num > 0 and job.get("exact"):
        labels, conf = line_speakers.cluster_lines(emb, num)
    else:   # 자동 또는 최대 N명: 실루엣 점수로 화자 수 추정
        labels, conf = line_speakers.cluster_lines(emb, 0, k_max=num if num > 0 else 10)
    return {"mode": "clusters", "labels": [int(v) for v in labels], "conf": [float(c) for c in conf]}


def job_diarize(job):
    import speech
    import whisperx
    device = _device(job.get("device", "auto"))
    if job.get("intervals"):
        return _lines_result(job, device)
    audio = _load_audio(job["media"], 3, 12)
    pipe = _diar_pipeline(job, device, "model", 12, 25)
    status("화자 분리 중...", "diarize", 30)
    df = speech._diarize_exclusive(pipe, audio, job.get("num_speakers", 0), job.get("exact", False))
    return {"mode": "turns", "turns": [[float(r.start), float(r.end), r.speaker]
                                       for r in df.itertuples(index=False)]}


def _load_audio(path, lo, hi):
    """whisperx.load_audio와 같은 결과 (16kHz 모노 float32). 긴 파일도 진행률을 알림."""
    import re
    import subprocess
    import threading
    import numpy as np
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-threads", "0", "-i", path, "-f", "s16le", "-ac", "1",
           "-acodec", "pcm_s16le", "-ar", str(SR), "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    dur, err = [0.0], []

    def read_err():
        for line in iter(p.stderr.readline, b""):
            err.append(line)
            m = not dur[0] and re.search(rb"Duration: (\d+):(\d+):(\d+\.?\d*)", line)
            if m:
                dur[0] = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    t = threading.Thread(target=read_err, daemon=True)
    t.start()
    progress = _stage_progress("음성 불러오는 중", "audio", lo, hi)
    status("음성 불러오는 중...", "audio", lo)
    buf = bytearray()
    while True:
        b = p.stdout.read(SR * 2 * 60)   # 1분 분량씩
        if not b:
            break
        buf += b
        if dur[0]:
            progress(min(99.0, 100 * len(buf) / (SR * 2 * dur[0])))
    p.wait()
    t.join(2)
    if p.returncode:
        raise RuntimeError("음성을 불러오지 못했어요: " + b"".join(err[-5:]).decode("utf-8", "replace").strip())
    audio = np.frombuffer(buf, np.int16).astype(np.float32)
    audio /= 32768.0
    return audio


def _stage_progress(label, step, lo, hi):
    """whisperx 진행 콜백(0~100) → '라벨  37% · 약 12분 남음' 상태 줄 (1초에 한 번까지)."""
    import time
    t0, last = time.time(), [0.0]

    def cb(p):
        now = time.time()
        if now - last[0] < 1 and p < 100:
            return
        last[0] = now
        msg = f"{label}  {p:.0f}%"
        if 3 <= p < 100 and now - t0 > 10:
            left = (now - t0) * (100 - p) / p
            msg += f" · 약 {max(1, round(left / 60))}분 남음"
        status(msg, step, lo + (hi - lo) * p / 100)
    return cb


MMS_PAD = 0.3   # 정렬할 때 조각 앞뒤로 더 보는 길이 (초, 옆 조각을 넘지 않게)


def _align_mms(segments, audio, device, progress=None):
    """다국어 MMS 정렬 모델로 단어 시간 맞추기 (한국어 wav2vec2보다 말 겹침에서 덜 밀림).
    부품(uroman)이 없으면 None → 기존 정렬을 씀."""
    try:
        import torch
        import torchaudio
        import uroman
    except Exception:
        return None
    import speech
    status("정렬 모델 준비 중... (처음 한 번은 내려받아요)", "align", 61)
    bundle = torchaudio.pipelines.MMS_FA
    model = bundle.get_model(with_star=False).to(device).eval()
    tokenizer, aligner = bundle.get_tokenizer(), bundle.get_aligner()
    vocab = set(bundle.get_dict(star=None)) - {"-"}
    rom = uroman.Uroman()
    wav_all = torch.from_numpy(audio)
    out = []
    for k, s in enumerate(segments):
        lo = max(0.0, s["start"] - MMS_PAD, segments[k - 1]["end"] if k else 0.0)
        hi = min(len(audio) / SR, s["end"] + MMS_PAD, segments[k + 1]["start"] if k + 1 < len(segments) else 1e9)
        words = (s.get("text") or "").split()
        romz = ["".join(ch for ch in rom.romanize_string(speech.spoken_form(w)).lower() if ch in vocab) for w in words]
        idx = [i for i, r in enumerate(romz) if r]   # 읽을 수 없는 단어는 시간 없이 둠 (앞뒤로 보간)
        ws = [{"word": w} for w in words]
        if idx and hi > lo:
            wav = wav_all[int(lo * SR):int(hi * SR)].unsqueeze(0).to(device)
            try:
                with torch.inference_mode():
                    em, _ = model(wav)
                ratio = wav.shape[1] / em.shape[1] / SR
                for i, sp in zip(idx, aligner(em[0], tokenizer([romz[i] for i in idx]))):
                    ws[i].update(start=round(lo + sp[0].start * ratio, 3), end=round(lo + sp[-1].end * ratio, 3),
                                 score=round(float(sum(t.score for t in sp) / len(sp)), 3))
            except Exception:   # 소리가 글자보다 짧은 조각 등: 그 조각만 시간 없이
                pass
        timed = [w for w in ws if "start" in w]
        out.append({"start": timed[0]["start"] if timed else s["start"], "end": timed[-1]["end"] if timed else s["end"],
                    "text": (s.get("text") or "").strip(), "words": ws})
        if progress:
            progress(100.0 * (k + 1) / len(segments))
    del model
    return out


def _retry_loops(model, audio, segments, batch_size, lang):
    """같은 문장만 되풀이한 구간을 짧은 조각으로 다시 인식 (그 사이 실제 대사가 통째로 빠지는 오류)."""
    import speech
    loops = speech.find_loops(segments)
    if not loops:
        return segments
    status("반복 인식된 구간 다시 듣는 중...", "asr", 60)
    out, last = [], 0
    for i, j in loops:
        a, b = segments[i]["start"], segments[j]["end"]
        out.extend(segments[last:i])
        last = j + 1
        try:
            r = model.transcribe(audio[int(a * SR):int(b * SR)], batch_size=batch_size, language=lang,
                                 chunk_size=speech.LOOP_RETRY_CHUNK)
            new = [dict(s, start=s["start"] + a, end=s["end"] + a) for s in r["segments"]]
        except Exception:
            new = []
        out.extend(new if new and not speech.find_loops(new) else segments[i:j + 1])
    out.extend(segments[last:])
    return out


def job_transcribe(job):
    import model_download
    import speech
    import whisperx
    device = _device(job.get("device", "auto"))
    mode = job.get("mode", speech._DEFAULT_ASR_MODE)
    lang = job.get("language") or None
    wname = speech._ASR_MODES.get(mode, speech._ASR_MODES[speech._DEFAULT_ASR_MODE])[0]
    _fetch(model_download.whisper_repo(wname), "음성 인식 모델", model_download.WHISPER_PATTERNS, 3, 14, "model")
    status(f"Whisper 모델 불러오는 중... ({device})", "model", 14)
    model, wname = speech._load_asr_model(whisperx, mode, device, language=lang, asr_hint=job.get("asr_hint") or None)
    audio = _load_audio(job["media"], 15, 20)
    status(f"음성 인식 중... ({device} / {wname})", "asr", 20)
    if device == "cuda":
        bidx = max(0, min(int(job.get("batch", 3)), len(speech._DIARIZE_BATCH_MAP) - 1))
        batch_size = speech._DIARIZE_BATCH_MAP[bidx]
    else:
        batch_size = 1
    result = model.transcribe(audio, batch_size=batch_size, language=lang,
                              progress_callback=_stage_progress(f"음성 인식 중 ({device} / {wname})", "asr", 20, 60))
    result["segments"] = _retry_loops(model, audio, result["segments"], batch_size, lang)
    del model
    _free(device)
    status("타임스탬프 정렬 중...", "align", 60)
    segs = _align_mms(result["segments"], audio, device, _stage_progress("타임스탬프 정렬 중", "align", 64, 99))
    if segs is not None:
        _free(device)
        return {"segments": segs, "language": result.get("language")}
    arepo = model_download.align_repo(result["language"])
    if arepo:
        _fetch(arepo, "정렬 모델", None, 60, 64, "align")
    model_a, meta = whisperx.load_align_model(language_code=result["language"], device=device)
    result = whisperx.align(result["segments"], model_a, meta, audio, device, return_char_alignments=False,
                            progress_callback=_stage_progress("타임스탬프 정렬 중", "align", 64, 99))
    del model_a
    _free(device)
    return {"segments": result["segments"], "language": result.get("language")}


def job_verify(job):
    import correction_audio
    def prog(n, total):
        status(f"음성 확인 중…  {n} / {total}", "verify", 100.0 * n / max(1, total))
    res = correction_audio.verify(job["media"], [tuple(v) for v in job["items"]], mode=job.get("mode", "accurate"),
                                  device=job.get("device", "auto"), on_progress=prog)
    return {"results": res}


def job_probe(job):
    import torch
    import whisperx  # noqa: F401  (불러와지는지 확인)
    import sklearn  # noqa: F401
    if job.get("warm"):   # 실제 작업에 쓰는 모듈·DLL을 미리 불러 첫 실행 지연을 설치 때 치름
        import importlib
        for mod in ("whisperx.asr", "whisperx.alignment", "whisperx.diarize", "pyannote.audio"):
            try:
                importlib.import_module(mod)
            except Exception:
                pass
    return {"cuda": bool(torch.cuda.is_available()), "torch": torch.__version__,
            "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else ""}


def job_echo(job):
    for i in range(3):
        status(f"단계 {i}", "echo", i * 50)
    if job.get("fail"):
        raise RuntimeError(job["fail"])
    return {"echo": job.get("value")}


JOBS = {"diarize": job_diarize, "transcribe": job_transcribe, "verify": job_verify, "probe": job_probe,
        "echo": job_echo}


def main():
    import warnings
    warnings.filterwarnings("ignore")
    import logging
    logging.disable(logging.WARNING)
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    with open(sys.argv[1], encoding="utf-8") as f:
        job = json.load(f)
    try:
        out = JOBS[job["type"]](job)
    except Exception as e:
        traceback.print_exc()
        emit(type="error", msg=str(e) or type(e).__name__)
        sys.exit(1)
    tmp = job["result"] + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, default=float)
    os.replace(tmp, job["result"])
    emit(type="done")


if __name__ == "__main__":
    main()
