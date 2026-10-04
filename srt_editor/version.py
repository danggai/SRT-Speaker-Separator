"""앱 버전, 업데이트 확인용 GitHub 주소와 최신 버전 조회."""
import json
import pathlib
import urllib.request

# ─────────────────────────────────────────────
#  버전 정보
# ─────────────────────────────────────────────
APP_VERSION      = "1.1.4"   # 현재 버전 (릴리즈 태그와 맞춰 관리)
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


def fetch_latest_version(timeout=6):
    """GitHub에서 가장 높은 버전을 가져온다 (공개된 릴리즈 → 태그 목록 순). 실패하면 None."""
    headers = {"User-Agent": "Mozilla/5.0 SRT-Speaker-Separator", "Accept": "application/vnd.github+json"}
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
