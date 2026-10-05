"""자막 교정: 문맥상 잘못 인식된 것 같은 표기를 찾아 줄별로 제안하고, 확인한 것만 적용."""
import threading
import tkinter as tk
from .. import dialogs as messagebox

from .. import correction, theme
from ..theme import ACCENT, BG, BG2, BG3, BORDER, FG, FG_DIM, FG_HINT, _apply_dark_titlebar
from ..widgets import ToggleSwitch, flat_button

_WRONG_FG = "#E08080"
_RIGHT_FG = "#7FD48F"


class CorrectionMixin:
    """자막 교정 창."""

    def _open_correction_dialog(self):
        if not self.subtitles:
            messagebox.showwarning("자막 교정", "자막을 먼저 열어 주세요.", parent=self)
            return
        self._blur_all_entries()   # 입력 중이던 내용부터 확정
        self._ensure_proper_nouns_init()
        texts = [s.get("text", "") for s in self.subtitles]
        fixes = correction.suggest(texts, proper_nouns=self._proper_nouns)
        if not fixes:
            messagebox.showinfo("자막 교정", "고칠 표기를 찾지 못했어요.", parent=self)
            return

        win = tk.Toplevel(self)
        win.withdraw()
        win.title("자막 교정")
        win.configure(bg=BG)
        win.geometry("700x580")
        win.minsize(540, 380)
        win.transient(self)

        # ── 머리글 ────────────────────────────
        head = tk.Frame(win, bg=BG)
        head.pack(fill="x", padx=28, pady=(22, 10))
        right_box = tk.Frame(head, bg=BG)
        right_box.pack(side="right", anchor="n")
        title_lbl = tk.Label(head, text="", bg=BG, fg=FG, font=(theme.FONT_FAMILY, 15, "bold"))
        title_lbl.pack(anchor="w")
        tk.Label(head, text="앞뒤 문맥을 보고 잘못 인식된 것 같은 표기를 찾았어요. 켠 줄만 바뀌어요.",
                 bg=BG, fg=FG_DIM, font=(theme.FONT_FAMILY, 9)).pack(anchor="w", pady=(3, 0))
        status_lbl = tk.Label(head, text="", bg=BG, fg=FG_DIM, font=(theme.FONT_FAMILY, 9))
        status_lbl.pack(anchor="w", pady=(4, 0))

        footer = tk.Frame(win, bg=BG)
        footer.pack(side="bottom", fill="x", padx=28, pady=(8, 16))
        tk.Frame(win, bg=BORDER, height=1).pack(side="bottom", fill="x")

        outer, inner = self._make_scrollable(win)
        outer.pack(fill="both", expand=True, padx=16)

        cards = []   # (fix, var, card, reasons_frame)

        def _text_line(parent, text, word, color, start=None):
            """한 줄 문장에서 word만 색을 입혀 보여 줌 (start: 칠할 위치)."""
            t = tk.Text(parent, height=1, width=1, bg=BG2, fg=FG, bd=0, highlightthickness=0,
                        font=(theme.FONT_FAMILY, 11), cursor="hand2", wrap="none")
            t.insert("1.0", text)
            if start is None:
                start = text.find(word)
            if start >= 0:
                t.tag_add("w", f"1.{start}", f"1.{start + len(word)}")
                t.tag_configure("w", foreground=color,
                                font=(theme.FONT_FAMILY, 11, "bold"))
            t.configure(state="disabled")
            return t

        def _fill_reasons(box, fix):
            for w in box.winfo_children():
                w.destroy()
            for r in fix.reasons:
                good = fix.audio != "wrong"
                tk.Label(box, text=r, bg=BG3, fg=FG_DIM if good else _WRONG_FG, padx=8, pady=2,
                         font=(theme.FONT_FAMILY, 8)).pack(side="left", padx=(0, 4))

        def _build_card(fix):
            var = tk.BooleanVar(value=fix.checked)
            card = tk.Frame(inner, bg=BG2, highlightthickness=1, highlightbackground=BORDER,
                            cursor="hand2")
            card.pack(fill="x", padx=12, pady=5)
            top = tk.Frame(card, bg=BG2)
            top.pack(fill="x", padx=14, pady=(10, 4))
            ToggleSwitch(top, var, _update_title).pack(side="right")
            tk.Label(top, text=f"{fix.line + 1}번째 줄", bg=BG2, fg=FG_DIM,
                     font=(theme.FONT_FAMILY, 9)).pack(side="left")
            tk.Label(top, text=f"   {fix.wrong}  →  {fix.right}", bg=BG2, fg=FG,
                     font=(theme.FONT_FAMILY, 9, "bold")).pack(side="left")

            before = self.subtitles[fix.line].get("text", "")
            after = correction.apply([before], [correction.Fix(0, fix.wrong, fix.right, fix.kind)])[0]
            body = tk.Frame(card, bg=BG2)
            body.pack(fill="x", padx=14)
            pos = correction.find_word(before, fix.wrong)
            _text_line(body, before, fix.wrong, _WRONG_FG, pos).pack(fill="x")
            _text_line(body, after, fix.right, _RIGHT_FG, pos).pack(fill="x", pady=(2, 0))
            reasons = tk.Frame(card, bg=BG2)
            reasons.pack(fill="x", padx=14, pady=(6, 10))
            _fill_reasons(reasons, fix)
            for w in (card, top, body) + tuple(body.winfo_children()):
                w.bind("<Button-1>", lambda e, i=fix.line: self._goto_correction_line(i))
            card.hidden = False
            cards.append((fix, var, card, reasons))

        def _update_title():
            on = sum(1 for _, v, c, _ in cards if v.get() and not c.hidden)
            shown = sum(1 for _, _, c, _ in cards if not c.hidden)
            title_lbl.configure(text=f"교정 제안 {shown}건  ·  {on}건 선택")

        for f in fixes:
            _build_card(f)
        _update_title()

        # ── 음성으로 다시 확인 (미디어가 있을 때) ──
        state = {"cancel": False}

        def _audio_check():
            items, targets = [], []
            for fix, var, card, _ in cards:
                t_s, t_e = (self._ts_cache[fix.line] if fix.line < len(self._ts_cache)
                            else (None, None))
                if t_s is None or t_e is None or fix.audio is not None:
                    continue
                items.append((t_s, t_e, fix.wrong, fix.right))
                targets.append(fix)
            if not items:
                return
            check_btn.configure(text="확인 중…")
            mode = getattr(self, "_diarize_mode_init", None) or "accurate"
            device = getattr(self, "_diarize_device_init", "auto")

            def on_ev(ev):
                if ev.get("type") == "status" and ev.get("msg"):
                    self.after(0, lambda m=ev["msg"]: status_lbl.winfo_exists() and status_lbl.configure(text=m))

            def work():
                try:
                    res = self._run_ai_job({"type": "verify", "media": self.media_path, "items": items,
                                            "mode": mode, "device": device},
                                           on_event=on_ev, cancelled=lambda: state["cancel"])
                    results, err = res["results"], None
                except Exception as e:
                    results, err = [], f"음성 확인 중 오류가 났어요: {e}"
                self.after(0, lambda: _audio_done(targets, results, err))
            self._ensure_ai(lambda: threading.Thread(target=work, daemon=True).start())

        def _audio_done(targets, results, err):
            if not win.winfo_exists():
                return
            check_btn.configure(text="음성으로 다시 확인")
            if err:
                status_lbl.configure(text=err, fg=_WRONG_FG)
                return
            right = wrong = 0
            for fix, heard in zip(targets, results):
                correction.apply_audio(fix, heard)
                right += heard == "right"
                wrong += heard == "wrong"
            for fix, var, card, reasons in cards:
                if fix.audio is None:
                    continue
                var.set(fix.checked)
                _fill_reasons(reasons, fix)
                if fix.audio == "wrong":   # 음성으로 원래 표기가 맞다고 확인되면 숨김
                    card.pack_forget()
                    card.hidden = True
            status_lbl.configure(
                text=f"음성 확인 완료  ·  바른 표기로 들림 {right}건, 원래대로 들림 {wrong}건 (숨김)",
                fg=FG_DIM)
            _update_title()

        if getattr(self, "media_path", None):
            check_btn = flat_button(right_box, "음성으로 다시 확인", _audio_check,
                                    bg=theme.ON_BG, fg=theme.ON_FG, hover=theme.ON_BG_HOVER,
                                    padx=14, pady=6)
            check_btn.pack()
        else:
            tk.Label(right_box, text="미디어를 열면 음성으로\n다시 확인할 수 있어요",
                     bg=BG, fg=FG_HINT, justify="right",
                     font=(theme.FONT_FAMILY, 8)).pack()

        # ── 하단 버튼 ─────────────────────────
        def _toggle_all():
            vis = [v for _, v, c, _ in cards if not c.hidden]
            on = not all(v.get() for v in vis)
            for v in vis:
                v.set(on)
            _update_title()

        def _apply():
            chosen = [f for f, v, c, _ in cards if v.get() and not c.hidden]
            _close()
            if not chosen:
                return
            changed = self._apply_corrections(chosen)
            messagebox.showinfo("자막 교정", f"{changed}줄을 고쳤어요. (Ctrl+Z로 되돌리기)", parent=self)

        def _close():
            state["cancel"] = True
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", _close)

        flat_button(footer, "전체 켜기/끄기", _toggle_all, bg=BG3, hover="#33333C",
                    padx=14, pady=6).pack(side="left")
        flat_button(footer, "닫기", _close, bg=BG3, hover="#33333C",
                    padx=16, pady=6).pack(side="right")
        flat_button(footer, "선택한 줄 고치기", _apply, bg=ACCENT, fg="white", hover="#AE96E2",
                    font=(theme.FONT_FAMILY, 9, "bold"), padx=16, pady=6
                    ).pack(side="right", padx=(0, 8))

        # 위치를 잡은 뒤 표시 (흰 창 번쩍임 방지)
        win.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - win.winfo_reqwidth()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - win.winfo_reqheight()) // 3
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
        try:
            win.attributes("-alpha", 0.0)
        except tk.TclError:
            pass
        win.deiconify()
        _apply_dark_titlebar(win)
        win.after(40, lambda: win.winfo_exists() and win.attributes("-alpha", 1.0))
        win.grab_set()

    def _goto_correction_line(self, idx):
        if 0 <= idx < len(self.subtitles):
            self._scroll_to_row(idx)
            self._select_row(idx, seek=False)

    def _apply_corrections(self, fixes):
        """제안을 해당 줄에만 적용하고 바뀐 자막 수를 반환. 한 번의 실행 취소로 되돌릴 수 있다."""
        texts = [s.get("text", "") for s in self.subtitles]
        fixed = correction.apply(texts, fixes)
        changed = [i for i, (a, b) in enumerate(zip(texts, fixed)) if a != b]
        if not changed:
            return 0
        self._push_undo()
        for i in changed:
            self.subtitles[i]["text"] = fixed[i]
        self._unsaved = True
        self._fill_slots(self._vscroll_top)
        self._wf_img_cache = None
        self._pb_redraw()
        return len(changed)
