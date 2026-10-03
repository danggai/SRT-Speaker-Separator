"""pygame 기반 미디어 재생."""
import threading
import time


# ─────────────────────────────────────────────
#  미디어 플레이어 (pygame.mixer 기반 — ffmpeg 불필요)
# ─────────────────────────────────────────────
def _ensure_pygame():
    """pygame 미설치 시 자동 pip install."""
    try:
        import pygame
        return pygame
    except ImportError:
        import subprocess, sys
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "pygame", "-q"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        import pygame
        return pygame

def _ensure_mutagen():
    """mutagen 미설치 시 자동 pip install (길이 조회용)."""
    try:
        import mutagen
        return mutagen
    except ImportError:
        import subprocess, sys
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "mutagen", "-q"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        import mutagen
        return mutagen


class MediaPlayer:
    """pygame.mixer 기반 미디어 플레이어 (ffmpeg/ffplay 불필요)."""

    SEEK_DELTA = 5   # 방향키 이동 초

    def __init__(self):
        self._filepath   = None
        self._duration   = 0.0
        self._position   = 0.0
        self._playing    = False
        self._paused     = False
        self._start_wall = 0.0
        self._start_pos  = 0.0
        self._lock       = threading.Lock()
        self._volume     = 100   # 0~100
        self._pg         = None  # pygame 모듈 (lazy init)
        self._watch_thread = None

    def _init_pygame(self):
        if self._pg is not None:
            return True
        try:
            pg = _ensure_pygame()
            if not pg.get_init():
                pg.init()
            if not pg.mixer.get_init():
                # 고품질 설정: 44100Hz, 16bit, stereo, 2048 buffer
                pg.mixer.init(frequency=44100, size=-16, channels=2, buffer=2048)
            self._pg = pg
            return True
        except Exception as e:
            self._pg = None
            return False

    def _get_duration(self, path):
        """mutagen으로 길이 조회 (순수 파이썬, ffprobe 불필요)."""
        try:
            mut = _ensure_mutagen()
            f = mut.File(path)
            if f is not None and hasattr(f, "info") and hasattr(f.info, "length"):
                return float(f.info.length)
        except Exception:
            pass
        # fallback: pygame Sound 로드 후 get_length (메모리 사용 주의)
        try:
            if self._init_pygame():
                snd = self._pg.mixer.Sound(path)
                dur = snd.get_length()
                del snd
                return dur
        except Exception:
            pass
        return 0.0

    # ── 공개 API ──────────────────────────────
    def load(self, path):
        self.stop()
        self._filepath = path
        self._position = 0.0
        if not self._init_pygame():
            self._duration = 0.0
        else:
            self._duration = self._get_duration(path)
        return self._duration

    def play(self):
        if not self._filepath:
            return
        if self._paused:
            self._resume()
            return
        if self._playing:
            return
        self._start_play(self._position)

    def pause(self):
        """토글 pause / resume."""
        if self._playing and not self._paused:
            self._pause()
        else:
            self._resume()

    def stop(self):
        self._playing = False
        self._paused  = False
        self._position = 0.0
        try:
            if self._pg and self._pg.mixer.get_init():
                self._pg.mixer.music.stop()
        except Exception:
            pass

    def seek(self, delta):
        # 재생 중에는 position 프로퍼티로 실제 현재 위치 읽기
        cur = self.position
        new_pos = max(0.0, min(cur + delta, self._duration))
        was_playing = self._playing and not self._paused
        self._stop_music()
        self._position = new_pos
        if was_playing:
            self._start_play(new_pos)

    def seek_to(self, pos):
        new_pos = max(0.0, min(pos, self._duration))
        was_playing = self._playing and not self._paused
        if was_playing:
            # 재생 중엔 set_pos로 즉시 이동 (파일 재로드 없음)
            try:
                self._pg.mixer.music.set_pos(new_pos)
                self._start_wall = time.time()
                self._start_pos  = new_pos
                self._position   = new_pos
                return
            except Exception:
                pass  # set_pos 미지원 포맷이면 fallback
        self._stop_music()
        self._position = new_pos
        if was_playing:
            self._start_play(new_pos)

    @property
    def is_playing(self):
        return self._playing and not self._paused

    @property
    def position(self):
        if self._playing and not self._paused:
            elapsed = time.time() - self._start_wall
            return min(self._start_pos + elapsed, self._duration)
        return self._position

    @property
    def duration(self):
        return self._duration

    # ── 내부 ──────────────────────────────────
    def _start_play(self, start_sec):
        if not self._init_pygame():
            return
        try:
            self._pg.mixer.music.load(self._filepath)
            # set_volume: 0.0~1.0
            self._pg.mixer.music.set_volume(self._volume / 100.0)
            # start_sec 위치부터 재생
            self._pg.mixer.music.play(start=start_sec)
            self._playing    = True
            self._paused     = False
            self._start_wall = time.time()
            self._start_pos  = start_sec

            # 재생 완료 감시 스레드
            self._watch_thread = threading.Thread(
                target=self._watch, daemon=True)
            self._watch_thread.start()
        except Exception:
            self._playing = False

    def _watch(self):
        """재생 완료 감시 — mixer.music.get_busy() 폴링."""
        pg = self._pg
        if not pg:
            return
        while True:
            time.sleep(0.2)
            with self._lock:
                if not self._playing or self._paused:
                    return
                try:
                    busy = pg.mixer.music.get_busy()
                except Exception:
                    busy = False
                if not busy:
                    self._position = self._duration
                    self._playing  = False
                    return

    def _pause(self):
        self._position = self.position
        try:
            if self._pg and self._pg.mixer.get_init():
                self._pg.mixer.music.pause()
        except Exception:
            pass
        self._paused  = True

    def _resume(self):
        if not self._filepath:
            return
        if self._paused:
            try:
                self._pg.mixer.music.unpause()
                self._paused     = False
                self._playing    = True
                self._start_wall = time.time()
                self._start_pos  = self._position
                # resume 후 watch 스레드 재시작
                self._watch_thread = threading.Thread(
                    target=self._watch, daemon=True)
                self._watch_thread.start()
            except Exception:
                self._start_play(self._position)
        elif not self._playing:
            self._start_play(self._position)

    def _stop_music(self):
        self._playing = False
        self._paused  = False
        try:
            if self._pg and self._pg.mixer.get_init():
                self._pg.mixer.music.stop()
        except Exception:
            pass

    def set_volume(self, vol):
        """볼륨 설정 (0~100)."""
        self._volume = max(0, min(vol, 100))
        try:
            if self._pg and self._pg.mixer.get_init():
                self._pg.mixer.music.set_volume(self._volume / 100.0)
        except Exception:
            pass

    def __del__(self):
        self._stop_music()
