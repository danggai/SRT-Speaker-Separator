"""설정 창과 자동 자막/모델 관리 탭."""
import json
import re
import tkinter as tk
from tkinter import messagebox

from .. import srt_io, theme
from ..config import _load_config, _save_config
from ..srt_io import display_to_regex
from ..theme import ACCENT, BG, BG2, BG3, BORDER, FG, FG_DIM, FG_HINT, FONT_MONO, _apply_dark_titlebar
from ..version import APP_VERSION, fetch_latest_version
from .options import OPTION_DEFAULTS
from ..widgets import (CheckBox, DarkScrollbar, PurpleSlider, Segmented, ToggleSwitch, flat_button,
                       rounded_rect_image)


class SettingsMixin:
    """설정 창과 자동 자막/모델 관리 탭."""

    def _make_scrollable(self, parent, with_footer=False):
        """parent 안에 세로 스크롤 가능한 영역을 만든다.
        with_footer=False (기본): 반환값 (outer, inner)
        with_footer=True:        반환값 (outer, inner, footer)
            footer는 outer 하단에 스크롤과 무관하게 항상 고정되는 프레임.
            (버튼 행처럼 스크롤해도 안 보이면 안 되는 UI에 사용)
        - outer: parent에 pack/nb.add로 배치할 컨테이너
        - inner: 실제 내용물을 채울 프레임 (기존 코드에서 parent로 쓰던 자리)
        내용이 창 높이보다 길어져도 잘리지 않고 스크롤로 볼 수 있게 하되,
        내용이 뷰포트보다 짧으면(스크롤할 필요가 없으면) 휠을 굴려도 위로
        빈 공간이 더 스크롤되지 않도록 막는다."""
        outer = tk.Frame(parent, bg=BG)

        footer = None
        if with_footer:
            footer = tk.Frame(outer, bg=BG)
            footer.pack(side="bottom", fill="x")
            tk.Frame(outer, bg=BORDER, height=1).pack(side="bottom", fill="x")

        canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        vsb = DarkScrollbar(outer, command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        inner = tk.Frame(canvas, bg=BG)
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _sync_scrollregion(_e=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            # 내용(inner의 실제 wrap된 높이)이 뷰포트(캔버스에 남은 실질
            # 영역)보다 작거나 같으면 — 즉 스크롤할 필요가 전혀 없으면 —
            # 스크롤바 자체를 숨기고 뷰를 맨 위로 고정한다. 스크롤이 실제로
            # 필요해지는 순간(내용이 늘어나거나 창이 작아지는 순간)에만
            # 스크롤바가 다시 나타난다.
            bbox = canvas.bbox("all")
            content_h = (bbox[3] - bbox[1]) if bbox else 0
            if content_h <= canvas.winfo_height():
                if vsb.winfo_ismapped():
                    vsb.pack_forget()
                canvas.yview_moveto(0)
            elif not vsb.winfo_ismapped():
                vsb.pack(side="right", fill="y")
        inner.bind("<Configure>", _sync_scrollregion)

        def _sync_width(e):
            canvas.itemconfigure(win_id, width=e.width)
            _sync_scrollregion()
        canvas.bind("<Configure>", _sync_width)

        def _wheel(event):
            # 내용이 캔버스 뷰포트보다 짧으면(스크롤할 필요가 없으면) 휠을
            # 굴려도 아무 것도 하지 않는다 — 빈 공간이 스크롤되어 보이는
            # 문제 방지.
            if not canvas.winfo_exists():   # 창이 닫힌 뒤면 메인 스크롤로 넘김
                _unbind_wheel()
                return self._on_mousewheel(event)
            bbox = canvas.bbox("all")
            content_h = (bbox[3] - bbox[1]) if bbox else 0
            if content_h <= canvas.winfo_height():
                return
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        def _bind_wheel(_e=None):
            canvas.bind_all("<MouseWheel>", _wheel)
        def _unbind_wheel(_e=None):
            # 다이얼로그를 벗어나면 메인 테이블의 원래 휠 스크롤 핸들러로 복원
            self.bind_all("<MouseWheel>", self._on_mousewheel)
        canvas.bind("<Enter>", _bind_wheel)
        canvas.bind("<Leave>", _unbind_wheel)
        inner.bind("<Enter>", _bind_wheel)
        inner.bind("<Leave>", _unbind_wheel)
        canvas.bind("<Destroy>", _unbind_wheel, add="+")

        if with_footer:
            return outer, inner, footer
        return outer, inner

    # ── 설정 창 공용 레이아웃 (카드 묶음형) ────────
    def _settings_title(self, parent, title, desc=None, section=None):
        """섹션 제목 (큼직한 글씨 + 한 줄 설명). section이 있으면 오른쪽에 기본값 버튼."""
        head = tk.Frame(parent, bg=BG)
        head.pack(fill="x", padx=32, pady=(26, 2))
        tk.Label(head, text=title, bg=BG, fg=FG,
                 font=(theme.FONT_FAMILY, 15, "bold")).pack(side="left")
        if section:
            def _reset():
                if not messagebox.askyesno("기본값", f"{title} 설정을 기본값으로 되돌릴까요?",
                                           parent=parent.winfo_toplevel()):
                    return
                self._reset_settings_section(section)
                rebuild = getattr(parent, "_rebuild", None)
                if rebuild:
                    parent.after_idle(rebuild)
            flat_button(head, "기본값", _reset, bg=BG3, hover="#33333C",
                        font=(theme.FONT_FAMILY, 9), padx=12, pady=4).pack(side="right")
        if desc:
            tk.Label(parent, text=desc, bg=BG, fg=FG_DIM, justify="left",
                     font=(theme.FONT_FAMILY, 9)).pack(anchor="w", padx=32)

    def _settings_card(self, parent, label=None):
        """설정 묶음 카드. 카드 Frame 반환 (줄 사이 구분선은 _settings_row가 넣음)."""
        if label:
            tk.Label(parent, text=label, bg=BG, fg="#8A8A96",
                     font=(theme.FONT_FAMILY, 9, "bold")).pack(anchor="w", padx=34, pady=(18, 6))
        else:
            tk.Frame(parent, bg=BG, height=14).pack()
        card = tk.Frame(parent, bg=BG2, highlightthickness=1, highlightbackground=BORDER)
        card.pack(fill="x", padx=32)
        card.rows = 0
        return card

    def _settings_row(self, card, icon, title, desc=None):
        """카드 안 설정 한 줄: 아이콘 | 제목·설명 | 컨트롤. (left, right) 반환."""
        if card.rows:
            tk.Frame(card, bg=BORDER, height=1).pack(fill="x", padx=14)
        card.rows += 1
        row = tk.Frame(card, bg=BG2)
        row.pack(fill="x", padx=14, pady=12)
        badge = tk.Canvas(row, width=30, height=30, bg=BG2, highlightthickness=0)
        badge.pack(side="left", anchor="n", padx=(0, 12))
        badge.create_image(0, 0, anchor="nw", image=rounded_rect_image(30, 30, 8, theme.ON_BG))
        badge.create_text(15, 15, text=icon, fill=theme.ON_FG,
                          font=(theme.FONT_FAMILY, 11, "bold"))
        right = tk.Frame(row, bg=BG2)
        right.pack(side="right", anchor="center")
        left = tk.Frame(row, bg=BG2)
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text=title, bg=BG2, fg=FG,
                 font=(theme.FONT_FAMILY, 10, "bold")).pack(anchor="w")
        if desc:
            d = tk.Label(left, text=desc, bg=BG2, fg=FG_DIM, justify="left", anchor="w",
                         wraplength=320, font=(theme.FONT_FAMILY, 9))
            d.pack(fill="x", pady=(2, 0))
            # 칸 폭에 맞춰 줄바꿈 (긴 설명이 오른쪽으로 넘치지 않게)
            left.bind("<Configure>", lambda e, d=d: d.configure(wraplength=max(120, e.width - 4)),
                      add="+")
        return left, right

    def _opt_toggle(self, right, key, on_change=None):
        var = tk.BooleanVar(value=bool(self._opt(key)))

        def _save():
            self._set_opt(key, bool(var.get()))
            if on_change:
                on_change(bool(var.get()))
        ToggleSwitch(right, var, _save).pack()
        return var

    def _opt_number(self, right, key, unit, lo, hi, is_float=False, label=None):
        """숫자 입력칸 (Enter·포커스 이동 시 저장, 범위 밖이면 맞춤)."""
        box = tk.Frame(right, bg=BG2)
        box.pack(side="left", padx=(8, 0))
        if label:
            tk.Label(box, text=label, bg=BG2, fg=FG_DIM,
                     font=(theme.FONT_FAMILY, 9)).pack(side="left", padx=(0, 4))
        var = tk.StringVar(value=f"{self._opt(key):g}")
        ent = tk.Entry(box, textvariable=var, width=4, bg=BG3, fg=FG, insertbackground=FG,
                       justify="center", relief="flat", highlightthickness=1,
                       highlightbackground=BORDER, highlightcolor=ACCENT,
                       font=(theme.FONT_FAMILY, 10))
        ent.pack(side="left", ipady=3)
        tk.Label(box, text=unit, bg=BG2, fg=FG_DIM,
                 font=(theme.FONT_FAMILY, 9)).pack(side="left", padx=(4, 0))

        def _commit(*_):
            try:
                v = float(var.get())
            except ValueError:
                v = self._opt(key)
            v = max(lo, min(hi, v))
            v = v if is_float else int(round(v))
            var.set(f"{v:g}")
            self._set_opt(key, v)
        ent.bind("<Return>", _commit)
        ent.bind("<FocusOut>", _commit)

    _SECTION_OPTS = {
        "general": ("startup_open_last", "update_check"),
        "edit": ("advance_after_assign", "seek_step", "seek_step_shift", "click_seek",
                 "new_sub_len", "lock_timeline"),
        "storage": ("backup_enabled", "backup_minutes"),
        "export": ("export_dir_mode", "export_dir", "export_subfolder"),
    }

    def _reset_settings_section(self, section):
        """설정 탭 하나를 기본값으로 되돌림."""
        for key in self._SECTION_OPTS.get(section, ()):
            self._set_opt(key, OPTION_DEFAULTS[key])
        cfg = _load_config()
        if section == "general":
            self._apply_key_hints(False)
            cfg["show_key_hints"] = False
        elif section == "transcribe":
            self._transcribe_max_chars = 25
            self._transcribe_language = "ko"
            self._transcribe_period = False
            self._transcribe_spellcheck = False
            cfg.update(transcribe_max_chars=25, transcribe_language="ko",
                       transcribe_period=False, transcribe_spellcheck=False)
            for name, v in (("_transcribe_max_chars_var", 25), ("_transcribe_period_var", False),
                            ("_transcribe_spellcheck_var", False)):
                var = getattr(self, name, None)
                if var is not None:
                    var.set(v)
        elif section == "speaker":
            srt_io.g_display_pattern = srt_io.DEFAULT_DISPLAY_PATTERN
            srt_io.g_speaker_pattern = srt_io.DEFAULT_SPEAKER_PATTERN
            self._diarize_device_init = "auto"
            cfg["diarize_device"] = "auto"
            var = getattr(self, "_diarize_device_var", None)
            if var is not None:
                try:
                    var.set("auto")
                except tk.TclError:
                    pass
        _save_config(cfg)

    def _open_settings(self, tab_idx=0):
        """설정 창 (왼쪽 메뉴 + 오른쪽 카드 묶음)."""
        old = getattr(self, "_settings_win", None)
        if old is not None and old.winfo_exists():
            old.deiconify()
            old.lift()
            old.focus_force()
            return
        win = tk.Toplevel(self)
        self._settings_win = win
        win.withdraw()
        win.title("설정")
        win.configure(bg=BG)
        win.geometry("820x620")
        win.minsize(700, 480)
        win.transient(self)

        def _on_settings_close():
            self._save_diarize_settings()
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", _on_settings_close)

        # ── 왼쪽 메뉴 (선택 항목: 왼쪽 보라 막대 + 보라 글씨) ──
        nav = tk.Frame(win, bg=BG2, width=190)
        nav.pack(side="left", fill="y")
        nav.pack_propagate(False)
        tk.Frame(win, bg=BORDER, width=1).pack(side="left", fill="y")
        tk.Label(nav, text="설정", bg=BG2, fg=FG,
                 font=(theme.FONT_FAMILY, 15, "bold")).pack(anchor="w", padx=22, pady=(22, 14))

        content_host = tk.Frame(win, bg=BG)
        content_host.pack(side="left", fill="both", expand=True)

        _items = []
        _active = {"idx": -1}

        def _paint_item(i, hover=False):
            it = _items[i]
            cv, sel = it["cv"], i == _active["idx"]
            cv.configure(bg="#1C1C22" if (hover and not sel) else BG2)
            cv.itemconfigure("bar", state="normal" if sel else "hidden")
            cv.itemconfigure("label", fill=theme.ON_FG if sel else (FG if hover else FG_DIM),
                             font=(theme.FONT_FAMILY, 10, "bold" if sel else "normal"))

        def _select(idx):
            if idx == _active["idx"]:
                return
            _active["idx"] = idx
            for i, it in enumerate(_items):
                if i == idx:
                    it["outer"].pack(in_=content_host, fill="both", expand=True)
                else:
                    it["outer"].pack_forget()
                _paint_item(i)

        def _add_section(title, builder):
            outer, inner = self._make_scrollable(content_host)
            builder(inner)

            def _rebuild():
                for w in inner.winfo_children():
                    w.destroy()
                builder(inner)
            inner._rebuild = _rebuild
            idx = len(_items)
            cv = tk.Canvas(nav, width=190, height=38, bg=BG2, highlightthickness=0,
                           cursor="hand2")
            cv.pack(fill="x")
            cv.create_rectangle(0, 8, 3, 30, fill=ACCENT, outline="", tags="bar")
            cv.create_text(24, 19, text=title, anchor="w", tags="label")
            cv.bind("<Button-1>", lambda e, i=idx: _select(i))
            cv.bind("<Enter>", lambda e, i=idx: _paint_item(i, True))
            cv.bind("<Leave>", lambda e, i=idx: _paint_item(i))
            _items.append({"outer": outer, "cv": cv})
            _paint_item(idx)

        # ── 메뉴 아래 버전 정보 ───────────────
        ver = tk.Frame(nav, bg=BG2)
        ver.pack(side="bottom", fill="x", padx=22, pady=16)
        tk.Label(ver, text=f"현재 버전  v{APP_VERSION}", bg=BG2, fg=FG_DIM,
                 font=(theme.FONT_FAMILY, 8)).pack(anchor="w")
        self._settings_latest_lbl = tk.Label(ver, text="최신 버전  확인 중…", bg=BG2,
                                             fg=FG_HINT, font=(theme.FONT_FAMILY, 8))
        self._settings_latest_lbl.pack(anchor="w", pady=(2, 6))
        import webbrowser as _wb
        _gh_lbl = tk.Label(ver, text="GitHub", bg=BG2, fg="#6A8FC8", cursor="hand2",
                           font=(theme.FONT_FAMILY, 8, "underline"))
        _gh_lbl.pack(anchor="w")
        _gh_lbl.bind("<Button-1>",
                     lambda e: _wb.open("https://github.com/danggai/SRT-Speaker-Separator"))

        def _update_latest_lbl(v):
            try:
                self._settings_latest_lbl.configure(text=f"최신 버전  v{v}")
            except Exception:
                pass

        if getattr(self, "_latest_version_cache", None):
            _update_latest_lbl(self._latest_version_cache)
        else:
            import threading

            def _fetch_for_settings():
                tag = fetch_latest_version(timeout=5)
                if tag:
                    self._latest_version_cache = tag
                try:
                    self.after(0, lambda: _update_latest_lbl(tag or "확인 실패"))
                except (RuntimeError, tk.TclError):   # 그 사이 앱이 닫힘
                    pass
            threading.Thread(target=_fetch_for_settings, daemon=True).start()

        # ── 섹션 ──────────────────────────────
        _add_section("일반", self._build_general_section)
        _add_section("편집", self._build_edit_section)
        _add_section("자동 자막", self._build_transcribe_settings_tab)
        _add_section("화자", self._build_speaker_section)
        _add_section("저장 공간", self._build_storage_section)
        _add_section("내보내기", self._build_export_section)

        _select(tab_idx if 0 <= tab_idx < len(_items) else 0)

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

    # ── 섹션: 일반 ────────────────────────────
    def _build_general_section(self, parent):
        self._settings_title(parent, "일반", section="general")
        card = self._settings_card(parent, "시작")
        _, right = self._settings_row(card, "⌂", "시작 화면", None)
        start_var = tk.StringVar(value="last" if self._opt("startup_open_last") else "home")
        Segmented(right, [("홈 화면", "home"), ("마지막 파일", "last")], start_var,
                  lambda: self._set_opt("startup_open_last", start_var.get() == "last")).pack()

        card = self._settings_card(parent, "앱")
        _, right = self._settings_row(card, "↑", "새 버전 알림", None)
        self._opt_toggle(right, "update_check")
        _, right = self._settings_row(card, "K", "단축키 표시",
                                      "버튼 위에 단축키 표시")
        var = tk.BooleanVar(value=bool(getattr(self, "_key_hints_on", False)))

        def _hints():
            self._apply_key_hints(bool(var.get()))
            cfg = _load_config(); cfg["show_key_hints"] = bool(var.get()); _save_config(cfg)
        ToggleSwitch(right, var, _hints).pack()

        card = self._settings_card(parent, "설정 파일")
        _, right = self._settings_row(card, "⇅", "설정 내보내기 · 불러오기",
                                      "토큰·최근 파일은 빼고 저장")
        win = parent.winfo_toplevel()
        flat_button(right, "불러오기", lambda: self._import_settings(win), bg=BG3,
                    hover="#33333C", padx=14, pady=6).pack(side="right")
        flat_button(right, "내보내기", lambda: self._export_settings(win), bg=BG3,
                    hover="#33333C", padx=14, pady=6).pack(side="right", padx=(0, 8))

    def _export_settings(self, win):
        """공유해도 되는 설정만 JSON 파일로 저장."""
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(
            title="설정 내보내기", parent=win, defaultextension=".json",
            initialfile="srt_speaker_editor_settings.json",
            filetypes=[("JSON", "*.json"), ("모든 파일", "*.*")])
        if not path:
            return
        cfg = _load_config()
        data = {k: cfg[k] for k in sorted(self._settings_keys()) if k in cfg}
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            messagebox.showerror("설정 내보내기", f"저장하지 못했어요.\n{e}", parent=win)
            return
        messagebox.showinfo("설정 내보내기", "설정을 저장했어요.", parent=win)

    def _import_settings(self, win):
        """JSON 파일의 설정을 불러와 바로 적용."""
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="설정 불러오기", parent=win,
            filetypes=[("JSON", "*.json"), ("모든 파일", "*.*")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("형식이 맞지 않아요")
        except (OSError, ValueError) as e:
            messagebox.showerror("설정 불러오기", f"불러오지 못했어요.\n{e}", parent=win)
            return
        keys = self._settings_keys()
        picked = {k: v for k, v in data.items() if k in keys}
        if not picked:
            messagebox.showwarning("설정 불러오기", "불러올 설정이 없어요.", parent=win)
            return
        cfg = _load_config()
        cfg.update(picked)
        _save_config(cfg)
        self._reload_settings_from_config()
        win.destroy()
        self._open_settings(0)

    @staticmethod
    def _settings_keys():
        """내보내기·불러오기 대상 설정 키."""
        return set(OPTION_DEFAULTS) | {
            "show_key_hints", "speaker_colors", "proper_nouns", "proper_nouns_enabled",
            "transcribe_max_chars", "transcribe_period", "transcribe_spellcheck",
            "transcribe_language", "diarize_mode", "diarize_device", "diarize_batch",
            "diarize_sensitivity", "diarize_sens_scale", "diarize_spk_exact", "num_speakers",
            "volume"}

    def _reload_settings_from_config(self):
        """설정 파일 값을 앱 상태에 다시 반영."""
        cfg = _load_config()
        self.__dict__.pop("_opt_cache", None)
        self._transcribe_max_chars = cfg.get("transcribe_max_chars", 25)
        self._transcribe_period = cfg.get("transcribe_period", False)
        self._transcribe_spellcheck = cfg.get("transcribe_spellcheck", False)
        self._transcribe_language = cfg.get("transcribe_language", "ko")
        for name, v in (("_transcribe_max_chars_var", self._transcribe_max_chars),
                        ("_transcribe_period_var", self._transcribe_period),
                        ("_transcribe_spellcheck_var", self._transcribe_spellcheck)):
            var = getattr(self, name, None)
            if var is not None:
                var.set(v)
        self._diarize_num_spk_val = cfg.get("num_speakers", 0)
        self._diarize_mode_init = cfg.get("diarize_mode", self._diarize_mode_init)
        self._diarize_device_init = cfg.get("diarize_device", "auto")
        self._diarize_batch_init = cfg.get("diarize_batch", 3)
        self._diarize_spk_exact_init = cfg.get("diarize_spk_exact", False)
        if cfg.get("diarize_sens_scale") == 2:
            self._diarize_sensitivity_init = cfg.get("diarize_sensitivity", 50)
        for name, v in (("_diarize_num_spk", self._diarize_num_spk_val),
                        ("_diarize_mode_var", self._diarize_mode_init),
                        ("_diarize_device_var", self._diarize_device_init),
                        ("_diarize_batch_var", self._diarize_batch_init),
                        ("_diarize_sensitivity_var", self._diarize_sensitivity_init),
                        ("_diarize_spk_exact_var", self._diarize_spk_exact_init)):
            var = getattr(self, name, None)
            if var is not None:
                try:
                    var.set(v)
                except (tk.TclError, AttributeError):
                    pass
        pn = cfg.get("proper_nouns", [])
        self._proper_nouns = list(pn.keys()) if isinstance(pn, dict) else list(dict.fromkeys(pn))
        self._proper_nouns_enabled = cfg.get("proper_nouns_enabled", True)
        self._global_speaker_colors = dict(cfg.get("speaker_colors", {}))
        self._apply_key_hints(bool(cfg.get("show_key_hints", False)))

    # ── 섹션: 편집 ────────────────────────────
    def _build_edit_section(self, parent):
        self._settings_title(parent, "편집", section="edit")
        card = self._settings_card(parent, "화자 지정")
        _, right = self._settings_row(card, "↓", "지정 후 다음 줄로",
                                      "숫자 키로 지정하면 아래 줄 선택")
        self._opt_toggle(right, "advance_after_assign")

        card = self._settings_card(parent, "재생 · 이동")
        _, right = self._settings_row(card, "↔", "←/→ 이동 간격", None)
        self._opt_number(right, "seek_step", "초", 1, 60)
        self._opt_number(right, "seek_step_shift", "초", 1, 300, label="Shift")
        _, right = self._settings_row(card, "▸", "자막 클릭 시 재생 위치 이동",
                                      None)
        self._opt_toggle(right, "click_seek")

        card = self._settings_card(parent, "자막 추가 · 타임라인")
        _, right = self._settings_row(card, "+", "새 자막 기본 길이",
                                      "A 키·+ 자막으로 추가할 때")
        self._opt_number(right, "new_sub_len", "초", 0.5, 30, is_float=True)
        _, right = self._settings_row(card, "≡", "타임라인 시간 잠금",
                                      "파형에서 자막을 끌어 옮기지 못하게")
        self._opt_toggle(right, "lock_timeline")

    # ── 섹션: 자동 자막 ───────────────────────
    def _build_transcribe_settings_tab(self, parent):
        """자동 자막 설정."""
        self._settings_title(parent, "자동 자막", section="transcribe")
        card = self._settings_card(parent, "인식")

        # 한 줄 최대 글자 수 (슬라이더 + 직접 입력, 10~50)
        left, right = self._settings_row(card, "가", "한 줄 최대 글자 수",
                                         None)
        if not hasattr(self, "_transcribe_max_chars_var"):
            self._transcribe_max_chars_var = tk.IntVar(
                value=getattr(self, "_transcribe_max_chars", 25))
        _CHARS_MIN, _CHARS_MAX = 10, 50
        tk.Label(right, text="자", bg=BG2, fg=FG_DIM,
                 font=(theme.FONT_FAMILY, 9)).pack(side="right", padx=(4, 0))
        _chars_entry_var = tk.StringVar(value=str(self._transcribe_max_chars_var.get()))
        _chars_entry = tk.Entry(right, textvariable=_chars_entry_var, width=4,
                                bg=BG3, fg=FG, insertbackground=FG, justify="center",
                                relief="flat", highlightthickness=1,
                                highlightbackground=BORDER, highlightcolor=ACCENT,
                                font=(theme.FONT_FAMILY, 10))
        _chars_entry.pack(side="right", ipady=3)

        def _on_chars_change(*_):
            try:
                v = int(self._transcribe_max_chars_var.get())
                self._transcribe_max_chars = v
                _chars_entry_var.set(str(v))
                cfg = _load_config(); cfg["transcribe_max_chars"] = v; _save_config(cfg)
            except Exception:
                pass

        def _chars_slider_cmd(v):
            self._transcribe_max_chars_var.set(int(v))

        _chars_slider = PurpleSlider(left, from_=_CHARS_MIN, to=_CHARS_MAX,
                                     value=self._transcribe_max_chars_var.get(),
                                     width=260, command=_chars_slider_cmd, bg=BG2)
        _chars_slider.pack(anchor="w", pady=(10, 0))
        self._transcribe_max_chars_var.trace_add("write", _on_chars_change)

        def _chars_entry_commit(*_):
            try:
                v = int(_chars_entry_var.get())
            except Exception:
                v = self._transcribe_max_chars_var.get()
            v = max(_CHARS_MIN, min(_CHARS_MAX, v))
            self._transcribe_max_chars_var.set(v)
            _chars_slider.set(v, fire=False)
        _chars_entry.bind("<Return>", _chars_entry_commit)
        _chars_entry.bind("<FocusOut>", _chars_entry_commit)

        # 인식 언어
        _, right = self._settings_row(card, "A", "인식 언어", None)
        _lang_var = tk.StringVar(value=getattr(self, "_transcribe_language", "ko"))

        def _save_lang():
            self._transcribe_language = _lang_var.get()
            cfg = _load_config(); cfg["transcribe_language"] = _lang_var.get(); _save_config(cfg)
        Segmented(right, [("한국어", "ko"), ("자동 감지", "auto")], _lang_var, _save_lang).pack()

        card = self._settings_card(parent, "다듬기")
        # 문장 끝 마침표
        _, right = self._settings_row(card, ".", "문장 끝 마침표", None)
        if not hasattr(self, "_transcribe_period_var"):
            self._transcribe_period_var = tk.BooleanVar(
                value=getattr(self, "_transcribe_period", False))

        def _save_period():
            v = self._transcribe_period_var.get()
            self._transcribe_period = v
            cfg = _load_config(); cfg["transcribe_period"] = v; _save_config(cfg)
        ToggleSwitch(right, self._transcribe_period_var, _save_period).pack()

        # 맞춤법 자동 교정
        _, right = self._settings_row(card, "✓", "맞춤법 자동 교정",
                                      "네이버 맞춤법 검사기 (인터넷 필요)")
        if not hasattr(self, "_transcribe_spellcheck_var"):
            self._transcribe_spellcheck_var = tk.BooleanVar(
                value=getattr(self, "_transcribe_spellcheck", False))

        def _save_spellcheck():
            v = self._transcribe_spellcheck_var.get()
            self._transcribe_spellcheck = v
            cfg = _load_config(); cfg["transcribe_spellcheck"] = v; _save_config(cfg)
        ToggleSwitch(right, self._transcribe_spellcheck_var, _save_spellcheck).pack()

        # 고유명사 사전
        self._ensure_proper_nouns_init()
        _, right = self._settings_row(card, "#", "고유명사 사전",
                                      "등록한 이름·용어를 더 잘 인식")
        btn = flat_button(right, "", lambda: self._open_proper_noun_manager(on_close=_refresh_pn),
                          bg=BG3, hover="#33333C", font=(theme.FONT_FAMILY, 9), padx=14, pady=6)
        btn.pack()

        def _refresh_pn():
            btn.configure(text=f"{len(self._proper_nouns or [])}개  ·  관리")
        _refresh_pn()

    # ── 섹션: 화자 ────────────────────────────
    def _build_speaker_section(self, parent):
        self._settings_title(parent, "화자", section="speaker")
        self._build_pattern_tab(parent)

        card = self._settings_card(parent, "화자 분석")
        _, right = self._settings_row(card, "◎", "처리 장치",
                                      "오류가 나면 CPU로")
        dev_var = tk.StringVar(value=getattr(self, "_diarize_device_init", "auto"))

        def _save_dev():
            self._diarize_device_init = dev_var.get()
            if getattr(self, "_diarize_device_var", None) is not None:
                try:
                    self._diarize_device_var.set(dev_var.get())
                except tk.TclError:
                    pass
            cfg = _load_config(); cfg["diarize_device"] = dev_var.get(); _save_config(cfg)
        Segmented(right, [("GPU 우선", "auto"), ("CPU", "cpu")], dev_var, _save_dev).pack()

    def _build_pattern_tab(self, parent):
        """화자 표시 형식 (SRT에 화자 이름을 적는 방식)."""
        presets = [("[화자] 대사", "[%] &"), ("(화자) 대사", "(%) &"), ("화자: 대사", "%: &")]
        cur = srt_io.g_display_pattern
        mode = tk.StringVar(value=cur if cur in [v for _, v in presets] else "custom")
        custom_var = tk.StringVar(value=cur)

        card = self._settings_card(parent, "표시 형식")
        left, right = self._settings_row(card, "[ ]", "SRT에 적는 형식",
                                         None)
        seg = Segmented(left, presets + [("직접 입력", "custom")], mode, lambda: _apply())
        seg.configure(bg=BG2)
        seg.pack(anchor="w", pady=(10, 0))

        custom = tk.Frame(left, bg=BG2)
        tk.Label(custom, text="% = 화자, & = 대사",
                 bg=BG2, fg=FG_DIM, font=(theme.FONT_FAMILY, 9)).pack(anchor="w")
        entry = tk.Entry(custom, textvariable=custom_var, bg=BG3, fg=FG, insertbackground=FG,
                         font=(FONT_MONO, 11), relief="flat", highlightthickness=1,
                         highlightbackground=BORDER, highlightcolor=ACCENT)
        entry.pack(fill="x", ipady=5, pady=(6, 0))

        preview = tk.Frame(left, bg=BG3)
        preview.pack(fill="x", pady=(10, 0))
        tk.Label(preview, text="미리보기", bg=BG3, fg=FG_DIM,
                 font=(theme.FONT_FAMILY, 8)).pack(side="left", padx=(12, 10), pady=8)
        preview_lbl = tk.Label(preview, text="", bg=BG3, fg=FG, font=(theme.FONT_FAMILY, 11))
        preview_lbl.pack(side="left")

        def _apply(*_):
            if mode.get() == "custom":
                custom.pack(fill="x", pady=(10, 0), before=preview)
                dp = custom_var.get().strip()
            else:
                custom.pack_forget()
                dp = mode.get()
            if "%" not in dp or "&" not in dp:
                preview_lbl.configure(text="% 와 & 가 모두 있어야 해요", fg="#FF6B8A")
                return
            try:
                rx = display_to_regex(dp)
                re.compile(rx)
            except Exception:
                preview_lbl.configure(text="이 형식은 쓸 수 없어요", fg="#FF6B8A")
                return
            srt_io.g_speaker_pattern = rx
            srt_io.g_display_pattern = dp
            preview_lbl.configure(text=dp.replace("%", "민지").replace("&", "안녕하세요"), fg=FG)

        custom_var.trace_add("write", _apply)
        _apply()

    # ── 섹션: 저장 공간 ───────────────────────
    def _build_storage_section(self, parent):
        self._settings_title(parent, "저장 공간", section="storage")
        card = self._settings_card(parent, "자동 백업")
        _, right = self._settings_row(card, "↺", "자동 백업",
                                      "갑자기 꺼져도 다음 실행 때 복구")
        self._opt_toggle(right, "backup_enabled")
        _, right = self._settings_row(card, "⏱", "백업 간격", None)
        iv = tk.StringVar(value=str(self._opt("backup_minutes")))
        Segmented(right, [("1분", "1"), ("3분", "3"), ("5분", "5"), ("10분", "10")], iv,
                  lambda: self._set_opt("backup_minutes", int(iv.get()))).pack()
        _, right = self._settings_row(card, "▤", "백업 파일", None)
        size_lbl = tk.Label(right, text="", bg=BG2, fg=FG_DIM, font=(theme.FONT_FAMILY, 9))
        size_lbl.pack(side="left", padx=(0, 10))

        def _refresh_size():
            n = len(self._backup_files())
            size_lbl.configure(text=f"{n}개  ·  {self._backup_size() / 1024:.1f} KB" if n else "없음")

        def _delete():
            if self._backup_files() and messagebox.askyesno(
                    "백업 삭제", "백업 파일을 모두 지울까요?",
                    parent=parent.winfo_toplevel()):
                self._delete_all_backups()
            _refresh_size()
        flat_button(right, "백업 삭제", _delete, bg="#5A2A2E", fg="#FFD8D8", hover="#6E3438",
                    padx=14, pady=6).pack(side="left")
        _refresh_size()

        self._build_ai_card(parent)

        tk.Label(parent, text="모델", bg=BG, fg="#8A8A96",
                 font=(theme.FONT_FAMILY, 9, "bold")).pack(anchor="w", padx=34, pady=(18, 6))
        self._build_model_mgmt_tab(parent)

    # ── 섹션: 내보내기 ────────────────────────
    def _build_export_section(self, parent):
        self._settings_title(parent, "내보내기", section="export")
        card = self._settings_card(parent)
        left, right = self._settings_row(card, "→", "저장할 폴더", None)
        mode = tk.StringVar(value=self._opt("export_dir_mode"))
        Segmented(left, [("매번 묻기", "ask"), ("SRT와 같은 폴더", "same"), ("지정한 폴더", "fixed")],
                  mode, lambda: _changed()).pack(anchor="w", pady=(10, 0))
        folder = tk.Frame(left, bg=BG2)
        path_lbl = tk.Label(folder, text="", bg=BG2, fg=FG, font=(theme.FONT_FAMILY, 9),
                            anchor="w")
        path_lbl.pack(side="left", fill="x", expand=True)

        def _pick():
            from tkinter import filedialog
            d = filedialog.askdirectory(title="내보낼 폴더 선택", parent=parent.winfo_toplevel(),
                                        initialdir=self._opt("export_dir") or None)
            if d:
                self._set_opt("export_dir", d)
                _changed()
        flat_button(folder, "폴더 선택", _pick, bg=BG3, hover="#33333C", padx=12,
                    pady=5).pack(side="right")

        def _changed():
            self._set_opt("export_dir_mode", mode.get())
            if mode.get() == "fixed":
                folder.pack(fill="x", pady=(10, 0))
                path_lbl.configure(text=self._opt("export_dir") or "폴더를 골라 주세요")
            else:
                folder.pack_forget()
        _changed()

        _, right = self._settings_row(card, "▣", "srts 폴더에 모아 저장",
                                      "고른 위치 안에 srts 폴더를 만들어 저장")
        self._opt_toggle(right, "export_subfolder")

    def _build_model_mgmt_tab(self, parent):
        """다운로드된 모델 캐시 관리 탭."""
        import pathlib, os, shutil


        # 목록 영역
        list_frame = tk.Frame(parent, bg=BG2, height=300,
                              highlightthickness=1, highlightbackground=BORDER)
        list_frame.pack(fill="x", padx=32, pady=(0, 10))
        list_frame.pack_propagate(False)

        # 스크롤 가능한 내부 캔버스
        _canvas = tk.Canvas(list_frame, bg=BG2, highlightthickness=0)
        _sb = DarkScrollbar(list_frame, command=_canvas.yview)
        _inner = tk.Frame(_canvas, bg=BG2)
        _canvas.configure(yscrollcommand=_sb.set)
        _sb.pack(side="right", fill="y")
        _canvas.pack(side="left", fill="both", expand=True)
        _win_id = _canvas.create_window((0, 0), window=_inner, anchor="nw")
        _inner.bind("<Configure>",
                    lambda e: _canvas.configure(scrollregion=_canvas.bbox("all")))
        _canvas.bind("<Configure>",
                     lambda e: _canvas.itemconfigure(_win_id, width=e.width))

        def _fmt_size(nb):
            for u in ("B", "KB", "MB", "GB"):
                if nb < 1024:
                    return f"{nb:.1f} {u}"
                nb /= 1024
            return f"{nb:.1f} TB"

        def _dir_size(p):
            total = 0
            try:
                for f in pathlib.Path(p).rglob("*"):
                    if f.is_file():
                        total += f.stat().st_size
            except Exception:
                pass
            return total

        def _scan_models():
            found = []
            hf_hub = pathlib.Path(os.environ.get(
                "HF_HOME", pathlib.Path.home() / ".cache" / "huggingface")) / "hub"
            if hf_hub.exists():
                for d in sorted(hf_hub.iterdir()):
                    if not d.is_dir():
                        continue
                    sz = _dir_size(d)
                    if sz == 0:
                        continue
                    label = d.name.replace("models--", "").replace("--", "/")
                    found.append(("dir", d, label, sz))
            old_w = pathlib.Path.home() / ".cache" / "whisper"
            if old_w.exists():
                for f in sorted(old_w.iterdir()):
                    if f.is_file():
                        found.append(("file", f, f"whisper/{f.name}", f.stat().st_size))
            return found

        _chk_vars = {}

        def _refresh():
            for w in _inner.winfo_children():
                w.destroy()
            _chk_vars.clear()
            models = _scan_models()

            if not models:
                tk.Label(_inner, text="다운로드된 모델이 없습니다.",
                         bg=BG2, fg=FG_DIM, font=(theme.FONT_FAMILY, 9)
                         ).pack(padx=16, pady=16)
                _del_btn.configure(state="disabled")
                _del_all_btn.configure(state="disabled")
                return

            # 헤더
            hdr = tk.Frame(_inner, bg=BG3)
            hdr.pack(fill="x")
            tk.Label(hdr, text="  모델", bg=BG3, fg=FG_DIM, pady=6,
                     font=(theme.FONT_FAMILY, 9), anchor="w").pack(side="left", fill="x", expand=True)
            tk.Label(hdr, text="용량  ", bg=BG3, fg=FG_DIM, pady=6,
                     font=(theme.FONT_FAMILY, 9), anchor="e", width=10).pack(side="right")

            total_sz = 0
            for kind, path, label, sz in models:
                total_sz += sz
                row = tk.Frame(_inner, bg=BG2)
                row.pack(fill="x", pady=3)
                var = tk.BooleanVar(value=False)
                _chk_vars[str(path)] = (var, kind, path)
                CheckBox(row, var).pack(side="left", padx=(8, 0))
                tk.Label(row, text=label, bg=BG2, fg=FG,
                         font=(FONT_MONO, 9), anchor="w"
                         ).pack(side="left", fill="x", expand=True, padx=4)
                tk.Label(row, text=_fmt_size(sz), bg=BG2, fg=FG_DIM,
                         font=(theme.FONT_FAMILY, 9), width=10, anchor="e"
                         ).pack(side="right", padx=(0, 8))

            # 합계
            foot = tk.Frame(_inner, bg=BG3)
            foot.pack(fill="x", pady=(2, 0))
            tk.Label(foot, text="  전체", bg=BG3, fg=FG_DIM, pady=6,
                     font=(theme.FONT_FAMILY, 9), anchor="w").pack(side="left", fill="x", expand=True)
            tk.Label(foot, text=f"{_fmt_size(total_sz)}  ", bg=BG3, fg=FG, pady=6,
                     font=(theme.FONT_FAMILY, 9, "bold"), width=10, anchor="e").pack(side="right")

            _del_btn.configure(state="normal")
            _del_all_btn.configure(state="normal")

        def _delete_selected():
            targets = [(kind, path)
                       for key, (var, kind, path) in _chk_vars.items() if var.get()]
            if not targets:
                messagebox.showwarning("모델 삭제", "삭제할 모델을 선택하세요.",
                                       parent=parent.winfo_toplevel())
                return
            names = "\n".join(f"  • {pathlib.Path(str(p)).name}" for _, p in targets)
            if not messagebox.askyesno("모델 삭제",
                    f"선택한 {len(targets)}개 모델을 삭제합니다.\n\n{names}\n\n계속하시겠습니까?",
                    parent=parent.winfo_toplevel()):
                return
            _remove(targets)

        def _delete_all():
            targets = [(kind, path) for kind, path, _, _ in _scan_models()]
            if not targets or not messagebox.askyesno(
                    "모델 전체 삭제", f"모델 {len(targets)}개를 모두 지울까요?",
                    parent=parent.winfo_toplevel()):
                return
            _remove(targets)

        def _remove(targets):
            errors = []
            for kind, path in targets:
                try:
                    if kind == "file":
                        pathlib.Path(str(path)).unlink()
                    else:
                        shutil.rmtree(str(path))
                except Exception as e:
                    errors.append(str(e))
            if errors:
                messagebox.showerror("삭제 오류", "\n".join(errors),
                                     parent=parent.winfo_toplevel())
            _refresh()

        # 하단 버튼
        btn_row = tk.Frame(parent, bg=BG)
        btn_row.pack(fill="x", padx=32, pady=(0, 20))
        flat_button(btn_row, "↻  새로고침", _refresh, bg=BG3, hover="#33333C",
                    padx=14, pady=6).pack(side="left")
        _del_btn = flat_button(btn_row, "선택 삭제", _delete_selected, bg="#5A2A2E",
                               fg="#FFD8D8", hover="#6E3438", padx=14, pady=6)
        _del_btn.pack(side="left", padx=(8, 0))
        _del_all_btn = flat_button(btn_row, "전체 삭제", _delete_all, bg="#5A2A2E",
                                   fg="#FFD8D8", hover="#6E3438", padx=14, pady=6)
        _del_all_btn.pack(side="left", padx=(8, 0))

        _refresh()
