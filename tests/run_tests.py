"""회귀 테스트 실행기: 앱 기능 전반을 자동으로 점검한다 (버전 올리기·리팩터링 전후 확인용).

    python tests/run_tests.py                 보이지 않는 별도 데스크톱에서 실행 (화면·포커스를 건드리지 않음)
    python tests/run_tests.py --visible       일반 화면에서 실행 (실패 원인을 눈으로 볼 때)
    python tests/run_tests.py --only table    이름에 'table'이 들어간 테스트만 (여러 개 가능)
    python tests/run_tests.py --list          테스트 목록
    python tests/run_tests.py -v              통과한 테스트도 모두 표시

설정·백업·모델·파형 캐시는 모두 임시 폴더로 돌려서 실제 사용자 데이터는 읽거나 쓰지 않는다.
모두 통과하면 종료 코드 0, 하나라도 실패하면 1이다.
"""
import argparse
import codecs
import importlib
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import time

HERE = pathlib.Path(__file__).resolve().parent


def _parse():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--visible", action="store_true", help="보이는 데스크톱에서 실행")
    p.add_argument("--only", nargs="+", metavar="이름", help="이름에 이 글자가 들어간 테스트만 실행")
    p.add_argument("--list", action="store_true", help="테스트 목록만 출력")
    p.add_argument("-v", "--verbose", action="store_true", help="통과한 테스트도 표시")
    p.add_argument("--timeout", type=int, default=900, help="전체 제한 시간(초), 기본 900")
    p.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    return p.parse_args()


def _child_args(a):
    out = ["--child"]
    if a.only:
        out += ["--only", *a.only]
    if a.verbose:
        out.append("-v")
    return out


# ───────── 보이지 않는 데스크톱에서 실행 (Windows) ─────────
def _run_hidden(a):
    import ctypes
    import ctypes.wintypes as wt

    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.CreateDesktopW.restype = wt.HANDLE
    user32.CreateDesktopW.argtypes = [wt.LPCWSTR, wt.LPCWSTR, ctypes.c_void_p, wt.DWORD, wt.DWORD, ctypes.c_void_p]
    user32.CloseDesktop.argtypes = [wt.HANDLE]
    kernel32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
    kernel32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
    kernel32.CloseHandle.argtypes = [wt.HANDLE]

    class STARTUPINFO(ctypes.Structure):
        _fields_ = [("cb", wt.DWORD), ("lpReserved", wt.LPWSTR), ("lpDesktop", wt.LPWSTR),
                    ("lpTitle", wt.LPWSTR), ("dwX", wt.DWORD), ("dwY", wt.DWORD),
                    ("dwXSize", wt.DWORD), ("dwYSize", wt.DWORD), ("dwXCountChars", wt.DWORD),
                    ("dwYCountChars", wt.DWORD), ("dwFillAttribute", wt.DWORD), ("dwFlags", wt.DWORD),
                    ("wShowWindow", wt.WORD), ("cbReserved2", wt.WORD), ("lpReserved2", ctypes.c_void_p),
                    ("hStdInput", wt.HANDLE), ("hStdOutput", wt.HANDLE), ("hStdError", wt.HANDLE)]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [("hProcess", wt.HANDLE), ("hThread", wt.HANDLE),
                    ("dwProcessId", wt.DWORD), ("dwThreadId", wt.DWORD)]

    name = f"srt_regression_{os.getpid()}"
    desk = user32.CreateDesktopW(name, None, None, 0, 0x01FF | 0x000F0000, None)
    if not desk:
        print("보이지 않는 데스크톱을 만들지 못했어요. --visible 로 다시 실행해 보세요.")
        return 2
    out_path = pathlib.Path(tempfile.gettempdir()) / f"srt_regression_{os.getpid()}.txt"
    out_path.write_bytes(b"")
    args = " ".join(_child_args(a))
    cmd = f'cmd /c ""{sys.executable}" -X utf8 "{__file__}" {args} > "{out_path}" 2>&1"'
    si = STARTUPINFO()
    si.cb = ctypes.sizeof(si)
    si.lpDesktop = name
    pi = PROCESS_INFORMATION()
    ok = kernel32.CreateProcessW(None, ctypes.create_unicode_buffer(cmd), None, None, False,
                                 0x08000000, None, os.getcwd(), ctypes.byref(si), ctypes.byref(pi))
    if not ok:
        user32.CloseDesktop(desk)
        print(f"테스트 프로세스를 시작하지 못했어요 (오류 {ctypes.GetLastError()}).")
        return 2

    dec = codecs.getincrementaldecoder("utf-8")(errors="replace")
    pos, deadline, timed_out = 0, time.time() + a.timeout, False

    def _drain():
        nonlocal pos
        with open(out_path, "rb") as f:
            f.seek(pos)
            chunk = f.read()
        pos += len(chunk)
        text = dec.decode(chunk).replace("\r\n", "\n")
        if text:
            sys.stdout.write(text)
            sys.stdout.flush()

    while kernel32.WaitForSingleObject(pi.hProcess, 300) != 0:
        _drain()
        if time.time() > deadline:
            timed_out = True
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pi.dwProcessId)],
                           capture_output=True)
            break
    time.sleep(0.2)
    _drain()
    code = wt.DWORD(1)
    kernel32.GetExitCodeProcess(pi.hProcess, ctypes.byref(code))
    kernel32.CloseHandle(pi.hProcess)
    kernel32.CloseHandle(pi.hThread)
    user32.CloseDesktop(desk)
    try:
        out_path.unlink()
    except OSError:
        pass
    if timed_out:
        print(f"\n제한 시간({a.timeout}초)을 넘겨 중단했어요.")
        return 2
    return int(code.value)


# ───────── 실제 테스트 실행 (자식 프로세스 또는 --visible) ─────────
def _run_suite(a):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    sys.path.insert(0, str(HERE))
    if not a.verbose:   # 앱을 닫은 뒤 늦게 끝나는 백그라운드 스레드가 stderr에 내는 소음은 숨김 (-v로 보기)
        sys.stderr = open(os.devnull, "w", encoding="utf-8")

    def _thread_hook(args):
        if "main thread is not in main loop" in str(args.exc_value):
            return
        print(f"[스레드 오류] {args.exc_type.__name__}: {args.exc_value}")
    threading.excepthook = _thread_hook

    import harness
    for f in sorted(HERE.glob("test_*.py")):
        importlib.import_module(f.stem)
    if a.list:
        for name, _ in harness.REGISTRY:
            print(name)
        print(f"\n총 {len(harness.REGISTRY)}개")
        return 0
    harness.setup()
    code = harness.run_all(a.only, a.verbose)
    sys.stdout.flush()
    os._exit(code)   # 남은 백그라운드 스레드(오디오·파형)가 종료를 막지 않게


def main():
    a = _parse()
    if a.child or a.visible or a.list or sys.platform != "win32":
        return _run_suite(a)
    return _run_hidden(a)


if __name__ == "__main__":   # 파형 추출 등 자식 프로세스가 이 파일을 다시 불러도 아무것도 실행하지 않게
    sys.exit(main())
