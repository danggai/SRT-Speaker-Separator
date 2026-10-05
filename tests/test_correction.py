"""자막 교정 창: 제안 표시·적용·실행 취소, 음성으로 다시 확인."""
from harness import ctx, eq, expect, find, flat, load_sample, press, pump, test, toplevels, wait_until

TEXTS = ["루파가 왔어요", "루파는 어디 갔어요", "루파한테 말했는데", "루파가 웃었어요",
         "루팍이 먼저 갔어요", "그래서 루파도 같이", "오늘은 루파가 이겼어요"]


def _open(app):
    load_sample(app, n=12, with_wav=True)
    for i, t in enumerate(TEXTS):
        app.subtitles[i]["text"] = t
    app._proper_nouns = ["루파"]   # 고유명사 사전 기준으로 찾음
    app._open_correction_dialog()
    app._proper_nouns = []
    pump(0.5)
    wins = [w for w in toplevels() if w.title() == "자막 교정"]
    expect(wins, f"교정 창이 떠야 해요: {ctx.msgs}")
    return wins[0]


@test
def correction_dialog_applies_selected_fix_with_undo(app):
    win = _open(app)
    titles = [w.cget("text") for w in find(win, "Label") if "교정 제안" in str(w.cget("text"))]
    expect(titles and "1건" in titles[0], f"제안 1건: {titles}")
    press(flat(win, "선택한 줄 고치기"))
    pump(0.3)
    eq(app.subtitles[4]["text"], "루파가 먼저 갔어요", "조사까지 맞춰 고침")
    eq([s["text"] for s in app.subtitles[:7] if "루팍" in s["text"]], [], "다른 줄은 그대로")
    expect(any("1개 자막을 고쳤어요" in (m[2] or "") for m in ctx.msgs), "완료 안내")
    app._undo()
    eq(app.subtitles[4]["text"], "루팍이 먼저 갔어요", "실행 취소")


@test
def correction_audio_check_uses_ai_job_and_hides_wrong(app):
    from srt_editor import ai_runtime
    jobs = []

    def fake(job, on_event=None, cancelled=None):
        jobs.append(job)
        if on_event:
            on_event({"type": "status", "msg": "음성 확인 중…  1 / 1"})
        return {"results": ["wrong"]}
    orig = ai_runtime.ai_python
    ai_runtime.ai_python = lambda: "python"
    app._run_ai_job = fake
    try:
        win = _open(app)
        press(flat(win, "음성으로 다시 확인"))
        wait_until(lambda: any("음성 확인 완료" in str(w.cget("text")) for w in find(win, "Label")), 5,
                   "음성 확인 결과")
        eq(jobs[0]["type"], "verify")
        eq(jobs[0]["items"][0][2:], ("루팍", "루파"), "고칠 표기·바른 표기를 넘김")
        expect(any("교정 제안 0건" in str(w.cget("text")) for w in find(win, "Label")),
               "원래 표기가 맞다고 들리면 제안을 숨김")
    finally:
        ai_runtime.ai_python = orig
        del app._run_ai_job
