"""AI 부품: 실행할 파이썬 고르기, 작업 실행기 주고받기, 설치 창·설정 카드."""
import json
import sys

from harness import ctx, eq, expect, find, pump, test, toplevels


def _rt():
    from srt_editor import ai_runtime
    return ai_runtime


@test
def ai_python_prefers_installed_runtime_then_dev_env():
    R = _rt()
    eq(R.installed_info(), None, "임시 폴더에는 설치돼 있지 않음")
    import importlib.util
    has_wx = importlib.util.find_spec("whisperx") is not None
    eq(R.ai_python(), sys.executable if has_wx else None, "개발 환경 whisperx가 있으면 지금 파이썬")
    (R.ROOT / "ready.json").parent.mkdir(parents=True, exist_ok=True)
    (R.ROOT / "ready.json").write_text(json.dumps({"device": "cpu", "cuda": False}), encoding="utf-8")
    try:
        eq(R.installed_info(), None, "가상 환경 파이썬이 없으면 설치 안 된 것으로 봄")
        py = R.ROOT / "venv" / "Scripts" / "python.exe"
        py.parent.mkdir(parents=True, exist_ok=True)
        py.write_bytes(b"")
        eq(R.installed_info()["device"], "cpu")
        eq(R.ai_python(), str(py), "설치한 AI 부품이 우선")
    finally:
        R.uninstall()


@test
def run_job_streams_events_and_returns_result():
    R = _rt()
    events = []
    res = R.run_job({"type": "echo", "value": [1, "가"]}, on_event=events.append, python=sys.executable)
    eq(res, {"echo": [1, "가"]})
    eq([e["msg"] for e in events if e.get("type") == "status"], ["단계 0", "단계 1", "단계 2"])
    expect((R.ROOT / "worker" / "ai_worker.py").exists(), "작업 실행기는 AI 폴더에 복사해서 실행")


@test
def run_job_reports_worker_error_and_missing_runtime():
    R = _rt()
    try:
        R.run_job({"type": "echo", "fail": "일부러 실패"}, python=sys.executable)
        raise AssertionError("오류가 나야 해요")
    except R.AIError as e:
        eq(str(e), "일부러 실패", "작업 실행기 오류 메시지를 그대로 전달")
    orig = R.ai_python
    R.ai_python = lambda: None
    try:
        R.run_job({"type": "echo"})
        raise AssertionError("AIMissing이 나야 해요")
    except R.AIMissing:
        pass
    finally:
        R.ai_python = orig


@test
def ensure_ai_opens_install_dialog_when_missing(app):
    R = _rt()
    orig = R.ai_python
    R.ai_python = lambda: None
    ran = []
    try:
        app._ensure_ai(lambda: ran.append(1))
        pump(0.4)
        wins = [w for w in toplevels() if w.title() == "AI 부품 설치"]
        expect(wins, "AI 부품 설치 창이 떠야 해요")
        eq(ran, [], "설치 전에는 작업을 시작하지 않음")
        expect(find(wins[0], "FlatButton", "설치 시작"), "설치 시작 버튼")
        wins[0].destroy()
        R.ai_python = lambda: "python"
        app._ensure_ai(lambda: ran.append(1))
        eq(ran, [1], "부품이 있으면 바로 실행")
    finally:
        R.ai_python = orig


@test
def settings_storage_shows_ai_card(app):
    app._open_settings(4)
    pump(0.5)
    win = [w for w in toplevels() if w.title() == "설정"][0]
    labels = [w.cget("text") for w in win.winfo_children() and __import__("harness").walk(win)
              if type(w).__name__ == "Label"]
    expect("AI 부품" in labels, "저장 공간에 AI 부품 카드가 있어야 해요")
    expect(any("설치 안 됨" in t or "개발 환경" in t for t in labels), f"상태 표시: {labels[:40]}")
    eq(ctx.tk_errors, [])


@test
def storage_delete_all_models_removes_every_cached_model(app):
    import os
    import pathlib
    from harness import flat
    hub = pathlib.Path(os.environ["HF_HOME"]) / "hub"
    expect(str(hub).startswith(str(ctx.work)), "테스트는 임시 모델 폴더만 써야 해요")
    for name in ("models--a--one", "models--b--two"):
        (hub / name).mkdir(parents=True, exist_ok=True)
        (hub / name / "w.bin").write_bytes(b"x" * 10)
    app._open_settings(4)
    pump(0.5)
    win = [w for w in toplevels() if w.title() == "설정"][0]
    from harness import press
    press(flat(win, "전체 삭제"))
    pump(0.3)
    expect(any(m[1] == "모델 전체 삭제" for m in ctx.msgs), "확인을 물어야 해요")
    eq([p.name for p in hub.iterdir()], [], "모두 지워짐")
