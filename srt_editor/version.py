"""앱 버전, 업데이트 확인용 GitHub 주소와 최신 버전 조회."""
import json
import pathlib
import urllib.request

# ─────────────────────────────────────────────
#  버전 정보
# ─────────────────────────────────────────────
APP_VERSION      = "1.2.5"   # 현재 버전 (릴리즈 태그와 맞춰 관리)
GITHUB_TAGS_URL  = "https://github.com/danggai/SRT-Speaker-Separator/releases"
GITHUB_LATEST_API = "https://api.github.com/repos/danggai/SRT-Speaker-Separator/tags"
_API = "https://api.github.com/repos/danggai/SRT-Speaker-Separator"
UPDATE_LOG = pathlib.Path.home() / ".srt_speaker_update.log"
_LOG_MAX = 50_000   # 이 크기를 넘으면 로그를 새로 시작


def parse_version(v):
    """'v1.10.2' → (1, 10, 2). 숫자가 아닌 부분이 있으면 ()."""
    try:
        return tuple(int(x) for x in str(v).strip().lstrip("vV").split("."))
    except ValueError:
        return ()


def pick_latest(names):
    """이름 목록에서 가장 높은 버전 (v 접두사 제거). 버전 형식이 아닌 이름은 무시하고, 없으면 None."""
    best = None
    for n in names:
        key = parse_version(n)
        if key and (best is None or key > best[0]):
            best = (key, str(n).strip().lstrip("vV"))
    return best[1] if best else None


def is_newer(latest, current):
    return parse_version(latest) > parse_version(current)


def _log(msg):
    import datetime
    try:
        if UPDATE_LOG.exists() and UPDATE_LOG.stat().st_size > _LOG_MAX:
            UPDATE_LOG.unlink()
        with open(UPDATE_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now():%H:%M:%S}] {msg}\n")
    except OSError:
        pass


_HEADERS = {"User-Agent": "Mozilla/5.0 SRT-Speaker-Separator", "Accept": "application/vnd.github+json"}


def release_exe(tag, timeout=10):
    """릴리즈 tag의 EXE (이름, 내려받기 주소, 크기). 없으면 None."""
    for t in (tag, f"v{tag}"):
        try:
            req = urllib.request.Request(f"{_API}/releases/tags/{t}", headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                assets = json.loads(resp.read().decode()).get("assets", [])
        except Exception as e:   # noqa: BLE001
            _log(f"릴리즈 {t} 조회 실패: {e}")
            continue
        for a in assets:
            if a.get("name", "").lower().endswith(".exe"):
                return a["name"], a["browser_download_url"], int(a.get("size") or 0)
    return None


def download(url, dest, progress=None, cancelled=None):
    """url을 dest로 내려받는다 (.part에 받은 뒤 이름 변경). 취소되면 False."""
    dest = pathlib.Path(dest)
    part = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": _HEADERS["User-Agent"]})
    with urllib.request.urlopen(req, timeout=30) as r, open(part, "wb") as f:
        total, done = int(r.headers.get("Content-Length") or 0), 0
        while True:
            if cancelled and cancelled():
                break
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    if cancelled and cancelled():
        part.unlink(missing_ok=True)
        return False
    part.replace(dest)
    return True


def launch_after_exit(new_exe, old_exe, pid):
    """이 프로세스(pid)가 끝나면 새 EXE를 실행하고 이전 EXE를 지우는 스크립트를 띄운다."""
    import base64
    import os
    import subprocess
    new_exe, old_exe = os.path.abspath(new_exe), os.path.abspath(old_exe)

    def q(p):
        return "'" + p.replace("'", "''") + "'"
    # 새 버전부터 띄우고, 이전 EXE는 잠금이 풀릴 때까지 기다렸다가 지운다 (한글 경로도 안전하게 UTF-16 인코딩 명령)
    script = (f"Wait-Process -Id {int(pid)} -ErrorAction SilentlyContinue; "
              f"Start-Process -FilePath {q(new_exe)}")
    if os.path.normcase(new_exe) != os.path.normcase(old_exe):
        script += (f"; for ($i = 0; $i -lt 30 -and (Test-Path -LiteralPath {q(old_exe)}); $i++) "
                   f"{{ Start-Sleep 1; Remove-Item -LiteralPath {q(old_exe)} -Force -ErrorAction SilentlyContinue }}")
    enc = base64.b64encode(script.encode("utf-16-le")).decode()
    cmd = ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-EncodedCommand", enc]
    subprocess.Popen(cmd, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), close_fds=True)
    return script


def fetch_latest_version(timeout=6):
    """GitHub에서 가장 높은 버전을 가져온다 (공개된 릴리즈 → 태그 목록 순). 실패하면 None."""
    headers = _HEADERS
    endpoints = [
        (f"{_API}/releases/latest", lambda d: [d.get("tag_name", "")]),
        (f"{_API}/git/refs/tags", lambda d: [r["ref"].split("/")[-1] for r in d]),
        (GITHUB_LATEST_API, lambda d: [t["name"] for t in d]),
    ]
    for url, names in endpoints:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                tag = pick_latest(names(json.loads(resp.read().decode())))
            if tag:
                _log(f"{url.rsplit('/', 2)[-2]} → {tag}")
                return tag
        except Exception as e:   # noqa: BLE001 (네트워크·형식 오류는 다음 주소로)
            _log(f"{url} 실패: {e}")
    _log("모든 주소 실패")
    return None
