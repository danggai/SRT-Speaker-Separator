"""화자 사이드바, 화자 색상, 화자 추가/이름 변경/삭제."""
import tkinter as tk
from .. import dialogs as messagebox
from tkinter import simpledialog
from tkinter import ttk

from .. import theme
from ..config import _load_config, _save_config
from ..theme import BG2, BG3, FG, FG_DIM, FG_FAINT, FG_HINT, SPEAKER_COLORS, is_hex_color

_ROW_BG    = BG2         # 화자 줄 배경
_ROW_HOVER = "#26262E"   # 마우스를 올렸을 때
_KEY_BG    = "#2C2C36"   # 단축키 키캡 배경
_KEY_FG    = "#C9C9D4"   # 단축키 숫자
from ..widgets import (DarkScrollbar, PopupMenu, Tooltip, _ColorPickerDialog, _circle_image,
                       rounded_rect_image, show_toast)


class SpeakerMixin:
    """화자 사이드바, 화자 색상, 화자 추가/이름 변경/삭제."""

        # ── 사이드바 (화자 관리) ──────────────────
    def _build_sidebar(self, parent):
        side = ttk.Frame(parent, style="Side.TFrame", width=220)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        self._side_panel = side

        # SPEAKERS 헤더 + 우측 + 버튼
        _hdr_row = tk.Frame(side, bg=BG2)
        _hdr_row.pack(fill="x", padx=(14, 8), pady=(16, 6))
        ttk.Label(_hdr_row, text="화자", style="Header.TLabel",
                  background=BG2).pack(side="left")
        self._spk_total_lbl = tk.Label(_hdr_row, text="", bg=BG2, fg=FG_HINT,
                                       font=(theme.FONT_FAMILY, 9))
        self._spk_total_lbl.pack(side="left", padx=(6, 0))

        list_frame = tk.Frame(side, bg=BG2)
        list_frame.pack(fill="both", expand=True, padx=6)

        canvas = tk.Canvas(list_frame, bg=BG2, highlightthickness=0, bd=0)
        scrollbar = DarkScrollbar(list_frame, command=canvas.yview)
        self.speaker_inner = tk.Frame(canvas, bg=BG2)
        self.speaker_inner.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        _spk_win = canvas.create_window((0, 0), window=self.speaker_inner, anchor="nw")
        self._spk_canvas = canvas   # 화자 목록을 통째로 교체할 때 사용
        self._spk_win = _spk_win
        canvas.configure(yscrollcommand=scrollbar.set)
        # speaker_inner 너비를 canvas 너비에 고정 — 내용물이 사이드바를 밀어내지 않도록
        canvas.bind("<Configure>",
            lambda e, w=_spk_win: canvas.itemconfigure(w, width=e.width))
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    # ── 자막 행 렌더 ────────────────────────

    # ── 화자 색상 헬퍼 ───────────────────────
    def _ensure_global_speaker_colors(self):
        """전역(로컬 스토리지) 화자 색상 맵을 지연 초기화해서 반환.
        __init__ 경로(DnD 서브클래스 등)에 따라 아직 로드되지 않았을 수
        있으므로, 여기서 최초 접근 시 config에서 안전하게 불러온다."""
        if not hasattr(self, "_global_speaker_colors"):
            try:
                self._global_speaker_colors = dict(_load_config().get("speaker_colors", {}))
            except Exception:
                self._global_speaker_colors = {}
        return self._global_speaker_colors

    def _speaker_color(self, name):
        """화자 색상 결정 우선순위: 1) 현재 파일(세션)에 지정된 색상
        2) 로컬 스토리지(다른 파일에서도 이 이름으로 지정했던 색상)
        3) 자동 배정 팔레트."""
        if name in self.speaker_colors:
            return self.speaker_colors[name]
        gsc = self._ensure_global_speaker_colors()
        if name in gsc:
            return gsc[name]
        return self._auto_speaker_colors().get(name, SPEAKER_COLORS[0])

    def _auto_speaker_colors(self):
        """색이 지정되지 않은 화자에게 다른 화자와 겹치지 않는 프리셋 색을 순서대로 배정."""
        gsc = self._ensure_global_speaker_colors()
        fixed = {n: (self.speaker_colors.get(n) or gsc.get(n)) for n in self.speakers}
        key = (tuple(self.speakers), tuple(fixed.values()))
        cache = getattr(self, "_auto_color_cache", None)
        if cache and cache[0] == key:
            return cache[1]
        kept = getattr(self, "_auto_kept", {})   # 이름 → 이미 받은 자동 색 (순서가 바뀌어도 유지)
        fixed_used = {c.upper() for c in fixed.values() if c}
        # 받은 색은 지정색과 겹치지 않는 한 유지 (프리셋이 모자라 겹쳐 받은 화자도 그대로)
        result = {n: kept[n] for n in self.speakers
                  if not fixed[n] and kept.get(n) and kept[n].upper() not in fixed_used}
        used = fixed_used | {c.upper() for c in result.values()}
        free = [c for c in SPEAKER_COLORS if c.upper() not in used]
        k = 0
        for n in self.speakers:
            if fixed[n] or n in result:
                continue
            if free:
                result[n] = free.pop(0)
            else:   # 프리셋을 다 쓰면 순환
                result[n] = SPEAKER_COLORS[k % len(SPEAKER_COLORS)]
                k += 1
        self._auto_kept = dict(result)
        self._auto_color_cache = (key, result)
        return result

    def _auto_color_meta(self):
        """저장용: 색을 따로 지정하지 않은 화자의 자동 배정 색 (다시 열어도 같은 색)."""
        auto = self._auto_speaker_colors()
        return {n: auto[n] for n in self.speakers if n in auto}

    @staticmethod
    def _valid_color_map(saved):
        """파일에서 읽은 {화자: '#RRGGBB'} 중 형식이 맞는 것만."""
        if not isinstance(saved, dict):
            return {}
        return {n: c for n, c in saved.items() if isinstance(n, str) and is_hex_color(c)}

    def _restore_speaker_colors(self, saved):
        """파일에서 읽은 화자 색 복원 (잘못된 값은 무시)."""
        self.speaker_colors = self._valid_color_map(saved)
        self._auto_color_cache = None

    def _restore_auto_colors(self, saved):
        """파일에서 읽은 자동 배정 색 복원 (잘못된 값은 무시)."""
        self._auto_kept = self._valid_color_map(saved)
        self._auto_color_cache = None

    def _save_global_speaker_color(self, name, color):
        """화자 색상을 로컬 스토리지(config)에도 저장 — 다른 자막 파일을
        열었을 때도 같은 이름의 화자면 이 색상이 기본으로 쓰이도록 한다."""
        gsc = self._ensure_global_speaker_colors()
        gsc[name] = color
        cfg = _load_config()
        cfg_colors = dict(cfg.get("speaker_colors", {}))
        cfg_colors[name] = color
        cfg["speaker_colors"] = cfg_colors
        _save_config(cfg)

    # ── 커스텀 컬러피커 ──────────────────────
    def _pick_speaker_color(self, name, dot_canvas, row_frame):
        current_color = self._speaker_color(name)
        result = _ColorPickerDialog(self, current_color, title=f"{name} 색상 선택").show()
        if result and result != current_color:
            self.speaker_colors.setdefault(name, current_color)   # 실행 취소하면 이 색으로 돌아오도록 먼저 기록
            self._push_undo()
            self.speaker_colors[name] = result   # 1순위: 현재 파일에 반영
            self._save_global_speaker_color(name, result)  # 2순위: 로컬 스토리지에도 반영
            self._unsaved = True
            self._render_speakers()
            self._fill_slots(self._vscroll_top)
            # 재생바(타임라인)의 자막 색상도 즉시 반영. cache_key는 화자
            # "이름"·타임스탬프만 보고 실제 색상 매핑까지는 보지 않으므로,
            # 색만 바뀐 경우엔 명시적으로 캐시를 지워줘야 한다.
            self._wf_img_cache = None
            self._pb_redraw()

    # ── 화자 사이드바 렌더 ───────────────────
    def _refresh_speaker_counts(self):
        """화자별 자막 수만 갱신 (목록은 그대로)."""
        total = getattr(self, "_spk_total_lbl", None)
        if total is not None:
            total.configure(text=str(len(self.speakers)) if self.speakers else "")
        lbls = getattr(self, "_spk_count_lbls", {})
        if list(lbls) != list(self.speakers) or not all(l.winfo_exists() for l in lbls.values()):
            self._render_speakers()
            return
        counts = {}
        for s in self.subtitles:
            counts[s["speaker"]] = counts.get(s["speaker"], 0) + 1
        for name, lbl in lbls.items():
            text = str(counts.get(name, 0))
            if lbl.cget("text") != text:
                lbl.configure(text=text)

    def _render_speakers(self):
        """화자 목록 갱신: 바뀐 줄만 다시 만들고, 그대로면 개수만 갱신."""
        if self._update_speaker_rows():
            return
        canvas = getattr(self, "_spk_canvas", None)
        if canvas is None:
            for w in self.speaker_inner.winfo_children():
                w.destroy()
            self._render_speakers_body()
            return
        old = self.speaker_inner
        new = tk.Frame(canvas, bg=BG2)
        self.speaker_inner = new
        try:
            self._render_speakers_body()
        finally:
            new.bind("<Configure>",
                     lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
            canvas.itemconfigure(self._spk_win, window=new)
            old.destroy()

    def _make_speaker_row(self, i, name, before=None):
        """화자 목록의 한 줄(색 점·이름·개수)을 만든다. before를 주면 그 위젯 위에 넣는다."""
        color = self._speaker_color(name)

        row = tk.Frame(self.speaker_inner, bg=_ROW_BG)
        row._spk_name = name
        row._spk_idx  = i
        # 마우스를 올렸을 때 보이는 둥근 배경 (맨 아래 깔림)
        hl = tk.Label(row, bg=_ROW_BG, bd=0, highlightthickness=0)
        hl.place(x=0, y=0, relwidth=1, relheight=1)

        bar = tk.Frame(row, bg=color, width=3)   # 색 표시 (배치하지 않음)

        # 드래그 핸들 — 마우스를 올렸을 때만 보임
        drag_lbl = tk.Label(row, text="⠿", bg=_ROW_BG, fg=_ROW_BG,
                            font=(theme.FONT_FAMILY, 10), cursor="fleur")
        drag_lbl.pack(side="left", padx=(4, 0))

        dot_c = tk.Canvas(row, width=14, height=14, bg=_ROW_BG,
                          highlightthickness=0, cursor="hand2")
        dot_c.pack(side="left", padx=(2, 6), pady=10)
        dot_c.create_image(2, 2, anchor="nw", image=_circle_image(10, color), tags="dot")
        # 줄은 이름·색이 바뀌어도 재사용되므로, 이벤트에서는 항상 row._spk_name을 읽는다
        def _dot_click(e, dc=dot_c, rf=row):
            self._pick_speaker_color(rf._spk_name, dc, rf)
            return "break"
        dot_c.bind("<Button-1>", _dot_click)

        name_var = tk.StringVar(value=name)

        # 단축키 배지·카운트를 right로 먼저 배치 → name_frame이 남은 공간만 차지
        badge = tk.Canvas(row, width=20, height=20, bg=_ROW_BG, highlightthickness=0,
                          cursor="hand2")
        badge.create_image(0, 0, anchor="nw", image=rounded_rect_image(20, 20, 5, _KEY_BG))
        badge.create_text(10, 10, text=str(i + 1) if i < 9 else "", fill=_KEY_FG,
                          font=(theme.FONT_FAMILY, 9, "bold"), tags="key")
        badge.pack(side="right", padx=(6, 8))
        if i >= 9:
            badge.pack_forget()
        cnt = sum(1 for s in self.subtitles if s["speaker"] == name)
        cnt_lbl = tk.Label(row, text=str(cnt), bg=_ROW_BG, fg=FG_DIM,
                 font=(theme.FONT_FAMILY, 9))
        cnt_lbl.pack(side="right", padx=2)
        self._spk_count_lbls[name] = cnt_lbl
        row._cnt_lbl = cnt_lbl
        row._spk_color = color

        # name_frame: 버튼들 배치 후 마지막에 pack → 남은 공간만 차지
        name_frame = tk.Frame(row, bg=_ROW_BG)
        name_frame.pack(side="left", fill="x", expand=True, padx=2)

        # Canvas 기반 말줄임 Label — 실제 너비에 맞게 텍스트를 잘라 표시
        name_canvas = tk.Canvas(name_frame, bg=_ROW_BG, highlightthickness=0,
                                height=22, cursor="xterm")
        name_canvas.pack(fill="x", expand=True)
        _name_text_id = name_canvas.create_text(
            2, 11, text=name, fill=FG,
            font=(theme.FONT_FAMILY, 10), anchor="w")

        def _trim_name(canvas=name_canvas, text_id=_name_text_id, r=row):
            """캔버스 너비에 맞게 이름을 잘라 … 로 표시 (파괴된 뒤 늦게 온 이벤트는 무시)."""
            try:
                if not canvas.winfo_exists():
                    return
                w = canvas.winfo_width()
            except Exception:
                return
            full = r._spk_name
            if w <= 4:
                return
            avail = max(10, w - 8)
            try:
                import tkinter.font as tkfont
                f = tkfont.Font(font=(theme.FONT_FAMILY, 10))
                if f.measure(full) <= avail:
                    canvas.itemconfigure(text_id, text=full)
                    return
                lo, hi = 0, len(full)
                while lo < hi:
                    mid = (lo + hi + 1) // 2
                    if f.measure(full[:mid] + "…") <= avail:
                        lo = mid
                    else:
                        hi = mid - 1
                canvas.itemconfigure(text_id, text=full[:lo] + "…" if lo < len(full) else full)
            except Exception:
                try:
                    canvas.itemconfigure(text_id, text=full)
                except Exception:
                    pass

        name_canvas.bind("<Configure>", lambda e, fn=_trim_name: fn())

        entry = tk.Entry(name_frame, textvariable=name_var,
                         bg=BG2, fg=FG, insertbackground=FG,
                         font=(theme.FONT_FAMILY, 10, "bold"), relief="flat",
                         highlightthickness=1, highlightbackground=color,
                         highlightcolor=color)

        row._name_canvas = name_canvas
        row._name_entry = entry
        row._name_var = name_var
        row._name_trim = _trim_name

        def _on_entry_key(e, r=row):
            if e.keysym == "Return":
                self._end_name_edit(commit=True)
                return "break"
            if e.keysym == "Escape":
                self._end_name_edit(commit=False)
                return "break"

        # "break": 전역 클릭 처리가 방금 준 포커스를 뺏지 않도록
        name_canvas.bind("<Button-1>", lambda e, r=row: self._begin_name_edit(r))
        entry.bind("<FocusOut>",
                   lambda e, r=row: self._end_name_edit(commit=True)
                   if getattr(self, "_spk_edit_row", None) is r else None)
        entry.bind("<KeyPress>", _on_entry_key)

        for widget in [row, hl, cnt_lbl, badge]:
            widget.bind("<Button-1>",
                lambda e, r=row: self._assign_speaker_from_sidebar(r._spk_name))

        # 드래그 바인딩 (핸들에만)
        drag_lbl.bind("<ButtonPress-1>",   lambda e, r=row: self._spk_drag_start(e, r))
        drag_lbl.bind("<B1-Motion>",        self._spk_drag_motion)
        drag_lbl.bind("<ButtonRelease-1>", self._spk_drag_end)

        # 우클릭 메뉴 (이름 변경·색상 변경·삭제)
        for widget in (row, hl, drag_lbl, badge, dot_c, name_canvas, cnt_lbl):
            widget.bind("<Button-3>", lambda e, r=row: self._speaker_menu(e, r))

        Tooltip(drag_lbl, "위아래로 드래그해 화자 순서 변경", delay=400)
        row._tips = (Tooltip(row, "", delay=600), Tooltip(dot_c, "", delay=400))
        row._badge, row._dot, row._name_text_id = badge, dot_c, _name_text_id
        row._bar, row._drag = bar, drag_lbl
        self._set_speaker_tips(row)

        # 마우스를 올리면 줄을 밝게 하고 드래그 핸들 표시
        hover_parts = (drag_lbl, dot_c, name_frame, name_canvas, cnt_lbl, badge)

        def _hover(on, r=row):
            bg = _ROW_HOVER if on else _ROW_BG
            for w in hover_parts:
                w.configure(bg=bg)
            drag_lbl.configure(fg=FG_DIM if on else bg)
            w, h = r.winfo_width(), r.winfo_height()
            hl.configure(image=rounded_rect_image(w, h, 6, _ROW_HOVER) if on and w > 12 else "")

        def _leave(e, r=row):
            x, y = r.winfo_pointerxy()
            w = r.winfo_containing(x, y)
            if w is None or not str(w).startswith(str(r)):
                _hover(False)
        for w in hover_parts + (row, hl, bar):
            w.bind("<Enter>", lambda e: _hover(True), add="+")
            w.bind("<Leave>", _leave, add="+")
        # 내용을 다 채운 뒤에 한 번에 보이게 한다 (만드는 도중 흰 바탕이 번쩍이지 않도록)
        row.pack(fill="x", padx=6, pady=0,
                 **({"before": before} if before is not None else {}))
        return row

    def _append_speaker_row(self, name):
        """새 화자 한 줄만 추가 (불가능하면 전체 다시 그림)."""
        add_row = getattr(self, "_spk_add_row", None)
        lbls = getattr(self, "_spk_count_lbls", {})
        if (add_row is None or not add_row.winfo_exists()
                or list(lbls) != self.speakers[:-1] or self.speakers[-1] != name):
            self._render_speakers()
            return
        self._make_speaker_row(len(self.speakers) - 1, name, before=add_row)
        self._refresh_speaker_counts()

    def _set_speaker_tips(self, row):
        name, i = row._spk_name, row._spk_idx
        key_hint = f"  단축키: {i+1}" if i < 9 else ""
        tip_row, tip_dot = row._tips
        tip_row._text = f"클릭 → 선택된 자막에 '{name}' 지정{key_hint}\n우클릭 → 이름·색상 변경, 삭제"
        tip_dot._text = f"클릭 → '{name}' 색상 변경"

    def _speaker_menu(self, event, row):
        """화자 줄 우클릭 메뉴."""
        name = row._spk_name
        menu = PopupMenu(self)
        menu.add_command(label="이름 변경", command=lambda: self._begin_name_edit(row),
                         accelerator="F2")
        menu.add_command(label="색상 변경",
                         command=lambda: self._pick_speaker_color(name, row._dot, row))
        menu.add_separator()
        menu.add_command(label=f"'{name}' 삭제", foreground="#FF6B8A",
                         command=lambda: self.delete_speaker(name), accelerator="Delete")
        menu.tk_popup(event.x_root, event.y_root)
        return "break"

    def _restyle_speaker_row(self, row, i, name):
        """기존 줄을 i번째 화자(name)로 바꾼다 — 줄을 새로 만들지 않아 깜빡이지 않음."""
        color = self._speaker_color(name)
        if (row._spk_name, row._spk_idx, row._spk_color) == (name, i, color):
            return
        renamed = row._spk_name != name
        row._spk_name, row._spk_idx, row._spk_color = name, i, color
        row._bar.configure(bg=color)
        row._badge.itemconfigure("key", text=str(i + 1) if i < 9 else "")
        if i < 9:
            row._badge.pack(side="right", padx=(6, 8), before=row._cnt_lbl)
        else:
            row._badge.pack_forget()
        row._dot.itemconfigure("dot", image=_circle_image(10, color))
        row._name_entry.configure(highlightbackground=color, highlightcolor=color)
        row._name_var.set(name)
        if renamed:
            row._name_trim()
        self._set_speaker_tips(row)

    def _update_speaker_rows(self):
        """i번째 줄을 i번째 화자로 맞춰 재사용하고, 모자라거나 남는 줄만 끝에서 추가·삭제.
        처리하지 못하면 False (전체 다시 그리기)."""
        add_row = getattr(self, "_spk_add_row", None)
        rows = [w for w in self.speaker_inner.pack_slaves() if hasattr(w, "_spk_name")]
        if not self.speakers or not rows or add_row is None or not add_row.winfo_exists():
            return False
        for r in rows[len(self.speakers):]:
            r.destroy()
        rows = rows[:len(self.speakers)]
        for i, name in enumerate(self.speakers):
            if i < len(rows):
                self._restyle_speaker_row(rows[i], i, name)
            else:
                rows.append(self._make_speaker_row(i, name, before=add_row))
        self._spk_count_lbls = {n: r._cnt_lbl for n, r in zip(self.speakers, rows)}
        edit = getattr(self, "_spk_edit_row", None)
        if edit is not None and not edit.winfo_exists():
            self._spk_edit_row = None
        self._refresh_speaker_counts()
        return True

    def _render_speakers_body(self):
        self._spk_count_lbls = {}
        self._spk_edit_row = None

        total = getattr(self, "_spk_total_lbl", None)
        if total is not None:
            total.configure(text=str(len(self.speakers)) if self.speakers else "")

        if not self.speakers:
            tk.Label(self.speaker_inner, text="화자가 없습니다",
                     bg=BG2, fg=FG_DIM,
                     font=(theme.FONT_FAMILY, 9)).pack(padx=10, pady=(6, 4))
            self._make_add_row()
            return

        # 드래그 상태
        self._spk_drag_src = None
        self._spk_drag_ghost = None

        for i, name in enumerate(self.speakers):
            self._make_speaker_row(i, name)

        # 목록 마지막에 '+ 화자 추가'
        self._spk_add_row = self._make_add_row()

    def _make_add_row(self):
        """'+ 화자 추가' 줄과 그 아래 단축키 안내."""
        add_row = tk.Frame(self.speaker_inner, bg=BG2)
        add_row.pack(fill="x", padx=6, pady=(4, 6))
        btn = tk.Label(add_row, text="＋  화자 추가", bg=BG2, fg=FG_DIM, cursor="hand2",
                       font=(theme.FONT_FAMILY, 9), anchor="w", padx=10, pady=6)
        btn.pack(fill="x")
        btn.bind("<Enter>", lambda e: btn.configure(bg=_ROW_HOVER, fg=FG))
        btn.bind("<Leave>", lambda e: btn.configure(bg=BG2, fg=FG_DIM))
        btn.bind("<ButtonRelease-1>", lambda e: self.add_speaker())
        tk.Label(add_row, text="숫자 키로 지정  ·  ` 키로 해제", bg=BG2, fg=FG_FAINT,
                 font=(theme.FONT_FAMILY, 8), anchor="w").pack(fill="x", padx=10, pady=(2, 0))
        return add_row

    # ── 화자 드래그 순서 변경 ─────────────────
    def _spk_drag_start(self, event, row):
        self._spk_drag_src = row._spk_idx
        self._spk_drag_y0  = event.y_root
        # 고스트: 반투명 Toplevel
        g = tk.Toplevel(self)
        g.overrideredirect(True)
        g.geometry(f"+{event.x_root+10}+{event.y_root+10}")   # 보이기 전에 위치부터 (떴다가 이동 방지)
        g.attributes("-alpha", 0.7)
        g.attributes("-topmost", True)
        lbl = tk.Label(g, text=row._spk_name, bg=BG3,
                       fg=self._speaker_color(row._spk_name),
                       font=(theme.FONT_FAMILY, 10, "bold"), padx=12, pady=4,
                       relief="solid", bd=1)
        lbl.pack()
        self._spk_drag_ghost = g

    def _spk_drag_motion(self, event):
        if self._spk_drag_ghost:
            self._spk_drag_ghost.geometry(
                f"+{event.x_root+10}+{event.y_root+10}")

    def _spk_drag_end(self, event):
        if self._spk_drag_ghost:
            self._spk_drag_ghost.destroy()
            self._spk_drag_ghost = None
        if self._spk_drag_src is None:
            return

        # 드롭 위치: speaker_inner 내부 row들 중 y_root와 가장 가까운 것
        src = self._spk_drag_src
        dst = src
        best = float("inf")
        for child in self.speaker_inner.winfo_children():
            if not hasattr(child, "_spk_idx"):
                continue
            cy = child.winfo_rooty() + child.winfo_height() // 2
            dist = abs(event.y_root - cy)
            if dist < best:
                best = dist
                dst = child._spk_idx

        self._spk_drag_src = None
        if src == dst:
            return

        # 순서 변경
        self._push_undo()
        spk = self.speakers.pop(src)
        self.speakers.insert(dst, spk)
        self._unsaved = True
        self._render_speakers()
        self._fill_slots(self._vscroll_top)

    def _on_speaker_key(self, event):
        """화자 지정 단축키: ` → (없음), 1~9 → 해당 번호 화자. 선택한 줄에 적용."""
        if isinstance(self.focus_get(), tk.Entry):
            return
        key = event.keysym
        if key == "grave":
            val = ""
        elif key.isdigit() and key != "0":
            spk_idx = int(key) - 1
            if spk_idx >= len(self.speakers):
                return
            val = self.speakers[spk_idx]
        else:
            return
        sel = getattr(self, "_selected_rows", set())
        cur = getattr(self, "_selected_row_idx", None)
        reviewing = len(sel) <= 1 and cur is not None and cur < len(self.subtitles) \
            and self.subtitles[cur].get("_check") and self._opt("advance_to_check")
        if self._assign_speaker_to_selection(val, advance=not reviewing):
            if reviewing:   # ? 줄을 정했으면 다음 ? 줄로 (재생 중일 때만 이어서 재생)
                self._review_next_check(play=self.player.is_playing)
            return "break"

    def _review_next_check(self, event=None, play=True):
        """F: 다음 확인 필요(?) 줄로 가서 그 줄만 재생. play=False면 이동만."""
        if isinstance(self.focus_get(), tk.Entry):
            return
        if not any(s.get("_check") for s in self.subtitles):
            if event is not None:
                show_toast(self, "확인 필요한 줄이 없어요")
            return "break"
        self._goto_next_check()
        idx = getattr(self, "_selected_row_idx", None)
        if play and idx is not None:
            self._play_line(idx)
        return "break"

    def _assign_speaker_to_selection(self, val, advance=False):
        """선택한 줄(없으면 마지막으로 누른 줄)에 화자 지정. 지정했으면 True.
        advance: 옵션이 켜져 있고 한 줄만 지정했으면 다음 줄로 넘어감."""
        selected = getattr(self, "_selected_rows", set())
        focused = getattr(self, "_last_focused_idx", None)
        if selected:
            targets = sorted(i for i in selected if i < len(self.subtitles))
        elif focused is not None and focused < len(self.subtitles):
            targets = [focused]
        else:
            targets = []
        if not targets:
            return False
        self._push_undo()
        for idx in targets:
            self._set_line_speaker(idx, val)
            self._refresh_row(idx)
        self._unsaved = True
        self._refresh_speaker_counts()
        self._update_check_count()
        self._wf_img_cache = None
        self._pb_redraw()   # 타임라인에도 바로 반영
        if advance and self._opt("advance_after_assign") and len(targets) == 1 \
                and targets[0] + 1 < len(self.subtitles):
            nxt = targets[0] + 1
            self._select_row(nxt)
            self._scroll_to_row(nxt)
        return True

    def _set_line_speaker(self, idx, val):
        """사용자가 직접 화자를 정함 → 분석이 붙인 '자동·확인 필요' 표시를 지움."""
        sub = self.subtitles[idx]
        sub["speaker"] = val
        for k in ("_auto", "_conf", "_check"):
            sub.pop(k, None)

    def _assign_speaker_from_sidebar(self, name):
        self._assign_speaker_to_selection(name)

    def add_speaker(self):
        # 고유 기본 이름 생성 (새화자1, 새화자2 ...)
        i = 1
        while f"새화자{i}" in self.speakers:
            i += 1
        name = f"새화자{i}"
        self._push_undo()
        self.speakers.append(name)
        self._auto_resize_speaker_col()
        self._fill_slots(self._vscroll_top)
        self._append_speaker_row(name)
        self._update_count()
        # 배치 즉시 반영 (깜빡임 방지)
        self.update_idletasks()
        # 추가된 화자의 entry를 바로 편집 모드로
        self.after(50, lambda: self._start_speaker_edit(name))

    def _start_speaker_edit(self, name):
        """화자 이름 편집 시작 (화자 추가 직후)."""
        row = next((r for r in self.speaker_inner.winfo_children()
                    if getattr(r, "_spk_name", None) == name), None)
        if row is not None:
            self._begin_name_edit(row)

    def _begin_name_edit(self, row):
        """화자 이름 편집 시작. 다른 화자를 편집 중이면 먼저 저장하고 닫는다."""
        cur = getattr(self, "_spk_edit_row", None)
        if cur is row:
            return "break"
        name = row._spk_name
        if cur is not None:
            self._end_name_edit(commit=True)
            if not row.winfo_exists():   # 이름 변경으로 목록이 다시 그려진 경우
                row = next((r for r in self.speaker_inner.winfo_children()
                            if getattr(r, "_spk_name", None) == name), None)
                if row is None:
                    return "break"
        self._spk_edit_row = row
        row._name_canvas.pack_forget()
        row._name_var.set(name)
        row._name_entry.pack(fill="x", expand=True, ipady=2)
        row._name_entry.focus_set()
        row._name_entry.select_range(0, "end")
        row._name_entry.icursor("end")
        return "break"

    def _end_name_edit(self, commit=True):
        """화자 이름 편집 종료 (여러 번 불려도 한 번만 처리)."""
        row = getattr(self, "_spk_edit_row", None)
        self._spk_edit_row = None
        if row is None or not row.winfo_exists():
            return
        old, new = row._spk_name, row._name_var.get().strip()
        if self.focus_get() is row._name_entry:
            self.focus_set()
        row._name_entry.pack_forget()
        row._name_var.set(old)
        row._name_canvas.pack(fill="x", expand=True)
        self.after(10, row._name_trim)
        if commit and new and new != old and new not in self.speakers:
            self.rename_speaker(old, new)

    def rename_speaker(self, old_name, new_name=None):
        if new_name is None:
            # 팝업 방식 (직접 호출 시 fallback)
            new_name = simpledialog.askstring(
                "화자 이름 변경", f"'{old_name}'의 새 이름:",
                initialvalue=old_name, parent=self)
        if not new_name or not new_name.strip():
            return
        new_name = new_name.strip()
        if new_name == old_name:
            return   # 바뀐 게 없으면 실행 취소 기록도 남기지 않음
        if new_name in self.speakers:
            messagebox.showwarning("화자 이름", f"'{new_name}' 화자가 이미 있어요.", parent=self)
            return
        self._push_undo()
        idx = self.speakers.index(old_name)
        self.speakers[idx] = new_name
        # 커스텀 색상 매핑 이전
        if old_name in self.speaker_colors:
            self.speaker_colors[new_name] = self.speaker_colors.pop(old_name)
        kept = getattr(self, "_auto_kept", {})
        if old_name in kept:
            kept[new_name] = kept.pop(old_name)
        for sub in self.subtitles:
            if sub["speaker"] == old_name:
                sub["speaker"] = new_name
        self._fill_slots(self._vscroll_top)
        self._render_speakers()
        self._update_count()
        self._wf_img_cache = None
        self._pb_redraw()

    def delete_speaker(self, name):
        if not messagebox.askyesno("화자 삭제", f"'{name}' 화자를 지울까요?\n이 화자로 지정된 줄은 비워져요.", parent=self, yes="삭제", no="취소"):
            return
        self._push_undo()
        self.speakers.remove(name)
        self.speaker_colors.pop(name, None)   # 커스텀 색상 제거
        for i, sub in enumerate(self.subtitles):
            if sub["speaker"] == name:
                self._set_line_speaker(i, "")
        self._auto_resize_speaker_col()
        self._fill_slots(self._vscroll_top)
        self._render_speakers()
        self._wf_img_cache = None
        self._pb_redraw()
        self._update_count()
