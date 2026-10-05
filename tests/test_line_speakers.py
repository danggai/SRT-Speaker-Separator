"""줄 단위 화자 구분: 임베딩 군집·선지정 분류와 결과 적용."""
import numpy as np

from harness import eq, expect, load_sample, test


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
    ctx.answers["askokcancel"] = True
    ran = []
    app._run_diarize_whisperx = lambda: ran.append(1)
    press(_start_button(win))
    pump(0.3)
    expect(any(m[0] == "askokcancel" for m in ctx.msgs), "선지정 안내가 떠야 해요")
    eq(ran, [], "확인을 누르면 분석을 시작하지 않음")
    expect(not [w for w in toplevels() if w.winfo_exists()], "확인을 누르면 분석 창이 닫혀야 해요")


@test
def diarize_start_without_seeds_cancel_runs_analysis(app):
    from harness import ctx, press, pump, toplevels
    load_sample(app, with_wav=True)
    for s in app.subtitles:
        s["speaker"] = ""
    app._open_diarize_dialog()
    pump(0.5)
    win = toplevels()[-1]
    ctx.answers["askokcancel"] = False
    ran = []
    app._run_diarize_whisperx = lambda: ran.append(1)
    press(_start_button(win))
    pump(0.3)
    eq(ran, [1], "취소를 누르면 그대로 분석 시작")
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
    expect(not any(m[0] == "askokcancel" for m in ctx.msgs), "안내가 뜨면 안 돼요")


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
    eq(app.canvas.itemcget(t + "num", "text"), "? 5", "번호 앞에 ? 표시")
    app._undo()
    eq(app.lbl_check.cget("text"), "?  확인 필요 3줄", "실행 취소하면 표시도 돌아옴")


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
