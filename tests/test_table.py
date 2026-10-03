"""자막 목록: 선택·키보드 이동·텍스트/시간 편집·추가·삭제·복사·붙여넣기·나누기·병합·실행 취소·검색·스크롤."""
import time

from harness import (Ev, app_key, click_row, col_x, ctx, eq, expect, flat, key, load_sample, near, pump, slot_of,
                     tap, test, wait_until)


def _entry(app, di, name="content"):
    s = slot_of(app, di)
    expect(s is not None, f"{di}번 줄이 화면에 없어요")
    return app._slot_widgets[s][name]


def begin_text_edit(app, di):
    click_row(app, di, "content")
    ent = _entry(app, di)
    expect(app.focus_get() is ent, f"{di}번 줄 자막 칸을 눌렀는데 입력칸에 포커스가 없어요")
    return ent


def finish_edit(app, ent):
    key(ent, "<Return>")
    pump(0.15)


# ───────── 선택 ─────────
@test
def click_selects_single_row(app):
    load_sample(app)
    click_row(app, 3)
    eq((app._selected_row_idx, app._selected_rows), (3, {3}))
    click_row(app, 7)
    eq((app._selected_row_idx, app._selected_rows), (7, {7}), "다른 줄을 누르면 앞 선택은 풀려야 해요")


@test
def ctrl_click_toggles_and_shift_click_ranges(app):
    load_sample(app)
    click_row(app, 1)
    click_row(app, 5, ctrl=True)
    eq(app._selected_rows, {1, 5}, "Ctrl+클릭은 추가")
    click_row(app, 5, ctrl=True)
    eq(app._selected_rows, {1}, "Ctrl+클릭을 다시 하면 해제")
    click_row(app, 8, shift=True)
    eq(app._selected_rows, set(range(1, 9)), "Shift+클릭은 기준 줄부터 범위")


@test
def drag_selects_range_and_autoscrolls(app):
    load_sample(app, n=60)
    c = app.canvas
    y = lambda s: s * app.ROW_H + app.ROW_H // 2
    app._canvas_press(Ev(c, col_x(app, "num"), y(2)))
    app._canvas_drag_motion(Ev(c, col_x(app, "num"), y(6)))
    eq(app._selected_rows, set(range(2, 7)), "드래그 범위")
    app._canvas_drag_end(Ev(c, col_x(app, "num"), y(6)))
    app._canvas_drag_motion(Ev(c, col_x(app, "num"), y(9)))
    eq(app._selected_rows, set(range(2, 7)), "마우스를 뗀 뒤에는 선택이 안 바뀌어야 해요")


@test
def keyboard_navigation(app):
    load_sample(app, n=60)
    click_row(app, 0)
    for _ in range(3):
        app_key("<Down>")
    eq(app._selected_row_idx, 3, "아래 방향키")
    app_key("<Up>")
    eq(app._selected_row_idx, 2, "위 방향키")
    app_key("<End>")
    eq(app._selected_row_idx, 59, "End")
    app_key("<Home>")
    eq(app._selected_row_idx, 0, "Home")
    page = app._page_size()
    app_key("<Next>")
    eq(app._selected_row_idx, page, "Page Down")
    app_key("<Prior>")
    eq(app._selected_row_idx, 0, "Page Up")
    app_key("<Up>")
    eq(app._selected_row_idx, 0, "맨 위에서 위로 가도 그대로")


@test
def shift_arrows_extend_and_escape_collapses(app):
    load_sample(app)
    click_row(app, 5)
    app_key("<Shift-Down>")
    app_key("<Shift-Down>")
    eq(app._selected_rows, {5, 6, 7}, "Shift+아래")
    app_key("<Shift-Up>")
    eq(app._selected_rows, {5, 6}, "Shift+위로 줄임")
    app_key("<Escape>")
    eq(len(app._selected_rows), 1, "Esc는 여러 줄 선택을 하나로")


@test
def select_all(app):
    load_sample(app)
    click_row(app, 2)
    app_key("<Control-a>")
    eq(app._selected_rows, set(range(24)), "Ctrl+A")


# ───────── 편집 ─────────
@test
def edit_text_commits_with_enter_and_undo_redo(app):
    load_sample(app)
    old = app.subtitles[2]["text"]
    ent = begin_text_edit(app, 2)
    ent.delete(0, "end")
    ent.insert(0, "새로 고친 자막")
    finish_edit(app, ent)
    eq(app.subtitles[2]["text"], "새로 고친 자막", "Enter로 확정")
    expect(app._unsaved, "수정했는데 '저장 안 됨'이 아님")
    expect(not app._slot_widgets[slot_of(app, 2)]["_txt_editing"], "확정 뒤 입력칸이 닫혀야 해요")
    app._undo()
    eq(app.subtitles[2]["text"], old, "실행 취소")
    app._redo()
    eq(app.subtitles[2]["text"], "새로 고친 자막", "다시 실행")


@test
def edit_text_commits_when_clicking_another_row(app):
    load_sample(app)
    ent = begin_text_edit(app, 2)
    ent.delete(0, "end")
    ent.insert(0, "다른 줄 누르기 전 입력")
    click_row(app, 4, "num")
    pump(0.2)
    eq(app.subtitles[2]["text"], "다른 줄 누르기 전 입력", "다른 줄을 눌러도 입력한 내용은 저장돼야 해요")
    eq(app._selected_row_idx, 4)


@test
def edit_text_keeps_long_and_special_text(app):
    load_sample(app)
    long = "아주 긴 자막 " * 40 + "끝"
    ent = begin_text_edit(app, 1)
    ent.delete(0, "end")
    ent.insert(0, long)
    finish_edit(app, ent)
    eq(app.subtitles[1]["text"], long, "긴 글자가 잘려 저장됨")
    shown = app.canvas.itemcget(app._slot_widgets[slot_of(app, 1)]["tag"] + "txt", "text")
    expect(shown.endswith("…") and len(shown) < len(long), f"화면에는 줄임표로: {shown[-6:]!r}")
    ent2 = begin_text_edit(app, 1)
    eq(ent2.get(), long, "편집을 열면 전체 글자가 보여야 해요")
    app.focus_set()
    pump(0.2)
    eq(app.subtitles[1]["text"], long, "열었다 닫아도 그대로")


@test
def edit_time_valid_updates_cache_and_invalid_is_rejected(app):
    load_sample(app)
    app._select_row(3, seek=False)
    click_row(app, 3, "time")
    wi = app._slot_widgets[slot_of(app, 3)]
    expect(wi["_ts_editing"], "선택된 줄의 시간을 누르면 편집이 열려야 해요")
    old = app.subtitles[3]["timestamp"]
    wi["ts_s_var"].set("00:00:07,100")
    wi["ts_e_var"].set("00:00:08,900")
    app.focus_force()
    app.focus_set()
    wait_until(lambda: not wi["_ts_editing"], 3, "편집 닫힘")
    eq(app.subtitles[3]["timestamp"], "00:00:07,100 --> 00:00:08,900", "유효한 시간 저장")
    near(app._ts_cache[3][0], 7.1, what="캐시 시작")
    near(app._ts_cache[3][1], 8.9, what="캐시 끝")
    # 잘못된 값
    app._select_row(3, seek=False)
    click_row(app, 3, "time")
    wi["ts_s_var"].set("abc")
    app.focus_set()
    wait_until(lambda: not wi["_ts_editing"], 3, "편집 닫힘")
    eq(app.subtitles[3]["timestamp"], "00:00:07,100 --> 00:00:08,900", "잘못된 값은 저장되면 안 돼요")


@test
def double_click_time_opens_edit_even_if_not_selected(app):
    load_sample(app)
    s = slot_of(app, 5)
    y = s * app.ROW_H + app.ROW_H // 2
    app._canvas_double(Ev(app.canvas, col_x(app, "time"), y))
    expect(app._slot_widgets[s]["_ts_editing"], "더블클릭으로 시간 편집")


@test
def only_one_edit_open_at_a_time(app):
    load_sample(app)
    begin_text_edit(app, 2)
    begin_text_edit(app, 4)
    open_rows = [i for i, w in enumerate(app._slot_widgets) if w["_txt_editing"] or w["_ts_editing"]]
    eq(len(open_rows), 1, f"입력칸이 여러 개 열려 있음: {open_rows}")


# ───────── 추가·삭제·복사 ─────────
@test
def add_row_after_selected_with_undo(app):
    load_sample(app)
    prev_end = app.subtitles[2]["timestamp"].split("-->")[1].strip()
    app.add_row(after_idx=2)
    eq(len(app.subtitles), 25)
    eq(app.subtitles[3]["timestamp"], f"{prev_end} --> {prev_end}", "앞 자막 끝에 이어서")
    eq((app.subtitles[3]["text"], app.subtitles[3]["speaker"]), ("", ""))
    eq(app._selected_row_idx, 3, "새 줄이 선택돼야 해요")
    app._undo()
    eq(len(app.subtitles), 24, "실행 취소")


@test
def add_row_at_time_keeps_time_order_and_limits_length(app):
    load_sample(app)
    app.add_row_at_time(6.0, duration=5.0)   # 자막 2(5.0~7.0)와 자막 3(7.5~) 사이: 6.0에 시작하면 3번 앞
    new = [s for s in app.subtitles if s["timestamp"].startswith("00:00:06,000")]
    eq(len(new), 1, "삽입된 자막")
    i = app.subtitles.index(new[0])
    eq(i, 3, "시간 순서에 맞는 위치 (시작 6.0초 뒤의 첫 자막 앞)")
    expect(new[0]["timestamp"].endswith("00:00:07,500"), f"다음 자막 시작 전까지만: {new[0]['timestamp']}")
    starts = [s[0] for s in app._ts_cache]
    eq(starts, sorted(starts), "시간 순서")


@test
def add_subtitle_here_without_media_uses_selected_row(app):
    load_sample(app)
    click_row(app, 4)
    app._add_subtitle_here()
    eq(len(app.subtitles), 25)
    eq(app._selected_row_idx, 5, "선택한 줄 다음에 추가")


@test
def delete_selected_rows_with_undo(app):
    load_sample(app)
    click_row(app, 3)
    click_row(app, 5, shift=True)
    texts = [s["text"] for s in app.subtitles]
    app._on_delete()
    eq(len(app.subtitles), 21, "3줄 삭제")
    eq([s["text"] for s in app.subtitles], texts[:3] + texts[6:], "나머지 순서")
    eq(app._selected_rows, set(), "삭제 후 선택 해제")
    app._undo()
    eq([s["text"] for s in app.subtitles], texts, "실행 취소로 복구")


@test
def delete_ignored_while_typing(app):
    load_sample(app)
    ent = begin_text_edit(app, 2)
    ent.focus_force()
    app._on_delete()
    eq(len(app.subtitles), 24, "글자를 입력하는 중에는 Delete가 줄을 지우면 안 돼요")


@test
def copy_paste_cut(app):
    load_sample(app)
    click_row(app, 1)
    click_row(app, 2, shift=True)
    plain = lambda subs: [{k: v for k, v in s.items() if k != "_lane"} for s in subs]   # _lane은 내부 값
    orig = plain([app.subtitles[1], app.subtitles[2]])
    app._on_copy(None)
    click_row(app, 10)
    app._on_paste(None)
    eq(len(app.subtitles), 26, "2줄 붙여넣기")
    eq(plain(app.subtitles[11:13]), orig, "붙여넣은 내용")
    eq(app._selected_rows, {11, 12}, "붙여넣은 범위 선택")
    app._undo()
    eq(len(app.subtitles), 24)
    click_row(app, 0)
    app._on_cut(None)
    eq(len(app.subtitles), 23, "잘라내기")
    click_row(app, 5)
    app._on_paste(None)
    eq(len(app.subtitles), 24, "잘라낸 것을 붙여넣기")


@test
def paste_with_empty_clipboard_does_nothing(app):
    load_sample(app)
    click_row(app, 2)
    app._on_paste(None)
    eq(len(app.subtitles), 24)


# ───────── 나누기·병합 ─────────
@test
def split_subtitle_at_position(app):
    load_sample(app)
    # 자막 2: 5.0 ~ 7.0
    ok = app.split_subtitle_at(2, 6.0)
    expect(ok, "나누기 실패")
    eq(len(app.subtitles), 25)
    eq(app.subtitles[2]["timestamp"], "00:00:05,000 --> 00:00:06,000", "앞부분")
    eq(app.subtitles[3]["timestamp"], "00:00:06,000 --> 00:00:07,000", "뒷부분")
    eq(app.subtitles[3]["text"], app.subtitles[2]["text"], "양쪽 다 같은 글자")
    eq(app.subtitles[3]["speaker"], app.subtitles[2]["speaker"], "양쪽 다 같은 화자")
    expect(not app.split_subtitle_at(2, 5.01), "너무 가장자리에서는 나눌 수 없어야 해요")
    expect(not app.split_subtitle_at(2, 99.0), "자막 밖 위치")
    expect(not app.split_subtitle_at(99, 1.0), "없는 줄")
    app._undo()
    eq(len(app.subtitles), 24)


@test
def split_keeps_layer_of_original(app):
    load_sample(app)
    app._wf_add_layer()      # 레이어가 2개 이상이어야 1번 레이어가 유효해요
    app.subtitles[2]["_lane"] = 1
    app.split_subtitle_at(2, 6.0)
    eq(app.subtitles[3].get("_lane"), 1, "뒷부분도 같은 레이어")


@test
def split_time_never_produces_invalid_timestamp(app):
    load_sample(app)
    import re
    pos = 5.0 + 0.9996 + 0.7     # 6.6996 → 소수 셋째 자리에서 반올림 경계
    app.split_subtitle_at(2, pos)
    for s in app.subtitles[2:4]:
        expect(re.fullmatch(r"\d\d:\d\d:\d\d,\d{3} --> \d\d:\d\d:\d\d,\d{3}", s["timestamp"]), s["timestamp"])


@test
def merge_selected_rows(app):
    load_sample(app)
    # 0(민지) 1(준호) 2(민지) 선택 → 민지가 더 오래 말함
    click_row(app, 0)
    click_row(app, 2, shift=True)
    texts = [app.subtitles[i]["text"] for i in range(3)]
    app.merge_selected()
    eq(len(app.subtitles), 22)
    eq(app.subtitles[0]["timestamp"], "00:00:00,000 --> 00:00:07,000", "처음~끝 시간")
    eq(app.subtitles[0]["text"], " ".join(texts), "글자는 띄어쓰기로 이어 붙임")
    eq(app.subtitles[0]["speaker"], "민지", "가장 오래 말한 화자")
    app._undo()
    eq(len(app.subtitles), 24)
    eq([app.subtitles[i]["text"] for i in range(3)], texts, "실행 취소로 복구")


@test
def merge_single_selection_merges_with_next_and_last_row_is_ignored(app):
    load_sample(app)
    click_row(app, 4)
    app.merge_selected()
    eq(len(app.subtitles), 23, "하나만 고르면 다음 줄과 합침")
    click_row(app, 22)
    app.merge_selected()
    eq(len(app.subtitles), 23, "마지막 줄은 합칠 상대가 없음")


# ───────── 화자 버튼·메뉴 ─────────
@test
def pill_click_assigns_speaker_with_undo(app):
    load_sample(app)
    app.subtitles[2]["speaker"] = ""
    app._redraw_slot_for(2)
    s = slot_of(app, 2)
    wi = app._slot_widgets[s]
    eq(wi["pill_values"][:2], ["민지", "준호"], "화자 버튼 순서 (화자 목록과 같음)")
    bbox = app.canvas.bbox(f"{wi['tag']}pb1")
    cx, cy = (bbox[0] + bbox[2]) // 2, (bbox[1] + bbox[3]) // 2
    app.canvas.event_generate("<Motion>", x=cx, y=cy)   # Tk가 '마우스 아래 항목'을 알아내려면 이동 이벤트가 필요
    pump(0.05)
    app._canvas_press(Ev(app.canvas, cx, cy))
    pump(0.15)
    eq(app.subtitles[2]["speaker"], "준호", "버튼으로 지정")
    app._undo()
    eq(app.subtitles[2]["speaker"], "", "실행 취소")


@test
def context_menu_lists_actions_and_speakers(app):
    from srt_editor.widgets import PopupMenu
    load_sample(app)
    click_row(app, 3)
    y = slot_of(app, 3) * app.ROW_H + app.ROW_H // 2
    app._canvas_right_press(Ev(app.canvas, col_x(app, "num"), y))
    pump(0.2)
    menu = PopupMenu._active
    expect(menu is not None, "우클릭 메뉴가 안 뜸")
    labels = [it[1] for it in menu._items if it[0] != "sep"]
    for want in ("잘라내기", "복사", "붙여넣기", "위에 행 추가", "아래에 행 추가", "삭제", "병합"):
        expect(any(want in l for l in labels), f"메뉴에 '{want}'가 없음: {labels}")
    cascade = [it for it in menu._items if it[0] == "cascade"][0]
    sub = [it[1] for it in cascade[3]._items if it[0] == "cmd"]
    eq(sub, ["(없음)", "민지", "준호"], "화자 변경 하위 메뉴")
    cascade[3]._items[2][2]()      # '민지' 선택
    eq(app.subtitles[3]["speaker"], "민지", "메뉴로 화자 변경")
    menu._destroy()


@test
def row_text_is_selected_row_highlighted_and_playing_rows_follow_position(app):
    load_sample(app)
    app._update_playback_highlight(5.5)    # 자막 2: 5.0~7.0
    eq(app._playing_rows, {2}, "재생 위치의 자막")
    app._update_playback_highlight(7.2)    # 자막 사이 빈 구간
    eq(app._playing_rows, set(), "빈 구간에서는 강조 해제")
    eq(app._get_rows_at(0.0), {0})


# ───────── 열 너비 ─────────
@test
def header_drag_resizes_columns_within_limits(app):
    load_sample(app)
    before = dict(app._col_w)
    pos = app._get_col_positions()
    hdr = app._hdr_canvas
    xt = pos["time"][0] + pos["time"][1]
    app._hdr_press(Ev(hdr, xt, 10))
    eq(app._drag_col, None, "시간 열 너비는 고정이라 드래그가 시작되면 안 돼요")
    x = pos["content"][0] + pos["content"][1]   # 자막 | 화자 경계
    app._hdr_press(Ev(hdr, x, 10))
    app._hdr_b1motion(Ev(hdr, x + 30, 10))
    app._hdr_release(Ev(hdr, x + 30, 10))
    eq(app._col_w["speaker"], before["speaker"] - 30, "경계를 오른쪽으로 끌면 화자 칸이 줄어듦")
    eq(app._col_w["time"], before["time"], "시간 열은 그대로")
    x = app._get_col_positions()["content"][0] + app._get_col_positions()["content"][1]
    app._hdr_press(Ev(hdr, x, 10))
    app._hdr_b1motion(Ev(hdr, x + 2000, 10))
    app._hdr_release(Ev(hdr, x + 2000, 10))
    expect(app._col_w["speaker"] >= 60, "화자 칸이 최소 너비 아래로 줄었어요")
    expect(app._get_col_positions()["content"][1] >= 60, "자막 칸이 사라졌어요")


# ───────── 실행 취소 ─────────
@test
def undo_stack_is_capped_and_redo_cleared_by_new_edit(app):
    load_sample(app)
    for i in range(60):
        app._push_undo()
        app.subtitles[0]["text"] = f"v{i}"
    expect(len(app._undo_stack) <= app._UNDO_MAX, f"실행 취소 기록이 {len(app._undo_stack)}개")
    app._undo()
    app._undo()
    expect(app._redo_stack, "다시 실행 기록")
    app._push_undo()
    eq(app._redo_stack, [], "새로 편집하면 다시 실행 기록은 비워짐")


@test
def undo_redo_on_empty_stacks_is_safe(app):
    load_sample(app)
    app._undo()
    app._redo()
    eq(len(app.subtitles), 24)


# ───────── 검색 ─────────
@test
def search_finds_text_and_speaker_and_wraps(app):
    load_sample(app)
    app._open_search()
    app._search_var.set("회의")
    pump(0.2)
    hits = [i for i, s in enumerate(app.subtitles) if "회의" in s["text"]]
    eq(app._search_hits, hits, "글자 검색 결과")
    eq(app._search_count.cget("text"), f"1 / {len(hits)}")
    eq(app._selected_row_idx, hits[0], "첫 결과가 선택됨")
    for _ in range(len(hits)):
        app._search_step(1)
    eq(app._selected_row_idx, hits[0], "끝에서 다음으로 가면 처음으로")
    app._search_step(-1)
    eq(app._selected_row_idx, hits[-1], "처음에서 이전으로 가면 끝으로")
    app._search_var.set("준호")
    pump(0.2)
    expect(len(app._search_hits) >= 10, "화자 이름으로도 검색")
    app._search_var.set("없는검색어xyz")
    pump(0.2)
    eq(app._search_count.cget("text"), "없음")
    app._search_var.set("")
    pump(0.1)
    eq(app._search_count.cget("text"), "", "검색어를 지우면 표시도 지움")
    app._close_search()
    expect(not app._search_bar.winfo_ismapped(), "검색 막대가 닫혀야 해요")


@test
def search_is_case_insensitive_and_handles_regex_chars(app):
    load_sample(app)
    app.subtitles[4]["text"] = "Hello (World) [x] 20% a.b"
    app._open_search()
    app._search_var.set("hello (world")
    pump(0.2)
    eq(app._search_hits, [4], "대소문자 무시")
    app._search_var.set("a.b")
    pump(0.2)
    eq(app._search_hits, [4], "정규식 기호는 글자 그대로")
    app._search_var.set("[x]")
    pump(0.2)
    eq(app._search_hits, [4])
    app._close_search()


# ───────── 큰 파일·스크롤 ─────────
@test
def large_file_virtual_scroll(app):
    t0 = time.time()
    load_sample(app, n=3000)
    expect(time.time() - t0 < 15, f"3000줄 파일 열기가 너무 느려요: {time.time() - t0:.1f}초")
    n_slots = len(app._slot_widgets)
    expect(n_slots < 60, f"화면에 보이는 것만 만들어야 해요 (슬롯 {n_slots}개)")
    app._vscroll_to(2500)
    eq(app._slot_data[0], 2500, "스크롤 후 맨 윗줄")
    eq(app.canvas.itemcget(app._slot_widgets[0]["tag"] + "num", "text"), "2501", "화면에 그려진 번호")
    app._scroll_to_row(10)
    expect(slot_of(app, 10) is not None, "목록 위쪽으로 돌아가기")
    app._vscroll_to(99999)
    eq(app._vscroll_top, 2999, "끝을 넘어 스크롤해도 범위 안")
    app._vscroll_to(-5)
    eq(app._vscroll_top, 0)
    t0 = time.time()
    for k in range(60):
        app._vscroll_to(k * 40)
    expect((time.time() - t0) / 60 < 0.15, f"스크롤 한 번에 {(time.time() - t0) / 60 * 1000:.0f}ms")


@test
def scrollbar_thumb_tracks_position(app):
    load_sample(app, n=300)
    app._vscroll_to(0)
    top0 = app.vsb.get()[0]
    app._vscroll_to(150)
    top1 = app.vsb.get()[0]
    near(top0, 0.0, 1e-9)
    near(top1, 0.5, 0.02, "중간쯤")
    app._update_vsb()
    near(app.vsb.get()[0], top1, 1e-9)


@test
def window_resize_keeps_rows_filled(app):
    load_sample(app, n=100)
    app.geometry("1000x600")
    pump(0.6)
    small = len([d for d in app._slot_data if d >= 0])
    app.geometry("1400x1000")
    pump(0.8)
    big = len([d for d in app._slot_data if d >= 0])
    expect(big > small, f"창이 커졌는데 줄 수가 안 늘었어요 ({small} → {big})")
    first, last = app._slot_data[0], max(app._slot_data)
    eq(sorted(d for d in app._slot_data if d >= 0), list(range(first, last + 1)), "줄이 빈틈없이 이어져야 해요")


@test
def empty_state_has_no_errors(app):
    app._update_count()
    app._pb_redraw()
    app._render_speakers()
    app._fill_slots(0)
    app._on_delete()
    app._on_copy(None)
    app._on_paste(None)
    app.merge_selected()
    app.add_row()
    eq(len(app.subtitles), 1, "빈 상태에서 줄 추가")
