"""앱 안 업데이트: 릴리즈 EXE 찾기, 내려받기, 종료 후 새 버전 실행."""
import io
import json
import sys

from harness import ctx, eq, expect, fresh_dir, test, wait_until


@test
def release_exe_picks_exe_asset_and_falls_back_to_v_tag():
    from srt_editor import version as V
    seen = []

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_open(req, timeout=0):
        seen.append(req.full_url)
        if req.full_url.endswith("/tags/1.2.0"):
            raise OSError("404")
        return Resp(json.dumps({"assets": [{"name": "notes.txt", "browser_download_url": "x"},
                                           {"name": "SRTSpeakerEditor_1.2.0.exe", "browser_download_url": "u",
                                            "size": 5}]}).encode())
    orig = V.urllib.request.urlopen
    V.urllib.request.urlopen = fake_open
    try:
        eq(V.release_exe("1.2.0"), ("SRTSpeakerEditor_1.2.0.exe", "u", 5))
        expect(seen[-1].endswith("/tags/v1.2.0"), "태그에 v가 붙은 경우도 찾음")
    finally:
        V.urllib.request.urlopen = orig


@test
def download_writes_file_reports_progress_and_cancel_leaves_nothing():
    from srt_editor import version as V
    d = fresh_dir()
    src = d / "src.bin"
    src.write_bytes(b"a" * 700_000)
    url = src.as_uri()
    prog = []
    ok = V.download(url, d / "out.exe", lambda a, b: prog.append((a, b)))
    expect(ok and (d / "out.exe").read_bytes() == src.read_bytes(), "내려받은 내용이 같아야 해요")
    eq(prog[-1], (700_000, 700_000), "진행률")
    ok = V.download(url, d / "cancel.exe", cancelled=lambda: True)
    expect(not ok and not (d / "cancel.exe").exists() and not (d / "cancel.exe.part").exists(),
           "취소하면 파일을 남기지 않음")


@test
def launch_after_exit_waits_removes_old_and_starts_new():
    import base64
    from srt_editor import version as V
    calls = []
    import subprocess
    real = subprocess.Popen
    subprocess.Popen = lambda cmd, **kw: calls.append(cmd)
    try:
        V.launch_after_exit(r"C:\앱\SRT_1.2.0.exe", r"C:\앱\SRT_1.1.6.exe", 4321)
        V.launch_after_exit(r"C:\앱\SRT.exe", r"C:\앱\SRT.exe", 4321)
    finally:
        subprocess.Popen = real
    s1 = base64.b64decode(calls[0][-1]).decode("utf-16-le")
    expect("Wait-Process -Id 4321" in s1 and "Remove-Item -LiteralPath 'C:\\앱\\SRT_1.1.6.exe'" in s1
           and s1.endswith("Start-Process -FilePath 'C:\\앱\\SRT_1.2.0.exe'"), s1)
    s2 = base64.b64decode(calls[1][-1]).decode("utf-16-le")
    expect("Remove-Item" not in s2, "같은 파일이면 지우지 않음")


@test
def update_click_in_dev_opens_page_and_in_exe_downloads_then_closes(app):
    import webbrowser
    from srt_editor import version as V
    opened, closed, launched = [], [], []
    orig_open = webbrowser.open
    webbrowser.open = opened.append
    try:
        app._on_update_click("9.9.9")
        eq(opened, [V.GITHUB_TAGS_URL], "개발 환경은 페이지만 엶")
    finally:
        webbrowser.open = orig_open

    d = fresh_dir()
    saved = (V.release_exe, V.download, V.launch_after_exit, sys.executable)
    V.release_exe = lambda v: (f"SRTSpeakerEditor_{v}.exe", "u", 3)
    V.download = lambda url, dest, prog=None, cancelled=None: (prog and prog(3, 3), open(dest, "wb").close(), True)[-1]
    V.launch_after_exit = lambda new, old, pid: launched.append((new, old))
    sys.frozen = True
    sys.executable = str(d / "SRTSpeakerEditor_1.0.0.exe")
    app._on_close = lambda before_exit=None: (closed.append(1), before_exit())
    try:
        app._on_update_click("9.9.9")
        wait_until(lambda: closed, 5)
    finally:
        V.release_exe, V.download, V.launch_after_exit, sys.executable = saved
        del sys.frozen
    eq(launched, [(str(d / "SRTSpeakerEditor_9.9.9.exe"), str(d / "SRTSpeakerEditor_1.0.0.exe"))],
       "새 EXE는 지금 EXE 옆에 받고, 닫힌 뒤 실행")
    eq([m[1] for m in ctx.msgs], ["업데이트", "업데이트"], "두 번 모두 확인만 묻고 오류 없음")
