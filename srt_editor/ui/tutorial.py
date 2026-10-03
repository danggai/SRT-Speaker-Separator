"""첫 실행 튜토리얼 (예제 자막 + 단계별 스포트라이트 안내)."""
import os
import tempfile
import tkinter as tk

from .. import theme
from ..config import _load_config, _save_config
from ..theme import ACCENT, BG, BG2, BG3, BORDER, FG, FG_DIM, _apply_dark_titlebar

_EXAMPLE_SRT = """1
00:00:01,000 --> 00:00:03,000
[민지] 오늘 회의 시작할게요.

2
00:00:03,500 --> 00:00:05,500
[준호] 네, 자료 띄워 놓을게요.

3
00:00:06,000 --> 00:00:08,500
먼저 지난주 결과부터 볼까요?

4
00:00:09,000 --> 00:00:11,000
방문자가 20% 늘었어요.

5
00:00:11,500 --> 00:00:13,500
생각보다 많이 늘었네요.

6
00:00:14,000 --> 00:00:16,000
이벤트 효과가 컸던 것 같아요.

7
00:00:16,500 --> 00:00:18,500
다음 달에도 한 번 더 하죠.

8
00:00:19,000 --> 00:00:21,000
좋아요, 일정 잡아 볼게요.

9
00:00:21,500 --> 00:00:23,500
그럼 오늘은 여기까지 할까요?

10
00:00:24,000 --> 00:00:26,000
네, 수고하셨습니다.
"""

_DIM_COLOR   = "#000000"
_DIM_ALPHA   = 0.6
_RING_W      = 3
_RING_COLORS = (ACCENT, "#C9B6F2")   # 깜빡임 두 색
_OK_COLOR    = "#6FCF97"
_PAD         = 4                     # 강조 영역 여백


class TutorialMixin:
    """첫 실행 튜토리얼."""

    # ── 진입 ──────────────────────────────
    def _tutorial_maybe_ask(self):
        """처음 실행이면 튜토리얼 진행 여부를 묻는다."""
        if _load_config().get("tutorial_seen") or self.subtitles:
            return
        self._tutorial_ask()

    def _tutorial_ask(self):
        cfg = _load_config()
        cfg["tutorial_seen"] = True
        _save_config(cfg)

        win = tk.Toplevel(self)
        win.withdraw()   # 위치·제목표시줄 적용 전 흰 창이 보이지 않게
        win.title("시작하기")
        win.configure(bg=BG)
        win.resizable(False, False)
        win.transient(self)

        tk.Label(win, text="처음 사용하시나요?", bg=BG, fg=FG,
                 font=(theme.FONT_FAMILY, 14, "bold")).pack(padx=40, pady=(28, 8))
        tk.Label(win, text="예제 자막으로 1분 정도 기본 사용법을 안내해 드릴게요.",
                 bg=BG, fg=FG_DIM, font=(theme.FONT_FAMILY, 10)).pack(padx=40)

        row = tk.Frame(win, bg=BG)
        row.pack(pady=(24, 24))

        def _start():
            win.destroy()
            self._tutorial_start()

        _button(row, "건너뛰기", win.destroy, primary=False).pack(side="left", padx=6)
        _button(row, "튜토리얼 시작", _start).pack(side="left", padx=6)

        win.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - win.winfo_width()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - win.winfo_height()) // 3
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
        try:
            win.attributes("-alpha", 0.0)
        except tk.TclError:
            pass
        win.deiconify()
        _apply_dark_titlebar(win)
        win.after(40, lambda: win.winfo_exists() and win.attributes("-alpha", 1.0))
        win.grab_set()

    # ── 시작 / 종료 ───────────────────────
    def _tutorial_start(self):
        """예제 자막을 열고 1단계부터 진행."""
        if getattr(self, "_tut", None):
            return
        if self.subtitles:
            self._close_to_home()
            if self.subtitles:   # 닫기 취소
                return
        path = os.path.join(tempfile.gettempdir(), "튜토리얼 예제.srt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(_EXAMPLE_SRT)
        self._load_srt(path)
        self.update_idletasks()

        self._tut = {"step": -1, "wins": [], "job": None, "pulse": 0,
                     "done": False, "path": path, "rect": None}
        self._tut_build_windows()
        self._tut_goto(0)
        self._tut_tick()

    def _tutorial_end(self, finished=False):
        tut = getattr(self, "_tut", None)
        if not tut:
            return
        if tut["job"]:
            self.after_cancel(tut["job"])
        self._tut_unhook_click()
        for w in tut["wins"]:
            try:
                w.destroy()
            except tk.TclError:
                pass
        self._tut = None
        self._unsaved = False
        self._close_to_home()
        try:
            os.remove(tut["path"])
        except OSError:
            pass
        if finished:
            from ..widgets import show_toast
            show_toast(self, "튜토리얼 끝! 이제 내 파일을 열어 보세요")

    # ── 단계 정의 ─────────────────────────
    def _tut_steps(self):
        return [
            {"target": self._tut_rect_table,
             "text": "불러온 자막이에요.\n한 줄이 대사 하나예요."},
            {"target": lambda: _widget_rect(self._side_panel),
             "text": "등장하는 화자 목록이에요.\n이름을 클릭하면 바꿀 수 있어요."},
            {"target": lambda: self._tut_rect_rows(2, 2, "speaker"),
             "text": "화자 버튼을 눌러\n이 줄의 화자를 지정해 보세요.",
             "interactive": True, "done": lambda: bool(self.subtitles[2]["speaker"])},
            {"target": lambda: self._tut_rect_rows(3, 3),
             "text": "번호를 클릭해 이 줄을 선택한 뒤\n숫자 키 1 또는 2를 눌러 보세요.",
             "keys": ("1", "2"),
             "interactive": True, "done": lambda: bool(self.subtitles[3]["speaker"])},
            {"target": lambda: self._tut_rect_rows(4, 6),
             "text": "번호 칸을 드래그하면 여러 줄을 한 번에 고를 수 있어요.\n세 줄을 고른 뒤 숫자 키를 눌러 보세요.",
             "keys": ("1", "2"),
             "interactive": True,
             "done": lambda: all(self.subtitles[i]["speaker"] for i in range(4, 7))},
            {"target": lambda: _widget_rect(self.lbl_count),
             "text": "아직 화자가 없는 줄 수예요.\n누르면 그 줄로 바로 이동해요. 눌러 보세요.",
             "interactive": True, "click": self.lbl_count,
             "done": lambda: self._tut.get("clicked")},
            {"target": lambda: self._tut_rect_rows(0, 0, "content"),
             "text": "자막을 클릭하면 바로 고칠 수 있어요.",
             "interactive": True, "skippable": True},
            {"target": lambda: _widget_rect(self._tb_btns["저장"]),
             "text": "Ctrl+S로 저장하면\n화자 정보가 SRT에 함께 남아요."},
            {"target": lambda: _widget_rect(self._tb_btns["내보내기"]),
             "text": "화자마다 따로 SRT 파일을 만들어요.\n영상 편집할 때 쓰면 돼요."},
            {"target": lambda: _union(_widget_rect(self._tb_btns["열기"]),
                                      _widget_rect(self._tb_btns["화자 분석"])),
             "text": "음성/영상 파일을 열면 자막 생성과\n화자 자동 분석도 할 수 있어요.",
             "last": True},
        ]

    # ── 강조 영역 계산 ────────────────────
    def _tut_rect_table(self):
        return _widget_rect(self.canvas.master)

    def _tut_rect_rows(self, first, last, col=None):
        """first~last 행 (col 지정 시 그 칸만)의 화면 좌표."""
        self._scroll_to_row(first)
        self._scroll_to_row(last)
        c = self.canvas
        top = self._vscroll_top
        x0, x1 = 0, c.winfo_width()
        if col:
            cx, cw = self._get_col_positions()[col]
            x0, x1 = cx, cx + cw
        y0 = (first - top) * self.ROW_H
        y1 = (last - top + 1) * self.ROW_H
        rx, ry = c.winfo_rootx(), c.winfo_rooty()
        return (rx + x0, ry + max(0, y0), rx + x1, ry + min(c.winfo_height(), y1))

    # ── 창 구성 ───────────────────────────
    def _tut_build_windows(self):
        tut = self._tut

        def _overlay(color, alpha=None):
            w = tk.Toplevel(self)
            w.overrideredirect(True)
            w.configure(bg=color)
            w.attributes("-topmost", True)
            if alpha is not None:
                try:
                    w.attributes("-alpha", alpha)
                except tk.TclError:
                    pass
            tut["wins"].append(w)
            return w

        tut["dims"]  = [_overlay(_DIM_COLOR, _DIM_ALPHA) for _ in range(4)]
        tut["rings"] = [_overlay(ACCENT) for _ in range(4)]

        bub = _overlay(BG3)
        bub.configure(highlightthickness=1, highlightbackground=ACCENT)
        tut["bubble"] = bub
        tut["b_step"] = tk.Label(bub, bg=BG3, fg=ACCENT, font=(theme.FONT_FAMILY, 9, "bold"))
        tut["b_step"].pack(anchor="w", padx=16, pady=(12, 4))
        tut["b_text"] = tk.Label(bub, bg=BG3, fg=FG, justify="left",
                                 font=(theme.FONT_FAMILY, 11))
        tut["b_text"].pack(anchor="w", padx=16)
        tut["b_keys"] = tk.Frame(bub, bg=BG3)
        row = tk.Frame(bub, bg=BG3)
        row.pack(fill="x", padx=12, pady=(12, 12))
        tut["b_row"] = row
        _button(row, "건너뛰기", lambda: self._tutorial_end(), primary=False,
                small=True).pack(side="left")
        tut["b_next"] = _button(row, "다음", self._tut_next, small=True)
        tut["b_next"].pack(side="right")

        self.bind("<Unmap>", self._tut_on_unmap, add="+")

    def _tut_on_unmap(self, e):
        tut = getattr(self, "_tut", None)
        if tut and e.widget is self:
            for w in tut["wins"]:
                w.withdraw()
            tut["rect"] = None   # 다시 보일 때 재배치

    # ── 단계 이동 ─────────────────────────
    def _tut_goto(self, i):
        tut = self._tut
        self._tut_unhook_click()
        steps = self._tut_steps()
        tut["step"], tut["cur"], tut["done"] = i, steps[i], False
        st = tut["cur"]
        tut["bubble"].withdraw()   # 내용 바꾸는 동안 이전 위치에 보이지 않게
        tut["b_step"].configure(text=f"{i + 1} / {len(steps)}")
        tut["b_text"].configure(text=st["text"])
        for w in tut["b_keys"].winfo_children():
            w.destroy()
        if st.get("keys"):
            tut["b_keys"].pack(anchor="w", padx=16, before=tut["b_row"])
        else:
            tut["b_keys"].pack_forget()
        for k in st.get("keys", ()):
            tk.Label(tut["b_keys"], text=f" {k} ", bg=BG2, fg=FG, bd=1, relief="solid",
                     font=(theme.FONT_FAMILY, 10, "bold")).pack(side="left", padx=(0, 6), pady=(8, 0))
        nxt = tut["b_next"]
        nxt.set_text("완료" if st.get("last") else "다음")
        if st.get("done") and not st.get("skippable"):
            nxt.pack_forget()
        else:
            nxt.pack(side="right")
        if st.get("click"):
            self._tut_hook_click(st["click"])
        tut["rect"] = None
        self._tut_layout()
        # 설명만 하는 단계는 말풍선만 조작 가능
        bub = tut["bubble"]
        if st.get("interactive"):
            bub.grab_release()
        else:
            bub.update_idletasks()
            try:
                bub.grab_set()
            except tk.TclError:
                pass

    def _tut_hook_click(self, w):
        """w 클릭 시 원래 동작 대신 클릭만 기록."""
        tag = "TutorialClick"
        self._tut["clicked"] = False
        self._tut["hooked"] = w
        w.bind_class(tag, "<Button-1>", lambda e: (self._tut.__setitem__("clicked", True), "break")[1]
                     if self._tut else None)
        w.bindtags((tag,) + w.bindtags())

    def _tut_unhook_click(self):
        tut = getattr(self, "_tut", None)
        w = tut and tut.pop("hooked", None)
        if w:
            w.bindtags(tuple(t for t in w.bindtags() if t != "TutorialClick"))

    def _tut_next(self):
        tut = getattr(self, "_tut", None)
        if not tut:
            return
        if tut["cur"].get("last"):
            self._tutorial_end(finished=True)
        else:
            self._tut_goto(tut["step"] + 1)
            self.focus_set()   # 숫자 키 입력이 메인 창으로 가게

    def _tut_tick(self):
        """강조 위치 갱신·완료 조건 확인·테두리 깜빡임."""
        tut = getattr(self, "_tut", None)
        if not tut:
            return
        tut["job"] = self.after(120, self._tut_tick)
        if not self.winfo_viewable():
            return
        st = tut["cur"]
        if not tut["done"] and st.get("done") and st["done"]():
            tut["done"] = True
            self._tut_ring_color(_OK_COLOR)
            step = tut["step"]
            self.after(700, lambda: self._tut and self._tut["step"] == step and self._tut_next())
            return
        if not tut["done"]:
            tut["pulse"] = (tut["pulse"] + 1) % 16
            self._tut_ring_color(_RING_COLORS[tut["pulse"] // 8])
        self._tut_layout()

    def _tut_ring_color(self, color):
        for w in self._tut["rings"]:
            w.configure(bg=color)

    def _tut_layout(self):
        """현재 단계의 강조 영역에 맞춰 어둡게·테두리·말풍선 위치 조정."""
        tut = self._tut
        st = tut["cur"]
        try:
            x0, y0, x1, y1 = st["target"]()
        except Exception:
            return
        x0, y0, x1, y1 = x0 - _PAD, y0 - _PAD, x1 + _PAD, y1 + _PAD
        wx, wy = self.winfo_rootx(), self.winfo_rooty()
        ww, wh = self.winfo_width(), self.winfo_height()
        state = (x0, y0, x1, y1, wx, wy, ww, wh)
        if state == tut["rect"]:
            # 말풍선 위치가 밀렸으면 다시 맞춤
            want = tut.get("bub_geo")
            if want and tut["bubble"].wm_geometry() != want:
                tut["bubble"].geometry(want)
            return
        tut["rect"] = state
        wx1, wy1 = wx + ww, wy + wh
        r = _RING_W
        x0, y0 = max(wx + r, x0), max(wy + r, y0)
        x1, y1 = min(wx1 - r, x1), min(wy1 - r, y1)

        show = []   # 위치를 먼저 모두 정한 뒤 한꺼번에 보이게 함

        def _place(w, a, b, c, d):
            if c - a <= 0 or d - b <= 0:
                w.withdraw()
                return
            w.geometry(f"{c - a}x{d - b}+{a}+{b}")
            show.append(w)

        top, bot, left, right = tut["dims"]
        _place(top,   wx, wy, wx1, y0)
        _place(bot,   wx, y1, wx1, wy1)
        _place(left,  wx, y0, x0, y1)
        _place(right, x1, y0, wx1, y1)

        rt, rb, rl, rr = tut["rings"]
        _place(rt, x0 - r, y0 - r, x1 + r, y0)
        _place(rb, x0 - r, y1, x1 + r, y1 + r)
        _place(rl, x0 - r, y0, x0, y1)
        _place(rr, x1, y0, x1 + r, y1)

        # 말풍선: 강조 영역 아래 → 위 → 오른쪽 → 왼쪽 순으로 들어가는 자리
        bub = tut["bubble"]
        bub.update_idletasks()
        bw, bh = bub.winfo_reqwidth(), bub.winfo_reqheight()
        gap = 14
        cands = [
            (x0, y1 + gap),
            (x0, y0 - gap - bh),
            (x1 + gap, y0),
            (x0 - gap - bw, y0),
        ]
        # 들어갈 자리가 없으면 강조 영역 안쪽 오른쪽 아래
        bx, by = next(((cx, cy) for cx, cy in cands
                       if wx <= cx and cx + bw <= wx1 and wy <= cy and cy + bh <= wy1),
                      (x1 - bw - 16, y1 - bh - 16))
        bx = min(max(wx + 8, bx), wx1 - bw - 8)
        tut["bub_geo"] = f"{bw}x{bh}+{bx}+{by}"
        bub.geometry(tut["bub_geo"])
        show.append(bub)

        # 새 위치가 반영된 뒤에 표시 (이전 위치에 잠깐 그려지지 않게)
        for w in show:
            w.update_idletasks()
        for w in show:
            if w.state() != "normal":
                w.deiconify()
            w.lift()


def _widget_rect(w):
    x, y = w.winfo_rootx(), w.winfo_rooty()
    return (x, y, x + w.winfo_width(), y + w.winfo_height())


def _union(a, b):
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _button(parent, text, cmd, primary=True, small=False):
    """앱 톤에 맞춘 평평한 버튼."""
    bg, hover = (ACCENT, "#AE96E2") if primary else (BG2, "#2E2E36")
    lbl = tk.Label(parent, text=text, bg=bg, fg="white" if primary else FG,
                   cursor="hand2", padx=12 if small else 18, pady=4 if small else 8,
                   font=(theme.FONT_FAMILY, 9 if small else 10, "bold" if primary else "normal"),
                   highlightthickness=0 if primary else 1, highlightbackground=BORDER)
    lbl.bind("<Enter>", lambda e: lbl.configure(bg=hover))
    lbl.bind("<Leave>", lambda e: lbl.configure(bg=bg))
    lbl.bind("<ButtonRelease-1>", lambda e: cmd())
    lbl.set_text = lambda t: lbl.configure(text=t)
    return lbl
