"""앱 안에서 새 버전 EXE를 내려받아 바꿔 끼우기."""
import os
import sys
import threading
import tkinter as tk
import webbrowser
from .. import dialogs as messagebox

from .. import theme, version
from ..theme import BG2, BG3, BORDER, FG, FG_DIM
from ..widgets import DimOverlay, _gradient_bar_rows, flat_button


class UpdateMixin:
    """업데이트 배지 클릭 → 내려받기 → 앱을 닫고 새 버전 실행."""

    def _on_update_click(self, v):
        frozen = getattr(sys, "frozen", False)
        ans = messagebox.askyesno("업데이트", f"새 버전 v{v}이 나왔어요 (현재 v{version.APP_VERSION}).",
                                  parent=self, yes="지금 업데이트" if frozen else "페이지 열기", no="나중에")
        if not ans:
            return
        if not frozen:   # 개발 환경: EXE가 없으니 페이지만
            webbrowser.open(version.GITHUB_TAGS_URL)
            return
        self._download_update(v)

    def _download_update(self, v):
        ov = DimOverlay(self)
        card = ov.card
        tk.Label(card, text=f"v{v} 내려받는 중", bg=BG2, fg=FG,
                 font=(theme.FONT_FAMILY, 11, "bold")).pack(padx=40, pady=(18, 4))
        status = tk.Label(card, text="확인 중...", bg=BG2, fg=FG_DIM, font=(theme.FONT_FAMILY, 9))
        status.pack()
        bw, bh = 340, 16
        bar = tk.Canvas(card, width=bw, height=bh, bg=BG3, highlightthickness=1, highlightbackground=BORDER)
        bar.pack(padx=40, pady=(10, 4))
        img = tk.PhotoImage(width=bw, height=bh)
        bar.create_image(0, 0, anchor="nw", image=img)
        st = {"pct": 0.0, "shown": 0.0, "phase": 0.0, "cancel": False, "run": True}

        def _cancel():
            st["cancel"] = True
            st["run"] = False
            ov.destroy()
        flat_button(card, "취소", _cancel, bg=BG3, hover="#33333C", padx=16, pady=5).pack(pady=(10, 16))

        def _draw():
            if not st["run"]:
                return
            try:
                st["shown"] += (st["pct"] - st["shown"]) * 0.2
                img.put(_gradient_bar_rows(bw, bh, int(bw * st["shown"] / 100), st["phase"], BG3))
                st["phase"] += 0.18
                ov.after(50, _draw)
            except tk.TclError:
                pass
        _draw()

        def _prog(done, total):
            st["pct"] = 100.0 * done / total if total else 0
            txt = f"{done / 1048576:,.0f} / {total / 1048576:,.0f} MB" if total else f"{done / 1048576:,.0f} MB"
            self.after(0, lambda: status.winfo_exists() and status.configure(text=txt))

        def _fail(msg):
            st["run"] = False
            try:
                ov.destroy()
            except tk.TclError:
                pass
            if messagebox.askyesno("업데이트 실패", msg, parent=self, yes="페이지 열기", no="닫기"):
                webbrowser.open(version.GITHUB_TAGS_URL)

        def _done(new_exe):
            st["run"] = False
            try:
                ov.destroy()
            except tk.TclError:
                pass
            old_exe = sys.executable
            self._on_close(before_exit=lambda: version.launch_after_exit(new_exe, old_exe, os.getpid()))

        def work():
            try:
                asset = version.release_exe(v)
                if not asset:
                    self.after(0, lambda: _fail("내려받을 파일을 찾지 못했어요."))
                    return
                name, url, _ = asset
                dest = os.path.join(os.path.dirname(sys.executable), name)
                if os.path.normcase(dest) == os.path.normcase(sys.executable):   # 이름이 같으면 옆에 받아 둠
                    dest = os.path.join(os.path.dirname(sys.executable), f"_new_{name}")
                if not version.download(url, dest, _prog, lambda: st["cancel"]):
                    return
                self.after(0, lambda: _done(dest))
            except Exception as e:   # noqa: BLE001
                if not st["cancel"]:
                    self.after(0, lambda: _fail(f"내려받지 못했어요.\n{e}"))
        threading.Thread(target=work, daemon=True).start()
        return ov
