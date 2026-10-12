"""큰 영상 재생·정지·이동 스트레스 (SRT_STRESS_MEDIA=영상 경로일 때만 실행)."""
import os
import random
import time

from harness import Skip, ctx, expect, pump, test, wait_until

MEDIA = os.environ.get("SRT_STRESS_MEDIA", "")
SLOW = 0.5   # 한 번 조작에 이보다 오래 걸리면 화면이 멈춘 것


def _ops(app, rnd):
    dur = max(1.0, app.player.duration)
    return [
        ("재생/일시정지", app._media_play_pause),
        ("정지", app._media_stop),
        ("→", lambda: app._media_seek(app._opt("seek_step"))),
        ("←", lambda: app._media_seek(-app._opt("seek_step"))),
        ("Shift+→", lambda: app._media_seek(app._opt("seek_step_shift"))),
        ("임의 위치", lambda: app._do_seek(rnd.uniform(0, dur), update_selection=False)),
        ("끝 근처", lambda: app._do_seek(dur - rnd.uniform(0.2, 3), update_selection=False)),
    ]


def _hammer(app, n, seed, log):
    rnd = random.Random(seed)
    slow, bad = [], []
    for k in range(n):
        name, fn = rnd.choice(_ops(app, rnd))
        t = time.perf_counter()
        fn()
        dt = time.perf_counter() - t
        pump(rnd.choice((0.0, 0.02, 0.1, 0.3)))
        if dt > SLOW:
            slow.append(f"{name} {dt:.2f}초")
        p, d = app.player.position, app.player.duration
        icon_play = app.btn_play._kind == "pause"
        if not (0 <= p <= d + 0.01):
            bad.append(f"{k}:{name} 위치 {p:.2f}/{d:.2f}")
        if icon_play != app.player.is_playing:
            bad.append(f"{k}:{name} 버튼({app.btn_play._kind})≠재생({app.player.is_playing})")
    log.append(f"{n}회: 느림 {len(slow)}, 상태 어긋남 {len(bad)}")
    return slow, bad


@test
def stress_big_media_play_stop_seek(app):
    if not MEDIA or not os.path.exists(MEDIA):
        raise Skip("SRT_STRESS_MEDIA 없음")
    log = []
    t = time.perf_counter()
    app._open_paths([MEDIA])
    log.append(f"열기 {time.perf_counter() - t:.2f}초")
    wait_until(lambda: app.player.duration > 0, 30, "길이")
    s1, b1 = _hammer(app, 40, 1, log)   # 소리 추출 중
    t = time.perf_counter()
    wait_until(lambda: str(app.player._filepath).endswith(".wav"), 900, "소리 추출")
    log.append(f"소리 추출 {time.perf_counter() - t:.0f}초")
    s2, b2 = _hammer(app, 300, 2, log)
    app._media_stop()
    pump(0.1)
    app._media_play_pause()
    p0 = app.player.position
    pump(1.5)
    log.append(f"1.5초 재생 진행 {app.player.position - p0:.2f}초")
    app._media_stop()
    print("   " + " / ".join(log))
    for s in (s1 + s2)[:10]:
        print("   느림:", s)
    for b in (b1 + b2)[:15]:
        print("   어긋남:", b)
    expect(not ctx.tk_errors, f"Tk 오류 {len(ctx.tk_errors)}개: {ctx.tk_errors[:1]}")
    expect(not (s1 + s2), f"느린 조작 {len(s1 + s2)}개")
    expect(not (b1 + b2), f"상태 어긋남 {len(b1 + b2)}개")
