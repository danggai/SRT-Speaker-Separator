"""회귀 테스트 공통 도구: 격리된 앱 실행, 샘플 데이터 만들기, 클릭·키 입력 흉내, 결과 집계."""
import gc
import json
import math
import os
import pathlib
import queue
import sys
import tempfile
import threading
import time
import traceback
import wave

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REGISTRY = []   # (이름, 함수)


class Skip(Exception):
    """조건이 안 맞아 건너뛰는 테스트."""


def test(fn):
    """테스트 등록. 함수가 `app` 인자를 받으면 초기화된 앱이 넘어온다."""
    mod = fn.__module__.split(".")[-1].removeprefix("test_")
    REGISTRY.append((f"{mod}.{fn.__name__}", fn))
    return fn


def expect(cond, msg="조건이 거짓이에요"):
    if not cond:
        raise AssertionError(msg)


def eq(actual, expected, what=""):
    if actual != expected:
        raise AssertionError(f"{what + ': ' if what else ''}기대 {expected!r}, 실제 {actual!r}")


def near(actual, expected, tol=1e-6, what=""):
    if abs(actual - expected) > tol:
        raise AssertionError(f"{what + ': ' if what else ''}기대 {expected}, 실제 {actual} (허용 {tol})")


class _Ctx:
    """테스트 전체가 공유하는 상태."""
    work = None          # 임시 작업 폴더
    cfg_path = None      # 임시 설정 파일
    app = None
    msgs = []            # (종류, 제목, 내용): 메시지 상자 호출 기록
    answers = {}         # 종류 → 응답 값 또는 함수 (기본: 확인/예)
    paths = []           # 파일·폴더 선택 창이 돌려줄 경로 대기열
    tk_errors = []       # 처리되지 않은 Tk 콜백 오류


ctx = _Ctx()
SEED = {"tutorial_seen": True, "update_check": False, "volume": 80}


# ───────── 격리 환경 ─────────
def setup():
    """실제 설정·백업·모델 캐시를 건드리지 않도록 임시 폴더로 돌린다."""
    import tkinter.filedialog as fd
    import tkinter.messagebox as mb

    os.environ["SDL_AUDIODRIVER"] = "dummy"   # 재생 테스트가 실제 스피커로 소리를 내지 않게
    ctx.work = pathlib.Path(tempfile.mkdtemp(prefix="srt_reg_"))
    ctx.cfg_path = ctx.work / "config.json"
    os.environ["HF_HOME"] = str(ctx.work / "hf")
    write_config({})

    import srt_editor.config as cfgmod
    cfgmod._CONFIG_CANDIDATES[:] = [ctx.cfg_path]
    cfgmod._CONFIG_PATH = ctx.cfg_path
    import srt_editor.ui.options as optmod
    optmod.BACKUP_DIR = ctx.work / "backup"
    ctx.offer_backup_restore = optmod.OptionsMixin._offer_backup_restore   # 백업 복구 테스트에서 직접 호출
    optmod.OptionsMixin._offer_backup_restore = lambda self: None
    import srt_editor.waveform as wf
    wf.CACHE_DIR = ctx.work / "wavecache"
    import srt_editor.ai_runtime as air
    air.ROOT = ctx.work / "ai"

    def _rec(kind, default):
        def fn(title=None, message=None, **kw):
            ctx.msgs.append((kind, title, message))
            ans = ctx.answers.get(kind, default)
            return ans() if callable(ans) else ans
        return fn
    import srt_editor.dialogs as dlg
    for kind, default in (("showinfo", "ok"), ("showwarning", "ok"), ("showerror", "ok"),
                          ("askyesno", True), ("askokcancel", True), ("askyesnocancel", True)):
        setattr(mb, kind, _rec(kind, default))
        setattr(dlg, kind, _rec(kind, default))   # 앱 스타일 팝업 (실제 창을 띄우면 테스트가 멈춤)

    import srt_editor.widgets as widgets
    import srt_editor.ui.diarize as dz
    ask = _rec("ask_choice", True)
    widgets.ask_choice = dz.ask_choice = lambda parent, title, message, primary, secondary: ask(title, message)

    def _path(**kw):
        return ctx.paths.pop(0) if ctx.paths else ""
    for name in ("askopenfilename", "asksaveasfilename", "askdirectory"):
        setattr(fd, name, _path)
    _install_thread_after()
    gc.disable()   # 스레드에서 도는 GC가 Tk 변수를 지우다 mainloop 없이 멈추므로, 메인 스레드(pump)에서만 돌림


_pending = queue.Queue()
_orig_after = None


def _install_thread_after():
    """백그라운드 스레드가 부른 after()를 큐에 모았다가 메인 스레드(pump)에서 실행한다.
    앱은 실제로는 mainloop가 이걸 해 주지만, 테스트는 update()로 직접 돌려서 따로 필요하다."""
    global _orig_after
    import tkinter as tk
    if _orig_after is not None:
        return
    _orig_after = tk.Misc.after

    def after(self, ms, func=None, *args):
        if threading.current_thread() is threading.main_thread():
            return _orig_after(self, ms, func, *args)
        _stats["queued"] += 1
        _pending.put((self, ms, func, args))
    tk.Misc.after = after


_stats = {"queued": 0, "drained": 0, "failed": 0, "last_error": ""}


def _drain_pending():
    while True:
        try:
            widget, ms, func, args = _pending.get_nowait()
        except queue.Empty:
            return
        try:
            _orig_after(widget, ms, func, *args)
            _stats["drained"] += 1
        except Exception as e:   # 그 사이 창이 닫힘
            _stats["failed"] += 1
            _stats["last_error"] = f"{type(e).__name__}: {e}"


def write_config(extra):
    cfg = dict(SEED)
    cfg.update(extra)
    ctx.cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")


def cfg():
    return json.loads(ctx.cfg_path.read_text(encoding="utf-8"))


def make_app():
    from srt_editor.app import SRTEditor
    app = SRTEditor()
    app._check_update_async = lambda: None
    app.geometry("1280x800+20+20")
    app.report_callback_exception = lambda *a: ctx.tk_errors.append(
        "".join(traceback.format_exception(*a))[-700:])
    ctx.app = app
    pump(0.5)
    return app


def new_app():
    """앱을 완전히 닫고 새로 만든다 (종료·시작 시나리오용)."""
    import tkinter as tk
    if ctx.app is not None:
        try:
            ctx.app.player.stop()
            ctx.app.destroy()
        except Exception:
            pass
    tk._default_root = None
    import srt_editor.widgets as widgets
    widgets._IMG_CACHE.clear()   # 이전 Tk 인터프리터에 묶인 이미지
    return make_app()


def reset_app():
    """테스트 사이에 앱을 처음 상태로 되돌린다."""
    import tkinter as tk
    from srt_editor.widgets import PopupMenu
    app = ctx.app
    try:
        app.winfo_exists()
    except tk.TclError:   # 앞 테스트가 앱을 닫았음
        app = new_app()
    ctx.msgs.clear()
    ctx.answers.clear()
    ctx.paths.clear()
    if PopupMenu._active is not None:
        try:
            PopupMenu._active._destroy()
        except Exception:
            pass
    for w in list(app.winfo_children()):
        if isinstance(w, tk.Toplevel):
            w.destroy()
    pump(0.05)
    write_config({})
    app.__dict__["_opt_cache"] = {}
    app._global_speaker_colors = {}
    app._unsaved = False
    try:
        if app.subtitles or app.media_path:
            app._close_to_home()
    except Exception:   # 앞 테스트가 앱 상태를 망가뜨렸으면 새로 만든다
        app = new_app()
        write_config({})
    app._unsaved = False
    app._undo_stack, app._redo_stack = [], []
    app._clipboard = []
    app._auto_kept = {}
    app._col_w = dict(app._COL_DEF_W)
    app.canvas.event_generate("<Leave>")   # 앞 테스트가 남긴 '마우스 아래 항목' 제거
    app._auto_color_cache = None
    app._selection_anchor = None
    app._set_volume(80, save=False)
    for name in ("_search_hits",):
        setattr(app, name, [])
    try:
        app._search_var.set("")
        app._close_search()
    except Exception:
        pass
    app.geometry("1280x800+20+20")
    app.focus_set()
    ctx.tk_errors.clear()
    pump(0.1)


# ───────── 기다리기·찾기 ─────────
def pump(sec=0.2):
    app = ctx.app
    end = time.time() + sec
    gc.collect(0)
    while time.time() < end:
        _drain_pending()
        app.update()
        time.sleep(0.01)


def wait_until(cond, timeout=10.0, what=""):
    """cond()가 참이 될 때까지 기다린다. what은 문자열 또는 '지금 상태'를 돌려주는 함수 (실패 메시지에 붙음)."""
    end = time.time() + timeout
    while time.time() < end:
        pump(0.05)
        if cond():
            return True
    state = what() if callable(what) else what
    raise AssertionError(f"시간 안에 조건이 안 맞았어요: {state}")


def walk(w):
    yield w
    for c in w.winfo_children():
        yield from walk(c)


def toplevels():
    import tkinter as tk
    return [w for w in ctx.app.winfo_children() if isinstance(w, tk.Toplevel)]


def find(root, cls=None, text=None):
    import tkinter as tk
    out = []
    for w in walk(root):
        if cls and type(w).__name__ != cls:
            continue
        if text is not None:
            try:
                t = w.itemcget("label", "text") if type(w).__name__ == "FlatButton" else w.cget("text")
            except tk.TclError:
                continue
            if t != text:
                continue
        out.append(w)
    return out


def flat(root, text):
    r = find(root, "FlatButton", text)
    expect(r, f"'{text}' 버튼을 못 찾았어요")
    return r[0]


# ───────── 입력 흉내 ─────────
def tap(w, x=6, y=6, wait=0.12):
    """실제 클릭처럼 누르고 뗀다 (누르기만 하면 Tk가 그 창을 '눌린 채'로 보고 이후 뗌을 가로챔)."""
    w.event_generate("<Enter>")
    w.event_generate("<ButtonPress-1>", x=x, y=y)
    w.event_generate("<ButtonRelease-1>", x=x, y=y)
    pump(wait)


def press(btn):
    tap(btn, 4, 4)


def key(widget, seq, wait=0.1):
    """키 이벤트는 포커스가 있는 창에만 가므로 포커스를 준 뒤 보낸다."""
    for _ in range(5):
        widget.focus_force()
        pump(0.05)
        if widget.focus_get() is widget:
            break
    widget.event_generate(seq)
    pump(wait)


def app_key(seq, wait=0.1):
    """앱 전역 단축키 (입력칸 밖에서)."""
    ctx.app.focus_force()
    ctx.app.focus_set()
    pump(0.05)
    ctx.app.event_generate(seq)
    pump(wait)


def seg_click(root, text):
    for sg in find(root, "Segmented"):
        for cv in sg.winfo_children():
            if cv.itemcget("label", "text") == text:
                tap(cv, 6, 6, 0.25)
                return True
    raise AssertionError(f"선택 버튼 '{text}'을 못 찾았어요")


class Ev:
    """위젯 핸들러를 직접 부를 때 쓰는 가짜 이벤트."""

    def __init__(self, widget, x, y, state=0):
        self.widget, self.x, self.y, self.state = widget, x, y, state
        self.x_root = widget.winfo_rootx() + x
        self.y_root = widget.winfo_rooty() + y
        self.delta = 0


def col_x(app, cid, off=20):
    return app._get_col_positions()[cid][0] + off


def slot_of(app, di):
    """자막 di를 보여 주는 화면 슬롯 번호 (안 보이면 None)."""
    return app._slot_data.index(di) if di in app._slot_data else None


def click_row(app, di, col="num", ctrl=False, shift=False):
    """자막 목록의 di번째 줄을 클릭 (화면에 보이도록 먼저 스크롤)."""
    app._scroll_to_row(di)
    pump(0.05)
    s = slot_of(app, di)
    expect(s is not None, f"{di}번 줄이 화면에 안 보여요")
    c = app.canvas
    y = s * app.ROW_H + app.ROW_H // 2 - int(c.canvasy(0))
    state = (0x4 if ctrl else 0) | (0x1 if shift else 0)
    if shift:
        app._canvas_shift_press(Ev(c, col_x(app, col), y, state))
    else:
        app._canvas_press(Ev(c, col_x(app, col), y, state))
        app._canvas_drag_end(Ev(c, col_x(app, col), y))
    pump(0.1)


# ───────── 샘플 데이터 ─────────
NAMES = ["민지", "준호"]
TEXTS = ["안녕하세요 오늘 회의를 시작할게요", "네 자료 띄워 놓을게요", "먼저 지난주 결과부터 볼까요", "방문자가 20% 늘었어요",
         "생각보다 많이 늘었네요", "이벤트 효과가 컸던 것 같아요", "다음 달에도 한 번 더 하죠", "좋아요 일정 잡아 볼게요",
         "그럼 오늘은 여기까지 할까요", "네 수고하셨습니다", "잠깐만요 질문이 있어요", "어떤 부분이 궁금하세요",
         "예산은 어떻게 되나요", "지난번과 같아요", "알겠습니다 정리해서 보낼게요", "감사합니다",
         "마지막으로 확인할 게 있어요", "말씀하세요", "일정이 바뀌면 알려 주세요", "물론이죠",
         "그럼 다음 주에 뵙겠습니다", "네 조심히 가세요", "오늘 고생 많았어요", "내일 봬요"]


def ts(sec):
    """초 → 'HH:MM:SS,mmm' (테스트용 독립 구현)."""
    total = int(round(sec * 1000))
    h, rem = divmod(total, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def sample_subs(n=24, tagged_every=1):
    """2.5초 간격, 길이 2초인 자막 n개. 화자는 번갈아 지정 (tagged_every=0이면 모두 미지정)."""
    subs = []
    for i in range(n):
        spk = NAMES[i % 2] if tagged_every and i % tagged_every == 0 else ""
        subs.append({"timestamp": f"{ts(i * 2.5)} --> {ts(i * 2.5 + 2.0)}",
                     "text": TEXTS[i % len(TEXTS)], "speaker": spk})
    return subs


def write_srt_file(path, subs, tagged=True, newline="\n", bom=False, meta=None):
    lines = []
    for i, s in enumerate(subs, 1):
        lines += [str(i), s["timestamp"], f"[{s['speaker']}] {s['text']}" if tagged and s["speaker"] else s["text"], ""]
    if meta:
        lines.append(f"; SRT_META {json.dumps(meta, ensure_ascii=False)}")
    data = newline.join(lines)
    pathlib.Path(path).write_bytes((b"\xef\xbb\xbf" if bom else b"") + data.encode("utf-8"))
    return pathlib.Path(path)


def write_wav(path, seconds=40, rate=16000):
    """소리 크기가 오르내리는 사인파 WAV."""
    n = rate * seconds
    frames = bytearray()
    for i in range(n):
        env = 0.2 + 0.7 * abs(math.sin(i / rate * 1.3))
        v = int(32767 * 0.8 * env * math.sin(2 * math.pi * 220 * i / rate))
        frames += v.to_bytes(2, "little", signed=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    return pathlib.Path(path)


_counter = [0]


def fresh_dir():
    _counter[0] += 1
    d = ctx.work / f"case{_counter[0]}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_sample(app, n=24, with_wav=False, tagged_every=1, name="sample"):
    """샘플 자막(과 소리)을 열고 화면이 준비될 때까지 기다린다. 경로를 돌려준다."""
    d = fresh_dir()
    srt = write_srt_file(d / f"{name}.srt", sample_subs(n, tagged_every))
    paths = {"dir": d, "srt": srt}
    if with_wav:
        paths["wav"] = write_wav(d / f"{name}.wav")
    app._open_paths([str(srt)] + ([str(paths["wav"])] if with_wav else []))
    wait_until(lambda: len(app.subtitles) == n and app._slot_data and app._slot_data[0] == 0, 5, "자막 열기")
    pump(0.2)
    return paths


# ───────── 실행 ─────────
def run_all(only=None, verbose=False, out=print):
    import inspect
    import srt_editor  # noqa: F401  (경로 확인용)
    results = []
    selected = [(n, f) for n, f in REGISTRY if not only or any(o in n for o in only)]
    started = time.time()
    for name, fn in selected:
        needs_app = "app" in inspect.signature(fn).parameters
        err, skip = None, None
        t0 = time.time()
        try:
            if needs_app:
                if ctx.app is None:
                    make_app()
                reset_app()
            before = len(ctx.tk_errors)
            fn(ctx.app) if needs_app else fn()
            if needs_app and len(ctx.tk_errors) > before:
                raise AssertionError("처리되지 않은 Tk 오류가 났어요:\n" + ctx.tk_errors[before])
        except Skip as e:
            skip = str(e)
        except BaseException as e:   # noqa: BLE001
            tb = traceback.extract_tb(e.__traceback__)
            where = next((f"{pathlib.Path(f.filename).name}:{f.lineno}" for f in reversed(tb)
                          if pathlib.Path(f.filename).name.startswith("test_")), "?")
            err = f"{type(e).__name__}: {e}  ({where})"
            if not isinstance(e, AssertionError):
                err += "\n" + "".join(traceback.format_exception(e))[-900:]
        dt = time.time() - t0
        results.append((name, err, skip, dt))
        if err:
            out(f"[실패] {name}  ({dt:.1f}초)\n       {err}")
        elif skip:
            out(f"[건너뜀] {name}: {skip}")
        elif verbose:
            out(f"[통과] {name}  ({dt:.1f}초)")
    failed = [r for r in results if r[1]]
    skipped = [r for r in results if r[2]]
    passed = len(results) - len(failed) - len(skipped)
    out(f"\n합계: {len(results)}개 중 통과 {passed}, 실패 {len(failed)}, 건너뜀 {len(skipped)}  "
        f"(소요 {time.time() - started:.0f}초)")
    if failed:
        out("실패한 테스트: " + ", ".join(r[0] for r in failed))
    return 1 if failed else 0
