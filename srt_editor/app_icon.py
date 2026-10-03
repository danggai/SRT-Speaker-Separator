"""앱 아이콘 (Pillow로 그림). 창 아이콘과 exe 빌드용 .ico 생성."""
import sys

from PIL import Image, ImageDraw

_SS = 4   # 안티앨리어싱용 확대 배율
_BG_TOP = (0x9B, 0x7F, 0xD4)
_BG_BOTTOM = (0x5E, 0x45, 0xA8)
_DOTS = ("#FFD166", "#4ECDC4")
_ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]


def make_icon(size=256):
    """둥근 사각형 바탕 + 화자 점이 붙은 자막 줄 두 개."""
    s = size * _SS
    grad = Image.new("RGB", (1, s))
    for y in range(s):
        t = y / max(1, s - 1)
        grad.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(_BG_TOP, _BG_BOTTOM)))
    grad = grad.resize((s, s))
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * 0.22), fill=255)
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    img.paste(grad, (0, 0), mask)

    d = ImageDraw.Draw(img)
    bar_h = s * 0.15
    dot_r = s * 0.075
    x_dot = s * 0.25
    x0, x1s = s * 0.38, (s * 0.80, s * 0.68)
    for (cy, color, x1) in zip((s * 0.38, s * 0.64), _DOTS, x1s):
        d.ellipse((x_dot - dot_r, cy - dot_r, x_dot + dot_r, cy + dot_r), fill=color)
        d.rounded_rectangle((x0, cy - bar_h / 2, x1, cy + bar_h / 2), radius=bar_h / 2,
                            fill=(255, 255, 255, 240))
    return img.resize((size, size), Image.LANCZOS)


def save_ico(path):
    """exe 빌드용 .ico 저장."""
    make_icon(256).save(path, sizes=[(n, n) for n in _ICO_SIZES])


def set_app_id():
    """python으로 실행해도 작업 표시줄에 앱 아이콘이 뜨도록 별도 앱으로 등록 (창 만들기 전 호출)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("danggai.SRTSpeakerEditor")
    except Exception:
        pass


def apply_icon(root):
    """창 아이콘 지정 (이후 만드는 창에도 적용)."""
    try:
        from PIL import ImageTk
        root._app_icons = [ImageTk.PhotoImage(make_icon(n)) for n in (16, 32, 48, 256)]
        root.iconphoto(True, *root._app_icons)
    except Exception:
        pass


if __name__ == "__main__":
    save_ico(sys.argv[1] if len(sys.argv) > 1 else "icon.ico")
