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
    eq(shown(app), ["Tab", "Ctrl+Space", "Enter", "Esc"], "편집 중")
    app.focus_set()
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
