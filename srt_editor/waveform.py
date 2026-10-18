"""파형 추출 (별도 프로세스에서 실행)과 디스크 캐시."""
import hashlib
import os
import pathlib

CACHE_DIR = pathlib.Path.home() / ".srt_speaker_editor_cache" / "waveform"
_CACHE_KEEP = 50   # 최근 파일 몇 개까지 보관


STEP_SEC = 0.01   # 파형 조각 길이 (10ms): 확대해도 소리와 어긋나지 않게 이 단위 그대로 보관


def _cache_path(path, track=0):
    st = os.stat(path)
    key = f"{os.path.abspath(path)}|{st.st_size}|{int(st.st_mtime)}|10ms" + (f"|t{track}" if track else "")
    return CACHE_DIR / (hashlib.md5(key.encode("utf-8")).hexdigest() + ".bin")


def load_cached(path, track=0):
    """캐시된 파형 (조각별 최대값, 제곱평균) 배열 쌍. 없으면 None."""
    import numpy as np
    try:
        p = _cache_path(path, track)
        if not p.exists():
            return None
        a = np.frombuffer(p.read_bytes(), np.float32)
        os.utime(p)   # 최근 사용 표시
    except (OSError, ValueError):
        return None
    n = len(a) // 2
    return (a[:n].copy(), a[n:2 * n].copy()) if n else None


def save_cached(path, stats, track=0):
    """파형을 캐시에 저장하고 오래된 캐시는 정리."""
    import numpy as np
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(path, track).write_bytes(np.concatenate(stats).astype(np.float32).tobytes())
        files = sorted(CACHE_DIR.glob("*.bin"), key=lambda f: f.stat().st_mtime, reverse=True)
        for f in files[_CACHE_KEEP:]:
            f.unlink(missing_ok=True)
    except OSError:
        pass


def amp(peak, rms):
    """화면에 그릴 진폭 (0~1)."""
    import numpy as np
    return np.clip(np.asarray(peak) * 0.6 + np.asarray(rms) * 2.5, 0.0, 1.0)


def columns(stats, t0, t1, width):
    """t0~t1초를 width개 세로줄로 나눈 줄별 진폭. 한 줄이 조각보다 넓으면 묶고, 좁으면 조각 사이를 이어 그림."""
    import numpy as np
    peak, sq = stats
    n = len(peak)
    out = np.zeros(width, np.float32)
    if n == 0 or width <= 0 or t1 <= t0:
        return out
    px = (t1 - t0) / width
    if px >= STEP_SEC:
        edges = np.floor((t0 + np.arange(width + 1) * px) / STEP_SEC).astype(np.int64)
        lo, hi = np.clip(edges[:-1], 0, n), np.clip(edges[1:], 0, n)
        hi = np.maximum(hi, np.minimum(lo + 1, n))
        ok = lo < hi
        if ok.any():
            starts = lo[ok]
            pk = np.maximum.reduceat(peak, starts)
            s = np.add.reduceat(sq, starts)
            # reduceat은 다음 시작점까지 묶으므로, 줄 끝(hi)이 다음 시작점과 다를 때만 직접 계산
            cnt = np.diff(np.append(starts, n))
            his = hi[ok]
            fix = np.nonzero(starts + cnt != his)[0]
            for i in fix:
                a, b = starts[i], his[i]
                pk[i], s[i], cnt[i] = peak[a:b].max(), sq[a:b].sum(), b - a
            out[ok] = amp(pk, np.sqrt(s / cnt))
        return out
    centers = t0 + (np.arange(width) + 0.5) * px
    a = amp(peak, np.sqrt(sq))
    xs = (np.arange(n) + 0.5) * STEP_SEC
    return np.interp(centers, xs, a, left=0.0, right=0.0).astype(np.float32)


def _av():
    try:
        import av
    except ImportError:
        from .video_deps import load_av
        av = load_av()
        if av is None:
            raise RuntimeError("소리 파일을 읽을 부품(PyAV)이 없어요")
    return av


def track_names(path):
    """파일 안 오디오 트랙 이름 목록 (이름이 없으면 빈 글자). 트랙 수 = 길이."""
    with _av().open(path) as c:
        return [(s.metadata or {}).get("title", "") for s in c.streams.audio]


def extract_waveform(path, track=0):
    """오디오 파일(track번째 오디오 트랙)의 10ms 조각별 (최대값, 제곱평균) 배열 쌍.
    PyAV(ffmpeg)로 16kHz 모노로 디코딩 (mp3·m4a·aac·wav·flac·ogg 모두 길이가 정확하고, 메모리는 조각 통계만 쓴다)."""
    import numpy as np
    av = _av()
    step = 160
    peak, sq = [], []
    carry = np.zeros(0, np.float32)
    with av.open(path) as c:
        res = av.AudioResampler(format="flt", layout="mono", rate=16000)
        for frame in c.decode(audio=track):
            for f in res.resample(frame):
                m = np.concatenate([carry, f.to_ndarray().reshape(-1) * 0.7071])   # ffmpeg 모노 변환은 두 채널 합/√2라 평균 기준으로 맞춤
                k = len(m) // step
                fr = m[:k * step].reshape(k, step)
                peak.append(np.abs(fr).max(axis=1))
                sq.append((fr * fr).mean(axis=1))
                carry = m[k * step:]
    if not peak:
        raise ValueError("읽은 소리가 없어요")
    return np.concatenate(peak).astype(np.float32), np.concatenate(sq).astype(np.float32)