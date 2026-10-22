"""키보드로 시간 맞추기(Q·W, Alt+←/→)와 편집 중 Esc 취소."""
from harness import steps, app_key, ctx, eq, expect, load_sample, near, pump, slot_of, test


def times(app, i):
    return app._ts_cache[i]


def q_w_set_start_and_end_to_playhead_with_undo(app):
    load_sample(app, with_wav=True)   # 자막 3: 7.5~9.5초
    app._select_row(3, seek=False)
    app._do_seek(7.8, update_selection=False)
    app_key("q")
    near(times(app, 3)[0], 7.8, 0.002, "Q: 시작을 재생 위치로")
    app._do_seek(9.2, update_selection=False)
    app_key("w")
    near(times(app, 3)[1], 9.2, 0.002, "W: 끝을 재생 위치로")
    eq(app._selected_row_idx, 3, "멈춘 상태에서는 그 줄에 그대로")
    expect(app._unsaved, "수정 표시")
    app._undo()
    near(times(app, 3)[1], 9.5, 0.002, "실행 취소 한 번에 끝만 되돌림")
    near(times(app, 3)[0], 7.8, 0.002)
    app._select_row(3, seek=False)
    app._do_seek(9.7, update_selection=False)
    app_key("q")
    near(times(app, 3)[0], 7.8, 0.002, "끝보다 뒤면 바꾸지 않음")
    app._do_seek(9.0, update_selection=False)
    app_key("w")
    app._do_seek(9.3, update_selection=False)
    app_key("w")
    app_key("<Control-z>")
    near(times(app, 3)[1], 9.0, 0.002, "W를 다시 찍고 Ctrl+Z: 바로 전에 찍은 자리로 (한 번씩 되돌림)")
    app_key("<Control-z>")
    near(times(app, 3)[1], 9.5, 0.002, "한 번 더: 원래대로")


def w_while_playing_moves_to_next_line(app):
    load_sample(app, with_wav=True)
    app._select_row(2, seek=False)
    app._do_seek(6.5, update_selection=False)
    app._media_play_pause()
    pump(0.2)
    app_key("w", 0.05)
    expect(abs(times(app, 2)[1] - app.media_progress_var.get()) < 0.3, "재생 위치로 끝을 찍음")
    eq(app._selected_row_idx, 3, "재생 중이면 다음 줄로 넘어가 이어서 찍기")
    app._media_play_pause()


def alt_arrows_nudge_start_and_end(app):
    load_sample(app, with_wav=True)
    app._select_row(4, seek=False)   # 10.0~12.0초
    for _ in range(3):
        app_key("<Alt-Right>", 0.02)
    near(times(app, 4)[0], 10.15, 0.002, "Alt+→ 3번: 시작 0.15초 뒤로")
    app_key("<Alt-Shift-Left>", 0.02)
    near(times(app, 4)[1], 11.95, 0.002, "Alt+Shift+←: 끝 0.05초 앞으로")
    app._undo()
    near(times(app, 4)[1], 12.0, 0.002, "끝 조정 되돌림")
    near(times(app, 4)[0], 10.15, 0.002)
    app._undo()
    near(times(app, 4)[0], 10.0, 0.002, "연달아 민 시작은 실행 취소 한 번에")


def esc_while_editing_discards_changes(app):
    load_sample(app)
    app._select_row(5, seek=False)
    before = app.subtitles[5]["text"]
    app_key("<Return>")
    s = slot_of(app, 5)
    ent = app._slot_widgets[s]["content"]
    expect(app.focus_get() is ent, "Enter로 편집 시작")
    ent.insert("end", "잘못친글자q")
    pump(0.05)
    eq(app.subtitles[5]["text"], before, "입력 중에는 아직 저장 안 됨 (q도 글자로)")
    ent.event_generate("<Escape>")
    pump(0.15)
    eq(app.subtitles[5]["text"], before, "Esc: 고친 내용 버림")
    expect(app.focus_get() is not ent, "표로 돌아감")
    expect(not app._unsaved, "수정 표시 없음")
    eq(app.canvas.itemcget(f"{app._slot_widgets[s]['tag']}txt", "text")[:3], before[:3], "화면 글자도 원래대로")
    expect(not ctx.tk_errors, f"Tk 오류: {ctx.tk_errors[:1]}")


@test
def touching_edges_move_together(app):
    from harness import ts
    load_sample(app, with_wav=True)   # 자막 3: 7.5~9.5, 자막 4: 10.0~12.0
    app.subtitles[3]["timestamp"] = f"{ts(7.5)} --> {ts(10.0)}"   # 3번 끝을 4번 시작에 붙임
    app._rebuild_ts_cache()
    app._select_row(3, seek=False)
    app._do_seek(10.3, update_selection=False)
    app_key("w")
    near(times(app, 3)[1], 10.3, 0.002, "W: 3번 끝")
    near(times(app, 4)[0], 10.3, 0.002, "붙어 있던 4번 시작도 같이")
    app._undo()
    near(times(app, 4)[0], 10.0, 0.002, "실행 취소 한 번에 둘 다 되돌림")
    near(times(app, 3)[1], 10.0, 0.002)
    app._select_row(4, seek=False)
    app_key("<Alt-Left>", 0.02)
    near(times(app, 4)[0], 9.95, 0.002, "Alt+←: 4번 시작")
    near(times(app, 3)[1], 9.95, 0.002, "붙은 3번 끝도 같이")
    app._do_seek(3.0, update_selection=False)
    app_key("<Control-Right>", 0.02)
    near(app.media_progress_var.get(), 3.05, 0.01, "Ctrl+→: 재생 위치 0.05초")
    near(times(app, 4)[0], 9.95, 0.002, "자막 시간은 그대로")
    app_key("<Control-Left>", 0.02)
    near(app.media_progress_var.get(), 3.0, 0.01, "Ctrl+←: 0.05초 뒤로")
    app._select_row(5, seek=False)   # 5번은 4번과 떨어져 있음
    app_key("<Alt-Left>", 0.02)
    near(times(app, 4)[1], 12.0, 0.002, "떨어진 줄은 그대로")
    app._set_opt("link_edges", False)
    app._select_row(4, seek=False)
    app_key("<Alt-Left>", 0.02)
    near(times(app, 3)[1], 9.95, 0.002, "설정을 끄면 따로 움직임")
    app._set_opt("link_edges", True)


@test
def dragging_shared_edge_separates_but_ctrl_drag_moves_neighbor(app):
    from harness import ts, Ev
    load_sample(app, with_wav=True)
    app.subtitles[3]["timestamp"] = f"{ts(7.5)} --> {ts(10.0)}"
    app._rebuild_ts_cache()
    app._wf_img_cache = None
    app._pb_redraw()
    pump(0.2)
    pb = app._pb_canvas
    dur = app._timeline_duration() if hasattr(app, "_timeline_duration") else app.player.duration
    cw = pb.winfo_width()
    x = app._wf_ratio_to_x(10.0 / dur, cw) + 1
    y = int(app._WF_LANE_H / 2)
    hit = app._wf_hit_test(x, y)
    eq(hit["type"], "handle", f"경계 핸들 판정 {hit}")
    x2 = app._wf_ratio_to_x(10.6 / dur, cw)

    def drag(state):
        app._pb_press(Ev(pb, x, y, state))
        for k in range(1, 5):
            app._pb_drag(Ev(pb, x + (x2 - x) * k // 4, y, state))
        app._pb_release(Ev(pb, x2, y, state))
        pump(0.1)

    drag(0)
    moved = times(app, 4)[0] if hit["idx"] == 4 else times(app, 3)[1]
    expect(abs(moved - 10.0) > 0.3, f"끈 경계가 움직임 ({times(app, 3)}, {times(app, 4)})")
    other = times(app, 3)[1] if hit["idx"] == 4 else times(app, 4)[0]
    near(other, 10.0, 0.002, "그냥 드래그: 옆 줄은 그대로 (떨어짐)")
    app._undo()
    app._wf_on_motion(Ev(pb, x, y, 0x0004))
    pump(0.05)
    eq(len(pb.find_withtag("link_bar")), 2, "Ctrl 누르고 붙은 경계 위: 두 줄에 보라 막대")
    app._wf_on_motion(Ev(pb, x, y))
    pump(0.05)
    eq(len(pb.find_withtag("link_bar")), 0, "Ctrl 떼면 사라짐")
    app._pb_press(Ev(pb, x, y, 0x0004))
    app._pb_drag(Ev(pb, x2, y, 0x0004))
    pump(0.05)
    eq(len(pb.find_withtag("link_bar")), 2, "Ctrl+드래그 중에도 두 막대")
    expect(pb.find_withtag("link_delta"), "옮긴 시간 표시")
    expect(app._wf_img_cache[0][-1] is not None, "드래그 중 블록(배경)도 새 위치로 다시 그림")
    app._pb_release(Ev(pb, x, y, 0x0004))
    drag(0x0004)
    near(times(app, 3)[1], times(app, 4)[0], 0.002, "Ctrl+드래그: 맞닿은 두 줄이 같이 움직임")
    expect(abs(times(app, 3)[1] - 10.0) > 0.3, "Ctrl+드래그로 경계가 움직임")
    app._undo()
    app._select_row(0, seek=False)
    app._pb_press(Ev(pb, x, y, 0x0004))
    app._pb_release(Ev(pb, x, y, 0x0004))
    eq(app._selected_rows, {0, hit["idx"]}, "경계 Ctrl+클릭은 선택 추가")


@test
def edge_keys(app):
    steps(q_w_set_start_and_end_to_playhead_with_undo, w_while_playing_moves_to_next_line, alt_arrows_nudge_start_and_end, esc_while_editing_discards_changes)
