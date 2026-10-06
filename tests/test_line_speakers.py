"""줄 단위 화자 구분: 임베딩 군집·선지정 분류와 결과 적용."""
import numpy as np

from harness import ctx, eq, expect, load_sample, test, wait_until


def _fake(n_per=30, k=4, dim=32, noise=0.35, seed=0):
    rng = np.random.default_rng(seed)
    centers = rng.normal(size=(k, dim))
    x = np.vstack([centers[i] + noise * rng.normal(size=(n_per, dim)) for i in range(k)])
    y = np.repeat(np.arange(k), n_per)
    return x, y


def _acc_cluster(lab, y):
    from scipy.optimize import linear_sum_assignment
    ids = sorted(set(lab))
    m = np.array([[np.sum((lab == i) & (y == j)) for j in range(y.max() + 1)] for i in ids])
    ri, ci = linear_sum_assignment(-m)
    mp = {ids[i]: j for i, j in zip(ri, ci)}
    return np.mean([mp.get(l) == t for l, t in zip(lab, y)])


@test
def cluster_lines_recovers_separated_speakers():
    from srt_editor import line_speakers as L
    x, y = _fake()
    lab, conf = L.cluster_lines(x, 4)
    eq(len(conf), len(lab))
    expect(0.0 <= conf.min() and conf.max() <= 1.0, "확신도는 0~1")
    expect(_acc_cluster(lab, y) > 0.95, f"분리된 4명은 거의 맞혀야 해요: {_acc_cluster(lab, y):.2f}")


@test
def cluster_lines_skips_lines_without_embedding_and_small_inputs():
    from srt_editor import line_speakers as L
    x, _ = _fake(n_per=5, k=2)
    x[3] = np.nan
    lab, conf = L.cluster_lines(x, 2)
    eq(lab[3], -1, "임베딩 없는 줄은 -1")
    eq(conf[3], 0.0)
    eq(len(set(lab[lab >= 0])), 2)
    eq(list(L.cluster_lines(x[:1], 3)[0]), [0], "줄이 모자라면 군집 수를 줄임")


@test
def seed_speakers_requires_enough_labeled_lines():
    from srt_editor import line_speakers as L
    eq(L.seed_speakers(["", "", ""]), {}, "지정 없음")
    eq(L.seed_speakers(["가", "가", "가", "나", ""]), {}, "한 명만 3줄 이상이면 부족")
    seeds = L.seed_speakers(["가", "가", "가", "나", "나", "나", "", "다"])
    eq(sorted(set(seeds.values())), ["가", "나", "다"], "조건을 채우면 지정된 줄을 모두 기준으로 씀")
    eq(len(seeds), 7)


@test
def assign_from_seeds_labels_all_lines_and_handles_missing_embedding():
    from srt_editor import line_speakers as L
    x, y = _fake(noise=0.6)
    names = ["가", "나", "다", "라"]
    seeds = {int(i): names[y[i]] for k in range(4) for i in np.where(y == k)[0][:4]}
    x[7] = np.nan
    pred, conf = L.assign_from_seeds(x, seeds)
    eq(conf[7], 0.0)
    eq(pred[7], "", "임베딩 없는 줄은 비움")
    rest = [i for i in range(len(y)) if i not in seeds and i != 7]
    acc = np.mean([pred[i] == names[y[i]] for i in rest])
    expect(acc > 0.9, f"줄을 4개씩 지정하면 나머지는 대부분 맞혀야 해요: {acc:.2f}")


def _start_button(win):
    from harness import find
    return find(win, "FlatButton", "화자 분석 시작")[0]


@test
def diarize_start_without_seeds_asks_and_ok_closes_dialog(app):
    from harness import ctx, press, pump, toplevels
    load_sample(app, with_wav=True)
    for s in app.subtitles:
        s["speaker"] = ""
    app._open_diarize_dialog()
    pump(0.5)
    win = toplevels()[-1]
    ctx.answers["ask_choice"] = True   # 지정하러 가기 (강조 버튼)
    ran = []
    app._run_diarize_whisperx = lambda: ran.append(1)
    press(_start_button(win))
    pump(0.3)
    expect(any(m[0] == "ask_choice" for m in ctx.msgs), "선지정 안내가 떠야 해요")
    eq(ran, [], "지정하러 가기는 분석을 시작하지 않음")
    expect(not [w for w in toplevels() if w.winfo_exists()], "지정하러 가기는 분석 창을 닫음")


@test
def diarize_start_without_seeds_cancel_runs_analysis(app):
    from harness import ctx, press, pump, toplevels
    load_sample(app, with_wav=True)
    for s in app.subtitles:
        s["speaker"] = ""
    app._open_diarize_dialog()
    pump(0.5)
    win = toplevels()[-1]
    ctx.answers["ask_choice"] = False   # 진행
    ran = []
    app._run_diarize_whisperx = lambda: ran.append(1)
    press(_start_button(win))
    pump(0.3)
    eq(ran, [1], "진행은 그대로 분석 시작")
    expect(win.winfo_exists(), "분석 창은 그대로")


@test
def diarize_start_with_seeds_skips_notice(app):
    from harness import ctx, press, pump, toplevels
    load_sample(app, n=12, with_wav=True, tagged_every=1)
    app._open_diarize_dialog()
    pump(0.5)
    win = toplevels()[-1]
    ran = []
    app._run_diarize_whisperx = lambda: ran.append(1)
    press(_start_button(win))
    pump(0.3)
    eq(ran, [1], "이미 충분히 지정돼 있으면 안내 없이 시작")
    expect(not any(m[0] == "ask_choice" for m in ctx.msgs), "안내가 뜨면 안 돼요")


@test
def apply_line_speakers_seeded_fills_only_unassigned_with_undo(app):
    load_sample(app, n=12, tagged_every=3)
    before = [s.get("speaker", "") for s in app.subtitles]
    expect("" in before, "비어 있는 줄이 있어야 시험이 돼요")
    keep = {i: v for i, v in enumerate(before) if v}
    result = ["민지"] * len(before)
    app._apply_line_speakers(result, True)
    after = [s.get("speaker", "") for s in app.subtitles]
    for i, v in keep.items():
        eq(after[i], v, "이미 지정한 줄은 그대로")
    expect(all(after), "비어 있던 줄은 채워짐")
    expect(app._unsaved)
    app._undo()
    eq([s.get("speaker", "") for s in app.subtitles], before, "실행 취소로 원래대로")


@test
def apply_line_speakers_clusters_adds_new_speakers(app):
    load_sample(app, n=10, tagged_every=0)
    for s in app.subtitles:
        s["speaker"] = ""
    app.speakers[:] = []
    labs = np.array([0, 1, 0, 1, -1, 2, 2, 0, 1, 2])
    app._apply_line_speakers(labs, False)
    eq(app.speakers, ["화자 1", "화자 2", "화자 3"], "군집 수만큼 새 화자")
    got = [s.get("speaker", "") for s in app.subtitles]
    eq(got[0], "화자 1")
    eq(got[4], "", "임베딩 없는 줄은 비움")
    eq(got[5], "화자 3")
    app._undo()
    eq(app.speakers, [], "실행 취소하면 새 화자도 사라짐")


@test
def cluster_lines_estimates_speaker_count_when_zero():
    from srt_editor import line_speakers as L
    x, y = _fake(n_per=25, k=5, noise=0.3)
    lab, _ = L.cluster_lines(x, 0)
    eq(len(set(lab)), 5, "화자 수 0이면 스스로 추정")
    lab, _ = L.cluster_lines(x, 0, k_max=3)
    expect(len(set(lab)) <= 3, "최대 인원을 넘지 않음")


@test
def unsure_mask_flags_lowest_confidence_auto_lines_only():
    from srt_editor import line_speakers as L
    conf = [0.9, 0.1, 0.5, 0.05, 0.8, 0.95, 0.7, 0.6, 0.4, 0.3]
    auto = [True] * 9 + [False]
    m = L.unsure_mask(conf, auto, frac=0.2)
    eq([i for i, v in enumerate(m) if v], [1, 3], "자동 줄 중 하위 20%")
    eq(list(L.unsure_mask(conf, [False] * 10)), [False] * 10, "자동 줄이 없으면 표시 없음")


@test
def rerun_reassigns_auto_lines_but_keeps_user_lines(app):
    load_sample(app, n=24, tagged_every=1)
    for i, s in enumerate(app.subtitles):
        if i % 4 > 1:   # 민지·준호가 번갈아 6줄씩 남게
            s["speaker"] = ""
    user = {i for i, s in enumerate(app.subtitles) if s.get("speaker")}
    app._apply_line_speakers(["민지"] * 24, True, [0.9] * 24)
    for i, s in enumerate(app.subtitles):
        eq(bool(s.get("_auto")), i not in user, "직접 지정한 줄만 자동 표시가 없음")
    from srt_editor import line_speakers as L
    seeds = L.seed_speakers(["" if s.get("_auto") else s["speaker"] for s in app.subtitles])
    eq(set(seeds), user, "다시 분석할 때는 직접 지정한 줄만 기준")
    app._apply_line_speakers(["준호"] * 24, True, [0.9] * 24)
    for i, s in enumerate(app.subtitles):
        if i not in user:
            eq(s["speaker"], "준호", "자동으로 정한 줄은 다시 분석 결과로 바뀜")


def _analyzed_with_checks(app, n=120):
    load_sample(app, n=n, tagged_every=1, with_wav=True)
    for i, s in enumerate(app.subtitles):
        if i % 4 > 1:
            s["speaker"] = ""
    conf = [0.95 - (i % 9) * 0.1 for i in range(n)]
    app._apply_line_speakers(["민지"] * n, True, conf)
    return [i for i, s in enumerate(app.subtitles) if s.get("_check")]


@test
def diarize_button_turns_into_check_only_and_glows_after_fixes(app):
    from harness import pump
    btn = app._tb_btns["화자 분석"]
    eq(btn.itemcget("label", "text"), "화자 분석")
    checks = _analyzed_with_checks(app)
    pump(0.2)
    expect(len(checks) >= 10, f"? 줄 {len(checks)}")
    eq(btn.itemcget("label", "text"), "? 줄만 분석", "? 줄이 있으면 버튼이 바뀜")
    expect(not getattr(app, "_diarize_glow", False), "고친 줄이 없으면 점등 안 함")
    for i in checks[:3]:
        app._set_line_speaker(i, "준호")
    app._update_count()
    expect(app._diarize_glow, "? 줄을 3개 고치면 점등")
    for i in checks[3:]:
        app._set_line_speaker(i, "준호")
    app._update_count()
    eq(btn.itemcget("label", "text"), "화자 분석", "? 줄이 없어지면 원래대로")
    expect(not app._diarize_glow)


@test
def check_only_rerun_changes_only_check_lines_and_keeps_unsure_ones(app):
    import srt_editor.ui.diarize as dz
    checks = _analyzed_with_checks(app)
    for i in checks[:3]:
        app._set_line_speaker(i, "준호")
    rest = checks[3:]
    before = [s["speaker"] for s in app.subtitles]
    jobs = []

    def fake_job(job, on_event=None, cancelled=None):
        jobs.append(job)
        conf = [0.99] * len(app.subtitles)
        conf[rest[0]] = 0.0   # 여전히 애매한 줄
        return {"mode": "seeded", "names": ["하늘"] * len(app.subtitles), "conf": conf}
    app._run_ai_job = fake_job
    app._hf_token = "hf_test"
    orig = dz.ai_runtime.ai_python
    dz.ai_runtime.ai_python = lambda: "py"
    ctx.msgs.clear()
    try:
        app._on_diarize_button()
        wait_until(lambda: any(k == "showinfo" for k, *_ in ctx.msgs), 5)
    finally:
        dz.ai_runtime.ai_python = orig
        del app._run_ai_job
    expect(jobs, f"AI 작업이 실행돼야 해요: {ctx.msgs}")
    expect(all(str(i) in jobs[0]["seeds"] for i in checks[:3]), "고친 ? 줄도 기준으로 전달")
    for i, s in enumerate(app.subtitles):
        if i in rest:
            eq(s["speaker"], "하늘", "? 줄은 새 결과로")
        else:
            eq(s["speaker"], before[i], "? 아닌 줄은 그대로")
    eq([i for i, s in enumerate(app.subtitles) if s.get("_check")], [rest[0]], "여전히 애매한 줄만 ? 유지")
    app._undo()
    eq([s["speaker"] for s in app.subtitles], before, "실행 취소")


@test
def check_marks_show_counter_navigate_and_clear_on_manual_assign(app):
    from harness import pump
    load_sample(app, n=20, tagged_every=0)
    for s in app.subtitles:
        s["speaker"] = ""
    conf = [0.9] * 20
    conf[4], conf[11], conf[17] = 0.01, 0.02, 0.03
    app._apply_line_speakers(["민지"] * 20, True, conf)
    pump(0.2)
    checks = [i for i, s in enumerate(app.subtitles) if s.get("_check")]
    eq(checks, [4, 11, 17], "확신도 낮은 줄 표시")
    expect(app.lbl_check.winfo_ismapped(), "확인 필요 숫자가 보여야 해요")
    eq(app.lbl_check.cget("text"), "?  확인 필요 3줄")
    app._select_row(0)
    app._goto_next_check()
    eq(app._selected_row_idx, 4, "다음 확인 필요 줄로 이동")
    app._goto_next_check()
    eq(app._selected_row_idx, 11)
    app._assign_speaker_to_selection("준호")
    s = app.subtitles[11]
    expect(not s.get("_check") and not s.get("_auto"), "직접 지정하면 표시가 사라짐")
    eq(app.lbl_check.cget("text"), "?  확인 필요 2줄")
    from harness import slot_of
    app._scroll_to_row(4)
    pump(0.1)
    t = app._slot_widgets[slot_of(app, 4)]["tag"]
    eq(app.canvas.itemcget(t + "chk", "text"), "?", "번호 칸에 ? 표시")
    eq(app.canvas.itemcget(t + "card", "fill"), app._CARD_CHECK_BG, "연한 노란 배경")
    expect(app._get_col_positions()["num"][1] == app._col_w["num"] + app._CHECK_NUM_EXTRA, "번호 칸이 넓어짐")
    app._undo()
    eq(app.lbl_check.cget("text"), "?  확인 필요 3줄", "실행 취소하면 표시도 돌아옴")


@test
def diarize_dialog_closes_when_analysis_starts(app):
    import srt_editor.ui.diarize as dz
    from harness import pump, toplevels
    load_sample(app, n=24, tagged_every=1, with_wav=True)
    app._open_diarize_dialog()
    pump(0.3)
    app._hf_token_var.set("hf_test")
    n = len(app.subtitles)
    import threading
    go = threading.Event()

    def job(job, on_event=None, cancelled=None):
        go.wait(5)
        return {"mode": "seeded", "names": ["민지"] * n, "conf": [0.9] * n}
    app._run_ai_job = job
    orig = dz.ai_runtime.ai_python
    dz.ai_runtime.ai_python = lambda: "py"
    ctx.msgs.clear()
    try:
        app._run_diarize_whisperx()
        pump(0.3)
        expect(not [w for w in toplevels() if w.title() == "화자 자동 분석"], "시작하면 분석 창은 닫힘")
        expect(app.grab_current() is not None, "메인 창 진행 카드가 입력을 막음")
        go.set()
        wait_until(lambda: any(k == "showinfo" for k, *_ in ctx.msgs), 5)
    finally:
        dz.ai_runtime.ai_python = orig
    pump(0.2)
    expect(not [w for w in toplevels() if w.title() == "화자 자동 분석"], "분석 창은 닫힘")


@test
def f_key_plays_next_check_line_and_number_key_moves_on(app):
    from types import SimpleNamespace as NS
    from harness import pump
    load_sample(app, n=20, tagged_every=0, with_wav=True)
    for s in app.subtitles:
        s["speaker"] = ""
    conf = [0.9] * 20
    conf[4], conf[11], conf[17] = 0.01, 0.02, 0.03
    app._apply_line_speakers(["민지"] * 20, True, conf)
    app._select_row(0)
    app._review_next_check(NS())
    pump(0.2)
    eq(app._selected_row_idx, 4, "다음 ? 줄 선택")
    t_s, t_e = app._ts_cache[4]
    expect(app.player.is_playing, "그 줄을 재생")
    eq(app._review_stop_at, t_e + 0.15, "줄 끝에서 멈춤 예약")
    app.player.seek_to(t_e + 0.3)
    app._poll_progress()
    expect(not app.player.is_playing and app._review_stop_at is None, "줄 끝을 지나면 멈춤")
    app.speakers[:] = ["민지", "준호"]
    k, who = 2, "준호"
    app._on_speaker_key(NS(keysym=str(k)))
    pump(0.1)
    eq(app.subtitles[4]["speaker"], who, "숫자키로 화자 지정")
    eq(app._selected_row_idx, 11, "다음 ? 줄로 이동")
    expect(not app.player.is_playing, "멈춰 있었으면 그대로 멈춤")
    app._media_play_pause()
    app._on_speaker_key(NS(keysym=str(k)))
    pump(0.1)
    eq(app._selected_row_idx, 17)
    expect(app.player.is_playing, "재생 중이었으면 다음 줄도 재생")
    app._media_play_pause()
    from harness import write_config
    write_config({"advance_to_check": False})
    app.__dict__["_opt_cache"] = {}
    app.subtitles[11]["_check"] = True
    app._select_row(11)
    app._on_speaker_key(NS(keysym=str(k)))
    eq(app._selected_row_idx, 11, "설정을 끄면 다음 ? 줄로 가지 않음")
    app._select_row(0)
    app._on_speaker_key(NS(keysym=str(k)))
    eq(app._selected_row_idx, 0 if not app._opt("advance_after_assign") else 1, "? 아닌 줄은 기존 동작 그대로")
    for i in (11, 17):   # 남은 ? 정리
        app._set_line_speaker(i, "준호")
    app._update_count()
    ctx.msgs.clear()
    app._select_row(0)
    app._review_next_check(NS())
    eq(app._selected_row_idx, 0, "? 줄이 없으면 그대로")


@test
def text_edit_tab_saves_moves_to_next_line_and_plays(app):
    from types import SimpleNamespace as NS
    from harness import pump, slot_of
    load_sample(app, n=12, with_wav=True)
    app._select_row(2)
    app._edit_selected_text()
    pump(0.1)
    s = slot_of(app, 2)
    ent = app._slot_widgets[s]["content"]
    ent.delete(0, "end"); ent.insert(0, "고친 문장")
    app._txt_jump(s, 1)
    pump(0.2)
    eq(app.subtitles[2]["text"], "고친 문장", "Tab: 지금 줄 저장")
    eq(app._selected_row_idx, 3, "다음 줄로 이동")
    s3 = slot_of(app, 3)
    expect(app.focus_get() is app._slot_widgets[s3]["content"], "다음 줄 편집 칸에 커서")
    expect(app.player.is_playing and app._review_stop_at == app._ts_cache[3][1] + 0.15, "다음 줄만 재생")
    app._media_play_pause()
    app._slot_widgets[s3]["content"].insert("end", "!")
    app._txt_jump(s3, -1)
    pump(0.2)
    expect(app.subtitles[3]["text"].endswith("!"), "Shift+Tab도 저장")
    eq(app._selected_row_idx, 2, "이전 줄로")
    s2 = slot_of(app, 2)
    app._txt_replay(s2)
    expect(app.player.is_playing and app.focus_get() is app._slot_widgets[s2]["content"], "Ctrl+Space: 편집은 그대로, 소리만 다시")
    app._media_play_pause()
    app.focus_set(); pump(0.2)
    eq(app.subtitles[2]["text"], "고친 문장", "늦게 온 포커스 해제가 다른 줄에 덮어쓰지 않음")
    app._undo()
    expect(not app.subtitles[3]["text"].endswith("!"), "실행 취소")


@test
def auto_and_check_flags_survive_save_and_reopen(app):
    p = load_sample(app, n=10, tagged_every=0)
    for s in app.subtitles:
        s["speaker"] = ""
    conf = [0.9] * 10
    conf[2], conf[7] = 0.01, 0.02
    app._apply_line_speakers(["민지"] * 10, True, conf)
    app.save_file()
    app._close_to_home()
    app._open_paths([str(p["srt"])])
    from harness import wait_until
    wait_until(lambda: len(app.subtitles) == 10, 5)
    eq([i for i, s in enumerate(app.subtitles) if s.get("_check")], [2, 7], "확인 필요 복원")
    expect(all(s.get("_auto") for s in app.subtitles), "자동 표시 복원")
    expect(app.lbl_check.winfo_ismapped(), "다시 열어도 확인 필요 숫자가 보임")


@test
def ask_choice_dialog_returns_button_result(app):
    import importlib
    import srt_editor.widgets as W
    real = importlib.reload(W).ask_choice   # 테스트용 대체 함수가 아닌 실제 창
    from harness import flat, toplevels
    for btn, want in (("진행", True), ("지정하러 가기", False)):
        def click(b=btn):
            win = [w for w in toplevels() if w.title() == "질문"][0]
            flat(win, b).event_generate("<ButtonRelease-1>", x=2, y=2)
        app.after(300, click)
        eq(real(app, "질문", "내용", "진행", "지정하러 가기"), want, btn)
    app.after(300, lambda: [w.destroy() for w in toplevels() if w.title() == "질문"])
    eq(real(app, "질문", "내용", "진행", "지정하러 가기"), None, "닫으면 None")
    W.ask_choice = __import__("srt_editor.ui.diarize", fromlist=["x"]).ask_choice
