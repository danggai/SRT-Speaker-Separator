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

    # 프리셋 색상: 열 = 톤(기본·밝게·차분), 행 = 색상(빨주노초청파보핑). 세로로 배치.
    PRESET_COLORS = [
        # 기본
        "#D63838", "#D67C38", "#D1AD36", "#38D65F",
        "#38D6C6", "#387AD6", "#8238D6", "#D63887",
        # 밝게
        "#F28D8D", "#F2B98D", "#F2DB8D", "#8DF2A6",
        "#8DF2E8", "#8DB7F2", "#BC8DF2", "#F28DBF",
        # 차분
        "#9E4C4C", "#9E704C", "#9E8B4C", "#4C9E60",
        "#4C9E96", "#4C6E9E", "#724C9E", "#9E4C75",
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
        win.attributes("-alpha", 0.0)   # 가운데로 옮기기 전까지 투명 (기본 위치에 잠깐 떴다 이동하는 것 방지)
        _apply_dark_titlebar(win)
        self._win = win
        win.title(self._title)
        win.resizable(False, False)
        win.configure(bg=BG2)
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
        _COLS = 3      # 그리드 열 수
        _ROWS = -(-len(self.PRESET_COLORS) // _COLS)
        for i, _hexcol in enumerate(self.PRESET_COLORS):
            c, r = divmod(i, _ROWS)   # 위에서 아래로 채운 뒤 다음 열
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
        ww, wh = win.winfo_reqwidth(), win.winfo_reqheight()
        win.geometry(f"+{pw - ww//2}+{ph - wh//2}")
        win.update_idletasks()
        win.attributes("-alpha", 1.0)
        win.grab_set()

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
_ACCEL_KEYS = {"Delete": "<Delete>", "Del": "<Delete>", "F2": "<F2>"}


class PopupMenu:
    """tk.Menu 대신 Toplevel로 만든 커스텀 팝업 메뉴.
    Windows 흰 테두리 문제 없이 완전한 다크 테마 적용 가능."""

    SEP = "__sep__"
    CASCADE = "__cascade__"
    _active = None   # 지금 떠 있는 메뉴 (항상 하나만)

    def __init__(self, root):
        self._root    = root
        self._items   = []   # (type, label, command, submenu, state, accel, fg)
        self._win     = None
        self._sub_win = None
        self._parent_menu = None

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

    def _show(self, x, y, parent_menu=None):
        self._destroy()
        self._parent_menu = parent_menu
        if parent_menu is None:   # 하위 메뉴가 아닐 때만 이전 메뉴를 바로 닫음 (겹침 방지)
            prev = PopupMenu._active
            if prev is not None and prev is not self:
                prev._destroy()
            PopupMenu._active = self
        win = tk.Toplevel(self._root)
        win.attributes("-alpha", 0.0)   # 제자리로 옮기기 전까지 투명
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=BG3)
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
        win.update_idletasks()
        win.attributes("-alpha", 0.97)

        win.bind("<Escape>", lambda e: self._destroy())

        # 포커스 잃으면 닫기 — 서브메뉴 포함 전체 영역 기준
        def _on_focus_out(e):
            def _check():
                try:
                    # 마우스가 메뉴(하위 메뉴 포함) 위에 있으면 닫지 않음
                    px, py = self._root.winfo_pointerxy()
                    under = self._root.winfo_containing(px, py)
                    for w in [self._win, self._sub_win]:
                        if under is not None and w and w.winfo_exists() \
                                and str(under).startswith(str(w)):
                            return
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
                    top = self
                    while getattr(top, "_parent_menu", None) is not None:
                        top = top._parent_menu
                    self._destroy()
                    top._destroy()   # 하위 메뉴에서 골라도 부모 메뉴까지 닫음
                    self._root.after(10, c)  # destroy 완료 후 실행
                row.bind("<Button-1>", _click)
                lbl.bind("<Button-1>", _click)
                key = _ACCEL_KEYS.get(accel)
                if key:   # 메뉴가 떠 있을 때 표시된 단축키로 실행
                    win.bind(key, _click)

            elif kind == "cascade" and submenu:
                def _hover_cascade(e, r=row, sub=submenu):
                    if self._sub_win is not None and self._sub_win is sub._win:
                        try:
                            if self._sub_win.winfo_exists():
                                return   # 이미 열린 하위 메뉴는 다시 만들지 않음
                        except Exception:
                            pass
                    rx = r.winfo_rootx() + r.winfo_width()
                    ry = r.winfo_rooty()
                    if self._sub_win:
                        try: self._sub_win.destroy()
                        except Exception: pass
                        self._sub_win = None
                    sub._show(rx, ry, parent_menu=self)
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
    """진행바 그라데이션 이미지 데이터 (PhotoImage.put 형식)."""
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


def show_toast(root, text, duration_ms=1600):
    """창 위쪽 가운데에 잠깐 떴다 사라지는 알림."""
    old = getattr(root, "_toast_win", None)
    if old is not None:
        try:
            old.destroy()
        except tk.TclError:
            pass
    win = tk.Toplevel(root)
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    try:
        win.attributes("-alpha", 0.0)
    except tk.TclError:
        pass
    box = tk.Frame(win, bg="#2A2A33", highlightthickness=1, highlightbackground=ACCENT)
    box.pack()
    tk.Label(box, text="✓", bg="#2A2A33", fg="#7FD48F",
             font=(theme.FONT_FAMILY, 11, "bold")).pack(side="left", padx=(14, 6), pady=8)
    tk.Label(box, text=text, bg="#2A2A33", fg=FG,
             font=(theme.FONT_FAMILY, 10)).pack(side="left", padx=(0, 16), pady=8)
    win.update_idletasks()
    x = root.winfo_rootx() + (root.winfo_width() - win.winfo_reqwidth()) // 2
    y = root.winfo_rooty() + 86   # 상단 툴바 바로 아래
    win.geometry(f"+{x}+{y}")
    root._toast_win = win

    def fade(alpha, step, then=None):
        try:
            if not win.winfo_exists():
                return
            win.attributes("-alpha", max(0.0, min(0.95, alpha)))
            if (step > 0 and alpha < 0.95) or (step < 0 and alpha > 0):
                win.after(20, lambda: fade(alpha + step, step, then))
            elif then:
                then()
        except tk.TclError:
            pass

    def close():
        try:
            win.destroy()
        except tk.TclError:
            pass
        if getattr(root, "_toast_win", None) is win:
            root._toast_win = None

    fade(0.0, 0.16, lambda: win.after(duration_ms, lambda: fade(0.95, -0.1, close)))
    return win


_IMG_CACHE = {}
_SS = 4   # 안티앨리어싱용 확대 배율


def _hex_rgba(color):
    from PIL import ImageColor
    return ImageColor.getrgb(color)[:3] + (255,)


def rounded_rect_image(w, h, r, fill, outline=None, width=1):
    """안티앨리어싱된 둥근 사각형 이미지 (캐시)."""
    from PIL import Image, ImageDraw, ImageTk
    key = ("rr", w, h, r, fill, outline, width)
    if key not in _IMG_CACHE:
        im = Image.new("RGBA", (w * _SS, h * _SS), (0, 0, 0, 0))
        ImageDraw.Draw(im).rounded_rectangle(
            [0, 0, w * _SS - 1, h * _SS - 1], radius=r * _SS, fill=_hex_rgba(fill),
            outline=_hex_rgba(outline) if outline else None,
            width=width * _SS if outline else 0)
        _IMG_CACHE[key] = ImageTk.PhotoImage(im.resize((w, h), Image.LANCZOS))
    return _IMG_CACHE[key]


def _icon_image(kind, size, fg, circle=None, hover_bg=None):
    """도형 아이콘 이미지 (원형 바탕·마우스 오버 바탕 포함, 안티앨리어싱, 캐시)."""
    from PIL import Image, ImageDraw, ImageTk
    key = ("icon", kind, size, fg, circle, hover_bg)
    if key in _IMG_CACHE:
        return _IMG_CACHE[key]
    S = size * _SS
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if circle:
        d.ellipse([0, 0, S - 1, S - 1], fill=_hex_rgba(circle))
    elif hover_bg:
        d.rounded_rectangle([0, 0, S - 1, S - 1], radius=theme.ON_RADIUS * _SS,
                            fill=_hex_rgba(hover_bg))
    f = _hex_rgba(fg)
    c, u = S / 2, S / 26   # 26px 기준 배율

    def tri(x, y, w, h, right=True):
        pts = [(x, y - h / 2), (x + w, y), (x, y + h / 2)] if right else \
              [(x + w, y - h / 2), (x, y), (x + w, y + h / 2)]
        d.polygon(pts, fill=f)

    if kind == "play":
        tri(c - 3.5 * u, c, 9 * u, 11 * u)
    elif kind == "pause":
        for x in (c - 4 * u, c + 1.5 * u):
            d.rounded_rectangle([x, c - 5 * u, x + 2.5 * u, c + 5 * u], radius=0.6 * u, fill=f)
    elif kind == "back":
        tri(c - 6 * u, c, 6 * u, 9 * u, right=False)
        tri(c, c, 6 * u, 9 * u, right=False)
    elif kind == "fwd":
        tri(c - 6 * u, c, 6 * u, 9 * u)
        tri(c, c, 6 * u, 9 * u)
    elif kind == "start":
        d.rectangle([c - 6 * u, c - 4.5 * u, c - 4 * u, c + 4.5 * u], fill=f)
        tri(c - 4 * u, c, 9 * u, 9 * u, right=False)
    elif kind.startswith("vol"):
        d.polygon([(c - 7 * u, c - 2.5 * u), (c - 4 * u, c - 2.5 * u), (c, c - 6 * u),
                   (c, c + 6 * u), (c - 4 * u, c + 2.5 * u), (c - 7 * u, c + 2.5 * u)], fill=f)
        lw = max(1, int(1.6 * u))
        if kind == "vol0":
            for dd in (1, -1):
                d.line([(c + 2.5 * u, c - 3 * u * dd), (c + 7.5 * u, c + 3 * u * dd)],
                       fill=f, width=lw)
        else:
            for rad in ((4,) if kind == "vol1" else (4, 7.5)):
                d.arc([c - rad * u, c - rad * u, c + rad * u, c + rad * u],
                      start=-45, end=45, fill=f, width=lw)
    photo = ImageTk.PhotoImage(im.resize((size, size), Image.LANCZOS))
    _IMG_CACHE[key] = photo
    return photo


class FlatButton(tk.Canvas):
    """둥근 모서리의 평평한 버튼 (안티앨리어싱, 글자를 바꾸면 크기도 맞춰짐)."""

    def __init__(self, parent, text, command, bg, fg=FG, hover=BG3, font=None,
                 padx=10, pady=3):
        try:
            outer = parent.cget("bg")   # 모서리 바깥은 부모 배경과 같게
        except tk.TclError:
            outer = bg
        super().__init__(parent, bg=outer, highlightthickness=0, cursor="hand2")
        import tkinter.font as tkfont
        self._font = tkfont.Font(self, font=font or (theme.FONT_FAMILY, 9))
        self._padx, self._pady, self._bg, self._hover = padx, pady, bg, hover
        self._outer, self._hovering = outer, False
        self.create_image(0, 0, anchor="nw", tags="box")
        self.create_text(0, 0, text=text, fill=fg, font=self._font, tags="label")
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        # 버튼 위에서 뗐을 때만 실행
        self.bind("<ButtonRelease-1>", lambda e: command()
                  if 0 <= e.x < self.winfo_width() and 0 <= e.y < self.winfo_height() else None)
        self._relayout()

    def _set_hover(self, on):
        self._hovering = on
        self._paint_box()

    def _paint_box(self):
        fill = self._hover if self._hovering else self._bg
        if fill == self._outer:
            self.itemconfigure("box", image="")
            return
        w, h = self._wh
        self.itemconfigure("box", image=rounded_rect_image(w, h, min(theme.ON_RADIUS, h // 2), fill))

    def _relayout(self):
        w = self._font.measure(self.itemcget("label", "text")) + 2 * self._padx
        h = self._font.metrics("linespace") + 2 * self._pady
        self._wh = (w, h)
        tk.Canvas.configure(self, width=w, height=h)
        self.coords("label", w / 2, h / 2)
        self._paint_box()

    def configure(self, cnf=None, **kw):
        if "text" in kw:
            self.itemconfigure("label", text=kw.pop("text"))
            self._relayout()
        if cnf or kw:
            return tk.Canvas.configure(self, cnf, **kw)

    config = configure


class IconButton(tk.Canvas):
    """이모지 대신 도형을 그리는 아이콘 버튼 (안티앨리어싱, Windows에서도 모양이 일정함).
    configure(text="▶"/"⏸"/"🔇"/"🔉"/"🔊")로 아이콘을 바꿀 수 있다."""

    _TEXT_KIND = {"▶": "play", "⏸": "pause", "🔇": "vol0", "🔉": "vol1", "🔊": "vol2"}

    def __init__(self, parent, kind, command=None, size=26, fg=FG, hover=BG3,
                 circle=None, circle_hover=None):
        try:
            outer = parent.cget("bg")
        except tk.TclError:
            outer = BG
        super().__init__(parent, width=size, height=size, bg=outer,
                         highlightthickness=0, cursor="hand2")
        self._size, self._fg, self._kind, self._hovering = size, fg, kind, False
        self._circle, self._circle_hover = circle, circle_hover or circle
        self._hover = hover
        self.create_image(size / 2, size / 2, tags="img")
        self._draw()
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        if command:
            self.bind("<ButtonRelease-1>", lambda e: command()
                      if 0 <= e.x < self.winfo_width() and 0 <= e.y < self.winfo_height() else None)

    def _set_hover(self, on):
        self._hovering = on
        self._draw()

    def _draw(self):
        h = self._hovering
        circle = (self._circle_hover if h else self._circle) if self._circle else None
        img = _icon_image(self._kind, self._size, self._fg, circle=circle,
                          hover_bg=self._hover if (h and not self._circle) else None)
        self.itemconfigure("img", image=img)

    def configure(self, cnf=None, **kw):
        if "text" in kw:
            kind = self._TEXT_KIND.get(kw.pop("text"))
            if kind and kind != self._kind:
                self._kind = kind
                self._draw()
        if cnf or kw:
            return tk.Canvas.configure(self, cnf, **kw)

    config = configure


def flat_button(parent, text, command, bg, fg=FG, hover=BG3, font=None, padx=10, pady=3):
    """테두리 없는 평평한 버튼 (마우스를 올리면 배경만 바뀜)."""
    return FlatButton(parent, text, command, bg, fg=fg, hover=hover, font=font,
                      padx=padx, pady=pady)


def _circle_image(d, color):
    """안티앨리어싱된 원 이미지 (캐시)."""
    from PIL import Image, ImageDraw, ImageTk
    key = ("circle", d, color)
    if key not in _IMG_CACHE:
        im = Image.new("RGBA", (d * _SS, d * _SS), (0, 0, 0, 0))
        ImageDraw.Draw(im).ellipse([0, 0, d * _SS - 1, d * _SS - 1], fill=_hex_rgba(color))
        _IMG_CACHE[key] = ImageTk.PhotoImage(im.resize((d, d), Image.LANCZOS))
    return _IMG_CACHE[key]


def _mix(c1, c2, t):
    """두 색의 중간색 (t=0 → c1, t=1 → c2)."""
    a, b = _hex_rgba(c1), _hex_rgba(c2)
    return "#%02X%02X%02X" % tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


_ANIM_STEPS = 7    # 전환 애니메이션 단계 수
_ANIM_MS = 16      # 단계 간격 (ms)


def _ease(t):
    return 1 - (1 - t) ** 3   # 끝에서 부드럽게 멈춤


class ToggleSwitch(tk.Canvas):
    """켜기/끄기 스위치 (BooleanVar 연동, 미끄러지는 애니메이션)."""

    W, H = 40, 22
    _OFF = "#3A3A44"

    def __init__(self, parent, variable, command=None):
        super().__init__(parent, width=self.W, height=self.H, bg=parent.cget("bg"),
                         highlightthickness=0, cursor="hand2")
        self._var, self._cmd = variable, command
        self._pos = 1.0 if variable.get() else 0.0   # 0=꺼짐, 1=켜짐
        self._job = None
        self.create_image(0, 0, anchor="nw", tags="track")
        self.create_image(0, 0, anchor="center", tags="knob")
        self.bind("<Button-1>", self._toggle)
        variable.trace_add("write", lambda *_: self._animate())
        self._draw()

    def _toggle(self, e=None):
        self._var.set(not self._var.get())
        if self._cmd:
            self._cmd()

    def _animate(self):
        if self._job:
            self.after_cancel(self._job)
        start, target = self._pos, 1.0 if self._var.get() else 0.0

        def step(i=1):
            self._pos = start + (target - start) * _ease(i / _ANIM_STEPS)
            self._draw()
            self._job = self.after(_ANIM_MS, step, i + 1) if i < _ANIM_STEPS else None
        step()

    def _draw(self):
        t = self._pos
        self.itemconfigure("track", image=rounded_rect_image(
            self.W, self.H, self.H // 2, _mix(self._OFF, ACCENT, t)))
        k = self.H - 6
        x0, x1 = 3 + k / 2, self.W - 3 - k / 2
        self.coords("knob", x0 + (x1 - x0) * t, self.H / 2)
        self.itemconfigure("knob", image=_circle_image(k, "#FFFFFF"))


class Segmented(tk.Frame):
    """여러 값 중 하나를 고르는 버튼 묶음 (StringVar 연동, 색이 서서히 바뀜)."""

    def __init__(self, parent, options, variable, command=None):
        super().__init__(parent, bg=parent.cget("bg"))
        self._var, self._cmd, self._btns = variable, command, []
        import tkinter.font as tkfont
        font = tkfont.Font(self, family=theme.FONT_FAMILY, size=9)
        for label, value in options:
            w, h = font.measure(label) + 24, font.metrics("linespace") + 12
            cv = tk.Canvas(self, width=w, height=h, bg=self.cget("bg"),
                           highlightthickness=0, cursor="hand2")
            cv.pack(side="left", padx=(0, 4))
            cv.create_image(0, 0, anchor="nw", tags="bg")
            cv.create_text(w / 2, h / 2, text=label, font=font, tags="label")
            cv.bind("<Button-1>", lambda e, v=value: self._select(v))
            cv.sel = 1.0 if value == variable.get() else 0.0   # 선택 정도 (애니메이션용)
            self._btns.append((cv, value, w, h))
        self._job = None
        variable.trace_add("write", lambda *_: self._animate())
        self._draw()

    def _select(self, value):
        self._var.set(value)
        if self._cmd:
            self._cmd()

    def _animate(self):
        if self._job:
            self.after_cancel(self._job)
        cur = self._var.get()
        starts = [(cv, cv.sel, 1.0 if v == cur else 0.0) for cv, v, _, _ in self._btns]

        def step(i=1):
            for cv, a, b in starts:
                cv.sel = a + (b - a) * _ease(i / _ANIM_STEPS)
            self._draw()
            self._job = self.after(_ANIM_MS, step, i + 1) if i < _ANIM_STEPS else None
        step()

    def _draw(self):
        for cv, value, w, h in self._btns:
            t = round(cv.sel, 2)
            fill = _mix(BG3, theme.ON_BG, t)
            outline = _mix(BG3, theme.ON_BORDER, t) if t > 0 else None
            cv.itemconfigure("bg", image=rounded_rect_image(w, h, theme.ON_RADIUS, fill, outline))
            cv.itemconfigure("label", fill=_mix(FG_DIM, theme.ON_FG, t))
