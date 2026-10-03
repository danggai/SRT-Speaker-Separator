"""영상 프레임 디코더와 소리 추출 (PyAV). GUI 없음."""
import hashlib
import os
import pathlib
import threading

VIDEO_EXTS = (".mp4", ".mkv", ".avi", ".mov", ".webm")
AUDIO_CACHE = pathlib.Path.home() / ".srt_speaker_editor_cache" / "audio"
_AUDIO_KEEP = 10   # 최근 영상 몇 개의 소리까지 보관


def audio_cache_path(path):
    st = os.stat(path)
    key = f"{os.path.abspath(path)}|{st.st_size}|{int(st.st_mtime)}"
    return AUDIO_CACHE / (hashlib.md5(key.encode("utf-8")).hexdigest() + ".mp3")


def extract_audio(av, path):
    """영상의 소리를 mp3로 뽑아 캐시 경로를 반환 (이미 있으면 그대로)."""
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
        with av.open(str(tmp), "w", format="mp3") as dst:
            ost = dst.add_stream("libmp3lame", rate=44100, layout="stereo")
            ost.bit_rate = 128000
            res = av.AudioResampler(format="s16p", layout="stereo", rate=44100)
            for frame in src.decode(src.streams.audio[0]):
                frame.pts = None
                for rf in res.resample(frame):
                    for pkt in ost.encode(rf):
                        dst.mux(pkt)
            for rf in res.resample(None):
                for pkt in ost.encode(rf):
                    dst.mux(pkt)
            for pkt in ost.encode(None):
                dst.mux(pkt)
    finally:
        src.close()
    os.replace(tmp, out)
    files = sorted(AUDIO_CACHE.glob("*.mp3"), key=lambda f: f.stat().st_mtime, reverse=True)
    for f in files[_AUDIO_KEEP:]:
        f.unlink(missing_ok=True)
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
