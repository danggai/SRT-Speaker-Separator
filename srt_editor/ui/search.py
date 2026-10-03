"""자막 검색 막대 (Ctrl+F)."""
import tkinter as tk

from .. import theme
from ..theme import ACCENT, BG2, BG3, BORDER, FG, FG_DIM
from ..widgets import Tooltip, flat_button


class SearchMixin:
    """자막 목록 위 검색 막대."""

    def _build_search_bar(self, parent, before):
        bar = tk.Frame(parent, bg=BG2)
        self._search_bar, self._search_before = bar, before
        self._search_var = tk.StringVar()
        self._search_hits = []
        self._search_pos = -1

        tk.Label(bar, text="⌕", bg=BG2, fg=FG_DIM,
                 font=(theme.FONT_FAMILY, 11)).pack(side="left", padx=(12, 4), pady=6)
        ent = tk.Entry(bar, textvariable=self._search_var, bg=BG3, fg=FG, insertbackground=FG,
                       relief="flat", highlightthickness=1, highlightbackground=BORDER,
                       highlightcolor=ACCENT, font=(theme.FONT_FAMILY, 10), width=28)
        ent.pack(side="left", ipady=3, pady=6)
        self._search_entry = ent
        self._search_count = tk.Label(bar, text="", bg=BG2, fg=FG_DIM,
                                      font=(theme.FONT_FAMILY, 9), width=9, anchor="w")
        self._search_count.pack(side="left", padx=(8, 0))
        for text, cmd, tip in (("↑", lambda: self._search_step(-1), "이전  [Shift+Enter]"),
                               ("↓", lambda: self._search_step(1), "다음  [Enter]")):
            b = flat_button(bar, text, cmd, bg=BG2, padx=8, pady=2)
            b.pack(side="left", padx=1)
            Tooltip(b, tip, delay=400)
        close = flat_button(bar, "✕", self._close_search, bg=BG2, padx=8, pady=2)
        close.pack(side="right", padx=8)
        Tooltip(close, "닫기  [Esc]", delay=400)

        self._search_var.trace_add("write", lambda *_: self._search_update())
        ent.bind("<Return>", lambda e: (self._search_step(1), "break")[1])
        ent.bind("<KP_Enter>", lambda e: (self._search_step(1), "break")[1])
        ent.bind("<Shift-Return>", lambda e: (self._search_step(-1), "break")[1])
        ent.bind("<Escape>", lambda e: (self._close_search(), "break")[1])

    def _open_search(self, event=None):
        if not self._search_bar.winfo_ismapped():
            self._search_bar.pack(fill="x", before=self._search_before)
        self._search_entry.focus_set()
        self._search_entry.select_range(0, "end")
        self._search_update()
        return "break"

    def _close_search(self):
        self._search_bar.pack_forget()
        self.focus_set()

    def _search_update(self):
        """검색어가 바뀌면 일치하는 자막을 다시 찾고 선택 줄 이후 첫 일치로 이동."""
        q = self._search_var.get().strip().lower()
        if not q:
            self._search_hits, self._search_pos = [], -1
            self._search_count.configure(text="", fg=FG_DIM)
            return
        self._search_hits = [i for i, s in enumerate(self.subtitles)
                             if q in s.get("text", "").lower() or q in s.get("speaker", "").lower()]
        if not self._search_hits:
            self._search_pos = -1
            self._search_count.configure(text="없음", fg="#FF6B8A")
            return
        cur = getattr(self, "_selected_row_idx", None) or 0
        self._search_pos = next((k for k, i in enumerate(self._search_hits) if i >= cur), 0)
        self._search_go()

    def _search_step(self, d):
        if not self._search_hits:
            self._search_update()
            if not self._search_hits:
                return
        self._search_pos = (self._search_pos + d) % len(self._search_hits)
        self._search_go()

    def _search_go(self):
        idx = self._search_hits[self._search_pos]
        self._search_count.configure(text=f"{self._search_pos + 1} / {len(self._search_hits)}",
                                     fg=FG_DIM)
        self._scroll_to_row(idx)
        self._select_row(idx, defer_seek=True)
