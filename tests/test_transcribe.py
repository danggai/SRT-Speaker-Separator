"""자동 자막: 인식 결과를 자막 줄로 나누기·다듬기와 불러오기."""
import os

from harness import ctx, eq, expect, fresh_dir, load_sample, test, wait_until


def _tp():
    from srt_editor import transcript_post
    return transcript_post


@test
def split_uses_word_times_and_interpolates_missing_ones():
    T = _tp()
    seg = {"start": 10.0, "end": 16.0, "text": "오늘은 새로 나온 게임을 같이 해 볼 거예요 정말 재밌을 것 같아요",
           "words": [{"word": "오늘은", "start": 10.0, "end": 10.5}, {"word": "새로", "start": 10.6, "end": 10.9},
                     {"word": "나온", "start": 11.0, "end": 11.3}, {"word": "게임을", "start": 11.4, "end": 11.9},
                     {"word": "같이", "start": 12.0, "end": 12.3}, {"word": "해"},   # 정렬 실패 단어
                     {"word": "볼", "start": 12.6, "end": 12.8}, {"word": "거예요", "start": 12.9, "end": 13.5},
                     {"word": "정말", "start": 14.0, "end": 14.4}, {"word": "재밌을", "start": 14.5, "end": 15.0},
                     {"word": "것", "start": 15.1, "end": 15.2}, {"word": "같아요", "start": 15.3, "end": 15.9}]}
    lines = T.split_segment(seg, 16)
    expect(len(lines) >= 2, f"나뉘어야 함: {lines}")
    eq(lines[0]["start"], 10.0, "첫 줄은 첫 단어 시작")
    eq(lines[-1]["end"], 15.9, "끝 줄은 마지막 단어 끝")
    for a, b in zip(lines, lines[1:]):
        expect(a["end"] <= b["start"] + 1e-6, f"줄끼리 겹치지 않음: {a} {b}")
        expect(a["end"] < 16.0, "단어 시간을 못 찾아도 문장 전체 시간을 받지 않음")


@test
def short_segment_splits_at_pause_or_sentence_end_but_keeps_tiny_pieces():
    T = _tp()
    seg = {"start": 0.0, "end": 4.0, "text": "아 그냥 딱 봤는데! 이쁘다 진짜",
           "words": [{"word": "아", "start": 0.0, "end": 0.2}, {"word": "그냥", "start": 0.6, "end": 0.9},
                     {"word": "딱", "start": 1.0, "end": 1.1}, {"word": "봤는데!", "start": 1.2, "end": 1.7},
                     {"word": "이쁘다", "start": 1.8, "end": 2.3}, {"word": "진짜", "start": 2.9, "end": 3.3}]}
    lines = T.build_lines([seg], 20)
    eq([l["text"] for l in lines], ["아 그냥 딱 봤는데!", "이쁘다 진짜"],
       "20자 안이어도 문장부호에서 나누고, 4자 미만 조각('아', '이쁘다')은 쉼이 있어도 붙여 둠")
    eq(lines[1]["start"], 1.8)
    seg2 = dict(seg, words=[dict(w) for w in seg["words"]])
    seg2["words"][4]["word"] = "정말이쁘다"
    eq([l["text"] for l in T.build_lines([seg2], 20)], ["아 그냥 딱 봤는데!", "정말이쁘다", "진짜"],
       "4자 이상이면 0.25초 넘는 쉼에서 나눔")


@test
def hallucinations_and_repeats_are_removed():
    T = _tp()
    segs = [{"start": 0, "end": 2, "text": "안녕하세요 여러분"},
            {"start": 3, "end": 5, "text": "시청해 주셔서 감사합니다."},
            {"start": 6, "end": 7, "text": "감사합니다"},
            {"start": 8, "end": 9, "text": "아 진짜"}, {"start": 9, "end": 10, "text": "아 진짜"},
            {"start": 10, "end": 11, "text": "아 진짜"}, {"start": 11, "end": 12, "text": "아 진짜"},
            {"start": 13, "end": 14, "text": "MBC 뉴스 김철수입니다"}]
    lines = T.build_lines(segs, 25)
    eq([l["text"] for l in lines], ["안녕하세요 여러분", "감사합니다", "아 진짜", "MBC 뉴스 김철수입니다"],
       "지어낸 문장은 빼고, 실제로 말할 법한 '감사합니다'와 긴 문장은 남김")
    eq((lines[2]["start"], lines[2]["end"]), (8, 12), "반복 줄은 하나로 합치고 시간은 이어 붙임")


@test
def timing_fix_removes_overlap_and_stretches_tiny_lines():
    T = _tp()
    lines = T.fix_timing([{"start": 0.0, "end": 2.5, "text": "a"}, {"start": 2.0, "end": 2.05, "text": "b"},
                          {"start": 5.0, "end": 6.0, "text": "c"}])
    eq([(l["start"], l["end"]) for l in lines], [(0.0, 2.0), (2.0, 2.3), (5.0, 6.0)])


@test
def period_option_adds_or_strips_whisper_period():
    T = _tp()
    eq(T.finish_text("안녕하세요.", False), "안녕하세요")
    eq(T.finish_text("진짜?", False), "진짜?")
    eq(T.finish_text("안녕하세요", True), "안녕하세요.")


@test
def toolbar_button_asks_before_replacing_and_opens_options(app):
    from harness import toplevels, pump
    load_sample(app, n=4, with_wav=True)
    ctx.answers["askyesno"] = False
    app._open_auto_transcribe()
    pump(0.2)
    eq([m[1] for m in ctx.msgs], ["자동 자막"], "있던 자막을 바꾸기 전에 물어봄")
    expect(not [w for w in toplevels() if w.title() == "자막 자동 생성"], "취소하면 창 안 뜸")
    ctx.answers["askyesno"] = True
    app._open_auto_transcribe()
    pump(0.3)
    expect([w for w in toplevels() if w.title() == "자막 자동 생성"], "확인하면 생성 창")


@test
def slide_opens_and_closes_sections_smoothly(app):
    import tkinter as tk
    import srt_editor.widgets as W
    from harness import pump
    win = tk.Toplevel(app)
    win.geometry("300x400+10+10")
    tk.Label(win, text="위").pack()
    box = tk.Frame(win)
    for k in range(4):
        tk.Label(box, text=f"줄 {k}").pack()
    tk.Label(win, text="아래").pack()
    pump(0.3)
    W.ANIMATE = True

    def overlay():
        return [w for w in win.winfo_children() if isinstance(w, tk.Canvas)]
    try:
        W.slide(box, True)
        expect(box.winfo_manager() == "pack", "실제 칸은 바로 펼친 상태로 배치")
        ov = overlay()
        expect(ov, "그림 덮개로 움직임")
        y1 = ov[0].coords("move")[1]
        pump(0.08)
        y2 = ov[0].coords("move")[1] if overlay() else None
        pump(0.4)
        expect(y2 is not None and y2 > y1 and not overlay(), f"아래 내용이 내려감 {y1} → {y2}, 끝나면 덮개 없음")
        W.slide(box, False)
        expect(box.winfo_manager() == "" and overlay(), "접을 때도 실제 칸은 바로 숨기고 그림으로 움직임")
        pump(0.4)
        expect(not overlay())
    finally:
        W.ANIMATE = False
        win.destroy()

@test
def narrow_window_hides_shortcut_buttons_and_restores_them(app):
    from harness import pump
    load_sample(app, n=4)
    names = lambda: [w.itemcget("label", "text") for w in app._tb_frame.pack_slaves() if hasattr(w, "set_on")]
    app.geometry("1280x800"); pump(0.5)
    expect("잘라내기" in names() and "다른 이름으로" in names(), names())
    app.geometry("900x700"); pump(0.5)
    expect(app._toolbar_need() <= app._tb_frame.winfo_width(), "좁아도 툴바가 넘치지 않음")
    expect("잘라내기" not in names() and "설정" in names() and "내보내기" in names(), names())
    app.geometry("1280x800"); pump(0.5)
    expect("잘라내기" in names() and "다른 이름으로" in names(), f"넓히면 되살아남: {names()}")
    order = names()
    expect(order.index("붙여넣기") < order.index("자동 자막") and order.index("저장") < order.index("다른 이름으로")
           < order.index("실행 취소"), f"원래 자리로: {order}")


@test
def auto_transcribe_loads_lines_and_removes_temp_file(app):
    import tempfile
    p = load_sample(app, n=4, with_wav=True)
    before = set(os.listdir(tempfile.gettempdir()))
    segs = [{"start": 0.5, "end": 2.0, "text": "안녕하세요 여러분."},
            {"start": 2.5, "end": 4.0, "text": "시청해주셔서 감사합니다"},
            {"start": 4.5, "end": 6.0, "text": "오늘 방송 시작할게요"}]
    app._run_ai_job = lambda job, on_event=None, cancelled=None: {"segments": segs, "language": "ko"}
    app._auto_transcribe(str(p["wav"]))
    wait_until(lambda: len(app.subtitles) == 2 and app.subtitles[0]["text"] == "안녕하세요 여러분", 10,
               lambda: f"{[s['text'] for s in app.subtitles]} {ctx.msgs}")
    eq([s["text"] for s in app.subtitles], ["안녕하세요 여러분", "오늘 방송 시작할게요"])
    left = [f for f in set(os.listdir(tempfile.gettempdir())) - before if f.endswith(".srt")]
    eq(left, [], "임시 SRT는 지움")
    expect(app.save_path.endswith(".srt") and app._unsaved, "미디어 이름으로 저장 대기")
