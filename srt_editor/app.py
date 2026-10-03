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
from .ui.correct import CorrectionMixin
from .ui.tutorial import TutorialMixin
from .ui.shortcuts import ShortcutsMixin
from . import theme
from .config import _load_config, _save_config
from .ime import ImeCompositionOverlay
from .media import MediaPlayer
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
    ON_BG,
    ON_BG_HOVER,
    ON_BORDER,
    ON_FG,
    ON_RADIUS,
    ROW_EVEN,
    ROW_SEL,
    _apply_dark_titlebar,
    _pick_font,
)
from .version import APP_VERSION, GITHUB_TAGS_URL
from .widgets import Tooltip, flat_button, rounded_rect


_BADGE_BG = "#2B2838"   # 단축키 배지 배경
_BADGE_FG = "#CFC7EE"   # 단축키 배지 글자


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
    CorrectionMixin,
    TutorialMixin,
    ShortcutsMixin,
    tk.Tk,
):
    """SRT 화자 편집기 메인 창. 기능별 메서드는 ui/ 믹스인에 있다."""

    def __init__(self):
        super().__init__()
        self._set_doc_title(None)
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
        self._apply_key_hints(_cfg.get("show_key_hints", False))
        self._setup_dnd()        # 드래그 앤 드롭
        # Windows에서 한글 조합 중인 글자가 입력창에 바로 보이도록
        self._ime_overlay = ImeCompositionOverlay(self)

        # 업데이트 체크 (백그라운드, 앱 시작 3초 후)
        self.after(3000, self._check_update_async)
        # 첫 실행이면 튜토리얼 안내
        self.after(500, self._tutorial_maybe_ask)

        # 단축키
        self.bind("<Control-s>", lambda e: self.save_file())
        self.bind("<Control-S>", lambda e: self.save_file_as())
        self.bind("<Control-o>", lambda e: self.open_file())
        self.bind("<question>",  self._show_shortcuts)
        self.bind("<F1>",        self._show_shortcuts)
        self.bind("<space>",     self._on_space_key)
        self.bind("<Left>",       self._on_left_key)
        self.bind("<Right>",      self._on_right_key)
        self.bind("<Shift-Left>",  self._on_left_key)
        self.bind("<Shift-Right>", self._on_right_key)
        self.bind("<Control-z>", lambda e: self._undo())
        self.bind("<Control-Z>", lambda e: self._redo())
        self.bind("<Control-y>", lambda e: self._redo())   # 다시 실행 버튼 툴팁의 단축키
        self.bind("<Control-Y>", lambda e: self._redo())
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
        self.bind("a", self._add_subtitle_shortcut)
        self.bind("A", self._add_subtitle_shortcut)
        self.bind("s", self._split_subtitle_shortcut)
        self.bind("S", self._split_subtitle_shortcut)
        try:
            # 한글 입력 상태(한영)에서 's' 키 위치에 대응하는 'ㄴ'도 동일하게 동작
            self.bind("ㄴ", self._split_subtitle_shortcut)
            self.bind("ㅁ", self._add_subtitle_shortcut)
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
        # 상단 툴바 — Vrew처럼 아이콘(위) + 이름(아래) 버튼, 기능 묶음 사이 구분선
        TB_BG, TB_HOVER = "#202024", "#2E2E36"
        top = tk.Frame(self, bg=TB_BG)
        top.pack(fill="x")
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")
        self._top_bar = top   # 업데이트 배지 삽입용
        self._tb_btns = {}    # 이름 → 툴바 버튼 (튜토리얼 강조용)
        self._tb_icons = {}   # 이름 → 툴바 아이콘 캔버스 (단축키·저장 표시)

        def _defocus(fn):
            """버튼 실행 후 포커스를 루트로 돌려 스페이스바 재실행 방지."""
            def wrapper(*a, **k):
                fn(*a, **k)
                self.focus_set()
            return wrapper

        def _tool(icon, label, cmd, tip, side="left", bg=TB_BG, hover=TB_HOVER,
                  fg=FG_DIM, fg_hover=FG):
            """아이콘 + 이름을 세로로 둔 툴바 버튼. 마우스를 올리면 배경이 밝아진다."""
            box = tk.Frame(top, bg=bg, cursor="hand2")
            box.pack(side=side, padx=1, pady=5)
            # 아이콘은 캔버스에 그려 단축키·저장 표시를 배경 없이 겹쳐 그릴 수 있게 함
            import tkinter.font as tkfont
            ifont = tkfont.Font(self, family=theme.FONT_FAMILY, size=15)
            icon_w = ifont.measure(icon)
            # 위쪽 얇은 줄은 단축키 배지 자리 (켜고 꺼도 버튼 크기 그대로)
            ic = tk.Canvas(box, bg=bg, highlightthickness=0, cursor="hand2",
                           width=icon_w + 24, height=ifont.metrics("linespace") + 10)
            ic.pack(fill="x")
            ic.create_text(0, 0, text=icon, fill=fg_hover, font=ifont, tags="icon")
            ic.create_rectangle(0, 0, 0, 0, fill=_BADGE_BG, outline="", state="hidden",
                                tags="hintbg")
            ic.create_text(0, 0, text="", fill=_BADGE_FG, anchor="ne",
                           font=(theme.FONT_FAMILY, 7), tags="hint")
            box._fg = fg   # 이름 글자색 (토글 켜짐 표시에 사용)
            ic.create_oval(0, 0, 0, 0, fill=ACCENT, outline="", state="hidden", tags="dot")

            def _layout(e=None, c=ic):
                w, h = c.winfo_width(), c.winfo_height()
                c.coords("icon", w / 2, h / 2 + 5)
                c.coords("hint", w - 4, 0)
                bb = c.bbox("hint") if c.itemcget("hint", "text") else None
                if bb and bb[0] < 3:   # 버튼 폭을 넘으면 가운데 정렬해 양쪽이 잘리지 않게
                    c.coords("hint", (w + bb[2] - bb[0]) / 2, 0)
                    bb = c.bbox("hint")
                if bb:
                    c.coords("hintbg", bb[0] - 3, bb[1], bb[2] + 2, bb[3])
                x1 = (bb[0] - 6) if bb else w - 4   # 배지가 있으면 그 왼쪽에 점
                c.coords("dot", x1 - 8, 2, x1, 10)
            ic.bind("<Configure>", _layout)
            ic.relayout = _layout
            tx = tk.Label(box, text=label, bg=bg, fg=fg, cursor="hand2",
                          font=(theme.FONT_FAMILY, 8))
            tx.pack(padx=8, pady=(0, 5))
            parts = (box, ic, tx)

            def _enter(e):
                for w in (box,) + tuple(box.winfo_children()):
                    w.configure(bg=hover)
                tx.configure(fg=fg_hover)

            def _leave(e):
                for w in (box,) + tuple(box.winfo_children()):
                    w.configure(bg=bg)
                tx.configure(fg=box._fg)

            run = _defocus(cmd)
            for w in parts:
                w.bind("<Enter>", _enter)
                w.bind("<Leave>", _leave)
                w.bind("<Button-1>", lambda e: run())
            for w in (ic, tx):
                Tooltip(w, tip, delay=500)
            self._tb_btns[label] = box
            self._tb_icons[label] = ic
            box._label = tx
            return box

        def _toggle_tool(icon, label, cmd, tip, side="right"):
            """켜짐 상태를 둥근 테두리와 연한 배경으로 보여 주는 툴바 토글 버튼."""
            import tkinter.font as tkfont
            ifont = tkfont.Font(self, family=theme.FONT_FAMILY, size=15)
            lfont = tkfont.Font(self, family=theme.FONT_FAMILY, size=8)
            w = max(ifont.measure(icon) + 24, lfont.measure(label) + 16)
            h = ifont.metrics("linespace") + 10 + lfont.metrics("linespace") + 9   # 다른 툴바 버튼과 같은 높이
            cv = tk.Canvas(top, width=w, height=h, bg=TB_BG, highlightthickness=0, cursor="hand2")
            cv.pack(side=side, padx=1, pady=5)
            rounded_rect(cv, 1, 1, w - 2, h - 2, ON_RADIUS, fill=TB_BG, outline=TB_BG, tags="box")
            iy = (ifont.metrics("linespace") + 10) / 2 + 5
            cv.create_text(w / 2, iy, text=icon, fill=FG, font=ifont)
            cv.create_text(w / 2, h - 7 - lfont.metrics("linespace") / 2, text=label,
                           fill=FG_DIM, font=lfont, tags="label")
            state = {"on": False, "hover": False}

            def _paint():
                on, hv = state["on"], state["hover"]
                fill = (ON_BG_HOVER if hv else ON_BG) if on else (TB_HOVER if hv else TB_BG)
                cv.itemconfigure("box", fill=fill, outline=ON_BORDER if on else fill)
                cv.itemconfigure("label", fill=ON_FG if on else (FG if hv else FG_DIM))

            def _set_on(on):
                state["on"] = on
                _paint()
            cv.set_on = _set_on
            cv.bind("<Enter>", lambda e: (state.update(hover=True), _paint()))
            cv.bind("<Leave>", lambda e: (state.update(hover=False), _paint()))
            cv.bind("<Button-1>", lambda e: _defocus(cmd)())
            Tooltip(cv, tip, delay=500)
            self._tb_btns[label] = cv
            return cv

        def _sep(side="left"):
            tk.Frame(top, bg="#34343C", width=1).pack(side=side, fill="y", padx=6, pady=12)

        tk.Frame(top, bg=TB_BG, width=6).pack(side="left")
        _tool("📂", "열기", self.open_file, "자막 또는 음성/영상 열기  [Ctrl+O]")
        _tool("💾", "저장", self.save_file, "저장  [Ctrl+S]")
        _tool("🗂", "다른 이름으로", self.save_file_as, "다른 이름으로 저장  [Ctrl+Shift+S]")
        _sep()
        _tool("↩", "실행 취소", self._undo, "실행 취소  [Ctrl+Z]")
        _tool("↪", "다시 실행", self._redo, "다시 실행  [Ctrl+Y]")
        _tool("🗑", "자막 삭제", self._on_delete, "선택한 자막 삭제  [Delete]")
        _sep()
        _tool("🎙", "화자 분석", self._open_diarize_dialog, "화자 자동 분석")
        _tool("✏", "자막 교정", self._open_correction_dialog, "잘못 인식된 표기 찾아서 고치기")
        _sep()
        _tool("⌂", "홈으로", self._close_to_home, "파일 닫고 처음 화면으로")

        # 오른쪽 끝부터: 내보내기(강조) → 설정 → 미지정 카운터
        tk.Frame(top, bg=TB_BG, width=6).pack(side="right")
        # 내보내기는 진한 보라 바탕으로 강조
        self._export_btn = _tool("📤", "내보내기", self.export, "화자별 자막 내보내기",
                                 side="right", bg="#5B3FA0", hover="#6B4DB4",
                                 fg="white", fg_hover="white")
        _tool("⚙", "설정", self._open_settings, "설정", side="right")
        _toggle_tool("⌨", "단축키", self._toggle_key_hints, "버튼에 단축키 표시 켜기/끄기")
        _sep(side="right")

        # 미지정 카운터
        self.lbl_count = tk.Label(top, text="", bg=TB_BG,
                                  fg="#FF9A5C", cursor="hand2",
                                  font=(theme.FONT_FAMILY, 9))
        self.lbl_count.pack(side="right", padx=(0, 4), pady=8)
        self.lbl_count.bind("<Button-1>", lambda e: self._goto_next_unassigned())

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

        # 하단 타임라인: 창 전체 폭 (본문보다 먼저 배치)
        self._build_media_panel(self)

        # 본문 영역 (사이드바 + 테이블)
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)

        self._build_sidebar(body)
        right_col = ttk.Frame(body)
        right_col.pack(side="left", fill="both", expand=True)

        self._build_table(right_col)
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
        """파일 미로드 상태에서 보이는 홈 화면 (열기 카드 + 최근 파일)."""
        self.overlay = tk.Frame(self, bg=BG)
        self.overlay.place(relx=0, rely=0, relwidth=1, relheight=1)

        wrap = tk.Frame(self.overlay, bg=BG)
        wrap.place(relx=0.5, rely=0.45, anchor="center")

        # 열기 카드
        card = tk.Frame(wrap, bg=BG2, padx=70, pady=36,
                        highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="x")
        tk.Label(card, text="📄 🎬", bg=BG2, fg=FG,
                 font=(theme.FONT_FAMILY, 28)).pack(pady=(0, 6))
        tk.Label(card, text="파일을 여기에 끌어다 놓으세요",
                 bg=BG2, fg=FG, font=(theme.FONT_FAMILY, 15, "bold")).pack()
        tk.Label(card, text="SRT 자막 또는 음성·영상 파일",
                 bg=BG2, fg=FG_DIM, font=(theme.FONT_FAMILY, 10)).pack(pady=(6, 18))
        flat_button(card, "📂  파일 열기", self.open_file,
                    bg=ACCENT, fg="white", hover="#AE96E2",
                    font=(theme.FONT_FAMILY, 11, "bold"), padx=22, pady=9).pack()

        # 최근 파일 (홈 화면이 보일 때마다 갱신)
        self._recent_box = tk.Frame(wrap, bg=BG)

        tut = tk.Label(wrap, text="튜토리얼 다시 보기", bg=BG, fg="#5A5A66",
                       cursor="hand2", font=(theme.FONT_FAMILY, 9))
        tut.pack(pady=(18, 0))
        tut.bind("<Enter>", lambda e: tut.configure(fg=FG_DIM))
        tut.bind("<Leave>", lambda e: tut.configure(fg="#5A5A66"))
        tut.bind("<Button-1>", lambda e: self._tutorial_start())
        self._tut_link = tut
        self._render_recent_files()

    @property
    def _unsaved(self):
        return self.__dict__.get("_unsaved_flag", False)

    @_unsaved.setter
    def _unsaved(self, value):
        value = bool(value)
        if value == self.__dict__.get("_unsaved_flag"):
            return
        self.__dict__["_unsaved_flag"] = value
        self._update_title()
        ic = getattr(self, "_tb_icons", {}).get("저장")
        if ic is not None:   # 저장 안 된 변경이 있으면 저장 버튼에 점 표시
            ic.itemconfigure("dot", state="normal" if value else "hidden")

    # 버튼 우상단에 표시할 단축키
    _TB_KEY_HINTS = {"열기": "Ctrl+O", "저장": "Ctrl+S", "다른 이름으로": "Ctrl+⇧+S",
                     "실행 취소": "Ctrl+Z", "다시 실행": "Ctrl+Y", "자막 삭제": "Del"}

    def _toggle_key_hints(self):
        on = not getattr(self, "_key_hints_on", False)
        self._apply_key_hints(on)
        cfg = _load_config()
        cfg["show_key_hints"] = on
        _save_config(cfg)

    def _apply_key_hints(self, on):
        """주요 버튼 우상단에 단축키 배지를 띄우거나 숨긴다 (버튼 크기는 그대로)."""
        self._key_hints_on = on
        for label, key in self._TB_KEY_HINTS.items():
            ic = self._tb_icons.get(label)
            if ic is not None:
                ic.itemconfigure("hint", text=key if on else "")
                ic.itemconfigure("hintbg", state="normal" if on else "hidden")
                ic.relayout()
        for badge in getattr(self, "_key_badges", []):
            badge.destroy()
        self._key_badges = []
        if on:
            for widget, key in ((self._split_btn, "S"), (self._add_btn, "A"), (self.btn_play, "Space"),
                                (self.btn_prev, "←"), (self.btn_next, "→")):
                badge = tk.Label(self, text=key, bg=_BADGE_BG, fg=_BADGE_FG,
                                 font=(theme.FONT_FAMILY, 7), padx=3, pady=0)
                # 버튼 우상단 바로 위에 띄움 (레이아웃에 영향 없음)
                badge.place(in_=widget, relx=1.0, x=2, y=4, anchor="se")
                badge.lower(self.overlay)   # 홈 화면이 떠 있으면 가려지게
                badge.bind("<Button-1>", lambda e, w=widget: w.event_generate("<Button-1>"))
                badge.bind("<ButtonRelease-1>",
                           lambda e, w=widget: w.event_generate("<ButtonRelease-1>", x=1, y=1))
                self._key_badges.append(badge)
        toggle = self._tb_btns.get("단축키")
        if toggle is not None:   # 켜짐: 둥근 테두리 + 연한 배경
            toggle.set_on(on)

    def _set_doc_title(self, name):
        """창 제목에 표시할 파일 이름을 바꾼다 (None이면 앱 이름만)."""
        self._doc_name = name
        self._update_title()

    def _update_title(self, suffix=""):
        base = f"SRT Speaker Editer v{APP_VERSION}"
        name = getattr(self, "_doc_name", None)
        mark = "● " if self._unsaved and name else ""   # 저장 안 된 변경 표시
        self.title(mark + (f"{name} - {base}" if name else base) + suffix)

    def _hide_overlay(self):
        self.overlay.place_forget()

    def _render_recent_files(self):
        """홈 화면의 최근 파일 목록을 다시 그린다."""
        import os
        box = self._recent_box
        for w in box.winfo_children():
            w.destroy()
        paths = self._recent_files()
        if not paths:
            box.pack_forget()
            return
        box.pack(fill="x", pady=(22, 0), before=self._tut_link)
        tk.Label(box, text="최근 파일", bg=BG, fg=FG_DIM,
                 font=(theme.FONT_FAMILY, 9, "bold")).pack(anchor="w", padx=2, pady=(0, 6))
        for p in paths:
            row = tk.Frame(box, bg=BG2, cursor="hand2")
            row.pack(fill="x", pady=2)
            icon = tk.Label(row, text="📄", bg=BG2, fg=FG_DIM, cursor="hand2",
                            font=(theme.FONT_FAMILY, 13))
            icon.pack(side="left", padx=(12, 8), pady=6)
            text = tk.Frame(row, bg=BG2, cursor="hand2")
            text.pack(side="left", fill="x", expand=True, pady=6)
            name = tk.Label(text, text=os.path.basename(p), bg=BG2, fg=FG, cursor="hand2",
                            font=(theme.FONT_FAMILY, 10, "bold"), anchor="w")
            name.pack(fill="x")
            folder = tk.Label(text, text=os.path.dirname(p), bg=BG2, fg="#6A6A76",
                              cursor="hand2", font=(theme.FONT_FAMILY, 8), anchor="w")
            folder.pack(fill="x")
            parts = (row, icon, text, name, folder)
            for w in parts:
                w.bind("<Enter>", lambda e, ps=parts: [x.configure(bg=BG3) for x in ps])
                w.bind("<Leave>", lambda e, ps=parts: [x.configure(bg=BG2) for x in ps])
                w.bind("<Button-1>", lambda e, path=p: self._open_paths([path]))
            Tooltip(name, p, delay=500)

    def _show_overlay(self):
        self._render_recent_files()
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
        ime = getattr(self, "_ime_overlay", None)
        if ime is not None:
            ime.unhook_all()
        super().destroy()


# ─────────────────────────────────────────────
#  tkinterdnd2 지원 여부에 따라 루트 클래스 선택
# ─────────────────────────────────────────────
def main():
    try:
        from tkinterdnd2 import TkinterDnD

        # SRTEditor.__init__ → super()로 TkinterDnD.Tk 초기화
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
