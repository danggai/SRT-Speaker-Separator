"""Windows 한글 IME 조합 중인 글자 표시.

Tk 8.6은 Windows에서 IME 조합 메시지를 받아 처리하지만 조합 중인 글자를
화면에 그리지 않는다. 그래서 '궈'를 입력하면 ㄱ → 구 → 궈가 보이지 않다가
다음 글자를 입력해 '궈'가 확정되는 순간에야 한꺼번에 나타난다.

이를 보완하기 위해, Entry에 포커스가 있는 동안 IME의 조합 문자열을 주기적으로
읽어 커서 위치에 밑줄 친 레이블로 겹쳐 그린다. 표시용일 뿐 Entry 내용은
건드리지 않으므로, 실제 입력(확정)은 기존과 똑같이 처리된다.
"""
import sys
import tkinter as tk
import tkinter.font as tkfont


class ImeCompositionOverlay:
    POLL_MS = 30
    GCS_COMPSTR = 0x8

    def __init__(self, root):
        self.root = root
        self._label = None
        self._label_master = None
        self._fonts = {}
        if sys.platform != "win32":
            return
        try:
            import ctypes
            import ctypes.wintypes as wt
            self._ctypes = ctypes
            self._user32 = ctypes.windll.user32
            self._imm = ctypes.windll.imm32
            self._user32.GetFocus.restype = wt.HWND
            self._imm.ImmGetContext.restype = ctypes.c_void_p
            self._imm.ImmGetContext.argtypes = [wt.HWND]
            self._imm.ImmReleaseContext.argtypes = [wt.HWND, ctypes.c_void_p]
            self._imm.ImmGetCompositionStringW.argtypes = [
                ctypes.c_void_p, wt.DWORD, ctypes.c_void_p, wt.DWORD]
        except Exception:
            return
        root.after(self.POLL_MS, self._poll)

    def _composition(self):
        """IME가 조합 중인 문자열 (없으면 빈 문자열)."""
        hwnd = self._user32.GetFocus()
        if not hwnd:
            return ""
        himc = self._imm.ImmGetContext(hwnd)
        if not himc:
            return ""
        try:
            n = self._imm.ImmGetCompositionStringW(himc, self.GCS_COMPSTR, None, 0)
            if n <= 0:
                return ""
            buf = self._ctypes.create_unicode_buffer(n // 2 + 1)
            self._imm.ImmGetCompositionStringW(himc, self.GCS_COMPSTR, buf, n)
            return buf.value
        finally:
            self._imm.ImmReleaseContext(hwnd, himc)

    def _poll(self):
        try:
            try:
                widget = self.root.focus_get()
            except Exception:   # 팝업 메뉴 등 Tk가 모르는 창에 포커스가 있을 때
                widget = None
            text = self._composition() if isinstance(widget, tk.Entry) else ""
            if text:
                self._show(widget, text)
            else:
                self._hide()
        except Exception:
            self._hide()
        try:
            self.root.after(self.POLL_MS, self._poll)
        except tk.TclError:   # 앱 종료
            pass

    def _font_for(self, entry):
        """Entry 글꼴에 밑줄만 더한 글꼴 (조합 중 표시)."""
        spec = entry.cget("font")
        f = self._fonts.get(spec)
        if f is None:
            f = tkfont.Font(root=self.root, font=spec)
            f.configure(underline=True)
            self._fonts[spec] = f
        return f

    def _caret_box(self, entry, font):
        """Entry 안에서 커서 위치의 (x, y, 높이).
        Entry.bbox()가 환경에 따라 (0, 0, 0, 0)을 돌려주는 경우가 있어,
        화면에 보이는 첫 글자부터 커서까지의 글자 폭을 직접 잰다."""
        text = entry.get()
        first = entry.index("@0")          # 가로 스크롤 시 화면에 보이는 첫 글자
        idx = entry.index("insert")
        pad = int(entry.cget("bd")) + int(entry.cget("highlightthickness")) + 1
        x = pad + font.measure(text[first:idx]) if idx >= first else pad
        h = font.metrics("linespace")
        return min(x, max(pad, entry.winfo_width() - pad)), max(0, (entry.winfo_height() - h) // 2), h

    def _show(self, entry, text):
        master = entry.master
        if self._label is None or self._label_master is not master:
            self._hide(destroy=True)
            self._label = tk.Label(master, bd=0, padx=0, pady=0, takefocus=0)
            self._label_master = master
        font = self._font_for(entry)
        x, y, h = self._caret_box(entry, font)
        self._label.configure(text=text, font=font,
                              bg=entry.cget("bg"), fg=entry.cget("fg"))
        self._label.place(in_=entry, x=x, y=y, height=h)
        self._label.lift(entry)

    def _hide(self, destroy=False):
        if self._label is None:
            return
        try:
            if destroy:
                self._label.destroy()
                self._label = None
                self._label_master = None
            else:
                self._label.place_forget()
        except tk.TclError:   # 부모 창이 이미 닫힘
            self._label = None
            self._label_master = None
