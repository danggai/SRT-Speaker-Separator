"""공용 커스텀 위젯 (툴팁, 슬라이더, 색상 선택, 팝업 메뉴)."""
import colorsys
import tkinter as tk

from . import theme
from .theme import ACCENT, BG, BG2, BG3, BORDER, FG, FG_DIM, FONT_MONO, _apply_dark_titlebar


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
                 font=(theme.FONT_FAMILY, 9),
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
#  커스텀 슬라이더 (음량 조절 바와 동일한 디자인)
# ─────────────────────────────────────────────
class PurpleSlider(tk.Canvas):
    """음량 조절 슬라이더와 같은 스타일의 커스텀 Canvas 슬라이더.
    ttk.Scale의 기본(회색 촌스러운) 디자인 대신 사용."""

    def __init__(self, parent, from_=0, to=100, value=None,
                 width=200, height=18, command=None,
                 bg=BG, track_color="#2A2A2A", fill_color="#7A5FB0",
                 handle_color="white", handle_outline="#555555", **kwargs):
        super().__init__(parent, width=width, height=height, bg=bg,
                          highlightthickness=0, cursor="hand2", **kwargs)
        self.from_        = from_
        self.to           = to
        self._value       = value if value is not None else from_
        self._command     = command
        self._track_color = track_color
        self._fill_color  = fill_color
        self._handle_color   = handle_color
        self._handle_outline = handle_outline
        self._dragging = False

        self.bind("<ButtonPress-1>",   self._on_press)
        self.bind("<B1-Motion>",       self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Configure>",       self._redraw)
        self.after(10, self._redraw)

    def get(self):
        return self._value

    def set(self, v, fire=True):
        v = max(self.from_, min(self.to, v))
        self._value = v
        self._redraw()
        if fire and self._command:
            self._command(v)

    def _value_from_x(self, x):
        cw = self.winfo_width()
        if cw <= 1:
            return self._value
        ratio = max(0.0, min(1.0, x / cw))
        return self.from_ + ratio * (self.to - self.from_)

    def _redraw(self, event=None):
        cw = self.winfo_width()
        ch = self.winfo_height()
        if cw <= 1:
            self.after(50, self._redraw)
            return
        self.delete("all")
        span  = self.to - self.from_
        ratio = (self._value - self.from_) / span if span else 0
        filled = int(cw * ratio)
        track_y = ch // 2

        # 트랙 배경
        self.create_rectangle(0, track_y - 4, cw, track_y + 4,
                               fill=self._track_color, outline="", tags="track")
        # 채워진 부분
        if filled > 0:
            self.create_rectangle(0, track_y - 4, filled, track_y + 4,
                                   fill=self._fill_color, outline="", tags="fill")
        # 핸들
        hx = max(6, min(filled, cw - 6))
        self.create_oval(hx - 6, track_y - 6, hx + 6, track_y + 6,
                          fill=self._handle_color, outline=self._handle_outline,
                          width=1, tags="handle")

    def _on_press(self, event):
        self._dragging = True
        self.set(round(self._value_from_x(event.x)))

    def _on_drag(self, event):
        if not self._dragging:
            return
        self.set(round(self._value_from_x(event.x)))

    def _on_release(self, event):
        self._dragging = False
        self.set(round(self._value_from_x(event.x)))


# ─────────────────────────────────────────────
#  커스텀 컬러피커
# ─────────────────────────────────────────────
class _ColorPickerDialog:
    """HSV 팔레트 + 밝기 슬라이더 + Hex 입력으로 구성된 커스텀 컬러피커."""

    SZ   = 200   # 팔레트 크기
    BH   = 20    # 밝기 슬라이더 높이

    # 프리셋 색상 — 채도를 낮춘 무지개(빨주노초파남보) + 추가 색상, 총 16개.
    # 파스텔보다는 진하고 원색보다는 연한 톤. 어두운 UI 배경 위에서도
    # 서로 잘 구분되도록 색상마다 채도/명도를 개별 보정했다.
    PRESET_COLORS = [
        "#D24B4B",  # 빨강
        "#DA944E",  # 주황
        "#D8BF5A",  # 노랑
        "#99CD51",  # 연두
        "#40BF60",  # 초록
        "#37BEA7",  # 청록
        "#51A3CD",  # 하늘
        "#597CCF",  # 파랑
        "#6D5EC9",  # 남색
        "#905EC9",  # 보라
        "#BC59C5",  # 자주
        "#D36995",  # 핑크
        "#DA7E6C",  # 코랄
        "#945E38",  # 갈색
        "#88813A",  # 올리브
        "#6282A7",  # 슬레이트
    ]

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
        _apply_dark_titlebar(win)
        self._win = win
        win.title(self._title)
        win.resizable(False, False)
        win.configure(bg=BG2)
        win.grab_set()
        win.transient(self._parent)

        pad_outer = tk.Frame(win, bg=BG2)
        pad_outer.pack()

        pad = tk.Frame(pad_outer, bg=BG2)
        pad.pack(side="left", padx=16, pady=14)

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
                 font=(theme.FONT_FAMILY, 11, "bold")).pack(side="left")
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
                  font=(theme.FONT_FAMILY, 10, "bold"), padx=18, pady=6,
                  cursor="hand2", activebackground="#7B5FB4",
                  command=self._ok).pack(side="right", padx=(6, 0))
        tk.Button(btn_row, text="취소",
                  bg=BG3, fg=FG_DIM, relief="flat", bd=0,
                  font=(theme.FONT_FAMILY, 10), padx=14, pady=6,
                  cursor="hand2", activebackground=BORDER,
                  command=win.destroy).pack(side="right")

        # ── 프리셋 색상 (오른쪽) ──────────────────
        preset_col = tk.Frame(pad_outer, bg=BG2)
        preset_col.pack(side="left", padx=(0, 16), pady=14, fill="y")
        tk.Label(preset_col, text="프리셋", bg=BG2, fg=FG_DIM,
                 font=(theme.FONT_FAMILY, 9, "bold")).pack(anchor="w", pady=(0, 6))
        preset_grid = tk.Frame(preset_col, bg=BG2)
        preset_grid.pack()
        _SW = 22       # 스와치 한 변 크기(px)
        _COLS = 2      # 그리드 열 수
        for i, _hexcol in enumerate(self.PRESET_COLORS):
            r, c = divmod(i, _COLS)
            sw = tk.Canvas(preset_grid, width=_SW, height=_SW,
                          highlightthickness=1, highlightbackground=BORDER,
                          cursor="hand2", bg=_hexcol)
            sw.grid(row=r, column=c, padx=3, pady=3)
            sw.bind("<Button-1>", lambda e, hc=_hexcol: self._pick_preset(hc))
            Tooltip(sw, _hexcol, delay=300)

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

    def _pick_preset(self, hexcol):
        """프리셋 스와치 클릭 — 그 색상으로 팔레트/슬라이더/미리보기/Hex 갱신."""
        val = hexcol.lstrip("#")
        r = int(val[0:2], 16)
        g = int(val[2:4], 16)
        b = int(val[4:6], 16)
        self._h, self._s, self._v = self._rgb2hsv(r, g, b)
        self._draw_palette()
        self._refresh()

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
#  메인 앱
# ─────────────────────────────────────────────

# ── 커스텀 팝업 메뉴 (OS 테두리 없는 다크 테마) ─────────────────────────
class PopupMenu:
    """tk.Menu 대신 Toplevel로 만든 커스텀 팝업 메뉴.
    Windows 흰 테두리 문제 없이 완전한 다크 테마 적용 가능."""

    SEP = "__sep__"
    CASCADE = "__cascade__"

    def __init__(self, root):
        self._root    = root
        self._items   = []   # (type, label, command, submenu, state, accel, fg)
        self._win     = None
        self._sub_win = None

    def add_command(self, label="", command=None, state="normal",
                    accelerator="", foreground=None, activeforeground=None):
        self._items.append(("cmd", label, command, None, state,
                             accelerator, foreground))

    def add_separator(self):
        self._items.append(("sep", "", None, None, "normal", "", None))

    def add_cascade(self, label="", menu=None, state="normal"):
        self._items.append(("cascade", label, None, menu, state, "", None))

    def post(self, x, y):
        self._show(x, y)

    def tk_popup(self, x, y):
        self._show(x, y)

    def _show(self, x, y):
        self._destroy()
        win = tk.Toplevel(self._root)
        _apply_dark_titlebar(win)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=BG3)
        win.attributes("-alpha", 0.97)
        self._win = win

        frame = tk.Frame(win, bg=BG3,
                         highlightthickness=1,
                         highlightbackground=BORDER)
        frame.pack(fill="both", expand=True, padx=0, pady=0)
        frame.configure(width=220)  # 최소 너비

        self._build_items(frame, win)

        win.update_idletasks()
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        ww = win.winfo_reqwidth()
        wh = win.winfo_reqheight()
        if x + ww > sw:
            x = sw - ww - 4
        if y + wh > sh:
            y = y - wh
        win.geometry(f"+{x}+{y}")

        win.bind("<Escape>", lambda e: self._destroy())

        # 포커스 잃으면 닫기 — 서브메뉴 포함 전체 영역 기준
        def _on_focus_out(e):
            def _check():
                try:
                    focused = self._root.focus_get()
                    for w in [self._win, self._sub_win]:
                        if w and w.winfo_exists():
                            try:
                                if str(focused).startswith(str(w)):
                                    return
                            except Exception:
                                pass
                    self._destroy()
                except Exception:
                    self._destroy()
            win.after(100, _check)
        self._focus_out_handler = _on_focus_out  # _build_items에서 접근용
        win.bind("<FocusOut>", _on_focus_out)
        win.focus_set()

    def _build_items(self, parent, win):
        for kind, label, cmd, submenu, state, accel, fg in self._items:
            if kind == "sep":
                tk.Frame(parent, bg=BORDER, height=1).pack(
                    fill="x", padx=8, pady=2)
                continue

            disabled = (state == "disabled")
            row_fg   = fg if (fg and not disabled) else (FG_DIM if disabled else FG)

            row = tk.Frame(parent, bg=BG3, cursor="arrow")
            row.pack(fill="x", padx=0, pady=0)

            # 라벨
            lbl = tk.Label(row, text=f"  {label}",
                           bg=BG3, fg=row_fg,
                           font=(theme.FONT_FAMILY, 9),
                           anchor="w", padx=4, pady=5)
            lbl.pack(side="left", fill="x", expand=True)

            # 단축키
            if accel:
                tk.Label(row, text=f"{accel}  ",
                         bg=BG3, fg=FG_DIM,
                         font=(theme.FONT_FAMILY, 8),
                         anchor="e", padx=4).pack(side="right")

            # 서브메뉴 화살표
            if kind == "cascade":
                tk.Label(row, text="›",
                         bg=BG3, fg=FG_DIM,
                         font=(theme.FONT_FAMILY, 10),
                         padx=4).pack(side="right")

            if disabled:
                continue

            # 자식 위젯별 원래 색상 기억
            _orig_colors = {w: w.cget("fg") for w in row.winfo_children()}

            def _enter(e, r=row):
                r.configure(bg=ACCENT)
                for w in r.winfo_children():
                    try: w.configure(bg=ACCENT, fg="white")
                    except Exception: pass

            def _leave(e, r=row, orig=_orig_colors):
                r.configure(bg=BG3)
                for w in r.winfo_children():
                    try:
                        w.configure(bg=BG3, fg=orig.get(w, FG))
                    except Exception:
                        pass

            row.bind("<Enter>", _enter)
            lbl.bind("<Enter>", _enter)
            row.bind("<Leave>", _leave)
            lbl.bind("<Leave>", _leave)

            if kind == "cmd" and cmd:
                def _click(e, c=cmd):
                    self._destroy()
                    self._root.after(10, c)  # destroy 완료 후 실행
                row.bind("<Button-1>", _click)
                lbl.bind("<Button-1>", _click)

            elif kind == "cascade" and submenu:
                def _hover_cascade(e, r=row, sub=submenu):
                    rx = r.winfo_rootx() + r.winfo_width()
                    ry = r.winfo_rooty()
                    if self._sub_win:
                        try: self._sub_win.destroy()
                        except Exception: pass
                        self._sub_win = None
                    sub._show(rx, ry)
                    self._sub_win = sub._win
                    # 서브메뉴 FocusOut도 부모 기준으로 처리
                    if sub._win:
                        handler = getattr(self, '_focus_out_handler', None)
                        if handler:
                            sub._win.bind("<FocusOut>", handler)
                def _enter_cascade(e, fn=_enter):
                    fn(e)
                    _hover_cascade(e)
                row.bind("<Enter>", _enter_cascade)
                lbl.bind("<Enter>", _enter_cascade)

    def _destroy(self):
        if self._sub_win:
            try: self._sub_win.destroy()
            except Exception: pass
            self._sub_win = None
        if self._win:
            try: self._win.destroy()
            except Exception: pass
            self._win = None


def _gradient_bar_rows(width, height, fill_w, phase, bg_color):
    """진행 창의 그라데이션 웨이브 진행바 이미지를 PhotoImage.put() 형식으로 만든다.
    채워진 부분은 보라→파랑→초록 그라데이션에 물결(phase)과 끝부분 광택을 더하고,
    나머지는 bg_color로 채운다."""
    import math
    bg = "#{:02x}{:02x}{:02x}".format(int(bg_color[1:3], 16), int(bg_color[3:5], 16),
                                      int(bg_color[5:7], 16))
    row = []
    for x in range(width):
        if x < fill_w:
            t = x / width
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
            wave = math.sin(phase - x * 0.045) * 0.20 + 0.85
            glow = math.exp(-(fill_w - x) * 0.10) * 0.35
            bri = min(1.15, wave + glow)
            row.append("#{:02x}{:02x}{:02x}".format(
                min(255, int(r0 * bri)), min(255, int(g0 * bri)), min(255, int(b0 * bri))))
        else:
            row.append(bg)
    row_str = "{" + " ".join(row) + "}"
    return " ".join([row_str] * height)
