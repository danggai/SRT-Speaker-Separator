"""SRTEditor 메인 창과 실행 진입점. 기능별 메서드는 ui/ 믹스인에 나뉘어 있다."""
import re
import tkinter as tk
from tkinter import messagebox
from tkinter import ttk

from .ui.transcribe import TranscribeMixin
from .ui.diarize import DiarizeMixin
from .ui.settings import SettingsMixin
from .ui.timeline import TimelineMixin
from .ui.speakers import SpeakerMixin
from .ui.table import SubtitleTableMixin
from .ui.editing import EditingMixin
from .ui.playback import PlaybackMixin
from .ui.files import FileMixin
from . import theme
from .config import _load_config
from .ime import ImeCompositionOverlay
from .media import MEDIA_EXTS, MediaPlayer
from .speech import _DEFAULT_ASR_MODE
from .theme import (
    ACCENT,
    BG,
    BG2,
    BG3,
    BORDER,
    FG,
    FG_DIM,
    MEDIA_BG,
    ROW_EVEN,
    ROW_SEL,
    _apply_dark_titlebar,
    _pick_font,
)
from .version import APP_VERSION, GITHUB_TAGS_URL
from .widgets import PopupMenu, Tooltip


class SRTEditor(
    TranscribeMixin,
    DiarizeMixin,
    SettingsMixin,
    TimelineMixin,
    SpeakerMixin,
    SubtitleTableMixin,
    EditingMixin,
    PlaybackMixin,
    FileMixin,
    tk.Tk,
):
    """SRT 화자 편집기 메인 창. 기능별 메서드는 ui/ 믹스인에 있다."""

    def __init__(self):
        super().__init__()
        self.title("SRT Speaker Editer")
        self.geometry("1200x820")
        self.minsize(900, 620)
        self.configure(bg=BG)
        _apply_dark_titlebar(self)

        # 앱 창이 생성된 후 정확한 폰트 탐지 (빈 창 없음)
        theme.FONT_FAMILY = _pick_font(root=self)

        self.subtitles      = []
        self.speakers       = []
        self.speaker_colors = {}   # 화자명 → 사용자 지정 색상 (없으면 팔레트 자동 배정)
        self.filepath   = None
        self.save_path  = None
        self.edited_row = None
        self._last_focused_idx = None
        self._selection_anchor = None   # Shift+방향키 다중선택 앵커
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
        self._transcribe_max_chars  = _cfg.get("transcribe_max_chars", 25)
        self._transcribe_period     = _cfg.get("transcribe_period", False)
        self._transcribe_spellcheck = _cfg.get("transcribe_spellcheck", False)
        self._transcribe_language   = _cfg.get("transcribe_language", "ko")   # "ko" | "auto"
        self._diarize_mode_init    = _cfg.get("diarize_mode", _DEFAULT_ASR_MODE)
        self._diarize_device_init  = _cfg.get("diarize_device", "auto")
        self._diarize_spk_exact_init = _cfg.get("diarize_spk_exact", False)
        # 민감도 눈금 v2: 50 = 모델 기본 임계값. 이전 눈금으로 저장된 값은 50으로 초기화.
        if _cfg.get("diarize_sens_scale") == 2:
            self._diarize_sensitivity_init = _cfg.get("diarize_sensitivity", 50)
        else:
            self._diarize_sensitivity_init = 50
        _pn_raw = _cfg.get("proper_nouns", [])
        if isinstance(_pn_raw, dict):
            self._proper_nouns = list(_pn_raw.keys())     # 이전 버전(빈도 dict) 호환
        else:
            self._proper_nouns = list(dict.fromkeys(_pn_raw))   # 중복 제거, 순서 유지
        self._proper_nouns_enabled = _cfg.get("proper_nouns_enabled", True)
        self._global_speaker_colors = dict(_cfg.get("speaker_colors", {}))
        self._recent_tokens        = _cfg.get("recent_tokens", [])
        self._diarize_batch_init  = _cfg.get("diarize_batch", 3)   # index=3 → batch=16 (권장)

        self._build_styles()
        self._build_ui()
        self._setup_dnd()        # 드래그 앤 드롭
        # Windows에서 한글 조합 중인 글자가 입력창에 바로 보이도록
        self._ime_overlay = ImeCompositionOverlay(self)

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
        self.bind("<Shift-Up>",  self._on_shift_arrow_up)
        self.bind("<Shift-Down>", self._on_shift_arrow_down)
        # 재생바에서 자막을 드래그하는 도중, 마우스를 움직이지 않고 Shift만
        # 눌렀다 떼도 미리보기(흰 박스)가 그 즉시 갱신되도록 감지
        self.bind("<KeyPress-Shift_L>",
                 lambda e: self._on_shift_key_change(e, pressed=True))
        self.bind("<KeyPress-Shift_R>",
                 lambda e: self._on_shift_key_change(e, pressed=True))
        self.bind("<KeyRelease-Shift_L>",
                 lambda e: self._on_shift_key_change(e, pressed=False))
        self.bind("<KeyRelease-Shift_R>",
                 lambda e: self._on_shift_key_change(e, pressed=False))
        self.bind("<Prior>",     self._on_page_up)     # Page Up
        self.bind("<Next>",      self._on_page_down)   # Page Down
        self.bind("<grave>",     self._on_speaker_key)
        for _k in "123456789":
            self.bind(_k, self._on_speaker_key)
        self.bind("s", self._split_subtitle_shortcut)
        self.bind("S", self._split_subtitle_shortcut)
        try:
            # 한글 입력 상태(한영)에서 's' 키 위치에 대응하는 'ㄴ'도 동일하게 동작
            self.bind("ㄴ", self._split_subtitle_shortcut)
        except tk.TclError:
            pass
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
            font=(theme.FONT_FAMILY, 10))
        style.configure("Dim.TLabel",
            background=BG2, foreground=FG_DIM,
            font=(theme.FONT_FAMILY, 9))
        style.configure("MediaDim.TLabel",
            background=MEDIA_BG, foreground=FG_DIM,
            font=(theme.FONT_FAMILY, 9))
        style.configure("Title.TLabel",
            background=BG3, foreground=FG,
            font=(theme.FONT_FAMILY, 13, "bold"))
        style.configure("Header.TLabel",
            background=BG2, foreground=FG_DIM,
            font=(theme.FONT_FAMILY, 9, "bold"))

        style.configure("Accent.TButton",
            background=ACCENT, foreground="white",
            font=(theme.FONT_FAMILY, 10, "bold"),
            borderwidth=0, relief="flat", padding=(12, 6))
        style.map("Accent.TButton",
            background=[("active", "#7B5FB4"), ("pressed", "#5B3F94")])

        style.configure("Ghost.TButton",
            background=BG2, foreground=FG,
            font=(theme.FONT_FAMILY, 9),
            borderwidth=1, relief="flat", padding=(8, 4))
        style.map("Ghost.TButton",
            background=[("active", BG3), ("pressed", BORDER)])

        # 아이콘 전용 버튼 — 텍스트 없이 아이콘만, 정사각형에 가깝게
        style.configure("Icon.TButton",
            background=BG2, foreground=FG,
            font=(theme.FONT_FAMILY, 10),
            borderwidth=0, relief="flat", padding=(2, 2))
        style.map("Icon.TButton",
            background=[("active", BG3), ("pressed", BORDER)])

        style.configure("Media.TButton",
            background=BG3, foreground=FG,
            font=(theme.FONT_FAMILY, 11),
            borderwidth=0, relief="flat", padding=(10, 5))
        style.map("Media.TButton",
            background=[("active", "#333333"), ("pressed", "#111111")])

        style.configure("MediaPlay.TButton",
            background=ACCENT, foreground="white",
            font=(theme.FONT_FAMILY, 14, "bold"),
            borderwidth=0, relief="flat", padding=(12, 6))
        style.map("MediaPlay.TButton",
            background=[("active", "#7B5FB4")])

        style.configure("Danger.TButton",
            background="#2A1A2A", foreground="#FF6B8A",
            font=(theme.FONT_FAMILY, 9),
            borderwidth=0, relief="flat", padding=(8, 4))
        style.map("Danger.TButton",
            background=[("active", "#3A1A2A")])

        style.configure("Subs.Treeview",
            background=ROW_EVEN, fieldbackground=ROW_EVEN,
            foreground=FG, rowheight=36,
            font=(theme.FONT_FAMILY, 10), borderwidth=0)
        style.configure("Subs.Treeview.Heading",
            background=BG2, foreground=FG_DIM,
            font=(theme.FONT_FAMILY, 9, "bold"),
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
        file_menu = PopupMenu(self)
        file_menu.add_command(label="열기",             accelerator="Ctrl+O", command=self.open_file)
        file_menu.add_separator()
        file_menu.add_command(label="저장",             accelerator="Ctrl+S", command=self.save_file)
        file_menu.add_command(label="다른 이름으로 저장",                      command=self.save_file_as)
        file_menu.add_separator()
        file_menu.add_command(label="닫기 (홈으로)",                          command=self._close_to_home)

        _file_wrap = tk.Frame(top, bg=BG3,
                              highlightthickness=1, highlightbackground=BORDER)
        _file_wrap.pack(side="left", padx=(8, 0), pady=10)

        def _show_file_menu(e=None):
            w = _file_wrap
            file_menu.tk_popup(w.winfo_rootx(), w.winfo_rooty() + w.winfo_height())

        _file_btn = tk.Button(_file_wrap, text="📁  파일",
                              bg=BG3, fg=FG, relief="flat", bd=0,
                              font=(theme.FONT_FAMILY, 10), padx=7, pady=2,
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
                          font=(theme.FONT_FAMILY, 10), padx=7, pady=2,
                          cursor="hand2", takefocus=0,
                          activebackground=BG2, activeforeground=FG)
            b.pack(side="left")
            # 버튼 사이 구분선
            Tooltip(b, tip, delay=500)
            return b

        # 콤팩트 버튼 그룹 (실행취소 / 다시실행)
        _btn_group = tk.Frame(top, bg=BG3,
                              highlightthickness=1, highlightbackground=BORDER)
        _btn_group.pack(side="left", padx=(0, 4), pady=10)

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
            font=(theme.FONT_FAMILY, 9, "bold"),
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
                              font=(theme.FONT_FAMILY, 10), padx=8, pady=2,
                              cursor="hand2", takefocus=0,
                              activebackground=BG2, activeforeground=FG)
                b.pack(side="left")
                Tooltip(b, tip, delay=500)
            return grp

        # 미지정 카운터
        self.lbl_count = tk.Label(top, text="", bg=BG3,
                                  fg="#FF9A5C", cursor="hand2",
                                  font=(theme.FONT_FAMILY, 9))
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
        # 시작 후 잠시 뒤 업데이트 확인 (백그라운드, UI 렌더링을 막지 않음)
        self.after(1500, self._check_update_async)

        # 파일 없을 때 드롭 오버레이
        self._build_drop_overlay()

        # 어디를 클릭해도 content Entry 포커스/하이라이트 해제
        # (단, Entry 자체 클릭은 제외 — tkinter가 자동으로 포커스를 줌)
        self.bind_all("<Button-1>",  self._on_global_click, add=True)
        # 드래그가 진행되는 동안(B1-Motion)에도 한 번 더 검사 — Entry가 아닌
        # 위젯 위로 드래그가 넘어가는 첫 순간 확실하게 blur/커밋되도록 하는
        # 이중 안전장치 (예: 편집 중이던 Entry에서 시작된 드래그가 아니라도
        # 어떤 경로로든 Entry가 포커스를 유지한 채 드래그가 진행되는 것을 방지)
        self.bind_all("<B1-Motion>", self._on_global_click, add=True)

    # ── 드롭 존 오버레이 ─────────────────────
    def _build_drop_overlay(self):
        """파일 미로드 상태에서 보이는 드래그앤드롭 안내 오버레이"""
        self.overlay = tk.Frame(self, bg=BG, cursor="hand2")
        self.overlay.place(relx=0, rely=0, relwidth=1, relheight=1)

        # 중앙 카드
        card = tk.Frame(self.overlay, bg=BG2, padx=60, pady=50,
                        highlightbackground=BORDER, highlightthickness=2)
        card.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(card, text="📄 🎬", bg=BG2, fg=FG,
                 font=(theme.FONT_FAMILY, 40)).pack(pady=(0, 8))
        tk.Label(card, text="자막 또는 음성/영상 파일을 여기에 드래그하세요",
                 bg=BG2, fg=FG, font=(theme.FONT_FAMILY, 16, "bold")).pack()
        tk.Label(card,
                 text="SRT 자막 → 바로 편집 (같은 이름의 음성/영상도 함께 열림)\n"
                      "음성/영상만 → 같은 이름의 SRT를 열거나, 없으면 자막 자동 생성",
                 bg=BG2, fg=FG_DIM, font=(theme.FONT_FAMILY, 10),
                 justify="center").pack(pady=(10, 0))
        tk.Label(card, text="또는",
                 bg=BG2, fg=FG_DIM, font=(theme.FONT_FAMILY, 11)).pack(pady=8)

        btn_open = tk.Button(card, text="📂  파일 열기",
                             bg=ACCENT, fg="white",
                             font=(theme.FONT_FAMILY, 12, "bold"),
                             relief="flat", padx=20, pady=10,
                             cursor="hand2",
                             command=self.open_file,
                             activebackground="#c73550", activeforeground="white")
        btn_open.pack(pady=(0, 4))

        tk.Label(card,
                 text="지원: .srt  ·  " + " ".join(e.lstrip(".") for e in MEDIA_EXTS),
                 bg=BG2, fg=FG_DIM, font=(theme.FONT_FAMILY, 9)).pack(pady=(8, 0))

    def _hide_overlay(self):
        self.overlay.place_forget()

    def _show_overlay(self):
        self.overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.overlay.lift()

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
        self._open_paths([p[0] or p[1] for p in paths])


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
                # 우측 버튼 그룹들(설정/내보내기/화자분석)이 이미 side="right"로
                # 채워진 뒤에 마지막으로 packing되므로, 그 왼쪽(화자 분석 버튼
                # 바로 왼쪽 빈 공간)에 자연스럽게 자리잡는다.
                btn.pack(side="right", padx=(0, 6), pady=10)
                btn.lift()
        except Exception as e:
            import traceback; traceback.print_exc()

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

        # SRTEditor를 앞에 두면 SRTEditor.__init__이 실행되고, 그 안의
        # super().__init__()이 TkinterDnD.Tk.__init__(드래그앤드롭 초기화)을
        # 호출한다. (예전에는 __init__ 본문을 통째로 복사해 두어, 설정 불러오기·
        # 업데이트 확인·Shift+←/→ 단축키가 드래그앤드롭 버전에서 빠져 있었다)
        class SRTEditorDnD(SRTEditor, TkinterDnD.Tk):
            """tkinterdnd2 기반 드래그앤드롭 지원 버전"""

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
