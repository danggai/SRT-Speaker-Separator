import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog, colorchooser
import subprocess, sys

# ── 필수 패키지 자동 설치 (앱 시작 시 1회) ─────────────────────────────
def _bootstrap_packages():
    """Pillow, tkinterdnd2, pygame, mutagen, librosa 미설치 시 자동 pip install."""
    _REQUIRED = [
        ("PIL",         "Pillow"),
        ("tkinterdnd2", "tkinterdnd2"),
        ("pygame",      "pygame"),
        ("mutagen",     "mutagen"),
        ("librosa",     "librosa"),
        ("soundfile",   "soundfile"),
        ("audioread",   "audioread"),
        ("numpy",       "numpy"),
    ]
    missing = []
    for import_name, pip_name in _REQUIRED:
        try:
            __import__(import_name)
        except ImportError:
            missing.append(pip_name)

    if not missing:
        return

    # 설치 전 사용자 안내 (tkinter 윈도우 띄우기)
    root = tk.Tk()
    root.withdraw()
    ok = messagebox.askyesno(
        "필수 패키지 설치",
        f"다음 패키지가 설치되어 있지 않습니다:\n\n"
        f"  {', '.join(missing)}\n\n"
        "지금 자동으로 설치할까요?\n"
        "(인터넷 연결 필요, 수 분 소요될 수 있습니다)",
        parent=root
    )
    root.destroy()
    if not ok:
        sys.exit(0)

    # 설치 진행 창
    prog_root = tk.Tk()
    prog_root.title("패키지 설치 중...")
    prog_root.geometry("380x110")
    prog_root.resizable(False, False)
    lbl = tk.Label(prog_root, text="설치 준비 중...", font=("", 10), pady=16)
    lbl.pack()
    bar = ttk.Progressbar(prog_root, mode="indeterminate", length=320)
    bar.pack()
    bar.start(10)
    prog_root.update()

    errors = []
    for i, pkg in enumerate(missing):
        lbl.configure(text=f"설치 중: {pkg}  ({i+1}/{len(missing)})")
        prog_root.update()
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", pkg, "-q"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except subprocess.CalledProcessError:
            # --user 재시도
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", pkg, "-q", "--user"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            except subprocess.CalledProcessError as e:
                errors.append(pkg)

    bar.stop()
    prog_root.destroy()

    if errors:
        root2 = tk.Tk()
        root2.withdraw()
        messagebox.showerror(
            "설치 실패",
            f"다음 패키지 설치에 실패했습니다:\n{', '.join(errors)}\n\n"
            "수동으로 설치 후 다시 실행해주세요:\n"
            f"pip install {' '.join(errors)}",
            parent=root2
        )
        root2.destroy()
        sys.exit(1)

    # 설치 완료 → 재시작
    root3 = tk.Tk()
    root3.withdraw()
    messagebox.showinfo("설치 완료",
        "패키지 설치가 완료됐습니다.\n앱을 재시작합니다.",
        parent=root3)
    root3.destroy()
    _frozen = getattr(sys, "frozen", False)
    if _frozen:
        subprocess.Popen([sys.executable])
    else:
        subprocess.Popen([sys.executable] + sys.argv)
    sys.exit(0)

_bootstrap_packages()
# ─────────────────────────────────────────────────────────────────────────

import re
import os
import copy
from collections import defaultdict
import threading
import subprocess
import sys
import time
import urllib.request
import json
import pathlib

# ── 앱 설정 저장/불러오기 ─────────────────────────────────
_CONFIG_PATH = pathlib.Path.home() / ".srt_speaker_editor_config.json"
_MAX_RECENT_TOKENS = 5

def _load_config() -> dict:
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save_config(cfg: dict):
    try:
        _CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

def _add_recent_token(cfg: dict, token: str):
    """최근 토큰 목록에 추가 (최대 _MAX_RECENT_TOKENS개, 중복 제거)."""
    if not token:
        return cfg
    recent = cfg.get("recent_tokens", [])
    if token in recent:
        recent.remove(token)
    recent.insert(0, token)
    cfg["recent_tokens"] = recent[:_MAX_RECENT_TOKENS]
    return cfg


# ─────────────────────────────────────────────
#  색상 팔레트 (화자별 자동 배정)
# ─────────────────────────────────────────────
SPEAKER_COLORS = [
    "#4A90E2", "#E25C5C", "#50C878", "#F5A623",
    "#9B59B6", "#1ABC9C", "#E67E22", "#E91E8C",
    "#00BCD4", "#8BC34A",
]

BG        = "#1A1A1A"
BG2       = "#141414"
BG3       = "#242424"
ACCENT    = "#9B7FD4"   # 연보라 포인트
FG        = "#E0E0E0"
FG_DIM    = "#777777"
BORDER    = "#333333"
ROW_ODD   = "#1E1E1E"
ROW_EVEN  = "#1A1A1A"
ROW_SEL   = "#2D2040"   # 선택 시 연보라 tint (Treeview용)
ROW_HL    = "#221A35"   # 행 하이라이트 배경 (아주 연한 보라)
MEDIA_BG  = "#111111"

# ─────────────────────────────────────────────
#  전역 설정 (화자 구분 패턴)
#  저장 형식:  [화자명] 자막내용
#  패턴 표기:  [%] &   (% = 화자, & = 내용)
#  예시: [Alice] 안녕하세요  →  화자=Alice, 내용=안녕하세요
# ─────────────────────────────────────────────
DEFAULT_SPEAKER_PATTERN = r"^\[([^\]]+)\]\s*"
g_speaker_pattern = DEFAULT_SPEAKER_PATTERN

# 사용자에게 보여주는 표시 패턴 (% = 화자명, & = 자막내용)
DEFAULT_DISPLAY_PATTERN = "[%] &"
g_display_pattern = DEFAULT_DISPLAY_PATTERN


def display_to_regex(display: str) -> str:
    """
    사용자 표시 패턴(% = 화자명, & = 자막내용)을 내부 정규식으로 변환.
    % → 첫 번째 캡처 그룹 (.+?), & → 나머지 내용 (무시, 패턴 끝)
    """
    # % 와 & 위치 찾기
    pct = display.find('%')
    amp = display.find('&')
    if pct < 0:
        raise ValueError("패턴에 % (화자명 위치)가 없습니다.")

    # % 앞 부분을 regex 이스케이프, % → (.+?), & 이전까지 구분자 이스케이프
    prefix = display[:pct]
    if amp >= 0 and amp > pct:
        between = display[pct + 1:amp]
    else:
        between = display[pct + 1:]

    regex = "^" + re.escape(prefix) + r"([^\n]+?)" + re.escape(between.rstrip()) + r"\s*"
    return regex


def _pick_font(root=None):
    """시스템에서 한글 지원 폰트를 찾아 반환.
    root가 주어지면 해당 Tk 인스턴스 기준으로 폰트 목록 조회 (빈 창 없음).
    root가 없으면 후보 목록을 이름만으로 반환 (OS별 기본값 우선)."""
    if root is not None:
        try:
            import tkinter.font as tkfont
            available = set(tkfont.families(root))
        except Exception:
            available = set()
    else:
        # 창을 띄우지 않고 OS 기반 우선순위만 사용
        available = set()

    candidates = [
        "Malgun Gothic",       # Windows 기본 한글
        "맑은 고딕",
        "Apple SD Gothic Neo", # macOS 기본 한글
        "AppleGothic",
        "Nanum Gothic",
        "NanumGothic",
        "NotoSansCJKkr",
        "Noto Sans CJK KR",
        "UnDotum",             # Linux 한글
        "Gulim",
        "Segoe UI",
        "TkDefaultFont",
    ]
    if available:
        for f in candidates:
            if f in available:
                return f
    # 창 없이 호출된 경우: OS 추측
    import sys
    if sys.platform == "win32":
        return "Malgun Gothic"
    if sys.platform == "darwin":
        return "Apple SD Gothic Neo"
    return "TkDefaultFont"

# 모듈 로드 시점에는 창을 띄우지 않고 OS 기본값으로 초기화
# 실제 앱 시작 후 _init_font()에서 정확한 값으로 교체됨
FONT_FAMILY = _pick_font(root=None)
FONT_MONO   = "Courier New"

# ─────────────────────────────────────────────
#  SRT 파싱 / 저장
# ─────────────────────────────────────────────
def parse_srt(filepath, pattern=None):
    global g_speaker_pattern
    pat = pattern if pattern is not None else g_speaker_pattern
    with open(filepath, "r", encoding="utf-8-sig") as f:
        content = f.read()
    blocks = re.split(r"\n\s*\n", content.strip())
    subs = []
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        timestamp = lines[1].strip()
        text = "\n".join(lines[2:]).strip()
        try:
            match = re.match(pat, text)
        except re.error:
            match = None
        if match and match.lastindex and match.lastindex >= 1:
            speaker = match.group(1).strip()
            clean   = text[match.end():].strip()
        else:
            speaker = ""
            clean   = text
        subs.append({"timestamp": timestamp, "text": clean, "speaker": speaker})
    return subs


def write_srt(subtitles, filepath):
    lines = []
    for i, sub in enumerate(subtitles, start=1):
        lines.append(str(i))
        lines.append(sub["timestamp"])
        lines.append(sub["text"])
        lines.append("")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_srt_tagged(subtitles, filepath, meta: dict = None):
    global g_display_pattern
    lines = []
    for i, sub in enumerate(subtitles, start=1):
        lines.append(str(i))
        lines.append(sub["timestamp"])
        spk  = sub.get("speaker", "")
        text = sub.get("text", "")
        if spk:
            # 표시 패턴 적용: % → 화자명, & → 내용
            tagged = g_display_pattern.replace("%", spk).replace("&", text)
        else:
            tagged = text
        lines.append(tagged)
        lines.append("")
    if meta:
        lines.append(f"; SRT_META {json.dumps(meta, ensure_ascii=False)}")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


_META_RE = re.compile(r"^;\s*SRT_META\s+(\{.*\})\s*$")

def read_srt_meta(filepath) -> dict:
    """SRT 파일 끝의 ; SRT_META {...} 줄을 읽어 dict 반환. 없으면 {}."""
    try:
        with open(filepath, "r", encoding="utf-8-sig") as f:
            for line in reversed(f.readlines()):
                line = line.rstrip()
                if not line:
                    continue
                m = _META_RE.match(line)
                if m:
                    return json.loads(m.group(1))
                break   # 마지막 비어있지 않은 줄이 메타가 아니면 없는 것
    except Exception:
        pass
    return {}


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


# ─────────────────────────────────────────────
#  툴팁
# ─────────────────────────────────────────────
class Tooltip:
    """위젯에 마우스오버 힌트를 표시하는 경량 툴팁."""
    _instance = None   # 동시에 하나만 표시

    def __init__(self, widget, text, delay=500):
        self._widget  = widget
        self._text    = text
        self._delay   = delay
        self._job     = None
        self._tip_win = None
        widget.bind("<Enter>",  self._on_enter, add=True)
        widget.bind("<Leave>",  self._on_leave, add=True)
        widget.bind("<Button>", self._on_leave, add=True)

    def _on_enter(self, e):
        self._cancel()
        self._job = self._widget.after(self._delay, self._show)

    def _on_leave(self, e):
        self._cancel()
        self._hide()

    def _cancel(self):
        if self._job:
            try:
                self._widget.after_cancel(self._job)
            except Exception:
                pass
            self._job = None

    def _show(self):
        if Tooltip._instance and Tooltip._instance is not self:
            Tooltip._instance._hide()
        Tooltip._instance = self
        x = self._widget.winfo_rootx() + 10
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 4
        self._tip_win = tw = tk.Toplevel(self._widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tw.attributes("-topmost", True)
        outer = tk.Frame(tw, bg=BORDER, bd=0)
        outer.pack()
        tk.Label(outer, text=self._text,
                 bg="#252535", fg="#CCCCDD",
                 font=(FONT_FAMILY, 9),
                 padx=8, pady=5,
                 justify="left",
                 relief="flat").pack()

    def _hide(self):
        if self._tip_win:
            try:
                self._tip_win.destroy()
            except Exception:
                pass
            self._tip_win = None
        if Tooltip._instance is self:
            Tooltip._instance = None


# ─────────────────────────────────────────────
#  커스텀 컬러피커
# ─────────────────────────────────────────────
class _ColorPickerDialog:
    """HSV 팔레트 + 밝기 슬라이더 + Hex 입력으로 구성된 커스텀 컬러피커."""

    SZ   = 200   # 팔레트 크기
    BH   = 20    # 밝기 슬라이더 높이

    def __init__(self, parent, initial_color="#9B7FD4", title="색상 선택"):
        self._parent  = parent
        self._result  = None
        self._title   = title
        self._h, self._s, self._v = self._hex_to_hsv(initial_color)

    # ── 공개 API ─────────────────────────────
    def show(self):
        self._build()
        self._parent.wait_window(self._win)
        return self._result

    # ── UI 빌드 ──────────────────────────────
    def _build(self):
        win = tk.Toplevel(self._parent)
        self._win = win
        win.title(self._title)
        win.resizable(False, False)
        win.configure(bg=BG2)
        win.grab_set()
        win.transient(self._parent)

        pad = tk.Frame(win, bg=BG2)
        pad.pack(padx=16, pady=14)

        # HSV 팔레트 캔버스
        sz = self.SZ
        self._pal = tk.Canvas(pad, width=sz, height=sz,
                              highlightthickness=1, highlightbackground=BORDER,
                              cursor="crosshair")
        self._pal.pack()
        self._draw_palette()

        # 팔레트 클릭/드래그
        self._pal.bind("<ButtonPress-1>",  self._pal_click)
        self._pal.bind("<B1-Motion>",       self._pal_click)

        # 밝기(V) 슬라이더
        bh = self.BH
        self._bsl = tk.Canvas(pad, width=sz, height=bh,
                              highlightthickness=1, highlightbackground=BORDER,
                              cursor="sb_h_double_arrow")
        self._bsl.pack(pady=(6, 0))
        self._draw_brightness()
        self._bsl.bind("<ButtonPress-1>",  self._bsl_click)
        self._bsl.bind("<B1-Motion>",       self._bsl_click)

        # 미리보기 + Hex 입력
        bot = tk.Frame(pad, bg=BG2)
        bot.pack(fill="x", pady=(10, 0))

        self._preview = tk.Canvas(bot, width=44, height=30,
                                  highlightthickness=1, highlightbackground=BORDER)
        self._preview.pack(side="left", padx=(0, 10))

        tk.Label(bot, text="#", bg=BG2, fg=FG,
                 font=(FONT_FAMILY, 11, "bold")).pack(side="left")
        self._hex_var = tk.StringVar()
        self._hex_entry = tk.Entry(bot, textvariable=self._hex_var,
                                   width=7, bg=BG3, fg=FG,
                                   insertbackground=FG,
                                   font=(FONT_MONO, 11),
                                   relief="flat",
                                   highlightthickness=1,
                                   highlightbackground=BORDER,
                                   highlightcolor=ACCENT)
        self._hex_entry.pack(side="left")
        self._hex_var.trace_add("write", self._on_hex_type)
        self._hex_entry.bind("<Return>", lambda e: self._on_hex_commit())

        # 버튼
        btn_row = tk.Frame(pad, bg=BG2)
        btn_row.pack(fill="x", pady=(12, 0))
        tk.Button(btn_row, text="확인",
                  bg=ACCENT, fg="white", relief="flat", bd=0,
                  font=(FONT_FAMILY, 10, "bold"), padx=18, pady=6,
                  cursor="hand2", activebackground="#7B5FB4",
                  command=self._ok).pack(side="right", padx=(6, 0))
        tk.Button(btn_row, text="취소",
                  bg=BG3, fg=FG_DIM, relief="flat", bd=0,
                  font=(FONT_FAMILY, 10), padx=14, pady=6,
                  cursor="hand2", activebackground=BORDER,
                  command=win.destroy).pack(side="right")

        self._refresh()

        # 화면 중앙 배치
        win.update_idletasks()
        pw = self._parent.winfo_rootx() + self._parent.winfo_width() // 2
        ph = self._parent.winfo_rooty() + self._parent.winfo_height() // 2
        ww, wh = win.winfo_width(), win.winfo_height()
        win.geometry(f"+{pw - ww//2}+{ph - wh//2}")

    # ── 팔레트 그리기 (H=x, S=y, V=고정) ────
    def _draw_palette(self):
        sz  = self.SZ
        img_data = []
        for row in range(sz):
            s = 1.0 - row / (sz - 1)
            row_pixels = []
            for col in range(sz):
                h = col / (sz - 1)
                r, g, b = self._hsv2rgb(h, s, self._v)
                row_pixels.append(f"#{r:02x}{g:02x}{b:02x}")
            img_data.append("{" + " ".join(row_pixels) + "}")
        self._pal_img = tk.PhotoImage(width=sz, height=sz)
        self._pal_img.put(" ".join(img_data))
        self._pal.delete("all")
        self._pal.create_image(0, 0, anchor="nw", image=self._pal_img)

    def _draw_brightness(self):
        sz = self.SZ; bh = self.BH
        self._bsl.delete("all")
        for x in range(sz):
            v   = x / (sz - 1)
            r, g, b = self._hsv2rgb(self._h, self._s, v)
            self._bsl.create_line(x, 0, x, bh, fill=f"#{r:02x}{g:02x}{b:02x}")

    def _draw_cursor(self):
        sz = self.SZ; bh = self.BH
        self._pal.delete("cursor")
        cx = int(self._h * (sz - 1))
        cy = int((1.0 - self._s) * (sz - 1))
        r  = 6
        self._pal.create_oval(cx-r, cy-r, cx+r, cy+r,
                              outline="white", width=2, tags="cursor")
        self._pal.create_oval(cx-r+1, cy-r+1, cx+r-1, cy+r-1,
                              outline="black", width=1, tags="cursor")
        # 밝기 슬라이더 핸들
        self._bsl.delete("handle")
        bx = int(self._v * (sz - 1))
        self._bsl.create_line(bx, 0, bx, bh,
                              fill="white", width=2, tags="handle")

    # ── 이벤트 ───────────────────────────────
    def _pal_click(self, e):
        sz = self.SZ
        self._h = max(0.0, min(1.0, e.x / (sz - 1)))
        self._s = max(0.0, min(1.0, 1.0 - e.y / (sz - 1)))
        self._refresh()

    def _bsl_click(self, e):
        self._v = max(0.0, min(1.0, e.x / (self.SZ - 1)))
        self._draw_palette()
        self._refresh()

    def _on_hex_type(self, *_):
        val = self._hex_var.get().strip().lstrip("#")
        if len(val) == 6:
            try:
                r = int(val[0:2], 16)
                g = int(val[2:4], 16)
                b = int(val[4:6], 16)
                self._h, self._s, self._v = self._rgb2hsv(r, g, b)
                self._draw_palette()
                self._draw_brightness()
                self._draw_cursor()
                self._update_preview()
            except ValueError:
                pass

    def _on_hex_commit(self):
        self._on_hex_type()

    def _ok(self):
        r, g, b = self._hsv2rgb(self._h, self._s, self._v)
        self._result = f"#{r:02x}{g:02x}{b:02x}"
        self._win.destroy()

    # ── 통합 갱신 ────────────────────────────
    def _refresh(self):
        self._draw_brightness()
        self._draw_cursor()
        self._update_preview()
        r, g, b = self._hsv2rgb(self._h, self._s, self._v)
        self._hex_var.trace_remove("write",
            self._hex_var.trace_info()[0][1] if self._hex_var.trace_info() else "")
        self._hex_var.set(f"{r:02x}{g:02x}{b:02x}")
        self._hex_var.trace_add("write", self._on_hex_type)

    def _update_preview(self):
        r, g, b = self._hsv2rgb(self._h, self._s, self._v)
        color = f"#{r:02x}{g:02x}{b:02x}"
        self._preview.delete("all")
        self._preview.configure(bg=color)
        self._preview.create_rectangle(0, 0, 44, 30, fill=color, outline="")

    # ── 색상 변환 헬퍼 ───────────────────────
    @staticmethod
    def _hsv2rgb(h, s, v):
        import colorsys
        r, g, b = colorsys.hsv_to_rgb(h, s, v)
        return int(r*255), int(g*255), int(b*255)

    @staticmethod
    def _rgb2hsv(r, g, b):
        return colorsys.rgb_to_hsv(r/255, g/255, b/255)

    @staticmethod
    def _hex_to_hsv(hex_color):
        hex_color = hex_color.lstrip("#")
        try:
            r = int(hex_color[0:2], 16)
            g = int(hex_color[2:4], 16)
            b = int(hex_color[4:6], 16)
        except (ValueError, IndexError):
            return 0.6, 0.5, 0.8
        return colorsys.rgb_to_hsv(r/255, g/255, b/255)


# ─────────────────────────────────────────────
#  버전 정보
# ─────────────────────────────────────────────
APP_VERSION      = "0.1.0"   # 현재 버전 (릴리즈 태그와 맞춰 관리)
GITHUB_TAGS_URL  = "https://github.com/danggai/SRT-Speaker-Separator/tags"
GITHUB_LATEST_API = "https://api.github.com/repos/danggai/SRT-Speaker-Separator/tags"

# ─────────────────────────────────────────────
#  메인 앱
# ─────────────────────────────────────────────
class SRTEditor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SRT Speaker Editer")
        self.geometry("1200x820")
        self.minsize(900, 620)
        self.configure(bg=BG)

        # 앱 창이 생성된 후 정확한 폰트 탐지 (빈 창 없음)
        global FONT_FAMILY
        FONT_FAMILY = _pick_font(root=self)

        self.subtitles      = []
        self.speakers       = []
        self.speaker_colors = {}   # 화자명 → 사용자 지정 색상 (없으면 팔레트 자동 배정)
        self.filepath   = None
        self.save_path  = None
        self.edited_row = None
        self._last_focused_idx = None
        self._unsaved   = False   # 미저장 변경사항 추적

        # Undo / Redo 스택  (각 항목: (subtitles_deepcopy, speakers_copy))
        self._undo_stack = []
        self._redo_stack = []
        self._clipboard  = None   # 잘라내기/복사한 자막 dict

        # 미디어 플레이어
        self.player      = MediaPlayer()
        self.media_path  = None
        self._seek_job   = None   # after job for progress polling
        self._playing_rows: set = set()
        self._ts_cache: list = []
        self._last_polled_pos: float = -1.0
        self._wf_zoom:   float = 1.0
        self._wf_offset: float = 0.0
        self._selected_rows: set = set()   # 다중 선택 인덱스 집합

        # 설정 불러오기
        _cfg = _load_config()
        self._hf_token             = _cfg.get("hf_token", "")
        self._diarize_num_spk_val  = _cfg.get("num_speakers", 0)
        self._diarize_mode_init    = _cfg.get("diarize_mode", "balanced")
        self._diarize_device_init  = _cfg.get("diarize_device", "auto")
        self._recent_tokens        = _cfg.get("recent_tokens", [])
        self._diarize_batch_init  = _cfg.get("diarize_batch", 3)   # index=3 → batch=16 (권장)

        self._build_styles()
        self._build_ui()
        self._setup_dnd()        # 드래그 앤 드롭

        # 업데이트 체크 (백그라운드, 앱 시작 3초 후)
        self.after(3000, self._check_update_async)

        # 단축키
        self.bind("<Control-s>", lambda e: self.save_file())
        self.bind("<Control-S>", lambda e: self.save_file_as())
        self.bind("<Control-o>", lambda e: self.open_file())
        self.bind("<space>",     self._on_space_key)
        self.bind("<Left>",       self._on_left_key)
        self.bind("<Right>",      self._on_right_key)
        self.bind("<Shift-Left>",  self._on_left_key)
        self.bind("<Shift-Right>", self._on_right_key)
        self.bind("<Control-z>", lambda e: self._undo())
        self.bind("<Control-Z>", lambda e: self._redo())
        self.bind("<Control-x>", self._on_cut)
        self.bind("<Control-c>", self._on_copy)
        self.bind("<Control-v>", self._on_paste)
        self.bind("<Delete>",    self._on_delete)
        self.bind("<Control-d>", self._on_delete)
        self.bind("<Up>",        self._on_arrow_up)
        self.bind("<Down>",      self._on_arrow_down)
        self.bind("<grave>",     self._on_speaker_key)
        for _k in "123456789":
            self.bind(_k, self._on_speaker_key)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── 스타일 ────────────────────────────────
    def _build_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure("TFrame",       background=BG)
        style.configure("Side.TFrame",  background=BG2)
        style.configure("Top.TFrame",   background=BG3)
        style.configure("Media.TFrame", background=MEDIA_BG)

        style.configure("TLabel",
            background=BG, foreground=FG,
            font=(FONT_FAMILY, 10))
        style.configure("Dim.TLabel",
            background=BG2, foreground=FG_DIM,
            font=(FONT_FAMILY, 9))
        style.configure("MediaDim.TLabel",
            background=MEDIA_BG, foreground=FG_DIM,
            font=(FONT_FAMILY, 9))
        style.configure("Title.TLabel",
            background=BG3, foreground=FG,
            font=(FONT_FAMILY, 13, "bold"))
        style.configure("Header.TLabel",
            background=BG2, foreground=FG_DIM,
            font=(FONT_FAMILY, 9, "bold"))

        style.configure("Accent.TButton",
            background=ACCENT, foreground="white",
            font=(FONT_FAMILY, 10, "bold"),
            borderwidth=0, relief="flat", padding=(12, 6))
        style.map("Accent.TButton",
            background=[("active", "#7B5FB4"), ("pressed", "#5B3F94")])

        style.configure("Ghost.TButton",
            background=BG2, foreground=FG,
            font=(FONT_FAMILY, 9),
            borderwidth=1, relief="flat", padding=(8, 4))
        style.map("Ghost.TButton",
            background=[("active", BG3), ("pressed", BORDER)])

        # 아이콘 전용 버튼 — 텍스트 없이 아이콘만, 정사각형에 가깝게
        style.configure("Icon.TButton",
            background=BG2, foreground=FG,
            font=(FONT_FAMILY, 10),
            borderwidth=0, relief="flat", padding=(2, 2))
        style.map("Icon.TButton",
            background=[("active", BG3), ("pressed", BORDER)])

        style.configure("Media.TButton",
            background=BG3, foreground=FG,
            font=(FONT_FAMILY, 11),
            borderwidth=0, relief="flat", padding=(10, 5))
        style.map("Media.TButton",
            background=[("active", "#333333"), ("pressed", "#111111")])

        style.configure("MediaPlay.TButton",
            background=ACCENT, foreground="white",
            font=(FONT_FAMILY, 14, "bold"),
            borderwidth=0, relief="flat", padding=(12, 6))
        style.map("MediaPlay.TButton",
            background=[("active", "#7B5FB4")])

        style.configure("Danger.TButton",
            background="#2A1A2A", foreground="#FF6B8A",
            font=(FONT_FAMILY, 9),
            borderwidth=0, relief="flat", padding=(8, 4))
        style.map("Danger.TButton",
            background=[("active", "#3A1A2A")])

        style.configure("Subs.Treeview",
            background=ROW_EVEN, fieldbackground=ROW_EVEN,
            foreground=FG, rowheight=36,
            font=(FONT_FAMILY, 10), borderwidth=0)
        style.configure("Subs.Treeview.Heading",
            background=BG2, foreground=FG_DIM,
            font=(FONT_FAMILY, 9, "bold"),
            relief="flat", borderwidth=0)
        style.map("Subs.Treeview",
            background=[("selected", ROW_SEL)],
            foreground=[("selected", FG)])

        style.configure("TEntry",
            fieldbackground=BG3, foreground=FG,
            insertcolor=FG, borderwidth=1)

        style.configure("TScrollbar",
            background=BG2, troughcolor=BG,
            arrowcolor=FG_DIM, borderwidth=0)

        style.configure("Media.Horizontal.TProgressbar",
            troughcolor=BG3, background=ACCENT,
            borderwidth=0, lightcolor=ACCENT, darkcolor=ACCENT)

    # ── UI 구성 ───────────────────────────────
    def _build_ui(self):
        # 상단 툴바
        top = ttk.Frame(self, style="Top.TFrame")
        top.pack(fill="x")
        self._top_bar = top   # 업데이트 배지 삽입용

        # ── 파일 메뉴 버튼 (컴팩트 아이콘) ──
        file_menu = tk.Menu(top, tearoff=0,
                            bg=BG3, fg=FG,
                            activebackground=ACCENT,
                            activeforeground="white",
                            disabledforeground=FG_DIM,
                            relief="flat", bd=0,
                            activeborderwidth=0,
                            font=(FONT_FAMILY, 9))
        file_menu.add_command(label="  열기             Ctrl+O", command=self.open_file)
        file_menu.add_separator()
        file_menu.add_command(label="  저장             Ctrl+S", command=self.save_file)
        file_menu.add_command(label="  다른 이름으로 저장",      command=self.save_file_as)

        _file_wrap = tk.Frame(top, bg=BG3,
                              highlightthickness=1, highlightbackground=BORDER)
        _file_wrap.pack(side="left", padx=(8, 0), pady=10)

        def _show_file_menu(e=None):
            w = _file_wrap
            file_menu.post(w.winfo_rootx(), w.winfo_rooty() + w.winfo_height())

        _file_btn = tk.Button(_file_wrap, text="📁  파일",
                              bg=BG3, fg=FG, relief="flat", bd=0,
                              font=(FONT_FAMILY, 10), padx=7, pady=2,
                              cursor="hand2", takefocus=0,
                              activebackground=BG2, activeforeground=FG,
                              command=_show_file_menu)
        _file_btn.pack(side="left")
        Tooltip(_file_btn, "파일  열기 / 저장", delay=500)

        tk.Frame(top, bg=BORDER, width=1).pack(side="left", fill="y", padx=8, pady=6)

        # ── 아이콘 전용 버튼 ──────────────────
        def _defocus(fn):
            """버튼 실행 후 포커스를 루트로 돌려 스페이스바 재실행 방지."""
            def wrapper(*a, **k):
                fn(*a, **k)
                self.focus_set()
            return wrapper

        def _mini_btn(parent, text, cmd, tip):
            b = tk.Button(parent, text=text, command=cmd,
                          bg=BG3, fg=FG, relief="flat", bd=0,
                          font=(FONT_FAMILY, 10), padx=7, pady=2,
                          cursor="hand2", takefocus=0,
                          activebackground=BG2, activeforeground=FG)
            b.pack(side="left")
            # 버튼 사이 구분선
            Tooltip(b, tip, delay=500)
            return b

        # 콤팩트 버튼 그룹 (자막추가 / 실행취소 / 다시실행)
        _btn_group = tk.Frame(top, bg=BG3,
                              highlightthickness=1, highlightbackground=BORDER)
        _btn_group.pack(side="left", padx=(0, 4), pady=10)

        _mini_btn(_btn_group, "＋",
                  _defocus(lambda: self.add_row(getattr(self, "_last_focused_idx", None))),
                  "자막 추가  [Ctrl+Enter]")
        tk.Frame(_btn_group, bg=BORDER, width=1).pack(side="left", fill="y", pady=3)
        _mini_btn(_btn_group, "↩",
                  _defocus(self._undo),
                  "실행 취소  [Ctrl+Z]")
        tk.Frame(_btn_group, bg=BORDER, width=1).pack(side="left", fill="y", pady=3)
        _mini_btn(_btn_group, "↪",
                  _defocus(self._redo),
                  "다시 실행  [Ctrl+Y]")

        tk.Frame(top, bg=BORDER, width=1).pack(side="left", fill="y", padx=8, pady=6)

        # 업데이트 배지 — 처음엔 숨겨둠, 신버전 감지 시 pack으로 표시
        import webbrowser as _wb_top
        self._update_btn = tk.Button(
            top, text="🆕  새로운 버전!",
            bg="#1E3A1E", fg="#4CAF50",
            relief="flat", bd=0, cursor="hand2",
            font=(FONT_FAMILY, 9, "bold"),
            padx=10, pady=4,
            activebackground="#162E16", activeforeground="#6FCF6F"
        )
        # 처음엔 숨김 — 신버전 감지 시 command 설정 후 pack
        self._update_badge_anchor = top
        self._update_badge_latest = None

        # ── 우측 버튼 그룹 ───────────────────────────
        def _right_group(*items):
            """(text, cmd, tip) 목록으로 컴팩트 버튼 그룹 생성."""
            grp = tk.Frame(top, bg=BG3,
                           highlightthickness=1, highlightbackground=BORDER)
            grp.pack(side="right", padx=(0, 6), pady=10)
            for i, (text, cmd, tip) in enumerate(items):
                if i > 0:
                    tk.Frame(grp, bg=BORDER, width=1).pack(side="left", fill="y", pady=3)
                b = tk.Button(grp, text=text, command=cmd,
                              bg=BG3, fg=FG, relief="flat", bd=0,
                              font=(FONT_FAMILY, 10), padx=8, pady=2,
                              cursor="hand2", takefocus=0,
                              activebackground=BG2, activeforeground=FG)
                b.pack(side="left")
                Tooltip(b, tip, delay=500)
            return grp

        # 미지정 카운터
        self.lbl_count = tk.Label(top, text="", bg=BG3,
                                  fg="#FF9A5C", cursor="hand2",
                                  font=(FONT_FAMILY, 9))
        self.lbl_count.pack(side="right", padx=(0, 4), pady=8)
        self.lbl_count.bind("<Button-1>", lambda e: self._goto_next_unassigned())

        _right_group(("⚙", self._open_settings, "설정"))
        _right_group(
            ("📤  내보내기", self.export, "화자별 자막 내보내기"),
        )
        _right_group(
            ("🎙  화자 분석", self._open_diarize_dialog, "화자 자동 분석"),
        )

        # 본문 영역 (사이드바 + 테이블)
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)

        self._build_sidebar(body)
        right_col = ttk.Frame(body)
        right_col.pack(side="left", fill="both", expand=True)

        self._build_table(right_col)
        self._build_media_panel(right_col)
        self.after(200, self._attach_tooltips)

        # 파일 없을 때 드롭 오버레이
        self._build_drop_overlay()

        # 어디를 클릭해도 content Entry 포커스/하이라이트 해제
        # (단, Entry 자체 클릭은 제외 — tkinter가 자동으로 포커스를 줌)
        self.bind_all("<Button-1>", self._on_global_click, add=True)

    # ── 드롭 존 오버레이 ─────────────────────
    def _build_drop_overlay(self):
        """파일 미로드 상태에서 보이는 드래그앤드롭 안내 오버레이"""
        self.overlay = tk.Frame(self, bg=BG, cursor="hand2")
        self.overlay.place(relx=0, rely=0, relwidth=1, relheight=1)

        # 중앙 카드
        card = tk.Frame(self.overlay, bg=BG2, padx=60, pady=50,
                        highlightbackground=BORDER, highlightthickness=2)
        card.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(card, text="📄", bg=BG2, fg=FG,
                 font=(FONT_FAMILY, 48)).pack(pady=(0, 8))
        tk.Label(card, text="SRT 파일을 여기에 드래그하세요",
                 bg=BG2, fg=FG, font=(FONT_FAMILY, 16, "bold")).pack()
        tk.Label(card, text="또는",
                 bg=BG2, fg=FG_DIM, font=(FONT_FAMILY, 11)).pack(pady=8)

        btn_open = tk.Button(card, text="📂  파일 열기",
                             bg=ACCENT, fg="white",
                             font=(FONT_FAMILY, 12, "bold"),
                             relief="flat", padx=20, pady=10,
                             cursor="hand2",
                             command=self.open_file,
                             activebackground="#c73550", activeforeground="white")
        btn_open.pack(pady=(0, 4))

        tk.Label(card, text="지원: .srt",
                 bg=BG2, fg=FG_DIM, font=(FONT_FAMILY, 9)).pack(pady=(8, 0))

    def _hide_overlay(self):
        self.overlay.place_forget()

    def _show_overlay(self):
        self.overlay.place(relx=0, rely=0, relwidth=1, relheight=1)

    # ── 드래그 앤 드롭 설정 ──────────────────
    def _attach_tooltips(self):
        """주요 위젯에 마우스오버 툴팁을 붙임."""
        T = Tooltip

        # ── 재생 컨트롤 ──────────────────────
        T(self.btn_stop, "처음으로 이동  [⏮]")
        T(self.btn_prev, "재생 중: 이전 자막으로  [←]\n정지 중: -5초 이동  [←]")
        T(self.btn_play, "재생 / 일시정지  [Space]")
        T(self.btn_next, "재생 중: 다음 자막으로  [→]\n정지 중: +5초 이동  [→]")
        T(self._vol_icon,   "음소거 토글  (클릭)")
        T(self._vol_canvas, "볼륨 조절  (드래그)\n현재: " + str(self._vol_var) + "%")
        T(self._pb_canvas,  "재생 위치 이동  (클릭/드래그)")
        T(self.lbl_pos, "현재 재생 위치")
        T(self.lbl_dur, "총 재생 시간")
        T(self.lbl_media, "미디어 파일 드래그 또는 버튼으로 불러오기\n지원: mp3, mp4, wav, m4a 등")

        # ── 헤더 / 카운터 ─────────────────────
        T(self._hdr_canvas, "컬럼 경계를 좌우로 드래그해 너비 조절")
        T(self.lbl_count,   "미배정 자막 수\n클릭 → 다음 미배정 자막으로 이동")

    def _setup_dnd(self):
        """tkinterdnd2가 있으면 DnD, 없으면 조용히 무시"""
        try:
            from tkinterdnd2 import DND_FILES, TkinterDnD
            self._dnd_enabled = True
            self._dnd_register(DND_FILES)
        except Exception:
            self._dnd_enabled = False
            self._setup_dnd_fallback()

    def _dnd_register(self, DND_FILES):
        """tkinterdnd2 방식으로 등록 - 가능한 모든 위젯에"""
        targets = [self, self.overlay, self.canvas, self.media_panel]
        for widget in targets:
            try:
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_dnd_drop)
            except Exception:
                pass

    def _setup_dnd_fallback(self):
        """tkinterdnd2 없는 환경: overlay 클릭으로 파일 선택"""
        # overlay가 이미 파일 열기 버튼을 갖고 있으므로 추가 안내만
        pass

    def _on_dnd_drop(self, event):
        """드롭된 파일 경로 처리"""
        raw = event.data.strip()
        paths = re.findall(r'\{([^}]+)\}|(\S+)', raw)
        paths = [p[0] or p[1] for p in paths]

        srt_paths   = [p for p in paths if p.lower().endswith(".srt")]
        media_paths = [p for p in paths if not p.lower().endswith(".srt")]

        if srt_paths:
            self._load_srt(srt_paths[0])
        if media_paths:
            self._load_media(media_paths[0])

    # ── 사이드바 (화자 관리) ──────────────────
    def _build_sidebar(self, parent):
        side = ttk.Frame(parent, style="Side.TFrame", width=220)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)

        # SPEAKERS 헤더 + 우측 + 버튼
        _hdr_row = tk.Frame(side, bg=BG2)
        _hdr_row.pack(fill="x", padx=(14, 8), pady=(16, 6))
        ttk.Label(_hdr_row, text="SPEAKERS", style="Header.TLabel",
                  background=BG2).pack(side="left")

        list_frame = tk.Frame(side, bg=BG2)
        list_frame.pack(fill="both", expand=True, padx=6)

        canvas = tk.Canvas(list_frame, bg=BG2, highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical",
                                  command=canvas.yview)
        self.speaker_inner = tk.Frame(canvas, bg=BG2)
        self.speaker_inner.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        _spk_win = canvas.create_window((0, 0), window=self.speaker_inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        # speaker_inner 너비를 canvas 너비에 고정 — 내용물이 사이드바를 밀어내지 않도록
        canvas.bind("<Configure>",
            lambda e, w=_spk_win: canvas.itemconfigure(w, width=e.width))
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def _setup_media_dnd(self, widget):
        """미디어 패널 위젯에 드래그드롭 바인딩 (tkinterdnd2)"""
        if not self._dnd_enabled:
            return
        try:
            from tkinterdnd2 import DND_FILES
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_dnd_drop)
        except Exception:
            pass

    def _build_media_panel(self, parent):
        panel = tk.Frame(parent, bg=MEDIA_BG)
        panel.pack(fill="x", side="bottom")
        self.media_panel = panel
        self._media_panel = panel   # 스크롤 바인딩용

        tk.Frame(panel, bg=ACCENT, height=2).pack(fill="x")

        inner = tk.Frame(panel, bg=MEDIA_BG)
        inner.pack(fill="x", padx=14, pady=(6, 6))

        # ── 상단: 파일명 + 열기 버튼 ──────────
        top_row = tk.Frame(inner, bg=MEDIA_BG)
        top_row.pack(fill="x", pady=(0, 4))

        self.lbl_media = tk.Label(top_row,
            text="🎵  음성/영상 파일을 여기에 드래그하거나 버튼으로 여세요",
            bg=MEDIA_BG, fg=FG_DIM, font=(FONT_FAMILY, 9), anchor="w")
        self.lbl_media.pack(side="left", fill="x", expand=True)
        _med_wrap = tk.Frame(top_row, bg="#1A1A2A",
                             highlightthickness=1, highlightbackground="#252535")
        _med_wrap.pack(side="right", padx=(8, 0))
        _med_btn = tk.Button(_med_wrap, text="♪  음성 파일 열기",
                             bg="#1A1A2A", fg=FG, relief="flat", bd=0,
                             font=(FONT_FAMILY, 10), padx=8, pady=2,
                             cursor="hand2", takefocus=0,
                             activebackground=BG2, activeforeground=FG,
                             command=self.open_media)
        _med_btn.pack()
        Tooltip(_med_btn, "음성/영상 파일 열기", delay=500)

        # ── 파형 Canvas (100px) ────────────────
        self.media_progress_var = tk.DoubleVar(value=0)
        self._pb_canvas = tk.Canvas(inner, height=100, bg="#0D0D14",
                                    highlightthickness=1,
                                    highlightbackground="#252535",
                                    cursor="hand2")
        self._pb_canvas.pack(fill="x", pady=(0, 0))
        self._pb_dragging  = False
        self._waveform_pts = []
        self._wf_loading   = False

        # 줌/스크롤 상태: _wf_zoom=1.0~10.0, _wf_offset=0.0~1.0 (좌측 비율)
        self._wf_zoom   = 1.0
        self._wf_offset = 0.0   # 보이는 구간의 시작 비율

        self._pb_canvas.bind("<ButtonPress-1>",   self._pb_press)
        self._pb_canvas.bind("<B1-Motion>",        self._pb_drag)
        self._pb_canvas.bind("<ButtonRelease-1>", self._pb_release)
        self._pb_canvas.bind("<Configure>",       self._pb_configure)
        self._pb_canvas.bind("<Motion>",          self._wf_on_motion)
        self._pb_canvas.bind("<MouseWheel>",      self._wf_mousewheel)
        self._pb_canvas.bind("<Control-MouseWheel>", self._wf_zoom_wheel)
        # panel 생성 완료 후 모든 자식 위젯에 스크롤 바인딩
        self._pb_configure_job = None

        # ── 파형 스크롤바 ─────────────────────
        self._wf_hsb = tk.Canvas(inner, height=10, bg="#1A1A2A",
                                  highlightthickness=0, cursor="sb_h_double_arrow")
        self._wf_hsb.pack(fill="x", pady=(1, 0))
        self._wf_hsb.bind("<ButtonPress-1>",   self._wf_hsb_press)
        self._wf_hsb.bind("<B1-Motion>",        self._wf_hsb_drag)
        self._wf_hsb.bind("<ButtonRelease-1>", self._wf_hsb_release)
        self._wf_hsb_dragging = False
        self._wf_hsb_drag_x0  = 0
        self._wf_hsb_off0     = 0.0

        # ── 컨트롤 행 (버튼 + 볼륨) ───────────
        ctrl = tk.Frame(inner, bg=MEDIA_BG)
        ctrl.pack(fill="x", pady=(5, 0))

        self.lbl_pos = tk.Label(ctrl, text="0:00:00", bg=MEDIA_BG, fg=ACCENT,
                                font=(FONT_FAMILY, 9, "bold"), width=8, anchor="w")
        self.lbl_pos.pack(side="left")

        btn_group = tk.Frame(ctrl, bg=MEDIA_BG)
        btn_group.pack(side="left", expand=True)

        # 재생 컨트롤 — 배경 MEDIA_BG와 동일, 테두리 없음
        _pc = dict(bg=MEDIA_BG, fg=FG, relief="flat", bd=0, cursor="hand2",
                   activebackground=BG3, activeforeground=FG,
                   font=(FONT_FAMILY, 11), padx=10, pady=3, takefocus=0)

        self.btn_stop = tk.Button(btn_group, text="⏮", **_pc,
                  command=self._media_stop)
        self.btn_stop.pack(side="left", padx=1)
        self.btn_prev = tk.Button(btn_group, text="⏪", **_pc,
                  command=lambda: self._media_seek(-5))
        self.btn_prev.pack(side="left", padx=1)

        self.btn_play = tk.Button(btn_group, text="▶",
                                  bg=ACCENT, fg="white",
                                  font=(FONT_FAMILY, 13, "bold"),
                                  relief="flat", bd=0, cursor="hand2",
                                  activebackground="#7B5FB4", activeforeground="white",
                                  padx=14, pady=3, takefocus=0,
                                  command=self._media_play_pause)
        self.btn_play.pack(side="left", padx=6)

        self.btn_next = tk.Button(btn_group, text="⏩", **_pc,
                  command=lambda: self._media_seek(+5))
        self.btn_next.pack(side="left", padx=1)

        # 줌 컨트롤 — 주변 배경과 동일색, 테두리 없음
        zoom_wrap = tk.Frame(ctrl, bg=MEDIA_BG)
        zoom_wrap.pack(side="left", padx=(12, 0))
        tk.Button(zoom_wrap, text="−", bg=MEDIA_BG, fg=FG, relief="flat", bd=0,
                  font=(FONT_FAMILY, 10), padx=6, pady=2, cursor="hand2",
                  activebackground=BG3,
                  command=self._wf_zoom_out).pack(side="left")
        self.lbl_zoom = tk.Label(zoom_wrap, text="1×", bg=MEDIA_BG, fg=FG_DIM,
                                 font=(FONT_FAMILY, 9), width=4)
        self.lbl_zoom.pack(side="left")
        tk.Button(zoom_wrap, text="+", bg=MEDIA_BG, fg=FG, relief="flat", bd=0,
                  font=(FONT_FAMILY, 10), padx=6, pady=2, cursor="hand2",
                  activebackground=BG3,
                  command=self._wf_zoom_in).pack(side="left")

        self.lbl_dur = tk.Label(ctrl, text="0:00:00", bg=MEDIA_BG, fg=FG_DIM,
                                font=(FONT_FAMILY, 9), width=8, anchor="e")
        self.lbl_dur.pack(side="right")

        vol_frame = tk.Frame(ctrl, bg=MEDIA_BG)
        vol_frame.pack(side="right", padx=(0, 12))

        self._vol_icon = tk.Label(vol_frame, text="🔊", bg=MEDIA_BG, fg=FG,
                                  font=(FONT_FAMILY, 11), cursor="hand2")
        self._vol_icon.pack(side="left", padx=(0, 4))
        self._vol_icon.bind("<Button-1>", self._toggle_mute)

        self._vol_canvas = tk.Canvas(vol_frame, width=80, height=18,
                                     bg=MEDIA_BG, highlightthickness=0,
                                     cursor="hand2")
        self._vol_canvas.pack(side="left")

        self._vol_pct = tk.Label(vol_frame, text="100%", bg=MEDIA_BG, fg=FG,
                                 font=(FONT_FAMILY, 9, "bold"), width=4, anchor="w")
        self._vol_pct.pack(side="left", padx=(4, 0))

        self._vol_var = 100
        self._vol_before_mute = 100
        self._vol_dragging = False

        self._vol_canvas.bind("<ButtonPress-1>",   self._vol_press)
        self._vol_canvas.bind("<B1-Motion>",        self._vol_drag)
        self._vol_canvas.bind("<ButtonRelease-1>", self._vol_release)
        self._vol_canvas.bind("<Configure>",       self._vol_redraw)
        self.after(100, self._vol_redraw)

        for w in [panel, inner, top_row, self.lbl_media, ctrl, btn_group]:
            w.bind("<Enter>", lambda e: None)

    # ── 파형 Canvas 헬퍼 ─────────────────────
    def _wf_view_range(self):
        """현재 줌/오프셋 기준 보이는 구간 (start_ratio, end_ratio) 반환."""
        zoom = max(1.0, getattr(self, "_wf_zoom", 1.0))
        off  = getattr(self, "_wf_offset", 0.0)
        span = 1.0 / zoom
        start = max(0.0, min(off, 1.0 - span))
        end   = start + span
        # offset을 clamp된 값으로 동기화
        self._wf_offset = start
        return start, end

    def _wf_ratio_to_x(self, ratio, cw):
        """전체 비율 → 현재 뷰 내 x픽셀."""
        start, end = self._wf_view_range()
        span = end - start
        if span <= 0:
            return 0
        return int((ratio - start) / span * cw)

    def _wf_x_to_ratio(self, x, cw):
        """현재 뷰 내 x픽셀 → 전체 비율."""
        start, end = self._wf_view_range()
        span = end - start
        return max(0.0, min(start + (x / cw) * span, 1.0))

    def _pb_configure(self, event=None):
        """창 크기 변경 시 디바운싱 — 100ms 내 추가 이벤트 없을 때만 redraw."""
        if self._pb_configure_job:
            try:
                self.after_cancel(self._pb_configure_job)
            except Exception:
                pass
        self._pb_configure_job = self.after(100, self._pb_invalidate)

    def _pb_invalidate(self):
        """파형 이미지 캐시를 무효화하고 전체 redraw."""
        self._wf_img_cache = None
        self._pb_redraw()

    def _pb_redraw(self, event=None):
        c  = self._pb_canvas
        cw = c.winfo_width()
        ch = c.winfo_height()
        if cw <= 1:
            self.after(50, self._pb_redraw)
            return

        from PIL import Image, ImageDraw, ImageTk

        dur    = self.player.duration if self.player.duration > 0 else 0
        pos    = self.media_progress_var.get()
        start_r, end_r = self._wf_view_range()

        # ── 레이아웃 상수 ──────────────────────
        SUB_H  = 26          # 자막 행 높이
        GAP    = 1           # 자막/파형 구분선
        TICK_H = 16          # 하단 시간 눈금 영역
        sub_top = 0
        sub_bot = SUB_H
        wf_top  = SUB_H + GAP
        wf_bot  = ch - TICK_H
        wf_h    = wf_bot - wf_top
        wf_mid  = wf_top + wf_h // 2   # 파형 중앙 (두 채널 경계)

        # dur=0이면 캐시에서 산출
        cache = getattr(self, "_ts_cache", [])
        if dur > 0:
            dur_ = dur
        else:
            ends = [t_e for _, t_e in cache if t_e is not None]
            dur_ = max(ends) if ends else 1.0

        head_x = self._wf_ratio_to_x(pos / dur if dur > 0 else 0, cw)

        # ── 캐시 키 ───────────────────────────
        cache_key = (cw, ch, round(self._wf_zoom, 4), round(self._wf_offset, 6),
                     id(self._waveform_pts),
                     tuple((s.get("speaker",""), s.get("timestamp",""))
                            for s in (self.subtitles or [])),
                     round(dur_, 2))

        cached = getattr(self, "_wf_img_cache", None)
        if cached and cached[0] == cache_key:
            img_tk = cached[1]
        else:
            img    = Image.new("RGB", (cw, ch), "#0D0D0F")
            draw   = ImageDraw.Draw(img)
            pixels = img.load()

            # ── A. 자막 타임라인 행 ───────────
            # 배경
            draw.rectangle([0, sub_top, cw, sub_bot], fill="#131318")
            # 구분선
            draw.line([0, sub_bot, cw, sub_bot], fill="#2A2A3A", width=1)

            # 자막 블록 — 한글 지원 폰트 로드
            try:
                from PIL import ImageFont
                import sys as _sys, os as _os
                _candidates = (
                    ["C:/Windows/Fonts/malgun.ttf",
                     "C:/Windows/Fonts/NanumGothic.ttf",
                     "C:/Windows/Fonts/gulim.ttc"]
                    if _sys.platform == "win32" else
                    ["/System/Library/Fonts/AppleSDGothicNeo.ttc",
                     "/Library/Fonts/NanumGothic.ttf"]
                    if _sys.platform == "darwin" else
                    ["/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
                     "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
                )
                font = None
                for _fp in _candidates:
                    if _os.path.exists(_fp):
                        font = ImageFont.truetype(_fp, 10)
                        break
            except Exception:
                font = None

            if cache and self.subtitles:
                drag = getattr(self, "_wf_sub_drag", None)
                for i, (t_s, t_e) in enumerate(cache):
                    if t_s is None or t_e is None:
                        continue
                    if drag and drag["idx"] == i:
                        t_s = drag.get("t_s", t_s)
                        t_e = drag.get("t_e", t_e)
                    r_s, r_e = t_s / dur_, t_e / dur_
                    if r_e < start_r or r_s > end_r:
                        continue
                    x1 = int(self._wf_ratio_to_x(max(r_s, start_r), cw))
                    x2 = int(self._wf_ratio_to_x(min(r_e, end_r), cw))
                    x2 = max(x1 + 2, x2)
                    spk   = self.subtitles[i].get("speaker", "")
                    raw   = self._speaker_color(spk) if spk else "#404055"
                    h_hex = raw.lstrip("#")
                    fr, fg_, fb = int(h_hex[0:2],16), int(h_hex[2:4],16), int(h_hex[4:6],16)
                    # 어둡게 (화자 색 30% + 배경 70%)
                    BG_R, BG_G, BG_B = 0x13, 0x13, 0x18
                    fill_rgb = (int(fr*0.30+BG_R*0.70),
                                int(fg_*0.30+BG_G*0.70),
                                int(fb*0.30+BG_B*0.70))
                    fill_hex = f"#{fill_rgb[0]:02x}{fill_rgb[1]:02x}{fill_rgb[2]:02x}"
                    # 블록 채우기 (1px 위아래 여백)
                    draw.rectangle([x1+1, sub_top+3, x2, sub_bot-3], fill=fill_hex)
                    # 좌측 색상 강조선 (1px)
                    draw.line([x1+1, sub_top+3, x1+1, sub_bot-3], fill=raw, width=1)

                    # 텍스트 (폭이 허용되는 만큼)
                    box_w = x2 - x1 - 6
                    if box_w >= 14:
                        text = self.subtitles[i].get("text", "").replace("\n", " ").strip()
                        if text:
                            CHAR_W = 6
                            max_ch = max(1, box_w // CHAR_W)
                            if len(text) > max_ch:
                                text = text[:max_ch - 1] + "…"
                            ty = sub_top + (SUB_H - 12) // 2
                            text_col = f"#{min(255,fr+80):02x}{min(255,fg_+80):02x}{min(255,fb+80):02x}"
                            if font:
                                draw.text((x1 + 5, ty), text, fill=text_col, font=font)
                            else:
                                draw.text((x1 + 5, ty), text, fill=text_col)

            # ── B. 파형 (상단 채널 ↑ + 하단 채널 ↓) ──
            draw.rectangle([0, wf_top, cw, wf_bot], fill="#0D0D14")
            # 중앙 분리선
            draw.line([0, wf_mid, cw, wf_mid], fill="#1A1A28", width=1)

            wf = getattr(self, "_waveform_pts", [])
            if wf:
                margin  = (end_r - start_r) / max(cw, 1)
                pts_vis = [(rx, amp) for rx, amp in wf
                           if start_r - margin <= rx <= end_r + margin]
                if not pts_vis:
                    pts_vis = wf

                # 데이터 포인트 → x픽셀 매핑 (최대값)
                x_amp_raw = {}
                for rx, amp in pts_vis:
                    x = int(self._wf_ratio_to_x(rx, cw))
                    if 0 <= x < cw:
                        x_amp_raw[x] = max(x_amp_raw.get(x, 0.0), amp)

                # 선형 보간: 데이터 없는 픽셀은 인접 포인트 사이를 부드럽게 채움
                if x_amp_raw:
                    filled_xs = sorted(x_amp_raw)
                    x_amp = {}
                    for i in range(len(filled_xs)):
                        xa = filled_xs[i]
                        aa = x_amp_raw[xa]
                        x_amp[xa] = aa
                        if i + 1 < len(filled_xs):
                            xb = filled_xs[i + 1]
                            ab = x_amp_raw[xb]
                            for xi in range(xa + 1, xb):
                                t = (xi - xa) / (xb - xa)
                                x_amp[xi] = aa + (ab - aa) * t
                    # 양 끝 채우기
                    for xi in range(0, filled_xs[0]):
                        x_amp[xi] = x_amp_raw[filled_xs[0]]
                    for xi in range(filled_xs[-1] + 1, cw):
                        x_amp[xi] = x_amp_raw[filled_xs[-1]]
                else:
                    x_amp = {}

                half_h  = wf_h // 2 - 2   # 채널 하나의 최대 높이
                WF_BASE = (0x1E, 0x1E, 0x3A)
                WF_PLAY = (0x3A, 0x2A, 0x5A)

                for x in range(cw):
                    amp = x_amp.get(x, 0.0)
                    if False:  # 구 코드 제거
                        amp = 0.0
                    px = int(amp * half_h)
                    col = WF_PLAY if x <= head_x else WF_BASE

                    # 상단 채널 (wf_mid 기준 위쪽으로)
                    y0_top = max(wf_top,  wf_mid - px)
                    y1_top = wf_mid
                    for y in range(y0_top, y1_top):
                        pixels[x, y] = col

                    # 하단 채널 (wf_mid 기준 아래쪽으로)
                    y0_bot = wf_mid + 1
                    y1_bot = min(wf_bot, wf_mid + px + 1)
                    for y in range(y0_bot, y1_bot):
                        pixels[x, y] = col

            elif dur_ > 0:
                draw.rectangle([0, wf_mid-1, cw, wf_mid+1], fill="#2A2A4A")
                if head_x > 0:
                    draw.rectangle([0, wf_mid-1, head_x, wf_mid+1], fill=ACCENT)

            # ── C. 시간 눈금 ─────────────────────
            if dur > 0:
                span_sec = (end_r - start_r) * dur
                for tick in [0.1, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600]:
                    if span_sec / tick <= 24:
                        tick_step = tick; break
                else:
                    tick_step = 600
                t = (int(start_r * dur / tick_step)) * tick_step
                while t <= end_r * dur:
                    if t > dur: break
                    x = self._wf_ratio_to_x(t / dur, cw)
                    if 0 <= x <= cw:
                        draw.line([x, wf_bot, x, wf_bot+4], fill="#444466")
                        h_ = int(t//3600); m_ = int((t%3600)//60); s_ = int(t%60)
                        ms = int((t*10)%10)
                        lbl = (f"{m_}:{s_:02d}.{ms}" if tick_step < 1
                               else f"{h_}:{m_:02d}:{s_:02d}" if h_
                               else f"{m_}:{s_:02d}")
                        draw.text((x+3, wf_bot+2), lbl, fill="#555577")
                    t += tick_step

            img_tk = ImageTk.PhotoImage(img)
            self._wf_img_cache = (cache_key, img_tk)

        # ── Canvas 오버레이 ───────────────────
        c.delete("all")
        c.create_image(0, 0, anchor="nw", image=img_tk)

        # 재생 헤드
        if dur > 0:
            c.create_line(head_x, 0, head_x, ch, fill="white", width=1, tags="head")
            c.create_polygon(head_x-5, sub_top, head_x+5, sub_top, head_x, sub_top+7,
                             fill="white", outline="", tags="head")

        # 드래그 핸들 (파형 영역 기준)
        if cache and self.subtitles:
            drag = getattr(self, "_wf_sub_drag", None)
            HW   = self._WF_HANDLE_W
            for i, (t_s, t_e) in enumerate(cache):
                if t_s is None or t_e is None:
                    continue
                ts = t_s; te = t_e
                if drag and drag["idx"] == i:
                    ts = drag.get("t_s", ts)
                    te = drag.get("t_e", te)
                r_s, r_e = ts / dur_, te / dur_
                if r_e < start_r or r_s > end_r:
                    continue
                x1 = self._wf_ratio_to_x(max(r_s, start_r), cw)
                x2 = max(x1+2, self._wf_ratio_to_x(min(r_e, end_r), cw))
                spk   = self.subtitles[i].get("speaker", "")
                color = self._speaker_color(spk) if spk else "#404055"
                snapped_s = drag and drag["idx"]==i and drag["mode"]=="head_start"
                snapped_e = drag and drag["idx"]==i and drag["mode"]=="head_end"
                # 핸들은 자막 행 전체 높이에
                c.create_rectangle(x1,    sub_top, x1+HW, sub_bot,
                                   fill="#FFFFFF" if snapped_s else color, outline="")
                c.create_rectangle(x2-HW, sub_top, x2,    sub_bot,
                                   fill="#FFFFFF" if snapped_e else color, outline="")

        if getattr(self, "_wf_loading", False):
            c.create_text(cw//2, wf_top + (wf_bot-wf_top)//2,
                         text="파형 분석 중...", fill="#555577", font=(FONT_FAMILY, 9))

        self._wf_hsb_redraw()

    def _wf_on_motion(self, event):
        """마우스 위치에 따라 커서 변경 + hover 자막 추적."""
        x, y  = event.x, event.y
        SUB_H = 26
        dur   = self.player.duration
        cache = getattr(self, "_ts_cache", [])

        if dur <= 0:
            ends = [t_e for _, t_e in cache if t_e is not None]
            dur = max(ends) if ends else 0

        self._wf_hovered_idx = None

        if y <= SUB_H and dur > 0 and cache and self.subtitles:
            cw = self._pb_canvas.winfo_width()
            start_r, end_r = self._wf_view_range()
            HW = max(self._WF_HANDLE_W + 3, 7)

            # body 위인지 먼저 확인 — 뒤에서부터 (위에 그려진 자막 우선)
            # → hovered_idx를 항상 body 기준으로 설정
            for i in range(len(cache)-1, -1, -1):
                t_s, t_e = cache[i]
                if t_s is None or t_e is None:
                    continue
                r_s, r_e = t_s/dur, t_e/dur
                if r_e < start_r or r_s > end_r:
                    continue
                x1 = self._wf_ratio_to_x(max(r_s, start_r), cw)
                x2 = self._wf_ratio_to_x(min(r_e, end_r), cw)
                if x1 <= x <= x2:
                    self._wf_hovered_idx = i
                    break   # 가장 위에 있는 자막으로 확정

            # 커서: 핸들 범위면 ←→, 아니면 hand2
            if self._wf_hovered_idx is not None:
                t_s, t_e = cache[self._wf_hovered_idx]
                if t_s is not None and t_e is not None:
                    x1 = self._wf_ratio_to_x(t_s/dur, cw)
                    x2 = self._wf_ratio_to_x(t_e/dur, cw)
                    if abs(x - x1) <= HW or abs(x - x2) <= HW:
                        self._pb_canvas.configure(cursor="sb_h_double_arrow")
                        return
                self._pb_canvas.configure(cursor="hand2")
            else:
                self._pb_canvas.configure(cursor="tcross")
        else:
            self._pb_canvas.configure(cursor="hand2")

    def _pb_press(self, event):
        x, y  = event.x, event.y
        SUB_H = 26
        self._pb_press_x = x

        if y <= SUB_H:
            dur   = self.player.duration
            cache = getattr(self, "_ts_cache", [])
            if dur <= 0:
                ends = [t_e for _, t_e in cache if t_e is not None]
                dur  = max(ends) if ends else 1.0
            cw = self._pb_canvas.winfo_width()
            start_r, end_r = self._wf_view_range()
            HW = max(self._WF_HANDLE_W + 3, 7)
            hovered = getattr(self, "_wf_hovered_idx", None)

            # ── 1순위: hover 자막의 핸들 (같은 거리 문제 회피) ──
            if hovered is not None and hovered < len(cache):
                t_s, t_e = cache[hovered]
                if t_s is not None and t_e is not None:
                    x1 = self._wf_ratio_to_x(t_s/dur, cw)
                    x2 = self._wf_ratio_to_x(t_e/dur, cw)
                    mid_x = (x1 + x2) / 2
                    # hover 자막 내 절반 기준으로 시작/끝 결정
                    mode = "head_start" if x <= mid_x else "head_end"
                    self._start_handle_drag(mode, hovered)
                    self._pb_sub_click_idx = hovered
                    return

            # ── 2순위: hover 없을 때 가장 가까운 핸들 ──
            best_dist = float("inf")
            best_mode = None
            best_idx  = None
            for i, (t_s, t_e) in enumerate(cache):
                if t_s is None or t_e is None:
                    continue
                r_s, r_e = t_s/dur, t_e/dur
                if r_e < start_r or r_s > end_r:
                    continue
                x1 = self._wf_ratio_to_x(max(r_s, start_r), cw)
                x2 = self._wf_ratio_to_x(min(r_e, end_r), cw)
                for mode_, xh in [("head_start", x1), ("head_end", x2)]:
                    d = abs(x - xh)
                    if d <= HW and d < best_dist:
                        best_dist = d
                        best_mode = mode_
                        best_idx  = i

            if best_idx is not None:
                self._start_handle_drag(best_mode, best_idx)
                return

            # ── 3순위: 빈 공간 ──
            self._wf_sub_drag = None
            self._pb_dragging = True
            return

        # ── 파형 영역 ────────────────────────────
        self._wf_sub_drag = None
        self._pb_dragging = True
        self._pb_canvas.configure(cursor="hand2")
        pos = self._pb_pos_from_x(x)
        self.media_progress_var.set(pos)
        self.lbl_pos.configure(text=self._fmt_time(pos))
        self._pb_redraw()

    def _start_handle_drag(self, mode, idx):
        """핸들 드래그 상태 초기화. undo 스냅샷을 드래그 시작 시점에 찍음."""
        cache = getattr(self, "_ts_cache", [])
        self._push_undo()   # 변경 전 상태를 여기서 snapshot
        self._wf_sub_drag = {
            "mode": mode, "idx": idx,
            "t_s": cache[idx][0],
            "t_e": cache[idx][1],
        }
        self._pb_dragging = False
        self._pb_sub_click_idx = None
        self._pb_canvas.configure(cursor="sb_h_double_arrow")

    def _pb_drag(self, event):
        drag = getattr(self, "_wf_sub_drag", None)
        if drag:
            dur = self.player.duration
            if dur <= 0: return
            cw = self._pb_canvas.winfo_width()
            t  = max(0.0, self._wf_x_to_ratio(event.x, cw) * dur)

            idx   = drag["idx"]
            cache = self._ts_cache
            # 스냅 임계값: 현재 뷰에서 8px에 해당하는 초
            span_sec = (1.0 / max(1.0, self._wf_zoom)) * dur
            snap_sec = span_sec * 8 / max(cw, 1)

            if drag["mode"] == "head_start":
                t = min(t, drag["t_e"] - 0.05)
                # 스냅 후보: 앞 자막 종료점 + 재생 헤드
                snap_candidates = []
                for j, (js, je) in enumerate(cache):
                    if j == idx or je is None: continue
                    if abs(je - t) < snap_sec:
                        snap_candidates.append(je)
                pos = self.media_progress_var.get()
                if abs(pos - t) < snap_sec:
                    snap_candidates.append(pos)
                if snap_candidates:
                    drag["t_s"] = min(snap_candidates, key=lambda v: abs(v - t))
                else:
                    drag["t_s"] = t
            else:
                t = max(t, drag["t_s"] + 0.05)
                # 스냅 후보: 뒤 자막 시작점 + 재생 헤드
                snap_candidates = []
                for j, (js, je) in enumerate(cache):
                    if j == idx or js is None: continue
                    if abs(js - t) < snap_sec:
                        snap_candidates.append(js)
                pos = self.media_progress_var.get()
                if abs(pos - t) < snap_sec:
                    snap_candidates.append(pos)
                if snap_candidates:
                    drag["t_e"] = min(snap_candidates, key=lambda v: abs(v - t))
                else:
                    drag["t_e"] = t

            self._pb_redraw()
            return
        if not self._pb_dragging:
            return
        pos = self._pb_pos_from_x(event.x)
        self.media_progress_var.set(pos)
        self.lbl_pos.configure(text=self._fmt_time(pos))
        self._pb_redraw()

    def _pb_release(self, event):
        drag      = getattr(self, "_wf_sub_drag", None)
        press_x   = getattr(self, "_pb_press_x", event.x)
        moved     = abs(event.x - press_x)
        CLICK_THR = 5   # 이 픽셀 이하 이동이면 클릭으로 판정

        self._pb_canvas.configure(cursor="hand2")

        if drag:
            idx = drag["idx"]

            # 거의 안 움직였으면 → 클릭으로 판정, 자막 시작점 seek
            if moved <= CLICK_THR:
                self._wf_sub_drag = None
                # 드래그 시작 시 찍은 undo 스냅샷 취소 (변경 없으므로)
                if self._undo_stack:
                    self._undo_stack.pop()
                cache = getattr(self, "_ts_cache", [])
                t_s = cache[idx][0] if idx < len(cache) else None
                if t_s is not None:
                    self._do_seek(t_s)
                else:
                    self._pb_redraw()
                return

            # 실제 드래그 → 타임스탬프 적용 (undo는 _start_handle_drag에서 이미 찍음)
            if 0 <= idx < len(self.subtitles):
                t_s = drag.get("t_s", self._ts_cache[idx][0])
                t_e = drag.get("t_e", self._ts_cache[idx][1])
                def _fmt_ts(sec):
                    h=int(sec//3600); m=int((sec%3600)//60); s=int(sec%60)
                    ms=int(round((sec%1)*1000))
                    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
                self.subtitles[idx]["timestamp"] = f"{_fmt_ts(t_s)} --> {_fmt_ts(t_e)}"
                self._ts_cache[idx] = (t_s, t_e)
                self._unsaved = True
                self._redraw_slot_for(idx)
            self._wf_sub_drag = None
            self._wf_img_cache = None   # 이미지 캐시 무효화
            self._pb_redraw()
            return

        self._pb_dragging = False
        if not self.media_path:
            return
        self._do_seek(self._pb_pos_from_x(event.x))

    def _do_seek(self, pos, update_selection=True):
        """지정 위치로 seek.
        update_selection=True(기본): 재생바 직접 이동 시, 해당 위치 자막을 선택으로 설정.
        update_selection=False: 내부 seek(재생/정지, 좌우키 등)에서 호출 시 현재 선택 자막을 변경하지 않음."""
        was_playing = self.player.is_playing
        self.player.seek_to(pos)
        self.media_progress_var.set(pos)
        self.lbl_pos.configure(text=self._fmt_time(pos))

        new_rows = self._get_rows_at(pos)

        # 하이라이트 갱신
        if new_rows != self._playing_rows:
            changed = self._playing_rows.symmetric_difference(new_rows)
            self._playing_rows = new_rows
            for idx in changed:
                self._redraw_slot_for(idx)

        # 재생바 직접 이동 시에만 해당 자막을 선택으로 설정
        if update_selection and new_rows:
            anchor = min(new_rows)
            old_sel = set(self._selected_rows) | ({self._selected_row_idx} if self._selected_row_idx is not None else set())
            self._selected_rows = set(new_rows)
            self._selected_row_idx = anchor
            self._last_focused_idx = anchor
            for idx in old_sel.symmetric_difference(self._selected_rows):
                self._redraw_slot_for(idx)
            self._scroll_to_row(anchor)

        self._pb_redraw()
        if was_playing:
            self.btn_play.configure(text="⏸")
            self._start_progress_poll()

    def _wf_hsb_redraw(self):
        c = getattr(self, "_wf_hsb", None)
        if c is None: return
        cw = c.winfo_width(); ch = c.winfo_height()
        if cw <= 1: return
        c.delete("all")
        c.create_rectangle(0, 0, cw, ch, fill="#1A1A2A", outline="")
        if self._wf_zoom <= 1.0: return
        start, end = self._wf_view_range()
        x1 = int(start * cw)
        x2 = max(x1+12, int(end * cw))
        c.create_rectangle(x1, 1, x2, ch-1, fill="#3A3A5A", outline="#555577")

    def _wf_hsb_press(self, e):
        self._wf_hsb_dragging = True
        self._wf_hsb_drag_x0  = e.x
        self._wf_hsb_off0     = self._wf_offset

    def _wf_hsb_drag(self, e):
        if not self._wf_hsb_dragging: return
        cw = self._wf_hsb.winfo_width()
        if cw <= 1: return
        span = 1.0 / max(1.0, self._wf_zoom)
        self._wf_offset = max(0.0, min(self._wf_hsb_off0 + (e.x - self._wf_hsb_drag_x0) / cw, 1.0 - span))
        self._pb_redraw()

    def _wf_hsb_release(self, e):
        self._wf_hsb_dragging = False

    def _wf_mousewheel(self, e):
        # 파형 뷰 구간 이동 (재생 위치 무관)
        # 위 스크롤 → 앞, 아래 스크롤 → 뒤 / Shift: 5배 빠르게
        span  = 1.0 / max(1.0, self._wf_zoom)
        step  = span * 0.2 if (e.state & 0x1) else span * 0.03
        delta = -step if e.delta > 0 else step
        self._wf_offset = max(0.0, min(self._wf_offset + delta, 1.0 - span))
        self._pb_redraw()
        return "break"


    def _wf_zoom_wheel(self, e):
        cw = self._pb_canvas.winfo_width()
        # 마우스 위치를 pivot으로
        pivot = self._wf_x_to_ratio(e.x, cw) if cw > 1 else None
        if e.delta > 0: self._wf_zoom_in(pivot=pivot)
        else:           self._wf_zoom_out(pivot=pivot)
        return "break"

    def _wf_zoom_in(self, pivot=None):
        old_zoom = self._wf_zoom
        self._wf_zoom = min(128.0, self._wf_zoom * 1.5)
        self._wf_adjust_offset(old_zoom, pivot)
        self._update_zoom_label()
        self._pb_redraw()

    def _wf_zoom_out(self, pivot=None):
        old_zoom = self._wf_zoom
        self._wf_zoom = max(1.0, self._wf_zoom / 1.5)
        self._wf_adjust_offset(old_zoom, pivot)
        self._update_zoom_label()
        self._pb_redraw()

    def _wf_adjust_offset(self, old_zoom, pivot=None):
        """줌 변경 후 pivot 비율이 같은 화면 위치에 유지되도록 offset 조정.
        pivot=None 이면 현재 재생 헤드 위치를 pivot으로 사용."""
        if pivot is None:
            dur = self.player.duration
            pivot = (self.media_progress_var.get() / dur) if dur > 0 else 0.5
        span = 1.0 / self._wf_zoom
        # pivot이 뷰에서 차지하던 상대 위치(0~1) 유지
        old_span  = 1.0 / max(1.0, old_zoom)
        rel = (pivot - self._wf_offset) / old_span if old_span > 0 else 0.5
        rel = max(0.0, min(rel, 1.0))
        new_offset = pivot - rel * span
        self._wf_offset = max(0.0, min(new_offset, 1.0 - span))

    def _update_zoom_label(self):
        z = self._wf_zoom
        try:
            self.lbl_zoom.configure(text=f"{z:.0f}×" if z == int(z) else f"{z:.1f}×")
        except Exception:
            pass

    def _pb_pos_from_x(self, x):
        cw  = self._pb_canvas.winfo_width()
        dur = self.player.duration if self.player.duration > 0 else 1
        return self._wf_x_to_ratio(x, cw) * dur

    # ── 볼륨 제어 (커스텀 Canvas 바) ──────────
    def _vol_redraw(self, event=None):
        """볼륨 바 Canvas 다시 그리기."""
        c = self._vol_canvas
        cw = c.winfo_width()
        ch = c.winfo_height()
        if cw <= 1:
            self.after(50, self._vol_redraw)
            return
        c.delete("all")
        v = self._vol_var          # 0~100
        ratio = v / 100.0
        filled = int(cw * ratio)
        track_y = ch // 2

        # 트랙 배경 (라운드 효과는 rect로 근사)
        c.create_rectangle(0, track_y - 4, cw, track_y + 4,
                           fill="#2A2A2A", outline="", tags="track")
        # 채워진 부분 — ACCENT보다 약간 어두운 단일 색
        if filled > 0:
            c.create_rectangle(0, track_y - 4, filled, track_y + 4,
                               fill="#7A5FB0", outline="", tags="fill")
        # 핸들
        hx = max(6, min(filled, cw - 6))
        c.create_oval(hx - 6, track_y - 6, hx + 6, track_y + 6,
                      fill="white", outline="#555555", width=1, tags="handle")

    def _vol_from_x(self, x):
        cw = self._vol_canvas.winfo_width()
        return max(0, min(100, int(x / cw * 100)))

    def _vol_press(self, event):
        self._vol_dragging = True
        self._set_volume(self._vol_from_x(event.x))

    def _vol_drag(self, event):
        if not self._vol_dragging:
            return
        self._set_volume(self._vol_from_x(event.x))

    def _vol_release(self, event):
        self._vol_dragging = False
        self._set_volume(self._vol_from_x(event.x))

    def _set_volume(self, v):
        """볼륨 값(0~100) 반영: 플레이어·UI·아이콘 모두 갱신."""
        v = max(0, min(100, v))
        self._vol_var = v
        self.player._volume = v
        self._vol_pct.configure(text=f"{v}%")
        # 아이콘
        if v == 0:
            self._vol_icon.configure(text="🔇")
        elif v < 40:
            self._vol_icon.configure(text="🔉")
        else:
            self._vol_icon.configure(text="🔊")
        self._vol_redraw()
        # 재생 중이면 즉시 반영
        if self.player.is_playing:
            pos = self.player.position
            self.player._kill_proc()
            self.player._start_play(pos)

    def _toggle_mute(self, event=None):
        """볼륨 아이콘 클릭 → 음소거/복원 토글."""
        if self._vol_var > 0:
            self._vol_before_mute = self._vol_var
            self._set_volume(0)
        else:
            self._set_volume(self._vol_before_mute if self._vol_before_mute > 0 else 80)


    def _check_update_async(self):
        import threading as _threading
        _threading.Thread(target=self._fetch_latest_version, daemon=True).start()

    def _fetch_latest_version(self):
        import urllib.request, json, pathlib, datetime

        log_path = pathlib.Path.home() / ".srt_speaker_update.log"
        def _log(msg):
            try:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(f"[{datetime.datetime.now():%H:%M:%S}] {msg}\n")
            except Exception:
                pass

        def _parse(v):
            try:
                return tuple(int(x) for x in v.strip().lstrip("v").split("."))
            except Exception:
                return (0,)

        headers = {
            "User-Agent": "Mozilla/5.0 SRT-Speaker-Separator",
            "Accept": "application/vnd.github+json",
        }

        latest = None

        # 1차: git/refs/tags (가장 안정적)
        try:
            req = urllib.request.Request(
                "https://api.github.com/repos/danggai/SRT-Speaker-Separator/git/refs/tags",
                headers=headers)
            with urllib.request.urlopen(req, timeout=6) as resp:
                refs = json.loads(resp.read().decode())
            if refs:
                latest = refs[-1]["ref"].split("/")[-1].lstrip("v")
                _log(f"git/refs/tags → {latest}")
        except Exception as e:
            _log(f"git/refs/tags FAIL: {e}")

        # 2차: /tags API
        if not latest:
            try:
                req = urllib.request.Request(
                    "https://api.github.com/repos/danggai/SRT-Speaker-Separator/tags",
                    headers=headers)
                with urllib.request.urlopen(req, timeout=6) as resp:
                    tags = json.loads(resp.read().decode())
                if tags:
                    latest = tags[0]["name"].lstrip("v")
                    _log(f"/tags → {latest}")
            except Exception as e:
                _log(f"/tags FAIL: {e}")

        if not latest:
            _log("모든 엔드포인트 실패")
            return

        self._latest_version_cache = latest
        _log(f"current={APP_VERSION} latest={latest} newer={_parse(latest) > _parse(APP_VERSION)}")

        if _parse(latest) > _parse(APP_VERSION):
            self.after(0, lambda v=latest: self._show_update_badge(v))

    def _show_update_badge(self, latest_ver):
        import webbrowser
        try:
            def _on_click(v=latest_ver):
                ans = messagebox.askyesno(
                    "업데이트 알림",
                    f"새로운 버전이 있습니다!\n\n"
                    f"현재 버전: v{APP_VERSION}\n"
                    f"최신 버전: v{v}\n\n"
                    "GitHub 릴리즈 페이지로 이동할까요?",
                    parent=self
                )
                if ans:
                    webbrowser.open(GITHUB_TAGS_URL)

            btn = self._update_btn
            btn.configure(command=_on_click)
            if not btn.winfo_ismapped():
                btn.pack(side="left", padx=(4, 0), pady=8)
                btn.lift()
        except Exception as e:
            import traceback; traceback.print_exc()

    def _open_settings(self):
        """설정 창 (탭: 패턴 / 화자 분석)"""
        global g_speaker_pattern, g_display_pattern
        win = tk.Toplevel(self)
        win.title("설정")
        win.configure(bg=BG)
        win.geometry("580x540")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()

        def _on_settings_close():
            self._save_diarize_settings()
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", _on_settings_close)

        nb = ttk.Notebook(win)

        # ── 하단 버전 정보 (먼저 pack해야 Notebook에 가려지지 않음)
        _ver_frame = tk.Frame(win, bg=BG2)
        _ver_frame.pack(fill="x", side="bottom")
        tk.Frame(_ver_frame, bg=BORDER, height=1).pack(fill="x")
        _ver_row = tk.Frame(_ver_frame, bg=BG2)
        _ver_row.pack(fill="x", padx=16, pady=6)
        tk.Label(_ver_row, text=f"현재 버전: v{APP_VERSION}",
                 bg=BG2, fg=FG_DIM, font=(FONT_FAMILY, 8)).pack(side="left")
        self._settings_latest_lbl = tk.Label(_ver_row, text="최신 버전: 확인 중...",
                 bg=BG2, fg=FG_DIM, font=(FONT_FAMILY, 8))
        self._settings_latest_lbl.pack(side="left", padx=(16, 0))

        import webbrowser as _wb
        _gh_lbl = tk.Label(_ver_row, text="🔗 GitHub",
                           bg=BG2, fg="#4A90E2",
                           font=(FONT_FAMILY, 8, "underline"),
                           cursor="hand2")
        _gh_lbl.pack(side="right")
        _gh_lbl.bind("<Button-1>",
                     lambda e: _wb.open("https://github.com/danggai/SRT-Speaker-Separator"))

        def _update_latest_lbl(v):
            try:
                self._settings_latest_lbl.configure(text=f"최신 버전: v{v}")
            except Exception:
                pass

        if getattr(self, "_latest_version_cache", None):
            _update_latest_lbl(self._latest_version_cache)
        else:
            import threading
            def _fetch_for_settings():
                import urllib.request, json
                headers = {"User-Agent": "Mozilla/5.0 SRT-Speaker-Separator",
                           "Accept": "application/vnd.github+json"}
                for url, extractor in [
                    ("https://api.github.com/repos/danggai/SRT-Speaker-Separator/releases/latest",
                     lambda d: d.get("tag_name", "")),
                    ("https://api.github.com/repos/danggai/SRT-Speaker-Separator/git/refs/tags",
                     lambda d: d[-1]["ref"].split("/")[-1] if d else ""),
                    (GITHUB_LATEST_API,
                     lambda d: d[0]["name"] if d else ""),
                ]:
                    try:
                        req = urllib.request.Request(url, headers=headers)
                        with urllib.request.urlopen(req, timeout=5) as resp:
                            tag = extractor(json.loads(resp.read().decode()))
                        if tag:
                            self._latest_version_cache = tag.lstrip("v")
                            self.after(0, lambda v=tag.lstrip("v"): _update_latest_lbl(v))
                            return
                    except Exception:
                        continue
                self.after(0, lambda: _update_latest_lbl("확인 실패"))
            threading.Thread(target=_fetch_for_settings, daemon=True).start()

        nb.pack(fill="both", expand=True, padx=0, pady=0)

        # ── 탭 1: 화자 구분 패턴 ──────────────────
        tab1 = tk.Frame(nb, bg=BG)
        nb.add(tab1, text="  화자 구분 패턴  ")

        tk.Label(tab1, text="화자 구분 패턴", bg=BG, fg=FG,
                 font=(FONT_FAMILY, 11, "bold")).pack(anchor="w", padx=20, pady=(18, 2))
        tk.Label(tab1,
                 text="% = 현재 화자명,  & = 자막 내용\n"
                      "예시:  [%] &  →  [Alice] 안녕하세요\n"
                      "예시:  (%): &  →  (Bob): 반갑습니다",
                 bg=BG, fg=FG_DIM, font=(FONT_FAMILY, 9),
                 justify="left").pack(anchor="w", padx=20, pady=(0, 6))

        pat_var = tk.StringVar(value=g_display_pattern)
        pat_entry = tk.Entry(tab1, textvariable=pat_var, width=52,
                             bg=BG3, fg=ACCENT, insertbackground=FG,
                             font=(FONT_MONO, 10), relief="flat",
                             highlightthickness=1, highlightbackground=BORDER,
                             highlightcolor=ACCENT)
        pat_entry.pack(fill="x", padx=20, ipady=4)

        preview_lbl = tk.Label(tab1, text="", bg=BG, fg=FG_DIM,
                               font=(FONT_MONO, 8), wraplength=500, justify="left")
        preview_lbl.pack(anchor="w", padx=20, pady=(3, 0))
        info_lbl = tk.Label(tab1, text="", bg=BG, fg="#FF6B8A",
                            font=(FONT_FAMILY, 9))
        info_lbl.pack(anchor="w", padx=20, pady=(2, 0))

        def update_preview(*_):
            dp = pat_var.get().strip()
            try:
                rx = display_to_regex(dp)
                re.compile(rx)
                preview_lbl.configure(text=f"정규식: {rx}", fg=FG_DIM)
                info_lbl.configure(text="")
            except Exception as err:
                preview_lbl.configure(text="")
                info_lbl.configure(text=f"❌ {err}", fg="#FF6B8A")

        pat_var.trace_add("write", update_preview)
        update_preview()

        def on_apply():
            global g_speaker_pattern, g_display_pattern
            dp = pat_var.get().strip()
            try:
                rx = display_to_regex(dp)
                re.compile(rx)
            except Exception as err:
                info_lbl.configure(text=f"❌ {err}", fg="#FF6B8A")
                return
            g_speaker_pattern = rx
            g_display_pattern = dp
            info_lbl.configure(text="✔ 적용되었습니다.", fg=ACCENT)
            win.after(1200, win.destroy)

        btn_row = tk.Frame(tab1, bg=BG)
        btn_row.pack(fill="x", padx=20, pady=(14, 10))
        tk.Button(btn_row, text="기본값",
                  bg="#2A2A2A", fg=FG_DIM, relief="flat", bd=0, cursor="hand2",
                  font=(FONT_FAMILY, 10), padx=10, pady=5,
                  activebackground="#333333",
                  command=lambda: pat_var.set(DEFAULT_DISPLAY_PATTERN)
                  ).pack(side="left")
        tk.Button(btn_row, text="적용",
                  bg=ACCENT, fg="white", relief="flat", bd=0, cursor="hand2",
                  font=(FONT_FAMILY, 10, "bold"), padx=18, pady=5,
                  activebackground="#7B5FB4", command=on_apply).pack(side="right")
        tk.Button(btn_row, text="취소",
                  bg="#2A2A2A", fg=FG, relief="flat", bd=0, cursor="hand2",
                  font=(FONT_FAMILY, 10), padx=12, pady=5,
                  activebackground="#333333",
                  command=win.destroy).pack(side="right", padx=(0, 8))

        # ── 탭 2: 모델 관리 ────────────────────
        tab2 = tk.Frame(nb, bg=BG)
        nb.add(tab2, text="  📦 모델 관리  ")
        self._build_model_mgmt_tab(tab2)


    def _build_model_mgmt_tab(self, parent):
        """다운로드된 모델 캐시 관리 탭."""
        import pathlib, os, shutil

        tk.Label(parent, text="다운로드된 모델", bg=BG, fg=FG,
                 font=(FONT_FAMILY, 11, "bold")).pack(anchor="w", padx=20, pady=(18, 2))
        tk.Label(parent,
                 text="WhisperX / pyannote 모델 캐시를 확인하고 삭제할 수 있습니다.",
                 bg=BG, fg=FG_DIM, font=(FONT_FAMILY, 9), justify="left"
                 ).pack(anchor="w", padx=20, pady=(0, 10))

        # 목록 영역
        list_frame = tk.Frame(parent, bg=BG2,
                              highlightthickness=1, highlightbackground=BORDER)
        list_frame.pack(fill="both", expand=True, padx=20, pady=(0, 8))

        # 스크롤 가능한 내부 캔버스
        _canvas = tk.Canvas(list_frame, bg=BG2, highlightthickness=0)
        _sb = ttk.Scrollbar(list_frame, orient="vertical", command=_canvas.yview)
        _inner = tk.Frame(_canvas, bg=BG2)
        _canvas.configure(yscrollcommand=_sb.set)
        _sb.pack(side="right", fill="y")
        _canvas.pack(side="left", fill="both", expand=True)
        _win_id = _canvas.create_window((0, 0), window=_inner, anchor="nw")
        _inner.bind("<Configure>",
                    lambda e: _canvas.configure(scrollregion=_canvas.bbox("all")))
        _canvas.bind("<Configure>",
                     lambda e: _canvas.itemconfigure(_win_id, width=e.width))

        def _fmt_size(nb):
            for u in ("B", "KB", "MB", "GB"):
                if nb < 1024:
                    return f"{nb:.1f} {u}"
                nb /= 1024
            return f"{nb:.1f} TB"

        def _dir_size(p):
            total = 0
            try:
                for f in pathlib.Path(p).rglob("*"):
                    if f.is_file():
                        total += f.stat().st_size
            except Exception:
                pass
            return total

        def _scan_models():
            found = []
            hf_hub = pathlib.Path(os.environ.get(
                "HF_HOME", pathlib.Path.home() / ".cache" / "huggingface")) / "hub"
            if hf_hub.exists():
                for d in sorted(hf_hub.iterdir()):
                    if not d.is_dir():
                        continue
                    sz = _dir_size(d)
                    if sz == 0:
                        continue
                    label = d.name.replace("models--", "").replace("--", "/")
                    found.append(("dir", d, label, sz))
            old_w = pathlib.Path.home() / ".cache" / "whisper"
            if old_w.exists():
                for f in sorted(old_w.iterdir()):
                    if f.is_file():
                        found.append(("file", f, f"whisper/{f.name}", f.stat().st_size))
            return found

        _chk_vars = {}

        def _refresh():
            for w in _inner.winfo_children():
                w.destroy()
            _chk_vars.clear()
            models = _scan_models()

            if not models:
                tk.Label(_inner, text="다운로드된 모델이 없습니다.",
                         bg=BG2, fg=FG_DIM, font=(FONT_FAMILY, 9)
                         ).pack(padx=16, pady=16)
                _del_btn.configure(state="disabled")
                return

            # 헤더
            hdr = tk.Frame(_inner, bg=BG3)
            hdr.pack(fill="x")
            tk.Label(hdr, text="  모델명", bg=BG3, fg=FG_DIM,
                     font=(FONT_FAMILY, 8), anchor="w").pack(side="left", fill="x", expand=True)
            tk.Label(hdr, text="용량  ", bg=BG3, fg=FG_DIM,
                     font=(FONT_FAMILY, 8), anchor="e", width=10).pack(side="right")

            total_sz = 0
            for kind, path, label, sz in models:
                total_sz += sz
                row = tk.Frame(_inner, bg=BG2)
                row.pack(fill="x", pady=1)
                var = tk.BooleanVar(value=False)
                _chk_vars[str(path)] = (var, kind, path)
                tk.Checkbutton(row, variable=var, bg=BG2, fg=FG,
                               selectcolor=BG3, activebackground=BG2,
                               cursor="hand2").pack(side="left", padx=(6, 0))
                tk.Label(row, text=label, bg=BG2, fg=FG,
                         font=(FONT_MONO, 8), anchor="w"
                         ).pack(side="left", fill="x", expand=True, padx=4)
                tk.Label(row, text=_fmt_size(sz), bg=BG2, fg=FG_DIM,
                         font=(FONT_FAMILY, 8), width=10, anchor="e"
                         ).pack(side="right", padx=(0, 8))

            # 합계
            foot = tk.Frame(_inner, bg=BG3)
            foot.pack(fill="x", pady=(2, 0))
            tk.Label(foot, text="  전체", bg=BG3, fg=FG_DIM,
                     font=(FONT_FAMILY, 8), anchor="w").pack(side="left", fill="x", expand=True)
            tk.Label(foot, text=f"{_fmt_size(total_sz)}  ", bg=BG3, fg=FG,
                     font=(FONT_FAMILY, 8, "bold"), width=10, anchor="e").pack(side="right")

            _del_btn.configure(state="normal")

        def _delete_selected():
            targets = [(kind, path)
                       for key, (var, kind, path) in _chk_vars.items() if var.get()]
            if not targets:
                messagebox.showwarning("모델 삭제", "삭제할 모델을 선택하세요.",
                                       parent=parent.winfo_toplevel())
                return
            names = "\n".join(f"  • {pathlib.Path(str(p)).name}" for _, p in targets)
            if not messagebox.askyesno("모델 삭제",
                    f"선택한 {len(targets)}개 모델을 삭제합니다.\n\n{names}\n\n계속하시겠습니까?",
                    parent=parent.winfo_toplevel()):
                return
            errors = []
            for kind, path in targets:
                try:
                    if kind == "file":
                        pathlib.Path(str(path)).unlink()
                    else:
                        shutil.rmtree(str(path))
                except Exception as e:
                    errors.append(str(e))
            if errors:
                messagebox.showerror("삭제 오류", "\n".join(errors),
                                     parent=parent.winfo_toplevel())
            _refresh()

        # 하단 버튼
        btn_row = tk.Frame(parent, bg=BG)
        btn_row.pack(fill="x", padx=20, pady=(0, 16))
        tk.Button(btn_row, text="↻  새로고침",
                  bg=BG3, fg=FG, relief="flat", bd=0, cursor="hand2",
                  font=(FONT_FAMILY, 9), padx=10, pady=5,
                  activebackground="#333333",
                  command=_refresh).pack(side="left")
        _del_btn = tk.Button(btn_row, text="🗑  선택 삭제",
                  bg="#6B2F2F", fg="white", relief="flat", bd=0, cursor="hand2",
                  font=(FONT_FAMILY, 9), padx=10, pady=5,
                  activebackground="#8B3F3F",
                  command=_delete_selected)
        _del_btn.pack(side="left", padx=(8, 0))

        _refresh()

    def _build_diarize_tab(self, parent):
        """설정창 내 화자 자동 분석 탭."""
        # WhisperX 섹션
        tk.Label(parent, text="WhisperX 화자 분리", bg=BG, fg=FG,
                 font=(FONT_FAMILY, 11, "bold")).pack(anchor="w", padx=20, pady=(18, 2))
        tk.Label(parent,
                 text="WhisperX + pyannote를 사용해 오디오에서 화자를 자동 분리합니다.\n"
                      "HuggingFace 토큰이 필요하며 처음 실행 시 모델을 다운로드합니다.",
                 bg=BG, fg=FG_DIM, font=(FONT_FAMILY, 9), justify="left"
                 ).pack(anchor="w", padx=20, pady=(0, 10))

        # HuggingFace 토큰
        hf_frame = tk.Frame(parent, bg=BG)
        hf_frame.pack(fill="x", padx=20, pady=(0, 2))
        tk.Label(hf_frame, text="HuggingFace 토큰", bg=BG, fg=FG,
                 font=(FONT_FAMILY, 9, "bold"), width=18, anchor="w"
                 ).pack(side="left")
        self._hf_token_var = tk.StringVar(
            value=getattr(self, "_hf_token", ""))
        _tok_entry = tk.Entry(hf_frame, textvariable=self._hf_token_var, show="*",
                 bg=BG3, fg=FG, insertbackground=FG,
                 font=(FONT_MONO, 9), relief="flat",
                 highlightthickness=1, highlightbackground=BORDER,
                 highlightcolor=ACCENT)
        _tok_entry.pack(side="left", fill="x", expand=True, ipady=3)

        # 👁 암호화 토글 버튼
        _show_var = tk.BooleanVar(value=False)
        def _toggle_show():
            _show_var.set(not _show_var.get())
            _tok_entry.configure(show="" if _show_var.get() else "*")
            _eye_btn.configure(text="🙈" if _show_var.get() else "👁")
        _eye_btn = tk.Button(hf_frame, text="👁", bg=BG3, fg=FG_DIM,
                             relief="flat", bd=0, cursor="hand2",
                             font=(FONT_FAMILY, 10), padx=6,
                             activebackground=BG3, activeforeground=FG,
                             command=_toggle_show)
        _eye_btn.pack(side="left", padx=(4, 0))

        # 최근 토큰 드롭다운
        _recent = getattr(self, "_recent_tokens", [])
        if _recent:
            def _pick_recent(val):
                self._hf_token_var.set(val)
                _show_var.set(False)
                _tok_entry.configure(show="*")
                _eye_btn.configure(text="👁")
            _recent_var = tk.StringVar(value="")
            _recent_menu = tk.OptionMenu(hf_frame, _recent_var,
                                         *[t[:8] + "…" + t[-4:] if len(t) > 14 else t
                                           for t in _recent])
            _recent_menu.configure(bg=BG3, fg=FG_DIM, relief="flat", bd=0,
                                   font=(FONT_FAMILY, 8), padx=4,
                                   activebackground=BG3, activeforeground=FG,
                                   highlightthickness=0, indicatoron=False,
                                   text="🕘")
            _recent_menu["menu"].configure(bg=BG3, fg=FG, activebackground=ACCENT,
                                            font=(FONT_MONO, 8))
            _recent_menu.pack(side="left", padx=(2, 0))
            # OptionMenu 선택 시 실제 전체 토큰 삽입
            def _on_recent_select(*_):
                idx_label = _recent_var.get()
                for t in _recent:
                    label = t[:8] + "…" + t[-4:] if len(t) > 14 else t
                    if label == idx_label:
                        _pick_recent(t)
                        break
                _recent_var.set("")
            _recent_var.trace_add("write", _on_recent_select)

        # 화자 수
        spk_frame = tk.Frame(parent, bg=BG)
        spk_frame.pack(fill="x", padx=20, pady=(0, 8))
        tk.Label(spk_frame, text="최대 화자 수 (0=자동)", bg=BG, fg=FG,
                 font=(FONT_FAMILY, 9, "bold"), width=18, anchor="w"
                 ).pack(side="left")
        self._diarize_num_spk = tk.IntVar(value=getattr(self, "_diarize_num_spk_val", 0))
        tk.Spinbox(spk_frame, from_=0, to=20, width=5,
                   textvariable=self._diarize_num_spk,
                   bg=BG3, fg=FG, insertbackground=FG,
                   buttonbackground=BG3, relief="flat",
                   font=(FONT_FAMILY, 10)).pack(side="left", padx=(0, 8))
        tk.Label(spk_frame, text="(0이면 pyannote가 자동 감지)",
                 bg=BG, fg=FG_DIM, font=(FONT_FAMILY, 8)).pack(side="left")

        # 분석 모드
        mode_frame = tk.Frame(parent, bg=BG)
        mode_frame.pack(fill="x", padx=20, pady=(0, 8))
        tk.Label(mode_frame, text="분석 모드", bg=BG, fg=FG,
                 font=(FONT_FAMILY, 9, "bold"), width=18, anchor="w"
                 ).pack(side="left")
        if not hasattr(self, "_diarize_mode_var"):
            self._diarize_mode_var = tk.StringVar(value=getattr(self, "_diarize_mode_init", "balanced"))
        mode_inner = tk.Frame(mode_frame, bg=BG)
        mode_inner.pack(side="left")
        _MODES = [
            ("⚡ 빠름",      "fast",     "속도 우선 — 정확도 소폭 감소"),
            ("⚖ 균형",      "balanced", "속도·정확도 균형 (기본)"),
            ("🎯 정확",      "accurate", "정확도 우선 — 시간 더 소요"),
            ("🔬 최고 정확", "best",     "회의·다수 화자 최적, 가장 느림"),
        ]
        for label, val, tip in _MODES:
            rb = tk.Radiobutton(mode_inner, text=label, value=val,
                                variable=self._diarize_mode_var,
                                bg=BG, fg=FG, selectcolor=BG3,
                                activebackground=BG, activeforeground=FG,
                                font=(FONT_FAMILY, 9), cursor="hand2")
            rb.pack(side="left", padx=(0, 6))
            # 툴팁
            def _bind_tip(w, t=tip):
                def _show(e): pass  # 간단히 title로 대체
            _bind_tip(rb)

        # 모드 설명 레이블
        _mode_tips = {
            "fast":     "⚡ large-v3-turbo, beam_size=1 — 빠른 속도, 짧은 발화 놓칠 수 있음",
            "balanced": "⚖ large-v3-turbo, beam_size=3 — 일반 대화·인터뷰에 적합",
            "accurate": "🎯 large-v3, beam_size=5 — 정확한 화자 경계 탐지",
            "best":     "🔬 large-v3, beam_size=5 — 회의·다수 화자 최적",
        }
        _tip_lbl = tk.Label(parent, text=_mode_tips["balanced"],
                            bg=BG, fg=FG_DIM, font=(FONT_FAMILY, 8), anchor="w")
        _tip_lbl.pack(fill="x", padx=20, pady=(0, 4))
        def _on_mode_change(*_):
            _tip_lbl.configure(text=_mode_tips.get(self._diarize_mode_var.get(), ""))
        self._diarize_mode_var.trace_add("write", _on_mode_change)

        # 디바이스 선택
        dev_frame = tk.Frame(parent, bg=BG)
        dev_frame.pack(fill="x", padx=20, pady=(4, 8))
        tk.Label(dev_frame, text="연산 디바이스", bg=BG, fg=FG,
                 font=(FONT_FAMILY, 9, "bold"), width=18, anchor="w"
                 ).pack(side="left")
        if not hasattr(self, "_diarize_device_var"):
            self._diarize_device_var = tk.StringVar(
                value=getattr(self, "_diarize_device_init", "auto"))
        dev_inner = tk.Frame(dev_frame, bg=BG)
        dev_inner.pack(side="left")
        for label, val in [("🚀 GPU 우선 (기본)", "auto"), ("🖥 CPU 강제", "cpu")]:
            tk.Radiobutton(dev_inner, text=label, value=val,
                           variable=self._diarize_device_var,
                           bg=BG, fg=FG, selectcolor=BG3,
                           activebackground=BG, activeforeground=FG,
                           font=(FONT_FAMILY, 9), cursor="hand2"
                           ).pack(side="left", padx=(0, 10))
        tk.Label(parent,
                 text="  GPU 우선: CUDA 가능 시 GPU 사용, 불가 시 CPU 자동 전환",
                 bg=BG, fg=FG_DIM, font=(FONT_FAMILY, 8), anchor="w"
                 ).pack(fill="x", padx=20, pady=(0, 6))

        # GPU 사용량 — 캔버스 커스텀 5단계 슬라이더
        _BATCH_MAP   = [2, 4, 8, 16, 32]
        _BATCH_LABEL = ["최소", "낮음", "보통", "권장", "최대"]
        _VRAM_HINT   = ["~2 GB", "~4 GB", "~6 GB", "~8 GB", "~12 GB+"]
        _BATCH_DEFAULT = 3

        if not hasattr(self, "_diarize_batch_var"):
            self._diarize_batch_var = tk.IntVar(
                value=getattr(self, "_diarize_batch_init", _BATCH_DEFAULT))

        # 헤더 행
        gpu_hdr = tk.Frame(parent, bg=BG)
        gpu_hdr.pack(fill="x", padx=20, pady=(0, 4))
        tk.Label(gpu_hdr, text="GPU 사용량", bg=BG, fg=FG,
                 font=(FONT_FAMILY, 9, "bold"), width=18, anchor="w"
                 ).pack(side="left")
        _gpu_val_lbl = tk.Label(gpu_hdr, bg=BG, fg=ACCENT,
                                font=(FONT_FAMILY, 9, "bold"), anchor="w")
        _gpu_val_lbl.pack(side="left")

        # 캔버스 슬라이더
        _SL_W, _SL_H = 360, 52   # 레이블 잘림 방지
        _N = len(_BATCH_MAP)
        _sl_cv = tk.Canvas(parent, width=_SL_W, height=_SL_H,
                           bg=BG, highlightthickness=0)
        _sl_cv.pack(padx=20, anchor="w", pady=(0, 2))

        # 트랙 Y 중앙
        _TY = _SL_H // 2
        _PAD = 20   # 양쪽 여백
        _TRACK_W = _SL_W - _PAD * 2
        _enabled = [True]

        def _step_x(i):
            return _PAD + int(i / (_N - 1) * _TRACK_W)

        def _draw_slider(idx):
            _sl_cv.delete("all")
            dim = not _enabled[0]
            track_color  = "#333344" if dim else BG3
            fill_color   = "#444455" if dim else ACCENT
            dot_off      = "#2A2A3A" if dim else BG3
            dot_on       = "#444455" if dim else ACCENT
            dot_border   = "#333344" if dim else ACCENT
            label_active = FG_DIM if dim else FG
            label_dim    = "#444455" if dim else FG_DIM

            # 트랙 배경
            _sl_cv.create_rectangle(_PAD, _TY-2, _SL_W-_PAD, _TY+2,
                                    fill=track_color, outline="")
            # 채워진 부분
            if idx > 0:
                _sl_cv.create_rectangle(_PAD, _TY-2, _step_x(idx), _TY+2,
                                        fill=fill_color, outline="")

            for i in range(_N):
                x = _step_x(i)
                active = i <= idx
                # 노브
                r = 7 if i == idx else 5
                color = dot_on if active else dot_off
                border = dot_border if active else track_color
                _sl_cv.create_oval(x-r, _TY-r, x+r, _TY+r,
                                   fill=color, outline=border, width=1)
                # 선택된 노브에 내부 흰 점
                if i == idx and not dim:
                    _sl_cv.create_oval(x-2, _TY-2, x+2, _TY+2,
                                       fill="white", outline="")
                # 레이블
                lbl_color = label_active if i == idx else label_dim
                lbl_font  = (FONT_FAMILY, 8, "bold") if i == idx else (FONT_FAMILY, 7)
                _sl_cv.create_text(x, _TY + 14, text=_BATCH_LABEL[i],
                                   fill=lbl_color, font=lbl_font, anchor="n")

        def _on_batch(*_):
            idx = max(0, min(self._diarize_batch_var.get(), _N-1))
            _draw_slider(idx)
            bs  = _BATCH_MAP[idx]
            vrm = _VRAM_HINT[idx]
            _gpu_val_lbl.configure(text=f"batch {bs}  —  VRAM {vrm}")

        def _sl_click(e):
            if not _enabled[0]: return
            # 클릭 x → 가장 가까운 스텝
            best_i, best_d = 0, 9999
            for i in range(_N):
                d = abs(e.x - _step_x(i))
                if d < best_d:
                    best_d, best_i = d, i
            self._diarize_batch_var.set(best_i)
            _on_batch()

        _sl_cv.bind("<Button-1>", _sl_click)
        _sl_cv.bind("<B1-Motion>", _sl_click)

        def _on_device_change(*_):
            is_gpu = self._diarize_device_var.get() != "cpu"
            _enabled[0] = is_gpu
            _gpu_val_lbl.configure(fg=ACCENT if is_gpu else FG_DIM)
            _on_batch()
        self._diarize_device_var.trace_add("write", _on_device_change)
        _on_batch()
        _on_device_change()

        # 구분선
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=20, pady=10)

        # SpeechBrain 섹션 (UI만, 미구현)
        tk.Label(parent, text="SpeechBrain 화자 분리 (준비 중)", bg=BG, fg="#444455",
                 font=(FONT_FAMILY, 11, "bold")).pack(anchor="w", padx=20, pady=(0, 2))
        tk.Label(parent,
                 text="토큰 없이 로컬에서 실행 가능한 방식입니다. (추후 지원 예정)",
                 bg=BG, fg="#444455", font=(FONT_FAMILY, 9), justify="left"
                 ).pack(anchor="w", padx=20, pady=(0, 10))

        sb_frame = tk.Frame(parent, bg=BG)
        sb_frame.pack(fill="x", padx=20, pady=(0, 8))
        tk.Label(sb_frame, text="모델", bg=BG, fg="#444455",
                 font=(FONT_FAMILY, 9, "bold"), width=18, anchor="w").pack(side="left")
        tk.Entry(sb_frame, bg=BG3, fg="#444455",
                 font=(FONT_MONO, 9), relief="flat",
                 highlightthickness=1, highlightbackground="#333333",
                 state="disabled").pack(side="left", fill="x", expand=True, ipady=3)

        # 실행 버튼
        btn_row = tk.Frame(parent, bg=BG)
        btn_row.pack(fill="x", padx=20, pady=(8, 10))
        tk.Button(btn_row, text="🎙  WhisperX로 화자 분석 시작",
                  bg=ACCENT, fg="white", relief="flat", bd=0, cursor="hand2",
                  font=(FONT_FAMILY, 10, "bold"), padx=18, pady=6,
                  activebackground="#7B5FB4",
                  command=self._run_diarize_whisperx
                  ).pack(side="left")
        tk.Button(btn_row, text="SpeechBrain (준비 중)",
                  bg="#2A2A2A", fg="#444455", relief="flat", bd=0,
                  font=(FONT_FAMILY, 10), padx=14, pady=6,
                  state="disabled").pack(side="left", padx=(8, 0))

    def _open_diarize_dialog(self):
        """툴바 버튼 → 설정창 화자 분석 탭 직접 열기."""
        if not self.media_path:
            messagebox.showwarning("화자 분석", "미디어 파일을 먼저 불러오세요.", parent=self)
            return
        global g_speaker_pattern, g_display_pattern
        win = tk.Toplevel(self)
        win.title("화자 자동 분석")
        win.configure(bg=BG)
        win.geometry("560x540")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()
        def _on_diarize_win_close():
            self._save_diarize_settings()
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", _on_diarize_win_close)
        self._build_diarize_tab(win)

    def _save_diarize_settings(self):
        """현재 화자 분석 설정을 파일에 저장."""
        # tk 위젯은 창 닫힌 후 소멸될 수 있으므로 try/except로 각각 읽기
        def _safe_get(var, fallback):
            try:
                return var.get() if var else fallback
            except Exception:
                return fallback

        hf_tok      = _safe_get(getattr(self, "_hf_token_var",     None), getattr(self, "_hf_token", "")).strip()
        num_spk     = _safe_get(getattr(self, "_diarize_num_spk",  None), getattr(self, "_diarize_num_spk_val", 0))
        mode        = _safe_get(getattr(self, "_diarize_mode_var", None), getattr(self, "_diarize_mode_init", "balanced"))
        device_pref = _safe_get(getattr(self, "_diarize_device_var", None), getattr(self, "_diarize_device_init", "auto"))
        batch_idx   = _safe_get(getattr(self, "_diarize_batch_var", None), 3)

        _cfg = _load_config()
        if hf_tok:
            _cfg["hf_token"] = hf_tok
            _add_recent_token(_cfg, hf_tok)
            self._hf_token      = hf_tok
            self._recent_tokens = _cfg.get("recent_tokens", [])
        _cfg["num_speakers"]   = num_spk
        _cfg["diarize_mode"]   = mode
        _cfg["diarize_device"] = device_pref
        _cfg["diarize_batch"]  = batch_idx
        self._diarize_num_spk_val = num_spk
        self._diarize_mode_init   = mode
        self._diarize_device_init = device_pref
        self._diarize_batch_init  = batch_idx
        _save_config(_cfg)

    def _run_diarize_whisperx(self):
        """WhisperX로 화자 분리 실행 (백그라운드 스레드)."""
        if not self.media_path:
            messagebox.showwarning("화자 분석", "미디어 파일을 먼저 불러오세요.", parent=self)
            return
        if not self.subtitles:
            messagebox.showwarning("화자 분석", "SRT 자막을 먼저 불러오세요.", parent=self)
            return

        token   = getattr(self, "_hf_token_var", None)
        hf_tok  = token.get().strip() if token else ""
        if not hf_tok:
            messagebox.showwarning("화자 분석",
                "HuggingFace 토큰을 입력하세요.\n"
                "https://huggingface.co/settings/tokens 에서 발급받을 수 있습니다.",
                parent=self)
            return

        num_spk_var = getattr(self, "_diarize_num_spk", None)
        num_spk = num_spk_var.get() if num_spk_var else 0
        self._hf_token            = hf_tok
        self._diarize_num_spk_val = num_spk

        # 설정 저장 (토큰·화자 수·모드)
        _cfg = _load_config()
        _cfg["hf_token"]     = hf_tok
        _cfg["num_speakers"] = num_spk
        _cfg["diarize_mode"] = getattr(self, "_diarize_mode_var", tk.StringVar()).get()
        _add_recent_token(_cfg, hf_tok)
        self._recent_tokens  = _cfg.get("recent_tokens", [])
        _save_config(_cfg)

        # 진행 다이얼로그
        import math as _math, time as _time
        prog_win = tk.Toplevel(self)
        prog_win.title("화자 분석 중...")
        prog_win.configure(bg=BG)
        prog_win.geometry("440x260")
        prog_win.resizable(False, False)
        prog_win.transient(self)
        prog_win.grab_set()

        tk.Label(prog_win, text="🎙  화자 자동 분석 중...", bg=BG, fg=FG,
                 font=(FONT_FAMILY, 11, "bold")).pack(pady=(18, 2))

        # 현재 단계 텍스트
        self._diarize_status_lbl = tk.Label(prog_win, text="초기화 중...",
                                             bg=BG, fg=FG, font=(FONT_FAMILY, 9, "bold"))
        self._diarize_status_lbl.pack()

        # 단계별 서브 상태 (점 애니메이션 + 경과시간)
        _sub_lbl = tk.Label(prog_win, text="", bg=BG, fg=FG_DIM, font=(FONT_FAMILY, 8))
        _sub_lbl.pack(pady=(1, 0))

        # ── 그라데이션 웨이브 프로그레스바 ──
        BAR_W, BAR_H = 380, 20
        bar_canvas = tk.Canvas(prog_win, width=BAR_W, height=BAR_H,
                               bg=BG3, highlightthickness=1,
                               highlightbackground=BORDER)
        bar_canvas.pack(pady=(10, 6))

        # 시간 정보 행 (경과 / 예상)
        time_row = tk.Frame(prog_win, bg=BG)
        time_row.pack(fill="x", padx=32, pady=(2, 0))
        _elapsed_lbl = tk.Label(time_row, text="경과  0:00", bg=BG, fg=FG_DIM,
                                font=(FONT_FAMILY, 8), anchor="w")
        _elapsed_lbl.pack(side="left")
        _eta_lbl = tk.Label(time_row, text="", bg=BG, fg=ACCENT,
                            font=(FONT_FAMILY, 10, "bold"), anchor="e")
        _eta_lbl.pack(side="right")

        # 단계 타임라인 — 전체 너비에 균등 분배
        STEP_LABELS = ["import", "model", "audio", "transcribe", "align", "diarize", "map"]
        STEP_NAMES  = ["임포트", "모델로드", "음성로드", "음성인식", "정렬", "화자분리", "매핑"]
        step_row = tk.Frame(prog_win, bg=BG)
        step_row.pack(fill="x", padx=32, pady=(8, 0))
        _step_lbls = []
        for sname in STEP_NAMES:
            lbl = tk.Label(step_row, text=sname, bg=BG3, fg=FG_DIM,
                           font=(FONT_FAMILY, 7), pady=3,
                           relief="flat", anchor="center")
            lbl.pack(side="left", fill="x", expand=True, padx=1)
            _step_lbls.append(lbl)

        # 진행 상태
        _prog_state = {
            "target": 0.0, "current": 0.0, "wave_phase": 0.0, "running": True,
            "step_key": None, "step_start": _time.time(), "global_start": _time.time(),
            "dot_tick": 0,
        }

        # 단계별 누적 % (예상시간 제거 — 실측 기반으로 계산)
        _STEPS = {
            "import":      5,
            "model":       20,
            "audio":       25,
            "transcribe":  55,
            "align":       70,
            "diarize":     90,
            "map":         97,
            "done":        100,
        }
        _STEP_ORDER = ["import","model","audio","transcribe","align","diarize","map","done"]

        def _fmt_time(sec):
            sec = int(sec)
            return f"{sec//60}:{sec%60:02d}"

        # PhotoImage 픽셀 렌더
        _bar_img = tk.PhotoImage(width=BAR_W, height=BAR_H)
        bar_canvas.create_image(0, 0, anchor="nw", image=_bar_img)
        _pct_id = bar_canvas.create_text(BAR_W // 2, BAR_H // 2,
                                         text="0%", fill=FG_DIM,
                                         font=(FONT_FAMILY, 8, "bold"))
        _BG3R = int(BG3[1:3], 16)
        _BG3G = int(BG3[3:5], 16)
        _BG3B = int(BG3[5:7], 16)

        def _draw_bar():
            if not _prog_state["running"]:
                return
            try:
                now   = _time.time()
                cur   = _prog_state["current"]
                phase = _prog_state["wave_phase"]
                fill_w = int(BAR_W * cur / 100)

                # ── 픽셀 렌더 ──
                row = []
                for x in range(BAR_W):
                    if x < fill_w:
                        t = x / BAR_W
                        if t < 0.5:
                            k = t * 2
                            r0 = int(0x7B + (0x4A - 0x7B) * k)
                            g0 = int(0x4F + (0x90 - 0x4F) * k)
                            b0 = int(0xD4 + (0xE2 - 0xD4) * k)
                        else:
                            k = (t - 0.5) * 2
                            r0 = int(0x4A + (0x1A - 0x4A) * k)
                            g0 = int(0x90 + (0xBC - 0x90) * k)
                            b0 = int(0xE2 + (0x9C - 0xE2) * k)
                        wave = _math.sin(phase - x * 0.045) * 0.20 + 0.85
                        glow = _math.exp(-(fill_w - x) * 0.10) * 0.35
                        bri  = min(1.15, wave + glow)
                        row.append("#{:02x}{:02x}{:02x}".format(
                            min(255, int(r0 * bri)),
                            min(255, int(g0 * bri)),
                            min(255, int(b0 * bri))))
                    else:
                        row.append("#{:02x}{:02x}{:02x}".format(_BG3R, _BG3G, _BG3B))
                row_str = "{" + " ".join(row) + "}"
                _bar_img.put(" ".join([row_str] * BAR_H))
                bar_canvas.itemconfigure(_pct_id,
                    text=f"{int(cur)}%",
                    fill="white" if fill_w > BAR_W // 2 else FG_DIM)

                # ── 경과 시간 ──
                elapsed = now - _prog_state["global_start"]
                _elapsed_lbl.configure(text=f"경과  {_fmt_time(elapsed)}")

                # ── 예상 남은 시간 ──
                # 오디오 길이 기반 각 단계 예상 종료 시각으로 역산
                # (프로그레스바 추정치 사용 X → 늘어나는 현상 방지)
                step_key = _prog_state["step_key"]
                if step_key:
                    _stage_est = _prog_state.get("stage_estimates", {})
                    if _stage_est:
                        remaining = 0.0
                        for sk in _STEP_ORDER:
                            if sk == "done":
                                continue
                            est = _stage_est.get(sk, 0.0)
                            wall = _prog_state.get(f"wall_{sk}", None)
                            if wall is None:
                                # 아직 시작 안 한 단계 → 예상치 전부 합산
                                remaining += est
                            elif sk == step_key:
                                # 현재 진행 중인 단계 → 실제 경과 빼고 남은 것만
                                elapsed_in_step = now - wall
                                remaining += max(0.0, est - elapsed_in_step)
                            # 이미 완료된 단계는 0
                        if remaining > 5:
                            _eta_lbl.configure(text=f"예상 잔여  ~{_fmt_time(remaining)}")
                        elif remaining > 0:
                            _eta_lbl.configure(text="거의 완료...")
                    else:
                        _eta_lbl.configure(text="계산 중...")

                # ── 단계 타임라인 색상 ──
                if step_key in STEP_LABELS:
                    cur_idx = STEP_LABELS.index(step_key)
                    for i, lbl in enumerate(_step_lbls):
                        if i < cur_idx:
                            lbl.configure(bg="#1E4A2E", fg="#4CAF50")   # 완료: 초록
                        elif i == cur_idx:
                            lbl.configure(bg=ACCENT, fg="white")         # 현재: 강조
                        else:
                            lbl.configure(bg=BG3, fg=FG_DIM)             # 대기: 회색

                # ── 점 애니메이션 (현재 단계 살아있음 표시) ──
                tick = _prog_state["dot_tick"]
                dots = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
                step_elapsed_s = now - _prog_state["step_start"]
                _sub_lbl.configure(
                    text=f"{dots[tick % len(dots)]}  {_fmt_time(step_elapsed_s)} 경과")
                _prog_state["dot_tick"] += 1

                # ── ease-out ──
                _prog_state["wave_phase"] += 0.18
                diff = _prog_state["target"] - cur
                if abs(diff) > 0.05:
                    _prog_state["current"] += diff * 0.07
                else:
                    _prog_state["current"] = _prog_state["target"]

                prog_win.after(100, _draw_bar)  # 10fps (시간 표시는 1초 정밀도면 충분)
            except Exception:
                pass

        prog_win.after(100, _draw_bar)

        def _set_status(msg, step_key=None):
            try:
                self._diarize_status_lbl.configure(text=msg)
                if step_key and step_key in _STEPS:
                    t = _time.time()
                    _prog_state["target"]          = float(_STEPS[step_key])
                    _prog_state["step_key"]        = step_key
                    _prog_state["step_start"]      = t
                    _prog_state["dot_tick"]        = 0
                    _prog_state[f"wall_{step_key}"] = t  # 단계별 실제 시작 시각
            except Exception:
                pass

        def _tick_progress(step_key, elapsed_sec, total_est_sec):
            """긴 단계 내부에서 세부 진행률 추정 업데이트 (30초마다 호출)."""
            try:
                if step_key not in _STEPS:
                    return
                step_start_pct = {
                    "transcribe": 25.0, "align": 55.0, "diarize": 70.0
                }.get(step_key, None)
                step_end_pct = float(_STEPS[step_key])
                if step_start_pct is None:
                    return
                ratio = min(0.92, elapsed_sec / max(1, total_est_sec))
                new_target = step_start_pct + (step_end_pct - step_start_pct) * ratio
                if new_target > _prog_state["target"]:
                    _prog_state["target"] = new_target
            except Exception:
                pass

        def _worker():
            try:
                _set_status("whisperx 임포트 중...", "import")
                import whisperx
                import torch

                # ── GPU 진단 ──────────────────────────────────────────
                _cuda_build   = torch.cuda.is_available()
                _cuda_ver     = torch.version.cuda if _cuda_build else None
                _gpu_name     = torch.cuda.get_device_name(0) if _cuda_build else None
                _torch_ver    = torch.__version__

                # 디바이스 결정
                _dev_pref = getattr(self, "_diarize_device_var", None)
                _dev_pref = _dev_pref.get() if _dev_pref else "auto"
                if _dev_pref == "cpu":
                    device = "cpu"
                    _dev_reason = "CPU 강제 모드"
                elif not _cuda_build:
                    device = "cpu"
                    _dev_reason = f"CUDA 불가 (torch {_torch_ver} — CPU 전용 빌드일 수 있음)"
                else:
                    device = "cuda"
                    _dev_reason = f"GPU: {_gpu_name}  |  CUDA {_cuda_ver}"

                _set_status(f"디바이스: {_dev_reason}", "import")

                # CUDA 빌드가 아닌데 GPU 우선 선택이면 → 자동 재설치 제안
                if _dev_pref != "cpu" and not _cuda_build:
                    import tkinter.messagebox as _mb
                    import subprocess, sys

                    # NVIDIA 드라이버에서 지원 CUDA 버전 감지
                    def _detect_cuda_tag():
                        try:
                            out = subprocess.check_output(
                                ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                                stderr=subprocess.DEVNULL, text=True).strip()
                            # 드라이버 버전으로 CUDA 지원 버전 추정
                            drv = float(out.split("\n")[0].split(".")[0])
                            if drv >= 525: return "cu121"
                            if drv >= 520: return "cu118"
                            return "cu117"
                        except Exception:
                            return "cu121"  # 기본값

                    _do_install = self.after(0, lambda: None)  # dummy

                    def _ask_and_install():
                        cuda_tag = _detect_cuda_tag()
                        ans = _mb.askyesno(
                            "GPU torch 자동 설치",
                            f"현재 torch ({_torch_ver}) 가 CPU 전용 빌드라 GPU를 쓸 수 없어요.\n\n"
                            f"CUDA 빌드 torch ({cuda_tag}) 를 지금 자동 설치할까요?\n"
                            f"(설치 후 앱이 자동 재시작됩니다)\n\n"
                            "아니오 선택 시 CPU로 계속 진행합니다.",
                            parent=self
                        )
                        if not ans:
                            return  # CPU로 그냥 진행

                        # 설치 진행 (별도 창)
                        inst_win = tk.Toplevel(self)
                        inst_win.title("torch 설치 중...")
                        inst_win.configure(bg=BG)
                        inst_win.geometry("400x120")
                        inst_win.resizable(False, False)
                        inst_win.transient(self)
                        inst_win.grab_set()
                        tk.Label(inst_win,
                                 text=f"⏳  torch+{cuda_tag} 설치 중...",
                                 bg=BG, fg=FG, font=(FONT_FAMILY, 10, "bold")
                                 ).pack(pady=(24, 6))
                        _inst_sub = tk.Label(inst_win,
                                 text="pip install 실행 중 (수 분 소요될 수 있습니다)",
                                 bg=BG, fg=FG_DIM, font=(FONT_FAMILY, 8))
                        _inst_sub.pack()
                        inst_win.update()

                        def _update_sub(text):
                            try: _inst_sub.configure(text=text)
                            except Exception: pass

                        def _do_pip():
                            idx_url = f"https://download.pytorch.org/whl/{cuda_tag}"
                            cmd_base = [
                                sys.executable, "-m", "pip", "install",
                                "torch", "torchaudio",
                                "--index-url", idx_url,
                                "--upgrade",
                                "--force-reinstall",   # CPU 빌드를 확실히 덮어씀
                            ]

                            def _run_cmd(extra_args=[]):
                                """pip 실행 후 stdout/stderr 캡처해서 반환."""
                                result = subprocess.run(
                                    cmd_base + extra_args,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT,
                                    text=True
                                )
                                return result.returncode, result.stdout

                            def _verify_cuda():
                                """설치 후 실제 CUDA 동작 여부 확인."""
                                try:
                                    result = subprocess.run(
                                        [sys.executable, "-c",
                                         "import torch; print(torch.cuda.is_available()); "
                                         "print(torch.__version__)"],
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        text=True, timeout=30
                                    )
                                    lines = result.stdout.strip().splitlines()
                                    cuda_ok = len(lines) >= 1 and lines[0].strip() == "True"
                                    ver = lines[1].strip() if len(lines) >= 2 else "?"
                                    return cuda_ok, ver
                                except Exception as e:
                                    return False, str(e)

                            # 1차: 일반 설치
                            self.after(0, lambda: _update_sub("pip 설치 중... (수 분 소요)"))
                            rc, out = _run_cmd()

                            if rc != 0:
                                # 2차: --user 재시도
                                self.after(0, lambda: _update_sub("권한 문제 → --user 모드로 재시도 중..."))
                                rc, out = _run_cmd(["--user"])

                            if rc != 0:
                                # 3차: UAC 관리자 승격
                                def _try_admin(log=out):
                                    try: inst_win.destroy()
                                    except Exception: pass
                                    ans2 = _mb.askyesno(
                                        "설치 실패 — 관리자 권한 필요",
                                        f"pip 설치가 실패했습니다.\n\n"
                                        f"오류 내용:\n{log[-300:]}\n\n"
                                        "관리자 권한으로 다시 시도할까요? (UAC 창이 뜹니다)",
                                        parent=self)
                                    if ans2:
                                        try:
                                            import ctypes
                                            args = (f"-m pip install torch torchaudio "
                                                    f"--index-url {idx_url} --upgrade --force-reinstall")
                                            ctypes.windll.shell32.ShellExecuteW(
                                                None, "runas", sys.executable, args, None, 1)
                                            _mb.showinfo("설치 진행 중",
                                                "관리자 권한으로 설치를 시작했습니다.\n"
                                                "완료 후 앱을 직접 재시작해주세요.",
                                                parent=self)
                                        except Exception as e2:
                                            _mb.showerror("설치 실패",
                                                f"관리자 설치도 실패했습니다.\n{e2}",
                                                parent=self)
                                self.after(0, _try_admin)
                                return

                            # 설치 성공 → CUDA 실제 동작 검증
                            self.after(0, lambda: _update_sub("설치 완료 — CUDA 동작 검증 중..."))
                            cuda_ok, ver = _verify_cuda()

                            if not cuda_ok:
                                def _bad_install(log=out, v=ver):
                                    try: inst_win.destroy()
                                    except Exception: pass
                                    _mb.showerror(
                                        "GPU 활성화 실패",
                                        f"pip 설치는 완료됐지만 CUDA가 여전히 비활성 상태입니다.\n"
                                        f"(torch {v})\n\n"
                                        "가능한 원인:\n"
                                        "• NVIDIA 드라이버가 너무 오래됨 → 드라이버 업데이트 필요\n"
                                        f"• CUDA 태그 불일치 (현재: {cuda_tag}) → "
                                        "다른 버전 시도 필요\n\n"
                                        "pip 출력 로그:\n" + log[-400:],
                                        parent=self)
                                self.after(0, _bad_install)
                                return

                            def _restart(v=ver):
                                try: inst_win.destroy()
                                except Exception: pass
                                _mb.showinfo("설치 완료",
                                    f"torch {v} GPU 빌드 설치 완료!\n"
                                    "앱을 재시작합니다.",
                                    parent=self)
                                self.destroy()
                                _frozen = getattr(sys, "frozen", False)
                                if _frozen:
                                    os.execv(sys.executable, [sys.executable])
                                else:
                                    os.execv(sys.executable, [sys.executable] + sys.argv)
                            self.after(0, _restart)

                        import threading as _t2
                        _t2.Thread(target=_do_pip, daemon=True).start()

                    self.after(0, _ask_and_install)
                    # 설치 완료 전까지 분석은 중단 (창 닫히면서 자연스럽게 종료)
                    return

                # CPU 스레드 최대한 활용
                cpu_count = os.cpu_count() or 4
                torch.set_num_threads(cpu_count)

                # ── 모드별 파라미터 ──────────────────────────────────
                _mode = getattr(self, "_diarize_mode_var", None)
                _mode = _mode.get() if _mode else "balanced"

                # GPU batch_size: VRAM 여유에 따라 조정 가능
                # CPU batch_size: 1 고정 (메모리/속도 균형)
                if device == "cuda":
                    _MODE_CFG = {
                        #           model               beam  batch
                        "fast":     ("large-v3-turbo",  1,    16),
                        "balanced": ("large-v3-turbo",  3,    16),
                        "accurate": ("large-v3",        5,    8),
                        "best":     ("large-v3",        5,    8),
                    }
                else:
                    _MODE_CFG = {
                        "fast":     ("large-v3-turbo",  1,    1),
                        "balanced": ("large-v3-turbo",  3,    1),
                        "accurate": ("large-v3",        5,    1),
                        "best":     ("large-v3",        5,    1),
                    }
                wmodel, beam, _mb = _MODE_CFG.get(_mode, _MODE_CFG["balanced"])
                compute = "float16" if device == "cuda" else "float32"

                # batch_size: GPU → 슬라이더, CPU → 1
                if device == "cuda":
                    _BATCH_MAP = [2, 4, 8, 16, 32]
                    _bidx = getattr(self, "_diarize_batch_var", None)
                    _bidx = _bidx.get() if _bidx else 3
                    batch_size = _BATCH_MAP[max(0, min(_bidx, len(_BATCH_MAP)-1))]
                else:
                    batch_size = 1

                # ── 모델 다운로드 진행 표시 ──────────────────────────────
                # huggingface_hub의 다운로드 콜백으로 실시간 진행률 수신
                _dl_state = {"active": False, "desc": "", "pct": 0.0}

                def _progress_ticker(step_key, est_sec):
                    """0.5초마다 세부 진행률 업데이트."""
                    t0 = _time.time()
                    while _prog_state["running"] and _prog_state["step_key"] == step_key:
                        _tick_progress(step_key, _time.time() - t0, est_sec)
                        _time.sleep(0.5)

                _set_status(f"Whisper 모델 로드 중... ({device} / {wmodel})", "model")
                model = whisperx.load_model(
                    wmodel, device,
                    compute_type=compute,
                    asr_options={"beam_size": beam},
                )

                _set_status("음성 로드 중...", "audio")
                audio = whisperx.load_audio(self.media_path)

                import threading as _threading

                # 오디오 길이 기반 단계별 예상시간 계산
                audio_dur = len(audio) / 16000.0
                if device == "cuda":
                    spd = 20.0 if "turbo" in wmodel else 12.0
                else:
                    spd = 1.5
                _est_transcribe = audio_dur / spd
                _est_align      = audio_dur / 30.0
                _est_diarize    = audio_dur / 8.0
                _prog_state["stage_estimates"] = {
                    "import":    2.0,
                    "model":     15.0,
                    "audio":     3.0,
                    "transcribe": _est_transcribe,
                    "align":     _est_align,
                    "diarize":   _est_diarize,
                    "map":       2.0,
                }

                _set_status("음성 인식 중...", "transcribe")
                _t = _threading.Thread(
                    target=_progress_ticker, args=("transcribe", _est_transcribe), daemon=True)
                _t.start()
                result = model.transcribe(audio, batch_size=batch_size)
                # 인식 모델 즉시 해제
                del model
                if device == "cuda":
                    torch.cuda.empty_cache()

                _set_status("타임스탬프 정렬 중...", "align")
                _t = _threading.Thread(
                    target=_progress_ticker, args=("align", _est_align), daemon=True)
                _t.start()
                model_a, meta = whisperx.load_align_model(
                    language_code=result["language"], device=device)
                result = whisperx.align(
                    result["segments"], model_a, meta, audio, device,
                    return_char_alignments=False,
                )
                # align 모델 즉시 해제 (VRAM/RAM 확보 → diarize 여유 확보)
                del model_a
                if device == "cuda":
                    torch.cuda.empty_cache()

                _set_status("화자 분리 중...", "diarize")
                _t = _threading.Thread(
                    target=_progress_ticker, args=("diarize", _est_diarize), daemon=True)
                _t.start()
                from whisperx.diarize import DiarizationPipeline, assign_word_speakers

                diarize_model = DiarizationPipeline(
                    token=hf_tok,
                    device=device,
                )
                kw = {}
                if num_spk > 0:
                    kw["num_speakers"] = num_spk
                diarize_segments = diarize_model(audio, **kw)

                _set_status("화자 매핑 중...", "map")
                result = assign_word_speakers(diarize_segments, result)

                # 결과를 기존 자막에 매핑
                def _apply():
                    try:
                        _set_status("완료!", "done")
                        prog_win.after(300, prog_win.destroy)
                    except Exception:
                        pass
                    self._apply_diarize_result(result["segments"])

                self.after(0, _apply)

            except ImportError:
                def _err_import():
                    try: prog_win.destroy()
                    except Exception: pass
                    messagebox.showerror("설치 필요",
                        "whisperx가 설치되지 않았습니다.\n\n"
                        "pip install whisperx\n\n"
                        "설치 후 다시 시도하세요.", parent=self)
                self.after(0, _err_import)
            except Exception as e:
                err_msg = str(e)
                def _err():
                    try: prog_win.destroy()
                    except Exception: pass
                    messagebox.showerror("화자 분석 오류", err_msg, parent=self)
                self.after(0, _err)

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_diarize_result(self, segments):
        """WhisperX 결과를 기존 SRT 자막에 화자 매핑으로 적용."""
        if not segments:
            messagebox.showinfo("화자 분석", "분석 결과가 없습니다.", parent=self)
            return

        # WhisperX 세그먼트에서 (start, end, speaker) 추출
        diar = []
        for seg in segments:
            spk = seg.get("speaker", "")
            if spk:
                diar.append((seg["start"], seg["end"], spk))

        if not diar:
            messagebox.showinfo("화자 분석",
                "화자 정보를 추출하지 못했습니다.\n"
                "HuggingFace 토큰과 pyannote 모델 접근 권한을 확인하세요.",
                parent=self)
            return

        # WhisperX 화자 ID → 앱 화자명 매핑 (SPEAKER_00 → 화자 N)
        spk_ids = sorted(set(s for _, _, s in diar))
        spk_map = {}
        n = 1  # 카운터를 루프 밖에서 관리해 sid마다 재초기화되지 않도록 수정
        for sid in spk_ids:
            # 기존 이름과 겹치지 않는 번호 찾기
            while True:
                name = f"화자 {n}"
                if name not in self.speakers:
                    break
                n += 1
            self.speakers.append(name)
            spk_map[sid] = name
            n += 1  # 방금 쓴 번호는 건너뛰어 다음 sid가 중복되지 않도록

        self._push_undo()

        # ── 각 자막에 화자 배정 (가중치 샘플링 방식) ──────────────────
        # 자막 구간을 N개 포인트로 샘플링 → 각 포인트의 화자 구간 매핑 → 가중 투표
        # 경계선 자막에서도 실제 발화 비율대로 화자를 결정
        SAMPLES = 20   # 자막 1개당 샘플 포인트 수 (많을수록 정밀, 성능 미미)

        # diar를 시작시간 기준으로 정렬 → 이진탐색으로 빠른 lookup
        diar_sorted = sorted(diar, key=lambda x: x[0])

        def _spk_at(t):
            """시각 t에 발화 중인 화자 반환. 없으면 None."""
            # 이진탐색: t보다 start가 작거나 같은 마지막 세그먼트 찾기
            lo, hi = 0, len(diar_sorted) - 1
            idx = -1
            while lo <= hi:
                mid = (lo + hi) // 2
                if diar_sorted[mid][0] <= t:
                    idx = mid
                    lo = mid + 1
                else:
                    hi = mid - 1
            if idx >= 0:
                d_s, d_e, d_spk = diar_sorted[idx]
                if d_s <= t <= d_e:
                    return spk_map.get(d_spk, "")
            return None

        cache = getattr(self, "_ts_cache", [])
        for i, (t_s, t_e) in enumerate(cache):
            if t_s is None or t_e is None:
                continue

            dur = t_e - t_s
            if dur <= 0:
                continue

            # 자막 구간을 SAMPLES개 포인트로 샘플링
            # 포인트 간격을 균일하게, 경계 부근 0.05초 가중치 낮춤
            scores: dict[str, float] = {}
            for k in range(SAMPLES):
                # 0~1 사이 균일 분포, 양 끝단은 약간 안쪽으로
                r = (k + 0.5) / SAMPLES
                t = t_s + dur * r

                # 경계 근처(앞 10% / 뒤 10%)는 가중치 0.5로 낮춤 (경계 오류 완화)
                weight = 0.5 if r < 0.10 or r > 0.90 else 1.0

                spk = _spk_at(t)
                if spk:
                    scores[spk] = scores.get(spk, 0.0) + weight

            if scores:
                # 가중치 합이 가장 높은 화자 선택
                best_spk = max(scores, key=scores.__getitem__)
                self.subtitles[i]["speaker"] = best_spk
            else:
                # 겹치는 구간이 아예 없으면 → 중간점 기준 가장 가까운 화자 fallback
                t_mid = (t_s + t_e) / 2
                best_spk  = ""
                best_dist = float("inf")
                for d_s, d_e, d_spk in diar_sorted:
                    d_mid = (d_s + d_e) / 2
                    dist  = abs(t_mid - d_mid)
                    if dist < best_dist:
                        best_dist = dist
                        best_spk  = spk_map.get(d_spk, "")
                if best_spk:
                    self.subtitles[i]["speaker"] = best_spk

        self._unsaved = True
        self._auto_resize_speaker_col()
        self._fill_slots(self._vscroll_top)
        self._render_speakers()
        self._update_count()
        self._wf_img_cache = None
        self._pb_redraw()

        n_mapped = sum(1 for s in self.subtitles if s.get("speaker"))
        messagebox.showinfo("화자 분석 완료",
            f"총 {len(self.subtitles)}개 자막 중 {n_mapped}개에 화자를 배정했습니다.\n"
            f"감지된 화자: {', '.join(spk_map.values())}\n\n"
            "결과를 확인하고 필요하면 수동으로 수정하세요.",
            parent=self)

    # ── 자막 행 렌더 ────────────────────────

    # ── 화자 색상 헬퍼 ───────────────────────
    def _speaker_color(self, name):
        if name in self.speaker_colors:
            return self.speaker_colors[name]
        idx = self.speakers.index(name) if name in self.speakers else 0
        return SPEAKER_COLORS[idx % len(SPEAKER_COLORS)]

    # ── 커스텀 컬러피커 ──────────────────────
    def _pick_speaker_color(self, name, dot_canvas, row_frame):
        current_color = self._speaker_color(name)
        result = _ColorPickerDialog(self, current_color, title=f"{name} 색상 선택").show()
        if result:
            self.speaker_colors[name] = result
            self._render_speakers()
            self._fill_slots(self._vscroll_top)

    # ── 화자 사이드바 렌더 ───────────────────
    def _render_speakers(self):
        for w in self.speaker_inner.winfo_children():
            w.destroy()

        # 화자 해제 단축키 힌트
        tk.Label(self.speaker_inner,
                 text="` = 화자 없음",
                 bg=BG2, fg="#3A3A4A",
                 font=(FONT_FAMILY, 7),
                 anchor="w").pack(fill="x", padx=10, pady=(4, 1))

        if not self.speakers:
            tk.Label(self.speaker_inner, text="화자가 없습니다",
                     bg=BG2, fg=FG_DIM,
                     font=(FONT_FAMILY, 9)).pack(padx=10, pady=4)
            add_row = tk.Frame(self.speaker_inner, bg=BG2)
            add_row.pack(fill="x", padx=6, pady=(2, 6))
            tk.Button(add_row, text="＋  화자 추가",
                      bg=BG2, fg=FG_DIM,
                      font=(FONT_FAMILY, 9), bd=0, relief="flat",
                      cursor="hand2", anchor="w",
                      activebackground=BG3, activeforeground=FG,
                      command=self.add_speaker).pack(fill="x", padx=4, pady=2)
            return

        # 드래그 상태
        self._spk_drag_src = None
        self._spk_drag_ghost = None

        for i, name in enumerate(self.speakers):
            color = self._speaker_color(name)

            row = tk.Frame(self.speaker_inner, bg=BG3,
                           highlightbackground=color, highlightthickness=1)
            row.pack(fill="x", padx=6, pady=3, ipady=2)
            row._spk_name = name
            row._spk_idx  = i

            # 드래그 핸들 (≡)
            drag_lbl = tk.Label(row, text="≡", bg=BG3, fg="#444455",
                                font=(FONT_FAMILY, 10), cursor="fleur")
            drag_lbl.pack(side="left", padx=(4, 0))

            # 단축키 번호 배지 (1~9)
            badge_text = str(i + 1) if i < 9 else ""
            badge = tk.Label(row, text=badge_text, bg=BG3, fg="#555566",
                             font=(FONT_FAMILY, 8), width=1, anchor="center")
            badge.pack(side="left", padx=(2, 0))

            dot_c = tk.Canvas(row, width=14, height=14, bg=BG3,
                              highlightthickness=0, cursor="hand2")
            dot_c.pack(side="left", padx=(4, 2), pady=6)
            dot_c.create_oval(2, 2, 12, 12, fill=color, outline="white", width=1,
                              tags="dot")
            def _dot_click(e, n=name, dc=dot_c, rf=row):
                self._pick_speaker_color(n, dc, rf)
                return "break"
            dot_c.bind("<Button-1>", _dot_click)
            dot_c.bind("<Enter>", lambda e, dc=dot_c: dc.configure(bg="#3A3A3A"))
            dot_c.bind("<Leave>", lambda e, dc=dot_c: dc.configure(bg=BG3))

            name_var = tk.StringVar(value=name)

            # 삭제 버튼·카운트를 right로 먼저 배치 → name_frame이 남은 공간만 차지
            del_btn = tk.Button(row, text="✕", bg=BG3, fg="#FF6B8A",
                      font=(FONT_FAMILY, 10), bd=0, cursor="hand2",
                      activebackground=BG3, activeforeground="#FF6B8A",
                      command=lambda n=name: self.delete_speaker(n))
            del_btn.pack(side="right", padx=(1, 4))

            cnt = sum(1 for s in self.subtitles if s["speaker"] == name)
            cnt_lbl = tk.Label(row, text=str(cnt), bg=BG3, fg=FG_DIM,
                     font=(FONT_FAMILY, 9))
            cnt_lbl.pack(side="right", padx=2)

            # name_frame: 버튼들 배치 후 마지막에 pack → 남은 공간만 차지
            name_frame = tk.Frame(row, bg=BG3)
            name_frame.pack(side="left", fill="x", expand=True, padx=2)

            # Canvas 기반 말줄임 Label — 실제 너비에 맞게 텍스트를 잘라 표시
            name_canvas = tk.Canvas(name_frame, bg=BG3, highlightthickness=0,
                                    height=22, cursor="xterm")
            name_canvas.pack(fill="x", expand=True)
            _name_text_id = name_canvas.create_text(
                4, 11, text=name, fill=color,
                font=(FONT_FAMILY, 10, "bold"), anchor="w")

            def _trim_name(canvas=name_canvas, text_id=_name_text_id,
                           full=name, c=color):
                """캔버스 너비에 맞게 이름을 잘라 … 로 표시."""
                w = canvas.winfo_width()
                if w <= 4:
                    return
                avail = max(10, w - 8)
                try:
                    import tkinter.font as tkfont
                    f = tkfont.Font(font=(FONT_FAMILY, 10, "bold"))
                    if f.measure(full) <= avail:
                        canvas.itemconfigure(text_id, text=full)
                        return
                    lo, hi = 0, len(full)
                    while lo < hi:
                        mid = (lo + hi + 1) // 2
                        if f.measure(full[:mid] + "…") <= avail:
                            lo = mid
                        else:
                            hi = mid - 1
                    canvas.itemconfigure(text_id, text=full[:lo] + "…" if lo < len(full) else full)
                except Exception:
                    canvas.itemconfigure(text_id, text=full)

            name_canvas.bind("<Configure>", lambda e, fn=_trim_name: fn())

            entry = tk.Entry(name_frame, textvariable=name_var,
                             bg="#2A2A2A", fg=color, insertbackground=color,
                             font=(FONT_FAMILY, 10, "bold"), relief="flat",
                             highlightthickness=1, highlightbackground=color,
                             highlightcolor=color)

            def _start_edit(e, canvas=name_canvas, entry=entry, var=name_var):
                if e.widget is not canvas:
                    return
                canvas.pack_forget()
                var.set(name)
                entry.pack(fill="x", expand=True, ipady=2)
                entry.focus_set(); entry.select_range(0, "end")

            def _commit_edit(e, old=name, var=name_var,
                             canvas=name_canvas, entry=entry, trim=_trim_name):
                new = var.get().strip()
                entry.pack_forget()
                if new and new != old and new not in self.speakers:
                    self.rename_speaker(old, new); return
                var.set(old)
                canvas.pack(fill="x", expand=True)
                self.after(10, trim)

            def _on_entry_key(e, old=name, var=name_var,
                              canvas=name_canvas, entry=entry, trim=_trim_name):
                if e.keysym == "Return":
                    _commit_edit(e, old, var, canvas, entry, trim)
                elif e.keysym == "Escape":
                    var.set(old); entry.pack_forget()
                    canvas.pack(fill="x", expand=True)
                    self.after(10, trim)

            name_canvas.bind("<Button-1>", _start_edit)
            entry.bind("<FocusOut>", _commit_edit)
            entry.bind("<KeyPress>", _on_entry_key)

            for widget in [row, cnt_lbl]:
                widget.bind("<Button-1>",
                    lambda e, n=name: self._assign_speaker_from_sidebar(n))

            # 드래그 바인딩 (핸들에만)
            drag_lbl.bind("<ButtonPress-1>",   lambda e, r=row: self._spk_drag_start(e, r))
            drag_lbl.bind("<B1-Motion>",        self._spk_drag_motion)
            drag_lbl.bind("<ButtonRelease-1>", self._spk_drag_end)

            # 툴팁 — 위젯별 개별 힌트
            key_hint = f"  단축키: {i+1}" if i < 9 else ""
            Tooltip(row,      f"클릭 → 선택된 자막에 '{name}' 지정{key_hint}", delay=600)
            Tooltip(drag_lbl, "위아래로 드래그해 화자 순서 변경", delay=400)
            Tooltip(dot_c,    f"클릭 → '{name}' 색상 변경", delay=400)
            Tooltip(del_btn, f"'{name}' 화자 삭제", delay=400)

        # 목록 마지막에 '+ 화자 추가' 버튼
        add_row = tk.Frame(self.speaker_inner, bg=BG2)
        add_row.pack(fill="x", padx=6, pady=(2, 6))
        add_btn = tk.Button(add_row, text="＋  화자 추가",
                            bg=BG2, fg=FG_DIM,
                            font=(FONT_FAMILY, 9), bd=0, relief="flat",
                            cursor="hand2", anchor="w",
                            activebackground=BG3, activeforeground=FG,
                            command=self.add_speaker)
        add_btn.pack(fill="x", padx=4, pady=2)

    # ── 화자 드래그 순서 변경 ─────────────────
    def _spk_drag_start(self, event, row):
        self._spk_drag_src = row._spk_idx
        self._spk_drag_y0  = event.y_root
        # 고스트: 반투명 Toplevel
        g = tk.Toplevel(self)
        g.overrideredirect(True)
        g.attributes("-alpha", 0.7)
        g.attributes("-topmost", True)
        lbl = tk.Label(g, text=row._spk_name, bg=BG3,
                       fg=self._speaker_color(row._spk_name),
                       font=(FONT_FAMILY, 10, "bold"), padx=12, pady=4,
                       relief="solid", bd=1)
        lbl.pack()
        g.geometry(f"+{event.x_root+10}+{event.y_root+10}")
        self._spk_drag_ghost = g

    def _spk_drag_motion(self, event):
        if self._spk_drag_ghost:
            self._spk_drag_ghost.geometry(
                f"+{event.x_root+10}+{event.y_root+10}")

    def _spk_drag_end(self, event):
        if self._spk_drag_ghost:
            self._spk_drag_ghost.destroy()
            self._spk_drag_ghost = None
        if self._spk_drag_src is None:
            return

        # 드롭 위치: speaker_inner 내부 row들 중 y_root와 가장 가까운 것
        src = self._spk_drag_src
        dst = src
        best = float("inf")
        for child in self.speaker_inner.winfo_children():
            if not hasattr(child, "_spk_idx"):
                continue
            cy = child.winfo_rooty() + child.winfo_height() // 2
            dist = abs(event.y_root - cy)
            if dist < best:
                best = dist
                dst = child._spk_idx

        self._spk_drag_src = None
        if src == dst:
            return

        # 순서 변경
        self._push_undo()
        spk = self.speakers.pop(src)
        self.speakers.insert(dst, spk)
        self._unsaved = True
        self._render_speakers()
        self._fill_slots(self._vscroll_top)

    def _on_speaker_key(self, event):
        """화자 지정 단축키: ` → (없음), 1~9 → 해당 번호 화자.
        항상 현재 선택된 행(_selected_rows)에 적용."""
        if isinstance(self.focus_get(), tk.Entry):
            return
        key = event.keysym
        if key == "grave":
            val = ""
        elif key.isdigit() and key != "0":
            spk_idx = int(key) - 1
            if spk_idx >= len(self.speakers):
                return
            val = self.speakers[spk_idx]
        else:
            return

        selected = getattr(self, "_selected_rows", set())
        focused  = getattr(self, "_last_focused_idx", None)
        if selected:
            targets = sorted(selected)
        elif focused is not None and focused < len(self.subtitles):
            targets = [focused]
        else:
            return

        if not targets:
            return

        self._push_undo()
        for idx in targets:
            if idx < len(self.subtitles):
                self.subtitles[idx]["speaker"] = val
                self._refresh_row(idx)
        self._unsaved = True
        self._render_speakers()
        return "break"

    def _assign_speaker_from_sidebar(self, name):
        idx = getattr(self, "_last_focused_idx", None)
        if idx is None or idx >= len(self.subtitles):
            return
        self._push_undo()
        self.subtitles[idx]["speaker"] = name
        self._unsaved = True
        self._refresh_row(idx)
        self._render_speakers()

    def _rebuild_ts_cache(self):
        """subtitles의 타임스탬프를 float으로 미리 파싱해 캐시."""
        cache = []
        for sub in self.subtitles:
            ts = sub.get("timestamp", "")
            parts = ts.split("-->")
            if len(parts) == 2:
                t_s = self._ts_to_sec(parts[0])
                t_e = self._ts_to_sec(parts[1])
            else:
                t_s = t_e = None
            cache.append((t_s, t_e))
        self._ts_cache = cache


    # ── 자막 테이블 (가상 스크롤) ─────────────
    # 컬럼 정의: num / ts_s / ts_e / content(가변) / speaker / del
    _WF_HANDLE_W = 5   # 파형 자막 핸들 너비(px)
    _COL_IDS   = ["num", "ts_s", "ts_e", "speaker"]
    _COL_DEF_W = {"num": 40, "ts_s": 132, "ts_e": 132, "speaker": 220}
    ROW_H      = 34   # 행 높이 (px)
    _VSCROLL_BUF = 3  # 뷰포트 위아래로 미리 만들어둘 여분 행 수

    def _build_table(self, parent):
        right = ttk.Frame(parent)
        right.pack(fill="both", expand=True)

        self._col_w = dict(self._COL_DEF_W)
        self._drag_col = None
        self._drag_x0  = 0
        self._drag_w0  = 0

        # ── 헤더 Canvas ───────────────────────
        hdr_c = tk.Canvas(right, bg=BG2, height=28, highlightthickness=0)
        hdr_c.pack(fill="x")
        self._hdr_canvas = hdr_c

        _titles = {"num":"#","ts_s":"시작시간","ts_e":"종료시간",
                   "content":"자막 내용","speaker":"화자"}
        self._hdr_wins = {}
        for cid in list(self._COL_IDS) + ["content"]:
            lbl = tk.Label(hdr_c, text=_titles[cid],
                           bg=BG2, fg=FG_DIM,
                           font=(FONT_FAMILY, 9, "bold"), anchor="w")
            win_id = hdr_c.create_window(0, 14, window=lbl, anchor="w",
                                         height=20, width=10)
            self._hdr_wins[cid] = (lbl, win_id)

        hdr_c.bind("<Configure>",      lambda e: self._layout_header())
        hdr_c.bind("<Motion>",         self._hdr_motion)
        hdr_c.bind("<ButtonPress-1>",  self._hdr_press)
        hdr_c.bind("<B1-Motion>",      self._hdr_b1motion)
        hdr_c.bind("<ButtonRelease-1>",self._hdr_release)

        # ── 가상 스크롤 Canvas ────────────────
        container = tk.Frame(right, bg=BG)
        container.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(container, bg=BG, highlightthickness=0, bd=0)
        self.vsb    = ttk.Scrollbar(container, orient="vertical",
                                    command=self._vscroll_cmd)

        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vsb.pack(side="right", fill="y")

        # 가상 스크롤 상태
        self._vscroll_top   = 0
        self._slot_frames   = []
        self._slot_data     = []
        self._slot_widgets  = []
        self._last_canvas_w = 0
        self._layout_debounce_job = None
        self._pill_defer_job = None   # 스크롤 중 pill 갱신 지연 job
        self._pill_slot_count = 0   # 슬롯 생성 시 pill을 몇 개 만들었는지

        self.canvas.bind("<Configure>",      self._on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        # 캔버스 레벨 드래그 선택 (슬롯 경계를 넘어도 동작)
        self.canvas.bind("<ButtonPress-1>",   self._canvas_drag_start)
        self.canvas.bind("<B1-Motion>",       self._canvas_drag_motion)
        self.canvas.bind("<ButtonRelease-1>", self._canvas_drag_end)
        self._drag_sel_active  = False   # 드래그 범위선택 진행 중
        self._drag_sel_anchor  = None    # 드래그 시작 자막 인덱스
        self._drag_autoscroll_job = None

        # 가상 스크롤용 더미 프레임 (scrollregion 설정 목적)
        # 실제 내용은 canvas window로 절대좌표 배치
        self._vport_frame = tk.Frame(self.canvas, bg=BG)
        self._vport_win   = self.canvas.create_window(
            (0, 0), window=self._vport_frame, anchor="nw", width=1, height=1)

        # 행 위젯 참조 (가상 스크롤 - 인덱스별 위젯 접근용 캐시)
        # _slot_frames[슬롯] → 위젯, _slot_data[슬롯] → 자막 인덱스
        self._row_widgets = []   # 하위호환: 사용하지 않음, 항상 []

    # ── 가상 스크롤 핵심 ─────────────────────

    def _vscroll_cmd(self, *args):
        action = args[0]
        if action == "moveto":
            frac = float(args[1])
            n = len(self.subtitles)
            if n == 0:
                return
            new_first = int(frac * n * self.ROW_H // self.ROW_H)
            self._vscroll_to(new_first)
        elif action == "scroll":
            amount = int(args[1])
            unit   = args[2]
            if unit == "units":
                self._vscroll_to(self._vscroll_top + amount)
            elif unit == "pages":
                visible = max(1, self.canvas.winfo_height() // self.ROW_H)
                self._vscroll_to(self._vscroll_top + amount * visible)

    def _on_mousewheel(self, event):
        # 재생바 패널 위면 seek, 그 외엔 자막 스크롤
        try:
            mp = self._media_panel
            if (mp.winfo_rooty() <= event.y_root
                    <= mp.winfo_rooty() + mp.winfo_height()):
                self._wf_mousewheel(event)
                return
        except Exception:
            pass
        delta = -1 if event.delta > 0 else 1
        self._vscroll_to(self._vscroll_top + delta)

    def _vscroll_to(self, first_idx, offset_y=None):
        """first_idx 행을 맨 위에 표시하도록 스크롤."""
        n = len(self.subtitles)
        if n == 0:
            return
        first_idx = max(0, min(first_idx, n - 1))
        if first_idx == self._vscroll_top:
            return
        self._vscroll_top = first_idx
        self._ensure_slots()
        self._fill_slots(first_idx)

        total_h = n * self.ROW_H
        ch = max(1, self.canvas.winfo_height())
        top_frac = (first_idx * self.ROW_H) / total_h
        bot_frac = min(1.0, top_frac + ch / total_h)
        self.vsb.set(top_frac, bot_frac)

    def _needed_slots(self):
        """현재 캔버스 높이 기준 필요한 슬롯 수."""
        ch = self.canvas.winfo_height()
        if ch <= 1:
            ch = 600
        return (ch // self.ROW_H) + self._VSCROLL_BUF * 2 + 2

    def _ensure_slots(self):
        """필요한 수만큼 슬롯(재사용 Frame)을 확보."""
        needed = self._needed_slots()
        while len(self._slot_frames) < needed:
            self._create_slot()

    def _create_slot(self):
        """빈 행 Frame과 내부 위젯을 한 세트 생성해 풀에 추가."""
        slot_idx = len(self._slot_frames)
        h   = self.ROW_H
        pos = self._get_col_positions()

        row = tk.Frame(self.canvas, bg=ROW_EVEN, height=h)
        row.pack_propagate(False)

        wi = {}  # cid → widget

        # 번호
        num_lbl = tk.Label(row, text="", bg=ROW_EVEN, fg=FG_DIM,
                           font=(FONT_FAMILY, 9), anchor="center", cursor="hand2")
        num_lbl.place(x=0, y=0, width=self._col_w["num"], height=h)
        wi["num"] = num_lbl

        # 타임스탬프 시작
        ts_s_var = tk.StringVar()
        ts_s = tk.Entry(row, textvariable=ts_s_var,
                        bg=BG3, fg=ACCENT, insertbackground=FG,
                        font=(FONT_MONO, 9), relief="flat",
                        highlightthickness=1, highlightbackground=BORDER,
                        highlightcolor=ACCENT)
        ts_s.place(x=self._col_w["num"], y=3,
                   width=self._col_w["ts_s"], height=h - 6)
        wi["ts_s"] = ts_s
        wi["ts_s_var"] = ts_s_var

        # 타임스탬프 종료
        ts_e_var = tk.StringVar()
        ts_e = tk.Entry(row, textvariable=ts_e_var,
                        bg=BG3, fg=ACCENT, insertbackground=FG,
                        font=(FONT_MONO, 9), relief="flat",
                        highlightthickness=1, highlightbackground=BORDER,
                        highlightcolor=ACCENT)
        x_ts_e = self._col_w["num"] + self._col_w["ts_s"]
        ts_e.place(x=x_ts_e, y=3, width=self._col_w["ts_e"], height=h - 6)
        wi["ts_e"] = ts_e
        wi["ts_e_var"] = ts_e_var

        # 내용
        cx, cw_ = pos["content"]
        txt_var = tk.StringVar()
        txt_e = tk.Entry(row, textvariable=txt_var,
                         bg=BG3, fg=FG, insertbackground=FG,
                         font=(FONT_FAMILY, 10), relief="flat",
                         highlightthickness=1, highlightbackground=BORDER,
                         highlightcolor=ACCENT)
        txt_e.place(x=cx, y=3, width=cw_, height=h - 6)
        wi["content"] = txt_e
        wi["txt_var"] = txt_var

        # 화자 pill — 슬롯 생성 시 현재 화자 수 + 1(없음) 만큼 미리 생성
        sx = pos["speaker"][0]
        spk_frame = tk.Frame(row, bg=ROW_EVEN)
        spk_frame.place(x=sx, y=0, width=self._col_w["speaker"], height=h)
        wi["speaker"] = spk_frame

        pill_labels = []
        n_pills = len(self.speakers) + 1   # (없음) + 화자들
        for pi in range(max(n_pills, 8)):   # 최소 8개 확보 (화자 추가 시 여유)
            lbl = tk.Label(spk_frame, text="", bg=ROW_EVEN,
                           fg=FG_DIM, font=(FONT_FAMILY, 9),
                           padx=7, pady=2, cursor="hand2",
                           relief="flat", highlightthickness=1,
                           highlightbackground="#2A2A2A")
            lbl.pack_forget()   # 초기엔 숨김, _update_slot_pills에서 필요한 것만 pack
            lbl.bind("<Button-1>", lambda e, s=slot_idx, p=pi: self._slot_pill_click(s, p))
            pill_labels.append(lbl)
        wi["pills"] = pill_labels
        wi["pill_values"] = [""] * len(pill_labels)   # 각 pill이 나타내는 화자값 캐시

        wi["_row_frame"] = row

        # 이벤트: 슬롯 인덱스 기준 → _slot_data로 실제 인덱스 조회
        # B1-Motion은 캔버스 좌표로 변환해 _canvas_drag_motion에 위임
        def _relay_press(e, s=slot_idx):
            self._slot_click(s, e)
            # 드래그 앵커를 현재 자막으로 설정
            di = self._slot_data_idx(s)
            if di >= 0:
                self._drag_sel_anchor = di
                self._drag_sel_active = False
        def _relay_motion(e):
            # 위젯 좌표 → 캔버스 절대 좌표로 변환
            cy = e.widget.winfo_rooty() + e.y - self.canvas.winfo_rooty()
            class _FakeEvent: pass
            fe = _FakeEvent(); fe.y = cy
            self._canvas_drag_motion(fe)
        def _relay_release(e):
            self._canvas_drag_end(e)

        row.bind("<Button-1>",         _relay_press)
        row.bind("<Shift-Button-1>",   lambda e, s=slot_idx: self._slot_shift_click(s))
        row.bind("<B1-Motion>",        _relay_motion)
        row.bind("<ButtonRelease-1>",  _relay_release)
        row.bind("<Button-3>",         lambda e, s=slot_idx: self._slot_right_click(s, e))
        num_lbl.bind("<Button-1>",     _relay_press)
        num_lbl.bind("<Shift-Button-1>",lambda e, s=slot_idx: self._slot_shift_click(s))
        num_lbl.bind("<B1-Motion>",    _relay_motion)
        num_lbl.bind("<ButtonRelease-1>", _relay_release)
        num_lbl.bind("<Button-3>",     lambda e, s=slot_idx: self._slot_right_click(s, e))
        spk_frame.bind("<Button-1>",   lambda e, s=slot_idx: self._slot_click(s, e))
        spk_frame.bind("<Shift-Button-1>", lambda e, s=slot_idx: self._slot_shift_click(s))
        spk_frame.bind("<B1-Motion>",  _relay_motion)
        spk_frame.bind("<ButtonRelease-1>", _relay_release)
        spk_frame.bind("<Button-3>",   lambda e, s=slot_idx: self._slot_right_click(s, e))

        def _ts_commit(s=slot_idx):
            di = self._slot_data[s] if s < len(self._slot_data) else -1
            if di < 0 or di >= len(self.subtitles):
                return
            sv = self._slot_widgets[s]["ts_s_var"].get().strip()
            ev = self._slot_widgets[s]["ts_e_var"].get().strip()
            se = self._slot_widgets[s]["ts_s"]
            ee = self._slot_widgets[s]["ts_e"]
            self._ts_style(se, sv); self._ts_style(ee, ev)
            if self._ts_valid(sv) and self._ts_valid(ev):
                self.subtitles[di]["timestamp"] = f"{sv} --> {ev}"
                self._unsaved = True
                if hasattr(self, "_ts_cache") and di < len(self._ts_cache):
                    self._ts_cache[di] = (self._ts_to_sec(sv), self._ts_to_sec(ev))

        def _ts_key(e, s=slot_idx):
            wi2 = self._slot_widgets[s]
            self._ts_style(wi2["ts_s"], wi2["ts_s_var"].get())
            self._ts_style(wi2["ts_e"], wi2["ts_e_var"].get())

        for ent in (ts_s, ts_e):
            ent.bind("<Return>",     lambda e, f=_ts_commit: f())
            ent.bind("<FocusOut>",   lambda e, f=_ts_commit: f())
            ent.bind("<KeyRelease>", _ts_key)

        txt_e.bind("<FocusOut>", lambda e, s=slot_idx: self._slot_save_text(s))
        txt_e.bind("<Return>",   lambda e, s=slot_idx: self._slot_save_text(s))
        txt_e.bind("<FocusIn>",  lambda e, s=slot_idx: self._slot_focus_in(s))

        # Canvas에 window 배치 (나중에 y좌표 갱신)
        win_id = self.canvas.create_window(
            0, 0, window=row, anchor="nw", width=1, height=h)
        wi["_win_id"] = win_id

        self._slot_frames.append(row)
        self._slot_data.append(-1)
        self._slot_widgets.append(wi)

    # ── 슬롯 이벤트 핸들러 ───────────────────

    def _slot_data_idx(self, slot_idx):
        if slot_idx < len(self._slot_data):
            return self._slot_data[slot_idx]
        return -1

    def _slot_click(self, slot_idx, event=None):
        """좌클릭: 단독 선택 (Ctrl이면 토글)."""
        di = self._slot_data_idx(slot_idx)
        if di < 0:
            return
        if event and (event.state & 0x4):   # Ctrl
            self._toggle_select(di)
        else:
            self._select_row(di)
        self._blur_all_entries()

    def _slot_right_click(self, slot_idx, event):
        """우클릭: 해당 행 선택 후 컨텍스트 메뉴 표시."""
        di = self._slot_data_idx(slot_idx)
        if di < 0:
            return
        # 선택 안 된 행이면 단독 선택, 이미 선택된 행이면 다중 선택 유지
        if di not in getattr(self, "_selected_rows", set()):
            self._select_row(di)
        self._show_context_menu(event, di)

    def _show_context_menu(self, event, anchor_idx):
        """자막 행 컨텍스트 메뉴."""
        MENU_BG     = BG3
        MENU_FG     = FG
        MENU_ACT_BG = ACCENT
        MENU_DIM    = FG_DIM

        def make_menu(parent=None):
            return tk.Menu(
                parent or self, tearoff=0,
                bg=MENU_BG, fg=MENU_FG,
                activebackground=MENU_ACT_BG, activeforeground="white",
                disabledforeground=MENU_DIM,
                relief="flat", bd=0,
                font=(FONT_FAMILY, 9),
                activeborderwidth=0,
                selectcolor=ACCENT,
            )

        menu = make_menu()

        sel = sorted(getattr(self, "_selected_rows", set()) or {anchor_idx})
        n   = len(sel)
        s   = f" ({n}개)" if n > 1 else ""

        # ── 편집 ──────────────────────────────
        menu.add_command(label=f"잘라내기{s}",
                         accelerator="Ctrl+X",
                         command=lambda: self._on_cut(None))
        menu.add_command(label=f"복사{s}",
                         accelerator="Ctrl+C",
                         command=lambda: self._on_copy(None))
        clips = self._clipboard if isinstance(self._clipboard, list) else (
                [self._clipboard] if self._clipboard else [])
        menu.add_command(
            label=f"붙여넣기" + (f" ({len(clips)}개)" if clips else ""),
            accelerator="Ctrl+V",
            state="normal" if clips else "disabled",
            command=lambda: self._on_paste(None))
        menu.add_separator()

        # ── 행 추가/삭제 ──────────────────────
        menu.add_command(label="위에 행 추가",
                         command=lambda: self.add_row(after_idx=anchor_idx - 1))
        menu.add_command(label="아래에 행 추가",
                         command=lambda: self.add_row(after_idx=anchor_idx))
        menu.add_separator()
        menu.add_command(label=f"삭제{s}",
                         accelerator="Del",
                         command=lambda: self._on_delete())
        menu.add_separator()

        # ── 화자 변경 ─────────────────────────
        if self.speakers:
            spk_menu = make_menu(menu)
            spk_menu.add_command(label="(없음)",
                                 accelerator="`",
                                 command=lambda: self._ctx_set_speaker(""))
            spk_menu.add_separator()
            for i, spk in enumerate(self.speakers):
                spk_menu.add_command(
                    label=spk,
                    accelerator=str(i+1) if i < 9 else "",
                    foreground=self._speaker_color(spk),
                    activeforeground=self._speaker_color(spk),
                    command=lambda s=spk: self._ctx_set_speaker(s))
            menu.add_cascade(label=f"화자 변경{s}", menu=spk_menu)
            menu.add_separator()

        # ── 타임스탬프 ────────────────────────
        has_media = bool(self.media_path)
        menu.add_command(label="재생 위치 → 시작점",
                         state="normal" if has_media else "disabled",
                         command=lambda: self._ctx_set_timestamp_start(anchor_idx))
        menu.add_command(label="재생 위치 → 종료점",
                         state="normal" if has_media else "disabled",
                         command=lambda: self._ctx_set_timestamp_end(anchor_idx))

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _ctx_set_speaker(self, val):
        """컨텍스트 메뉴에서 화자 설정 — 다중 선택 일괄 적용."""
        targets = self._selected_targets()
        if not targets:
            return
        self._push_undo()
        for idx in targets:
            if idx < len(self.subtitles):
                self.subtitles[idx]["speaker"] = val
                self._redraw_slot_for(idx)
        self._unsaved = True
        self._render_speakers()

    def _ctx_set_timestamp_start(self, idx):
        """재생 위치를 해당 자막의 시작 타임스탬프로 설정."""
        if not self.media_path or idx >= len(self.subtitles):
            return
        pos = self.media_progress_var.get()
        ts  = self.subtitles[idx]["timestamp"]
        parts = ts.split("-->")
        if len(parts) != 2:
            return
        def _fmt(sec):
            h=int(sec//3600); m=int((sec%3600)//60); s=int(sec%60)
            ms=int(round((sec%1)*1000))
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
        self._push_undo()
        self.subtitles[idx]["timestamp"] = f"{_fmt(pos)} --> {parts[1].strip()}"
        self._ts_cache[idx] = (pos, self._ts_cache[idx][1])
        self._unsaved = True
        self._redraw_slot_for(idx)
        self._wf_img_cache = None
        self._pb_redraw()

    def _ctx_set_timestamp_end(self, idx):
        """재생 위치를 해당 자막의 종료 타임스탬프로 설정."""
        if not self.media_path or idx >= len(self.subtitles):
            return
        pos = self.media_progress_var.get()
        ts  = self.subtitles[idx]["timestamp"]
        parts = ts.split("-->")
        if len(parts) != 2:
            return
        def _fmt(sec):
            h=int(sec//3600); m=int((sec%3600)//60); s=int(sec%60)
            ms=int(round((sec%1)*1000))
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
        self._push_undo()
        self.subtitles[idx]["timestamp"] = f"{parts[0].strip()} --> {_fmt(pos)}"
        self._ts_cache[idx] = (self._ts_cache[idx][0], pos)
        self._unsaved = True
        self._redraw_slot_for(idx)
        self._wf_img_cache = None
        self._pb_redraw()
        di = self._slot_data_idx(slot_idx)
        if di < 0:
            return
        # Ctrl+클릭: 토글 추가/제거
        if event and (event.state & 0x4):
            self._toggle_select(di)
        else:
            self._select_row(di)
        self._blur_all_entries()

    def _slot_shift_click(self, slot_idx):
        """Shift+클릭: anchor부터 현재까지 범위 선택."""
        di = self._slot_data_idx(slot_idx)
        if di < 0:
            return
        anchor = getattr(self, "_selected_row_idx", None)
        if anchor is None:
            self._select_row(di)
            return
        lo, hi = min(anchor, di), max(anchor, di)
        old = set(self._selected_rows) | {anchor}
        self._selected_rows = set(range(lo, hi + 1))
        self._selected_row_idx = anchor
        self._last_focused_idx = di
        # 변경된 슬롯만 재렌더
        for idx in old.symmetric_difference(self._selected_rows):
            self._redraw_slot_for(idx)

    def _slot_drag(self, slot_idx, event):
        """드래그 중: 시작 행부터 현재 행까지 범위 선택."""
        di = self._slot_data_idx(slot_idx)
        if di < 0:
            return
        anchor = getattr(self, "_selected_row_idx", None)
        if anchor is None:
            return
        lo, hi = min(anchor, di), max(anchor, di)
        new_sel = set(range(lo, hi + 1))
        if new_sel == self._selected_rows:
            return
        old = set(self._selected_rows)
        self._selected_rows = new_sel
        self._last_focused_idx = di
        for idx in old.symmetric_difference(new_sel):
            self._redraw_slot_for(idx)

    # ── Canvas 레벨 드래그 범위 선택 ───────────
    def _canvas_y_to_idx(self, y):
        """캔버스 Y 좌표 → 자막 인덱스. 범위 밖이면 클램프."""
        idx = self._vscroll_top + int(y // self.ROW_H)
        return max(0, min(idx, len(self.subtitles) - 1))

    def _canvas_drag_start(self, event):
        """캔버스 빈 공간 클릭 시 드래그 선택 시작 준비."""
        # 슬롯 위젯 위 클릭이면 슬롯 핸들러가 처리 — 여기서는 anchor만 기억
        if not self.subtitles:
            return
        self._drag_sel_anchor = self._canvas_y_to_idx(event.y)
        self._drag_sel_active = False   # motion 이 일어날 때 활성화

    def _canvas_drag_motion(self, event):
        """드래그 중 Y 좌표로 범위 선택 갱신 + 경계 자동 스크롤."""
        if self._drag_sel_anchor is None or not self.subtitles:
            return
        self._drag_sel_active = True
        anchor = self._drag_sel_anchor
        cur    = self._canvas_y_to_idx(event.y)
        lo, hi = min(anchor, cur), max(anchor, cur)
        new_sel = set(range(lo, hi + 1))

        if new_sel != self._selected_rows or self._selected_row_idx != anchor:
            old = set(self._selected_rows)
            self._selected_rows    = new_sel
            self._selected_row_idx = anchor
            self._last_focused_idx = cur
            for idx in old.symmetric_difference(new_sel):
                self._redraw_slot_for(idx)

        # 경계 자동 스크롤
        ch = self.canvas.winfo_height()
        margin = self.ROW_H
        if event.y < margin and self._vscroll_top > 0:
            self._vscroll_to(self._vscroll_top - 1)
            self._schedule_autoscroll(-1)
        elif event.y > ch - margin:
            self._vscroll_to(self._vscroll_top + 1)
            self._schedule_autoscroll(+1)
        else:
            self._cancel_autoscroll()

    def _canvas_drag_end(self, event):
        self._drag_sel_active = False
        self._drag_sel_anchor = None
        self._cancel_autoscroll()

    def _schedule_autoscroll(self, direction):
        """드래그 중 경계에서 100ms마다 한 행씩 자동 스크롤."""
        self._cancel_autoscroll()
        def _tick():
            if self._drag_sel_active:
                self._vscroll_to(self._vscroll_top + direction)
                self._drag_autoscroll_job = self.after(100, _tick)
        self._drag_autoscroll_job = self.after(100, _tick)

    def _cancel_autoscroll(self):
        if self._drag_autoscroll_job:
            self.after_cancel(self._drag_autoscroll_job)
            self._drag_autoscroll_job = None

    def _toggle_select(self, idx):
        """Ctrl+클릭: 해당 행 선택/해제 토글."""
        if idx in self._selected_rows:
            self._selected_rows.discard(idx)
            if self._selected_row_idx == idx:
                self._selected_row_idx = next(iter(self._selected_rows), None)
        else:
            self._selected_rows.add(idx)
            self._selected_row_idx = idx
            self._last_focused_idx = idx
        self._redraw_slot_for(idx)

    def _slot_save_text(self, slot_idx):
        di = self._slot_data_idx(slot_idx)
        if di < 0 or di >= len(self.subtitles):
            return
        val = self._slot_widgets[slot_idx]["txt_var"].get()
        self.subtitles[di]["text"] = val
        self._unsaved = True

    def _slot_focus_in(self, slot_idx):
        di = self._slot_data_idx(slot_idx)
        if di < 0:
            return
        self._last_focused_idx = di
        self._select_row(di)

    def _slot_delete(self, slot_idx):
        di = self._slot_data_idx(slot_idx)
        if di < 0:
            return
        self.delete_row(di)

    def _slot_pill_click(self, slot_idx, pill_idx):
        """pill 클릭 → 해당 슬롯의 자막에 화자 지정."""
        di = self._slot_data_idx(slot_idx)
        if di < 0 or di >= len(self.subtitles):
            return
        val = self._slot_widgets[slot_idx]["pill_values"][pill_idx]
        self._pill_select(di, val)

    # ── 슬롯 데이터 채우기 ───────────────────

    def _fill_slots(self, first_idx, defer_pills=False):
        """first_idx 행부터 슬롯 수만큼 데이터를 채워 화면에 표시."""
        n       = len(self.subtitles)
        h       = self.ROW_H
        n_slots = len(self._slot_frames)
        cw      = max(self.canvas.winfo_width(), 100)
        pos     = self._get_col_positions()

        for slot_idx in range(n_slots):
            di = first_idx + slot_idx
            prev_di = self._slot_data[slot_idx]
            self._slot_data[slot_idx] = di if di < n else -1

            wi     = self._slot_widgets[slot_idx]
            win_id = wi["_win_id"]

            if di >= n:
                self.canvas.itemconfigure(win_id, state="hidden")
                continue

            y_screen = slot_idx * h
            self.canvas.itemconfigure(win_id, state="normal", width=cw)
            self.canvas.coords(win_id, 0, y_screen)

            sub     = self.subtitles[di]
            is_sel  = (di == getattr(self, "_selected_row_idx", None) or di in getattr(self, "_selected_rows", set()))
            is_play = (di in getattr(self, "_playing_rows", set()))
            bg = ROW_HL if is_sel else (self.ROW_PLAYING if is_play else
                 (ROW_ODD if di % 2 == 0 else ROW_EVEN))

            row = self._slot_frames[slot_idx]
            wi["num"].configure(text=str(di + 1), bg=bg)

            ts_full  = sub.get("timestamp", "")
            parts    = ts_full.split("-->")
            ts_start = parts[0].strip() if len(parts) >= 2 else ts_full.strip()
            ts_end   = parts[1].strip() if len(parts) >= 2 else ""
            wi["ts_s_var"].set(ts_start)
            wi["ts_e_var"].set(ts_end)
            self._ts_style(wi["ts_s"], ts_start)
            self._ts_style(wi["ts_e"], ts_end)

            # 편집 중인 Entry는 덮어쓰지 않음
            txt_entry = wi.get("content")
            if txt_entry is None or self.focus_get() is not txt_entry:
                wi["txt_var"].set(sub.get("text", ""))
            self._update_slot_pills(slot_idx, sub, bg)

            row.configure(bg=bg)
            wi["num"].configure(bg=bg)
            wi["speaker"].configure(bg=bg)

            self._apply_col_to_slot(slot_idx, pos, cw)

    def _flush_deferred_pills(self, expected_top):
        """스크롤이 멈춘 뒤 호출 — 현재 뷰포트의 pill을 완성."""
        self._pill_defer_job = None
        if self._vscroll_top != expected_top:
            return   # 그 사이 또 스크롤됐으면 다음 flush에 맡김
        for slot_idx, di in enumerate(self._slot_data):
            if di < 0 or di >= len(self.subtitles):
                continue
            sub     = self.subtitles[di]
            is_sel  = (di == getattr(self, "_selected_row_idx", None) or di in getattr(self, "_selected_rows", set()))
            is_play = (di in getattr(self, "_playing_rows", set()))
            bg = ROW_HL if is_sel else (self.ROW_PLAYING if is_play else
                 (ROW_ODD if di % 2 == 0 else ROW_EVEN))
            self._update_slot_pills(slot_idx, sub, bg)

    def _update_slot_bg(self, slot_idx, bg):
        """배경색만 갱신 (데이터 변경 없이 선택/재생 하이라이트 반영)."""
        wi  = self._slot_widgets[slot_idx]
        row = self._slot_frames[slot_idx]
        cur_bg = row.cget("bg")
        if cur_bg == bg:
            return
        row.configure(bg=bg)
        wi["num"].configure(bg=bg)
        wi["speaker"].configure(bg=bg)
        # 스크롤 중 지연 중이면 pill은 flush 때 갱신
        if getattr(self, "_pill_defer_job", None):
            return
        di = self._slot_data[slot_idx]
        if 0 <= di < len(self.subtitles):
            self._update_slot_pills(slot_idx, self.subtitles[di], bg)

    def _update_slot_pills(self, slot_idx, sub, bg):
        """pill Label들을 configure로만 갱신 — destroy/create 없음."""
        wi      = self._slot_widgets[slot_idx]
        pills   = wi["pills"]
        vals    = wi["pill_values"]
        current = sub.get("speaker", "")

        choices = [("", "(없음)")] + [(sp, sp) for sp in self.speakers]

        for pi, lbl in enumerate(pills):
            if pi < len(choices):
                val, label = choices[pi]
                is_sel = (val == current)
                if val == "":
                    color = FG_DIM
                else:
                    color = self._speaker_color(val)
                sel_bg = "#2D2040" if is_sel else bg
                lbl.configure(
                    text=label,
                    bg=sel_bg,
                    fg=color if is_sel else "#444455",
                    font=(FONT_FAMILY, 9, "bold" if is_sel else "normal"),
                    highlightbackground=color if is_sel else "#2A2A2A"
                )
                vals[pi] = val
                # 보이게
                if not lbl.winfo_ismapped():
                    lbl.pack(side="left", padx=2)
            else:
                # 화자 수보다 pill이 많으면 숨김
                if lbl.winfo_ismapped():
                    lbl.pack_forget()
                vals[pi] = ""

    def _apply_col_to_slot(self, slot_idx, pos, cw):
        """단일 슬롯의 컬럼 너비/위치를 pos에 맞게 재배치."""
        wi = self._slot_widgets[slot_idx]
        h  = self.ROW_H
        for cid in list(self._COL_IDS) + ["content"]:
            if cid not in pos or cid not in wi:
                continue
            x, w = pos[cid]
            y_off = 3 if cid in ("ts_s", "ts_e", "content") else 0
            h_use = (h - 6) if cid in ("ts_s", "ts_e", "content") else h
            try:
                wi[cid].place(x=x, y=y_off, width=w, height=h_use)
            except Exception:
                pass

    # ── Canvas 크기 변경 ──────────────────────

    def _on_canvas_configure(self, event):
        w = event.width
        if w == self._last_canvas_w:
            return
        self._last_canvas_w = w
        if self._layout_debounce_job:
            try:
                self.after_cancel(self._layout_debounce_job)
            except Exception:
                pass
        self._layout_debounce_job = self.after(60, self._relayout)

    def _relayout(self):
        """컬럼 너비/슬롯 수 재계산 후 재렌더."""
        self._layout_debounce_job = None
        self._layout_header()
        self._ensure_slots()
        self._fill_slots(self._vscroll_top)

    # ── 컬럼 레이아웃 계산 ────────────────────
    def _get_col_positions(self):
        total = self.canvas.winfo_width()
        if total <= 1:
            total = self.winfo_width() - self._col_w.get("__sidebar__", 230)
        if total <= 1:
            total = 900
        vsb_w = self.vsb.winfo_width() if self.vsb.winfo_width() > 1 else 16
        total = max(total - vsb_w, 200)
        fixed = sum(self._col_w[c] for c in self._COL_IDS)
        content_w = max(60, total - fixed)

        pos = {}
        x = 0
        for cid in ["num", "ts_s", "ts_e"]:
            pos[cid] = (x, self._col_w[cid]); x += self._col_w[cid]
        pos["content"] = (x, content_w);     x += content_w
        pos["speaker"] = (x, self._col_w["speaker"]); x += self._col_w["speaker"]
        return pos

    # ── 헤더 ──────────────────────────────────
    def _layout_header(self):
        c   = self._hdr_canvas
        cw  = c.winfo_width()
        if cw <= 1:
            return
        pos = self._get_col_positions()
        c.delete("div")
        for cid, (lbl, win_id) in self._hdr_wins.items():
            x, w = pos[cid]
            c.coords(win_id, x + 4, 14)
            c.itemconfigure(win_id, width=max(4, w - 8))
        for cid in ["ts_s", "ts_e", "content", "speaker"]:
            x, w = pos[cid]
            dx = x + w
            c.create_line(dx, 3, dx, 25, fill=BORDER, width=2,
                          tags="div", activefill=ACCENT)

    def _hdr_divider_at(self, mx):
        pos = self._get_col_positions()
        for cid in ["ts_s", "ts_e", "content", "speaker"]:
            x, w = pos[cid]
            if abs(mx - (x + w)) <= 5:
                return cid
        return None

    def _hdr_motion(self, e):
        hit = self._hdr_divider_at(e.x)
        self._hdr_canvas.configure(
            cursor="sb_h_double_arrow" if hit else "arrow")

    def _hdr_press(self, e):
        hit = self._hdr_divider_at(e.x)
        if hit:
            self._drag_col = hit
            self._drag_x0  = e.x

    def _hdr_b1motion(self, e):
        if not self._drag_col:
            return
        delta = e.x - self._drag_x0
        if delta == 0:
            return
        self._drag_x0 = e.x
        cid = self._drag_col
        if cid == "content":
            self._col_w["speaker"] = max(60, self._col_w["speaker"] - delta)
        else:
            self._col_w[cid] = max(40, self._col_w[cid] + delta)
        self._layout_header()
        pos = self._get_col_positions()
        cw  = max(self.canvas.winfo_width(), 100)
        # 드래그 중: 위치/크기만 갱신, pill은 숨김 (spk_frame 밖으로 삐져나오는 현상 방지)
        for slot_idx in range(len(self._slot_frames)):
            if self._slot_data[slot_idx] >= 0:
                self._apply_col_to_slot(slot_idx, pos, cw)
                for pill in self._slot_widgets[slot_idx].get("pills", []):
                    try:
                        pill.pack_forget()
                    except Exception:
                        pass

    def _hdr_release(self, e):
        if self._drag_col:
            self._drag_col = None
            self._relayout()   # 여기서 _fill_slots → pill 완전 복원

    # ── 가상 스크롤 scrollregion 갱신 ────────
    def _update_scrollregion(self):
        n = len(self.subtitles)
        total_h = n * self.ROW_H
        cw = max(self.canvas.winfo_width(), 100)
        self.canvas.configure(scrollregion=(0, 0, cw, total_h))

    # ── 타임스탬프 유효성 패턴 ───────────────
    _TS_RE    = re.compile(r"^\d{2}:\d{2}:\d{2}[,\.]\d{3}$")
    _TS_ERR_BG = "#3A1010"

    def _ts_valid(self, val):
        return bool(self._TS_RE.match(val.strip()))

    def _ts_style(self, entry, val):
        ok = self._ts_valid(val)
        entry.configure(bg=BG3 if ok else self._TS_ERR_BG,
                        highlightbackground=BORDER if ok else "#8B1A1A")

    # ── 전체 테이블 재렌더 ───────────────────
    def _render_rows(self):
        self._selected_row_idx = None
        self._vscroll_top = 0
        self._update_scrollregion()
        self._layout_header()
        self._auto_resize_speaker_col()
        self._ensure_slots()
        self._fill_slots(0)
        self._update_count()

    # ── 단일 행 갱신 (화자 pill 재빌드) ──────
    def _refresh_row(self, idx):
        """해당 인덱스가 현재 뷰포트에 있으면 해당 슬롯만 재렌더."""
        self._redraw_slot_for(idx)
        self._update_count()

    def _refresh_row_full(self, idx):
        self._redraw_slot_for(idx)

    def _refresh_speaker_pills(self, idx):
        slot = self._find_slot(idx)
        if slot < 0:
            return
        wi  = self._slot_widgets[slot]
        sub = self.subtitles[idx]
        is_sel  = (idx == getattr(self, "_selected_row_idx", None) or idx in getattr(self, "_selected_rows", set()))
        is_play = (idx in getattr(self, "_playing_rows", set()))
        if is_sel:
            bg = ROW_HL
        elif is_play:
            bg = self.ROW_PLAYING
        else:
            bg = ROW_ODD if idx % 2 == 0 else ROW_EVEN
        self._update_slot_pills(slot, sub, bg)

    def _find_slot(self, data_idx):
        """data_idx를 표시 중인 슬롯 번호 반환. 없으면 -1."""
        for s, di in enumerate(self._slot_data):
            if di == data_idx:
                return s
        return -1

    def _redraw_slot_for(self, data_idx):
        """data_idx가 뷰포트에 있으면 해당 슬롯 갱신."""
        slot = self._find_slot(data_idx)
        if slot < 0:
            return
        # fill_slots의 부분 적용: 해당 슬롯 하나만
        n   = len(self.subtitles)
        h   = self.ROW_H
        cw  = max(self.canvas.winfo_width(), 100)
        pos = self._get_col_positions()

        wi  = self._slot_widgets[slot]
        row = self._slot_frames[slot]
        sub = self.subtitles[data_idx]

        is_sel  = (data_idx == getattr(self, "_selected_row_idx", None) or data_idx in getattr(self, "_selected_rows", set()))
        is_play = (data_idx in getattr(self, "_playing_rows", set()))
        if is_sel:
            bg = ROW_HL
        elif is_play:
            bg = self.ROW_PLAYING
        else:
            bg = ROW_ODD if data_idx % 2 == 0 else ROW_EVEN

        wi["num"].configure(text=str(data_idx + 1), bg=bg)

        ts_full  = sub.get("timestamp", "")
        parts    = ts_full.split("-->")
        ts_start = parts[0].strip() if len(parts) >= 2 else ts_full.strip()
        ts_end   = parts[1].strip() if len(parts) >= 2 else ""
        wi["ts_s_var"].set(ts_start)
        wi["ts_e_var"].set(ts_end)
        self._ts_style(wi["ts_s"], ts_start)
        self._ts_style(wi["ts_e"], ts_end)

        txt_entry = wi.get("content")
        if txt_entry is None or self.focus_get() is not txt_entry:
            wi["txt_var"].set(sub.get("text", ""))

        self._update_slot_pills(slot, sub, bg)

        row.configure(bg=bg)
        wi["num"].configure(bg=bg)
        wi["speaker"].configure(bg=bg)
        self._apply_col_to_slot(slot, pos, cw)

    # ── 행 선택 / 하이라이트 ─────────────────
    def _on_global_click(self, event):
        clicked = event.widget
        # 클릭한 위젯이 어떤 Entry든 포커스 이동만 허용, 나머지는 blur
        if isinstance(clicked, tk.Entry):
            return
        self._blur_all_entries()

    def _blur_all_entries(self):
        """모든 슬롯의 Entry에서 포커스를 제거하고 selection을 즉시 지움."""
        cur = self.focus_get()
        if not isinstance(cur, tk.Entry):
            return
        # selection 즉시 제거
        try:
            cur.selection_clear()
        except Exception:
            pass
        # FocusOut 발생시켜 변경사항 저장
        try:
            cur.event_generate("<FocusOut>")
        except Exception:
            pass
        self.focus_set()

    # 하위호환
    def _blur_content_entry(self):
        self._blur_all_entries()

    def _select_row(self, idx, seek=True):
        """단독 선택 — 다중 선택 해제 후 idx만 선택."""
        prev       = getattr(self, "_selected_row_idx", None)
        old_multi  = set(getattr(self, "_selected_rows", set()))
        self._selected_row_idx = idx
        self._last_focused_idx = idx
        self._selected_rows    = {idx}
        # 이전 선택들 재렌더
        for old_idx in old_multi:
            if old_idx != idx:
                self._redraw_slot_for(old_idx)
        if prev is not None and prev != idx and prev not in old_multi:
            self._redraw_slot_for(prev)
        self._redraw_slot_for(idx)
        if seek:
            self._seek_to_subtitle(idx)
        self._wf_reveal_subtitle(idx)

    def _wf_reveal_subtitle(self, idx):
        """선택한 자막이 현재 파형 뷰포트 밖에 있으면 해당 구간이 보이도록 오프셋 이동."""
        dur = getattr(self.player, "duration", 0)
        if dur <= 0 or self._wf_zoom <= 1.0:
            return
        cache = getattr(self, "_ts_cache", [])
        if idx >= len(cache):
            return
        t_s, t_e = cache[idx]
        if t_s is None or t_e is None:
            return
        r_s = t_s / dur
        r_e = t_e / dur
        start, end = self._wf_view_range()
        # 이미 뷰 안에 있으면 이동 안 함
        if start <= r_s and r_e <= end:
            return
        # 자막 시작점이 뷰 좌측 20% 지점에 오도록
        span = end - start
        new_offset = max(0.0, min(r_s - span * 0.2, 1.0 - span))
        self._wf_offset = new_offset
        self._pb_redraw()

    def _set_row_highlight(self, idx, selected: bool):
        """재생/선택 하이라이트 — 슬롯 재렌더로 처리."""
        self._redraw_slot_for(idx)

    # ── 화자 pill ────────────────────────────
    def _build_speaker_pills(self, parent, idx, sub, row_bg):
        current = sub.get("speaker", "")
        choices = [("", "(없음)")] + [(sp, sp) for sp in self.speakers]
        for val, label in choices:
            is_sel = (val == current)
            if val == "":
                color = FG_DIM; sel_bg = "#2A2A2A"
            else:
                color = self._speaker_color(val); sel_bg = "#2D2040"
            btn = tk.Label(parent, text=label,
                           bg=sel_bg if is_sel else row_bg,
                           fg=color if is_sel else "#444455",
                           font=(FONT_FAMILY, 9, "bold" if is_sel else "normal"),
                           padx=7, pady=2, cursor="hand2",
                           relief="flat", highlightthickness=1,
                           highlightbackground=color if is_sel else "#2A2A2A")
            btn.pack(side="left", padx=2)
            btn.bind("<Button-1>",
                lambda e, v=val, i=idx: self._pill_select(i, v))

    def _auto_resize_speaker_col(self):
        char_w = 8
        pad = 7 * 2 + 4 + 2
        RIGHT_MARGIN = 70   # 마지막 pill 오른쪽 여유 공간 (spk_frame 배경으로 표현)
        max_label_len = max((len(sp) for sp in self.speakers), default=0)
        none_len = len("(없음)")
        pill_w_none = none_len * char_w + pad
        pill_w_spk  = max_label_len * char_w + pad
        needed = pill_w_none + pill_w_spk * len(self.speakers) + 8 + RIGHT_MARGIN
        needed = max(needed, 80)
        if self._col_w["speaker"] != needed:
            self._col_w["speaker"] = needed
            self._layout_header()

    # ── seek ──────────────────────────────────
    def _seek_to_subtitle(self, idx):
        if not self.media_path or idx >= len(self.subtitles):
            return
        ts = self.subtitles[idx]["timestamp"]
        m = re.match(r"(\d+):(\d+):(\d+)[,.](\d+)", ts)
        if not m:
            return
        h, mi, s, ms = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        pos = h * 3600 + mi * 60 + s + ms / 1000.0
        was_playing = self.player.is_playing or self.player._paused
        self.player.seek_to(pos)
        self.media_progress_var.set(pos)
        self.lbl_pos.configure(text=self._fmt_time(pos))
        self._pb_redraw()
        if was_playing:
            self.btn_play.configure(text="⏸")
            self._start_progress_poll()

    def _pill_select(self, sub_idx, val):
        self._push_undo()
        self.subtitles[sub_idx]["speaker"] = val
        self._unsaved = True
        self._refresh_row(sub_idx)
        self._render_speakers()

    # ── 데이터 저장 콜백 ──────────────────────
    def _save_ts(self, idx, var):
        self.subtitles[idx]["timestamp"] = var.get()
        self._unsaved = True

    def _save_text(self, idx, var):
        self.subtitles[idx]["text"] = var.get()
        self._unsaved = True

    # ── 행 삽입/삭제 (데이터만, 뷰는 _render_rows로) ──
    def _insert_row_widget(self, idx, sub):
        """데이터 삽입 후 뷰를 스크롤하여 해당 행이 보이도록."""
        self._update_scrollregion()
        self._scroll_to_row(idx)

    def _remove_row_widget(self, idx):
        """데이터 삭제 후 뷰 갱신."""
        self._update_scrollregion()
        self._fill_slots(self._vscroll_top)

    def _renumber_rows(self, from_idx=0):
        """데이터 변경 후 현재 뷰포트 갱신."""
        self._update_scrollregion()
        self._fill_slots(self._vscroll_top)

    def _scroll_to_row(self, idx):
        """idx 행이 보이도록 가상 스크롤 이동 (중앙 정렬 — 수동 이동용)."""
        n = len(self.subtitles)
        if n == 0 or idx >= n:
            return
        ch = max(1, self.canvas.winfo_height())
        visible_rows = ch // self.ROW_H
        cur_top = self._vscroll_top
        if cur_top <= idx < cur_top + visible_rows:
            return
        new_top = max(0, min(idx - visible_rows // 2, n - 1))
        self._vscroll_to(new_top)

    def _scroll_to_row_paged(self, idx):
        """재생 하이라이트용: idx가 뷰포트 밖이면 페이지(뷰포트 크기) 단위로 한 번 스크롤."""
        n = len(self.subtitles)
        if n == 0 or idx >= n:
            return
        ch = max(1, self.canvas.winfo_height())
        visible_rows = max(1, ch // self.ROW_H)
        cur_top = self._vscroll_top

        if idx < cur_top:
            # 위로 벗어남 → 한 페이지 위로
            new_top = max(0, cur_top - visible_rows)
        elif idx >= cur_top + visible_rows:
            # 아래로 벗어남 → 한 페이지 아래로
            new_top = min(n - 1, cur_top + visible_rows)
        else:
            return  # 이미 보임
        self._vscroll_to(new_top)

    # ── _apply_col_layout_to_rows 하위호환 ───
    def _apply_col_layout_to_rows(self, visible_only=False):
        """가상 스크롤에서는 _relayout으로 위임."""
        self._layout_header()
        self._fill_slots(self._vscroll_top)

    def _row_col_w(self, col_id):
        return self._col_w.get(col_id, self._COL_DEF_W.get(col_id, 80))

    # ── Undo / Redo ───────────────────────────
    _UNDO_MAX = 50

    def _snapshot(self):
        # _col_w도 함께 저장해 undo/redo 시 컬럼 너비가 되돌아가지 않도록 함
        return (copy.deepcopy(self.subtitles), list(self.speakers),
                dict(self.speaker_colors), dict(self._col_w))

    def _push_undo(self):
        self._undo_stack.append(self._snapshot())
        if len(self._undo_stack) > self._UNDO_MAX:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def _undo(self):
        if not self._undo_stack:
            return
        self._redo_stack.append(self._snapshot())
        subs, spks, colors, col_w = self._undo_stack.pop()
        self._apply_snapshot(subs, spks, colors, col_w)

    def _redo(self):
        if not self._redo_stack:
            return
        self._undo_stack.append(self._snapshot())
        subs, spks, colors, col_w = self._redo_stack.pop()
        self._apply_snapshot(subs, spks, colors, col_w)

    def _apply_snapshot(self, new_subs, new_spks, new_colors=None, new_col_w=None):
        """스냅샷 복원: 가상 스크롤에서는 데이터 교체 후 전체 재렌더."""
        self.subtitles      = new_subs
        self.speakers       = new_spks
        if new_colors is not None:
            self.speaker_colors = new_colors
        # 컬럼 너비 복원 — 저장된 값이 있으면 그대로, 없으면 speaker 컬럼만 재계산
        if new_col_w is not None:
            self._col_w.update(new_col_w)
        else:
            self._auto_resize_speaker_col()
        self._unsaved = True
        self._rebuild_ts_cache()
        self._update_scrollregion()
        self._layout_header()
        self._fill_slots(min(self._vscroll_top, max(0, len(new_subs) - 1)))
        self._render_speakers()
        self._update_count()
        # 파형 타임라인 갱신
        self._wf_img_cache = None
        self._pb_redraw()

    # ── 클립보드 (자막 행 단위) ───────────────
    def _focused_idx(self):
        idx = getattr(self, "_last_focused_idx", None)
        if idx is not None and 0 <= idx < len(self.subtitles):
            return idx
        return None

    def _selected_targets(self):
        """현재 선택된 인덱스 목록 (정렬). 없으면 _last_focused_idx 단독."""
        sel = getattr(self, "_selected_rows", set())
        if sel:
            return sorted(sel)
        focused = self._focused_idx()
        return [focused] if focused is not None else []

    def _on_delete(self, event=None):
        """Del / Ctrl+D: 선택된 행 일괄 삭제."""
        if isinstance(self.focus_get(), tk.Entry):
            return
        targets = self._selected_targets()
        if not targets:
            return
        self._push_undo()
        # 뒤에서부터 삭제해야 인덱스 안 밀림
        for idx in sorted(targets, reverse=True):
            if 0 <= idx < len(self.subtitles):
                self.subtitles.pop(idx)
        self._selected_rows.clear()
        self._selected_row_idx = None
        self._rebuild_ts_cache()
        self._renumber_rows(0)
        self._update_count()
        self._render_speakers()
        self._unsaved = True
        self._wf_img_cache = None
        self._pb_redraw()
        return "break"

    def _on_cut(self, event):
        if isinstance(self.focus_get(), tk.Entry):
            return
        targets = self._selected_targets()
        if not targets:
            return
        self._clipboard = [copy.deepcopy(self.subtitles[i])
                           for i in targets if i < len(self.subtitles)]
        self._push_undo()
        for idx in sorted(targets, reverse=True):
            if 0 <= idx < len(self.subtitles):
                self.subtitles.pop(idx)
        self._selected_rows.clear()
        self._selected_row_idx = None
        self._rebuild_ts_cache()
        self._renumber_rows(0)
        self._update_count()
        self._render_speakers()
        self._unsaved = True
        self._wf_img_cache = None
        self._pb_redraw()
        return "break"

    def _on_copy(self, event):
        if isinstance(self.focus_get(), tk.Entry):
            return
        targets = self._selected_targets()
        if not targets:
            return
        self._clipboard = [copy.deepcopy(self.subtitles[i])
                           for i in targets if i < len(self.subtitles)]
        return "break"

    def _on_paste(self, event):
        if isinstance(self.focus_get(), tk.Entry):
            return
        if not self._clipboard:
            return
        # clipboard가 단일 dict(구버전)이면 리스트로 감쌈
        clips = self._clipboard if isinstance(self._clipboard, list) else [self._clipboard]
        focused = self._focused_idx()
        insert_at = (focused + 1) if focused is not None else len(self.subtitles)
        self._push_undo()
        for i, sub in enumerate(clips):
            self.subtitles.insert(insert_at + i, copy.deepcopy(sub))
        self._rebuild_ts_cache()
        self._renumber_rows(insert_at)
        self._update_count()
        self._render_speakers()
        self._unsaved = True
        # 붙여넣은 범위 선택
        new_range = set(range(insert_at, insert_at + len(clips)))
        self._selected_rows = new_range
        self._selected_row_idx = insert_at
        for idx in new_range:
            self._redraw_slot_for(idx)
        self.after(50, lambda: self._scroll_to_row(insert_at))
        self._wf_img_cache = None
        self._pb_redraw()
        return "break"

    # ── 자막 추가 ─────────────────────────────
    def add_row(self, after_idx=None):
        if after_idx is None:
            after_idx = len(self.subtitles) - 1
        prev_ts_end = "00:00:00,000"
        if 0 <= after_idx < len(self.subtitles):
            ts = self.subtitles[after_idx]["timestamp"]
            parts = ts.split("-->")
            if len(parts) == 2:
                prev_ts_end = parts[1].strip()
        new_sub = {"timestamp": f"{prev_ts_end} --> {prev_ts_end}",
                   "text": "", "speaker": ""}
        insert_at = after_idx + 1
        self._push_undo()
        self.subtitles.insert(insert_at, new_sub)
        self._rebuild_ts_cache()
        self._renumber_rows(insert_at)
        self._update_count()
        self._render_speakers()
        self._unsaved = True
        self._select_row(insert_at)
        self.after(50, lambda: self._scroll_to_row(insert_at))

    # ── 자막 삭제 ─────────────────────────────
    def delete_row(self, idx):
        self._push_undo()
        self.subtitles.pop(idx)
        self._rebuild_ts_cache()
        self._renumber_rows(idx)
        self._update_count()
        self._render_speakers()
        self._unsaved = True

    def add_speaker(self):
        name = simpledialog.askstring("화자 추가", "화자 이름을 입력하세요:", parent=self)
        if not name or not name.strip():
            return
        name = name.strip()
        if name in self.speakers:
            messagebox.showwarning("중복", f"'{name}' 화자가 이미 있습니다.", parent=self)
            return
        self._push_undo()
        self.speakers.append(name)
        self._auto_resize_speaker_col()
        self._fill_slots(self._vscroll_top)
        self._render_speakers()
        self._update_count()

    def rename_speaker(self, old_name, new_name=None):
        if new_name is None:
            # 팝업 방식 (직접 호출 시 fallback)
            new_name = simpledialog.askstring(
                "화자 이름 변경", f"'{old_name}'의 새 이름:",
                initialvalue=old_name, parent=self)
        if not new_name or not new_name.strip():
            return
        new_name = new_name.strip()
        if new_name in self.speakers and new_name != old_name:
            messagebox.showwarning("중복", f"'{new_name}' 화자가 이미 있습니다.", parent=self)
            return
        self._push_undo()
        idx = self.speakers.index(old_name)
        self.speakers[idx] = new_name
        # 커스텀 색상 매핑 이전
        if old_name in self.speaker_colors:
            self.speaker_colors[new_name] = self.speaker_colors.pop(old_name)
        for sub in self.subtitles:
            if sub["speaker"] == old_name:
                sub["speaker"] = new_name
        self._fill_slots(self._vscroll_top)
        self._render_speakers()
        self._update_count()

    def delete_speaker(self, name):
        if not messagebox.askyesno(
                "화자 삭제",
                f"'{name}' 화자를 삭제하시겠습니까?\n해당 화자가 지정된 자막은 '없음'으로 초기화됩니다.",
                parent=self):
            return
        self._push_undo()
        self.speakers.remove(name)
        self.speaker_colors.pop(name, None)   # 커스텀 색상 제거
        for sub in self.subtitles:
            if sub["speaker"] == name:
                sub["speaker"] = ""
        self._auto_resize_speaker_col()
        self._fill_slots(self._vscroll_top)
        self._render_speakers()
        self._update_count()

    # ── 파일 열기 ─────────────────────────────
    def open_file(self):
        path = filedialog.askopenfilename(
            title="SRT 파일 선택",
            filetypes=[("SRT 파일", "*.srt"), ("모든 파일", "*.*")],
            parent=self)
        if not path:
            return
        self._load_srt(path)

    def _load_srt(self, path):
        try:
            self.subtitles = parse_srt(path)
        except Exception as e:
            messagebox.showerror("오류", f"파일을 읽는 중 오류가 발생했습니다:\n{e}", parent=self)
            return

        self.filepath  = path
        self.save_path = path
        _fname = os.path.splitext(os.path.basename(path))[0]
        self.title(f"{_fname} - SRT Speaker Editer")

        self.speakers = []
        self.speaker_colors = {}
        for sub in self.subtitles:
            sp = sub.get("speaker", "")
            if sp and sp not in self.speakers:
                self.speakers.append(sp)

        # ── 파일 끝 메타 복원 ──────────────────
        meta = read_srt_meta(path)
        if "speaker_colors" in meta:
            self.speaker_colors = meta["speaker_colors"]
        if "display_pattern" in meta:
            global g_speaker_pattern, g_display_pattern
            g_display_pattern = meta["display_pattern"]
            try:
                g_speaker_pattern = display_to_regex(g_display_pattern)
            except Exception:
                pass

        self._hide_overlay()
        self._unsaved = False
        self._rebuild_ts_cache()
        self._render_speakers()
        self._render_rows()

        # 동명 미디어 파일 자동 로드
        self._try_load_sibling_media(path)

    def _try_load_sibling_media(self, srt_path):
        """SRT와 같은 폴더, 같은 이름의 미디어 파일이 있으면 자동 로드"""
        base = os.path.splitext(srt_path)[0]
        media_exts = [".mp3", ".mp4", ".wav", ".m4a", ".aac",
                      ".ogg", ".flac", ".mkv", ".avi", ".mov", ".webm"]
        for ext in media_exts:
            candidate = base + ext
            if os.path.isfile(candidate):
                self._load_media(candidate)
                return

    # ── 미디어 열기 ───────────────────────────
    def open_media(self):
        path = filedialog.askopenfilename(
            title="음성/영상 파일 선택",
            filetypes=[
                ("미디어 파일", "*.mp3 *.mp4 *.wav *.m4a *.aac *.ogg *.flac *.mkv *.avi *.mov *.webm"),
                ("모든 파일", "*.*")
            ],
            parent=self)
        if not path:
            return
        self._load_media(path)

    def _load_media(self, path):
        if not self.player._init_pygame():
            messagebox.showwarning(
                "미디어 재생 불가",
                "pygame 초기화에 실패했습니다.\n"
                "pip install pygame 후 다시 시도하세요.",
                parent=self)
            return

        self.player.stop()
        self.player._filepath = path
        self.player._position = 0.0
        self.player._duration = 0.0
        self.media_path = path

        name = os.path.basename(path)
        self.lbl_media.configure(text=f"🎵  {name}", fg=FG)
        self.media_progress_var.set(0)
        self.lbl_dur.configure(text="…")   # 조회 중 표시
        self.lbl_pos.configure(text="0:00:00")
        self.btn_play.configure(text="▶")
        self.after(100, self._pb_redraw)

        # duration 조회를 백그라운드에서 수행 → UI 블로킹 없음
        def _fetch():
            dur = self.player._get_duration(path)
            # 여전히 같은 파일이 로드된 경우에만 반영
            def _apply():
                if self.media_path == path:
                    self.player._duration = dur
                    self.lbl_dur.configure(text=self._fmt_time(dur))
                    # 진행바 현재 위치가 0이면 비율 재계산을 위해 명시적으로 0 재설정
                    if self.media_progress_var.get() == 0:
                        self.media_progress_var.set(0)
                    self._pb_redraw()
            self.after(0, _apply)

        threading.Thread(target=_fetch, daemon=True).start()

        # 파형 추출 시작
        self._waveform_pts = []
        self._pb_redraw()
        self._extract_waveform(path)

    def _extract_waveform(self, path):
        """librosa 로 파형 추출 (mp3 포함 전 포맷 지원, ffmpeg 불필요) — UI 블로킹 없음."""
        self._wf_loading = True
        self._waveform_pts = []
        self._pb_redraw()

        cw    = max(self._pb_canvas.winfo_width(), 800)
        N_PTS = max(4000, min(cw * 128, 32000))

        def _ensure_pip(*pkgs):
            import subprocess as _sp, sys as _sys
            for pkg in pkgs:
                try:
                    __import__(pkg)
                except ImportError:
                    _sp.check_call(
                        [_sys.executable, "-m", "pip", "install", pkg, "-q"],
                        stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)

        def _worker():
            import traceback
            try:
                _ensure_pip("librosa", "numpy", "soundfile", "audioread")
                import librosa, numpy as np

                # 22050Hz 모노로 로드 (mp3/wav/flac/ogg/m4a 전부 지원)
                y, sr = librosa.load(path, sr=22050, mono=True)
                total  = len(y)
                hop    = max(1, total // N_PTS)

                # librosa.util.frame: 버전에 따라 shape (frame_length, n_frames)
                frames = librosa.util.frame(y, frame_length=hop, hop_length=hop)
                # 항상 axis=0이 frame_length, axis=1이 n_frames
                if frames.ndim == 1:
                    frames = frames.reshape(-1, 1)

                peak    = np.max(np.abs(frames), axis=0)   # (n_frames,)
                rms     = np.sqrt(np.mean(frames ** 2, axis=0))
                amp_arr = np.clip(peak * 0.6 + rms * 2.5, 0.0, 1.0)
                n_frames = int(amp_arr.shape[0])

                # x: 0~1 시간축 비율
                pts = [(i / max(1, n_frames - 1), float(amp_arr[i]))
                       for i in range(n_frames)]

                UPDATE_EVERY = 500
                for i in range(UPDATE_EVERY, len(pts), UPDATE_EVERY):
                    snapshot = pts[:i]
                    def _partial(s=snapshot):
                        if self.media_path == path:
                            self._waveform_pts = s
                            self._pb_redraw()
                    self.after(0, _partial)

                def _apply():
                    if self.media_path == path:
                        self._waveform_pts = pts
                        self._wf_loading   = False
                        self._pb_redraw()
                self.after(0, _apply)

            except Exception:
                traceback.print_exc()   # 콘솔에 오류 출력
                def _done():
                    self._wf_loading = False
                    self._pb_redraw()
                self.after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()

    # ── 미디어 컨트롤 ────────────────────────
    def _on_space_key(self, event):
        """스페이스바: 자막 내용 Entry 편집 중이면 무시, 그 외 재생/정지."""
        focused = self.focus_get()
        # 자막 content Entry 편집 중이면 스페이스 통과
        if isinstance(focused, tk.Entry):
            for wi in self._slot_widgets:
                if wi.get("content") is focused:
                    return
        # 버튼에 포커스가 있으면 앱으로 돌려서 이중 호출 방지
        if isinstance(focused, (tk.Button, ttk.Button)):
            self.focus_set()
        self._media_play_pause()
        return "break"

    def _on_left_key(self, event):
        if isinstance(self.focus_get(), tk.Entry):
            return
        step = 30 if (event.state & 0x1) else 5
        self._media_seek(-step)
        return "break"

    def _on_right_key(self, event):
        if isinstance(self.focus_get(), tk.Entry):
            return
        step = 30 if (event.state & 0x1) else 5
        self._media_seek(+step)
        return "break"

    def _on_arrow_up(self, event):
        if isinstance(self.focus_get(), tk.Entry):
            return
        if not self.subtitles:
            return "break"
        # 재생 중이면 현재 재생 위치 기준, 아니면 선택 행 기준
        idx = self._current_nav_idx()
        new_idx = max(0, idx - 1)
        if new_idx != idx:
            self._select_row(new_idx)
            self._scroll_to_row(new_idx)
        return "break"

    def _on_arrow_down(self, event):
        if isinstance(self.focus_get(), tk.Entry):
            return
        if not self.subtitles:
            return "break"
        idx = self._current_nav_idx()
        new_idx = min(len(self.subtitles) - 1, idx + 1)
        if new_idx != idx:
            self._select_row(new_idx)
            self._scroll_to_row(new_idx)
        return "break"

    def _current_nav_idx(self):
        """위아래 이동의 기준 인덱스.
        재생 중이든 아니든 항상 현재 선택/포커스 행 기준으로 동작."""
        idx = getattr(self, "_selected_row_idx", None)
        if idx is None:
            idx = getattr(self, "_last_focused_idx", None)
        return idx if idx is not None else 0

    def _media_play_pause(self):
        if not self.media_path:
            return
        if self.player.is_playing:
            self.player.pause()
            self.btn_play.configure(text="▶")
            self._stop_progress_poll()
            # 하이라이트 유지 — _playing_rows 건드리지 않음
        else:
            self.player.play()
            self.btn_play.configure(text="⏸")
            self._start_progress_poll()

    def _media_stop(self):
        self.player.stop()
        self.btn_play.configure(text="▶")
        self.media_progress_var.set(0)
        self.lbl_pos.configure(text="0:00:00")
        self._stop_progress_poll()
        self._pb_redraw()
        old = self._playing_rows.copy()
        self._playing_rows.clear()
        for idx in old:
            self._redraw_slot_for(idx)

    def _media_seek(self, delta):
        if not self.media_path:
            return
        was_playing = self.player.is_playing
        # poll을 먼저 멈춰야 seek 중 is_playing=False 구간에서 poll이 오작동하지 않음
        self._stop_progress_poll()
        self.player.seek(delta)
        pos = self.player.position
        self.media_progress_var.set(pos)
        self.lbl_pos.configure(text=self._fmt_time(pos))
        self._pb_redraw()
        if was_playing:
            self.btn_play.configure(text="⏸")
            # 재생 안정화 후 poll 시작
            self.after(150, self._start_progress_poll)

    def _on_seek_drag(self, val):
        """진행바 드래그 중 위치 레이블만 갱신 (호환용)"""
        self.lbl_pos.configure(text=self._fmt_time(float(val)))

    def _on_seek_release(self, event):
        """진행바 놓았을 때 해당 위치로 seek (호환용) — 선택 자막은 변경하지 않음"""
        if not self.media_path:
            return
        pos = self.media_progress_var.get()
        was_playing = self.player.is_playing
        self._stop_progress_poll()
        self.player.seek_to(pos)
        if was_playing:
            self.btn_play.configure(text="⏸")
            self.after(150, self._start_progress_poll)

    # ── 진행바 폴링 ──────────────────────────
    def _start_progress_poll(self):
        self._stop_progress_poll()
        self._poll_progress()

    @staticmethod
    def _ts_to_sec(ts_str):
        """'HH:MM:SS,mmm' 또는 'HH:MM:SS.mmm' → float 초. 실패 시 None."""
        m = re.match(r"(\d+):(\d+):(\d+)[,.](\d+)", ts_str.strip())
        if not m:
            return None
        h, mi, s, ms = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        return h * 3600 + mi * 60 + s + ms / 1000.0

    def _get_rows_at(self, pos_sec):
        """현재 재생 위치(초)에 해당하는 자막 행 인덱스 집합 반환.
        _ts_cache(미리 파싱된 float 쌍)를 사용해 regex 반복 호출을 피한다."""
        result = set()
        cache = getattr(self, "_ts_cache", None)
        if cache is None:
            return result
        for i, (t_start, t_end) in enumerate(cache):
            if t_start is None or t_end is None:
                continue
            if t_start <= pos_sec <= t_end:
                result.add(i)
        return result

    ROW_PLAYING = "#1A2A1A"   # 재생 중 하이라이트 색상 (어두운 초록)

    def _set_playing_highlight(self, idx, on: bool):
        """재생 위치 하이라이트를 켜거나 끔 — 슬롯 재렌더로 처리."""
        is_selected = (idx == getattr(self, "_selected_row_idx", None) or idx in getattr(self, "_selected_rows", set()))
        if is_selected:
            return
        self._redraw_slot_for(idx)

    def _update_playback_highlight(self, pos_sec):
        """재생 위치 하이라이트만 갱신 — 선택(_selected_rows)은 건드리지 않음."""
        new_rows = self._get_rows_at(pos_sec)
        if new_rows == self._playing_rows:
            return
        if not new_rows:
            return
        changed = self._playing_rows.symmetric_difference(new_rows)
        self._playing_rows = new_rows
        for idx in changed:
            self._redraw_slot_for(idx)

    def _poll_progress(self):
        if self.player.is_playing:
            pos = self.player.position
            prev_pos = getattr(self, "_last_polled_pos", -1.0)
            self._last_polled_pos = pos

            if abs(pos - prev_pos) >= 0.01:
                self.media_progress_var.set(pos)
                self.lbl_pos.configure(text=self._fmt_time(pos))
                dur = self.player.duration
                if dur > 0:
                    self.lbl_dur.configure(text=self._fmt_time(dur))
                # 줌 상태에서 재생헤드가 뷰 밖으로 나가면 뷰 이동
                self._wf_follow_playhead(pos)
                self._pb_redraw()

            self._update_playback_highlight(pos)
            self._seek_job = self.after(16, self._poll_progress)
        else:
            self._last_polled_pos = -1.0
            self.btn_play.configure(text="▶")
            self._seek_job = None

    def _wf_follow_playhead(self, pos):
        """재생 중 헤드가 뷰 밖으로 나가지 않도록 부드럽게 오프셋 추종."""
        dur = self.player.duration
        if dur <= 0 or self._wf_zoom <= 1.0:
            return
        pos_r = pos / dur
        start, end = self._wf_view_range()
        span = end - start
        # 헤드를 뷰의 30%~70% 사이에 유지 (ease toward center)
        target_center = pos_r
        new_offset = target_center - span * 0.35
        new_offset = max(0.0, min(new_offset, 1.0 - span))
        # 현재 오프셋과 너무 차이나지 않으면 스킵 (작은 움직임은 무시)
        if abs(new_offset - self._wf_offset) < span * 0.01:
            return
        # ease: 현재 → 목표를 10% 씩 이동 (부드러운 추종)
        self._wf_offset += (new_offset - self._wf_offset) * 0.15

    def _stop_progress_poll(self):
        if self._seek_job:
            self.after_cancel(self._seek_job)
            self._seek_job = None

    @staticmethod
    def _fmt_time(seconds):
        seconds = int(seconds)
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        return f"{h}:{m:02d}:{s:02d}"

    # ── 전체 저장 ─────────────────────────────
    def save_file(self):
        if not self.subtitles:
            messagebox.showwarning("저장", "저장할 자막이 없습니다.", parent=self)
            return
        if not self.save_path:
            self.save_file_as()
            return
        try:
            meta = {}
            if self.speaker_colors:
                meta["speaker_colors"] = self.speaker_colors
            if g_display_pattern != DEFAULT_DISPLAY_PATTERN:
                meta["display_pattern"] = g_display_pattern
            write_srt_tagged(self.subtitles, self.save_path, meta or None)
            self._unsaved = False
            _fn = os.path.splitext(os.path.basename(self.save_path))[0]
            self.title(f"{_fn} - SRT Speaker Editer  ✓")
            self.after(800, lambda fn=_fn: self.title(f"{fn} - SRT Speaker Editer"))
        except Exception as e:
            messagebox.showerror("저장 오류", str(e), parent=self)

    def save_file_as(self):
        if not self.subtitles:
            messagebox.showwarning("저장", "저장할 자막이 없습니다.", parent=self)
            return
        default = ""
        if self.filepath:
            base = os.path.splitext(os.path.basename(self.filepath))[0]
            default = os.path.join(os.path.dirname(self.filepath), f"{base}_tagged.srt")
        path = filedialog.asksaveasfilename(
            title="다른 이름으로 저장",
            initialfile=os.path.basename(default) if default else "output_tagged.srt",
            initialdir=os.path.dirname(default) if default else "",
            defaultextension=".srt",
            filetypes=[("SRT 파일", "*.srt"), ("모든 파일", "*.*")],
            parent=self)
        if not path:
            return
        try:
            meta = {}
            if self.speaker_colors:
                meta["speaker_colors"] = self.speaker_colors
            if g_display_pattern != DEFAULT_DISPLAY_PATTERN:
                meta["display_pattern"] = g_display_pattern
            write_srt_tagged(self.subtitles, path, meta or None)
            self._unsaved = False
            self.save_path = path
            _fn2 = os.path.splitext(os.path.basename(path))[0]
            self.title(f"{_fn2} - SRT Speaker Editer  ✓")
            self.after(800, lambda fn=_fn2: self.title(f"{fn} - SRT Speaker Editer"))
        except Exception as e:
            messagebox.showerror("저장 오류", str(e), parent=self)

    def _update_count(self):
        total      = len(self.subtitles)
        unassigned = sum(1 for s in self.subtitles if not s["speaker"])
        if total == 0:
            self.lbl_count.configure(text="", fg="#FF9A5C")
        elif unassigned == 0:
            self.lbl_count.configure(
                text=f"✓  미지정 없음", fg="#6FCF97")
        else:
            self.lbl_count.configure(
                text=f"▼  미지정 {unassigned}개", fg="#FF9A5C")

    def _goto_next_unassigned(self):
        """현재 선택/스크롤 위치 이후 첫 번째 미지정 화자 행으로 순환 이동."""
        if not self.subtitles:
            return

        # 탐색 시작점: 마지막 이동했던 위치 → 없으면 뷰포트 상단 행
        start = getattr(self, "_last_unassigned_idx", None)
        if start is None:
            start = self._vscroll_top

        n = len(self.subtitles)
        for offset in range(1, n + 1):
            idx = (start + offset) % n
            if not self.subtitles[idx]["speaker"]:
                self._scroll_to_row(idx)
                self._set_row_highlight(idx, True)
                self._selected_row_idx = idx
                self._last_focused_idx = idx
                self._last_unassigned_idx = idx   # 다음 클릭 시 여기서부터
                # 포커스를 버튼이 아닌 루트로 이동
                self.focus_set()
                return

    # ── 내보내기 ──────────────────────────────
    def export(self):
        if not self.subtitles:
            messagebox.showwarning("내보내기", "자막이 없습니다.", parent=self)
            return
        init_dir = os.path.dirname(self.filepath) if self.filepath else ""
        out_dir = filedialog.askdirectory(title="저장할 폴더 선택",
                                          initialdir=init_dir,
                                          parent=self)
        if not out_dir:
            return

        speaker_subs  = defaultdict(list)
        untagged_subs = []
        for sub in self.subtitles:
            entry = {"timestamp": sub["timestamp"], "text": sub["text"]}
            if sub["speaker"]:
                speaker_subs[sub["speaker"]].append(entry)
            else:
                untagged_subs.append(entry)

        saved = []
        for speaker, subs in sorted(speaker_subs.items()):
            path = os.path.join(out_dir, f"{speaker}.srt")
            write_srt(subs, path)   # 내보내기는 태그 없는 순수 자막
            saved.append(f"{speaker}.srt  ({len(subs)}개)")

        if untagged_subs:
            base = os.path.splitext(os.path.basename(self.filepath or "output"))[0]
            path = os.path.join(out_dir, f"{base}_untagged.srt")
            write_srt(untagged_subs, path)
            saved.append(f"{base}_untagged.srt  ({len(untagged_subs)}개)")

        if saved:
            messagebox.showinfo(
                "내보내기 완료",
                "저장된 파일:\n\n" + "\n".join(saved) + f"\n\n📁 {out_dir}",
                parent=self)
        else:
            messagebox.showwarning("내보내기", "저장할 자막이 없습니다.", parent=self)

    # ── 종료 처리 ─────────────────────────────
    def _on_close(self):
        if self._unsaved and self.subtitles:
            ans = messagebox.askyesnocancel(
                "저장되지 않은 변경사항",
                "저장되지 않은 변경사항이 있습니다.\n저장하고 종료하시겠습니까?",
                parent=self)
            if ans is None:    # 취소
                return
            if ans:            # 예 → 저장 후 종료
                self.save_file()
        self._stop_progress_poll()
        self.player.stop()
        self.destroy()

    def destroy(self):
        self._stop_progress_poll()
        self.player.stop()
        super().destroy()


# ─────────────────────────────────────────────
#  tkinterdnd2 지원 여부에 따라 루트 클래스 선택
# ─────────────────────────────────────────────
def main():
    try:
        from tkinterdnd2 import TkinterDnD

        class SRTEditorDnD(TkinterDnD.Tk, SRTEditor):
            """tkinterdnd2 기반 드래그앤드롭 지원 버전"""
            def __init__(self):
                TkinterDnD.Tk.__init__(self)
                self.title("SRT Speaker Editer")
                self.geometry("1200x820")
                self.minsize(900, 620)
                self.configure(bg=BG)

                global FONT_FAMILY
                FONT_FAMILY = _pick_font(root=self)

                self.subtitles      = []
                self.speakers       = []
                self.speaker_colors = {}   # 화자명 → 사용자 지정 색상
                self.filepath   = None
                self.save_path  = None
                self.edited_row = None
                self.player     = MediaPlayer()
                self.media_path = None
                self._seek_job  = None
                self._last_focused_idx = None
                self._unsaved   = False
                self._playing_rows: set = set()
                self._ts_cache: list = []
                self._last_polled_pos: float = -1.0
                self._wf_zoom:   float = 1.0
                self._wf_offset: float = 0.0
                self._selected_rows: set = set()
                self._undo_stack = []
                self._redo_stack = []
                self._clipboard  = None

                self._build_styles()
                self._build_ui()
                self._setup_dnd()

                self.bind("<Control-s>", lambda e: self.save_file())
                self.bind("<Control-S>", lambda e: self.save_file_as())
                self.bind("<Control-o>", lambda e: self.open_file())
                self.bind("<space>",     self._on_space_key)
                self.bind("<Left>",      self._on_left_key)
                self.bind("<Right>",     self._on_right_key)
                self.bind("<Control-z>", lambda e: self._undo())
                self.bind("<Control-Z>", lambda e: self._redo())
                self.bind("<Control-x>", self._on_cut)
                self.bind("<Control-c>", self._on_copy)
                self.bind("<Control-v>", self._on_paste)
                self.bind("<Delete>",    self._on_delete)
                self.bind("<Control-d>", self._on_delete)
                self.bind("<Up>",        self._on_arrow_up)
                self.bind("<Down>",      self._on_arrow_down)
                self.bind("<grave>",     self._on_speaker_key)
                for _k in "123456789":
                    self.bind(_k, self._on_speaker_key)
                self.protocol("WM_DELETE_WINDOW", self._on_close)

        app = SRTEditorDnD()
        app.mainloop()

    except ImportError:
        # tkinterdnd2 없는 경우: 기본 Tk (드래그앤드롭 비활성)
        app = SRTEditor()
        app.mainloop()
    except Exception as e:
        # tkinterdnd2 관련 에러면 기본 Tk로 재시도, 그 외 에러는 보여줌
        import traceback, tkinter as _tk, tkinter.messagebox as _mb
        err_msg = traceback.format_exc()
        try:
            root = _tk.Tk()
            root.withdraw()
            _mb.showerror("시작 오류", f"앱 초기화 중 오류가 발생했습니다:\n\n{err_msg[:800]}")
            root.destroy()
        except Exception:
            print(err_msg)
        try:
            app = SRTEditor()
            app.mainloop()
        except Exception:
            print(traceback.format_exc())


if __name__ == "__main__":
    import traceback as _tb
    try:
        main()
    except Exception:
        err = _tb.format_exc()
        print(err)
        # 같은 폴더에 에러 로그 저장
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "srt_error.log")
        try:
            with open(log_path, "w", encoding="utf-8") as _f:
                _f.write(err)
        except Exception:
            pass
        try:
            import tkinter as _tk, tkinter.messagebox as _mb
            _r = _tk.Tk(); _r.withdraw()
            _mb.showerror("치명적 오류", f"앱이 시작되지 않았습니다.\n\n{err[:600]}\n\n로그: {log_path}")
            _r.destroy()
        except Exception:
            pass
