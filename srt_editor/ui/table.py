"""자막 표(가상 스크롤 슬롯) 렌더링·선택·열 레이아웃."""
import re
import tkinter as tk
from tkinter import ttk

from .. import theme
from ..theme import ACCENT, BG, BG2, BG3, BORDER, FG, FG_DIM, FONT_MONO, ROW_HL
from ..widgets import PopupMenu


class SubtitleTableMixin:
    """자막 표(가상 스크롤 슬롯) 렌더링·선택·열 레이아웃."""

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


    # ── 자막 테이블 (가상 스크롤, 한 줄 카드) ─────────────
    # 컬럼: num / time(시작 + 길이) / content(가변) / speaker
    _WF_HANDLE_W = 5   # 파형 자막 핸들 너비(px)
    _MIN_SUB_DURATION = 0.05   # 리사이즈 시 강제되는 최소 자막 길이(초)
    _COL_IDS   = ["num", "time", "speaker"]
    _COL_DEF_W = {"num": 44, "time": 150, "speaker": 220}
    ROW_H      = 38   # 행 높이 (카드 32 + 위아래 간격 6)
    _CARD_X    = 8    # 카드 좌우 바깥 여백
    _CARD_Y    = 3    # 카드 위아래 바깥 여백
    _CARD_R    = 8    # 카드 모서리 둥글기
    _CARD_BG       = BG2
    _CARD_SEL_BG   = ROW_HL
    _CARD_PLAY_BORDER = "#2F5A2F"
    _TS_EDIT_W = 118  # 시간 편집 입력칸 하나의 너비
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

        _titles = {"num": "#", "time": "시간 (선택 후 클릭: 편집)",
                   "content": "자막 내용", "speaker": "화자"}
        self._hdr_wins = {}
        for cid in list(self._COL_IDS) + ["content"]:
            lbl = tk.Label(hdr_c, text=_titles[cid],
                           bg=BG2, fg=FG_DIM,
                           font=(theme.FONT_FAMILY, 9, "bold"), anchor="w")
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
        """빈 카드(행) 한 세트 생성. 배치는 _apply_col_to_slot."""
        slot_idx = len(self._slot_frames)
        h   = self.ROW_H
        card_bg = self._CARD_BG

        row = tk.Canvas(self.canvas, bg=BG, height=h, highlightthickness=0, bd=0)
        row.create_polygon(0, 0, 0, 0, smooth=True, tags="card",
                           fill=card_bg, outline=BORDER)
        for _ in range(3):   # 번호|시간|자막|화자 칸 구분선
            row.create_line(0, 0, 0, 0, fill=BORDER, tags="div")

        wi = {}  # cid → widget

        # 번호
        num_lbl = tk.Label(row, text="", bg=card_bg, fg=FG_DIM,
                           font=(theme.FONT_FAMILY, 9), anchor="center", cursor="hand2")
        wi["num"] = num_lbl

        # 시간: '0:30.37 +2.12초' (더블클릭하면 아래 입력칸으로 편집)
        time_frame = tk.Frame(row, bg=card_bg, cursor="hand2")
        time_lbl = tk.Label(time_frame, text="", bg=card_bg, fg="#B9A6EC",
                            font=(FONT_MONO, 10, "bold"), cursor="hand2")
        time_lbl.pack(side="left", padx=(10, 5))
        dur_lbl = tk.Label(time_frame, text="", bg=card_bg, fg=FG_DIM,
                           font=(theme.FONT_FAMILY, 8), cursor="hand2")
        dur_lbl.pack(side="left")
        wi["time"] = time_frame
        wi["time_lbl"] = time_lbl
        wi["dur_lbl"] = dur_lbl
        wi["_ts_editing"] = False

        # 시작/종료 타임스탬프 입력칸 — 평소엔 숨기고 시간 편집 중에만 표시
        ts_s_var = tk.StringVar()
        ts_s = tk.Entry(row, textvariable=ts_s_var,
                        bg=BG3, fg=ACCENT, insertbackground=FG,
                        font=(FONT_MONO, 9), relief="flat",
                        highlightthickness=1, highlightbackground=BORDER,
                        highlightcolor=ACCENT)
        wi["ts_s"] = ts_s
        wi["ts_s_var"] = ts_s_var

        ts_e_var = tk.StringVar()
        ts_e = tk.Entry(row, textvariable=ts_e_var,
                        bg=BG3, fg=ACCENT, insertbackground=FG,
                        font=(FONT_MONO, 9), relief="flat",
                        highlightthickness=1, highlightbackground=BORDER,
                        highlightcolor=ACCENT)
        wi["ts_e"] = ts_e
        wi["ts_e_var"] = ts_e_var

        # 내용 — 카드와 같은 배경으로 두고, 편집 중일 때만 보라색 테두리
        txt_var = tk.StringVar()
        txt_e = tk.Entry(row, textvariable=txt_var,
                         bg=card_bg, fg=FG, insertbackground=FG,
                         font=(theme.FONT_FAMILY, 10), relief="flat",
                         highlightthickness=1, highlightbackground=card_bg,
                         highlightcolor=ACCENT)
        wi["content"] = txt_e
        wi["txt_var"] = txt_var

        # 화자 pill — 슬롯 생성 시 현재 화자 수 + 1(없음) 만큼 미리 생성
        spk_frame = tk.Frame(row, bg=card_bg)
        wi["speaker"] = spk_frame

        pill_labels = []
        n_pills = len(self.speakers) + 1   # (없음) + 화자들
        for pi in range(max(n_pills, 8)):   # 최소 8개 확보 (화자 추가 시 여유)
            lbl = tk.Label(spk_frame, text="", bg=card_bg,
                           fg=FG_DIM, font=(theme.FONT_FAMILY, 9),
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
        # 시간 칸: 선택된 자막이면 클릭으로 편집, 아니면 선택 (더블클릭은 항상 편집)
        def _time_press(e, s=slot_idx):
            di = self._slot_data_idx(s)
            if (di >= 0 and di == getattr(self, "_selected_row_idx", None)
                    and len(getattr(self, "_selected_rows", set())) <= 1):
                self._ts_edit_start(s)
                return "break"
            _relay_press(e, s)

        for w in (time_frame, time_lbl, dur_lbl):
            w.bind("<Button-1>",        _time_press)
            w.bind("<Shift-Button-1>",  lambda e, s=slot_idx: self._slot_shift_click(s))
            w.bind("<B1-Motion>",       _relay_motion)
            w.bind("<ButtonRelease-1>", _relay_release)
            w.bind("<Button-3>",        lambda e, s=slot_idx: self._slot_right_click(s, e))
            w.bind("<Double-Button-1>", lambda e, s=slot_idx: self._ts_edit_start(s))

        def _ts_commit(s=slot_idx):
            wi2 = self._slot_widgets[s]
            # 편집을 시작한 시점에 고정해둔 자막 인덱스를 우선 사용.
            # (드래그/스크롤로 슬롯 매핑이 바뀌어도 항상 처음 편집하던
            #  자막에 저장되도록 하여, 다른 행에 잘못 저장/복제되는 문제 방지)
            di = wi2.get("_edit_di")
            if di is None or di < 0:
                di = self._slot_data[s] if s < len(self._slot_data) else -1
            if di < 0 or di >= len(self.subtitles):
                return
            sv = wi2["ts_s_var"].get().strip()
            ev = wi2["ts_e_var"].get().strip()
            se = wi2["ts_s"]
            ee = wi2["ts_e"]
            self._ts_style(se, sv); self._ts_style(ee, ev)
            if self._ts_valid(sv) and self._ts_valid(ev):
                new_ts = f"{sv} --> {ev}"
                if self.subtitles[di].get("timestamp", "") != new_ts:
                    self._push_undo()   # 실제로 바뀐 경우에만 undo 스냅샷 기록
                    self.subtitles[di]["timestamp"] = new_ts
                    self._unsaved = True
                    if hasattr(self, "_ts_cache") and di < len(self._ts_cache):
                        self._ts_cache[di] = (self._ts_to_sec(sv), self._ts_to_sec(ev))
            wi2["_edit_di"] = None

        def _ts_key(e, s=slot_idx):
            wi2 = self._slot_widgets[s]
            self._ts_style(wi2["ts_s"], wi2["ts_s_var"].get())
            self._ts_style(wi2["ts_e"], wi2["ts_e_var"].get())

        def _ts_focus_out(e, s=slot_idx, f=_ts_commit):
            f()
            # 시작↔종료 입력칸 사이 이동이 아니면 편집 종료 (포커스가 옮겨간 뒤 판단)
            self.after_idle(lambda: self._ts_edit_end_if_left(s))

        for ent in (ts_s, ts_e):
            ent.bind("<Return>",     lambda e: self.focus_set())   # 확정 → FocusOut에서 저장
            ent.bind("<FocusOut>",   _ts_focus_out)
            ent.bind("<KeyRelease>", _ts_key)
            ent.bind("<FocusIn>",    lambda e, s=slot_idx: self._slot_focus_in(s))

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
            return PopupMenu(self)

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
                    label=f"{spk}",
                    accelerator=str(i+1) if i < 9 else "",
                    foreground=self._speaker_color(spk),
                    activeforeground=self._speaker_color(spk),
                    command=lambda s=spk: self._ctx_set_speaker(s))
            menu.add_cascade(label=f"화자 변경{s}", menu=spk_menu)

        menu.tk_popup(event.x_root, event.y_root)

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
        self._refresh_speaker_counts()
        # 재생바(타임라인)의 자막 색상도 즉시 반영 — 그렇지 않으면 재생/이동
        # 등 다른 동작을 해야 뒤늦게 갱신되는 것처럼 보였다.
        self._wf_img_cache = None
        self._pb_redraw()

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
        # 드래그 도중 편집 중이던 Entry가 남아있으면 슬롯 재매핑 시 엉뚱한
        # 행에 저장될 수 있으므로, 드래그 시작 시 바로 포커스를 풀어 커밋한다.
        self._blur_all_entries()
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
        wi = self._slot_widgets[slot_idx]
        # 편집을 시작한 시점에 고정해둔 자막 인덱스를 우선 사용.
        # (드래그/스크롤로 슬롯 매핑이 바뀌어도 항상 처음 편집하던 자막에
        #  저장되도록 하여, 다른 행에 텍스트가 잘못 저장/복제되는 문제 방지)
        di = wi.get("_edit_di")
        if di is None or di < 0:
            di = self._slot_data_idx(slot_idx)
        if di < 0 or di >= len(self.subtitles):
            return
        val = wi["txt_var"].get()
        if self.subtitles[di].get("text", "") != val:
            self._push_undo()   # 실제로 바뀐 경우에만 undo 스냅샷 기록
            self.subtitles[di]["text"] = val
            self._unsaved = True
        wi["_edit_di"] = None

    def _slot_focus_in(self, slot_idx):
        di = self._slot_data_idx(slot_idx)
        if di < 0:
            return
        wi = self._slot_widgets[slot_idx]
        # 지금 이 슬롯이 가리키는 자막 인덱스를 편집 시작 시점 값으로 고정.
        wi["_edit_di"] = di

        # ⚠ 핵심 수정: 가상 스크롤 구조상 이 슬롯(화면 자리)은 방금 전까지
        # 전혀 다른 자막을 보여주고 있었을 수 있다. _fill_slots/_redraw_slot_for는
        # "지금 포커스된 Entry는 덮어쓰지 않는다"는 가드가 있는데, 이 FocusIn
        # 콜백이 실행되는 시점엔 이미 포커스가 이 Entry로 넘어와 있으므로 그
        # 가드에 걸려 새 자막의 실제 텍스트로 채워지지 않고 이전 자막의 텍스트가
        # 그대로 남아있게 된다. 그 상태로 편집/저장하면 엉뚱한 자막에 이전 자막의
        # 내용이 복제 저장되는 문제가 생긴다. 그래서 편집을 "시작하는" 이 시점에는
        # 가드를 우회하고 반드시 지금 자막의 실제 저장값으로 강제 갱신한다.
        sub = self.subtitles[di] if di < len(self.subtitles) else {}
        wi["txt_var"].set(sub.get("text", ""))
        ts_full = sub.get("timestamp", "")
        parts   = ts_full.split("-->")
        wi["ts_s_var"].set(parts[0].strip() if len(parts) >= 2 else ts_full.strip())
        wi["ts_e_var"].set(parts[1].strip() if len(parts) >= 2 else "")

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
        # ⚠ 가상 스크롤 재매핑(슬롯 ↔ 자막 인덱스)이 실제로 바뀌기 직전에
        # 무조건 먼저 편집 중인 입력창을 blur(커밋)한다. 이 함수가 호출된다는
        # 것 자체가 "화면에 보이는 슬롯-자막 매핑이 곧 바뀐다"는 뜻이므로,
        # 매핑을 바꾸기 전에 지금 활성화된 입력창의 내용을 그 슬롯이 아직
        # 가리키고 있는(올바른) 자막에 먼저 반영해 커밋하고 포커스를 없앤다.
        # 이렇게 하면 매핑이 바뀐 뒤에 커밋되어 엉뚱한 자막에 저장되는 문제와,
        # 편집 중이던 입력창에 이전/이후 자막의 내용이 잘못 표시되는 문제를
        # 근본적으로 막을 수 있다.
        self._blur_all_entries()

        n       = len(self.subtitles)
        h       = self.ROW_H
        n_slots = len(self._slot_frames)
        cw      = max(self.canvas.winfo_width(), 100)
        pos     = self._get_col_positions()

        for slot_idx in range(n_slots):
            di = first_idx + slot_idx

            wi     = self._slot_widgets[slot_idx]
            win_id = wi["_win_id"]

            # 참고: 이전엔 여기서 편집 중인(포커스된) Entry가 있는 슬롯 전체를
            # 통째로 건너뛰어(freeze) 재매핑을 막았었다. 하지만 그 방식은
            # 드래그/스크롤 중 편집 중이던 행이 화면에 '고정'되어 다른 행들과
            # 함께 움직이지 않는 것처럼 보이는 부작용이 있었다.
            # 지금은 위에서 _blur_all_entries()로 이 함수가 실제 매핑을 바꾸기
            # 전에 항상 먼저 커밋/포커스 해제를 하므로, 이 시점에는 이미 어떤
            # Entry도 포커스를 갖고 있지 않아 안전하게 매핑을 갱신할 수 있다.
            self._slot_data[slot_idx] = di if di < n else -1

            if di >= n:
                self.canvas.itemconfigure(win_id, state="hidden")
                continue

            y_screen = slot_idx * h
            self.canvas.itemconfigure(win_id, state="normal", width=cw)
            self.canvas.coords(win_id, 0, y_screen)
            self._paint_slot(slot_idx, di, pos, cw)

    def _slot_colors(self, di):
        """자막 상태별 카드 색: (카드 배경, 테두리 색, 테두리 두께)."""
        if di == getattr(self, "_selected_row_idx", None) or di in getattr(self, "_selected_rows", set()):
            return self._CARD_SEL_BG, ACCENT, 2
        if di in getattr(self, "_playing_rows", set()):
            return self.ROW_PLAYING, self._CARD_PLAY_BORDER, 1
        return self._CARD_BG, BORDER, 1

    @staticmethod
    def _fmt_card_time(sec):
        """카드에 표시할 시작 시각 (1시간 미만: 0:30.37, 이상: 1:02:03.45)."""
        h = int(sec // 3600)
        m = int(sec % 3600 // 60)
        s = sec % 60
        return f"{h}:{m:02d}:{s:05.2f}" if h else f"{m}:{s:05.2f}"

    def _paint_slot(self, slot_idx, di, pos, cw):
        """슬롯 하나를 자막 di의 내용·상태로 채우고 배치한다."""
        wi  = self._slot_widgets[slot_idx]
        sub = self.subtitles[di]
        bg, outline, width = self._slot_colors(di)
        row = self._slot_frames[slot_idx]
        row.itemconfigure("card", fill=bg, outline=outline, width=width)

        wi["num"].configure(text=str(di + 1), bg=bg)

        ts_full  = sub.get("timestamp", "")
        parts    = ts_full.split("-->")
        ts_start = parts[0].strip() if len(parts) >= 2 else ts_full.strip()
        ts_end   = parts[1].strip() if len(parts) >= 2 else ""
        # 편집 중(포커스 상태)인 타임스탬프 Entry는 덮어쓰지 않음 (안전장치)
        if self.focus_get() is not wi["ts_s"]:
            wi["ts_s_var"].set(ts_start)
        if self.focus_get() is not wi["ts_e"]:
            wi["ts_e_var"].set(ts_end)
        self._ts_style(wi["ts_s"], ts_start)
        self._ts_style(wi["ts_e"], ts_end)
        if self._ts_valid(ts_start) and self._ts_valid(ts_end):
            t_s, t_e = self._ts_to_sec(ts_start), self._ts_to_sec(ts_end)
            wi["time_lbl"].configure(text=self._fmt_card_time(t_s), fg="#B9A6EC", bg=bg)
            wi["dur_lbl"].configure(text=f"+{max(0.0, t_e - t_s):.2f}초", bg=bg)
        else:
            wi["time_lbl"].configure(text="시간 오류", fg="#FF6B8A", bg=bg)
            wi["dur_lbl"].configure(text="", bg=bg)
        wi["time"].configure(bg=bg)

        # 편집 중(포커스 상태)인 텍스트 Entry는 덮어쓰지 않음 (안전장치)
        txt_entry = wi["content"]
        if self.focus_get() is not txt_entry:
            wi["txt_var"].set(sub.get("text", ""))
        txt_entry.configure(bg=bg, highlightbackground=bg)
        wi["speaker"].configure(bg=bg)
        self._update_slot_pills(slot_idx, sub, bg)
        self._apply_col_to_slot(slot_idx, pos, cw)

    def _flush_deferred_pills(self, expected_top):
        """스크롤이 멈춘 뒤 호출 — 현재 뷰포트의 pill을 완성."""
        self._pill_defer_job = None
        if self._vscroll_top != expected_top:
            return   # 그 사이 또 스크롤됐으면 다음 flush에 맡김
        for slot_idx, di in enumerate(self._slot_data):
            if di < 0 or di >= len(self.subtitles):
                continue
            self._update_slot_pills(slot_idx, self.subtitles[di], self._slot_colors(di)[0])

    def _update_slot_bg(self, slot_idx, bg=None):
        """선택/재생 하이라이트만 다시 반영 (카드 색은 자막 상태로 결정)."""
        di = self._slot_data[slot_idx]
        if 0 <= di < len(self.subtitles):
            self._paint_slot(slot_idx, di, self._get_col_positions(),
                             max(self.canvas.winfo_width(), 100))

    # ── 시간 편집 (더블클릭) ─────────────────
    def _ts_edit_start(self, slot_idx):
        """시간 칸 더블클릭 → 시작/종료 타임스탬프 입력칸을 펼쳐 편집."""
        di = self._slot_data_idx(slot_idx)
        if di < 0:
            return
        wi = self._slot_widgets[slot_idx]
        wi["_ts_editing"] = True
        self._apply_col_to_slot(slot_idx, self._get_col_positions(),
                                max(self.canvas.winfo_width(), 100))
        wi["ts_s"].focus_set()
        wi["ts_s"].select_range(0, "end")
        wi["ts_s"].icursor("end")

    def _ts_edit_end_if_left(self, slot_idx):
        """포커스가 시작/종료 입력칸 밖으로 나갔으면 입력칸을 접고 시간 표시로 복귀."""
        wi = self._slot_widgets[slot_idx]
        if not wi.get("_ts_editing"):
            return
        try:
            focus = self.focus_get()
        except Exception:
            focus = None
        if focus in (wi["ts_s"], wi["ts_e"]):
            return
        wi["_ts_editing"] = False
        wi["ts_s"].place_forget()
        wi["ts_e"].place_forget()
        di = self._slot_data_idx(slot_idx)
        if 0 <= di < len(self.subtitles):
            self._paint_slot(slot_idx, di, self._get_col_positions(),
                             max(self.canvas.winfo_width(), 100))

    def _update_slot_pills(self, slot_idx, sub, bg):
        """pill Label들을 configure로만 갱신 — destroy/create 없음."""
        wi      = self._slot_widgets[slot_idx]
        pills   = wi["pills"]
        vals    = wi["pill_values"]
        current = sub.get("speaker", "")

        choices = [("", "(없음)")] + [(sp, sp) for sp in self.speakers]

        # 버튼 수가 바뀐 만큼만 끝에서 추가/숨김 (기존 버튼 순서 유지)
        n_show = min(len(choices), len(pills))
        prev = wi.get("_pill_n")
        if prev is None:            # 처음이거나 헤더 드래그로 모두 숨겼던 경우
            for lbl in pills:
                lbl.pack_forget()
            for lbl in pills[:n_show]:
                lbl.pack(side="left", padx=2)
        elif n_show > prev:
            for lbl in pills[prev:n_show]:
                lbl.pack(side="left", padx=2)
        elif n_show < prev:
            for lbl in pills[n_show:prev]:
                lbl.pack_forget()
        wi["_pill_n"] = n_show

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
                    font=(theme.FONT_FAMILY, 9, "bold" if is_sel else "normal"),
                    highlightbackground=color if is_sel else "#2A2A2A"
                )
                vals[pi] = val
            else:
                vals[pi] = ""   # 화자 수보다 많은 pill은 위에서 이미 숨김

    def _apply_col_to_slot(self, slot_idx, pos, cw):
        """단일 슬롯의 카드 테두리·구분선과 위젯 위치를 pos에 맞게 재배치."""
        wi  = self._slot_widgets[slot_idx]
        row = self._slot_frames[slot_idx]
        y0, y1 = self._CARD_Y, self.ROW_H - self._CARD_Y
        ch  = y1 - y0
        x0  = pos["num"][0]
        x1  = pos["speaker"][0] + pos["speaker"][1]
        r   = self._CARD_R
        row.coords("card", x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
                   x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0)
        for line, cid in zip(row.find_withtag("div"), ("time", "content", "speaker")):
            x = pos[cid][0]
            row.coords(line, x, y0 + 1, x, y1 - 1)
        try:
            nx, nw = pos["num"]
            wi["num"].place(x=nx + 1, y=y0 + 2, width=nw - 2, height=ch - 4)
            tx, tw = pos["time"]
            wi["time"].place(x=tx + 1, y=y0 + 2, width=tw - 2, height=ch - 4)
            cx, cw_ = pos["content"]
            wi["content"].place(x=cx + 6, y=y0 + 5, width=max(20, cw_ - 12), height=ch - 10)
            sx, sw = pos["speaker"]
            wi["speaker"].place(x=sx + 6, y=y0 + 2, width=max(20, sw - 12), height=ch - 4)
            if wi.get("_ts_editing"):
                ew = self._TS_EDIT_W
                wi["ts_s"].place(x=tx + 4, y=y0 + 5, width=ew, height=ch - 10)
                wi["ts_e"].place(x=tx + 8 + ew, y=y0 + 5, width=ew, height=ch - 10)
                wi["ts_s"].lift()
                wi["ts_e"].lift()
            else:
                wi["ts_s"].place_forget()
                wi["ts_e"].place_forget()
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
        # 카드 좌우 여백만 제외 (스크롤바 폭은 캔버스 밖)
        total = max(total - 2 * self._CARD_X, 200)
        fixed = sum(self._col_w[c] for c in self._COL_IDS)
        content_w = max(60, total - fixed)

        pos = {}
        x = self._CARD_X
        for cid in ["num", "time"]:
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
        for cid in ["time", "content", "speaker"]:
            x, w = pos[cid]
            dx = x + w
            c.create_line(dx, 3, dx, 25, fill=BORDER, width=2,
                          tags="div", activefill=ACCENT)

    def _hdr_divider_at(self, mx):
        pos = self._get_col_positions()
        for cid in ["time", "content", "speaker"]:
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
                # 드래그가 끝나고 다시 채울 때 버튼을 처음부터 다시 배치하도록
                self._slot_widgets[slot_idx]["_pill_n"] = None

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
        self._update_slot_pills(slot, self.subtitles[idx], self._slot_colors(idx)[0])

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
        self._paint_slot(slot, data_idx, self._get_col_positions(),
                         max(self.canvas.winfo_width(), 100))

    # ── 행 선택 / 하이라이트 ─────────────────
    def _on_global_click(self, event):
        clicked = event.widget
        # 클릭한 위젯이 어떤 Entry든 포커스 이동만 허용, 나머지는 blur
        if isinstance(clicked, tk.Entry):
            return
        self._blur_all_entries()

    def _blur_all_entries(self):
        """모든 슬롯의 Entry에서 포커스를 제거하고 selection을 즉시 지움.
        when=\"now\"로 즉시(동기) 처리해야, 바로 이어지는 드래그/스크롤이
        커밋이 끝나기 전에 진행되어 편집 중이던 행이 화면에 '고정'되어
        보이는 문제가 생기지 않는다."""
        cur = self.focus_get()
        if not isinstance(cur, tk.Entry):
            return
        # selection 즉시 제거
        try:
            cur.selection_clear()
        except Exception:
            pass
        # FocusOut을 즉시(동기) 발생시켜 변경사항을 그 자리에서 바로 저장
        try:
            cur.event_generate("<FocusOut>", when="now")
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
        self._selection_anchor = idx   # Shift+방향키 확장의 새 기준점
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
                           font=(theme.FONT_FAMILY, 9, "bold" if is_sel else "normal"),
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
        self._refresh_speaker_counts()
        # 재생바(타임라인)의 자막 색상도 즉시 반영
        self._wf_img_cache = None
        self._pb_redraw()

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
