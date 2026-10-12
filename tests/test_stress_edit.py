"""긴 자막(수천 줄)+긴 음성 작업 중 렉 측정 (SRT_STRESS_SRT·SRT_STRESS_AUDIO 경로가 있을 때만 실행).

SRT_STRESS_PROFILE_OPS=1 이면 조작별 CPU 사용 분석도 출력한다.
"""
import cProfile
import io
import os
import pstats
import time

from harness import Skip, app_key, pump, test, wait_until

SRT = os.environ.get("SRT_STRESS_SRT", "")
AUDIO = os.environ.get("SRT_STRESS_AUDIO", "")


def _time(fn, n=1):
    ts = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        ts.append(time.perf_counter() - t)
    return sum(ts) / len(ts) * 1000, max(ts) * 1000


def _latency(app, sec):
    """sec 동안 이벤트 처리 지연 (after(0)이 실제로 몇 ms 늦게 도는지): 평균·최대."""
    out, end = [], time.perf_counter() + sec

    def probe():
        t = time.perf_counter()
        app.after(0, lambda: out.append(time.perf_counter() - t))
    while time.perf_counter() < end:
        probe()
        pump(0.05)
    return sum(out) / max(1, len(out)) * 1000, max(out or [0]) * 1000


@test
def stress_long_srt_editing_lag(app):
    if not (os.path.exists(SRT) and os.path.exists(AUDIO)):
        raise Skip("SRT_STRESS_SRT / SRT_STRESS_AUDIO 없음")
    rep, profs = [], {}
    t = time.perf_counter()
    app._open_paths([SRT, AUDIO])
    wait_until(lambda: len(app.subtitles) > 100, 30, "자막 열기")
    rep.append(f"열기 {time.perf_counter() - t:.2f}초 ({len(app.subtitles)}줄, 화자 {len(app.speakers)}명)")
    wait_until(lambda: app.player.duration > 0, 30, "길이")
    wait_until(lambda: app._waveform_pts, 300, "파형")
    wait_until(lambda: str(app.player._filepath).endswith(".wav"), 120, "재생용 소리")
    pump(0.5)

    def r(name, fn, n=1):
        if os.environ.get("SRT_STRESS_PROFILE_OPS"):
            p = cProfile.Profile()
            p.enable()
        a, m = _time(fn, n)
        rep.append(f"{name}: 평균 {a:.1f} / 최대 {m:.1f}ms")
        if os.environ.get("SRT_STRESS_PROFILE_OPS"):
            p.disable()
            s = io.StringIO()
            pstats.Stats(p, stream=s).sort_stats("tottime").print_stats(12)
            profs[name] = s.getvalue()

    def k(seq):   # 키 하나 처리와 화면 그리기까지
        def go():
            app.event_generate(seq)
            app.update()
        return go

    def redraw(full):
        def go():
            app._wf_img_cache = None
            if full:
                app._wf_base_cache = None
            app._pb_redraw()
        return go
    r("타임라인 다시 그리기(전체)", redraw(True), 5)
    r("타임라인 다시 그리기(자막만)", redraw(False), 5)
    r("타임라인 재생헤드만", app._pb_redraw, 20)

    app._select_row(500, seek=False)
    app_key("<Up>", 0.1)   # 포커스를 앱에 둠
    r("↓ 이동", k("<Down>"), 30)
    r("화자 키 1", k("1"), 20)
    r("실행 취소", app._undo, 10)
    r("Page Down", k("<Next>"), 20)
    r("Page Up", k("<Prior>"), 20)
    rep.append("정지 상태 지연: 평균 %.1f / 최대 %.1fms" % _latency(app, 2))

    def hold(seq, n=30, gap_ms=33):
        """키를 누르고 있을 때(초당 30번 반복): 손을 뗀 뒤 화면이 따라잡기까지 걸린 시간."""
        app.update()
        t0 = time.perf_counter()
        for i in range(n):
            app.after(i * gap_ms, lambda: app.event_generate(seq))
        last = t0 + (n - 1) * gap_ms / 1000
        while time.perf_counter() < last + 0.005:
            app.update()
        app.update()
        return (time.perf_counter() - last) * 1000
    app._select_row(100, seek=False)
    app._scroll_to_row(100)
    app.update()
    rep.append("Page Down 누르고 있기: 뗀 뒤 %.0fms 늦게 멈춤" % hold("<Next>"))
    rep.append("↓ 누르고 있기: 뗀 뒤 %.0fms 늦게 멈춤" % hold("<Down>"))

    app._select_row(900, seek=True)
    app._media_play_pause()
    pump(0.3)
    app_key("<Up>", 0.1)
    r("재생 중 ↓ 이동", k("<Down>"), 20)
    r("재생 중 Page Down", k("<Next>"), 10)
    dur = app.player.duration
    r("재생 중 위치 이동", lambda: app._do_seek(dur * (0.2 + 0.7 * (time.time() % 1))), 10)
    di = app._selected_row_idx
    s = next(i for i, d in enumerate(app._slot_data) if d == di)
    app._txt_edit_start(s)
    ent = app._slot_widgets[s]["content"]
    pump(0.1)

    def typ():
        ent.insert("insert", "가")
        app.update()
    r("재생 중 글자 입력", typ, 30)
    app.focus_set()
    pump(0.1)
    for zoom in (1.0, 8.0, 40.0):
        app._wf_zoom = zoom
        rep.append(f"재생 중 지연(배율 {zoom:g}): 평균 %.1f / 최대 %.1fms" % _latency(app, 3))
    app._media_play_pause()
    app._wf_zoom = 1.0
    print("\n   " + "\n   ".join(rep))
    for name, v in profs.items():
        print(f"\n==== {name}\n" + v[v.find("ncalls"):][:2500])
    app._unsaved = False
