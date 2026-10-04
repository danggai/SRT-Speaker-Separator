"""HuggingFace 모델을 미리 내려받으며 바이트 단위 진행률을 알려 준다. GUI 의존성 없음."""
import fnmatch
import os
import threading

DIARIZE_REPO = "pyannote/speaker-diarization-community-1"
WHISPER_PATTERNS = ["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"]


def whisper_repo(model_name):
    """faster-whisper 모델 이름(large-v3 등) → HF 저장소 이름."""
    if "/" in model_name:
        return model_name
    from faster_whisper.utils import _MODELS
    return _MODELS.get(model_name, model_name)


def align_repo(language_code):
    """정렬(wav2vec2) 모델의 HF 저장소 이름. torchaudio 내장 모델이면 None."""
    from whisperx.alignment import DEFAULT_ALIGN_MODELS_HF
    return DEFAULT_ALIGN_MODELS_HF.get(language_code)


def is_cached(repo_id, allow_patterns=None):
    """필요한 파일이 모두 내려받아져 있는가 (네트워크 없이 확인)."""
    try:
        from huggingface_hub import snapshot_download
        snapshot_download(repo_id, allow_patterns=allow_patterns, local_files_only=True)
        return True
    except Exception:
        return False


def _remote_size(repo_id, allow_patterns, token):
    try:
        from huggingface_hub import HfApi
        info = HfApi().model_info(repo_id, files_metadata=True, token=token or None)
        files = [s for s in info.siblings if not allow_patterns
                 or any(fnmatch.fnmatch(s.rfilename, p) for p in allow_patterns)]
        return sum(s.size or 0 for s in files) or None
    except Exception:
        return None


def _blobs_size(repo_id):
    """내려받는 중인 파일(.incomplete 포함)까지 합한 저장소 캐시 크기."""
    try:
        from huggingface_hub.constants import HF_HUB_CACHE
        from huggingface_hub.file_download import repo_folder_name
        blobs = os.path.join(HF_HUB_CACHE, repo_folder_name(repo_id=repo_id, repo_type="model"), "blobs")
        return sum(e.stat().st_size for e in os.scandir(blobs) if e.is_file())
    except OSError:
        return 0


def download(repo_id, allow_patterns=None, token=None, progress=None, cancelled=None):
    """모델 내려받기. progress(받은 바이트, 전체 바이트 또는 None)를 0.3초마다 호출.
    이미 받아져 있으면 바로 끝난다. 반환: 저장 경로."""
    from huggingface_hub import snapshot_download

    if is_cached(repo_id, allow_patterns):
        return snapshot_download(repo_id, allow_patterns=allow_patterns, token=token or None)
    total = _remote_size(repo_id, allow_patterns, token)
    stop = threading.Event()

    def _watch():
        while not stop.is_set():
            if progress is not None and not (cancelled and cancelled()):
                done = _blobs_size(repo_id)
                progress(min(done, total) if total else done, total)
            stop.wait(0.3)

    t = threading.Thread(target=_watch, daemon=True)
    t.start()
    try:
        return snapshot_download(repo_id, allow_patterns=allow_patterns, token=token or None)
    finally:
        stop.set()
        t.join(1)
        if progress is not None and total and not (cancelled and cancelled()):
            progress(total, total)


def format_progress(name, done, total):
    """'모델 이름  412 / 3,087 MB (13%)' 형태의 한 줄."""
    mb = done / 1048576
    if total:
        return f"{name}  {mb:,.0f} / {total / 1048576:,.0f} MB ({min(100, done * 100 // total)}%)"
    return f"{name}  {mb:,.0f} MB"
