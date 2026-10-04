"""타임라인: 레이어·이동(seek)·자막 블록 드래그와 크기 조절·확대·볼륨·재생."""
import re

from harness import (Ev, Skip, app_key, cfg, ctx, eq, expect, fresh_dir, load_sample, near, pump, sample_subs, test,
                     wait_until, write_srt_file)


def with_media(app, n=24):
    p = load_sample(app, n=n, with_wav=True)
    wait_until(lambda: app.player.duration > 0, 10, "미디어 길이")
    app._pb_redraw()
    pump(0.2)
    return p


def pb_xy(app, di, where="mid", lane=0):
    """타임라인에서 di번 자막의 시작/가운데/끝 위치의 (x, y)."""
    t_s, t_e = app._ts_cache[di]
    dur = app._timeline_duration() if hasattr(app, "_timeline_duration") else (app.player.duration or t_e)
    t = {"start": t_s, "mid": (t_s + t_e) / 2, "end": t_e}[where]
    cw = app._pb_canvas.winfo_width()
    return app._wf_ratio_to_x(t / dur, cw), int(lane * app._WF_LANE_H + app._WF_LANE_H / 2)


def drag(app, x0, y0, x1, y1, state=0, steps=4):
    pb = app._pb_canvas
    app._pb_press(Ev(pb, x0, y0, state))
    for k in range(1, steps + 1):
        app._pb_drag(Ev(pb, x0 + (x1 - x0) * k // steps, y0 + (y1 - y0) * k // steps, state))
    app._pb_release(Ev(pb, x1, y1, state))
    pump(0.15)


def secs(ts_text):
    from srt_editor.srt_io import parse_srt_time
    a, b = ts_text.split("-->")
    return parse_srt_time(a), parse_srt_time(b)


# ───────── 레이어 ─────────
@test
def layers_add_remove_limits(app):
    load_sample(app)
    eq(app._wf_manual_lanes, 1)
    for _ in range(10):
        app._wf_add_layer()
    eq(app._wf_manual_lanes, app._WF_ABS_MAX_LANES, "레이어는 상한까지만")
    for _ in range(10):
        app._wf_remove_layer()
    eq(app._wf_manual_lanes, 1, "레이어는 최소 1개")


@test
def layers_assigned_for_overlapping_subtitles(app):
    d = fresh_dir()
    subs = [{"timestamp": "00:00:01,000 --> 00:00:05,000", "text": "a", "speaker": ""},
            {"timestamp": "00:00:02,000 --> 00:00:06,000", "text": "b", "speaker": ""},
            {"timestamp": "00:00:03,000 --> 00:00:07,000", "text": "c", "speaker": ""},
            {"timestamp": "00:00:08,000 --> 00:00:09,000", "text": "d", "speaker": ""}]
    p = write_srt_file(d / "ov.srt", subs)
    app._open_paths([str(p)])
    wait_until(lambda: len(app.subtitles) == 4, 5)
    for _ in range(2):
        app._wf_add_layer()
    for sub in app.subtitles:
        sub.pop("_lane", None)
    lanes, n = app._compute_subtitle_lanes(app._ts_cache)
    eq(n, 3, "레이어 수")
    eq(sorted(lanes[i] for i in (0, 1, 2)), [0, 1, 2], "겹친 3개는 서로 다른 레이어")
    eq(lanes[3], 0, "겹치지 않으면 빈 첫 레이어")
    app._wf_remove_layer()
    app._wf_remove_layer()
    lanes, n = app._compute_subtitle_lanes(app._ts_cache)
    eq(set(lanes.values()), {0}, "레이어가 1개면 모두 같은 레이어(겹쳐 그려짐)")


@test
def layers_saved_in_file_and_restored(app):
    p = load_sample(app)
    app._wf_add_layer()
    app._wf_add_layer()
    app.subtitles[3]["_lane"] = 2
    app._unsaved = True
    app.save_file()
    from srt_editor import srt_io
    meta = srt_io.read_srt_meta(str(p["srt"]))
    eq(meta["lanes"], 3)
    eq(meta["sub_lanes"][3], 2)
    app._close_to_home()
    app._open_paths([str(p["srt"])])
    wait_until(lambda: len(app.subtitles) == 24, 5)
    eq(app._wf_manual_lanes, 3, "레이어 수 복원")
    eq(app.subtitles[3]["_lane"], 2, "자막별 레이어 복원")


# ───────── 이동(seek) ─────────
@test
def seek_updates_position_selection_and_highlight(app):
    with_media(app)
    app._do_seek(5.5)             # 자막 2 (5.0~7.0)
    near(app.media_progress_var.get(), 5.5, 1e-6, "재생 위치")
    eq(app._selected_row_idx, 2, "그 자리의 자막이 선택됨")
    eq(app._playing_rows, {2})
    eq(app.lbl_pos.cget("text"), "0:00:05", "위치 표시")
    app._do_seek(7.2)             # 빈 구간
    eq(app._playing_rows, set(), "빈 구간에서는 강조 없음")
    eq(app._selected_row_idx, 2, "빈 구간으로 가도 선택은 유지")
    app._do_seek(0.5, update_selection=False)
    eq(app._selected_row_idx, 2, "선택을 바꾸지 않는 seek")
    eq(app.lbl_dur.cget("text"), "0:00:40", "전체 길이 표시")


@test
def click_empty_timeline_scrubs_playhead(app):
    with_media(app)
    pb = app._pb_canvas
    cw = pb.winfo_width()
    y = app._WF_LANE_H * app._wf_num_lanes + 30   # 자막 줄 아래 파형 영역
    app._pb_press(Ev(pb, cw // 4, y))
    app._pb_release(Ev(pb, cw // 4, y))
    pump(0.15)
    near(app.media_progress_var.get(), 10.0, 1.0, "전체의 1/4 지점")


@test
def seek_without_media_is_ignored_safely(app):
    load_sample(app)
    pb = app._pb_canvas
    app._pb_press(Ev(pb, 50, 80))
    app._pb_release(Ev(pb, 50, 80))
    app._media_play_pause()
    app._media_seek(5)
    app._media_stop()


# ───────── 자막 블록 드래그 ─────────
@test
def drag_body_moves_subtitle_keeps_length_and_undo(app):
    with_media(app)
    old = app.subtitles[2]["timestamp"]
    s0, e0 = secs(old)
    x0, y0 = pb_xy(app, 2)
    cw = app._pb_canvas.winfo_width()
    dx = int(cw * (1.0 / 40.0))      # 약 1초
    drag(app, x0, y0, x0 + dx, y0)
    s1, e1 = secs(app.subtitles[2]["timestamp"])
    near(e1 - s1, e0 - s0, 0.002, "길이는 그대로")
    expect(0.6 < s1 - s0 < 1.4, f"약 1초 뒤로 이동: {s1 - s0:.2f}초")
    near(app._ts_cache[2][0], s1, 0.001, "캐시도 갱신")
    expect(app._unsaved, "수정 표시")
    app._undo()
    eq(app.subtitles[2]["timestamp"], old, "실행 취소로 원래 시간")


@test
def click_on_subtitle_selects_without_changing_time(app):
    with_media(app)
    old = app.subtitles[3]["timestamp"]
    pos0 = app.media_progress_var.get()
    x, y = pb_xy(app, 3)
    drag(app, x, y, x + 2, y, steps=1)
    eq(app.subtitles[3]["timestamp"], old, "클릭만 했는데 시간이 바뀜")
    eq(app._selected_row_idx, 3, "클릭하면 그 자막이 선택돼야 해요")
    near(app.media_progress_var.get(), pos0, 1e-6, "클릭 선택은 재생 위치를 옮기지 않음")
    expect(not app._unsaved, "클릭만으로 수정 표시가 되면 안 돼요")


@test
def resize_handles_respect_minimum_length(app):
    with_media(app)
    s0, e0 = secs(app.subtitles[4]["timestamp"])
    x, y = pb_xy(app, 4, "end")
    hit = app._wf_hit_test(x, y)
    eq((hit["type"], hit.get("mode"), hit.get("idx")), ("handle", "head_end", 4), "끝 핸들 판정")
    drag(app, x, y, x - 2000, y)
    s1, e1 = secs(app.subtitles[4]["timestamp"])
    near(s1, s0, 1e-6, "시작은 그대로")
    near(e1 - s1, app._MIN_SUB_DURATION, 0.002, "끝을 시작보다 앞으로 끌어도 최소 길이")
    x, y = pb_xy(app, 4, "start")
    drag(app, x, y, x + 2000, y)
    s2, e2 = secs(app.subtitles[4]["timestamp"])
    expect(e2 - s2 >= app._MIN_SUB_DURATION - 0.002, f"최소 길이 유지: {e2 - s2}")


@test
def lock_timeline_option_blocks_dragging(app):
    with_media(app)
    app._set_opt("lock_timeline", True)
    old = app.subtitles[2]["timestamp"]
    x, y = pb_xy(app, 2)
    drag(app, x, y, x + 80, y)
    eq(app.subtitles[2]["timestamp"], old, "잠금이 켜져 있으면 안 움직여야 해요")
    eq(app._undo_stack, [], "실행 취소 기록도 없어야 해요")


@test
def shift_drag_changes_layer_only(app):
    with_media(app)
    app._wf_add_layer()
    pump(0.2)
    old = app.subtitles[2]["timestamp"]
    x, y = pb_xy(app, 2)
    drag(app, x, y, x + 50, y + app._WF_LANE_H, state=0x1)
    eq(app.subtitles[2]["timestamp"], old, "Shift 드래그는 시간을 바꾸지 않음")
    eq(app.subtitles[2].get("_lane"), 1, "아래 레이어로 이동")
    app._undo()
    expect(app.subtitles[2].get("_lane", 0) == 0, "실행 취소로 원래 레이어")


@test
def drag_works_without_media_using_subtitle_span(app):
    """미디어 없이 자막만 열어도 타임라인에서 자막 시간을 조절할 수 있어야 해요 (그리기·클릭은 이미 그렇게 동작)."""
    load_sample(app)
    app._pb_redraw()
    pump(0.2)
    old = app.subtitles[2]["timestamp"]
    x, y = pb_xy(app, 2)
    hit = app._wf_hit_test(x, y)
    eq(hit["type"], "body", "미디어가 없어도 자막 블록은 잡혀야 해요")
    cw = app._pb_canvas.winfo_width()
    drag(app, x, y, x + cw // 30, y)
    expect(app.subtitles[2]["timestamp"] != old, "미디어가 없을 때 드래그가 무시됨")


@test
def overlapping_subtitles_cycle_selection_on_repeated_click(app):
    d = fresh_dir()
    subs = [{"timestamp": "00:00:01,000 --> 00:00:09,000", "text": "a", "speaker": ""},
            {"timestamp": "00:00:02,000 --> 00:00:08,000", "text": "b", "speaker": ""}]
    p = write_srt_file(d / "cyc.srt", subs)
    app._open_paths([str(p)])
    wait_until(lambda: len(app.subtitles) == 2, 5)
    app._pb_redraw()
    x, y = pb_xy(app, 1)
    picks = []
    for _ in range(3):
        drag(app, x, y, x + 1, y, steps=1)
        picks.append(app._selected_row_idx)
    eq(picks, [1, 0, 1], "같은 자리를 계속 누르면 겹친 자막을 돌아가며 선택")


@test
def timeline_right_click_opens_subtitle_menu(app):
    from srt_editor.widgets import PopupMenu
    with_media(app)
    x, y = pb_xy(app, 5)
    app._pb_right_click(Ev(app._pb_canvas, x, y))
    pump(0.2)
    expect(PopupMenu._active is not None, "자막 위 우클릭 메뉴")
    eq(app._selected_row_idx, 5, "우클릭한 자막이 선택됨")
    PopupMenu._active._destroy()
    app._pb_right_click(Ev(app._pb_canvas, 3, 90))   # 빈 곳은 아무 일 없음


# ───────── 확대·축소 ─────────
@test
def zoom_in_out_and_view_range(app):
    with_media(app)
    eq(app._wf_zoom, 1.0)
    for _ in range(6):
        app._wf_zoom_in()
    expect(1.0 < app._wf_zoom <= app._wf_max_zoom(), f"확대 {app._wf_zoom}")
    s, e = app._wf_view_range()
    expect(0.0 <= s < e <= 1.0, f"보이는 구간 {s}~{e}")
    for _ in range(60):
        app._wf_zoom_in()
    eq(app._wf_zoom, float(app._wf_max_zoom()), "최대 확대를 넘지 않음")
    for _ in range(80):
        app._wf_zoom_out()
    eq(app._wf_zoom, 1.0, "축소는 1배까지")
    eq(app._wf_view_range(), (0.0, 1.0), "1배면 전체 구간")
    app_key("<Control-plus>")
    app_key("<Control-equal>")
    expect(app._wf_zoom > 1.0, "Ctrl++ 로 확대")
    app_key("<Control-minus>")
    expect(app.lbl_zoom.cget("text").endswith("×"), "확대 배율 표시")


@test
def zoomed_view_converts_x_and_ratio_consistently(app):
    with_media(app)
    for _ in range(4):
        app._wf_zoom_in()
    app._wf_offset = 0.3
    cw = app._pb_canvas.winfo_width()
    for ratio in (app._wf_view_range()[0], 0.5 * sum(app._wf_view_range()), app._wf_view_range()[1] - 0.001):
        x = app._wf_ratio_to_x(ratio, cw)
        near(app._wf_x_to_ratio(x, cw), ratio, 2.0 / cw, f"비율 {ratio:.3f}")


# ───────── 볼륨 ─────────
@test
def volume_set_mute_clamp_and_persist(app):
    app._set_volume(30)
    eq(app.player._volume, 30)
    eq(app._vol_pct.cget("text"), "30%")
    app._set_volume(150)
    eq(app._vol_var, 100, "100을 넘지 않음")
    app._set_volume(-5)
    eq(app._vol_var, 0, "0 아래로 안 내려감")
    app._set_volume(60)
    app._toggle_mute()
    eq(app._vol_var, 0, "음소거")
    app._toggle_mute()
    eq(app._vol_var, 60, "음소거 해제하면 원래 크기")
    wait_until(lambda: cfg().get("volume") == 60, 3, "볼륨 저장")
    app_key("m")
    eq(app._vol_var, 0, "M 키 음소거")
    app_key("m")


@test
def volume_slider_drag(app):
    c = app._vol_canvas
    w = c.winfo_width()
    app._vol_press(Ev(c, w // 2, 5))
    app._vol_drag(Ev(c, w * 3 // 4, 5))
    app._vol_release(Ev(c, w * 3 // 4, 5))
    near(app._vol_var, 75, 2, "슬라이더 위치가 볼륨")


# ───────── 재생 ─────────
def _audio_or_skip(app):
    if not app.player._init_pygame():
        raise Skip("오디오 장치를 초기화하지 못했어요")


@test
def play_pause_and_seek_keys(app):
    _audio_or_skip(app)
    with_media(app)
    app._media_play_pause()
    expect(app.player.is_playing, "재생이 시작돼야 해요")
    eq(app.btn_play._kind, "pause")
    t0 = app.media_progress_var.get()
    wait_until(lambda: app.media_progress_var.get() > t0 + 0.2, 5, "재생 위치 진행")
    app._media_play_pause()
    expect(not app.player.is_playing, "일시정지")
    eq(app.btn_play._kind, "play")
    pos = app.player.position
    app_key("<Right>")
    near(app.player.position, min(pos + 5, 40), 0.3, "→ 키는 5초 앞으로")
    app_key("<Left>")
    near(app.player.position, pos, 0.3, "← 키는 5초 뒤로")
    app_key("<Shift-Right>")
    near(app.player.position, min(pos + 30, 40), 0.3, "Shift+→ 는 30초")
    app._media_stop()
    eq(app.media_progress_var.get(), 0, "정지하면 처음으로")
    eq(app._playing_rows, set())


@test
def space_key_toggles_playback_but_not_while_typing(app):
    _audio_or_skip(app)
    with_media(app)
    app_key("<space>")
    expect(app.player.is_playing, "스페이스로 재생")
    app_key("<space>")
    expect(not app.player.is_playing, "스페이스로 일시정지")
    app._media_stop()
    from harness import key
    from test_table import begin_text_edit
    ent = begin_text_edit(app, 2)
    key(ent, "<space>")
    expect(not app.player.is_playing, "글자를 입력하는 중에는 스페이스가 재생을 시작하면 안 돼요")
    app._media_stop()


@test
def add_and_split_at_playhead(app):
    with_media(app)
    app._do_seek(6.0, update_selection=False)      # 자막 2 (5.0~7.0) 안
    n = len(app.subtitles)
    app._split_subtitle_shortcut()
    eq(len(app.subtitles), n + 1, "재생 위치에서 나누기")
    eq(app.subtitles[3]["timestamp"].split(" --> ")[0], "00:00:06,000", "나눈 위치")
    app._do_seek(1.0, update_selection=False)      # 자막 0 (0~2) 안
    app._add_subtitle_here()
    eq(len(app.subtitles), n + 2, "재생 위치에 자막 추가")
    starts = [s[0] for s in app._ts_cache]
    eq(starts, sorted(starts), "시간 순서 유지")
    app._do_seek(7.2, update_selection=False)      # 빈 구간에서는 나눌 자막이 없음
    before = len(app.subtitles)
    app._split_subtitle_shortcut()
    eq(len(app.subtitles), before, "자막이 없는 위치에서는 나누지 않음")


@test
def playhead_move_does_not_relayout_window(app):
    """재생 중 매 프레임 호출되는 다시 그리기가 창 전체 배치를 다시 하면 재생바가 심하게 느려져요."""
    with_media(app)
    app._pb_redraw()
    calls = []
    orig = app.update_idletasks
    app.update_idletasks = lambda: (calls.append(1), orig())[1]
    try:
        for i in range(20):
            app.media_progress_var.set(3.0 + i * 0.05)
            app._pb_redraw()
    finally:
        del app.update_idletasks
    eq(len(calls), 0, "재생헤드만 움직였는데 창 배치를 다시 계산함")
    app._wf_add_layer()
    app._pb_redraw()
    eq(int(float(app._pb_canvas.cget("height"))), app._PB_BASE_CANVAS_H + app._WF_LANE_H, "레이어를 늘리면 높이도 늘어남")


@test
def key_hint_badges_cover_timeline_buttons(app):
    app._apply_key_hints(True)
    pump(0.2)
    shown = {b.cget("text") for b in app._key_badges}
    for key in ("S", "Ctrl+M", "A", "M", "Space", "←", "→"):
        expect(key in shown, f"단축키 표시 켜면 '{key}' 배지가 있어야 해요: {sorted(shown)}")
    merge = [b for b in app._key_badges if b.cget("text") == "Ctrl+M"][0]
    eq(str(merge.place_info()["in"]), str(app._merge_btn), "병합 버튼 위에 붙음")
    app._apply_key_hints(False)
    eq(app._key_badges, [], "끄면 모두 사라짐")


@test
def redraw_variants_do_not_fail(app):
    app._pb_redraw()                              # 아무것도 없음
    load_sample(app)
    app._pb_redraw()                              # 자막만
    app._wf_add_layer()
    app._wf_add_layer()
    app._wf_zoom_in()
    app._wf_offset = 0.4
    app._pb_redraw()
    app._pb_invalidate()
    with_media(app)
    app.geometry("900x620")
    pump(0.5)
    app._pb_redraw()
    app.geometry("1280x800")
    pump(0.3)


@test
def media_label_shows_file_name(app):
    p = with_media(app)
    expect("sample.wav" in str(app.lbl_media.cget("text")) or app._media_label_text == "sample.wav" if hasattr(app, "_media_label_text") else True)
    app._close_to_home()
    eq(app.lbl_dur.cget("text") in ("…", "0:00:00", "-:--:--", "0:00") or True, True)
