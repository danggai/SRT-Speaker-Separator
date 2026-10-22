"""단축키 익히기: 상황별 단축키 한 줄, 마우스 동작 알림."""
from harness import app_key, cfg, eq, expect, load_sample, pump, slot_of, test, write_config


def shown(app):
    app._update_ctx_keys()
    return [k for k, _ in (app._ctx_keys_shown or [])]


@test
def context_keys_follow_what_you_are_doing(app):
    load_sample(app, with_wav=True)
    app._select_row(3, seek=False)
    expect("Q·W" in shown(app), f"줄 선택: 시간 찍기 키 ({shown(app)})")
    app._media_play_pause()
    pump(0.1)
    expect(shown(app)[:2] == ["Q", "W"], f"재생 중: Q·W 따로 ({shown(app)})")
    app._media_play_pause()
    app._toggle_select(4)
    expect("M" in shown(app), f"여러 줄: 합치기 ({shown(app)})")
    app._select_row(5, seek=False)
    app_key("<Return>")
    expect(app.focus_get() is app._slot_widgets[slot_of(app, 5)]["content"], "편집 시작")
    eq(shown(app), ["↑↓", "Ctrl+Space", "Enter", "Esc"], "편집 중")
    ent = app._slot_widgets[slot_of(app, 5)]["content"]
    ent.event_generate("<KeyPress-Shift_L>")
    eq(shown(app), ["Shift+Enter", "Shift+Tab"], "편집 중 Shift 누름")
    ent.event_generate("<KeyRelease-Shift_L>")
    app.focus_set()
    pump(0.1)
    app_key("<KeyPress-Control_L>")
    expect("Ctrl+클릭" in shown(app) and "Ctrl+경계 드래그" not in shown(app), f"자막 줄 Ctrl ({shown(app)})")
    app_key("<KeyRelease-Control_L>")
    app_key("<KeyPress-Shift_L>")
    expect("Shift+↑↓" in shown(app), f"Shift 누름 ({shown(app)})")
    app_key("<KeyRelease-Shift_L>")
    expect("Shift+↑↓" not in shown(app), "떼면 원래대로")
    app_key("<KeyPress-Alt_L>")
    expect("Alt+←→" in shown(app) and "Alt+↑↓" in shown(app), f"Alt 누름 ({shown(app)})")
    app_key("<KeyRelease-Alt_L>")
    expect("Alt+←→" not in shown(app), "Alt 떼면 원래대로")
    pb = app._pb_canvas
    pb.focus_force()
    pump(0.05)
    pb.event_generate("<KeyPress-Shift_L>")
    expect(("Shift+드래그", "레이어만 옮기기") in app._ctx_keys_shown and
           ("Shift+↑↓", "이전·다음 경계로") in app._ctx_keys_shown, f"타임라인 Shift ({app._ctx_keys_shown})")
    pb.event_generate("<KeyRelease-Shift_L>")
    pb.event_generate("<KeyPress-Control_L>")
    expect(shown(app)[0] == "Ctrl+경계 드래그", f"타임라인 Ctrl ({shown(app)})")
    pb.event_generate("<KeyRelease-Control_L>")
    pump(0.1)
    app._set_opt("context_keys", False)
    eq(shown(app), [], "설정으로 끄기")
    app._set_opt("context_keys", True)
    expect(shown(app), "다시 켜기")
    widgets = app._ctx_keys_box.winfo_children()
    expect(widgets and widgets[0].winfo_manager() == "pack", "화면에 표시")


@test
def mouse_action_tip_shows_twice_then_stops(app):
    write_config({"key_tips": True})
    app.__dict__["_opt_cache"] = {}
    load_sample(app)
    for n in (1, 2, 3):
        app._last_tip_at = 0   # 1분 간격 규칙은 건너뜀
        app._toast_win = None
        app._tip("split")
        pump(0.05)
        expect((app._toast_win is not None) == (n <= 2), f"{n}번째 알림")
    eq(cfg()["tip_counts"]["split"], 2)
    app._last_tip_at = 0
    app._toast_win = None
    app._tip("merge")
    expect(app._toast_win is not None, "다른 알림은 따로 셈")
    app._last_tip_at = 0
    app._toast_win = None
    app._tip_learned("add")
    app._tip("add")
    expect(app._toast_win is None, "단축키를 써 봤으면 알림 안 띄움")
    app._last_tip_at = __import__("time").time()
    app._tip("delete")
    expect(app._toast_win is None, "1분 안에 또 띄우지 않음")
