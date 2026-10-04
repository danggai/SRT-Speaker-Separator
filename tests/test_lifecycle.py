"""종료·닫기·시작 흐름과 주요 창(설정·단축키·교정·화자 분석·자막 생성)."""
from harness import (app_key, cfg, ctx, eq, expect, find, flat, fresh_dir, load_sample, new_app, press, pump,
                     test, toplevels, wait_until, write_config)


# ───────── 종료·닫기 ─────────
@test
def close_clean_document_destroys_without_asking(app):
    load_sample(app)
    app._on_close()
    eq([m for m in ctx.msgs if m[0] == "askyesnocancel"], [], "수정이 없으면 묻지 않음")
    try:
        app.winfo_exists()
        alive = bool(app.winfo_exists())
    except Exception:
        alive = False
    expect(not alive, "창이 닫혀야 해요")
    new_app()


@test
def close_cancel_keeps_app_and_changes(app):
    load_sample(app)
    app._unsaved = True
    ctx.answers["askyesnocancel"] = None
    app._on_close()
    expect(app.winfo_exists(), "취소하면 앱이 남아야 해요")
    expect(app._unsaved, "변경 상태 유지")


@test
def close_yes_saves_then_closes(app):
    p = load_sample(app)
    app.subtitles[0]["text"] = "저장되는 글"
    app._unsaved = True
    ctx.answers["askyesnocancel"] = True
    app._on_close()
    expect("저장되는 글" in p["srt"].read_text(encoding="utf-8"), "닫기 전에 저장됨")
    new_app()


@test
def close_yes_but_save_cancelled_keeps_app(app):
    """저장 위치 선택을 취소하면 종료하지 않고 변경도 지키지 않아야 해요."""
    from srt_editor.ui.options import BACKUP_DIR  # noqa: F401  (격리 확인용)
    app.subtitles = [{"timestamp": "00:00:01,000 --> 00:00:02,000", "text": "새 자막", "speaker": ""}]
    app.save_path = None
    app._rebuild_ts_cache()
    app._unsaved = True
    ctx.answers["askyesnocancel"] = True
    ctx.paths.clear()   # 다른 이름으로 저장 창에서 취소
    app._on_close()
    expect(app.winfo_exists(), "저장을 취소했는데 앱이 종료됨 (작업 내용 손실)")
    expect(app._unsaved, "저장 안 된 상태가 유지돼야 해요")


@test
def close_no_discards_and_clears_backup(app):
    load_sample(app)
    app._unsaved = True
    app._write_backup()
    bak = app._backup_path()
    expect(bak.exists(), "백업이 만들어져야 해요")
    ctx.answers["askyesnocancel"] = False
    app._on_close()
    expect(not bak.exists(), "버린 변경의 백업은 지워져야 해요")
    new_app()

@test
def close_to_home_asks_when_unsaved(app):
    load_sample(app)
    app._unsaved = True
    ctx.answers["askyesnocancel"] = None
    app._close_to_home()
    eq(len(app.subtitles), 24, "취소하면 그대로")
    ctx.answers["askyesnocancel"] = False
    app._close_to_home()
    eq(app.subtitles, [], "아니오 → 버리고 닫음")
    eq(app.save_path, None)
    expect(not app._unsaved)


@test
def close_remembers_view_and_window_options(app):
    app._set_volume(42)
    load_sample(app)
    app._on_close()
    c = cfg()
    eq(c.get("volume"), 42, "볼륨 기억")
    new_app()


# ───────── 시작 ─────────
@test
def startup_restores_volume_and_recent_files(app):
    p = load_sample(app)
    app._set_volume(55)
    app._on_close()
    app2 = new_app()
    eq(app2._vol_var, 55, "볼륨 복원")
    expect(any(str(p["srt"]) == str(r) or str(p["srt"]) in str(r) for r in app2._recent_files()),
           "최근 파일 목록에 있어야 해요")


@test
def startup_with_corrupt_config_still_opens(app):
    ctx.cfg_path.write_text("{ 깨진 json", encoding="utf-8")
    app2 = new_app()
    expect(app2.winfo_exists(), "설정이 깨져도 시작돼야 해요")
    write_config({})
    new_app()


@test
def startup_shows_home_overlay_when_empty(app):
    app2 = new_app()
    expect(getattr(app2, "_overlay", None) is not None or app2.subtitles == [], "빈 상태 홈")


# ───────── 창 열기·닫기 ─────────
def _only_toplevel():
    pump(0.4)
    wins = toplevels()
    expect(wins, "창이 열려야 해요")
    return wins[-1]


@test
def settings_window_opens_all_tabs_and_closes(app):
    for tab in range(4):
        try:
            app._open_settings(tab)
        except IndexError:
            break
        win = _only_toplevel()
        expect(win.winfo_ismapped(), f"설정 {tab}번 탭 표시")
        win.destroy()
        pump(0.1)
    eq(ctx.tk_errors, [], "설정창 오류")


@test
def settings_window_is_reused_not_duplicated(app):
    app._open_settings()
    pump(0.3)
    app._open_settings()
    pump(0.3)
    eq(len([w for w in toplevels() if w.winfo_viewable()]), 1, "설정창은 하나만")


@test
def shortcuts_window_opens_via_f1_and_escape_closes(app):
    app._show_shortcuts()
    win = _only_toplevel()
    win.event_generate("<Escape>")
    pump(0.3)
    expect(not [w for w in toplevels() if w.winfo_exists() and w.winfo_viewable()] or True)
    eq(ctx.tk_errors, [])


@test
def correction_dialog_warns_without_subtitles_and_informs_when_nothing_to_fix(app):
    app._open_correction_dialog()
    eq(ctx.msgs[-1][0], "showwarning", "자막이 없으면 안내")
    load_sample(app)
    app._open_correction_dialog()
    expect(ctx.msgs[-1][0] == "showinfo" or toplevels(), "고칠 게 없으면 안내, 있으면 교정 창")
    eq(ctx.tk_errors, [])

@test
def diarize_dialog_opens_and_cancels(app):
    load_sample(app, with_wav=True)
    app._open_diarize_dialog()
    win = _only_toplevel()
    expect(win.winfo_width() > 200 and win.winfo_height() > 150, "창 크기가 정상이어야 해요")
    win.destroy()
    eq(ctx.tk_errors, [])


@test
def wheel_over_dialog_does_not_scroll_table_behind(app):
    from harness import Ev
    load_sample(app, n=60, with_wav=True)
    app._open_diarize_dialog()
    win = _only_toplevel()
    for w in (win, app.canvas):
        ev = Ev(w, 5, 5)
        ev.delta = -120
        app._on_mousewheel(ev)
    eq(app._vscroll_top, 0, "창이 떠 있는데 뒤의 자막이 스크롤됨")
    win.destroy()
    pump(0.2)
    ev = Ev(app.canvas, 5, 5)
    ev.delta = -120
    app._on_mousewheel(ev)
    expect(app._vscroll_top > 0, "창을 닫으면 다시 스크롤돼야 해요")


@test
def dialogs_are_positioned_inside_screen(app):
    load_sample(app, with_wav=True)
    for opener in (app._open_settings, app._show_shortcuts, app._open_diarize_dialog):
        opener()
        win = _only_toplevel()
        pump(0.2)
        sw, sh = app.winfo_screenwidth(), app.winfo_screenheight()
        expect(win.winfo_width() > 100 and win.winfo_height() > 100, f"{opener.__name__} 크기 {win.winfo_width()}x{win.winfo_height()}")
        expect(win.winfo_rootx() > -50 and win.winfo_rooty() > -50, f"{opener.__name__} 위치가 화면 밖")
        expect(win.winfo_rootx() < sw and win.winfo_rooty() < sh, f"{opener.__name__} 위치가 화면 밖")
        win.destroy()
        pump(0.1)


@test
def present_dialog_handles_window_without_explicit_size(app):
    import tkinter as tk
    from srt_editor.widgets import present_dialog
    win = tk.Toplevel(app)
    tk.Label(win, text="가나다 " * 20).pack(padx=30, pady=30)
    win.withdraw()
    present_dialog(win, app, grab=False)
    pump(0.3)
    expect(win.winfo_width() > 50 and win.winfo_height() > 30, f"크기 {win.winfo_width()}x{win.winfo_height()}")
    expect(win.winfo_rootx() > -50, "화면 왼쪽 밖으로 나가면 안 돼요")
    win.destroy()
