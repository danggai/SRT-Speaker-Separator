"""설정 창과 자동 자막/모델 관리 탭."""
import re
import tkinter as tk
from tkinter import messagebox
from tkinter import ttk

from .. import srt_io, theme
from ..config import _load_config, _save_config
from ..srt_io import display_to_regex
from ..theme import ACCENT, BG, BG2, BG3, BORDER, FG, FG_DIM, FONT_MONO, _apply_dark_titlebar
from ..version import APP_VERSION, GITHUB_LATEST_API
from ..widgets import PurpleSlider, Segmented, ToggleSwitch, flat_button, rounded_rect_image


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

    # ── 설정 창 공용 레이아웃 ─────────────────
    def _settings_title(self, parent, title, desc=None):
        """섹션 제목 (큼직한 글씨 + 한 줄 설명)."""
        tk.Label(parent, text=title, bg=BG, fg=FG,
                 font=(theme.FONT_FAMILY, 15, "bold")).pack(anchor="w", padx=32, pady=(26, 2))
        if desc:
            tk.Label(parent, text=desc, bg=BG, fg=FG_DIM,
                     font=(theme.FONT_FAMILY, 9)).pack(anchor="w", padx=32)
        tk.Frame(parent, bg=BG, height=10).pack()

    def _settings_row(self, parent, title, desc=None):
        """설정 한 줄: 왼쪽 제목·설명, 오른쪽 컨트롤 자리. (left, right) 반환."""
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", padx=32, pady=11)
        right = tk.Frame(row, bg=BG)
        right.pack(side="right", anchor="n", pady=(2, 0))
        left = tk.Frame(row, bg=BG)
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text=title, bg=BG, fg=FG,
                 font=(theme.FONT_FAMILY, 11, "bold")).pack(anchor="w")
        if desc:
            tk.Label(left, text=desc, bg=BG, fg=FG_DIM, justify="left",
                     font=(theme.FONT_FAMILY, 9)).pack(anchor="w", pady=(3, 0))
        return left, right

    def _open_settings(self, tab_idx=0):
        """설정 창 (왼쪽 메뉴: 자동 자막 / 모델 관리 / 화자 표시 형식)."""
        win = tk.Toplevel(self)
        win.withdraw()
        win.title("설정")
        win.configure(bg=BG)
        win.geometry("780x580")
        win.minsize(660, 460)
        win.transient(self)

        def _on_settings_close():
            self._save_diarize_settings()
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", _on_settings_close)

        # ── 왼쪽 메뉴 ─────────────────────────
        nav = tk.Frame(win, bg=BG2, width=196)
        nav.pack(side="left", fill="y")
        nav.pack_propagate(False)
        tk.Frame(win, bg=BORDER, width=1).pack(side="left", fill="y")
        tk.Label(nav, text="설정", bg=BG2, fg=FG,
                 font=(theme.FONT_FAMILY, 15, "bold")).pack(anchor="w", padx=20, pady=(22, 16))

        content_host = tk.Frame(win, bg=BG)
        content_host.pack(side="left", fill="both", expand=True)

        _items = []
        _active = {"idx": -1}

        def _paint_item(i, hover=False):
            it = _items[i]
            sel = i == _active["idx"]
            fill = BG3 if sel else ("#202026" if hover else BG2)
            it["cv"].itemconfigure("bg", image=rounded_rect_image(it["w"], it["h"], 8, fill))
            it["cv"].itemconfigure("label", fill=FG if sel else FG_DIM,
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

        def _add_section(title, outer):
            idx = len(_items)
            w, h = 172, 38
            cv = tk.Canvas(nav, width=w, height=h, bg=BG2, highlightthickness=0, cursor="hand2")
            cv.pack(padx=12, pady=1)
            cv.create_image(0, 0, anchor="nw", tags="bg")
            cv.create_text(16, h / 2, text=title, anchor="w", tags="label")
            cv.bind("<Button-1>", lambda e, i=idx: _select(i))
            cv.bind("<Enter>", lambda e, i=idx: _paint_item(i, True))
            cv.bind("<Leave>", lambda e, i=idx: _paint_item(i))
            _items.append({"outer": outer, "cv": cv, "w": w, "h": h})
            _paint_item(idx)

        # ── 메뉴 아래 버전 정보 ───────────────
        ver = tk.Frame(nav, bg=BG2)
        ver.pack(side="bottom", fill="x", padx=20, pady=16)
        tk.Label(ver, text=f"현재 버전  v{APP_VERSION}", bg=BG2, fg=FG_DIM,
                 font=(theme.FONT_FAMILY, 8)).pack(anchor="w")
        self._settings_latest_lbl = tk.Label(ver, text="최신 버전  확인 중…", bg=BG2,
                                             fg="#5A5A66", font=(theme.FONT_FAMILY, 8))
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

        # ── 섹션 ──────────────────────────────
        outer, inner = self._make_scrollable(content_host)
        _add_section("자동 자막", outer)
        self._build_transcribe_settings_tab(inner)

        outer, inner = self._make_scrollable(content_host)
        _add_section("모델 관리", outer)
        self._build_model_mgmt_tab(inner)

        outer, inner = self._make_scrollable(content_host)
        _add_section("화자 표시 형식", outer)
        self._build_pattern_tab(inner)

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

    def _build_transcribe_settings_tab(self, parent):
        """자동 자막 설정."""
        self._settings_title(parent, "자동 자막", "음성·영상에서 자막을 만들 때 쓰는 설정이에요.")

        # 한 줄 최대 글자 수 (슬라이더 + 직접 입력, 10~50)
        left, right = self._settings_row(parent, "한 줄 최대 글자 수",
                                         "자막 한 줄에 넣을 글자 수예요.")
        if not hasattr(self, "_transcribe_max_chars_var"):
            self._transcribe_max_chars_var = tk.IntVar(
                value=getattr(self, "_transcribe_max_chars", 25))
        _CHARS_MIN, _CHARS_MAX = 10, 50
        tk.Label(right, text="자", bg=BG, fg=FG_DIM,
                 font=(theme.FONT_FAMILY, 10)).pack(side="right", padx=(4, 0))
        _chars_entry_var = tk.StringVar(value=str(self._transcribe_max_chars_var.get()))
        _chars_entry = tk.Entry(right, textvariable=_chars_entry_var, width=4,
                                bg=BG3, fg=FG, insertbackground=FG, justify="center",
                                relief="flat", highlightthickness=1,
                                highlightbackground=BORDER, highlightcolor=ACCENT,
                                font=(theme.FONT_FAMILY, 11))
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
                                     width=300, command=_chars_slider_cmd, bg=BG)
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

        # 문장 끝 마침표
        _, right = self._settings_row(parent, "문장 끝 마침표", "자막 끝에 마침표를 붙여요.")
        if not hasattr(self, "_transcribe_period_var"):
            self._transcribe_period_var = tk.BooleanVar(
                value=getattr(self, "_transcribe_period", False))

        def _save_period():
            v = self._transcribe_period_var.get()
            self._transcribe_period = v
            cfg = _load_config(); cfg["transcribe_period"] = v; _save_config(cfg)
        ToggleSwitch(right, self._transcribe_period_var, _save_period).pack()

        # 인식 언어
        _, right = self._settings_row(parent, "인식 언어",
                                      "한국어 영상이면 '한국어'가 더 정확해요.")
        _lang_var = tk.StringVar(value=getattr(self, "_transcribe_language", "ko"))

        def _save_lang():
            self._transcribe_language = _lang_var.get()
            cfg = _load_config(); cfg["transcribe_language"] = _lang_var.get(); _save_config(cfg)
        Segmented(right, [("한국어", "ko"), ("자동 감지", "auto")], _lang_var, _save_lang).pack()

        # 맞춤법 자동 교정
        _, right = self._settings_row(parent, "맞춤법 자동 교정",
                                      "네이버 맞춤법 검사기로 고쳐요. 인터넷이 필요해요.")
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
        _, right = self._settings_row(parent, "고유명사 사전",
                                      "자주 나오는 이름·용어를 등록하면 더 잘 알아들어요.")
        btn = flat_button(right, "", lambda: self._open_proper_noun_manager(on_close=_refresh_pn),
                          bg=BG3, hover="#33333C", font=(theme.FONT_FAMILY, 9), padx=14, pady=6)
        btn.pack()

        def _refresh_pn():
            btn.configure(text=f"{len(self._proper_nouns or [])}개  ·  관리")
        _refresh_pn()

    def _build_pattern_tab(self, parent):
        """화자 표시 형식 (SRT에 화자 이름을 적는 방식)."""
        self._settings_title(parent, "화자 표시 형식", "SRT 파일에 화자 이름을 어떻게 적을지 정해요.")

        presets = [("[화자] 대사", "[%] &"), ("(화자) 대사", "(%) &"), ("화자: 대사", "%: &")]
        cur = srt_io.g_display_pattern
        mode = tk.StringVar(value=cur if cur in [v for _, v in presets] else "custom")
        custom_var = tk.StringVar(value=cur)

        _, right = self._settings_row(parent, "형식", None)
        Segmented(right, presets + [("직접 입력", "custom")], mode, lambda: _apply()).pack()

        custom = tk.Frame(parent, bg=BG)
        tk.Label(custom, text="화자 이름 자리에 %, 대사 자리에 & 를 넣어 주세요.",
                 bg=BG, fg=FG_DIM, font=(theme.FONT_FAMILY, 9)).pack(anchor="w")
        entry = tk.Entry(custom, textvariable=custom_var, bg=BG3, fg=FG, insertbackground=FG,
                         font=(FONT_MONO, 11), relief="flat", highlightthickness=1,
                         highlightbackground=BORDER, highlightcolor=ACCENT)
        entry.pack(fill="x", ipady=5, pady=(6, 0))

        preview = tk.Frame(parent, bg=BG2, highlightthickness=1, highlightbackground=BORDER)
        preview.pack(fill="x", padx=32, pady=(14, 0))
        tk.Label(preview, text="미리보기", bg=BG2, fg=FG_DIM,
                 font=(theme.FONT_FAMILY, 8)).pack(anchor="w", padx=14, pady=(10, 2))
        preview_lbl = tk.Label(preview, text="", bg=BG2, fg=FG, font=(theme.FONT_FAMILY, 12))
        preview_lbl.pack(anchor="w", padx=14, pady=(0, 12))

        def _apply(*_):
            if mode.get() == "custom":
                custom.pack(fill="x", padx=32, pady=(0, 4), before=preview)
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

    def _build_model_mgmt_tab(self, parent):
        """다운로드된 모델 캐시 관리 탭."""
        import pathlib, os, shutil

        self._settings_title(parent, "모델 관리",
                             "내려받은 음성 인식·화자 분석 모델이에요. 안 쓰는 모델은 지워서 공간을 확보하세요.")

        # 목록 영역
        list_frame = tk.Frame(parent, bg=BG2, height=300,
                              highlightthickness=1, highlightbackground=BORDER)
        list_frame.pack(fill="x", padx=32, pady=(0, 10))
        list_frame.pack_propagate(False)

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
                tk.Checkbutton(row, variable=var, bg=BG2, fg=FG,
                               selectcolor=BG3, activebackground=BG2,
                               cursor="hand2").pack(side="left", padx=(6, 0))
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
        btn_row.pack(fill="x", padx=32, pady=(0, 20))
        flat_button(btn_row, "↻  새로고침", _refresh, bg=BG3, hover="#33333C",
                    padx=14, pady=6).pack(side="left")
        _del_btn = flat_button(btn_row, "선택 삭제", _delete_selected, bg="#5A2A2E",
                               fg="#FFD8D8", hover="#6E3438", padx=14, pady=6)
        _del_btn.pack(side="left", padx=(8, 0))

        _refresh()
