"""이름 검수: 비슷하게 인식된 이름 묶기와 고른 표기로 한 번에 바꾸기."""
from harness import steps, eq, expect, fresh_dir, pump, test, toplevels, wait_until, write_srt_file

TEXTS = ["아 고우백 씨 왔어요", "공우백씨 어디 가요", "공우백 씨!", "복순아 밥 먹자", "복순씨 안녕", "복순씨가 왔어",
         "옥순씨 네", "봉마랑 씨, 안녕하세요", "병원장님 오셨다", "그냥 평범한 줄", "고우백씨는 몰라"]


def groups_only_honorific_names_and_safe_default():
    from srt_editor import name_review as nr
    gs = {frozenset(w for w, _ in g.variants): g for g in nr.find_groups(TEXTS)}
    expect(frozenset({"공우백", "고우백"}) in gs, f"호칭이 붙은 비슷한 이름끼리 묶음 {list(gs)}")
    eq(gs[frozenset({"복순", "옥순"})].default, "복순", "확실히 많은 표기는 미리 고름")
    eq(gs[frozenset({"공우백", "고우백"})].default, "", "비슷한 횟수면 그대로 둠")
    g = next(g for g in nr.find_groups(TEXTS, ["봉마당"]) if any(w == "봉마랑" for w, _ in g.variants))
    eq(g.default, "봉마당", "사전에 있는 이름은 자막에 없어도 정답으로")
    eq(nr.apply(["아 봉마랑 씨, 안녕", "고우백씨가 왔어", "고우백이랑"], {"봉마랑": "봉마당", "고우백": "고무백"}),
       ["아 봉마당 씨, 안녕", "고무백씨가 왔어", "고무백이랑"], "조사·호칭은 그대로")


def review_dialog_applies_choice_with_one_undo(app):
    from srt_editor.srt_io import format_srt_time
    d = fresh_dir()
    srt = d / "이름.srt"
    srt.write_text("\n".join(f"{i}\n{format_srt_time(i * 2)} --> {format_srt_time(i * 2 + 1.5)}\n{t}\n"
                             for i, t in enumerate(TEXTS, 1)), encoding="utf-8")
    app._open_paths([str(srt)])
    wait_until(lambda: len(app.subtitles) == len(TEXTS), 10)
    app.after(50, app._open_name_review)
    wait_until(lambda: any(w.title() == "이름 검수" for w in toplevels()), 5)
    win = next(w for w in toplevels() if w.title() == "이름 검수")
    from harness import find
    ents = find(win, "Entry")
    expect(ents, "직접 입력 칸")
    # 공우백 묶음(첫 직접 입력 칸 중 해당 카드)에 '고무백' 입력
    card = next(e for e in ents if "공우백" in " ".join(
        w.cget("text") for w in e.master.winfo_children() if hasattr(w, "cget") and w.winfo_class() == "Label"))
    card.insert(0, "고무백")
    pump(0.05)
    btn = next(b for b in find(win, "FlatButton") if b.itemcget("label", "text") == "고른 대로 바꾸기")
    btn.event_generate("<ButtonRelease-1>", x=4, y=4)
    pump(0.2)
    texts = [s["text"] for s in app.subtitles]
    expect("아 고무백 씨 왔어요" in texts and "고무백씨 어디 가요" in texts and "고무백씨는 몰라" in texts, texts)
    expect("옥순씨 네" not in texts and "복순씨 네" in texts, "미리 골라 둔 묶음도 적용")
    expect("고무백" in app._proper_nouns, "고른 이름을 사전에 넣음")
    app._undo()
    eq([s["text"] for s in app.subtitles], TEXTS, "실행 취소 한 번에 되돌림")
    app._unsaved = False


@test
def name_review(app):
    steps(groups_only_honorific_names_and_safe_default, review_dialog_applies_choice_with_one_undo)
