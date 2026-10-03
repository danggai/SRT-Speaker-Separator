"""자막 교정: 오인식으로 보이는 표기를 찾아 제안하고, 확인한 것만 적용."""
import tkinter as tk
from tkinter import messagebox

from .. import correction, theme
from ..theme import ACCENT, BG, BG2, BG3, BORDER, FG, FG_DIM, _apply_dark_titlebar


class CorrectionMixin:
    """자막 교정 창 (반복 단어 통일 · 고유명사 사전)."""

    def _open_correction_dialog(self):
        if not self.subtitles:
            messagebox.showwarning("자막 교정", "자막을 먼저 불러오세요.", parent=self)
            return
        self._blur_all_entries()   # 입력 중이던 내용부터 확정
        self._ensure_proper_nouns_init()
        texts = [s.get("text", "") for s in self.subtitles]
        suggestions = correction.suggest(texts, proper_nouns=self._proper_nouns)
        if not suggestions:
            messagebox.showinfo(
                "자막 교정",
                "교정할 항목을 찾지 못했습니다.\n\n"
                "자주 나오는 이름·용어를 고유명사 사전에 등록하면,\n"
                "비슷하게 잘못 인식된 표기도 찾아 바꿀 수 있습니다.",
                parent=self)
            return

        win = tk.Toplevel(self)
        _apply_dark_titlebar(win)
        win.title("자막 교정")
        win.configure(bg=BG)
        win.geometry("620x520")
        win.minsize(480, 320)
        win.transient(self)
        win.grab_set()

        tk.Label(win, text=f"교정 제안 {len(suggestions)}건", bg=BG, fg=FG,
                 font=(theme.FONT_FAMILY, 11, "bold")).pack(anchor="w", padx=16, pady=(14, 2))
        tk.Label(win,
                 text="자주 나온 표기와 거의 같은데 드물게 나온 표기, 고유명사 사전과 비슷한 표기를\n"
                      "찾았습니다. 체크한 항목만 적용되며, 줄 수를 누르면 해당 자막으로 이동합니다.",
                 bg=BG, fg=FG_DIM, font=(theme.FONT_FAMILY, 8), justify="left"
                 ).pack(anchor="w", padx=16, pady=(0, 8))

        footer = tk.Frame(win, bg=BG)
        footer.pack(side="bottom", fill="x", padx=16, pady=(6, 12))
        tk.Frame(win, bg=BORDER, height=1).pack(side="bottom", fill="x")

        outer, inner = self._make_scrollable(win)
        outer.pack(fill="both", expand=True, padx=8)

        rows = []
        for sg in suggestions:
            var = tk.BooleanVar(value=True)
            row = tk.Frame(inner, bg=BG2, highlightthickness=1, highlightbackground=BORDER)
            row.pack(fill="x", padx=8, pady=3)
            tk.Checkbutton(row, variable=var, bg=BG2, activebackground=BG2,
                           selectcolor=BG3, cursor="hand2").pack(side="left", padx=(6, 2))
            body = tk.Frame(row, bg=BG2)
            body.pack(side="left", fill="x", expand=True, pady=4)
            line1 = tk.Frame(body, bg=BG2)
            line1.pack(anchor="w")
            tk.Label(line1, text=sg.wrong, bg=BG2, fg="#E08080",
                     font=(theme.FONT_FAMILY, 10, "bold")).pack(side="left")
            tk.Label(line1, text="  →  ", bg=BG2, fg=FG_DIM,
                     font=(theme.FONT_FAMILY, 10)).pack(side="left")
            tk.Label(line1, text=sg.right, bg=BG2, fg="#7FD48F",
                     font=(theme.FONT_FAMILY, 10, "bold")).pack(side="left")
            tk.Label(line1, text=f"   {sg.reason}", bg=BG2, fg=FG_DIM,
                     font=(theme.FONT_FAMILY, 8)).pack(side="left")
            first = sg.lines[0] if sg.lines else None
            if first is not None:
                example = self.subtitles[first].get("text", "")
                tk.Label(body, text=example if len(example) <= 60 else example[:60] + "…",
                         bg=BG2, fg=FG_DIM, font=(theme.FONT_FAMILY, 8),
                         anchor="w").pack(anchor="w")
                tk.Button(row, text=f"{len(sg.lines)}줄", bg=BG3, fg=FG, relief="flat", bd=0,
                          cursor="hand2", font=(theme.FONT_FAMILY, 8), padx=8,
                          activebackground=BG, activeforeground=FG,
                          command=lambda i=first: self._goto_correction_line(i)
                          ).pack(side="right", padx=8)
            rows.append((sg, var))

        def _toggle_all():
            on = not all(v.get() for _, v in rows)
            for _, v in rows:
                v.set(on)

        def _apply():
            chosen = [sg for sg, v in rows if v.get()]
            if not chosen:
                win.destroy()
                return
            changed = self._apply_corrections(chosen)
            win.destroy()
            messagebox.showinfo("자막 교정", f"{changed}개 자막을 교정했습니다.\n(실행 취소: Ctrl+Z)",
                                parent=self)

        tk.Button(footer, text="전체 선택/해제", bg=BG3, fg=FG, relief="flat", bd=0,
                  cursor="hand2", font=(theme.FONT_FAMILY, 9), padx=12, pady=5,
                  activebackground=BG2, command=_toggle_all).pack(side="left")
        tk.Button(footer, text="닫기", bg=BG3, fg=FG, relief="flat", bd=0,
                  cursor="hand2", font=(theme.FONT_FAMILY, 9), padx=14, pady=5,
                  activebackground=BG2, command=win.destroy).pack(side="right")
        tk.Button(footer, text="선택 항목 적용", bg=ACCENT, fg="white", relief="flat", bd=0,
                  cursor="hand2", font=(theme.FONT_FAMILY, 9, "bold"), padx=14, pady=5,
                  activebackground="#7B5FB4", command=_apply).pack(side="right", padx=(0, 6))

    def _goto_correction_line(self, idx):
        if 0 <= idx < len(self.subtitles):
            self._scroll_to_row(idx)
            self._select_row(idx, seek=False)

    def _apply_corrections(self, suggestions):
        """제안을 적용하고 바뀐 자막 수를 반환. 한 번의 실행 취소로 되돌릴 수 있다."""
        texts = [s.get("text", "") for s in self.subtitles]
        fixed = correction.apply(texts, suggestions)
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
