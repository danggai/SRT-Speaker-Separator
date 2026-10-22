"""이름 검수 창: 비슷하게 인식된 이름 묶음마다 맞는 표기를 골라 한 번에 바꿈."""
import tkinter as tk
from .. import dialogs as messagebox

from .. import name_review, theme
from ..theme import ACCENT, BG, BG2, BG3, BORDER, FG, FG_DIM, FG_HINT, _apply_dark_titlebar
from ..widgets import CheckBox, flat_button

_CHIP_ON = "#3A3150"


class NameReviewMixin:
    """이름 검수 창."""

    def _name_groups(self):
        self._ensure_proper_nouns_init()
        return name_review.find_groups([s.get("text", "") for s in self.subtitles], self._proper_nouns)

    def _offer_name_review(self):
        """자동 자막 뒤: 비슷한 이름 묶음이 있으면 검수할지 물음."""
        groups = self._name_groups()
        if groups and messagebox.askyesno("이름 검수", f"비슷하게 인식된 이름이 {len(groups)}묶음 있어요. 확인할까요?",
                                          parent=self, yes="확인", no="나중에"):
            self._open_name_review(groups)

    def _open_name_review(self, groups=None):
        if not self.subtitles:
            return
        self._blur_all_entries()
        groups = self._name_groups() if groups is None else groups
        if not groups:
            messagebox.showinfo("이름 검수", "비슷하게 인식된 이름을 찾지 못했어요.", parent=self)
            return
        win = tk.Toplevel(self)
        win.withdraw()
        win.title("이름 검수")
        win.configure(bg=BG)
        win.geometry("700x600")
        win.minsize(540, 380)
        win.transient(self)
        self._name_review_win = win

        head = tk.Frame(win, bg=BG)
        head.pack(fill="x", padx=28, pady=(22, 10))
        tk.Label(head, text=f"이름 검수 {len(groups)}묶음", bg=BG, fg=FG,
                 font=(theme.FONT_FAMILY, 15, "bold")).pack(anchor="w")
        tk.Label(head, text="비슷하게 인식된 이름이에요. 맞는 표기를 고르면 모두 바뀌어요.",
                 bg=BG, fg=FG_DIM, font=(theme.FONT_FAMILY, 9)).pack(anchor="w", pady=(3, 0))

        footer = tk.Frame(win, bg=BG)
        footer.pack(side="bottom", fill="x", padx=28, pady=(8, 16))
        tk.Frame(win, bg=BORDER, height=1).pack(side="bottom", fill="x")
        outer, inner = self._make_scrollable(win)
        outer.pack(fill="both", expand=True, padx=16)

        cards = []   # (group, 고른 표기 StringVar)

        def _build(g):
            choice = tk.StringVar(value=g.default)
            card = tk.Frame(inner, bg=BG2, highlightthickness=1, highlightbackground=BORDER)
            card.pack(fill="x", padx=12, pady=5)
            row = tk.Frame(card, bg=BG2)
            row.pack(fill="x", padx=14, pady=(12, 6))
            chips = {}
            custom = tk.StringVar()
            count_lbl = tk.Label(card, bg=BG2, fg=FG_HINT, font=(theme.FONT_FAMILY, 8))

            def _paint(*_):
                cur = choice.get()
                for key, lbl in chips.items():
                    on = key == cur and not (key == "" and custom.get().strip())
                    lbl.configure(bg=_CHIP_ON if on else BG3, fg="white" if on else FG,
                                  highlightbackground=ACCENT if on else BORDER)
                n = sum(len(g.lines[w]) for w, _ in g.variants if w != cur) if cur else 0
                count_lbl.configure(text=f"바꾸면 {n}줄" if cur else "그대로 둠")

            def _pick(key, play_line=None):
                custom.set("") if key != custom.get().strip() else None
                choice.set(key)
                _paint()
                if play_line is not None:
                    self._goto_correction_line(play_line)
                    self._play_line(play_line)

            for w, n in g.variants:
                lbl = tk.Label(row, text=f"{w} {n}", bg=BG3, fg=FG, padx=10, pady=3, cursor="hand2",
                               highlightthickness=1, highlightbackground=BORDER, font=(theme.FONT_FAMILY, 10))
                lbl.pack(side="left", padx=(0, 6))
                lbl.bind("<Button-1>", lambda e, w=w: _pick(w, g.lines[w][0]))
                chips[w] = lbl
            ent = tk.Entry(row, textvariable=custom, width=10, bg="#121217", fg=FG, insertbackground=FG,
                           relief="flat", highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT,
                           font=(theme.FONT_FAMILY, 10))
            ent.pack(side="left", padx=(0, 6), ipady=3)
            hint = tk.Label(ent, text="직접 입력", bg="#121217", fg=FG_HINT, font=(theme.FONT_FAMILY, 9))
            hint.place(x=4, rely=0.5, anchor="w")
            hint.bind("<Button-1>", lambda e: ent.focus_set())

            def _typed(*_):
                choice.set(custom.get().strip())
                hint.place_forget() if custom.get() else hint.place(x=4, rely=0.5, anchor="w")
                _paint()
            custom.trace_add("write", _typed)
            keep = tk.Label(row, text="그대로 둠", bg=BG3, fg=FG, padx=10, pady=3, cursor="hand2",
                            highlightthickness=1, highlightbackground=BORDER, font=(theme.FONT_FAMILY, 10))
            keep.pack(side="left")
            keep.bind("<Button-1>", lambda e: _pick(""))
            chips[""] = keep
            ex = [f"{g.lines[w][0] + 1}번 줄  {self.subtitles[g.lines[w][0]].get('text', '')}" for w, _ in g.variants[:2]]
            tk.Label(card, text="   ·   ".join(ex), bg=BG2, fg=FG_DIM, anchor="w", justify="left",
                     font=(theme.FONT_FAMILY, 9)).pack(fill="x", padx=14)
            count_lbl.pack(anchor="w", padx=14, pady=(2, 10))
            _paint()
            cards.append((g, choice))

        for g in groups:
            _build(g)

        to_dict = tk.BooleanVar(value=True)
        CheckBox(footer, to_dict, text="고른 이름을 고유명사 사전에 넣기").pack(side="left")

        def _apply():
            mapping, chosen = {}, []
            for g, choice in cards:
                right = choice.get().strip()
                if not right:
                    continue
                chosen.append(right)
                mapping.update({w: right for w, _ in g.variants if w != right})
            win.destroy()
            if not mapping:
                return
            n = self._apply_name_mapping(mapping)
            if to_dict.get():
                for right in chosen:
                    self._add_proper_noun(right)
            messagebox.showinfo("이름 검수", f"{n}줄을 고쳤어요. (Ctrl+Z로 되돌리기)", parent=self)

        flat_button(footer, "닫기", win.destroy, bg=BG3, hover="#33333C", padx=16, pady=6).pack(side="right")
        flat_button(footer, "고른 대로 바꾸기", _apply, bg=ACCENT, fg="white", hover="#AE96E2",
                    font=(theme.FONT_FAMILY, 9, "bold"), padx=16, pady=6).pack(side="right", padx=(0, 8))

        win.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - win.winfo_reqwidth()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - win.winfo_reqheight()) // 3
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
        win.deiconify()
        _apply_dark_titlebar(win)
        win.grab_set()

    def _apply_name_mapping(self, mapping):
        """이름 바꾸기를 모든 줄에 적용 (실행 취소 한 번). 바뀐 줄 수."""
        texts = [s.get("text", "") for s in self.subtitles]
        fixed = name_review.apply(texts, mapping)
        changed = [i for i, (a, b) in enumerate(zip(texts, fixed)) if a != b]
        if not changed:
            return 0
        self._push_undo()
        self._learn_fixes([(texts[i], fixed[i]) for i in changed])
        for i in changed:
            self.subtitles[i]["text"] = fixed[i]
        self._unsaved = True
        self._fill_slots(self._vscroll_top)
        self._wf_img_cache = None
        self._pb_redraw()
        return len(changed)
