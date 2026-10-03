"""단축키 안내 창."""
import tkinter as tk

from .. import theme
from ..theme import ACCENT, BG, BG3, BORDER, FG, FG_DIM, _apply_dark_titlebar

_SHORTCUTS = [
    ("파일", [
        ("Ctrl+O", "열기"),
        ("Ctrl+S", "저장"),
        ("Ctrl+Shift+S", "다른 이름으로 저장"),
    ]),
    ("편집", [
        ("Ctrl+Z", "실행 취소"),
        ("Ctrl+Y", "다시 실행"),
        ("Ctrl+X / C / V", "잘라내기 / 복사 / 붙여넣기"),
        ("Enter", "선택한 자막 내용 편집"),
        ("Delete", "선택한 자막 삭제"),
        ("S", "재생 위치에서 자막 나누기"),
        ("A", "재생 위치에 자막 추가"),
    ]),
    ("화자", [
        ("1 ~ 9", "선택한 자막에 화자 지정"),
        ("`", "화자 지정 해제"),
    ]),
    ("이동 · 재생", [
        ("↑ / ↓", "이전 / 다음 자막 선택"),
        ("Shift+↑ / ↓", "여러 줄 선택"),
        ("Page Up / Down", "한 화면씩 이동"),
        ("Space", "재생 / 일시정지"),
        ("M", "음소거 켜기 / 끄기"),
        ("← / →", "5초 이동 (Shift: 30초)"),
    ]),
    ("기타", [
        ("?", "단축키 보기"),
    ]),
]


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

        body = tk.Frame(win, bg=BG)
        body.pack(padx=28, pady=(20, 8))
        row = 0
        for section, items in _SHORTCUTS:
            tk.Label(body, text=section, bg=BG, fg=ACCENT,
                     font=(theme.FONT_FAMILY, 10, "bold")).grid(
                row=row, column=0, columnspan=2, sticky="w", pady=(10 if row else 0, 4))
            row += 1
            for key, desc in items:
                tk.Label(body, text=key, bg=BG3, fg=FG, padx=8, pady=1,
                         highlightthickness=1, highlightbackground=BORDER,
                         font=(theme.FONT_FAMILY, 9, "bold")).grid(
                    row=row, column=0, sticky="w", pady=2)
                tk.Label(body, text=desc, bg=BG, fg=FG_DIM,
                         font=(theme.FONT_FAMILY, 9)).grid(
                    row=row, column=1, sticky="w", padx=(14, 0), pady=2)
                row += 1

        close = tk.Label(win, text="닫기", bg=BG3, fg=FG, cursor="hand2", padx=18, pady=5,
                         font=(theme.FONT_FAMILY, 9))
        close.pack(pady=(10, 20))
        close.bind("<ButtonRelease-1>", lambda e: win.destroy())
        win.bind("<Escape>", lambda e: win.destroy())

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
