"""키보드로 시간 맞추기(Q·W, Alt+←/→)와 편집 중 Esc 취소."""
from harness import app_key, ctx, eq, expect, load_sample, near, pump, slot_of, test


def times(app, i):
    return app._ts_cache[i]


@test
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


@test
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


@test
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


@test
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
