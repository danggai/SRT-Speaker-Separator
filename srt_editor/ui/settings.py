"""설정 창과 자동 자막/모델 관리 탭."""
import re
import tkinter as tk
from tkinter import messagebox
from tkinter import ttk

from .. import srt_io, theme
from ..config import _load_config, _save_config
from ..srt_io import DEFAULT_DISPLAY_PATTERN, display_to_regex
from ..theme import ACCENT, BG, BG2, BG3, BORDER, FG, FG_DIM, FONT_MONO, _apply_dark_titlebar
from ..version import APP_VERSION, GITHUB_LATEST_API
from ..widgets import PurpleSlider


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
        vsb = tk.Scrollbar(outer, orient="vertical", command=canvas.yview)
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
            bbox = canvas.bbox("all")
            content_h = (bbox[3] - bbox[1]) if bbox else 0
            if content_h <= canvas.winfo_height():
                return
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        def _bind_wheel(_e=None):
            canvas.bind_all("<MouseWheel>", _wheel)
        def _unbind_wheel(_e=None):
            # 다이얼로그를 벗어나면 메인 테이블의 원래 휠 스크롤 핸들러로 복원
            canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        canvas.bind("<Enter>", _bind_wheel)
        canvas.bind("<Leave>", _unbind_wheel)
        inner.bind("<Enter>", _bind_wheel)
        inner.bind("<Leave>", _unbind_wheel)

        if with_footer:
            return outer, inner, footer
        return outer, inner

    def _open_settings(self, tab_idx=0):
        """설정 창 (탭: 자동 자막 / 모델 관리 / 화자 구분 패턴)"""
        win = tk.Toplevel(self)
        _apply_dark_titlebar(win)
        win.title("설정")
        win.configure(bg=BG)
        win.geometry("580x540")
        win.minsize(500, 380)
        win.resizable(True, True)
        win.transient(self)
        win.grab_set()

        def _on_settings_close():
            self._save_diarize_settings()
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", _on_settings_close)

        # ── 커스텀 탭바 (플랫 디자인: 점 표시 + 강조색, ttk.Notebook 대체) ──
        tab_bar = tk.Frame(win, bg=BG)
        tab_bar.pack(fill="x", side="top")
        tk.Frame(win, bg=BORDER, height=1).pack(fill="x", side="top")

        _tabs = []
        _active = {"idx": -1}

        def _select_tab(idx):
            if idx == _active["idx"]:
                return
            for i, t in enumerate(_tabs):
                active = (i == idx)
                if active:
                    t["outer"].pack(in_=content_host, fill="both", expand=True)
                else:
                    t["outer"].pack_forget()
                t["label"].configure(
                    fg=FG if active else FG_DIM,
                    font=(theme.FONT_FAMILY, 10, "bold" if active else "normal"))
                t["underline"].configure(bg=ACCENT if active else BG)
            _active["idx"] = idx

        def _add_tab(title, outer):
            idx = len(_tabs)
            cell = tk.Frame(tab_bar, bg=BG, cursor="hand2")
            cell.pack(side="left", padx=(18 if idx == 0 else 16, 0))
            lbl = tk.Label(cell, text=title, bg=BG, fg=FG_DIM,
                          font=(theme.FONT_FAMILY, 10), cursor="hand2")
            lbl.pack(side="top", pady=(11, 8))
            underline = tk.Frame(cell, bg=BG, height=3)
            underline.pack(side="top", fill="x")
            for w in (cell, lbl, underline):
                w.bind("<Button-1>", lambda e, i=idx: _select_tab(i))
            _tabs.append({"outer": outer, "label": lbl, "underline": underline})
            return idx

        # ── 하단 버전 정보 (content_host보다 먼저 pack해야 가려지지 않음)
        _ver_frame = tk.Frame(win, bg=BG2)
        _ver_frame.pack(fill="x", side="bottom")
        tk.Frame(_ver_frame, bg=BORDER, height=1).pack(fill="x")
        _ver_row = tk.Frame(_ver_frame, bg=BG2)
        _ver_row.pack(fill="x", padx=16, pady=6)
        tk.Label(_ver_row, text=f"현재 버전: v{APP_VERSION}",
                 bg=BG2, fg=FG_DIM, font=(theme.FONT_FAMILY, 8)).pack(side="left")
        self._settings_latest_lbl = tk.Label(_ver_row, text="최신 버전: 확인 중...",
                 bg=BG2, fg=FG_DIM, font=(theme.FONT_FAMILY, 8))
        self._settings_latest_lbl.pack(side="left", padx=(16, 0))

        import webbrowser as _wb
        _gh_lbl = tk.Label(_ver_row, text="🔗 GitHub",
                           bg=BG2, fg="#4A90E2",
                           font=(theme.FONT_FAMILY, 8, "underline"),
                           cursor="hand2")
        _gh_lbl.pack(side="right")
        _gh_lbl.bind("<Button-1>",
                     lambda e: _wb.open("https://github.com/danggai/SRT-Speaker-Separator"))

        def _update_latest_lbl(v):
            try:
                self._settings_latest_lbl.configure(text=f"최신 버전: v{v}")
            except Exception:
                pass

        if getattr(self, "_latest_version_cache", None):
            _update_latest_lbl(self._latest_version_cache)
        else:
            import threading
            def _fetch_for_settings():
                import urllib.request, json
                headers = {"User-Agent": "Mozilla/5.0 SRT-Speaker-Separator",
                           "Accept": "application/vnd.github+json"}
                for url, extractor in [
                    ("https://api.github.com/repos/danggai/SRT-Speaker-Separator/releases/latest",
                     lambda d: d.get("tag_name", "")),
                    ("https://api.github.com/repos/danggai/SRT-Speaker-Separator/git/refs/tags",
                     lambda d: d[-1]["ref"].split("/")[-1] if d else ""),
                    (GITHUB_LATEST_API,
                     lambda d: d[0]["name"] if d else ""),
                ]:
                    try:
                        req = urllib.request.Request(url, headers=headers)
                        with urllib.request.urlopen(req, timeout=5) as resp:
                            tag = extractor(json.loads(resp.read().decode()))
                        if tag:
                            self._latest_version_cache = tag.lstrip("v")
                            self.after(0, lambda v=tag.lstrip("v"): _update_latest_lbl(v))
                            return
                    except Exception:
                        continue
                self.after(0, lambda: _update_latest_lbl("확인 실패"))
            threading.Thread(target=_fetch_for_settings, daemon=True).start()

        content_host = tk.Frame(win, bg=BG)
        content_host.pack(fill="both", expand=True)

        # ── 탭 1: 자동 자막 ────────────────────
        tab2_outer, tab2 = self._make_scrollable(content_host)
        _add_tab("자동 자막", tab2_outer)
        self._build_transcribe_settings_tab(tab2)

        # ── 탭 2: 모델 관리 ────────────────────
        tab3_outer, tab3 = self._make_scrollable(content_host)
        _add_tab("모델 관리", tab3_outer)
        self._build_model_mgmt_tab(tab3)

        # ── 탭 3: 화자 구분 패턴 ──────────────────
        tab1_outer, tab1, tab1_footer = self._make_scrollable(content_host, with_footer=True)
        _add_tab("화자 구분 패턴", tab1_outer)

        tk.Label(tab1, text="화자 구분 패턴", bg=BG, fg=FG,
                 font=(theme.FONT_FAMILY, 11, "bold")).pack(anchor="w", padx=20, pady=(18, 2))
        tk.Label(tab1,
                 text="% = 현재 화자명,  & = 자막 내용\n"
                      "예시:  [%] &  →  [Alice] 안녕하세요\n"
                      "예시:  (%): &  →  (Bob): 반갑습니다",
                 bg=BG, fg=FG_DIM, font=(theme.FONT_FAMILY, 9),
                 justify="left").pack(anchor="w", padx=20, pady=(0, 6))

        pat_var = tk.StringVar(value=srt_io.g_display_pattern)
        pat_entry = tk.Entry(tab1, textvariable=pat_var, width=52,
                             bg=BG3, fg=ACCENT, insertbackground=FG,
                             font=(FONT_MONO, 10), relief="flat",
                             highlightthickness=1, highlightbackground=BORDER,
                             highlightcolor=ACCENT)
        pat_entry.pack(fill="x", padx=20, ipady=4)

        preview_lbl = tk.Label(tab1, text="", bg=BG, fg=FG_DIM,
                               font=(FONT_MONO, 8), wraplength=500, justify="left")
        preview_lbl.pack(anchor="w", padx=20, pady=(3, 0))
        info_lbl = tk.Label(tab1, text="", bg=BG, fg="#FF6B8A",
                            font=(theme.FONT_FAMILY, 9))
        info_lbl.pack(anchor="w", padx=20, pady=(2, 0))

        def update_preview(*_):
            dp = pat_var.get().strip()
            try:
                rx = display_to_regex(dp)
                re.compile(rx)
                preview_lbl.configure(text=f"정규식: {rx}", fg=FG_DIM)
                info_lbl.configure(text="")
            except Exception as err:
                preview_lbl.configure(text="")
                info_lbl.configure(text=f"❌ {err}", fg="#FF6B8A")

        pat_var.trace_add("write", update_preview)
        update_preview()

        def on_apply():
            dp = pat_var.get().strip()
            try:
                rx = display_to_regex(dp)
                re.compile(rx)
            except Exception as err:
                info_lbl.configure(text=f"❌ {err}", fg="#FF6B8A")
                return
            srt_io.g_speaker_pattern = rx
            srt_io.g_display_pattern = dp
            info_lbl.configure(text="✔ 적용되었습니다.", fg=ACCENT)
            win.after(1200, win.destroy)

        btn_row = tk.Frame(tab1_footer, bg=BG)
        btn_row.pack(fill="x", padx=20, pady=(10, 10))
        tk.Button(btn_row, text="기본값",
                  bg="#2A2A2A", fg=FG_DIM, relief="flat", bd=0, cursor="hand2",
                  font=(theme.FONT_FAMILY, 10), padx=10, pady=5,
                  activebackground="#333333",
                  command=lambda: pat_var.set(DEFAULT_DISPLAY_PATTERN)
                  ).pack(side="left")
        tk.Button(btn_row, text="적용",
                  bg=ACCENT, fg="white", relief="flat", bd=0, cursor="hand2",
                  font=(theme.FONT_FAMILY, 10, "bold"), padx=18, pady=5,
                  activebackground="#7B5FB4", command=on_apply).pack(side="right")
        tk.Button(btn_row, text="취소",
                  bg="#2A2A2A", fg=FG, relief="flat", bd=0, cursor="hand2",
                  font=(theme.FONT_FAMILY, 10), padx=12, pady=5,
                  activebackground="#333333",
                  command=win.destroy).pack(side="right", padx=(0, 8))

        _select_tab(tab_idx if 0 <= tab_idx < len(_tabs) else 0)


    def _build_transcribe_settings_tab(self, parent):
        """자동 자막 생성 설정 탭."""
        tk.Label(parent, text="자동 자막 설정", bg=BG, fg=FG,
                 font=(theme.FONT_FAMILY, 11, "bold")).pack(anchor="w", padx=20, pady=(18, 2))
        tk.Label(parent,
                 text="미디어 파일 드래그 시 자동 자막 생성에 사용되는 설정입니다.",
                 bg=BG, fg=FG_DIM, font=(theme.FONT_FAMILY, 9)).pack(anchor="w", padx=20, pady=(0, 14))
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=20, pady=(0, 14))

        # 문장 당 글자 수 제한 (슬라이더 + 직접 입력, 10~50, 기본 25)
        row1 = tk.Frame(parent, bg=BG)
        row1.pack(fill="x", padx=20, pady=(0, 4))
        tk.Label(row1, text="문장 당 글자 수 제한", bg=BG, fg=FG,
                 font=(theme.FONT_FAMILY, 9, "bold"), width=22, anchor="w").pack(side="left")
        if not hasattr(self, "_transcribe_max_chars_var"):
            self._transcribe_max_chars_var = tk.IntVar(
                value=getattr(self, "_transcribe_max_chars", 25))
        _CHARS_MIN, _CHARS_MAX = 10, 50
        tk.Label(row1, text="자", bg=BG, fg=FG,
                 font=(theme.FONT_FAMILY, 9)).pack(side="right")
        _chars_entry_var = tk.StringVar(value=str(self._transcribe_max_chars_var.get()))
        _chars_entry = tk.Entry(row1, textvariable=_chars_entry_var, width=4,
                                 bg=BG3, fg=FG, insertbackground=FG, justify="center",
                                 relief="flat", highlightthickness=1,
                                 highlightbackground=BORDER, highlightcolor=ACCENT,
                                 font=(theme.FONT_FAMILY, 9))
        _chars_entry.pack(side="right", padx=(0, 2))
        def _on_chars_change(*_):
            try:
                v = int(self._transcribe_max_chars_var.get())
                self._transcribe_max_chars = v
                _chars_entry_var.set(str(v))
                cfg = _load_config(); cfg["transcribe_max_chars"] = v; _save_config(cfg)
            except Exception: pass
        def _chars_slider_cmd(v):
            self._transcribe_max_chars_var.set(int(v))
            _on_chars_change()
        _chars_slider = PurpleSlider(parent, from_=_CHARS_MIN, to=_CHARS_MAX,
                     value=self._transcribe_max_chars_var.get(),
                     width=340, command=_chars_slider_cmd, bg=BG)
        _chars_slider.pack(padx=20, anchor="w", pady=(2, 14))
        self._transcribe_max_chars_var.trace_add("write", _on_chars_change)
        def _chars_entry_commit(*_):
            try:
                v = int(_chars_entry_var.get())
            except Exception:
                v = self._transcribe_max_chars_var.get()
            v = max(_CHARS_MIN, min(_CHARS_MAX, v))
            self._transcribe_max_chars_var.set(v)   # trace가 _on_chars_change 호출
            _chars_slider.set(v, fire=False)
        _chars_entry.bind("<Return>",   _chars_entry_commit)
        _chars_entry.bind("<FocusOut>", _chars_entry_commit)

        # 문장 끝 마침표
        row2 = tk.Frame(parent, bg=BG)
        row2.pack(fill="x", padx=20, pady=(0, 12))
        tk.Label(row2, text="\ubb38\uc7a5 \ub05d \ub9c8\uce68\ud45c \ucd94\uac00", bg=BG, fg=FG,
                 font=(theme.FONT_FAMILY, 9, "bold"), width=22, anchor="w").pack(side="left")
        if not hasattr(self, "_transcribe_period_var"):
            self._transcribe_period_var = tk.BooleanVar(
                value=getattr(self, "_transcribe_period", False))
        def _save_period():
            v = self._transcribe_period_var.get()
            self._transcribe_period = v
            cfg = _load_config(); cfg["transcribe_period"] = v; _save_config(cfg)
        tk.Checkbutton(row2, variable=self._transcribe_period_var,
                       bg=BG, fg=FG, selectcolor=BG3, activebackground=BG,
                       font=(theme.FONT_FAMILY, 9), cursor="hand2",
                       text="\ud65c\uc131\ud654",
                       command=_save_period).pack(side="left")

        # 인식 언어
        row_lang = tk.Frame(parent, bg=BG)
        row_lang.pack(fill="x", padx=20, pady=(0, 12))
        tk.Label(row_lang, text="인식 언어", bg=BG, fg=FG,
                 font=(theme.FONT_FAMILY, 9, "bold"), width=22, anchor="w").pack(side="left")
        _lang_var = tk.StringVar(value=getattr(self, "_transcribe_language", "ko"))
        def _save_lang():
            self._transcribe_language = _lang_var.get()
            cfg = _load_config(); cfg["transcribe_language"] = _lang_var.get(); _save_config(cfg)
        for _txt, _val in [("한국어 고정 (권장)", "ko"), ("자동 감지", "auto")]:
            tk.Radiobutton(row_lang, text=_txt, value=_val, variable=_lang_var,
                           command=_save_lang,
                           bg=BG, fg=FG, selectcolor=BG3, activebackground=BG,
                           font=(theme.FONT_FAMILY, 9), cursor="hand2").pack(side="left", padx=(0, 10))

        # 자동 맞춤법 검사 (UI만)
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=20, pady=(4, 14))
        row3 = tk.Frame(parent, bg=BG)
        row3.pack(fill="x", padx=20, pady=(0, 4))
        tk.Label(row3, text="\uc790\ub3d9 \ub9de\ucda4\ubc95 \uac80\uc0ac", bg=BG, fg=FG,
                 font=(theme.FONT_FAMILY, 9, "bold"), width=22, anchor="w").pack(side="left")
        if not hasattr(self, "_transcribe_spellcheck_var"):
            self._transcribe_spellcheck_var = tk.BooleanVar(value=False)
        def _save_spellcheck():
            v = self._transcribe_spellcheck_var.get()
            self._transcribe_spellcheck = v
            cfg = _load_config(); cfg["transcribe_spellcheck"] = v; _save_config(cfg)
        tk.Checkbutton(row3, variable=self._transcribe_spellcheck_var,
                       bg=BG, fg=FG, selectcolor=BG3, activebackground=BG,
                       font=(theme.FONT_FAMILY, 9), cursor="hand2",
                       text="\ud65c\uc131\ud654  (\ub124\uc774\ubc84 \ub9de\ucda4\ubc95 \uac80\uc0ac\uae30 \uc0ac\uc6a9)",
                       command=_save_spellcheck).pack(side="left")
        tk.Label(row3, text="\u26a0\ufe0f  \uc778\ud130\ub137 \uc5f0\uacb0 \ud544\uc694 / \uc790\ub9c9 \uc0dd\uc131 \uc2dc\uc5d0\ub9cc \uc801\uc6a9",
                 bg=BG, fg=FG_DIM, font=(theme.FONT_FAMILY, 8)).pack(side="left", padx=(8, 0))

        # 고유명사 사전 (인식 가중치)
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=20, pady=(10, 10))
        self._build_proper_noun_section(parent)

    def _build_model_mgmt_tab(self, parent):
        """다운로드된 모델 캐시 관리 탭."""
        import pathlib, os, shutil

        tk.Label(parent, text="다운로드된 모델", bg=BG, fg=FG,
                 font=(theme.FONT_FAMILY, 11, "bold")).pack(anchor="w", padx=20, pady=(18, 2))
        tk.Label(parent,
                 text="WhisperX / pyannote 모델 캐시를 확인하고 삭제할 수 있습니다.",
                 bg=BG, fg=FG_DIM, font=(theme.FONT_FAMILY, 9), justify="left"
                 ).pack(anchor="w", padx=20, pady=(0, 10))

        # 목록 영역
        list_frame = tk.Frame(parent, bg=BG2,
                              highlightthickness=1, highlightbackground=BORDER)
        list_frame.pack(fill="both", expand=True, padx=20, pady=(0, 8))

        # 스크롤 가능한 내부 캔버스
        _canvas = tk.Canvas(list_frame, bg=BG2, highlightthickness=0)
        _sb = ttk.Scrollbar(list_frame, orient="vertical", command=_canvas.yview)
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
                return

            # 헤더
            hdr = tk.Frame(_inner, bg=BG3)
            hdr.pack(fill="x")
            tk.Label(hdr, text="  모델명", bg=BG3, fg=FG_DIM,
                     font=(theme.FONT_FAMILY, 8), anchor="w").pack(side="left", fill="x", expand=True)
            tk.Label(hdr, text="용량  ", bg=BG3, fg=FG_DIM,
                     font=(theme.FONT_FAMILY, 8), anchor="e", width=10).pack(side="right")

            total_sz = 0
            for kind, path, label, sz in models:
                total_sz += sz
                row = tk.Frame(_inner, bg=BG2)
                row.pack(fill="x", pady=1)
                var = tk.BooleanVar(value=False)
                _chk_vars[str(path)] = (var, kind, path)
                tk.Checkbutton(row, variable=var, bg=BG2, fg=FG,
                               selectcolor=BG3, activebackground=BG2,
                               cursor="hand2").pack(side="left", padx=(6, 0))
                tk.Label(row, text=label, bg=BG2, fg=FG,
                         font=(FONT_MONO, 8), anchor="w"
                         ).pack(side="left", fill="x", expand=True, padx=4)
                tk.Label(row, text=_fmt_size(sz), bg=BG2, fg=FG_DIM,
                         font=(theme.FONT_FAMILY, 8), width=10, anchor="e"
                         ).pack(side="right", padx=(0, 8))

            # 합계
            foot = tk.Frame(_inner, bg=BG3)
            foot.pack(fill="x", pady=(2, 0))
            tk.Label(foot, text="  전체", bg=BG3, fg=FG_DIM,
                     font=(theme.FONT_FAMILY, 8), anchor="w").pack(side="left", fill="x", expand=True)
            tk.Label(foot, text=f"{_fmt_size(total_sz)}  ", bg=BG3, fg=FG,
                     font=(theme.FONT_FAMILY, 8, "bold"), width=10, anchor="e").pack(side="right")

            _del_btn.configure(state="normal")

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
        btn_row.pack(fill="x", padx=20, pady=(0, 16))
        tk.Button(btn_row, text="↻  새로고침",
                  bg=BG3, fg=FG, relief="flat", bd=0, cursor="hand2",
                  font=(theme.FONT_FAMILY, 9), padx=10, pady=5,
                  activebackground="#333333",
                  command=_refresh).pack(side="left")
        _del_btn = tk.Button(btn_row, text="🗑  선택 삭제",
                  bg="#6B2F2F", fg="white", relief="flat", bd=0, cursor="hand2",
                  font=(theme.FONT_FAMILY, 9), padx=10, pady=5,
                  activebackground="#8B3F3F",
                  command=_delete_selected)
        _del_btn.pack(side="left", padx=(8, 0))

        _refresh()
