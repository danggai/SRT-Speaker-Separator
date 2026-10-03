"""Windows 한글 IME 조합 중 글자를 입력칸에 표시 (Tk 8.6 미지원 보완), IME 기본 조합창은 화면 밖으로.
입력칸이 아닌 곳에서는 IME를 떼어 한글 상태에서도 단축키가 동작하게 한다."""
import sys
import tkinter as tk
import tkinter.font as tkfont

_WM_IME_STARTCOMPOSITION = 0x010D
_WM_IME_COMPOSITION = 0x010F
_GWLP_WNDPROC = -4
_CFS_POINT = 0x0002
_OFFSCREEN = -32000


class ImeCompositionOverlay:
    POLL_MS = 30
    GCS_COMPSTR = 0x8

    def __init__(self, root):
        self.root = root
        self._label = None
        self._label_master = None
        self._fonts = {}
        self._hooked = {}   # hwnd → (콜백 객체, 원래 창 프로시저)
        self._no_ime = set()   # 입력기를 떼어 둔 창 (입력칸이 아닌 곳)
        if sys.platform != "win32":
            return
        try:
            import ctypes
            import ctypes.wintypes as wt
            self._ctypes = ctypes
            self._user32 = ctypes.windll.user32
            self._imm = ctypes.windll.imm32
            self._user32.GetFocus.restype = wt.HWND
            self._user32.IsWindow.argtypes = [wt.HWND]
            self._user32.SetWindowLongPtrW.restype = ctypes.c_void_p
            self._user32.SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_void_p]
            self._lresult = ctypes.c_ssize_t
            self._user32.CallWindowProcW.restype = self._lresult
            self._user32.CallWindowProcW.argtypes = [
                ctypes.c_void_p, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
            self._WNDPROC = ctypes.WINFUNCTYPE(self._lresult, wt.HWND, wt.UINT,
                                               wt.WPARAM, wt.LPARAM)
            self._imm.ImmGetContext.restype = ctypes.c_void_p
            self._imm.ImmGetContext.argtypes = [wt.HWND]
            self._imm.ImmReleaseContext.argtypes = [wt.HWND, ctypes.c_void_p]
            self._imm.ImmGetCompositionStringW.argtypes = [
                ctypes.c_void_p, wt.DWORD, ctypes.c_void_p, wt.DWORD]

            class _CompositionForm(ctypes.Structure):
                _fields_ = [("dwStyle", wt.DWORD), ("ptCurrentPos", wt.POINT),
                            ("rcArea", wt.RECT)]
            self._CompositionForm = _CompositionForm
            self._imm.ImmSetCompositionWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            self._imm.ImmAssociateContextEx.argtypes = [wt.HWND, ctypes.c_void_p, wt.DWORD]
        except Exception:
            return
        root.after(self.POLL_MS, self._poll)

    # ── IME 기본 조합창(흰 상자) 숨기기 ──────────────────
    def _push_ime_window_offscreen(self, hwnd):
        himc = self._imm.ImmGetContext(hwnd)
        if not himc:
            return
        try:
            form = self._CompositionForm()
            form.dwStyle = _CFS_POINT
            form.ptCurrentPos.x = form.ptCurrentPos.y = _OFFSCREEN
            self._imm.ImmSetCompositionWindow(himc, self._ctypes.byref(form))
        finally:
            self._imm.ImmReleaseContext(hwnd, himc)

    def _hook(self, hwnd):
        """창 메시지를 가로채, Tk가 IME 메시지를 처리한 직후 조합창을 화면 밖으로 옮긴다."""
        if hwnd in self._hooked:
            return
        holder = {}

        def proc(h, msg, wp, lp):
            res = self._user32.CallWindowProcW(holder["orig"], h, msg, wp, lp)
            if msg in (_WM_IME_STARTCOMPOSITION, _WM_IME_COMPOSITION):
                try:
                    self._push_ime_window_offscreen(h)
                except Exception:
                    pass
            return res

        cb = self._WNDPROC(proc)
        holder["orig"] = self._user32.SetWindowLongPtrW(
            hwnd, _GWLP_WNDPROC, self._ctypes.cast(cb, self._ctypes.c_void_p))
        if holder["orig"]:
            self._hooked[hwnd] = (cb, holder["orig"])

    def unhook_all(self):
        """앱 종료 전에 원래 창 프로시저로 되돌린다 (종료 중 콜백 호출 방지)."""
        for hwnd, (_cb, orig) in list(self._hooked.items()):
            try:
                if self._user32.IsWindow(hwnd):
                    self._user32.SetWindowLongPtrW(hwnd, _GWLP_WNDPROC, orig)
            except Exception:
                pass
        self._hooked.clear()

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
            hwnd = self._user32.GetFocus()
            if hwnd:
                self._hook(hwnd)
                if not isinstance(widget, tk.Entry) and hwnd not in self._no_ime:
                    # 입력칸이 아닌 곳에서는 입력기를 떼어, 한글 상태여도 S·A·M 같은 단축키가 바로 동작
                    self._imm.ImmAssociateContextEx(hwnd, None, 0)
                    self._no_ime.add(hwnd)
            text = self._composition() if isinstance(widget, tk.Entry) else ""
            if text:
                self._push_ime_window_offscreen(hwnd)
                self._replace_selection(widget)
                self._show(widget, text)
            else:
                self._hide()
        except Exception:
            self._hide()
        try:
            self.root.after(self.POLL_MS, self._poll)
        except tk.TclError:   # 앱 종료
            pass

    @staticmethod
    def _replace_selection(entry):
        """조합이 시작되면 선택된 글자를 지운다 (Tk는 조합이 끝나야 지워서 글자가 겹쳐 보임)."""
        if entry.selection_present():
            first = entry.index("sel.first")
            entry.delete("sel.first", "sel.last")
            entry.icursor(first)

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
        """커서 위치 (x, y, 높이). Entry.bbox()가 0을 주는 환경이 있어 글자 폭으로 계산."""
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
