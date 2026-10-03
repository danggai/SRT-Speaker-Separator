"""색상 팔레트, 폰트, 다크 타이틀바 등 화면 테마."""
import sys


# ── Windows 다크 타이틀바 ─────────────────────────
TITLEBAR_BG = "#202024"   # 툴바와 같은 색
TITLEBAR_FG = "#E0E0E0"


def _colorref(hex_color):
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return r | (g << 8) | (b << 16)


def _apply_dark_titlebar(window):
    """창 제목표시줄을 다크 모드 + 앱 색상으로 맞춘다 (메인 창·팝업 공통)."""
    if sys.platform != "win32":
        return

    def _apply():
        try:
            import ctypes
            dwm = ctypes.windll.dwmapi
            hwnd = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()

            def _set(attr, val):
                v = ctypes.c_int(val)
                return dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))

            for attr in (20, 19):   # 20=최신 Windows, 19=구버전 빌드
                if _set(attr, 1) == 0:
                    break
            _set(35, _colorref(TITLEBAR_BG))   # 제목표시줄 배경 (Windows 11)
            _set(36, _colorref(TITLEBAR_FG))   # 제목 글자
        except Exception:
            pass

    try:
        window.update_idletasks()
    except Exception:
        return
    _apply()
    # 창이 실제로 화면에 뜬 뒤 다시 적용 (생성 직후엔 적용이 안 되는 경우 대비)
    window.bind("<Map>", lambda e: _apply() if e.widget is window else None, add="+")


# ─────────────────────────────────────────────
#  색상 팔레트 (화자별 자동 배정)
# ─────────────────────────────────────────────
# 색상 프리셋에서 서로 잘 구분되는 순서로 (기본 → 차분 → 밝게)
SPEAKER_COLORS = [
    "#D63838", "#387AD6", "#38D65F", "#D67C38",
    "#8238D6", "#38D6C6", "#D1AD36", "#D63887",
    "#9E4C4C", "#4C6E9E", "#4C9E60", "#9E704C",
    "#724C9E", "#4C9E96", "#9E8B4C", "#9E4C75",
    "#F28D8D", "#8DB7F2", "#8DF2A6", "#F2B98D",
    "#BC8DF2", "#8DF2E8", "#F2DB8D", "#F28DBF",
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

# 켜짐(ON) 상태 공통 스타일: 얇은 둥근 테두리 + 연한 보라 배경
ON_BG       = "#2A2740"
ON_BG_HOVER = "#33304A"
ON_BORDER   = "#6E5AA8"
ON_FG       = ACCENT
ON_RADIUS   = 6


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
