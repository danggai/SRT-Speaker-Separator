"""영상 프레임 디코더와 소리 추출 (PyAV). GUI 없음."""
import hashlib
import os
import pathlib
import threading

VIDEO_EXTS = (".mp4", ".mkv", ".avi", ".mov", ".webm")
AUDIO_CACHE = pathlib.Path.home() / ".srt_speaker_editor_cache" / "audio"
_AUDIO_KEEP = 10                 # 최근 몇 개의 재생용 소리까지 보관
_AUDIO_MAX_BYTES = 3 * 1024 ** 3   # 재생용 소리 전체 용량 한도
PLAY_RATE = 22050   # 재생용 소리: 모노 FLAC + 위치 색인 (어디로 이동해도 즉시·소수점까지 정확)
# mp3는 뒤로 갈수록 이동이 느려지고, WAV는 재생 엔진이 시작 위치의 소수점을 버려 최대 1초 늦게 들림
_SEEK_EVERY = 10   # 위치 색인 간격 (초)


def needs_play_audio(path):
    """재생용 소리를 따로 만들어야 하는 파일인가 (이미 만든 재생용 소리면 아님)."""
    return pathlib.Path(path).parent != AUDIO_CACHE


def audio_cache_path(path):
    st = os.stat(path)
    key = f"{os.path.abspath(path)}|{st.st_size}|{int(st.st_mtime)}"
    return AUDIO_CACHE / (hashlib.md5(key.encode("utf-8")).hexdigest() + ".flac")


def _trim_cache(keep):
    """오래된 재생용 소리부터 지워 개수·용량 한도를 맞춘다 (keep은 남김, 예전 형식은 지움)."""
    files = sorted((f for f in AUDIO_CACHE.glob("*") if f.suffix in (".flac", ".wav", ".mp3")),
                   key=lambda f: f.stat().st_mtime, reverse=True)
    total = 0
    for i, f in enumerate(files):
        total += f.stat().st_size
        if f != keep and (f.suffix != ".flac" or i >= _AUDIO_KEEP or total > _AUDIO_MAX_BYTES):
            f.unlink(missing_ok=True)


class PlayAudioWriter:
    """재생용 소리(모노 s16 FLAC) 쓰기. 닫을 때 위치 색인을 넣어 이동이 항상 1ms 안쪽."""

    def __init__(self, av, path, rate=PLAY_RATE):
        self.path, self.rate = str(path), rate
        self._out = av.open(self.path, "w", format="flac")
        self._st = self._out.add_stream("flac", rate=rate, layout="mono")
        self._points, self._off, self._smp, self._next = [], 0, 0, 0

    def _mux(self, pkts):
        for pk in pkts:
            n = pk.duration or 0
            if self._smp >= self._next:   # (첫 샘플, 첫 프레임부터 바이트 위치, 샘플 수)
                self._points.append((self._smp, self._off, n))
                self._next = self._smp + self.rate * _SEEK_EVERY
            self._off += pk.size
            self._smp += n
            self._out.mux(pk)

    def write(self, frame):
        """frame: 모노 s16, rate와 같은 샘플레이트."""
        frame.pts = None
        self._mux(self._st.encode(frame))

    def close(self):
        self._mux(self._st.encode(None))
        self._out.close()
        import mutagen.flac as mf
        f = mf.FLAC(self.path)
        st = mf.SeekTable(None)
        st.seekpoints = [mf.SeekPoint(*p) for p in self._points]
        f.metadata_blocks = [b for b in f.metadata_blocks if not isinstance(b, mf.SeekTable)] + [st]
        f.seektable = st
        f.save()


def extract_audio(av, path):
    """영상·음성의 소리를 재생용 FLAC으로 뽑아 캐시 경로를 반환 (이미 있으면 그대로)."""
    out = audio_cache_path(path)
    if out.exists():
        os.utime(out)
        return str(out)
    AUDIO_CACHE.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".part")
    src = av.open(path)
    try:
        if not src.streams.audio:
            raise RuntimeError("소리가 없는 영상이에요.")
        w = PlayAudioWriter(av, tmp)
        res = av.AudioResampler(format="s16", layout="mono", rate=PLAY_RATE)
        for frame in src.decode(src.streams.audio[0]):
            frame.pts = None
            for rf in res.resample(frame):
                w.write(rf)
        for rf in res.resample(None):
            w.write(rf)
        w.close()
    finally:
        src.close()
    os.replace(tmp, out)
    _trim_cache(out)
    return str(out)


class VideoDecoder:
    """request(시각, 크기)로 요청하면 latest()로 PIL 이미지를 받는다."""

    def __init__(self, av, path):
        self.path = path
        self._container = av.open(path)
        self._stream = self._container.streams.video[0]
        self._stream.thread_type = "AUTO"
        rate = self._stream.average_rate
        self._frame_dur = 1.0 / float(rate) if rate else 1 / 30
        self._iter = None
        self._cur = None          # 지금 보여 주는 프레임
        self._pending = None      # 미리 디코딩한 다음 프레임
        self._target = None       # (요청 키, 시각, (너비, 높이))
        self._done_key = None
        self._result = None       # 새로 뽑은 PIL 이미지
        self._cv = threading.Condition()
        self._closed = False
        threading.Thread(target=self._run, daemon=True).start()

    @property
    def size(self):
        return self._stream.width, self._stream.height

    def request(self, t, size):
        key = (round(t / self._frame_dur), size)
        with self._cv:
            if key == self._done_key or (self._target and self._target[0] == key):
                return
            self._target = (key, t, size)
            self._cv.notify()

    def latest(self):
        """새 이미지가 있으면 반환하고 비움."""
        with self._cv:
            res, self._result = self._result, None
        return res

    def close(self):
        with self._cv:
            self._closed = True
            self._cv.notify()

    def _run(self):
        try:
            while True:
                with self._cv:
                    while self._target is None and not self._closed:
                        self._cv.wait()
                    if self._closed:
                        break
                    key, t, size = self._target
                    self._target = None
                try:
                    img = self._render(t, size)
                except Exception:
                    img = None
                with self._cv:
                    self._done_key = key
                    if img is not None:
                        self._result = img
        finally:
            try:
                self._container.close()
            except Exception:
                pass

    def _seek(self, t):
        tb = self._stream.time_base
        self._container.seek(max(0, int(t / tb)), stream=self._stream, backward=True)
        self._iter = self._container.decode(self._stream)
        self._cur = self._pending = None

    def _frame_at(self, t):
        """t 시각에 보여야 할 프레임 (가까운 앞쪽이면 이어서 디코딩, 멀면 seek)."""
        cur = self._cur
        if cur is not None and cur.time <= t < cur.time + self._frame_dur:
            return cur
        if cur is None or t < cur.time or t > cur.time + 2.0:
            self._seek(t)
            cur = None
        while True:
            nxt, self._pending = self._pending, None
            if nxt is None:
                nxt = next(self._iter, None)
            if nxt is None:   # 영상 끝
                break
            if nxt.time is None:
                continue
            if nxt.time > t + 1e-3:
                if cur is None:
                    cur = nxt
                else:
                    self._pending = nxt
                break
            cur = nxt
        self._cur = cur
        return cur

    def _render(self, t, size):
        f = self._frame_at(t)
        if f is None:
            return None
        w, h = size
        sw, sh = self.size
        scale = min(w / sw, h / sh)
        tw, th = max(2, int(sw * scale)) // 2 * 2, max(2, int(sh * scale)) // 2 * 2
        return f.to_image(width=tw, height=th)
