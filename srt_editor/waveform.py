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


def _amp(peak, rms):
    import numpy as np
    return np.clip(np.asarray(peak) * 0.6 + np.asarray(rms) * 2.5, 0.0, 1.0)


def extract_waveform_pts(path, n_pts):
    """오디오 파일에서 (시간 비율, 진폭) 목록을 만든다.
    PyAV(ffmpeg)로 16kHz 모노로 디코딩하며 10ms 조각의 최대값·제곱평균만 모은 뒤 n_pts개로 묶는다
    (mp3·m4a·aac·wav·flac·ogg 모두 길이가 정확하고, 긴 파일도 메모리는 조각 통계만 쓴다)."""
    import numpy as np
    try:
        import av
    except ImportError:
        from .video_deps import load_av
        av = load_av()
        if av is None:
            raise RuntimeError("소리 파일을 읽을 부품(PyAV)이 없어요")
    step = 160
    peak, sq = [], []
    carry = np.zeros(0, np.float32)
    with av.open(path) as c:
        res = av.AudioResampler(format="flt", layout="mono", rate=16000)
        for frame in c.decode(audio=0):
            for f in res.resample(frame):
                m = np.concatenate([carry, f.to_ndarray().reshape(-1) * 0.7071])   # ffmpeg 모노 변환은 두 채널 합/√2라 평균 기준으로 맞춤
                k = len(m) // step
                fr = m[:k * step].reshape(k, step)
                peak.append(np.abs(fr).max(axis=1))
                sq.append((fr * fr).mean(axis=1))
                carry = m[k * step:]
    if not peak:
        raise ValueError("읽은 소리가 없어요")
    peak, sq = np.concatenate(peak), np.concatenate(sq)
    per = max(1, -(-len(peak) // n_pts))   # 올림: 점이 n_pts를 넘지 않게
    n = len(peak) // per
    if n == 0:
        raise ValueError("읽은 소리가 없어요")
    amp = _amp(peak[:n * per].reshape(n, per).max(axis=1), np.sqrt(sq[:n * per].reshape(n, per).mean(axis=1)))
    return [(i / max(1, n - 1), float(amp[i])) for i in range(n)]