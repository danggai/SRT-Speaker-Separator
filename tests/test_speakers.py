"""화자: 사이드바·추가·이름 변경·삭제·순서·색·단축키 지정·자동 색 유지."""
import tkinter as tk

from harness import (Ev, app_key, cfg, click_row, ctx, eq, expect, key, load_sample, pump, slot_of, test, wait_until,
                     write_srt_file, fresh_dir)


def rows(app):
    return [w for w in app.speaker_inner.pack_slaves() if hasattr(w, "_spk_name")]


def counts(app):
    return {r._spk_name: r._cnt_lbl.cget("text") for r in rows(app)}


def colors(app):
    return {n: app._speaker_color(n) for n in app.speakers}


def make_speakers(app, n, pinned=None):
    """샘플을 연 뒤 화자를 n명으로 바꾼다 (색은 pinned만 직접 지정)."""
    load_sample(app)
    for s in app.subtitles:
        s["speaker"] = ""
    app.speakers[:] = [f"화자{i + 1}" for i in range(n)]
    app.speaker_colors.clear()
    app.speaker_colors.update(pinned or {})
    app._auto_kept = {}
    app._auto_color_cache = None
    app._render_speakers()
    app._fill_slots(app._vscroll_top)
    pump(0.2)


def drag_speaker(app, src, dst):
    """화자 사이드바에서 src번째 줄을 dst번째 줄 위치로 끌어다 놓는다 (실제 핸들러)."""
    rs = {r._spk_idx: r for r in rows(app)}
    a, b = rs[src], rs[dst]
    app._spk_drag_start(Ev(a, 5, 5), a)
    app._spk_drag_end(Ev(b, 5, b.winfo_height() // 2))
    pump(0.2)


class FakePicker:
    """색 선택 창 대신 정해 둔 색을 돌려준다."""
    result = "#445566"
    last = None

    def __init__(self, parent, color, title=""):
        FakePicker.last = (color, title)

    def show(self):
        return FakePicker.result


def use_fake_picker(result):
    from srt_editor.ui import speakers
    old = speakers._ColorPickerDialog
    FakePicker.result = result
    speakers._ColorPickerDialog = FakePicker
    return lambda: setattr(speakers, "_ColorPickerDialog", old)


# ───────── 사이드바 ─────────
@test
def sidebar_lists_speakers_in_order_with_counts(app):
    load_sample(app)
    eq([r._spk_name for r in rows(app)], ["민지", "준호"], "사이드바 순서")
    eq(counts(app), {"민지": "12", "준호": "12"}, "화자별 자막 수")
    app.subtitles[0]["speaker"] = "준호"
    app._refresh_speaker_counts()
    eq(counts(app), {"민지": "11", "준호": "13"}, "지정을 바꾸면 개수도 바뀜")
    eq(app._spk_total_lbl.cget("text"), "2", "화자 총 수")


@test
def sidebar_empty_state(app):
    app._render_speakers()
    expect(not rows(app), "화자가 없을 땐 줄이 없어야 해요")
    app.add_speaker()
    pump(0.3)
    eq(app.speakers, ["새화자1"], "화자가 없을 때 추가")


@test
def sidebar_click_assigns_to_all_selected_rows(app):
    load_sample(app)
    for s in app.subtitles:
        s["speaker"] = ""
    click_row(app, 2)
    click_row(app, 4, shift=True)
    eq(app._selected_rows, {2, 3, 4})
    app._assign_speaker_from_sidebar("준호")
    eq([app.subtitles[i]["speaker"] for i in (2, 3, 4)], ["준호"] * 3,
       "여러 줄을 골라 두고 화자를 누르면 고른 줄 모두에 지정돼야 해요 (숫자 키와 같게)")
    app._undo()
    eq([app.subtitles[i]["speaker"] for i in (2, 3, 4)], [""] * 3, "한 번에 실행 취소")


@test
def sidebar_click_single_row_and_no_selection(app):
    load_sample(app)
    app._assign_speaker_from_sidebar("준호")     # 선택이 없을 때는 아무 일도 없어야 함
    eq(app.subtitles[0]["speaker"], "민지")
    click_row(app, 1)
    app._assign_speaker_from_sidebar("민지")
    eq(app.subtitles[1]["speaker"], "민지")


# ───────── 단축키 지정 ─────────
@test
def number_keys_assign_selection_and_backtick_clears(app):
    load_sample(app)
    click_row(app, 2)
    click_row(app, 4, shift=True)
    app_key("2")
    eq([app.subtitles[i]["speaker"] for i in (2, 3, 4)], ["준호"] * 3, "숫자 2 → 둘째 화자")
    app_key("1")
    eq([app.subtitles[i]["speaker"] for i in (2, 3, 4)], ["민지"] * 3, "숫자 1 → 첫 화자")
    app_key("<grave>")
    eq([app.subtitles[i]["speaker"] for i in (2, 3, 4)], [""] * 3, "` → 해제")
    before = [s["speaker"] for s in app.subtitles]
    app_key("9")
    eq([s["speaker"] for s in app.subtitles], before, "없는 번호는 무시")
    app._undo()
    eq([app.subtitles[i]["speaker"] for i in (2, 3, 4)], ["민지"] * 3, "해제도 실행 취소")


@test
def number_key_ignored_while_typing(app):
    load_sample(app)
    click_row(app, 3)
    old = app.subtitles[3]["speaker"]
    ent = key_target_entry(app, 3)
    key(ent, "<Key-2>")
    eq(app.subtitles[3]["speaker"], old, "글자를 입력하는 중에는 화자 지정 단축키가 먹으면 안 돼요")


def key_target_entry(app, di):
    click_row(app, di, "content")
    ent = app._slot_widgets[slot_of(app, di)]["content"]
    expect(app.focus_get() is ent, "입력칸 포커스")
    return ent


@test
def advance_after_assign_option(app):
    load_sample(app, tagged_every=0)
    app.speakers[:] = ["민지", "준호"]
    app._render_speakers()
    click_row(app, 3)
    app_key("1")
    eq(app._selected_row_idx, 3, "옵션이 꺼져 있으면 그대로")
    app._set_opt("advance_after_assign", True)
    app_key("2")
    eq(app._selected_row_idx, 4, "옵션이 켜지면 다음 줄로")
    click_row(app, 6)
    click_row(app, 7, shift=True)
    app_key("1")
    eq(app._selected_rows, {6, 7}, "여러 줄을 골랐을 땐 넘어가지 않음")


# ───────── 추가·이름 변경·삭제 ─────────
@test
def add_speaker_default_names_and_inline_rename(app):
    load_sample(app)
    app.add_speaker()
    app.add_speaker()
    eq(app.speakers[2:], ["새화자1", "새화자2"], "기본 이름")
    wait_until(lambda: app._spk_edit_row is not None, 3, "이름 편집 모드")
    row = app._spk_edit_row
    eq(row._spk_name, "새화자2", "방금 추가한 화자가 편집 상태")
    row._name_var.set("수진")
    app._end_name_edit(commit=True)
    pump(0.2)
    eq(app.speakers[2:], ["새화자1", "수진"], "Enter로 이름 확정")
    app._undo()
    eq(app.speakers[2:], ["새화자1", "새화자2"], "이름 변경도 실행 취소")


@test
def rename_updates_subtitles_and_color(app):
    load_sample(app)
    restore = use_fake_picker("#778899")
    try:
        app._pick_speaker_color("민지", rows(app)[0]._dot, rows(app)[0])
    finally:
        restore()
    app.rename_speaker("민지", "수진")
    eq(app.speakers, ["수진", "준호"])
    eq([s["speaker"] for s in app.subtitles[:4]], ["수진", "준호", "수진", "준호"], "자막의 화자도 바뀜")
    eq(app._speaker_color("수진"), "#778899", "지정한 색이 새 이름으로 이어짐")
    eq(counts(app), {"수진": "12", "준호": "12"})


@test
def rename_rejects_duplicate_blank_and_noop(app):
    load_sample(app)
    undo_before = len(app._undo_stack)
    app.rename_speaker("민지", "준호")
    eq(app.speakers, ["민지", "준호"], "중복 이름")
    eq(ctx.msgs[-1][0], "showwarning", "중복이면 안내")
    app.rename_speaker("민지", "   ")
    app.rename_speaker("민지", "")
    app.rename_speaker("민지", "민지")
    eq(app.speakers, ["민지", "준호"])
    eq(len(app._undo_stack), undo_before, "바뀐 게 없으면 실행 취소 기록도 안 남김")
    app.rename_speaker("민지", "  공백있는이름  ")
    eq(app.speakers[0], "공백있는이름", "앞뒤 공백은 정리")


@test
def inline_name_edit_escape_and_duplicate_are_ignored(app):
    load_sample(app)
    app._begin_name_edit(rows(app)[0])
    rows(app)[0]._name_var.set("다른이름")
    app._end_name_edit(commit=False)
    eq(app.speakers[0], "민지", "Esc는 취소")
    app._begin_name_edit(rows(app)[0])
    rows(app)[0]._name_var.set("준호")
    app._end_name_edit(commit=True)
    eq(app.speakers, ["민지", "준호"], "중복 이름은 무시")
    app._begin_name_edit(rows(app)[0])
    app._begin_name_edit(rows(app)[1])
    eq(app._spk_edit_row._spk_name, "준호", "다른 줄을 누르면 편집이 그 줄로 옮겨감")
    open_entries = [r for r in rows(app) if r._name_entry.winfo_manager()]
    eq(len(open_entries), 1, "이름 입력칸은 하나만 열려 있어야 해요")
    app._end_name_edit(commit=False)


@test
def delete_speaker_clears_assignments_with_confirmation(app):
    load_sample(app)
    ctx.answers["askyesno"] = False
    app.delete_speaker("준호")
    eq(app.speakers, ["민지", "준호"], "거절하면 그대로")
    ctx.answers["askyesno"] = True
    app.delete_speaker("준호")
    eq(app.speakers, ["민지"])
    eq([s["speaker"] for s in app.subtitles[:4]], ["민지", "", "민지", ""], "그 화자의 자막은 '없음'")
    eq(counts(app), {"민지": "12"})
    app._undo()
    eq(app.speakers, ["민지", "준호"])
    eq([s["speaker"] for s in app.subtitles[:4]], ["민지", "준호", "민지", "준호"], "실행 취소로 지정도 복구")


@test
def speaker_context_menu_has_rename_color_delete(app):
    from srt_editor.widgets import PopupMenu
    load_sample(app)
    r = rows(app)[1]
    app._speaker_menu(Ev(r, 5, 5), r)
    pump(0.15)
    menu = PopupMenu._active
    labels = [it[1] for it in menu._items if it[0] != "sep"]
    eq(labels[:2], ["이름 변경", "색상 변경"])
    expect("'준호' 삭제" in labels, f"삭제 항목: {labels}")
    menu._destroy()


# ───────── 순서·색 ─────────
@test
def reorder_by_dragging_and_undo(app):
    make_speakers(app, 5)
    drag_speaker(app, 4, 0)
    eq(app.speakers, ["화자5", "화자1", "화자2", "화자3", "화자4"], "맨 뒤를 맨 앞으로")
    eq([r._spk_name for r in rows(app)], app.speakers, "사이드바 순서도 같음")
    eq([r._badge.itemcget("key", "text") for r in rows(app)], ["1", "2", "3", "4", "5"], "단축키 번호 다시 매김")
    drag_speaker(app, 2, 2)
    eq(app.speakers[2], "화자2", "같은 자리에 놓으면 그대로")
    app._undo()
    eq(app.speakers, ["화자1", "화자2", "화자3", "화자4", "화자5"], "실행 취소")


@test
def color_change_applies_persists_and_undo_restores(app):
    load_sample(app)
    original = app._speaker_color("준호")
    restore = use_fake_picker("#445566")
    try:
        r = rows(app)[1]
        app._pick_speaker_color("준호", r._dot, r)
    finally:
        restore()
    eq(app._speaker_color("준호"), "#445566", "바꾼 색")
    eq(r._spk_color if r.winfo_exists() else None, r._spk_color, "줄 색")
    eq(cfg().get("speaker_colors", {}).get("준호"), "#445566", "다른 파일에서도 같은 이름이면 쓰도록 설정에 저장")
    expect(app._unsaved, "색을 바꾸면 저장 안 됨 표시")
    app._undo()
    eq(app._speaker_color("준호"), original, "실행 취소하면 원래 색으로 (설정에 저장된 색이 되살아나면 안 돼요)")


@test
def color_change_cancel_and_same_color_do_nothing(app):
    load_sample(app)
    before = colors(app)
    restore = use_fake_picker(None)
    try:
        app._pick_speaker_color("민지", rows(app)[0]._dot, rows(app)[0])
    finally:
        restore()
    eq(colors(app), before, "취소")
    restore = use_fake_picker(before["민지"])
    try:
        app._pick_speaker_color("민지", rows(app)[0]._dot, rows(app)[0])
    finally:
        restore()
    expect(not app._unsaved, "같은 색을 고르면 변경이 아님")


@test
def saved_global_color_applies_to_same_name_in_other_file(app):
    load_sample(app)
    restore = use_fake_picker("#0A0B0C")
    try:
        app._pick_speaker_color("준호", rows(app)[1]._dot, rows(app)[1])
    finally:
        restore()
    app._close_to_home()
    del app._global_speaker_colors       # 앱을 다시 시작한 것처럼 설정에서 새로 읽게 함
    app._ensure_global_speaker_colors()
    p = write_srt_file(fresh_dir() / "other.srt", [{"timestamp": "00:00:01,000 --> 00:00:02,000",
                                                     "text": "다른 파일", "speaker": "준호"}])
    app._open_paths([str(p)])
    wait_until(lambda: len(app.subtitles) == 1, 5)
    eq(app._speaker_color("준호"), "#0A0B0C", "같은 이름 화자의 색")


# ───────── 자동 색 ─────────
@test
def auto_colors_distinct_and_follow_palette_order(app):
    from srt_editor.theme import SPEAKER_COLORS
    make_speakers(app, 5)
    c = colors(app)
    eq([c[f"화자{i + 1}"] for i in range(5)], SPEAKER_COLORS[:5], "처음 배정은 프리셋 순서")
    make_speakers(app, 24)
    eq(len(set(colors(app).values())), 24, "프리셋이 모자라지 않으면 모두 다른 색")
    make_speakers(app, 26)
    expect(all(v in SPEAKER_COLORS for v in colors(app).values()), "프리셋을 넘으면 순환")


@test
def auto_colors_stay_with_speaker_when_reordered(app):
    make_speakers(app, 11, pinned={"화자2": "#FF00AA", "화자5": "#00AAFF", "화자9": "#AAFF00"})
    before = colors(app)
    drag_speaker(app, 10, 0)
    drag_speaker(app, 3, 7)
    eq(colors(app), before, "순서를 바꿔도 각 화자의 색은 그대로여야 해요")
    app._undo()
    app._undo()
    eq(colors(app), before, "실행 취소 후에도")


@test
def auto_colors_stable_across_rename_delete_and_new_speaker(app):
    make_speakers(app, 6)
    before = colors(app)
    app.rename_speaker("화자3", "새이름")
    eq(colors(app)["새이름"], before["화자3"], "이름을 바꿔도 색 유지")
    ctx.answers["askyesno"] = True
    app.delete_speaker("화자2")
    now = colors(app)
    expect(all(now[n] == before[n] for n in now if n in before), "삭제해도 나머지 색 유지")
    app.add_speaker()
    pump(0.3)
    app._end_name_edit(commit=False)
    new = [n for n in app.speakers if n.startswith("새화자")][0]
    eq(colors(app)[new], before["화자2"], "삭제된 화자의 빈 색을 새 화자가 씀")
    expect(colors(app)[new] not in [colors(app)[n] for n in app.speakers if n != new], "기존 화자와 다른 색")


@test
def auto_colors_saved_and_restored_with_file(app):
    from srt_editor import srt_io
    make_speakers(app, 11, pinned={"화자2": "#FF00AA"})
    drag_speaker(app, 10, 0)
    before = colors(app)
    path = str(fresh_dir() / "colors.srt")
    app._unsaved = True
    ctx.paths[:] = [path]
    app.save_file_as()
    meta = srt_io.read_srt_meta(path)
    eq(set(meta["auto_colors"]), set(app.speakers) - {"화자2"}, "지정하지 않은 화자의 자동 색이 저장됨")
    eq(meta["speaker_colors"], {"화자2": "#FF00AA"}, "지정한 색은 따로")
    app._open_paths([path])
    wait_until(lambda: app.speakers == list(before) or app.speakers[:11] == list(before), 5)
    eq({n: app._speaker_color(n) for n in before}, before, "다시 열어도 같은 색")


@test
def auto_color_conflict_with_pinned_color_is_reassigned(app):
    make_speakers(app, 4, pinned={"화자1": "#D63838"})   # 첫 프리셋을 직접 지정
    c = colors(app)
    eq(c["화자1"], "#D63838")
    expect(c["화자2"] != "#D63838" and len({c[n] for n in app.speakers}) == 4, f"자동 색이 지정색과 겹침: {c}")


@test
def many_speakers_show_all_buttons_and_sidebar_scrolls(app):
    make_speakers(app, 15)
    app._auto_resize_speaker_col()
    app._relayout()
    app._fill_slots(0)
    pump(0.3)
    wi = app._slot_widgets[0]
    shown = [i for i in range(15) if app.canvas.itemcget(f"pk0_{i}", "state") != "hidden"]
    eq(len(shown), 15, "화자 칸이 자동으로 넓어져서 모든 화자 버튼이 보여야 해요")
    app.update_idletasks()
    inner_h = app.speaker_inner.winfo_reqheight()
    view_h = app._spk_canvas.winfo_height()
    expect(inner_h > view_h, "화자 15명이면 사이드바가 스크롤돼야 해요")
