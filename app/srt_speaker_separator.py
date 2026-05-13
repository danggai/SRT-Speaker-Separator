import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import re
import os
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
ROW_SEL   = "#2D2040"   # 선택 시 연보라 tint
MEDIA_BG  = "#111111"

# ─────────────────────────────────────────────
#  전역 설정 (정규식 화자 구분)
# ─────────────────────────────────────────────
DEFAULT_SPEAKER_PATTERN = r"^\[([^\]]+)\]\s*"
g_speaker_pattern = DEFAULT_SPEAKER_PATTERN

# ─────────────────────────────────────────────
#  한글 지원 폰트 탐색
# ─────────────────────────────────────────────
def _pick_font():
    """시스템에서 한글 지원 폰트를 찾아 반환"""
    try:
        import tkinter.font as tkfont
        root_tmp = tk.Tk()
        root_tmp.withdraw()
        available = set(tkfont.families())
        root_tmp.destroy()
    except Exception:
        available = set()

    candidates = [
        "Malgun Gothic",       # Windows 기본 한글
        "맑은 고딕",
        "Apple SD Gothic Neo", # macOS 기본 한글
        "AppleGothic",
        "Nanum Gothic",        # 나눔고딕 (설치 시)
        "NanumGothic",
        "NotoSansCJKkr",       # Noto CJK
        "Noto Sans CJK KR",
        "UnDotum",             # Linux 한글
        "Gulim",
        "Segoe UI",            # fallback
        "TkDefaultFont",
    ]
    for f in candidates:
        if f in available:
            return f
    return "TkDefaultFont"

FONT_FAMILY = _pick_font()
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
                capture_output=True, text=True, timeout=10)
            info = json.loads(result.stdout)
            return float(info["format"]["duration"])
        except Exception:
            pass
        try:
            result = subprocess.run(
                ["ffmpeg", "-i", path],
                capture_output=True, text=True, timeout=10)
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
            cmd = [
                "ffplay", "-nodisp", "-autoexit",
                "-ss", str(start_sec),
                self._filepath
            ]
        elif backend == "afplay":
            cmd = ["afplay", "-t", str(max(0, self._duration - start_sec)),
                   "-q", "1", self._filepath]
        else:
            return

        self._proc = subprocess.Popen(
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

        self.subtitles  = []
        self.speakers   = []
        self.filepath   = None
        self.save_path  = None
        self.edited_row = None
        self._last_focused_idx = None

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
        self.bind("<space>",     lambda e: self._media_play_pause())
        self.bind("<Left>",      lambda e: self._media_seek(-5))
        self.bind("<Right>",     lambda e: self._media_seek(+5))

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
    def _build_table(self, parent):
        right = ttk.Frame(parent)
        right.pack(fill="both", expand=True)

        # 헤더
        hdr = tk.Frame(right, bg=BG2, height=32)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        for text, width, anchor in [
            ("#",       38,  "center"),
            ("타임스탬프", 200, "w"),
            ("자막 내용", 0,   "w"),
            ("화자",     140, "center"),
            ("",        50,  "center"),
        ]:
            lbl = tk.Label(hdr, text=text, bg=BG2, fg=FG_DIM,
                           font=(FONT_FAMILY, 9, "bold"), anchor=anchor)
            if width == 0:
                lbl.pack(side="left", fill="x", expand=True, padx=6, pady=5)
            else:
                lbl.pack(side="left", padx=6, pady=5)
                lbl.configure(width=width // 10)

        container = tk.Frame(right, bg=BG)
        container.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(container, bg=BG, highlightthickness=0, bd=0)
        self.vsb = ttk.Scrollbar(container, orient="vertical",
                                 command=self.canvas.yview)
        self.rows_frame = tk.Frame(self.canvas, bg=BG)
        self.rows_frame.bind("<Configure>",
            lambda e: self.canvas.configure(
                scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.rows_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vsb.pack(side="right", fill="y")

        self.canvas.bind_all("<MouseWheel>",
            lambda e: self.canvas.yview_scroll(-1*(e.delta//120), "units"))

        # SRT 파일 드래그 드롭 영역 (테이블 영역)
        self.canvas.bind("<Enter>", lambda e: None)

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
            return
        c.delete("all")
        dur = self.player.duration if self.player.duration > 0 else 1
        pos = self.media_progress_var.get()
        ratio = min(pos / dur, 1.0)
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
        self.player._kill_proc()
        self.player._position = pos
        self.player._playing  = False
        if was_playing:
            self.player.play()
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
        # 현재 self._last_focused_idx 를 사용 (없으면 마지막 행)
        idx = getattr(self, "_last_focused_idx", None)
        if idx is None or idx >= len(self.subtitles):
            return
        self.subtitles[idx]["speaker"] = name
        self._render_rows()
        self._render_speakers()

    # ── 설정 창 ────────────────────────────
    def _open_settings(self):
        """설정 창: 정규식 화자 구분 패턴 변경"""
        win = tk.Toplevel(self)
        win.title("설정")
        win.configure(bg=BG)
        win.geometry("520x260")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()

        tk.Label(win, text="설정", bg=BG, fg=FG,
                 font=(FONT_FAMILY, 14, "bold")).pack(anchor="w", padx=20, pady=(18, 4))

        tk.Frame(win, bg=BORDER, height=1).pack(fill="x", padx=20)

        # 정규식 패턴
        sec = tk.Frame(win, bg=BG)
        sec.pack(fill="x", padx=20, pady=14)

        tk.Label(sec, text="화자 구분 정규식 패턴", bg=BG, fg=FG,
                 font=(FONT_FAMILY, 10, "bold")).pack(anchor="w")
        tk.Label(sec, text="첫 번째 캡처 그룹 ()이 화자 이름으로 인식됩니다.",
                 bg=BG, fg=FG_DIM, font=(FONT_FAMILY, 9)).pack(anchor="w", pady=(2, 6))

        pat_var = tk.StringVar(value=g_speaker_pattern)
        pat_entry = tk.Entry(sec, textvariable=pat_var, width=52,
                             bg=BG3, fg=ACCENT, insertbackground=FG,
                             font=(FONT_MONO, 10), relief="flat",
                             highlightthickness=1, highlightbackground=BORDER,
                             highlightcolor=ACCENT)
        pat_entry.pack(fill="x", ipady=4)

        info_lbl = tk.Label(sec, text="", bg=BG, fg="#FF6B8A",
                            font=(FONT_FAMILY, 9))
        info_lbl.pack(anchor="w", pady=(4, 0))

        def validate_pattern(p):
            try:
                re.compile(p)
                return True
            except re.error as err:
                return str(err)

        def on_apply():
            global g_speaker_pattern
            p = pat_var.get().strip()
            result = validate_pattern(p)
            if result is not True:
                info_lbl.configure(text=f"❌ 정규식 오류: {result}")
                return
            g_speaker_pattern = p
            info_lbl.configure(text="✔ 적용되었습니다.", fg=ACCENT)
            win.after(1500, win.destroy)

        def on_reset():
            pat_var.set(DEFAULT_SPEAKER_PATTERN)
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
        for idx, sub in enumerate(self.subtitles):
            self._make_row(idx, sub)
        self._update_count()

    def _make_row(self, idx, sub):
        bg = ROW_ODD if idx % 2 == 0 else ROW_EVEN
        row = tk.Frame(self.rows_frame, bg=bg)
        row.pack(fill="x")

        # 번호 (클릭 시 해당 타임라인으로 이동)
        num_lbl = tk.Label(row, text=str(idx + 1), width=3, bg=bg, fg=FG_DIM,
                 font=(FONT_FAMILY, 9), cursor="hand2")
        num_lbl.pack(side="left", padx=(8, 4), pady=8)
        num_lbl.bind("<Button-1>", lambda e, i=idx: self._seek_to_subtitle(i))

        # 타임스탬프 (클릭 시 타임라인 이동)
        ts_var = tk.StringVar(value=sub["timestamp"])
        ts_entry = tk.Entry(row, textvariable=ts_var, width=26,
                            bg=BG3, fg=ACCENT, insertbackground=FG,
                            font=(FONT_MONO, 9), relief="flat",
                            highlightthickness=1, highlightbackground=BORDER,
                            highlightcolor=ACCENT, cursor="hand2")
        ts_entry.pack(side="left", padx=(0, 8), pady=6, ipady=3)
        ts_entry.bind("<FocusOut>", lambda e, i=idx, v=ts_var: self._save_ts(i, v))
        ts_entry.bind("<Return>",   lambda e, i=idx, v=ts_var: self._save_ts(i, v))
        ts_entry.bind("<Button-1>", lambda e, i=idx: self._seek_to_subtitle(i))

        # 자막 텍스트
        txt_var = tk.StringVar(value=sub["text"])
        txt_entry = tk.Entry(row, textvariable=txt_var,
                             bg=BG3, fg=FG, insertbackground=FG,
                             font=(FONT_FAMILY, 10), relief="flat",
                             highlightthickness=1, highlightbackground=BORDER,
                             highlightcolor=ACCENT)
        txt_entry.pack(side="left", fill="x", expand=True, padx=(0, 8), pady=6, ipady=3)
        txt_entry.bind("<FocusOut>", lambda e, i=idx, v=txt_var: self._save_text(i, v))
        txt_entry.bind("<Return>",   lambda e, i=idx, v=txt_var: self._save_text(i, v))
        txt_entry.bind("<FocusIn>",  lambda e, i=idx: setattr(self, "_last_focused_idx", i))

        # ── 화자 선택: 박스 버튼 형태 ────────
        spk_frame = tk.Frame(row, bg=bg)
        spk_frame.pack(side="left", padx=(0, 8), pady=4)
        self._build_speaker_selector(spk_frame, idx, sub, bg)

        # 삭제 버튼
        tk.Button(row, text="✕", bg=bg, fg="#FF6B8A",
                  font=(FONT_FAMILY, 11), bd=0, cursor="hand2",
                  activebackground=bg, activeforeground=ACCENT,
                  command=lambda i=idx: self.delete_row(i)
                  ).pack(side="left", padx=(0, 8), pady=6)

        # 호버
        hover_bg = "#2A2A2A"
        for widget in [row]:
            widget.bind("<Enter>",
                lambda e, r=row:
                    [w.configure(bg=hover_bg) for w in [r] + r.winfo_children()
                     if isinstance(w, (tk.Frame, tk.Label, tk.Button))])
            widget.bind("<Leave>",
                lambda e, r=row, b=bg:
                    [w.configure(bg=b) for w in [r] + r.winfo_children()
                     if isinstance(w, (tk.Frame, tk.Label, tk.Button))])

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
        self.player._kill_proc()
        self.player._position = pos
        self.player._playing  = False
        self.media_progress_var.set(pos)
        self.lbl_pos.configure(text=self._fmt_time(pos))
        self._pb_redraw()
        if was_playing:
            self.player.play()
            self.btn_play.configure(text="⏸")
            self._start_progress_poll()

    def _build_speaker_selector(self, parent, idx, sub, row_bg):
        """화자를 박스 버튼 형태로 선택 (드롭다운 대신)"""
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

    def _save_text(self, idx, var):
        self.subtitles[idx]["text"] = var.get()

    # ── 화자 관리 ─────────────────────────────
    def add_speaker(self):
        name = simpledialog.askstring("화자 추가", "화자 이름을 입력하세요:", parent=self)
        if not name or not name.strip():
            return
        name = name.strip()
        if name in self.speakers:
            messagebox.showwarning("중복", f"'{name}' 화자가 이미 있습니다.", parent=self)
            return
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
        self.speakers.remove(name)
        for sub in self.subtitles:
            if sub["speaker"] == name:
                sub["speaker"] = ""
        self._render_rows()
        self._render_speakers()

    def delete_row(self, idx):
        self.subtitles.pop(idx)
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
        dur = self.player.load(path)
        self.media_path = path

        name = os.path.basename(path)
        self.lbl_media.configure(text=f"🎵  {name}", fg=FG)
        self.media_progress_var.set(0)
        self.lbl_dur.configure(text=self._fmt_time(dur))
        self.lbl_pos.configure(text="0:00:00")
        self.btn_play.configure(text="▶")
        self.after(50, self._pb_redraw)

    # ── 미디어 컨트롤 ────────────────────────
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
        self.player._kill_proc()
        self.player._position = pos
        self.player._playing  = False
        if was_playing:
            self.player.play()
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
            self._pb_redraw()
            self._seek_job = self.after(300, self._poll_progress)
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
        out_dir = filedialog.askdirectory(title="저장할 폴더 선택", parent=self)
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

        class SRTEditorDnD(SRTEditor):
            """tkinterdnd2 기반 드래그앤드롭 지원 버전"""
            def __init__(self):
                # Tk.__init__ 대신 TkinterDnD.Tk 방식으로 초기화
                TkinterDnD.Tk.__init__(self)
                self.title("SRT Speaker Editor")
                self.geometry("1200x820")
                self.minsize(900, 620)
                self.configure(bg=BG)

                self.subtitles  = []
                self.speakers   = []
                self.filepath   = None
                self.save_path  = None
                self.edited_row = None
                self.player     = MediaPlayer()
                self.media_path = None
                self._seek_job  = None
                self._last_focused_idx = None

                self._build_styles()
                self._build_ui()
                self._setup_dnd()

                self.bind("<Control-s>", lambda e: self.save_file())
                self.bind("<Control-S>", lambda e: self.save_file_as())
                self.bind("<Control-o>", lambda e: self.open_file())
                self.bind("<space>",     lambda e: self._media_play_pause())
                self.bind("<Left>",      lambda e: self._media_seek(-5))
                self.bind("<Right>",     lambda e: self._media_seek(+5))

        # TkinterDnD.Tk 를 상속해야 drop_target_register 사용 가능
        class _Root(TkinterDnD.Tk):
            pass

        # SRTEditorDnD 의 MRO를 TkinterDnD.Tk 기반으로 교체
        app = SRTEditorDnD.__new__(SRTEditorDnD)
        TkinterDnD.Tk.__init__(app)
        SRTEditorDnD.__init__(app)
        app.mainloop()

    except ImportError:
        # tkinterdnd2 없는 경우: 기본 Tk (드래그앤드롭 비활성)
        app = SRTEditor()
        app.mainloop()
    except Exception:
        app = SRTEditor()
        app.mainloop()


if __name__ == "__main__":
    main()
