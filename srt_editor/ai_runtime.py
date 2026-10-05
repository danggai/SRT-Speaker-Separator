"""AI 부품(whisperx·torch)을 앱과 분리된 파이썬에 설치하고, 그 파이썬으로 AI 작업을 실행한다. GUI 의존성 없음.

설치: uv(단일 실행 파일)를 받아 → uv가 파이썬 3.12를 받아 가상 환경을 만들고 → whisperx·torch를 설치.
실행: ai_worker.py를 그 파이썬으로 띄워 진행 상황('@@{json}' 줄)을 읽고 결과 JSON을 받는다.
개발 환경(빌드 전)에서 whisperx가 이미 설치돼 있으면 설치 없이 지금 파이썬을 쓴다.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile

ROOT = pathlib.Path(os.environ.get("SRT_EDITOR_AI_DIR") or pathlib.Path.home() / ".srt_speaker_editor_ai")
UV_URL = "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip"
PYTHON_VERSION = "3.12"
TORCH_INDEX = {"cuda": "https://download.pytorch.org/whl/cu126", "cpu": "https://download.pytorch.org/whl/cpu"}
PACKAGES = ["whisperx==3.8.6", "torch==2.8.0", "torchaudio==2.8.0", "torchvision==0.23.0", "scikit-learn"]
EST_MB = {"cuda": 7000, "cpu": 3700}   # 설치 중 쌓이는 양 (실측, 진행률·용량 안내용)
WORKER_FILES = ["ai_worker.py", "speech.py", "line_speakers.py", "model_download.py", "correction_audio.py"]
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class AIError(Exception):
    """AI 작업 실패 (사용자에게 보여 줄 메시지)."""


class AIMissing(AIError):
    """AI 부품이 설치돼 있지 않음."""


# ── 상태 ─────────────────────────────────────────
def _venv_python():
    return ROOT / "venv" / "Scripts" / "python.exe"


def installed_info():
    """설치 정보 dict (없으면 None): device, cuda, gpu, torch."""
    try:
        info = json.loads((ROOT / "ready.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return info if _venv_python().exists() else None


def _dev_python_ok():
    if getattr(sys, "frozen", False):
        return False
    import importlib.util
    return importlib.util.find_spec("whisperx") is not None


def ai_python():
    """AI 작업에 쓸 파이썬 경로 (없으면 None). 설치한 AI 부품이 우선."""
    if installed_info():
        return str(_venv_python())
    if _dev_python_ok():
        return sys.executable
    return None


def has_nvidia_gpu():
    """NVIDIA GPU와 CUDA 12 이상을 지원하는 드라이버가 있는가."""
    try:
        out = subprocess.check_output(["nvidia-smi"], stderr=subprocess.DEVNULL, text=True,
                                      timeout=10, creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return False
    import re
    m = re.search(r"CUDA (?:UMD )?Version:\s*(\d+)\.(\d+)", out)   # 최신 드라이버는 "CUDA UMD Version"
    return bool(m) and int(m.group(1)) >= 12


def dir_size(path):
    total = 0
    for dirpath, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total


def uninstall():
    shutil.rmtree(ROOT, ignore_errors=True)


# ── 설치 ─────────────────────────────────────────
def _env():
    env = dict(os.environ)
    env.update({"UV_PYTHON_INSTALL_DIR": str(ROOT / "python"), "UV_CACHE_DIR": str(ROOT / "cache"),
                "UV_NO_PROGRESS": "1", "PYTHONIOENCODING": "utf-8"})
    env.pop("VIRTUAL_ENV", None)
    return env


def _download(url, dest, progress, cancelled):
    with urllib.request.urlopen(url, timeout=30) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            if cancelled():
                raise AIError("설치를 취소했어요.")
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            progress(done, total)


def _run_logged(cmd, log, cancelled, on_tick=None):
    """명령을 창 없이 실행하고 출력은 로그 파일에. 취소되면 프로세스를 끝낸다."""
    with open(log, "a", encoding="utf-8", errors="replace") as lf:
        lf.write("\n$ " + " ".join(map(str, cmd)) + "\n")
        lf.flush()
        p = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT, env=_env(), creationflags=_NO_WINDOW)
        while p.poll() is None:
            if cancelled():
                p.kill()
                raise AIError("설치를 취소했어요.")
            if on_tick:
                on_tick()
            time.sleep(0.5)
    if p.returncode:
        tail = pathlib.Path(log).read_text(encoding="utf-8", errors="replace")[-600:]
        raise AIError(f"설치 중 오류가 났어요.\n\n{tail}")


def install(device="cuda", progress=None, cancelled=None):
    """AI 부품 설치. progress(메시지, 0~100). device: 'cuda'(NVIDIA GPU) 또는 'cpu'."""
    progress = progress or (lambda msg, pct: None)
    cancelled = cancelled or (lambda: False)
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "ready.json").unlink(missing_ok=True)
    log = ROOT / "install.log"
    log.write_text("", encoding="utf-8")

    uv = ROOT / "bin" / "uv.exe"
    if not uv.exists():
        tmp = ROOT / "uv.zip"
        _download(UV_URL, tmp, lambda d, t: progress(
            f"설치 도구 내려받는 중  {d / 1048576:,.0f} / {t / 1048576:,.0f} MB" if t else "설치 도구 내려받는 중",
            3 * d / t if t else 0), cancelled)
        with zipfile.ZipFile(tmp) as z:
            name = next(n for n in z.namelist() if n.endswith("uv.exe"))
            (ROOT / "bin").mkdir(exist_ok=True)
            with z.open(name) as src, open(uv, "wb") as dst:
                shutil.copyfileobj(src, dst)
        tmp.unlink(missing_ok=True)

    progress("파이썬 준비 중...", 4)
    shutil.rmtree(ROOT / "venv", ignore_errors=True)
    _run_logged([uv, "venv", ROOT / "venv", "--python", PYTHON_VERSION, "--python-preference", "only-managed"],
                log, cancelled)

    est = EST_MB.get(device, EST_MB["cpu"]) * 1048576
    base = dir_size(ROOT / "cache")

    def tick():
        got = max(0, dir_size(ROOT / "cache") - base)
        progress(f"AI 부품 내려받는 중  {got / 1048576:,.0f} MB / 약 {est / 1048576:,.0f} MB",
                 6 + 84 * min(0.99, got / est))
    _run_logged([uv, "pip", "install", "--python", _venv_python(), "--link-mode", "copy",
                 "--index-strategy", "unsafe-best-match", "--extra-index-url", TORCH_INDEX[device], *PACKAGES],
                log, cancelled, on_tick=tick)

    progress("설치 확인 중...", 92)
    info = run_job({"type": "probe"}, python=str(_venv_python()))
    info["device"] = device
    (ROOT / "ready.json").write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    progress("내려받은 임시 파일 정리 중...", 97)
    shutil.rmtree(ROOT / "cache", ignore_errors=True)   # --link-mode copy라 지워도 설치본은 그대로
    progress("설치 완료", 100)
    return info


# ── 작업 실행 ─────────────────────────────────────
def _worker_src():
    if getattr(sys, "frozen", False):
        return pathlib.Path(getattr(sys, "_MEIPASS", "")) / "aiworker"
    return pathlib.Path(__file__).resolve().parent


def _worker_dir():
    """작업 실행기 파일을 앱 모듈과 섞이지 않는 폴더에 복사해 둔다."""
    dst = ROOT / "worker"
    dst.mkdir(parents=True, exist_ok=True)
    src = _worker_src()
    for name in WORKER_FILES:
        shutil.copy2(src / name, dst / name)
    return dst


def run_job(job, on_event=None, cancelled=None, python=None):
    """AI 작업 실행 → 결과 dict. on_event(dict): 진행 상황. 실패하면 AIError, 부품이 없으면 AIMissing."""
    python = python or ai_python()
    if not python:
        raise AIMissing("AI 부품이 설치돼 있지 않아요.")
    cancelled = cancelled or (lambda: False)
    work = pathlib.Path(tempfile.mkdtemp(prefix="srt_ai_job_"))
    job = dict(job, result=str(work / "result.json"))
    (work / "job.json").write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    env.pop("PYTHONPATH", None)
    err_log = work / "stderr.txt"
    last_err = None
    try:
        with open(err_log, "w", encoding="utf-8", errors="replace") as ef:
            p = subprocess.Popen([python, "-X", "utf8", str(_worker_dir() / "ai_worker.py"), str(work / "job.json")],
                                 stdout=subprocess.PIPE, stderr=ef, env=env, creationflags=_NO_WINDOW)
            stop = threading.Event()

            def _watch_cancel():
                while not stop.wait(0.3):
                    if cancelled() and p.poll() is None:
                        p.kill()
                        return
            threading.Thread(target=_watch_cancel, daemon=True).start()
            for raw in p.stdout:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("@@"):
                    continue
                try:
                    ev = json.loads(line[2:])
                except ValueError:
                    continue
                if ev.get("type") == "error":
                    last_err = ev.get("msg")
                elif on_event:
                    on_event(ev)
            p.wait()
            stop.set()
        if cancelled():
            raise AIError("취소했어요.")
        res = work / "result.json"
        if p.returncode == 0 and res.exists():
            return json.loads(res.read_text(encoding="utf-8"))
        tail = err_log.read_text(encoding="utf-8", errors="replace")[-800:]
        raise AIError(last_err or f"AI 작업이 비정상 종료됐어요 (코드 {p.returncode}).\n\n{tail}")
    finally:
        shutil.rmtree(work, ignore_errors=True)
