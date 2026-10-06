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
def first_run_of_unwarmed_install_shows_notice_once():
    import pathlib
    R = _rt()
    orig = R._venv_python
    R._venv_python = lambda: pathlib.Path(sys.executable)
    R.ROOT.mkdir(parents=True, exist_ok=True)
    (R.ROOT / "ready.json").write_text(json.dumps({"device": "cpu"}), encoding="utf-8")
    try:
        ev1, ev2 = [], []
        R.run_job({"type": "echo"}, on_event=ev1.append, python=sys.executable)
        expect(ev1[0]["msg"].startswith("첫 실행 준비"), f"예열 전 첫 실행 안내: {ev1[:1]}")
        expect(R.installed_info().get("warm"), "성공하면 예열됨으로 기록")
        R.run_job({"type": "echo"}, on_event=ev2.append, python=sys.executable)
        expect(not any("첫 실행" in (e.get("msg") or "") for e in ev2), "두 번째부터는 안내 없음")
    finally:
        R._venv_python = orig
        R.uninstall()


@test
def line_embedding_cache_reuses_unchanged_lines():
    import numpy as np
    from harness import fresh_dir
    from srt_editor import ai_worker as W
    import line_speakers as LS   # 작업 실행기가 불러 쓰는 같은 모듈
    d = fresh_dir()
    media = d / "a.wav"
    media.write_bytes(b"x")
    calls = []

    def fake_emb(model, audio, intervals, cancelled=None):
        calls.append(len(intervals))
        return np.array([[s, e, 1.0] for s, e in intervals], dtype=np.float32)

    class FakeWX:
        @staticmethod
        def load_audio(path):
            return np.zeros(10)

    class FakePipe:
        class model:
            _embedding = object()
    saved = (LS.line_embeddings, W._diar_pipeline, W.status, W._campplus, LS.combine_embeddings,
             sys.modules.get("whisperx"))
    LS.line_embeddings = fake_emb
    W._diar_pipeline = lambda *a, **k: FakePipe
    W.status = lambda *a, **k: None
    W._campplus = lambda device: (lambda wav: None)   # 두 번째 목소리 모델 흉내
    dims = []
    LS.combine_embeddings = lambda xs: (dims.append([x.shape[1] for x in xs]), saved[4](xs))[1]
    sys.modules["whisperx"] = FakeWX
    try:
        job = {"media": str(media), "cache_dir": str(d / "cache"), "num_speakers": 2, "exact": True,
               "intervals": [[0, 1], [1, 2], [2, 3], [3, 4], None]}
        W._lines_result(job, "cpu")
        eq(dims[-1], [3, 3], "두 모델 특징을 섞음")
        W._lines_result(job, "cpu")
        eq(calls, [4, 4], "두 번째는 두 모델 모두 캐시 (구간 없는 줄은 제외)")
        job["intervals"][1] = [1, 2.5]
        W._lines_result(job, "cpu")
        eq(calls, [4, 4, 1, 1], "바뀐 줄만 새로 분석")
        W._campplus = lambda device: None   # 두 번째 모델 부품이 없으면
        job["cache_dir"] = str(d / "cache2")
        W._lines_result(job, "cpu")
        eq(dims[-1], [3], "첫 모델만으로 분석")
    finally:
        LS.line_embeddings, W._diar_pipeline, W.status, W._campplus, LS.combine_embeddings = saved[:5]
        if saved[5] is None:
            sys.modules.pop("whisperx", None)
        else:
            sys.modules["whisperx"] = saved[5]


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
