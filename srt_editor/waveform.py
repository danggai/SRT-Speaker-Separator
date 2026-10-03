"""파형 추출 (별도 프로세스에서 실행)과 디스크 캐시."""
import array
import hashlib
import os
import pathlib

CACHE_DIR = pathlib.Path.home() / ".srt_speaker_editor_cache" / "waveform"
_CACHE_KEEP = 50   # 최근 파일 몇 개까지 보관


def _cache_path(path, n_pts):
    st = os.stat(path)
    key = f"{os.path.abspath(path)}|{st.st_size}|{int(st.st_mtime)}|{n_pts}"
    return CACHE_DIR / (hashlib.md5(key.encode("utf-8")).hexdigest() + ".bin")


def load_cached(path, n_pts):
    """캐시된 파형이 있으면 반환, 없으면 None."""
    try:
        p = _cache_path(path, n_pts)
        if not p.exists():
            return None
        amp = array.array("f")
        amp.frombytes(p.read_bytes())
        os.utime(p)   # 최근 사용 표시
    except (OSError, ValueError):
        return None
    n = len(amp)
    return [(i / max(1, n - 1), amp[i]) for i in range(n)] if n else None


def save_cached(path, n_pts, pts):
    """파형을 캐시에 저장하고 오래된 캐시는 정리."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(path, n_pts).write_bytes(array.array("f", (a for _, a in pts)).tobytes())
        files = sorted(CACHE_DIR.glob("*.bin"), key=lambda f: f.stat().st_mtime, reverse=True)
        for f in files[_CACHE_KEEP:]:
            f.unlink(missing_ok=True)
    except OSError:
        pass


def extract_waveform_pts(path, n_pts):
    """오디오 파일에서 (시간 비율, 진폭) 목록을 만든다."""
    import librosa
    import numpy as np

    # 22050Hz 모노로 로드 (mp3/wav/flac/ogg/m4a 전부 지원)
    y, sr = librosa.load(path, sr=22050, mono=True)
    hop = max(1, len(y) // n_pts)

    # 항상 axis=0이 frame_length, axis=1이 n_frames
    frames = librosa.util.frame(y, frame_length=hop, hop_length=hop)
    if frames.ndim == 1:
        frames = frames.reshape(-1, 1)

    peak = np.max(np.abs(frames), axis=0)
    rms = np.sqrt(np.mean(frames ** 2, axis=0))
    amp = np.clip(peak * 0.6 + rms * 2.5, 0.0, 1.0)
    n = int(amp.shape[0])
    return [(i / max(1, n - 1), float(amp[i])) for i in range(n)]
