"""Windows 한글 IME 조합 중 글자를 입력칸에 임시로 넣어 표시 (Tk 8.6 미지원 보완), IME 기본 조합창은 화면 밖으로.
입력칸이 아닌 곳에서는 IME를 떼어 한글 상태에서도 단축키가 동작하게 한다."""
import sys
import tkinter as tk

_WM_IME_STARTCOMPOSITION = 0x010D
_WM_IME_COMPOSITION = 0x010F
_WM_IME_SETCONTEXT = 0x0281
_ISC_SHOWUICOMPOSITIONWINDOW = 0x80000000
_GWLP_WNDPROC = -4
_CFS_POINT = 0x0002
_OFFSCREEN = -32000
_IACE_DEFAULT = 0x10
_PRE_TAG = "ImePreBefore"    # 입력칸 기본 동작 전
_POST_TAG = "ImePreAfter"    # 입력칸 기본 동작 후


class ImeCompositionOverlay:
    POLL_MS = 15
    GCS_COMPSTR = 0x8

    def __init__(self, root):
        self.root = root
        self._preview = None   # (입력칸, 임시로 넣은 조합 글자)
        self._hooked = {}   # hwnd → (콜백 객체, 원래 창 프로시저)
        self._no_ime = set()   # 입력기를 떼어 둔 창 (입력칸이 아닌 곳)
        if sys.platform != "win32":
            return
        # 글자가 확정돼 들어가기 전에 임시 글자를 빼고, 들어간 뒤 바로 다시 채움
        root.bind_class(_PRE_TAG, "<KeyPress>", lambda e: self._clear_preview())
        root.bind_class(_PRE_TAG, "<FocusOut>", lambda e: self._clear_preview())
        root.bind_class(_POST_TAG, "<KeyPress>", lambda e: self._sync_preview())
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
            if msg == _WM_IME_SETCONTEXT and lp:
                lp &= ~_ISC_SHOWUICOMPOSITIONWINDOW   # 입력기 기본 조합창 그리지 않음
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
                is_entry = isinstance(widget, (tk.Entry, tk.Text))
                if not is_entry and hwnd not in self._no_ime:
                    # 입력칸이 아닌 곳에서는 입력기를 떼어, 한글 상태여도 S·A·M 같은 단축키가 바로 동작
                    self._imm.ImmAssociateContextEx(hwnd, None, 0)
                    self._no_ime.add(hwnd)
                elif is_entry and hwnd in self._no_ime:
                    # 입력칸으로 돌아오면 입력기 다시 연결
                    self._imm.ImmAssociateContextEx(hwnd, None, _IACE_DEFAULT)
                    self._no_ime.discard(hwnd)
            self._sync_preview(widget)
        except Exception:
            self._clear_preview()
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

    def _sync_preview(self, widget=None):
        """지금 조합 중인 글자를 입력칸에 맞춰 넣거나 뺀다."""
        if widget is None:
            try:
                widget = self.root.focus_get()
            except Exception:
                widget = None
        text = self._composition() if isinstance(widget, tk.Entry) else ""
        if not text:
            self._clear_preview()
            return
        try:
            hwnd = self._user32.GetFocus()
            if hwnd:
                self._push_ime_window_offscreen(hwnd)
        except Exception:
            pass
        if self._preview == (widget, text):
            return
        if self._preview is None:
            self._replace_selection(widget)
        self._set_preview(widget, text)

    def _set_preview(self, entry, text):
        """커서 자리에 조합 중인 글자를 넣는다 (커서는 그 뒤)."""
        self._clear_preview()
        tags = entry.bindtags()
        if _PRE_TAG not in tags:
            k = tags.index("Entry") + 1 if "Entry" in tags else len(tags)
            entry.bindtags((_PRE_TAG,) + tags[:k] + (_POST_TAG,) + tags[k:])
        entry.insert("insert", text)
        try:
            entry.tk.call("::tk::EntrySeeInsert", entry._w)
        except tk.TclError:
            pass
        self._preview = (entry, text)

    def _clear_preview(self):
        """임시로 넣은 조합 글자를 지운다."""
        if self._preview is None:
            return
        entry, text = self._preview
        self._preview = None
        try:
            pos = entry.index("insert")
            if pos >= len(text) and entry.get()[pos - len(text):pos] == text:
                entry.delete(pos - len(text), pos)
        except tk.TclError:   # 입력칸이 이미 사라짐
            pass
