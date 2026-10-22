"""단축키 안내 창: 텐키리스 키보드 그림, 누른 키의 동작과 짧은 시연."""
import tkinter as tk

from .. import theme
from ..theme import ACCENT, BG, BG3, FG, FG_DIM, ON_BG, ON_BORDER, _apply_dark_titlebar

U = 38      # 키 한 칸 크기
GAP = 4

# (키 이름, 너비) 줄 단위. None은 빈칸.
_ROWS = [
    [("Esc", 1), None, ("F1", 1), ("F2", 1), ("F3", 1), ("F4", 1), (None, .5), ("F5", 1), ("F6", 1), ("F7", 1), ("F8", 1),
     (None, .5), ("F9", 1), ("F10", 1), ("F11", 1), ("F12", 1)],
    [("`", 1), ("1", 1), ("2", 1), ("3", 1), ("4", 1), ("5", 1), ("6", 1), ("7", 1), ("8", 1), ("9", 1), ("0", 1),
     ("-", 1), ("=", 1), ("Backspace", 2)],
    [("Tab", 1.5), ("Q", 1), ("W", 1), ("E", 1), ("R", 1), ("T", 1), ("Y", 1), ("U", 1), ("I", 1), ("O", 1), ("P", 1),
     ("[", 1), ("]", 1), ("\\", 1.5)],
    [("Caps", 1.75), ("A", 1), ("S", 1), ("D", 1), ("F", 1), ("G", 1), ("H", 1), ("J", 1), ("K", 1), ("L", 1),
     (";", 1), ("'", 1), ("Enter", 2.25)],
    [("Shift", 2.25), ("Z", 1), ("X", 1), ("C", 1), ("V", 1), ("B", 1), ("N", 1), ("M", 1), (",", 1), (".", 1),
     ("/", 1), ("Shift ", 2.75)],
    [("Ctrl", 1.25), ("Win", 1.25), ("Alt", 1.25), ("Space", 6.25), ("Alt ", 1.25), ("Win ", 1.25), ("Menu", 1.25),
     ("Ctrl ", 1.25)],
]
_NAV = {0: ["PrtSc", "ScrLk", "Pause"], 1: ["Ins", "Home", "PgUp"], 2: ["Del", "End", "PgDn"],
        4: [None, "Up", None], 5: ["Left", "Down", "Right"]}
_LABEL = {"Up": "↑", "Down": "↓", "Left": "←", "Right": "→", "Backspace": "⌫"}
_MOD_KEYS = {"Ctrl": "Ctrl", "Ctrl ": "Ctrl", "Shift": "Shift", "Shift ": "Shift", "Alt": "Alt", "Alt ": "Alt"}
_MOD_SYM = {"Control_L": "Ctrl", "Control_R": "Ctrl", "Shift_L": "Shift", "Shift_R": "Shift",
            "Alt_L": "Alt", "Alt_R": "Alt"}

# 조합 → 키 → (이름, 설명, 시연)
_DIGITS = "1234567890"
_KEYS = {
    "": {
        "`": ("화자 해제", "선택한 줄의 화자를 지워요", "spk0"),
        **{d: ("화자 지정", "1~0: 1~10번째 화자", "spk") for d in _DIGITS},
        "Q": ("시작으로", "재생 위치를 자막 시작으로", "q"),
        "W": ("끝으로", "재생 위치를 자막 끝으로 (재생 중이면 다음 줄)", "w"),
        "S": ("나누기", "재생 위치에서 자막을 둘로", "split"),
        "M": ("병합", "선택한 자막을 하나로", "merge"),
        "F": ("다음 ? 줄", "화자 없는 다음 줄 듣기", "next"),
        "V": ("영상 창", "영상 창 열기 / 닫기", None),
        "[": ("느리게", "재생 한 단계 느리게 (0.5배속까지)", None),
        "]": ("빠르게", "재생 한 단계 빠르게 (4배속까지)", None),
        "Space": ("재생", "재생 / 일시정지", "play"),
        "Left": ("뒤로", "재생 위치 0.2초 뒤로", "left"),
        "Right": ("앞으로", "재생 위치 0.2초 앞으로", "right"),
        "Up": ("이전 줄", "이전 자막 선택 (편집 중엔 윗줄 편집)", "up"),
        "Down": ("다음 줄", "다음 자막 선택 (편집 중엔 아랫줄 편집)", "down"),
        "Enter": ("편집", "선택한 자막 내용 편집", "edit"),
        "F2": ("편집", "선택한 자막 내용 편집", "edit"),
        "Tab": ("다음 줄 편집", "편집 중: 저장하고 다음 줄", "down"),
        "Del": ("삭제", "선택한 자막 삭제", "del"),
        "Home": ("첫 자막", "처음 자막으로", "home"),
        "End": ("마지막 자막", "마지막 자막으로", "end"),
        "PgUp": ("한 화면 위", "한 화면씩 위로", "home"),
        "PgDn": ("한 화면 아래", "한 화면씩 아래로", "end"),
        "Esc": ("취소", "여러 줄 선택 해제 · 편집 중엔 고친 내용 취소", None),
        "F1": ("단축키", "이 창 열기", None),
    },
    "Ctrl": {
        "O": ("열기", "파일 열기", None), "S": ("저장", "저장", None),
        "E": ("화자별 내보내기", "화자마다 따로 내보내기", None), "W": ("닫기", "파일 닫고 홈으로", None),
        "Z": ("실행 취소", "", None), "Y": ("다시 실행", "", None),
        "X": ("잘라내기", "", None), "C": ("복사", "", None), "V": ("붙여넣기", "", None),
        "D": ("삭제", "선택한 자막 삭제", "del"), "A": ("자막 추가", "재생 위치에 새 자막", "add"),
        "F": ("검색", "자막 검색", None), "H": ("찾아 바꾸기", "", None), "M": ("음소거", "음소거 켜기 / 끄기", None),
        "Space": ("다시 듣기", "편집 중: 이 줄 다시 듣기", "play"),
        "Left": ("조금 뒤로", "재생 위치 0.05초 뒤로", "small_l"),
        "Right": ("조금 앞으로", "재생 위치 0.05초 앞으로", "small_r"),
        "=": ("확대", "타임라인 확대", None), "-": ("축소", "타임라인 축소", None), ",": ("설정", "설정 열기", None),
    },
    "Shift": {
        **{d: ("화자 지정", "Shift+1~0: 11~20번째 화자", "spk") for d in _DIGITS},
        "Left": ("크게 뒤로", "재생 위치 5초 뒤로", "big_l"),
        "Right": ("크게 앞으로", "재생 위치 5초 앞으로", "big_r"),
        "Up": ("여러 줄 선택", "위로 넓히기 (타임라인: 이전 경계로)", "multi_up"),
        "Down": ("여러 줄 선택", "아래로 넓히기 (타임라인: 다음 경계로)", "multi"),
        "Enter": ("줄바꿈", "편집 중: 자막 안에 줄바꿈 넣기", "edit"),
        "Tab": ("이전 줄 편집", "편집 중: 저장하고 이전 줄", "up"),
        "/": ("단축키", "이 창 열기", None),
    },
    "Alt": {
        "Left": ("시작 당기기", "자막 시작 0.05초 앞으로", "nudge_l"),
        "Right": ("시작 밀기", "자막 시작 0.05초 뒤로", "nudge_r"),
        "Up": ("단어 올리기", "윗줄과 단어 하나 주고받기", "word_up"),
        "Down": ("단어 내리기", "윗줄과 단어 하나 주고받기", "word_down"),
    },
    "Shift+Alt": {
        "Left": ("끝 당기기", "자막 끝 0.05초 앞으로", "end_l"),
        "Right": ("끝 밀기", "자막 끝 0.05초 뒤로", "end_r"),
    },
    "Ctrl+Shift": {
        "S": ("다른 이름으로 저장", "", None), "A": ("전체 선택", "", "all"), "Z": ("다시 실행", "", None),
    },
}

_MOUSE = [("휠", "타임라인 좌우 이동"), ("Alt+휠 · Ctrl+휠", "타임라인 확대·축소"),
          ("Ctrl+경계 드래그", "맞닿은 옆 줄 경계도 같이"), ("화자 줄 끌기", "화자 순서 바꾸기")]

# Windows 가상 키 코드 → 키 이름 (한글 입력 상태여도 같은 키로)
_VK = {**{65 + i: chr(65 + i) for i in range(26)}, **{48 + i: str(i) for i in range(10)},
       **{112 + i: f"F{i + 1}" for i in range(12)},
       37: "Left", 38: "Up", 39: "Right", 40: "Down", 32: "Space", 13: "Enter", 27: "Esc", 9: "Tab", 8: "Backspace",
       46: "Del", 45: "Ins", 36: "Home", 35: "End", 33: "PgUp", 34: "PgDn", 192: "`", 189: "-", 187: "=",
       219: "[", 221: "]", 220: "\\", 186: ";", 222: "'", 188: ",", 190: ".", 191: "/"}
_SYM = {"grave": "`", "asciitilde": "`", "minus": "-", "underscore": "-", "equal": "=", "plus": "=",
        "bracketleft": "[", "braceleft": "[", "bracketright": "]", "braceright": "]", "comma": ",", "less": ",",
        "period": ".", "greater": ".", "slash": "/", "question": "/", "space": "Space", "Return": "Enter",
        "Escape": "Esc", "Delete": "Del", "Prior": "PgUp", "Next": "PgDn", "BackSpace": "Backspace",
        "exclam": "1", "at": "2", "numbersign": "3", "dollar": "4", "percent": "5", "asciicircum": "6",
        "ampersand": "7", "asterisk": "8", "parenleft": "9", "parenright": "0", "Insert": "Ins"}

_DEMO_ROWS = ["안녕하세요", "오늘 방송은", "그래서 말이야", "ㅋㅋㅋㅋ"]
_OFF_BG, _OFF_FG, _OFF_LINE = "#24242C", "#55555F", "#2E2E38"


def key_of(event):
    """키 이벤트 → 키보드 그림의 키 이름."""
    sym = event.keysym or ""
    if sym in _SYM:
        return _SYM[sym]
    if len(sym) == 1 and sym.isascii() and sym.isalnum():
        return sym.upper()
    if sym in _LABEL or sym in ("Home", "End", "Tab") or (sym[:1] == "F" and sym[1:].isdigit()):
        return sym
    return _VK.get(getattr(event, "keycode", 0))


def mods_of(event):
    m = []
    if event.state & 0x4:
        m.append("Ctrl")
    if event.state & 0x1:
        m.append("Shift")
    if event.state & 0x20000:   # Windows Alt (0x8은 Num Lock)
        m.append("Alt")
    return m


def combo(mods):
    return "+".join(m for m in ("Ctrl", "Shift", "Alt") if m in mods)


def lookup(mods, key):
    return _KEYS.get(combo(mods), {}).get(key)


class _Keyboard:
    """단축키 창 내용: 키보드 그림 + 설명 + 시연."""

    def __init__(self, win):
        self.win = win
        self.held, self.sticky = set(), set()
        self._anim = None
        self.last = self.demo_kind = None   # 마지막으로 누른 (조합, 키, 동작)·시연
        self.cv = tk.Canvas(win, bg=BG, highlightthickness=0)
        self.cv.pack(padx=24, pady=(20, 6))
        self._layout()

        info = tk.Frame(win, bg=BG3)
        info.pack(fill="x", padx=24, pady=(8, 0))
        self.demo = tk.Canvas(info, width=250, height=84, bg=BG3, highlightthickness=0)
        self.demo.pack(side="left", padx=12, pady=10)
        txt = tk.Frame(info, bg=BG3)
        txt.pack(side="left", fill="both", expand=True, pady=10)
        self.name = tk.Label(txt, text="키를 눌러 보세요", bg=BG3, fg=FG, anchor="w",
                             font=(theme.FONT_FAMILY, 13, "bold"))
        self.name.pack(fill="x")
        self.desc = tk.Label(txt, text="빛나는 키에 단축키가 있어요. Ctrl·Shift·Alt를 누르면 바뀌어요.",
                             bg=BG3, fg=FG_DIM, anchor="w", justify="left", font=(theme.FONT_FAMILY, 9))
        self.desc.pack(fill="x", pady=(4, 0))

        mouse = tk.Frame(win, bg=BG)
        mouse.pack(fill="x", padx=24, pady=(10, 0))
        for i, (k, d) in enumerate(_MOUSE):
            tk.Label(mouse, text=k, bg=BG, fg=FG, font=(theme.FONT_FAMILY, 9, "bold")).grid(
                row=i // 2, column=(i % 2) * 2, sticky="w", pady=1)
            tk.Label(mouse, text=d, bg=BG, fg=FG_DIM, font=(theme.FONT_FAMILY, 9)).grid(
                row=i // 2, column=(i % 2) * 2 + 1, sticky="w", padx=(8, 28), pady=1)
        self.paint()

    # ── 키보드 그리기 ──
    def _layout(self):
        self.keys = {}   # 이름 → (사각형 id, 글자 id)
        step = U + GAP
        main_w = 15 * step
        for r, row in enumerate(_ROWS):
            y = r * step + (10 if r else 0)
            x = 0.0
            for item in row:
                if item is None:
                    x += step
                    continue
                k, w = item
                if k is None:
                    x += w * step
                    continue
                self._key(k, x, y, w * step - GAP)
                x += w * step
            for i, k in enumerate(_NAV.get(r, [])):
                if k:
                    self._key(k, main_w + 12 + i * step, y, U)
        self.cv.configure(width=main_w + 12 + 3 * step, height=6 * step + 10)
        self.cv.tag_bind("key", "<Enter>", self._hover)
        self.cv.tag_bind("key", "<ButtonRelease-1>", self._click)

    def _key(self, k, x, y, w):
        tag = f"k:{k}"
        rect = self.cv.create_rectangle(x, y, x + w, y + U, width=1, tags=("key", tag))
        label = _LABEL.get(k, k.strip())
        size = 9 if len(label) <= 2 else 8
        text = self.cv.create_text(x + w / 2, y + U / 2, text=label, font=(theme.FONT_FAMILY, size), tags=("key", tag))
        self.keys[k] = (rect, text)

    def mods(self):
        return self.held | self.sticky

    def paint(self):
        mods = self.mods()
        table = _KEYS.get(combo(mods), {})
        for k, (rect, text) in self.keys.items():
            if _MOD_KEYS.get(k) in mods:
                bg, fg, line = ACCENT, "white", ACCENT
            elif k in table or (_MOD_KEYS.get(k) and combo(mods | {_MOD_KEYS[k]}) in _KEYS):
                bg, fg, line = ON_BG, FG, ON_BORDER
            else:
                bg, fg, line = _OFF_BG, _OFF_FG, _OFF_LINE
            self.cv.itemconfigure(rect, fill=bg, outline=line)
            self.cv.itemconfigure(text, fill=fg)

    def _key_at(self):
        for t in self.cv.gettags("current"):
            if t.startswith("k:"):
                return t[2:]
        return None

    def _hover(self, e):
        k = self._key_at()
        v = k and lookup(self.mods(), k)
        if v:
            self.show(k, v, animate=False)

    def _click(self, e):
        k = self._key_at()
        if not k:
            return
        m = _MOD_KEYS.get(k)
        if m:
            self.sticky ^= {m}
            self.paint()
            return
        self.press(k)

    # ── 키 누름 ──
    def on_key(self, e):
        m = _MOD_SYM.get(e.keysym)
        if m:
            self.held.add(m)
            self.paint()
            return "break"
        self.held = set(mods_of(e))
        if e.keysym == "Escape" and not self.mods():
            self.win.destroy()
            return "break"
        k = key_of(e)
        if k:
            self.paint()
            self.press(k)
        return "break"

    def on_release(self, e):
        m = _MOD_SYM.get(e.keysym)
        if m:
            self.held.discard(m)
            self.paint()
        return "break"

    def press(self, k):
        rect = self.keys.get(k, (None,))[0]
        if rect is not None:
            self.cv.itemconfigure(rect, fill=ACCENT)
            self.win.after(140, self.paint)
        v = lookup(self.mods(), k)
        if v:
            self.show(k, v, animate=True)
        else:
            self.name.configure(text=self._title(k))
            self.desc.configure(text="이 조합엔 단축키가 없어요")
            self._demo(None)
        self.last = (combo(self.mods()), k, v and v[0])

    def _title(self, k):
        return "+".join(combo(self.mods()).split("+") + [_LABEL.get(k, k.strip())]).lstrip("+")

    def show(self, k, v, animate):
        name, desc, demo = v
        self.name.configure(text=f"{self._title(k)}   {name}")
        self.desc.configure(text=desc or name)
        self._demo(demo, animate)

    # ── 시연 ──
    def _demo(self, kind, animate=True):
        """kind 시연 그리기. animate면 전→후로 움직이고, 아니면 후 모습만."""
        c = self.demo
        if self._anim:
            self.win.after_cancel(self._anim)
            self._anim = None
        c.delete("all")
        self.demo_kind = kind
        if not kind:
            return
        if kind in _ROW_DEMOS:
            before, after = _ROW_DEMOS[kind]
            if not animate:
                self._rows(*after)
                return
            self._rows(*before)

            def flip():
                self._anim = None
                c.delete("all")
                self._rows(*after)
            self._anim = self.win.after(380, flip)
            return
        self._timeline(kind, animate)

    def _rows(self, rows, sel, spk=None, cursor=None):
        c = self.demo
        for i, t in enumerate(rows[:4]):
            y = 4 + i * 20
            on = i in sel
            c.create_rectangle(0, y, 250, y + 17, fill="#4A3F70" if on else "#2E2E3A", outline="")
            x = 8
            if spk == i:
                c.create_text(x, y + 9, text="[철수]", anchor="w", fill="#E8A86A", font=(theme.FONT_FAMILY, 9))
                x += 42
            c.create_text(x, y + 9, text=t, anchor="w", fill="white" if on else "#9A9AA6",
                          font=(theme.FONT_FAMILY, 9))
            if cursor == i:
                c.create_rectangle(1, y + 1, 249, y + 16, outline=ACCENT, width=2)

    def _timeline(self, kind, animate=True):
        c = self.demo
        c.create_rectangle(0, 18, 250, 66, fill="#2A2A36", outline="")
        a, b = 50, 190
        start_to = {"nudge_l": 40, "nudge_r": 60}.get(kind, a)
        end_to = {"end_l": 180, "end_r": 200}.get(kind, b)
        block = c.create_rectangle(a, 32, b, 52, fill="#4A3F70", outline="")
        ph0 = 120
        ph_to = {"q": a, "w": b, "left": 104, "right": 136, "small_l": 114, "small_r": 126,
                 "big_l": 20, "big_r": 230, "play": 230}.get(kind, ph0)
        ph = c.create_line(ph0, 18, ph0, 66, fill="#E85050", width=2)
        frames = 22 if kind == "play" else 9

        def step(i=1):
            f = i / frames
            x = ph0 + (ph_to - ph0) * f
            c.coords(ph, x, 18, x, 66)
            c.coords(block, a + (start_to - a) * f, 32, b + (end_to - b) * f, 52)
            if i < frames:
                self._anim = self.win.after(30, lambda: step(i + 1))
            else:
                self._anim = None
        if animate:
            self._anim = self.win.after(200, step)
        else:
            step(frames)


_R = _DEMO_ROWS
_ROW_DEMOS = {   # 시연: (전, 후) = (줄들, 선택한 줄, 화자 붙은 줄, 편집 중인 줄)
    "up": ((_R, {1}), (_R, {0})),
    "down": ((_R, {1}), (_R, {2})),
    "multi": ((_R, {1}), (_R, {1, 2})),
    "multi_up": ((_R, {1}), (_R, {0, 1})),
    "all": ((_R, {1}), (_R, {0, 1, 2, 3})),
    "home": ((_R, {2}), (_R, {0})),
    "end": ((_R, {1}), (_R, {3})),
    "next": ((_R, {0}), (_R, {2})),
    "spk": ((_R, {1}), (_R, {1}, 1)),
    "spk0": ((_R, {1}, 1), (_R, {1})),
    "edit": ((_R, {1}), (_R, {1}, None, 1)),
    "del": ((_R, {1}), ([_R[0], _R[2], _R[3]], {1})),
    "add": ((_R, {1}), ([_R[0], _R[1], "새 자막", _R[2]], {2})),
    "split": ((_R, {1}), ([_R[0], "오늘", "방송은", _R[2]], {2})),
    "merge": ((_R, {1, 2}), ([_R[0], "오늘 방송은 그래서 말이야", _R[3]], {1})),
    "word_up": (([_R[0], "오늘", "방송은 그래서", _R[3]], {2}), ([_R[0], "오늘 방송은", "그래서", _R[3]], {2})),
    "word_down": (([_R[0], "오늘 방송은", "그래서", _R[3]], {2}), ([_R[0], "오늘", "방송은 그래서", _R[3]], {2})),
}


class ShortcutsMixin:
    """단축키 안내 창."""

    def _show_shortcuts(self, event=None):
        if isinstance(self.focus_get(), tk.Entry):
            return
        old = getattr(self, "_shortcuts_win", None)
        if old is not None and old.winfo_exists():
            old.lift()
            return "break"

        win = tk.Toplevel(self)
        win.withdraw()   # 다 그린 뒤 제자리에 표시
        win.title("단축키")
        win.configure(bg=BG)
        win.resizable(False, False)
        win.transient(self)
        self._shortcuts_win = win
        kb = _Keyboard(win)
        win._kb = kb

        close = tk.Label(win, text="닫기", bg=BG3, fg=FG, cursor="hand2", padx=18, pady=5,
                         font=(theme.FONT_FAMILY, 9))
        close.pack(pady=(12, 18))
        close.bind("<ButtonRelease-1>", lambda e: win.destroy())
        win.bind("<KeyPress>", kb.on_key)
        win.bind("<KeyRelease>", kb.on_release)
        win.bind("<FocusOut>", lambda e: (kb.held.clear(), kb.paint()) if e.widget is win else None)

        win.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - win.winfo_reqwidth()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - win.winfo_reqheight()) // 3
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
        try:
            win.attributes("-alpha", 0.0)
        except tk.TclError:
            pass
        win.deiconify()
        _apply_dark_titlebar(win)
        win.after(40, lambda: win.winfo_exists() and win.attributes("-alpha", 1.0))
        win.focus_set()
        return "break"
