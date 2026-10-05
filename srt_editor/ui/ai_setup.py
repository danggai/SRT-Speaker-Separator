"""AI 부품(whisperx·torch) 설치 창과 설정 카드, AI 작업 실행 도우미."""
import threading
import tkinter as tk
from .. import dialogs as messagebox

from .. import ai_runtime, theme
from ..theme import ACCENT, BG, BG2, BG3, BORDER, FG, FG_DIM, FG_HINT
from ..widgets import Segmented, _gradient_bar_rows, flat_button, present_dialog


def _fmt_gb(nbytes):
    return f"{nbytes / 1073741824:.1f} GB"


class AISetupMixin:
    """AI 부품 설치·상태 표시와 작업 실행."""

    def _ai_device_pref(self):
        var = getattr(self, "_diarize_device_var", None)
        try:
            return var.get() if var is not None else getattr(self, "_diarize_device_init", "auto")
        except tk.TclError:
            return getattr(self, "_diarize_device_init", "auto")

    def _ensure_ai(self, then):
        """AI 부품이 있으면 바로 then(), 없으면 설치 창을 띄우고 설치가 끝나면 then()."""
        if ai_runtime.ai_python():
            then()
            return
        self._open_ai_install_dialog(on_done=then, needed=True)

    def _open_ai_install_dialog(self, on_done=None, needed=False):
        """AI 부품 설치 창: GPU/CPU 선택 → 내려받기 진행률 → 완료되면 on_done()."""
        win = tk.Toplevel(self)
        win.withdraw()
        win.title("AI 부품 설치")
        win.configure(bg=BG)
        win.resizable(False, False)
        win.transient(self)
        state = {"cancel": False, "running": False, "pct": 0.0, "shown": 0.0, "phase": 0.0}

        body = tk.Frame(win, bg=BG)
        body.pack(fill="both", expand=True, padx=28, pady=(22, 8))
        tk.Label(body, text="AI 부품 설치", bg=BG, fg=FG, font=(theme.FONT_FAMILY, 15, "bold")).pack(anchor="w")
        desc = "자동 자막·화자 분석에 필요해요. 처음 한 번만 설치해요."
        tk.Label(body, text=desc, bg=BG, fg=FG_DIM, justify="left",
                 font=(theme.FONT_FAMILY, 9)).pack(anchor="w", pady=(4, 14))

        card = tk.Frame(body, bg=BG2, highlightthickness=1, highlightbackground=BORDER)
        card.pack(fill="x")
        row = tk.Frame(card, bg=BG2)
        row.pack(fill="x", padx=14, pady=12)
        tk.Label(row, text="처리 장치", bg=BG2, fg=FG, font=(theme.FONT_FAMILY, 10, "bold")).pack(anchor="w")
        gpu = ai_runtime.has_nvidia_gpu()
        dev_var = tk.StringVar(value="cuda" if gpu else "cpu")
        Segmented(row, [(f"NVIDIA GPU  (약 {ai_runtime.EST_MB['cuda'] / 1024:.0f} GB)", "cuda"),
                        (f"CPU만  (약 {ai_runtime.EST_MB['cpu'] / 1024:.0f} GB)", "cpu")],
                  dev_var).pack(anchor="w", pady=(8, 4))
        tk.Label(row, text=("NVIDIA GPU 있음" if gpu else "NVIDIA GPU 없음 · CPU 권장"),
                 bg=BG2, fg=FG_HINT, font=(theme.FONT_FAMILY, 8)).pack(anchor="w")
        tk.Label(body, text=f"설치 위치: {ai_runtime.ROOT}", bg=BG, fg=FG_HINT, justify="left", wraplength=460,
                 font=(theme.FONT_FAMILY, 8)).pack(anchor="w", pady=(8, 0))

        prog = tk.Frame(body, bg=BG)
        status = tk.Label(prog, text="", bg=BG, fg=FG, anchor="w", font=(theme.FONT_FAMILY, 9, "bold"))
        status.pack(fill="x", pady=(14, 6))
        bar_w, bar_h = 440, 16
        bar = tk.Canvas(prog, width=bar_w, height=bar_h, bg=BG3, highlightthickness=1, highlightbackground=BORDER)
        bar.pack(anchor="w")
        bar_img = tk.PhotoImage(width=bar_w, height=bar_h)
        bar.create_image(0, 0, anchor="nw", image=bar_img)
        pct_id = bar.create_text(bar_w // 2, bar_h // 2, text="0%", fill=FG_DIM, font=(theme.FONT_FAMILY, 7, "bold"))

        footer = tk.Frame(win, bg=BG)
        footer.pack(fill="x", padx=24, pady=(10, 16))

        def _draw():
            if not state["running"] or not win.winfo_exists():
                return
            state["shown"] += (state["pct"] - state["shown"]) * 0.15
            fw = int(bar_w * state["shown"] / 100)
            bar_img.put(_gradient_bar_rows(bar_w, bar_h, fw, state["phase"], BG3))
            bar.itemconfigure(pct_id, text=f"{int(state['shown'])}%", fill="white" if fw > bar_w // 2 else FG_DIM)
            state["phase"] += 0.18
            win.after(40, _draw)

        def _progress(msg, pct):
            state["pct"] = float(pct)
            self.after(0, lambda: status.winfo_exists() and status.configure(text=msg))

        def _cancel():
            if state["running"]:
                if messagebox.askyesno("설치 중단", "설치를 중단할까요?", parent=win, yes="중단", no="계속"):
                    state["cancel"] = True
            else:
                win.destroy()

        def _finish(info, err):
            state["running"] = False
            if not win.winfo_exists():
                return
            win.destroy()
            if err:
                if not state["cancel"]:
                    messagebox.showerror("AI 부품 설치 실패", err[:900], parent=self)
                return
            msg = "설치 완료"
            if info.get("device") == "cuda":
                msg += (f" · GPU ({info.get('gpu')})" if info.get("cuda") else
                        "\nGPU를 못 써서 CPU로 동작해요. 드라이버 업데이트 후 다시 설치해 보세요.")
            messagebox.showinfo("설치 완료", msg, parent=self)
            if on_done:
                on_done()

        def _start():
            start_btn.destroy()
            card.pack_forget()
            prog.pack(fill="x")
            state["running"] = True
            _draw()
            device = dev_var.get()

            def work():
                try:
                    info = ai_runtime.install(device, _progress, lambda: state["cancel"])
                    err = None
                except ai_runtime.AIError as e:
                    info, err = None, str(e)
                except Exception as e:
                    info, err = None, f"설치 중 오류가 났어요: {e}"
                self.after(0, lambda: _finish(info, err))
            threading.Thread(target=work, daemon=True).start()

        start_btn = flat_button(footer, "설치 시작", _start, bg=ACCENT, fg="white", hover="#AE96E2",
                                font=(theme.FONT_FAMILY, 10, "bold"), padx=22, pady=8)
        start_btn.pack(side="right")
        flat_button(footer, "취소", _cancel, bg=BG3, hover="#33333C",
                    font=(theme.FONT_FAMILY, 10), padx=18, pady=8).pack(side="right", padx=(0, 8))
        win.protocol("WM_DELETE_WINDOW", _cancel)
        present_dialog(win, self)
        return win

    def _build_ai_card(self, parent):
        """설정 → 저장 공간의 'AI 부품' 카드: 상태와 설치·다시 설치·삭제."""
        card = self._settings_card(parent, "AI 부품")
        left, right = self._settings_row(card, "AI", "AI 부품", "자동 자막·화자 분석용")
        info_lbl = tk.Label(left, text="", bg=BG2, fg=ACCENT, anchor="w", justify="left",
                            font=(theme.FONT_FAMILY, 9, "bold"))
        info_lbl.pack(fill="x", pady=(4, 0))

        def _refresh():
            for w in right.winfo_children():
                w.destroy()
            info = ai_runtime.installed_info()
            if info:
                dev = f"GPU ({info.get('gpu')})" if info.get("cuda") else "CPU"
                info_lbl.configure(text=f"설치됨  ·  {dev}  ·  용량 계산 중…")

                def size():
                    sz = ai_runtime.dir_size(ai_runtime.ROOT)
                    self.after(0, lambda: info_lbl.winfo_exists() and info_lbl.configure(
                        text=f"설치됨  ·  {dev}  ·  {_fmt_gb(sz)}"))
                threading.Thread(target=size, daemon=True).start()
                flat_button(right, "다시 설치", lambda: self._open_ai_install_dialog(on_done=_refresh),
                            bg=BG3, hover="#33333C", padx=12, pady=6).pack(side="left", padx=(0, 6))
                flat_button(right, "삭제", _remove, bg="#5A2A2E", fg="#FFD8D8", hover="#6E3438",
                            padx=12, pady=6).pack(side="left")
            elif ai_runtime.ai_python():
                info_lbl.configure(text="개발 환경 파이썬 사용 중")
                flat_button(right, "따로 설치", lambda: self._open_ai_install_dialog(on_done=_refresh),
                            bg=BG3, hover="#33333C", padx=12, pady=6).pack(side="left")
            else:
                info_lbl.configure(text="설치 안 됨", fg=FG_DIM)
                flat_button(right, "설치", lambda: self._open_ai_install_dialog(on_done=_refresh),
                            bg=ACCENT, fg="white", hover="#AE96E2", padx=14, pady=6).pack(side="left")

        def _remove():
            if messagebox.askyesno("AI 부품 삭제", "AI 부품을 지울까요?", parent=parent.winfo_toplevel(), yes="삭제", no="취소"):
                ai_runtime.uninstall()
                _refresh()
        _refresh()
        return card

    def _run_ai_job(self, job, on_event=None, cancelled=None):
        """AI 작업 실행 (작업 스레드에서 호출). 처리 장치 설정을 채워 넣는다."""
        job = dict(job)
        job.setdefault("device", self._ai_device_pref())
        return ai_runtime.run_job(job, on_event=on_event, cancelled=cancelled)
