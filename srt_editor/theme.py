"""색상 팔레트, 폰트, 다크 타이틀바 등 화면 테마."""
import sys


# ── Windows 다크 타이틀바 강제 적용 ─────────────────────────
# Toplevel(설정/대화상자 등) 창은 Windows에서 메인 창과 달리 시스템 다크
# 테마가 자동으로 적용되지 않아 흰색 타이틀바로 튀는 경우가 있다.
# DWM API로 명시적으로 다크 모드를 지정해 항상 앱 배경과 어울리게 한다.
def _apply_dark_titlebar(window):
    if sys.platform != "win32":
        return
    try:
        import ctypes
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1)
        for attr in (20, 19):   # 20=최신 Windows, 19=구버전 빌드 호환
            res = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attr, ctypes.byref(value), ctypes.sizeof(value))
            if res == 0:
                break
    except Exception:
        pass


# ─────────────────────────────────────────────
#  색상 팔레트 (화자별 자동 배정)
# ─────────────────────────────────────────────
SPEAKER_COLORS = [
    "#4A90E2", "#E25C5C", "#50C878", "#F5A623",
    "#9B59B6", "#1ABC9C", "#E67E22", "#E91E8C",
    "#00BCD4", "#8BC34A",
]

BG        = "#1A1A1A"
BG2       = "#141414"
BG3       = "#242424"
ACCENT    = "#9B7FD4"   # 연보라 포인트
FG        = "#E0E0E0"
FG_DIM    = "#777777"
BORDER    = "#333333"
ROW_ODD   = "#1E1E1E"
ROW_EVEN  = "#1A1A1A"
ROW_SEL   = "#2D2040"   # 선택 시 연보라 tint (Treeview용)
ROW_HL    = "#221A35"   # 행 하이라이트 배경 (아주 연한 보라)
MEDIA_BG  = "#111111"


def _pick_font(root=None):
    """시스템에서 한글 지원 폰트를 찾아 반환.
    root가 주어지면 해당 Tk 인스턴스 기준으로 폰트 목록 조회 (빈 창 없음).
    root가 없으면 후보 목록을 이름만으로 반환 (OS별 기본값 우선)."""
    if root is not None:
        try:
            import tkinter.font as tkfont
            available = set(tkfont.families(root))
        except Exception:
            available = set()
    else:
        # 창을 띄우지 않고 OS 기반 우선순위만 사용
        available = set()

    candidates = [
        "Malgun Gothic",       # Windows 기본 한글
        "맑은 고딕",
        "Apple SD Gothic Neo", # macOS 기본 한글
        "AppleGothic",
        "Nanum Gothic",
        "NanumGothic",
        "NotoSansCJKkr",
        "Noto Sans CJK KR",
        "UnDotum",             # Linux 한글
        "Gulim",
        "Segoe UI",
        "TkDefaultFont",
    ]
    if available:
        for f in candidates:
            if f in available:
                return f
    # 창 없이 호출된 경우: OS 추측
    import sys
    if sys.platform == "win32":
        return "Malgun Gothic"
    if sys.platform == "darwin":
        return "Apple SD Gothic Neo"
    return "TkDefaultFont"

# 모듈 로드 시점에는 창을 띄우지 않고 OS 기본값으로 초기화
# 실제 앱 시작 후 _init_font()에서 정확한 값으로 교체됨
FONT_FAMILY = _pick_font(root=None)
FONT_MONO   = "Courier New"
