"""자동 자막: 인식 결과를 자막 줄로 나누기·다듬기와 불러오기."""
import os

from harness import steps, ctx, eq, expect, fresh_dir, load_sample, near, test, wait_until


def _tp():
    from srt_editor import transcript_post
    return transcript_post


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


def char_split_leaves_no_short_tail_and_balances_lines():
    T = _tp()
    eq(T.split_by_chars("자 얘들아 내가 또 꿈에서 우리의 사업체를", 20), ["자 얘들아 내가 또 꿈에서 우리의 사업체를"],
       "몇 글자 넘치는 건 꼬리('사업체를')를 떼지 않고 한 줄")
    eq(T.split_by_chars("자 얘들아 내가 또 꿈에서 우리의 사업체를 어떻게 이끌어가면 좋을지 생각을 해왔거든", 20),
       ["자 얘들아 내가 또 꿈에서 우리의 사업체를", "어떻게 이끌어가면 좋을지 생각을 해왔거든"], "넘으면 고르게 나눔")
    lines = T.split_by_chars("모르겠어요 저 근데 엄청 무서운 사람이 갑자기 나타나서 막 쫓아왔어요", 20)
    expect(not any(T.dangling_word(l.split()[-1]) == 2 for l in lines[:-1]), f"꾸미는 말로 줄이 끝나지 않음: {lines}")
    lines = T.split_by_chars("가나다 " * 20, 20)
    expect(all(len(l) <= 25 for l in lines) and max(map(len, lines)) - min(map(len, lines)) <= 4, f"{lines}")


def short_segment_splits_at_pause_or_sentence_end_but_keeps_tiny_pieces():
    T = _tp()
    seg = {"start": 0.0, "end": 4.0, "text": "아 그냥 딱 봤는데! 이쁘다 진짜",
           "words": [{"word": "아", "start": 0.0, "end": 0.2}, {"word": "그냥", "start": 0.6, "end": 0.9},
                     {"word": "딱", "start": 1.0, "end": 1.1}, {"word": "봤는데!", "start": 1.2, "end": 1.7},
                     {"word": "이쁘다", "start": 1.8, "end": 2.3}, {"word": "진짜", "start": 2.9, "end": 3.3}]}
    lines = T.build_lines([seg], 20)
    eq([l["text"] for l in lines], ["아 그냥 딱 봤는데!", "이쁘다 진짜"],
       "20자 안이어도 문장부호에서 나누고, 4자 미만 조각('아', '이쁘다')은 쉼이 있어도 붙여 둠")
    near(lines[1]["start"], 1.75, 1e-6, "단어 시작보다 0.05초 일찍 시작")
    near(lines[0]["start"], 0.0, 1e-6, "0초보다 앞으로는 안 감")
    lines = T.lead_in([{"start": 1.0, "end": 2.0}, {"start": 2.02, "end": 3.0}, {"start": 3.0, "end": 4.0}])
    eq([round(l["start"], 3) for l in lines], [0.95, 2.0, 3.0], "앞 줄 끝보다 앞으로는 안 감, 붙은 줄은 그대로")
    seg2 = dict(seg, words=[dict(w) for w in seg["words"]])
    seg2["words"][4]["word"] = "정말이쁘다"
    eq([l["text"] for l in T.build_lines([seg2], 20)], ["아 그냥 딱 봤는데!", "정말이쁘다", "진짜"],
       "4자 이상이면 0.25초 넘는 쉼에서 나눔")


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
    eq((round(lines[2]["start"], 3), round(lines[2]["end"], 3)), (7.95, 12.95),
       "반복 줄은 하나로 합치고 시간은 이어 붙임 (시작 0.05초 앞당김, 끝은 다음 줄까지 메움)")


def timing_fix_removes_overlap_and_stretches_tiny_lines():
    T = _tp()
    lines = T.fix_timing([{"start": 0.0, "end": 2.5, "text": "a"}, {"start": 2.0, "end": 2.05, "text": "b"},
                          {"start": 5.0, "end": 6.0, "text": "c"}])
    eq([(l["start"], l["end"]) for l in lines], [(0.0, 2.0), (2.0, 2.3), (5.0, 6.0)])


def short_gaps_between_lines_are_filled():
    T = _tp()
    lines = T.build_lines([{"start": 0.0, "end": 1.0, "text": "첫 번째 줄이에요"},
                           {"start": 1.4, "end": 2.0, "text": "두 번째 줄이에요"},
                           {"start": 4.0, "end": 5.0, "text": "한참 뒤 줄이에요"}])
    eq([(round(l["start"], 3), round(l["end"], 3)) for l in lines], [(0.0, 1.35), (1.35, 2.0), (3.95, 5.0)],
       "1초 미만 빈틈은 앞 줄을 늘려 메우고, 긴 쉼은 그대로 (시작은 0.05초 앞당김)")


def period_option_adds_or_strips_whisper_period():
    T = _tp()
    eq(T.finish_text("안녕하세요.", False), "안녕하세요")
    eq(T.finish_text("진짜?", False), "진짜?")
    eq(T.finish_text("안녕하세요", True), "안녕하세요.")


@test
def find_and_replace_one_and_all_with_single_undo(app):
    from harness import pump
    load_sample(app, n=6)
    texts = ["마모의 방송", "오늘 마모가 왔어요", "평범한 줄", "MAMO 마모", "끝", "마모"]
    for s, t in zip(app.subtitles, texts):
        s["text"] = t
    app._fill_slots(app._vscroll_top)
    app._open_replace()
    app._search_var.set("마모")
    app._replace_var.set("마무")
    pump(0.1)
    app._select_row(0); app._search_update()
    app._replace_one()
    eq(app.subtitles[0]["text"], "마무의 방송", "바꾸기: 지금 줄만")
    eq(app.subtitles[1]["text"], "오늘 마모가 왔어요")
    eq(app._selected_row_idx, 1, "다음 일치로 이동")
    app._replace_entry.focus_force()
    pump(0.05)
    app._replace_entry.event_generate("<Shift-Return>")   # 바꿀 말 칸에서 Shift+Enter = 모두 바꾸기
    pump(0.05)
    eq([s["text"] for s in app.subtitles], ["마무의 방송", "오늘 마무가 왔어요", "평범한 줄", "MAMO 마무", "끝", "마무"])
    app._undo()
    eq([s["text"] for s in app.subtitles][:2], ["마무의 방송", "오늘 마모가 왔어요"], "모두 바꾸기는 실행 취소 한 번에")
    app._search_var.set("mamo"); app._replace_var.set("Mamu"); app._replace_all()
    eq(app.subtitles[3]["text"], "Mamu 마모", "대소문자 구분 없이 찾음")


@test
def playback_speed_renders_audio_and_keeps_media_time(app):
    import time
    from harness import pump, wait_until
    from srt_editor import stretch
    load_sample(app, n=6, with_wav=True)
    src = app.player._filepath
    app._set_play_speed(2.0)
    wait_until(lambda: app.player.speed == 2.0 and app._speed_btn.itemcget("label", "text") == "2배속", 15,
               lambda: app._speed_btn.itemcget("label", "text"))
    expect(stretch.cache_path(src, 2.0).exists(), "배속 소리를 만들어 둠")
    app._do_seek(4.0)
    app._media_play_pause()
    time.sleep(0.5)
    pos = app.player.position
    app._media_play_pause()
    expect(4.8 <= pos <= 5.6, f"2배속: 0.5초에 원본 시간으로 약 1초 진행 ({pos:.2f})")
    app._speed_step(-1)
    wait_until(lambda: app.player.speed == 1.5, 15)
    expect(abs(app.player.position - pos) < 0.01, "배속을 바꿔도 위치 유지")
    app._set_play_speed(4.0)
    wait_until(lambda: app.player.speed == 4.0, 15)
    app._set_play_speed(1.0)
    eq((app.player.speed, app.player._speed_path), (1.0, None), "1배속은 원본 그대로")
    load_sample(app, n=4, with_wav=True)
    pump(0.3)
    eq(app._speed_btn.itemcget("label", "text"), "1배속", "새 미디어는 1배속부터")
    pump(0.3)
    expect(not stretch.cache_path(src, 2.0).exists() or app.player._filepath == src, "다른 파일의 배속 소리는 지움")


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
    # 직접 두 번 고친 말은 다음 자동 자막에 바로 반영
    app.subtitles[0]["text"], app.subtitles[1]["text"] = "지아야 안녕", "지아씨 방송"
    app._open_replace()
    app._search_var.set("지아"); app._replace_var.set("지하")
    app._replace_all()
    segs[2]["text"] = "지아야 방송 끝"
    app._auto_transcribe(str(p["wav"]))
    wait_until(lambda: app.subtitles[-1]["text"] == "지하야 방송 끝", 10, lambda: [s["text"] for s in app.subtitles])

def learned_fixes_need_two_same_fixes_and_skip_kept_words():
    from srt_editor import learned_fixes as LF
    store = {}
    LF.learn(store, "야 지아야 너 뭐해", "야 지하야 너 뭐해")
    eq(LF.rules(store), {}, "한 번 고친 건 아직 적용 안 함")
    LF.learn(store, "지아씨가 다 불었어", "지하씨가 다 불었어")
    eq(LF.rules(store), {"지아": "지하"}, "두 번 똑같이 고치면 적용")
    eq(LF.apply("고맙다 지아야 지아씨는?", LF.rules(store)), ("고맙다 지하야 지하씨는?", 2), "조사·호칭은 그대로")
    LF.learn(store, "손해를 봤어", "순해를 봤어")
    LF.learn(store, "손해야 왔어", "순해야 왔어")
    LF.learn(store, "그건 손해가 크다 진짜", "그건 손해가 크다 정말")
    expect("손해" not in LF.rules(store), "고친 줄에서 그대로 둔 적 있는 말(진짜 단어)은 적용 안 함")


def whisper_repeat_loops_are_found_and_retried():
    from srt_editor import speech, ai_worker

    def seg(t, s, e):
        return {"text": t, "start": s, "end": e}
    segs = [seg("시작", 0, 1)] + [seg(" 정지해주세요.", 1 + k, 2 + k) for k in range(6)] + [seg("끝", 8, 9)]
    eq(speech.find_loops(segs), [(1, 6)], "같은 문장 4번 이상 이어지면 반복 오류")
    eq(speech.find_loops(segs[:4]), [], "3번까지는 그대로")
    stut = [seg("보스", 0, 1), seg("아니이이이이이이이이이이이이", 1, 3), seg("이이이이이이이이이이", 3, 5), seg("가자", 5, 6)]
    eq(speech.find_loops(stut), [(1, 2)], "한 문장 안 글자 반복도 (이어진 줄은 묶어서)")
    eq(speech.find_loops([seg("오지마 오지마 오지마", 0, 2)]), [], "몇 번 반복은 실제 말일 수 있어 그대로")
    glued = [seg("정지해주세요. " * 12, 0, 20)]
    eq(speech.find_loops(glued), [(0, 0)], "정렬 전처럼 한 줄에 붙은 문장 반복도")

    class Model:
        def __init__(self, result):
            self.result, self.calls = result, []

        def transcribe(self, audio, **kw):
            self.calls.append((len(audio), kw.get("chunk_size")))
            return {"segments": self.result}
    status, ai_worker.status = ai_worker.status, lambda *a, **k: None
    try:
        good = Model([seg("나 돈이 없어", 0.5, 1.5), seg("그냥 가라", 3.0, 4.0)])
        out = ai_worker._retry_loops(good, [0.0] * (16000 * 10), segs, 8, "ko")
        eq([s["text"] for s in out], ["시작", "나 돈이 없어", "그냥 가라", "끝"], "반복 구간을 다시 인식한 결과로 바꿈")
        eq((out[1]["start"], out[2]["end"]), (1.5, 5.0), "다시 인식한 시간은 구간 시작 기준으로 옮김")
        eq(good.calls[0], (16000 * 6, speech.LOOP_RETRY_CHUNK), "그 구간만 짧은 조각으로")
        bad = Model([seg("정지", 0, 1)] * 5)
        eq(len(ai_worker._retry_loops(bad, [0.0] * 160000, segs, 8, "ko")), len(segs), "다시 해도 반복이면 원래대로")
    finally:
        ai_worker.status = status


@test
def line_building():
    steps(split_uses_word_times_and_interpolates_missing_ones, char_split_leaves_no_short_tail_and_balances_lines, short_segment_splits_at_pause_or_sentence_end_but_keeps_tiny_pieces, hallucinations_and_repeats_are_removed, timing_fix_removes_overlap_and_stretches_tiny_lines, short_gaps_between_lines_are_filled, period_option_adds_or_strips_whisper_period, whisper_repeat_loops_are_found_and_retried, learned_fixes_need_two_same_fixes_and_skip_kept_words)


@test
def toolbar_layout(app):
    steps(toolbar_button_asks_before_replacing_and_opens_options, slide_opens_and_closes_sections_smoothly, narrow_window_hides_shortcut_buttons_and_restores_them)
