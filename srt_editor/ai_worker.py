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


def _lines_result(job, audio, pipe, step, pct):
    """자막 줄마다 목소리를 뽑아 선지정 기준 분류 또는 군집."""
    import line_speakers
    intervals = [tuple(v) if v else (None, None) for v in job["intervals"]]
    n = len(intervals)
    status(f"자막 {n}줄의 목소리 분석 중...", "diarize", pct)
    emb = line_speakers.line_embeddings(pipe.model._embedding, audio, intervals)
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
    status("음성 불러오는 중...", "audio", 8)
    audio = whisperx.load_audio(job["media"])
    pipe = _diar_pipeline(job, device, "model", 12, 25)
    if job.get("intervals"):
        return _lines_result(job, audio, pipe, "diarize", 30)
    status("화자 분리 중...", "diarize", 30)
    df = speech._diarize_exclusive(pipe, audio, job.get("num_speakers", 0), job.get("exact", False))
    return {"mode": "turns", "turns": [[float(r.start), float(r.end), r.speaker]
                                       for r in df.itertuples(index=False)]}


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
    status("음성 불러오는 중...", "audio", 15)
    audio = whisperx.load_audio(job["media"])
    status(f"음성 인식 중... ({device} / {wname})", "asr", 20)
    if device == "cuda":
        bidx = max(0, min(int(job.get("batch", 3)), len(speech._DIARIZE_BATCH_MAP) - 1))
        batch_size = speech._DIARIZE_BATCH_MAP[bidx]
    else:
        batch_size = 1
    result = model.transcribe(audio, batch_size=batch_size, language=lang)
    del model
    _free(device)
    status("타임스탬프 정렬 중...", "align", 60)
    arepo = model_download.align_repo(result["language"])
    if arepo:
        _fetch(arepo, "정렬 모델", None, 60, 64, "align")
    model_a, meta = whisperx.load_align_model(language_code=result["language"], device=device)
    result = whisperx.align(result["segments"], model_a, meta, audio, device, return_char_alignments=False)
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
