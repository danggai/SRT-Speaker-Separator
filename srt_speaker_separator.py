"""SRT Speaker Editor 실행 진입점.

필수 패키지를 확인(없으면 설치 안내)한 뒤 srt_editor 패키지의 앱을 실행한다.
실제 코드는 srt_editor/ 아래에 기능별로 나뉘어 있다. PyInstaller 빌드도 이 파일을
대상으로 하며, srt_editor 패키지는 import를 따라 자동으로 포함된다.
"""
import tkinter as tk
from tkinter import ttk, messagebox
import subprocess, sys
import os

# ── 필수 패키지 자동 설치 (앱 시작 시 1회) ─────────────────────────────
def _bootstrap_packages():
    """Pillow, tkinterdnd2, pygame, mutagen, librosa 미설치 시 자동 pip install."""
    _REQUIRED = [
        ("PIL",         "Pillow"),
        ("tkinterdnd2", "tkinterdnd2"),
        ("pygame",      "pygame"),
        ("mutagen",     "mutagen"),
        ("librosa",     "librosa"),
        ("soundfile",   "soundfile"),
        ("audioread",   "audioread"),
        ("numpy",       "numpy"),
    ]
    missing = []
    for import_name, pip_name in _REQUIRED:
        try:
            __import__(import_name)
        except ImportError:
            missing.append(pip_name)

    if not missing:
        return

    # 설치 전 사용자 안내 (tkinter 윈도우 띄우기)
    root = tk.Tk()
    root.withdraw()
    ok = messagebox.askyesno(
        "필수 패키지 설치",
        f"다음 패키지가 설치되어 있지 않습니다:\n\n"
        f"  {', '.join(missing)}\n\n"
        "지금 자동으로 설치할까요?\n"
        "(인터넷 연결 필요, 수 분 소요될 수 있습니다)",
        parent=root
    )
    root.destroy()
    if not ok:
        sys.exit(0)

    # 설치 진행 창
    prog_root = tk.Tk()
    prog_root.title("패키지 설치 중...")
    prog_root.geometry("380x110")
    prog_root.resizable(False, False)
    lbl = tk.Label(prog_root, text="설치 준비 중...", font=("", 10), pady=16)
    lbl.pack()
    bar = ttk.Progressbar(prog_root, mode="indeterminate", length=320)
    bar.pack()
    bar.start(10)
    prog_root.update()

    errors = []
    for i, pkg in enumerate(missing):
        lbl.configure(text=f"설치 중: {pkg}  ({i+1}/{len(missing)})")
        prog_root.update()
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", pkg, "-q"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except subprocess.CalledProcessError:
            # --user 재시도
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", pkg, "-q", "--user"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            except subprocess.CalledProcessError as e:
                errors.append(pkg)

    bar.stop()
    prog_root.destroy()

    if errors:
        root2 = tk.Tk()
        root2.withdraw()
        messagebox.showerror(
            "설치 실패",
            f"다음 패키지 설치에 실패했습니다:\n{', '.join(errors)}\n\n"
            "수동으로 설치 후 다시 실행해주세요:\n"
            f"pip install {' '.join(errors)}",
            parent=root2
        )
        root2.destroy()
        sys.exit(1)

    # 설치 완료 → 재시작
    root3 = tk.Tk()
    root3.withdraw()
    messagebox.showinfo("설치 완료",
        "패키지 설치가 완료됐습니다.\n앱을 재시작합니다.",
        parent=root3)
    root3.destroy()
    _frozen = getattr(sys, "frozen", False)
    if _frozen:
        subprocess.Popen([sys.executable])
    else:
        subprocess.Popen([sys.executable] + sys.argv)
    sys.exit(0)

# ─────────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    # 파형 추출 등 하위 프로세스로 실행된 경우 여기서 처리하고 끝남
    import multiprocessing
    multiprocessing.freeze_support()
    _bootstrap_packages()

    import traceback as _tb
    try:
        from srt_editor.app import main
        main()
    except Exception:
        err = _tb.format_exc()
        print(err)
        # 같은 폴더에 에러 로그 저장
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "srt_error.log")
        try:
            with open(log_path, "w", encoding="utf-8") as _f:
                _f.write(err)
        except Exception:
            pass
        try:
            import tkinter as _tk, tkinter.messagebox as _mb
            _r = _tk.Tk(); _r.withdraw()
            _mb.showerror("치명적 오류", f"앱이 시작되지 않았습니다.\n\n{err[:600]}\n\n로그: {log_path}")
            _r.destroy()
        except Exception:
            pass
