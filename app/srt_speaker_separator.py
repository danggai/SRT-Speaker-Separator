import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
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


def regex_to_display(regex: str) -> str:
    """내부 정규식을 사용자 표시 패턴으로 역변환 (최선 노력)."""
    # 기본 패턴 [%] & 이면 그대로 반환
    if regex == DEFAULT_SPEAKER_PATTERN:
        return DEFAULT_DISPLAY_PATTERN
    # 역변환은 간단히: 캡처그룹 → %, 나머지는 unescape
    try:
        # ^re.escape(prefix)(.+?)re.escape(between)\s* 역산
        inner = regex
        if inner.startswith("^"):
            inner = inner[1:]
        if inner.endswith(r"\s*"):
            inner = inner[: -len(r"\s*")]
        # (.+?) 또는 ([^\n]+?) 를 % 로
        inner = re.sub(r'\([^)]+\)', '%', inner, count=1)
        # re.escape 된 특수문자 복원
        inner = inner.replace(r'\[', '[').replace(r'\]', ']') \
                     .replace(r'\.', '.').replace(r'\(', '(') \
                     .replace(r'\)', ')').replace(r'\s', ' ')
        return inner.strip() + " &"
    except Exception:
        return DEFAULT_DISPLAY_PATTERN

# ─────────────────────────────────────────────
#  한글 지원 폰트 탐색
# ─────────────────────────────────────────────
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


def write_srt_tagged(subtitles, filepath):
    lines = []
    for i, sub in enumerate(subtitles, start=1):
        lines.append(str(i))
        lines.append(sub["timestamp"])
        if sub.get("speaker"):
            lines.append(f"[{sub['speaker']}] {sub['text']}")
        else:
            lines.append(sub["text"])
        lines.append("")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ─────────────────────────────────────────────
#  미디어 플레이어 (subprocess + ffplay / afplay)
# ─────────────────────────────────────────────
class MediaPlayer:
    """ffplay / afplay 기반 경량 미디어 플레이어"""

    SEEK_DELTA = 5   # 방향키 이동 초

    def __init__(self):
        self._proc       = None
        self._filepath   = None
        self._duration   = 0.0
        self._position   = 0.0       # 현재 재생 위치 (초)
        self._playing    = False
        self._start_wall = 0.0       # 재생 시작 시점의 wall time
        self._start_pos  = 0.0       # 재생 시작 시점의 position
        self._lock       = threading.Lock()
        self._backend    = self._detect_backend()

    # ── 백엔드 탐지 ───────────────────────────
    def _detect_backend(self):
        """ffplay → afplay 순으로 사용 가능 백엔드 반환"""
        for cmd in ["ffplay", "ffmpeg"]:
            try:
                subprocess.run([cmd, "-version"],
                               capture_output=True, timeout=2)
                return "ffplay"
            except Exception:
                pass
        if sys.platform == "darwin":
            return "afplay"
        return None

    def _get_duration(self, path):
        """ffprobe / ffmpeg 로 길이 조회"""
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json",
                 "-show_format", path],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
            info = json.loads(result.stdout)
            return float(info["format"]["duration"])
        except Exception:
            pass
        try:
            result = subprocess.run(
                ["ffmpeg", "-i", path],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
            m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", result.stderr)
            if m:
                h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
                return h * 3600 + mi * 60 + s
        except Exception:
            pass
        return 0.0

    # ── 공개 API ──────────────────────────────
    def load(self, path):
        self.stop()
        self._filepath = path
        self._position = 0.0
        self._duration = self._get_duration(path)
        return self._duration

    def play(self):
        if not self._filepath or self._playing:
            return
        self._start_play(self._position)

    def pause(self):
        """토글 pause / resume"""
        if self._playing:
            self._pause()
        else:
            self._resume()

    def stop(self):
        self._kill_proc()
        self._playing  = False
        self._position = 0.0

    def seek(self, delta):
        """delta 초만큼 이동 (양수/음수)"""
        new_pos = max(0.0, min(self._position + delta, self._duration))
        was_playing = self._playing
        self._kill_proc()
        self._position = new_pos
        if was_playing:
            self._start_play(new_pos)

    def seek_to(self, pos):
        """절대 위치(초)로 이동"""
        new_pos = max(0.0, min(pos, self._duration))
        was_playing = self._playing
        self._kill_proc()
        self._position = new_pos
        if was_playing:
            self._start_play(new_pos)

    @property
    def is_playing(self):
        return self._playing

    @property
    def position(self):
        if self._playing:
            elapsed = time.time() - self._start_wall
            return min(self._start_pos + elapsed, self._duration)
        return self._position

    @property
    def duration(self):
        return self._duration

    # ── 내부 ──────────────────────────────────
    def _start_play(self, start_sec):
        self._kill_proc()
        backend = self._backend
        if backend == "ffplay":
            # -ss를 -i 앞에 두면 fast seek, 뒤에 두면 정확하지만 느림
            # 여기서는 빠른 seek + 타이머 보정으로 정확도 확보
            cmd = [
                "ffplay", "-nodisp", "-autoexit",
                "-ss", f"{start_sec:.3f}",
                self._filepath
            ]
        elif backend == "afplay":
            cmd = ["afplay", "-t", str(max(0, self._duration - start_sec)),
                   "-q", "1", self._filepath]
        else:
            return

        self._proc       = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._playing    = True
        self._start_wall = time.time()
        self._start_pos  = start_sec

        # 재생 완료 감시 스레드
        t = threading.Thread(target=self._watch, daemon=True)
        t.start()

    def _watch(self):
        if self._proc:
            self._proc.wait()
        with self._lock:
            if self._playing:
                self._position = min(
                    self._start_pos + (time.time() - self._start_wall),
                    self._duration)
                self._playing = False

    def _pause(self):
        self._position = self.position
        self._kill_proc()
        self._playing = False

    def _resume(self):
        if self._filepath:
            self._start_play(self._position)

    def _kill_proc(self):
        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=1)
            except Exception:
                pass
            self._proc = None

    def __del__(self):
        self._kill_proc()


# ─────────────────────────────────────────────
#  메인 앱
# ─────────────────────────────────────────────
class SRTEditor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SRT Speaker Editor")
        self.geometry("1200x820")
        self.minsize(900, 620)
        self.configure(bg=BG)

        # 앱 창이 생성된 후 정확한 폰트 탐지 (빈 창 없음)
        global FONT_FAMILY
        FONT_FAMILY = _pick_font(root=self)

        self.subtitles  = []
        self.speakers   = []
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

        self._build_styles()
        self._build_ui()
        self._setup_dnd()        # 드래그 앤 드롭

        # 단축키
        self.bind("<Control-s>", lambda e: self.save_file())
        self.bind("<Control-S>", lambda e: self.save_file_as())
        self.bind("<Control-o>", lambda e: self.open_file())
        self.bind("<space>",     self._on_space_key)
        self.bind("<Left>",      lambda e: self._media_seek(-5))
        self.bind("<Right>",     lambda e: self._media_seek(+5))
        self.bind("<Control-z>", lambda e: self._undo())
        self.bind("<Control-Z>", lambda e: self._redo())
        self.bind("<Control-x>", self._on_cut)
        self.bind("<Control-c>", self._on_copy)
        self.bind("<Control-v>", self._on_paste)
        self.bind("<Up>",        self._on_arrow_up)
        self.bind("<Down>",      self._on_arrow_down)
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

        ttk.Label(top, text="SRT Speaker Editor", style="Title.TLabel"
                  ).pack(side="left", padx=18, pady=10)

        tk.Frame(top, bg=BORDER, width=1).pack(side="left", fill="y", padx=8, pady=6)

        ttk.Button(top, text="📂  열기",
                   style="Accent.TButton", command=self.open_file
                   ).pack(side="left", padx=(0, 4), pady=8)
        ttk.Button(top, text="💾  저장",
                   style="Ghost.TButton", command=self.save_file
                   ).pack(side="left", padx=(0, 4), pady=8)
        ttk.Button(top, text="📝  다른 이름으로 저장",
                   style="Ghost.TButton", command=self.save_file_as
                   ).pack(side="left", padx=(0, 4), pady=8)

        tk.Frame(top, bg=BORDER, width=1).pack(side="left", fill="y", padx=8, pady=6)

        ttk.Button(top, text="📤  화자별 내보내기",
                   style="Ghost.TButton", command=self.export
                   ).pack(side="left", padx=(0, 6), pady=8)

        tk.Frame(top, bg=BORDER, width=1).pack(side="left", fill="y", padx=8, pady=6)

        ttk.Button(top, text="＋  자막 추가",
                   style="Ghost.TButton",
                   command=lambda: self.add_row(getattr(self, "_last_focused_idx", None))
                   ).pack(side="left", padx=(0, 4), pady=8)

        ttk.Button(top, text="↩  실행취소",
                   style="Ghost.TButton", command=self._undo
                   ).pack(side="left", padx=(0, 4), pady=8)

        ttk.Button(top, text="↪  다시실행",
                   style="Ghost.TButton", command=self._redo
                   ).pack(side="left", padx=(0, 6), pady=8)

        self.lbl_file = ttk.Label(top, text="파일을 열어주세요", style="Dim.TLabel")
        self.lbl_file.pack(side="left", padx=12, pady=8)

        self.lbl_count = ttk.Label(top, text="", style="Dim.TLabel")
        self.lbl_count.pack(side="right", padx=18, pady=8)

        ttk.Button(top, text="⚙  설정",
                   style="Ghost.TButton", command=self._open_settings
                   ).pack(side="right", padx=(0, 4), pady=8)

        # 본문 영역 (사이드바 + 테이블)
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)

        self._build_sidebar(body)
        right_col = ttk.Frame(body)
        right_col.pack(side="left", fill="both", expand=True)

        self._build_table(right_col)
        self._build_media_panel(right_col)

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
        targets = [self, self.overlay, self.canvas,
                   self.rows_frame, self.media_panel]
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

        ttk.Label(side, text="SPEAKERS", style="Header.TLabel",
                  background=BG2).pack(anchor="w", padx=14, pady=(16, 6))

        list_frame = tk.Frame(side, bg=BG2)
        list_frame.pack(fill="both", expand=True, padx=6)

        canvas = tk.Canvas(list_frame, bg=BG2, highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical",
                                  command=canvas.yview)
        self.speaker_inner = tk.Frame(canvas, bg=BG2)
        self.speaker_inner.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.speaker_inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        btn_frame = tk.Frame(side, bg=BG2)
        btn_frame.pack(fill="x", padx=10, pady=10)
        ttk.Button(btn_frame, text="＋  화자 추가",
                   style="Accent.TButton",
                   command=self.add_speaker).pack(fill="x")

    # ── 자막 테이블 ───────────────────────────
    # 컬럼 정의: num / ts_s / ts_e / content(가변) / speaker / del
    _COL_IDS   = ["num", "ts_s", "ts_e", "speaker", "del"]
    _COL_DEF_W = {"num": 40, "ts_s": 132, "ts_e": 132, "speaker": 220, "del": 30}
    ROW_H      = 34   # 행 높이 (px)

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

        # 헤더 레이블 (Canvas window)
        _titles = {"num":"#","ts_s":"시작시간","ts_e":"종료시간",
                   "content":"자막 내용","speaker":"화자","del":""}
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

        # ── 스크롤 영역 ───────────────────────
        container = tk.Frame(right, bg=BG)
        container.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(container, bg=BG, highlightthickness=0, bd=0)
        self.vsb    = ttk.Scrollbar(container, orient="vertical",
                                    command=self.canvas.yview)

        self.rows_frame = tk.Frame(self.canvas, bg=BG)
        self._layout_debounce_job = None

        def _on_rows_configure(e):
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
            self._schedule_col_layout()

        self.rows_frame.bind("<Configure>", _on_rows_configure)
        self._rows_win = self.canvas.create_window((0, 0), window=self.rows_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.vsb.set)

        # canvas 크기 바뀌면 rows_frame 너비를 canvas에 맞춤 (핵심!)
        def _on_canvas_resize(e):
            self.canvas.itemconfig(self._rows_win, width=e.width)
            self._schedule_col_layout()
        self.canvas.bind("<Configure>", _on_canvas_resize)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.vsb.pack(side="right", fill="y")
        self.canvas.bind_all("<MouseWheel>",
            lambda e: self.canvas.yview_scroll(-1*(e.delta//120), "units"))

        self._row_widgets = []   # [{col_id: widget, ...}, ...]  행별 위젯 참조

    # ── 컬럼 레이아웃 계산 ────────────────────
    def _get_col_positions(self):
        """헤더/행 공용 컬럼 x 좌표 + 너비 dict 반환.
        content 컬럼은 canvas 실제 너비 기준으로 계산."""
        total = self.canvas.winfo_width()
        if total <= 1:
            total = self.winfo_width() - self._col_w.get("__sidebar__", 230)
        if total <= 1:
            total = 900
        # 스크롤바 너비 제외
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
        pos["del"]     = (x, self._col_w["del"])
        return pos

    # ── 헤더 레이아웃 ────────────────────────
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

        # 구분선
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
            pos = self._get_col_positions()
            self._drag_w0 = pos[hit][1] if hit == "content" \
                            else self._col_w[hit]

    def _hdr_b1motion(self, e):
        if not self._drag_col:
            return
        delta = e.x - self._drag_x0
        cid   = self._drag_col
        if cid == "content":
            # content 오른쪽 경계 드래그 → speaker 왼쪽 경계 이동
            # speaker 너비를 줄이거나 늘림
            new_sp = max(60, self._col_w["speaker"] - delta)
            self._col_w["speaker"] = new_sp
            self._drag_x0 = e.x          # 매 프레임 누적 방지
        else:
            new_w = max(40, self._drag_w0 + delta)
            self._col_w[cid] = new_w
        # 헤더만 즉시 갱신 — 행은 건드리지 않음
        self._layout_header()

    def _hdr_release(self, e):
        if self._drag_col:
            self._drag_col = None
            # 드래그 종료 시 한 번만 행 레이아웃 재적용
            self._apply_col_layout_to_rows()

    # ── rows_frame 너비 변경 시 content 컬럼 재조정 ──
    def _on_rows_frame_resize(self, event=None):
        self._layout_header()
        self._apply_col_layout_to_rows()

    def _schedule_col_layout(self, delay_ms=60):
        """Configure 이벤트 연속 발생 시 마지막 것만 실행 (debounce)."""
        if self._layout_debounce_job is not None:
            try:
                self.after_cancel(self._layout_debounce_job)
            except Exception:
                pass
        self._layout_debounce_job = self.after(delay_ms, self._on_rows_frame_resize)

    # ── 기존 행 위젯에 컬럼 너비만 반영 (재생성 없음) ──
    def _apply_col_layout_to_rows(self, visible_only=True):
        """뷰포트에 보이는 행만 즉시 처리, 나머지는 idle 시간에 청크 처리."""
        if not self._row_widgets:
            return
        pos = self._get_col_positions()
        h   = self.ROW_H
        all_cols = list(self._COL_IDS) + ["content"]

        if visible_only:
            try:
                top_frac, bot_frac = self.canvas.yview()
                total_h = len(self._row_widgets) * h
                buf = h * 2
                first = max(0, (int(top_frac * total_h) - buf) // h)
                last  = min(len(self._row_widgets) - 1,
                            (int(bot_frac * total_h) + buf) // h)
            except Exception:
                first, last = 0, len(self._row_widgets) - 1
        else:
            first, last = 0, len(self._row_widgets) - 1

        def _place_row(idx):
            row_info = self._row_widgets[idx]
            for cid in all_cols:
                if cid not in row_info or cid not in pos:
                    continue
                x, w = pos[cid]
                y_off = 3 if cid in ("ts_s", "ts_e", "content") else 0
                h_use = (h - 6) if cid in ("ts_s", "ts_e", "content") else h
                try:
                    row_info[cid].place(x=x, y=y_off, width=w, height=h_use)
                except Exception:
                    pass

        for idx in range(first, last + 1):
            _place_row(idx)

        if visible_only and (first > 0 or last < len(self._row_widgets) - 1):
            offscreen = list(range(0, first)) + list(range(last + 1, len(self._row_widgets)))
            CHUNK = 40
            def _process(indices):
                for idx in indices[:CHUNK]:
                    if idx < len(self._row_widgets):
                        _place_row(idx)
                if indices[CHUNK:]:
                    self.after_idle(lambda r=indices[CHUNK:]: _process(r))
            self.after_idle(lambda: _process(offscreen))

    # 행 빌드 시 컬럼 너비 참조 헬퍼 (하위호환)
    def _row_col_w(self, col_id):
        return self._col_w.get(col_id, self._COL_DEF_W.get(col_id, 80))

    # ── 미디어 패널 ───────────────────────────
    def _build_media_panel(self, parent):
        panel = tk.Frame(parent, bg=MEDIA_BG, height=130)
        panel.pack(fill="x", side="bottom")
        panel.pack_propagate(False)
        self.media_panel = panel

        # 상단 구분선
        tk.Frame(panel, bg=ACCENT, height=2).pack(fill="x")

        inner = tk.Frame(panel, bg=MEDIA_BG)
        inner.pack(fill="both", expand=True, padx=16, pady=8)

        # 파일명 + 드래그 안내
        top_row = tk.Frame(inner, bg=MEDIA_BG)
        top_row.pack(fill="x")

        self.lbl_media = tk.Label(top_row,
            text="🎵  음성/영상 파일을 여기에 드래그하거나 버튼으로 여세요",
            bg=MEDIA_BG, fg=FG_DIM, font=(FONT_FAMILY, 9), anchor="w")
        self.lbl_media.pack(side="left", fill="x", expand=True)

        ttk.Button(top_row, text="📁  미디어 열기",
                   style="Media.TButton",
                   command=self.open_media).pack(side="right", padx=(8, 0))

        # ── 커스텀 진행바 ──────────────────────
        self.media_progress_var = tk.DoubleVar(value=0)
        pb_frame = tk.Frame(inner, bg=MEDIA_BG)
        pb_frame.pack(fill="x", pady=(6, 2))

        # 진행바 캔버스 (커스텀)
        self._pb_canvas = tk.Canvas(pb_frame, height=18, bg=MEDIA_BG,
                                    highlightthickness=0, cursor="hand2")
        self._pb_canvas.pack(fill="x")
        self._pb_dragging = False
        self._pb_canvas.bind("<ButtonPress-1>",   self._pb_press)
        self._pb_canvas.bind("<B1-Motion>",        self._pb_drag)
        self._pb_canvas.bind("<ButtonRelease-1>", self._pb_release)
        self._pb_canvas.bind("<Configure>",       self._pb_redraw)

        # 컨트롤 버튼 행
        ctrl = tk.Frame(inner, bg=MEDIA_BG)
        ctrl.pack(fill="x")

        self.lbl_pos = tk.Label(ctrl, text="0:00:00", bg=MEDIA_BG, fg=ACCENT,
                                font=(FONT_FAMILY, 9, "bold"))
        self.lbl_pos.pack(side="left")

        # 컨트롤 버튼들 (중앙)
        btn_group = tk.Frame(ctrl, bg=MEDIA_BG)
        btn_group.pack(side="left", expand=True)

        btn_cfg = dict(bg="#2A2A2A", fg=FG, relief="flat", bd=0, cursor="hand2",
                       activebackground="#3A3A3A", activeforeground=FG,
                       font=(FONT_FAMILY, 12), width=3)

        tk.Button(btn_group, text="⏮", **btn_cfg,
                  command=self._media_stop).pack(side="left", padx=4)
        tk.Button(btn_group, text="◀◀", **btn_cfg,
                  command=lambda: self._media_seek(-5)).pack(side="left", padx=4)

        self.btn_play = tk.Button(btn_group, text="▶",
                                  bg=ACCENT, fg="white",
                                  font=(FONT_FAMILY, 14, "bold"),
                                  relief="flat", bd=0, cursor="hand2",
                                  activebackground="#7B5FB4", activeforeground="white",
                                  width=3,
                                  command=self._media_play_pause)
        self.btn_play.pack(side="left", padx=6)

        tk.Button(btn_group, text="▶▶", **btn_cfg,
                  command=lambda: self._media_seek(+5)).pack(side="left", padx=4)

        self.lbl_dur = tk.Label(ctrl, text="0:00:00", bg=MEDIA_BG, fg=FG_DIM,
                                font=(FONT_FAMILY, 9))
        self.lbl_dur.pack(side="right")

        # 미디어 패널에도 드래그 드롭 바인딩
        for w in [panel, inner, top_row, self.lbl_media, ctrl, btn_group]:
            w.bind("<Enter>", lambda e: None)

    # ── 커스텀 진행바 그리기 ─────────────────
    def _pb_redraw(self, event=None):
        c = self._pb_canvas
        w = c.winfo_width()
        h = c.winfo_height()
        if w <= 1:
            # Canvas가 아직 배치되지 않은 경우 짧게 대기 후 재시도
            self.after(50, self._pb_redraw)
            return
        c.delete("all")
        dur = self.player.duration if self.player.duration > 0 else 0
        pos = self.media_progress_var.get()
        ratio = min(pos / dur, 1.0) if dur > 0 else 0.0
        filled = int(w * ratio)

        # 트랙 배경
        track_y = h // 2
        c.create_rectangle(0, track_y - 3, w, track_y + 3,
                            fill="#333333", outline="", tags="track")
        # 채워진 부분
        if filled > 0:
            c.create_rectangle(0, track_y - 3, filled, track_y + 3,
                                fill=ACCENT, outline="", tags="fill")
        # 핸들 (동그라미)
        hx = max(7, min(filled, w - 7))
        c.create_oval(hx - 7, track_y - 7, hx + 7, track_y + 7,
                      fill=ACCENT, outline="white", width=2, tags="handle")

    def _pb_pos_from_x(self, x):
        w = self._pb_canvas.winfo_width()
        dur = self.player.duration if self.player.duration > 0 else 1
        ratio = max(0.0, min(x / w, 1.0))
        return ratio * dur

    def _pb_press(self, event):
        self._pb_dragging = True
        pos = self._pb_pos_from_x(event.x)
        self.media_progress_var.set(pos)
        self.lbl_pos.configure(text=self._fmt_time(pos))
        self._pb_redraw()

    def _pb_drag(self, event):
        if not self._pb_dragging:
            return
        pos = self._pb_pos_from_x(event.x)
        self.media_progress_var.set(pos)
        self.lbl_pos.configure(text=self._fmt_time(pos))
        self._pb_redraw()

    def _pb_release(self, event):
        self._pb_dragging = False
        if not self.media_path:
            return
        pos = self._pb_pos_from_x(event.x)
        self.media_progress_var.set(pos)
        was_playing = self.player.is_playing
        self.player.seek_to(pos)
        if was_playing:
            self.btn_play.configure(text="⏸")
            self._start_progress_poll()
        self._pb_redraw()

    # ── 미디어 드롭 안내 ─────────────────────
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

    # ── 화자 사이드바 렌더 ───────────────────
    def _render_speakers(self):
        for w in self.speaker_inner.winfo_children():
            w.destroy()

        if not self.speakers:
            tk.Label(self.speaker_inner, text="화자가 없습니다",
                     bg=BG2, fg=FG_DIM,
                     font=(FONT_FAMILY, 9)).pack(padx=10, pady=8)
            return

        for i, name in enumerate(self.speakers):
            color = SPEAKER_COLORS[i % len(SPEAKER_COLORS)]

            # 화자 박스 (클릭 가능)
            row = tk.Frame(self.speaker_inner, bg=BG3,
                           highlightbackground=color, highlightthickness=1,
                           cursor="hand2")
            row.pack(fill="x", padx=6, pady=3, ipady=2)

            # 색 점
            dot_c = tk.Canvas(row, width=10, height=10, bg=BG3,
                              highlightthickness=0)
            dot_c.pack(side="left", padx=(6, 2), pady=6)
            dot_c.create_oval(1, 1, 9, 9, fill=color, outline="")

            lbl = tk.Label(row, text=name, bg=BG3, fg=color,
                           font=(FONT_FAMILY, 10, "bold"), anchor="w",
                           cursor="hand2")
            lbl.pack(side="left", fill="x", expand=True, padx=2)

            cnt = sum(1 for s in self.subtitles if s["speaker"] == name)
            cnt_lbl = tk.Label(row, text=str(cnt), bg=BG3, fg=FG_DIM,
                     font=(FONT_FAMILY, 9))
            cnt_lbl.pack(side="left", padx=2)

            tk.Button(row, text="✎", bg=BG3, fg=FG_DIM,
                      font=(FONT_FAMILY, 10), bd=0, cursor="hand2",
                      activebackground=BG3, activeforeground=color,
                      command=lambda n=name: self.rename_speaker(n)
                      ).pack(side="left", padx=1)

            tk.Button(row, text="✕", bg=BG3, fg="#FF6B8A",
                      font=(FONT_FAMILY, 10), bd=0, cursor="hand2",
                      activebackground=BG3, activeforeground="#FF6B8A",
                      command=lambda n=name: self.delete_speaker(n)
                      ).pack(side="left", padx=(1, 4))

            # 박스 전체 클릭 → 선택된 자막에 화자 지정
            for widget in [row, lbl, dot_c, cnt_lbl]:
                widget.bind("<Button-1>",
                    lambda e, n=name: self._assign_speaker_from_sidebar(n))

    def _assign_speaker_from_sidebar(self, name):
        """사이드바 화자 박스 클릭 시 현재 포커스된 자막에 화자 지정"""
        idx = getattr(self, "_last_focused_idx", None)
        if idx is None or idx >= len(self.subtitles):
            return
        self._push_undo()
        self.subtitles[idx]["speaker"] = name
        self._unsaved = True
        self._refresh_row(idx)
        self._render_speakers()

    # ── 설정 창 ────────────────────────────
    def _open_settings(self):
        """설정 창: 화자 구분 패턴 변경 (% = 화자명, & = 자막 내용)"""
        global g_speaker_pattern, g_display_pattern
        win = tk.Toplevel(self)
        win.title("설정")
        win.configure(bg=BG)
        win.geometry("520x300")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()

        tk.Label(win, text="설정", bg=BG, fg=FG,
                 font=(FONT_FAMILY, 14, "bold")).pack(anchor="w", padx=20, pady=(18, 4))
        tk.Frame(win, bg=BORDER, height=1).pack(fill="x", padx=20)

        sec = tk.Frame(win, bg=BG)
        sec.pack(fill="x", padx=20, pady=14)

        tk.Label(sec, text="화자 구분 패턴", bg=BG, fg=FG,
                 font=(FONT_FAMILY, 10, "bold")).pack(anchor="w")
        tk.Label(sec,
                 text="% = 현재 화자명,  & = 자막 내용\n"
                      "예시:  [%] &  →  [Alice] 안녕하세요  (화자=Alice)\n"
                      "예시:  (%): &  →  (Bob): 반갑습니다  (화자=Bob)",
                 bg=BG, fg=FG_DIM, font=(FONT_FAMILY, 9),
                 justify="left").pack(anchor="w", pady=(2, 6))

        pat_var = tk.StringVar(value=g_display_pattern)
        pat_entry = tk.Entry(sec, textvariable=pat_var, width=52,
                             bg=BG3, fg=ACCENT, insertbackground=FG,
                             font=(FONT_MONO, 10), relief="flat",
                             highlightthickness=1, highlightbackground=BORDER,
                             highlightcolor=ACCENT)
        pat_entry.pack(fill="x", ipady=4)

        # 변환된 정규식 미리보기
        preview_lbl = tk.Label(sec, text="", bg=BG, fg=FG_DIM,
                               font=(FONT_MONO, 8), wraplength=460, justify="left")
        preview_lbl.pack(anchor="w", pady=(3, 0))

        info_lbl = tk.Label(sec, text="", bg=BG, fg="#FF6B8A",
                            font=(FONT_FAMILY, 9))
        info_lbl.pack(anchor="w", pady=(2, 0))

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

        def on_reset():
            pat_var.set(DEFAULT_DISPLAY_PATTERN)
            info_lbl.configure(text="기본값으로 초기화했습니다. '적용'을 눌러 저장하세요.",
                               fg=FG_DIM)

        btn_row = tk.Frame(win, bg=BG)
        btn_row.pack(fill="x", padx=20, pady=(0, 10))

        tk.Button(btn_row, text="[기본값]",
                  bg="#2A2A2A", fg=FG_DIM, relief="flat", bd=0, cursor="hand2",
                  font=(FONT_FAMILY, 10), padx=10, pady=5,
                  activebackground="#333333", activeforeground=FG,
                  command=on_reset).pack(side="left", padx=(0, 8))

        tk.Button(btn_row, text="적용",
                  bg=ACCENT, fg="white", relief="flat", bd=0, cursor="hand2",
                  font=(FONT_FAMILY, 10, "bold"), padx=18, pady=5,
                  activebackground="#7B5FB4", activeforeground="white",
                  command=on_apply).pack(side="right")

        tk.Button(btn_row, text="취소",
                  bg="#2A2A2A", fg=FG, relief="flat", bd=0, cursor="hand2",
                  font=(FONT_FAMILY, 10), padx=12, pady=5,
                  activebackground="#333333",
                  command=win.destroy).pack(side="right", padx=(0, 8))

    # ── 자막 행 렌더 ────────────────────────
    def _render_rows(self):
        for w in self.rows_frame.winfo_children():
            w.destroy()
        self._row_widgets = []
        self._selected_row_idx = None
        # 컬럼 위치를 한 번만 계산해 캐시 → 행마다 재계산 방지
        self._cached_col_pos = self._get_col_positions()
        for idx, sub in enumerate(self.subtitles):
            self._make_row(idx, sub)
        self._cached_col_pos = None   # 캐시 해제
        self._update_count()
        self._auto_resize_speaker_col()  # 내부에서 _apply_col_layout_to_rows 1회 호출
        self._layout_header()

    # ── 타임스탬프 유효성 패턴 ───────────────
    _TS_RE    = re.compile(r"^\d{2}:\d{2}:\d{2}[,\.]\d{3}$")
    _TS_ERR_BG = "#3A1010"

    def _ts_valid(self, val):
        return bool(self._TS_RE.match(val.strip()))

    def _make_row(self, idx, sub):
        h  = self.ROW_H
        bg = ROW_ODD if idx % 2 == 0 else ROW_EVEN

        # 행 컨테이너 — pack으로 높이만, 너비는 rows_frame에 맞춤
        row = tk.Frame(self.rows_frame, bg=bg, height=h)
        row.pack(fill="x")
        row.pack_propagate(False)

        row_info = {}  # cid → 위젯

        # ── 번호 컬럼 ─────────────────────────
        num_lbl = tk.Label(row, text=str(idx + 1), bg=bg, fg=FG_DIM,
                           font=(FONT_FAMILY, 9), anchor="center", cursor="hand2")
        num_lbl.place(x=0, y=0, width=self._col_w["num"], height=h)
        num_lbl.bind("<Button-1>", lambda e, i=idx: self._select_row(i))
        row_info["num"] = num_lbl

        # ── 타임스탬프: 시작 ──────────────────
        ts_full  = sub.get("timestamp", "")
        parts    = ts_full.split("-->")
        ts_start = parts[0].strip() if len(parts) >= 2 else ts_full.strip()
        ts_end   = parts[1].strip() if len(parts) >= 2 else ""

        ts_s_var = tk.StringVar(value=ts_start)
        ts_e_var = tk.StringVar(value=ts_end)

        def _ts_style(entry, val):
            ok = self._ts_valid(val)
            entry.configure(bg=BG3 if ok else self._TS_ERR_BG,
                            highlightbackground=BORDER if ok else "#8B1A1A")

        ts_s = tk.Entry(row, textvariable=ts_s_var,
                        bg=BG3, fg=ACCENT, insertbackground=FG,
                        font=(FONT_MONO, 9), relief="flat",
                        highlightthickness=1, highlightbackground=BORDER,
                        highlightcolor=ACCENT)
        ts_s.place(x=self._col_w["num"], y=3,
                   width=self._col_w["ts_s"], height=h - 6)
        row_info["ts_s"] = ts_s

        # ── 타임스탬프: 종료 ──────────────────
        ts_e = tk.Entry(row, textvariable=ts_e_var,
                        bg=BG3, fg=ACCENT, insertbackground=FG,
                        font=(FONT_MONO, 9), relief="flat",
                        highlightthickness=1, highlightbackground=BORDER,
                        highlightcolor=ACCENT)
        ts_e.place(x=self._col_w["num"] + self._col_w["ts_s"], y=3,
                   width=self._col_w["ts_e"], height=h - 6)
        row_info["ts_e"] = ts_e

        def _commit_ts(i=idx, sv=ts_s_var, ev=ts_e_var, se=ts_s, ee=ts_e):
            s, e = sv.get().strip(), ev.get().strip()
            _ts_style(se, s); _ts_style(ee, e)
            if self._ts_valid(s) and self._ts_valid(e):
                self.subtitles[i]["timestamp"] = f"{s} --> {e}"
                self._unsaved = True

        for ent in (ts_s, ts_e):
            ent.bind("<Return>",    lambda e, f=_commit_ts: f())
            ent.bind("<FocusOut>",  lambda e, f=_commit_ts: f())
            ent.bind("<KeyRelease>",lambda e, sv=ts_s_var, ev=ts_e_var,
                                           se=ts_s, ee=ts_e:
                                    (_ts_style(se, sv.get()),
                                     _ts_style(ee, ev.get())))

        _ts_style(ts_s, ts_start)
        _ts_style(ts_e, ts_end)

        # ── 자막 텍스트 (content, 가변) ───────
        # _render_rows 에서 미리 캐시된 위치 사용 (없으면 즉시 계산)
        pos = getattr(self, "_cached_col_pos", None) or self._get_col_positions()
        cx, cw = pos["content"]

        txt_var = tk.StringVar(value=sub["text"])
        txt_e = tk.Entry(row, textvariable=txt_var,
                         bg=BG3, fg=FG, insertbackground=FG,
                         font=(FONT_FAMILY, 10), relief="flat",
                         highlightthickness=1, highlightbackground=BORDER,
                         highlightcolor=ACCENT)
        txt_e.place(x=cx, y=3, width=cw, height=h - 6)
        txt_e.bind("<FocusOut>", lambda e, i=idx, v=txt_var: self._save_text(i, v))
        txt_e.bind("<Return>",   lambda e, i=idx, v=txt_var: self._save_text(i, v))
        txt_e.bind("<FocusIn>",  lambda e, i=idx: (
            setattr(self, "_last_focused_idx", i),
            self._select_row(i)
        ))
        row_info["content"] = txt_e

        # ── 화자 pill 컨테이너 ────────────────
        sx, sw = pos["speaker"], self._col_w["speaker"]
        if isinstance(sx, tuple):
            sx, sw = sx[0], sx[1]

        spk_frame = tk.Frame(row, bg=bg)
        spk_frame.place(x=pos["speaker"][0], y=0,
                        width=self._col_w["speaker"], height=h)
        self._build_speaker_pills(spk_frame, idx, sub, bg)
        row_info["speaker"] = spk_frame

        # ── 삭제 버튼 ─────────────────────────
        del_x = pos["del"][0]
        del_btn = tk.Button(row, text="✕", bg=bg, fg="#FF6B8A",
                            font=(FONT_FAMILY, 10), bd=0, cursor="hand2",
                            activebackground=bg, activeforeground=ACCENT,
                            command=lambda i=idx: self.delete_row(i))
        del_btn.place(x=del_x, y=0, width=self._col_w["del"], height=h)
        row_info["del"] = del_btn

        self._row_widgets.append(row_info)
        row_info["_row_frame"] = row  # 하이라이트용 frame 참조

        # ── 행 클릭: 행 선택 + content Entry 외 클릭 시 포커스 해제 ──
        def _row_click(e, i=idx):
            self._select_row(i)
            self._blur_content_entry()
        row.bind("<Button-1>", _row_click)
        num_lbl.bind("<Button-1>", lambda e, i=idx: _row_click(e, i))
        spk_frame.bind("<Button-1>", lambda e, i=idx: _row_click(e, i))

    def _on_global_click(self, event):
        """어디든 클릭 시, 클릭 대상이 content Entry가 아니면 포커스 해제."""
        clicked = event.widget
        # 클릭한 위젯이 content Entry 본인이면 그냥 둠
        for ri in self._row_widgets:
            if ri.get("content") is clicked:
                return
        self._blur_content_entry()

    def _blur_content_entry(self):
        """현재 포커스가 content Entry이면 포커스를 루트로 이동해 하이라이트 해제."""
        cur = self.focus_get()
        if not isinstance(cur, tk.Entry):
            return
        for ri in self._row_widgets:
            if ri.get("content") is cur:
                cur.event_generate("<FocusOut>")
                self.focus_set()
                return

    def _select_row(self, idx):
        """자막 행 선택: 이전 선택 해제 → 새 행 하이라이트 → seek"""
        prev = getattr(self, "_selected_row_idx", None)
        self._selected_row_idx = idx
        self._last_focused_idx = idx

        # 이전 행 하이라이트 해제
        if prev is not None and prev != idx and prev < len(self._row_widgets):
            self._set_row_highlight(prev, False)

        # 새 행 하이라이트
        if idx < len(self._row_widgets):
            self._set_row_highlight(idx, True)

        self._seek_to_subtitle(idx)

    def _set_row_highlight(self, idx, selected: bool):
        """행 배경색을 선택/해제 상태로 변경."""
        if idx >= len(self._row_widgets):
            return
        row_info = self._row_widgets[idx]
        base_bg = ROW_ODD if idx % 2 == 0 else ROW_EVEN
        bg = ROW_HL if selected else base_bg
        row_frame = row_info.get("_row_frame")
        if row_frame:
            try:
                row_frame.configure(bg=bg)
            except Exception:
                pass
        for cid, widget in row_info.items():
            if cid.startswith("_"):
                continue
            if cid in ("ts_s", "ts_e", "content"):
                continue  # Entry 배경은 BG3 고정
            try:
                widget.configure(bg=bg)
            except Exception:
                pass
        # spk_frame 자식(pill label)도 미선택 상태 배경 갱신
        spk_frame = row_info.get("speaker")
        if spk_frame:
            sub = self.subtitles[idx] if idx < len(self.subtitles) else {}
            current = sub.get("speaker", "")
            for child in spk_frame.winfo_children():
                try:
                    child_text = child.cget("text")
                    # 선택된 pill은 자체 sel_bg 유지, 비선택 pill만 행 배경으로
                    is_pill_selected = (child_text == current) or \
                                       (child_text == "(없음)" and current == "")
                    if not is_pill_selected:
                        child.configure(bg=bg)
                except Exception:
                    pass

    # ── 화자 pill 버튼 상시 나열 ────────────
    def _build_speaker_pills(self, parent, idx, sub, row_bg):
        """없음 + 화자 목록을 가변폭 pill 버튼으로 상시 표시"""
        current = sub.get("speaker", "")
        choices = [("", "(없음)")] + [(sp, sp) for sp in self.speakers]

        for val, label in choices:
            is_sel = (val == current)
            if val == "":
                color = FG_DIM
                sel_bg = "#2A2A2A"
            else:
                sp_i  = self.speakers.index(val)
                color = SPEAKER_COLORS[sp_i % len(SPEAKER_COLORS)]
                sel_bg = "#2D2040"

            btn = tk.Label(parent, text=label,
                           bg=sel_bg if is_sel else row_bg,
                           fg=color if is_sel else "#444455",
                           font=(FONT_FAMILY, 9, "bold" if is_sel else "normal"),
                           padx=7, pady=2, cursor="hand2",
                           relief="flat",
                           highlightthickness=1,
                           highlightbackground=color if is_sel else "#2A2A2A")
            btn.pack(side="left", padx=2)
            btn.bind("<Button-1>",
                lambda e, v=val, i=idx: self._pill_select(i, v))

    def _auto_resize_speaker_col(self):
        """화자 pill 전체를 표시하는 데 필요한 최소 너비로 speaker 컬럼 자동 조정."""
        # 각 pill의 추정 너비 계산 (폰트 기준 대략 글자당 8px + padx*2 + border)
        char_w = 8
        pad = 7 * 2 + 4 + 2  # padx*2 + highlightthickness*2 + pack padx*2
        choices_count = 1 + len(self.speakers)  # (없음) + 화자들
        # 가장 긴 화자명 길이
        max_label_len = max(
            (len(sp) for sp in self.speakers), default=0
        )
        none_len = len("(없음)")
        pill_w_none = none_len * char_w + pad
        pill_w_spk  = max_label_len * char_w + pad
        needed = pill_w_none + pill_w_spk * len(self.speakers) + 8
        needed = max(needed, 80)

        if self._col_w["speaker"] != needed:
            self._col_w["speaker"] = needed
            self._layout_header()
            self._apply_col_layout_to_rows()

    def _seek_to_subtitle(self, idx):
        """해당 자막의 시작 시간으로 미디어 seek"""
        if not self.media_path or idx >= len(self.subtitles):
            return
        ts = self.subtitles[idx]["timestamp"]
        # "00:00:01,000 --> 00:00:03,000" 파싱
        m = re.match(r"(\d+):(\d+):(\d+)[,.](\d+)", ts)
        if not m:
            return
        h, mi, s, ms = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        pos = h * 3600 + mi * 60 + s + ms / 1000.0
        was_playing = self.player.is_playing
        self.player.seek_to(pos)
        self.media_progress_var.set(pos)
        self.lbl_pos.configure(text=self._fmt_time(pos))
        self._pb_redraw()
        if was_playing:
            self.btn_play.configure(text="⏸")
            self._start_progress_poll()

    def _pill_select(self, sub_idx, val):
        """pill 클릭 시 화자 지정 + 해당 행만 재렌더"""
        self._push_undo()
        self.subtitles[sub_idx]["speaker"] = val
        self._unsaved = True
        self._refresh_row(sub_idx)
        self._render_speakers()

    def _refresh_row(self, idx):
        """해당 인덱스 행의 speaker pill만 갱신 (전체 재렌더 없음)."""
        if idx >= len(self._row_widgets):
            return
        row_info = self._row_widgets[idx]
        spk_frame = row_info.get("speaker")
        if spk_frame is None:
            return
        sub = self.subtitles[idx]
        is_selected = getattr(self, "_selected_row_idx", None) == idx
        bg = ROW_HL if is_selected else (ROW_ODD if idx % 2 == 0 else ROW_EVEN)
        for child in spk_frame.winfo_children():
            child.destroy()
        self._build_speaker_pills(spk_frame, idx, sub, bg)
        self._update_count()

    def _build_speaker_selector(self, parent, idx, sub, row_bg):
        """(구버전 호환용 — _build_speaker_pills 로 대체됨)"""
        self._build_speaker_pills(parent, idx, sub, row_bg)
        current = sub.get("speaker", "")
        display = current if current else "(없음)"

        if current and current in self.speakers:
            sp_idx = self.speakers.index(current)
            color = SPEAKER_COLORS[sp_idx % len(SPEAKER_COLORS)]
        else:
            color = FG_DIM

        btn = tk.Button(parent, text=display, width=14,
                        bg=BG3, fg=color,
                        font=(FONT_FAMILY, 9, "bold"),
                        relief="flat", bd=0, cursor="hand2",
                        activebackground="#333333",
                        anchor="center")
        btn.pack()
        btn.configure(command=lambda b=btn, i=idx: self._toggle_speaker_popup(b, i))
        sub["_btn"] = btn

    def _toggle_speaker_popup(self, anchor_btn, sub_idx):
        """화자 선택 팝업을 anchor_btn 아래에 표시"""
        if hasattr(self, "_spk_popup") and self._spk_popup:
            try:
                self._spk_popup.destroy()
            except Exception:
                pass
            self._spk_popup = None
            return

        popup = tk.Toplevel(self)
        popup.overrideredirect(True)
        popup.configure(bg="#2A2A2A")
        popup.attributes("-topmost", True)
        self._spk_popup = popup

        x = anchor_btn.winfo_rootx()
        y = anchor_btn.winfo_rooty() + anchor_btn.winfo_height() + 2
        popup.geometry(f"+{x}+{y}")

        choices = ["(없음)"] + self.speakers
        frame = tk.Frame(popup, bg="#2A2A2A", padx=4, pady=4)
        frame.pack()

        for choice in choices:
            if choice == "(없음)":
                fg = FG_DIM
                bg_sel = "#333333"
            else:
                sp_i = self.speakers.index(choice)
                fg = SPEAKER_COLORS[sp_i % len(SPEAKER_COLORS)]
                bg_sel = "#2D2040"

            current = self.subtitles[sub_idx].get("speaker", "")
            is_sel = (choice == current) or (choice == "(없음)" and current == "")

            b = tk.Button(frame, text=choice, width=14,
                          bg=bg_sel if is_sel else "#2A2A2A",
                          fg=fg,
                          font=(FONT_FAMILY, 9, "bold" if is_sel else "normal"),
                          relief="flat", bd=0, cursor="hand2",
                          activebackground="#333333",
                          anchor="w", padx=8, pady=4)
            b.pack(fill="x", pady=1)
            b.configure(command=lambda c=choice, p=popup, i=sub_idx:
                        self._select_speaker(c, i, p))

        popup.bind("<FocusOut>", lambda e: self._close_spk_popup())
        popup.focus_set()

    def _select_speaker(self, choice, sub_idx, popup):
        val = "" if choice == "(없음)" else choice
        self.subtitles[sub_idx]["speaker"] = val
        self._unsaved = True

        # 버튼 텍스트/색 갱신
        if "_btn" in self.subtitles[sub_idx]:
            btn = self.subtitles[sub_idx]["_btn"]
            if val and val in self.speakers:
                sp_i = self.speakers.index(val)
                color = SPEAKER_COLORS[sp_i % len(SPEAKER_COLORS)]
            else:
                color = FG_DIM
            try:
                btn.configure(text=choice, fg=color)
            except Exception:
                pass

        self._close_spk_popup()
        self._render_speakers()

    def _close_spk_popup(self):
        if hasattr(self, "_spk_popup") and self._spk_popup:
            try:
                self._spk_popup.destroy()
            except Exception:
                pass
            self._spk_popup = None

    # ── 데이터 저장 콜백 ──────────────────────
    def _save_ts(self, idx, var):
        self.subtitles[idx]["timestamp"] = var.get()
        self._unsaved = True

    def _save_text(self, idx, var):
        self.subtitles[idx]["text"] = var.get()
        self._unsaved = True

    # ── Undo / Redo ───────────────────────────
    _UNDO_MAX = 50   # 최대 스택 깊이

    def _snapshot(self):
        """현재 subtitles/speakers 상태를 스냅샷으로 저장."""
        return (copy.deepcopy(self.subtitles), list(self.speakers))

    def _push_undo(self):
        """현재 상태를 undo 스택에 쌓고 redo 스택을 비움."""
        self._undo_stack.append(self._snapshot())
        if len(self._undo_stack) > self._UNDO_MAX:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def _undo(self):
        if not self._undo_stack:
            return
        self._redo_stack.append(self._snapshot())
        subs, spks = self._undo_stack.pop()
        self._apply_snapshot(subs, spks)

    def _redo(self):
        if not self._redo_stack:
            return
        self._undo_stack.append(self._snapshot())
        subs, spks = self._redo_stack.pop()
        self._apply_snapshot(subs, spks)

    def _apply_snapshot(self, new_subs, new_spks):
        """스냅샷 복원: diff 비교로 변경된 행만 업데이트, 행 수 변화 시도 위젯 단위 처리."""
        old_subs    = self.subtitles
        spk_changed = (new_spks != self.speakers)

        self.subtitles = new_subs
        self.speakers  = new_spks
        self._unsaved  = True

        old_len = len(old_subs)
        new_len = len(new_subs)

        if old_len == new_len:
            # 행 수 동일: 내용이 다른 행만 부분 갱신
            changed_indices = [
                i for i, (a, b) in enumerate(zip(old_subs, new_subs)) if a != b
            ]
            if spk_changed:
                self._render_rows()
                self._render_speakers()
                return
            for i in changed_indices:
                self._refresh_row_full(i)
            self._update_count()
            return

        # ── 행 수가 달라진 경우: 위젯 단위 diff 처리 ──
        # 삭제(old > new) / 삽입(old < new) 모두 처리
        # 변경 범위를 앞에서부터 탐색해 최소한만 재생성
        min_len = min(old_len, new_len)

        # 앞쪽 공통 구간 찾기
        first_diff = 0
        while first_diff < min_len and old_subs[first_diff] == new_subs[first_diff]:
            first_diff += 1

        # 뒤쪽 공통 구간 찾기
        last_old = old_len - 1
        last_new = new_len - 1
        while (last_old >= first_diff and last_new >= first_diff
               and old_subs[last_old] == new_subs[last_new]):
            last_old -= 1
            last_new -= 1

        # first_diff ~ last_old 구간 위젯 제거
        for i in range(last_old, first_diff - 1, -1):
            if i < len(self._row_widgets):
                frame = self._row_widgets[i].get("_row_frame")
                if frame:
                    try:
                        frame.destroy()
                    except Exception:
                        pass
                self._row_widgets.pop(i)

        # first_diff ~ last_new 구간 위젯 삽입
        self._cached_col_pos = self._get_col_positions()
        children_before = list(self.rows_frame.winfo_children())
        # first_diff 이후 기존 위젯들을 임시로 unpack
        for i in range(first_diff, len(children_before)):
            try:
                children_before[i].pack_forget()
            except Exception:
                pass

        new_infos = []
        for i in range(first_diff, last_new + 1):
            self._make_row(i, new_subs[i])
            new_infos.append(self._row_widgets.pop())

        # 새 위젯들을 올바른 위치에 삽입
        for info in new_infos:
            self._row_widgets.insert(first_diff + new_infos.index(info), info)

        # unpack했던 기존 위젯 재pack
        for i in range(first_diff, len(children_before)):
            try:
                children_before[i].pack(fill="x")
            except Exception:
                pass

        self._cached_col_pos = None

        # first_diff 이후 행 번호/배경색 갱신
        self._renumber_rows(first_diff)
        self._update_count()

        if spk_changed:
            self._render_speakers()
        else:
            self._render_speakers()

    def _refresh_row_full(self, idx):
        """idx 행의 Entry 값 + pill을 모두 갱신 (위젯 재생성 없음)."""
        if idx >= len(self._row_widgets) or idx >= len(self.subtitles):
            return
        row_info = self._row_widgets[idx]
        sub = self.subtitles[idx]

        # 타임스탬프 Entry 갱신
        ts_full  = sub.get("timestamp", "")
        parts    = ts_full.split("-->")
        ts_start = parts[0].strip() if len(parts) >= 2 else ts_full.strip()
        ts_end   = parts[1].strip() if len(parts) >= 2 else ""
        for cid, val in (("ts_s", ts_start), ("ts_e", ts_end)):
            w = row_info.get(cid)
            if w:
                try:
                    w.delete(0, "end")
                    w.insert(0, val)
                except Exception:
                    pass

        # 자막 텍스트 Entry 갱신
        w = row_info.get("content")
        if w:
            try:
                cur = w.get()
                if cur != sub["text"]:
                    w.delete(0, "end")
                    w.insert(0, sub["text"])
            except Exception:
                pass

        # Speaker pill 갱신 (_refresh_row와 동일)
        spk_frame = row_info.get("speaker")
        if spk_frame:
            is_selected = getattr(self, "_selected_row_idx", None) == idx
            bg = ROW_HL if is_selected else (ROW_ODD if idx % 2 == 0 else ROW_EVEN)
            for child in spk_frame.winfo_children():
                child.destroy()
            self._build_speaker_pills(spk_frame, idx, sub, bg)

    # ── 클립보드 (자막 행 단위) ───────────────
    def _focused_idx(self):
        """현재 선택/포커스된 행 인덱스 반환 (없으면 None)."""
        idx = getattr(self, "_last_focused_idx", None)
        if idx is not None and 0 <= idx < len(self.subtitles):
            return idx
        return None

    def _on_cut(self, event):
        """Ctrl+X: Entry 포커스 중이면 기본 동작, 그 외엔 자막 행 잘라내기."""
        if isinstance(self.focus_get(), tk.Entry):
            return  # Entry 내 텍스트 편집 허용
        idx = self._focused_idx()
        if idx is None:
            return
        self._clipboard = copy.deepcopy(self.subtitles[idx])
        self._push_undo()
        self._remove_row_widget(idx)
        self.subtitles.pop(idx)
        self._renumber_rows(idx)
        self._update_count()
        self._render_speakers()
        self._unsaved = True
        return "break"

    def _on_copy(self, event):
        """Ctrl+C: Entry 포커스 중이면 기본 동작, 그 외엔 자막 행 복사."""
        if isinstance(self.focus_get(), tk.Entry):
            return
        idx = self._focused_idx()
        if idx is None:
            return
        self._clipboard = copy.deepcopy(self.subtitles[idx])
        return "break"

    def _on_paste(self, event):
        """Ctrl+V: Entry 포커스 중이면 기본 동작, 그 외엔 클립보드 자막 붙여넣기."""
        if isinstance(self.focus_get(), tk.Entry):
            return
        if self._clipboard is None:
            return
        idx = self._focused_idx()
        insert_at = (idx + 1) if idx is not None else len(self.subtitles)
        self._push_undo()
        new_sub = copy.deepcopy(self._clipboard)
        self.subtitles.insert(insert_at, new_sub)
        # 새 행 삽입: insert_at 이후 행 번호 갱신
        self._insert_row_widget(insert_at, new_sub)
        self._renumber_rows(insert_at)
        self._update_count()
        self._render_speakers()
        self._unsaved = True
        self._select_row(insert_at)
        return "break"

    # ── 자막 추가 ─────────────────────────────
    def add_row(self, after_idx=None):
        """자막 한 줄 추가. after_idx=None이면 맨 끝에 추가."""
        if after_idx is None:
            after_idx = len(self.subtitles) - 1
        # 이전 자막의 종료 시간을 시작으로 사용
        prev_ts_end = "00:00:00,000"
        if 0 <= after_idx < len(self.subtitles):
            ts = self.subtitles[after_idx]["timestamp"]
            parts = ts.split("-->")
            if len(parts) == 2:
                prev_ts_end = parts[1].strip()
        new_sub = {
            "timestamp": f"{prev_ts_end} --> {prev_ts_end}",
            "text": "",
            "speaker": ""
        }
        insert_at = after_idx + 1
        self._push_undo()
        self.subtitles.insert(insert_at, new_sub)
        self._insert_row_widget(insert_at, new_sub)
        self._renumber_rows(insert_at)
        self._update_count()
        self._render_speakers()
        self._unsaved = True
        # 새로 추가된 행으로 스크롤 + 포커스
        self._select_row(insert_at)
        self.after(50, lambda: self._scroll_to_row(insert_at))

    # ── 자막 삭제 (부분 재렌더) ───────────────
    def delete_row(self, idx):
        self._push_undo()
        self._remove_row_widget(idx)
        self.subtitles.pop(idx)
        self._renumber_rows(idx)
        self._update_count()
        self._render_speakers()
        self._unsaved = True

    # ── 행 위젯 삽입 / 삭제 헬퍼 ─────────────
    def _insert_row_widget(self, idx, sub):
        """self.subtitles[idx]가 이미 삽입된 상태에서 위젯만 추가."""
        # idx 이후 기존 위젯들을 잠시 unpack하고 재pack하는 대신
        # rows_frame 자식 순서를 재정렬: 기존 구현에서 pack 순서가 곧 표시 순서
        # 가장 단순한 방법: idx 이후 위젯들을 detach했다가 새 행 추가 후 재attach
        children = list(self.rows_frame.winfo_children())

        # idx 이후 위젯을 pack에서 제거 (destroy 안 함)
        for i in range(idx, len(children)):
            children[i].pack_forget()

        # 새 행 생성 (idx 위치)
        self._cached_col_pos = self._get_col_positions()
        self._make_row(idx, sub)
        self._cached_col_pos = None

        # 제거했던 위젯들을 순서대로 다시 pack
        for i in range(idx, len(children)):
            children[i].pack(fill="x")

        # _row_widgets도 삽입
        # _make_row가 이미 self._row_widgets.append()를 했으므로
        # 마지막에 추가된 것을 올바른 위치로 이동
        new_info = self._row_widgets.pop()
        self._row_widgets.insert(idx, new_info)

    def _remove_row_widget(self, idx):
        """idx 행의 위젯만 destroy하고 _row_widgets에서 제거."""
        if idx >= len(self._row_widgets):
            return
        row_info = self._row_widgets[idx]
        frame = row_info.get("_row_frame")
        if frame:
            try:
                frame.destroy()
            except Exception:
                pass
        self._row_widgets.pop(idx)

    def _renumber_rows(self, from_idx=0):
        """from_idx부터 행 번호 레이블 + 배경색 갱신 (위젯 재생성 없음)."""
        for i in range(from_idx, len(self._row_widgets)):
            row_info = self._row_widgets[i]
            # 번호 레이블
            num_lbl = row_info.get("num")
            if num_lbl:
                try:
                    num_lbl.configure(text=str(i + 1))
                except Exception:
                    pass
            # 배경색 (홀짝 변경)
            is_sel = getattr(self, "_selected_row_idx", None) == i
            base_bg = ROW_ODD if i % 2 == 0 else ROW_EVEN
            bg = ROW_HL if is_sel else base_bg
            frame = row_info.get("_row_frame")
            if frame:
                try:
                    frame.configure(bg=bg)
                except Exception:
                    pass

    def _scroll_to_row(self, idx):
        """idx 행이 보이도록 canvas 스크롤."""
        if idx >= len(self._row_widgets):
            return
        frame = self._row_widgets[idx].get("_row_frame")
        if not frame:
            return
        try:
            self.canvas.update_idletasks()
            fy = frame.winfo_y()
            fh = frame.winfo_height()
            ch = self.canvas.winfo_height()
            total_h = self.rows_frame.winfo_height()
            if total_h <= ch:
                return
            # 화면 중앙에 오도록
            target = max(0.0, min((fy - ch // 2 + fh // 2) / total_h, 1.0))
            self.canvas.yview_moveto(target)
        except Exception:
            pass

    # ── 화자 관리 ─────────────────────────────
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
        self._render_rows()
        self._render_speakers()

    def rename_speaker(self, old_name):
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
        for sub in self.subtitles:
            if sub["speaker"] == old_name:
                sub["speaker"] = new_name
        self._render_rows()
        self._render_speakers()

    def delete_speaker(self, name):
        if not messagebox.askyesno(
                "화자 삭제",
                f"'{name}' 화자를 삭제하시겠습니까?\n해당 화자가 지정된 자막은 '없음'으로 초기화됩니다.",
                parent=self):
            return
        self._push_undo()
        self.speakers.remove(name)
        for sub in self.subtitles:
            if sub["speaker"] == name:
                sub["speaker"] = ""
        self._render_rows()
        self._render_speakers()

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
        self.lbl_file.configure(text=os.path.basename(path))

        self.speakers = []
        for sub in self.subtitles:
            sp = sub.get("speaker", "")
            if sp and sp not in self.speakers:
                self.speakers.append(sp)

        self._hide_overlay()
        self._unsaved = False
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
        if self.player._backend is None:
            messagebox.showwarning(
                "미디어 재생 불가",
                "ffplay 또는 ffmpeg가 설치되어 있지 않습니다.\n"
                "https://ffmpeg.org 에서 설치 후 다시 시도하세요.",
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

    # ── 미디어 컨트롤 ────────────────────────
    def _on_space_key(self, event):
        """스페이스바: 자막 내용 Entry에 포커스가 있으면 무시, 그 외에는 재생/정지."""
        focused = self.focus_get()
        # 자막 내용(content) Entry인지 확인
        if isinstance(focused, tk.Entry):
            # row_widgets 에서 content Entry 목록 추출
            for row_info in self._row_widgets:
                if row_info.get("content") is focused:
                    return  # 자막 내용 편집 중 → 스페이스 통과
            # content가 아닌 다른 Entry(타임스탬프 등)도 포커스 해제 후 재생
            self.focus_set()
        self._media_play_pause()

    def _on_arrow_up(self, event):
        """위 방향키: Entry 포커스 중이면 통과, 그 외엔 윗 행 선택."""
        if isinstance(self.focus_get(), tk.Entry):
            return
        idx = getattr(self, "_selected_row_idx", None)
        if idx is None:
            idx = getattr(self, "_last_focused_idx", None)
        if idx is None or not self.subtitles:
            return "break"
        new_idx = max(0, idx - 1)
        if new_idx != idx:
            self._select_row(new_idx)
            self._scroll_to_row(new_idx)
        return "break"

    def _on_arrow_down(self, event):
        """아래 방향키: Entry 포커스 중이면 통과, 그 외엔 아랫 행 선택."""
        if isinstance(self.focus_get(), tk.Entry):
            return
        idx = getattr(self, "_selected_row_idx", None)
        if idx is None:
            idx = getattr(self, "_last_focused_idx", None)
        if idx is None or not self.subtitles:
            return "break"
        new_idx = min(len(self.subtitles) - 1, idx + 1)
        if new_idx != idx:
            self._select_row(new_idx)
            self._scroll_to_row(new_idx)
        return "break"
        if not self.media_path:
            return
        if self.player.is_playing:
            self.player.pause()
            self.btn_play.configure(text="▶")
            self._stop_progress_poll()
        else:
            self.player.play()
            self.btn_play.configure(text="⏸")
            self._start_progress_poll()

    def _media_play_pause(self):
        if not self.media_path:
            return
        if self.player.is_playing:
            self.player.pause()
            self.btn_play.configure(text="▶")
            self._stop_progress_poll()
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

    def _media_seek(self, delta):
        if not self.media_path:
            return
        was_playing = self.player.is_playing
        self.player.seek(delta)
        pos = self.player.position
        self.media_progress_var.set(pos)
        self.lbl_pos.configure(text=self._fmt_time(pos))
        self._pb_redraw()
        if was_playing:
            self.btn_play.configure(text="⏸")
            self._start_progress_poll()

    def _on_seek_drag(self, val):
        """진행바 드래그 중 위치 레이블만 갱신 (호환용)"""
        self.lbl_pos.configure(text=self._fmt_time(float(val)))

    def _on_seek_release(self, event):
        """진행바 놓았을 때 해당 위치로 seek (호환용)"""
        if not self.media_path:
            return
        pos = self.media_progress_var.get()
        was_playing = self.player.is_playing
        self.player.seek_to(pos)
        if was_playing:
            self.btn_play.configure(text="⏸")
            self._start_progress_poll()

    # ── 진행바 폴링 ──────────────────────────
    def _start_progress_poll(self):
        self._stop_progress_poll()
        self._poll_progress()

    def _poll_progress(self):
        if self.player.is_playing:
            pos = self.player.position
            self.media_progress_var.set(pos)
            self.lbl_pos.configure(text=self._fmt_time(pos))
            dur = self.player.duration
            if dur > 0:
                self.lbl_dur.configure(text=self._fmt_time(dur))
            self._pb_redraw()
            self._seek_job = self.after(100, self._poll_progress)  # 300→100ms
        else:
            self.btn_play.configure(text="▶")
            self._seek_job = None

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
            write_srt_tagged(self.subtitles, self.save_path)
            self._unsaved = False
            self.lbl_file.configure(text=f"{os.path.basename(self.save_path)}  ✓")
            self.after(800, lambda: self.lbl_file.configure(
                text=os.path.basename(self.save_path)))
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
            write_srt_tagged(self.subtitles, path)
            self._unsaved = False
            self.save_path = path
            self.lbl_file.configure(text=f"{os.path.basename(path)}  ✓")
            self.after(800, lambda: self.lbl_file.configure(
                text=os.path.basename(path)))
        except Exception as e:
            messagebox.showerror("저장 오류", str(e), parent=self)

    def _update_count(self):
        total  = len(self.subtitles)
        tagged = sum(1 for s in self.subtitles if s["speaker"])
        self.lbl_count.configure(
            text=f"총 {total}개 자막  |  화자 지정됨: {tagged}개")

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
            write_srt(subs, path)
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
                self.title("SRT Speaker Editor")
                self.geometry("1200x820")
                self.minsize(900, 620)
                self.configure(bg=BG)

                global FONT_FAMILY
                FONT_FAMILY = _pick_font(root=self)

                self.subtitles  = []
                self.speakers   = []
                self.filepath   = None
                self.save_path  = None
                self.edited_row = None
                self.player     = MediaPlayer()
                self.media_path = None
                self._seek_job  = None
                self._last_focused_idx = None
                self._unsaved   = False

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
                self.bind("<Left>",      lambda e: self._media_seek(-5))
                self.bind("<Right>",     lambda e: self._media_seek(+5))
                self.bind("<Control-z>", lambda e: self._undo())
                self.bind("<Control-Z>", lambda e: self._redo())
                self.bind("<Control-x>", self._on_cut)
                self.bind("<Control-c>", self._on_copy)
                self.bind("<Control-v>", self._on_paste)
                self.bind("<Up>",        self._on_arrow_up)
                self.bind("<Down>",      self._on_arrow_down)
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
