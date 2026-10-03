"""영상 재생 부품(PyAV)을 처음 쓸 때 PyPI에서 받아 사용자 폴더에 푼다. GUI 없음."""
import json
import os
import pathlib
import platform
import sys
import tempfile
import urllib.request
import zipfile

LIB_DIR = (pathlib.Path.home() / ".srt_speaker_editor_libs"
           / f"py{sys.version_info.major}{sys.version_info.minor}")
_PYPI = "https://pypi.org/pypi/av/json"


def _add_path():
    p = str(LIB_DIR)
    if LIB_DIR.exists() and p not in sys.path:
        sys.path.insert(0, p)


def load_av():
    """av 모듈을 반환 (없으면 None)."""
    _add_path()
    try:
        import av
        return av
    except Exception:
        return None


def _wheel_ok(filename):
    """이 파이썬·OS에서 쓸 수 있는 wheel인지."""
    parts = filename[:-4].split("-")
    if len(parts) < 5:
        return False
    py, abi, plat = parts[-3], parts[-2], parts[-1]
    cur = sys.version_info.major * 100 + sys.version_info.minor
    try:
        ver = int(py[2]) * 100 + int(py[3:])
    except (ValueError, IndexError):
        return False
    if not py.startswith("cp"):
        return False
    if abi == "abi3":
        if ver > cur:
            return False
    elif abi != py or ver != cur:
        return False
    machine = platform.machine().lower()
    if sys.platform == "win32":
        return plat == ("win_arm64" if machine == "arm64" else "win_amd64")
    if sys.platform == "darwin":
        return plat.startswith("macosx") and ("arm64" if machine == "arm64" else "x86_64") in plat
    return "manylinux" in plat and machine in plat


def _find_wheel():
    with urllib.request.urlopen(_PYPI, timeout=20) as r:
        data = json.loads(r.read().decode())
    files = list(data.get("urls", []))
    releases = data.get("releases", {})

    def _ver_key(v):
        return [int(x) if x.isdigit() else 0 for x in v.split(".")]
    for v in sorted(releases, key=_ver_key, reverse=True)[:15]:
        files += releases[v]
    for f in files:
        if f.get("packagetype") == "bdist_wheel" and _wheel_ok(f["filename"]):
            return f["url"], f.get("size", 0)
    return None, 0


def install_av(on_progress=None):
    """PyAV를 받아 LIB_DIR에 푼다. on_progress(받은 바이트, 전체 바이트)."""
    url, size = _find_wheel()
    if not url:
        raise RuntimeError("이 PC에 맞는 영상 부품을 찾지 못했어요.")
    tmp = pathlib.Path(tempfile.gettempdir()) / "srt_editor_av.whl"
    with urllib.request.urlopen(url, timeout=30) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or size or 0)
        done = 0
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if on_progress:
                on_progress(done, total)
    LIB_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(tmp) as z:
        z.extractall(LIB_DIR)
    try:
        os.remove(tmp)
    except OSError:
        pass
    av = load_av()
    if av is None:
        raise RuntimeError("영상 부품을 불러오지 못했어요.")
    return av
