"""앱 스타일 팝업. tkinter.messagebox와 같은 이름·인자라 `from .. import dialogs as messagebox`로 바꿔 쓴다."""
from .widgets import ask_buttons


def showinfo(title=None, message=None, parent=None, **kw):
    ask_buttons(parent, title, message, [("확인", "ok")], kind="info", default="ok")
    return "ok"


def showwarning(title=None, message=None, parent=None, **kw):
    ask_buttons(parent, title, message, [("확인", "ok")], kind="warning", default="ok")
    return "ok"


def showerror(title=None, message=None, parent=None, **kw):
    ask_buttons(parent, title, message, [("확인", "ok")], kind="error", default="ok")
    return "ok"


def askyesno(title=None, message=None, parent=None, yes="예", no="아니오", **kw):
    return bool(ask_buttons(parent, title, message, [(no, False), (yes, True)], kind="question", default=False))


def askokcancel(title=None, message=None, parent=None, ok="확인", cancel="취소", **kw):
    return bool(ask_buttons(parent, title, message, [(cancel, False), (ok, True)], kind="question", default=False))


def askyesnocancel(title=None, message=None, parent=None, yes="예", no="아니오", cancel="취소", **kw):
    """예 → True, 아니오 → False, 취소·닫기 → None."""
    return ask_buttons(parent, title, message, [(cancel, None), (no, False), (yes, True)], kind="question")
