"""자막 자동 생성(음성 인식)과 고유명사 사전."""
import os
import tkinter as tk
from .. import dialogs as messagebox

from .. import theme, transcript_post
from ..config import _add_recent_token, _load_config, _save_config
from ..srt_io import format_srt_time
from ..speech import _DEFAULT_ASR_MODE, _friendly_transcribe_error
from ..theme import ACCENT, BG, BG2, BG3, BORDER, FG, FG_DIM, FG_HINT, _apply_dark_titlebar
from ..widgets import (DarkScrollbar, PurpleSlider, Segmented, ToggleSwitch, _gradient_bar_rows,
                       _watch, flat_button, present_dialog)


class TranscribeMixin:
    """자막 자동 생성(음성 인식)과 고유명사 사전."""

    def _ask_auto_transcribe(self, media_path):
        """자막 자동 생성 여부 및 방식 선택 창 (설정창과 같은 카드 스타일)."""
        win = tk.Toplevel(self)
        win.withdraw()
        win.title("자막 자동 생성")
        win.configure(bg=BG)
        win.geometry("580x700")
        win.minsize(500, 460)
        win.transient(self)
        outer, inner, footer = self._make_scrollable(win, with_footer=True)
        outer.pack(fill="both", expand=True)
        self._settings_title(inner, "자막 자동 생성",
                             f"{os.path.basename(media_path)}\n같은 이름의 SRT 파일이 없어요. 자동으로 만들까요?")

        mode_var = tk.StringVar(value="text")
        card = self._settings_card(inner, "생성 방식")
        left, _ = self._settings_row(card, "▶", "어떻게 만들까요",
                                     "화자 분리까지 하면 화자도 자동으로 나눠요 (HuggingFace 토큰 필요)")
        Segmented(left, [("텍스트만 (빠름)", "text"), ("화자 분리까지 (느림)", "diarize")],
                  mode_var).pack(anchor="w", pady=(10, 0))

        # 화자 분리 설정 (방식이 '화자 분리까지'일 때만 보임)
        diar_holder = tk.Frame(inner, bg=BG)
        diar_anchor = tk.Frame(inner, bg=BG)
        diar_anchor.pack()
        hf_tok_var = tk.StringVar(value=getattr(self, "_hf_token", "") or _load_config().get("hf_token", ""))
        card = self._settings_card(diar_holder, "화자 분리")
        left, _ = self._settings_row(card, "K", "HuggingFace 토큰", "화자 분리 모델을 내려받을 때 필요해요")
        self._hf_token_row(left, hf_tok_var).pack(fill="x", pady=(8, 0))
        self._speaker_count_rows(card)

        def _on_mode_change():
            if mode_var.get() == "diarize":
                diar_holder.pack(fill="x", before=diar_anchor)
            else:
                diar_holder.pack_forget()
        _watch(diar_holder, mode_var, _on_mode_change)

        # ── 자막 설정 ────────────────────────────────────────
        card = self._settings_card(inner, "자막 설정")
        if not hasattr(self, "_transcribe_max_chars_var"):
            self._transcribe_max_chars_var = tk.IntVar(value=getattr(self, "_transcribe_max_chars", 25))
        _CS_MIN, _CS_MAX = 10, 50
        left, right = self._settings_row(card, "가", "문장 당 글자 수", "한 자막에 들어갈 최대 글자 수")
        cs_text = tk.StringVar(value=str(self._transcribe_max_chars_var.get()))
        tk.Label(right, text="자", bg=BG2, fg=FG_DIM, font=(theme.FONT_FAMILY, 9)).pack(side="right", padx=(4, 0))
        cs_entry = tk.Entry(right, textvariable=cs_text, width=4, bg=BG3, fg=FG, insertbackground=FG,
                            justify="center", relief="flat", highlightthickness=1,
                            highlightbackground=BORDER, highlightcolor=ACCENT,
                            font=(theme.FONT_FAMILY, 10))
        cs_entry.pack(side="right", ipady=3)

        def _cs_save():
            try:
                v = int(self._transcribe_max_chars_var.get())
                self._transcribe_max_chars = v
                cs_text.set(str(v))
                cfg = _load_config(); cfg["transcribe_max_chars"] = v; _save_config(cfg)
            except Exception:
                pass
        _cs_save()

        def _cs_slider_cmd(v):
            self._transcribe_max_chars_var.set(int(v))
            _cs_save()
        cs_slider = PurpleSlider(left, from_=_CS_MIN, to=_CS_MAX, value=self._transcribe_max_chars_var.get(),
                                 width=340, command=_cs_slider_cmd, bg=BG2)
        cs_slider.pack(anchor="w", pady=(8, 0))

        def _cs_entry_commit(*_):
            try:
                v = int(cs_text.get())
            except Exception:
                v = self._transcribe_max_chars_var.get()
            v = max(_CS_MIN, min(_CS_MAX, v))
            self._transcribe_max_chars_var.set(v)
            cs_slider.set(v, fire=False)
            _cs_save()
        cs_entry.bind("<Return>", _cs_entry_commit)
        cs_entry.bind("<FocusOut>", _cs_entry_commit)

        if not hasattr(self, "_diarize_device_var"):
            self._diarize_device_var = tk.StringVar(value=getattr(self, "_diarize_device_init", "auto"))
        _, right = self._settings_row(card, "◉", "처리 장치", "GPU 우선: CUDA 가능하면 GPU, 아니면 CPU로 자동 전환")
        Segmented(right, [("GPU 우선", "auto"), ("CPU", "cpu")], self._diarize_device_var).pack()

        if not hasattr(self, "_diarize_mode_var"):
            self._diarize_mode_var = tk.StringVar(value=getattr(self, "_diarize_mode_init", _DEFAULT_ASR_MODE))
        left, _ = self._settings_row(card, "◆", "인식 모드", "텍스트만·화자 분리 모두에 적용돼요")
        Segmented(left, [("빠름", "fast"), ("균형", "balanced"), ("정확", "accurate"), ("최고 정확", "best")],
                  self._diarize_mode_var).pack(anchor="w", pady=(10, 0))
        mode_hint = tk.Label(left, bg=BG2, fg=FG_HINT, font=(theme.FONT_FAMILY, 9), anchor="w")
        mode_hint.pack(fill="x", pady=(6, 0))

        def _mode_hint_upd():
            mode_hint.configure(text="CPU에서는 '균형' 권장 ('정확'·'최고 정확'은 매우 느릴 수 있어요)"
                                if self._diarize_device_var.get() == "cpu"
                                else "GPU에서는 '정확' 권장 ('최고 정확'은 짧은 추임새까지 잡아요)")
        _watch(mode_hint, self._diarize_device_var, _mode_hint_upd)
        _mode_hint_upd()

        lang_var = tk.StringVar(value=getattr(self, "_transcribe_language", "ko"))

        def _save_lang():
            self._transcribe_language = lang_var.get()
            cfg = _load_config(); cfg["transcribe_language"] = lang_var.get(); _save_config(cfg)
        _, right = self._settings_row(card, "A", "인식 언어")
        Segmented(right, [("한국어 고정 (권장)", "ko"), ("자동 감지", "auto")], lang_var, _save_lang).pack()

        if not hasattr(self, "_transcribe_period_var"):
            self._transcribe_period_var = tk.BooleanVar(value=getattr(self, "_transcribe_period", False))

        def _save_period():
            self._transcribe_period = self._transcribe_period_var.get()
            cfg = _load_config(); cfg["transcribe_period"] = self._transcribe_period; _save_config(cfg)
        _, right = self._settings_row(card, ".", "문장 끝 마침표")
        ToggleSwitch(right, self._transcribe_period_var, _save_period).pack()

        def _start():
            hf_tok = hf_tok_var.get().strip()
            if mode_var.get() == "diarize" and not hf_tok:
                messagebox.showwarning("자막 생성", "HuggingFace 토큰을 입력해 주세요.", parent=win)
                return
            _cfg = _load_config()
            if hf_tok:
                self._hf_token = hf_tok
                _cfg["hf_token"] = hf_tok
                _add_recent_token(_cfg, hf_tok)
            # 화자 수·모드·민감도 저장
            _num, _exact = self._get_diarize_spk_settings()
            _cfg["num_speakers"]        = _num
            _cfg["diarize_spk_exact"]   = _exact
            _cfg["diarize_mode"]        = self._diarize_mode_var.get()
            _cfg["diarize_device"]      = self._diarize_device_var.get()
            _cfg["diarize_sensitivity"] = self._get_diarize_sensitivity()
            _cfg["diarize_sens_scale"]  = 2
            _save_config(_cfg)
            win.destroy()
            self._auto_transcribe(media_path, with_diarize=(mode_var.get() == "diarize"),
                                   hf_token=hf_tok)

        btn_row = tk.Frame(footer, bg=BG)
        btn_row.pack(fill="x", padx=24, pady=(12, 14))
        flat_button(btn_row, "생성 시작", _start, bg=ACCENT, fg="white", hover="#AE96E2",
                    font=(theme.FONT_FAMILY, 10, "bold"), padx=22, pady=8).pack(side="right")
        flat_button(btn_row, "취소", win.destroy, bg=BG3, hover="#33333C",
                    font=(theme.FONT_FAMILY, 10), padx=18, pady=8).pack(side="right", padx=(0, 8))
        present_dialog(win, self)

    def _auto_transcribe(self, media_path, with_diarize=False, hf_token=""):
        """Whisper로 자막 자동 생성 후 임시 로드 (파일 저장 안 함)."""
        import threading

        # ── 진행 창 ──────────────────────────────────────────────
        prog = tk.Toplevel(self)
        _apply_dark_titlebar(prog)
        prog.title("자막 자동 생성 중...")
        prog.configure(bg=BG)
        prog.geometry("440x240")
        prog.resizable(False, False)
        prog.transient(self)
        prog.grab_set()

        tk.Label(prog, text="🎙  자막 자동 생성 중...",
                 bg=BG, fg=FG, font=(theme.FONT_FAMILY, 11, "bold")).pack(pady=(18, 2))
        _status = tk.Label(prog, text="초기화 중...",
                           bg=BG, fg=FG, font=(theme.FONT_FAMILY, 9, "bold"))
        _status.pack()
        _sub = tk.Label(prog, text="", bg=BG, fg=FG_DIM, font=(theme.FONT_FAMILY, 8))
        _sub.pack(pady=(1, 0))

        BAR_W, BAR_H = 380, 16
        _bar_cv = tk.Canvas(prog, width=BAR_W, height=BAR_H,
                            bg=BG3, highlightthickness=1, highlightbackground=BORDER)
        _bar_cv.pack(pady=(10, 4))
        _bar_img = tk.PhotoImage(width=BAR_W, height=BAR_H)
        _bar_cv.create_image(0, 0, anchor="nw", image=_bar_img)
        _pct_id = _bar_cv.create_text(BAR_W//2, BAR_H//2, text="0%",
                                       fill=FG_DIM, font=(theme.FONT_FAMILY, 7, "bold"))

        _pstate = {"target": 0.0, "cur": 0.0, "phase": 0.0, "run": True, "cancelled": False}

        def _cancel(*_):
            """중단 버튼 또는 창 닫기(X) — 음성인식을 취소한다.
            실행 중인 whisper 연산 자체를 즉시 강제 종료할 수는 없지만
            (라이브러리가 중간에 끊는 기능을 제공하지 않음), 취소 플래그를
            세워 결과가 나와도 화면에 반영하지 않고, 진행 창을 바로 닫아
            사용자가 더 기다리지 않도록 한다."""
            if _pstate.get("cancelled"):
                return
            _pstate["cancelled"] = True
            _pstate["run"] = False
            try: prog.destroy()
            except Exception: pass

        prog.protocol("WM_DELETE_WINDOW", _cancel)

        tk.Button(prog, text="중단", bg="#3A2A2A", fg="#E08080",
                  relief="flat", bd=0, cursor="hand2",
                  font=(theme.FONT_FAMILY, 9), padx=14, pady=4,
                  activebackground="#4A3232",
                  command=_cancel).pack(pady=(8, 4))

        def _draw():
            if not _pstate["run"]: return
            try:
                cur = _pstate["cur"]; phase = _pstate["phase"]
                fw = int(BAR_W * cur / 100)
                _bar_img.put(_gradient_bar_rows(BAR_W, BAR_H, fw, phase, BG3))
                _bar_cv.itemconfigure(_pct_id, text=f"{int(cur)}%",
                    fill="white" if fw > BAR_W//2 else FG_DIM)
                _pstate["phase"] += 0.18
                diff = _pstate["target"] - cur
                _pstate["cur"] += diff*0.07 if abs(diff)>0.05 else diff
                prog.after(30, _draw)
            except Exception: pass
        prog.after(30, _draw)

        def _set(msg, pct=None):
            try:
                _status.configure(text=msg)
                if pct is not None:
                    _pstate["target"] = float(pct)
            except Exception: pass

        # ── 워커 ─────────────────────────────────────────────────
        def _worker():
            try:
                import os as _os
                _mode_var = getattr(self, "_diarize_mode_var", None)
                _mode = _mode_var.get() if _mode_var else getattr(self, "_diarize_mode_init", _DEFAULT_ASR_MODE)
                _lang = getattr(self, "_transcribe_language", "ko")
                _lang = None if _lang == "auto" else _lang
                _bidx = getattr(self, "_diarize_batch_var", None)
                _bidx = _bidx.get() if _bidx else getattr(self, "_diarize_batch_init", 3)
                _cancelled = lambda: _pstate.get("cancelled")

                def _on_ev(ev, lo=0.0, hi=100.0):
                    if ev.get("type") == "status":
                        msg, pct = ev.get("msg", ""), ev.get("pct")
                        pct = None if pct is None else lo + (hi - lo) * float(pct) / 100.0
                        self.after(0, lambda: _set(msg, pct))

                res = self._run_ai_job({"type": "transcribe", "media": media_path, "mode": _mode,
                                        "language": _lang, "asr_hint": self._build_proper_noun_hint(),
                                        "batch": _bidx},
                                       on_event=lambda ev: _on_ev(ev, 0, 72 if with_diarize else 90),
                                       cancelled=_cancelled)
                if _cancelled():
                    return
                segments = res["segments"]

                self.after(0, lambda: _set("자막 줄 나누는 중...", 72 if with_diarize else 92))
                split_segs = transcript_post.build_lines(
                    segments, getattr(self, "_transcribe_max_chars", 25), getattr(self, "_transcribe_period", False))

                _auto = None
                if with_diarize and split_segs:
                    _num_spk, _exact = self._get_diarize_spk_settings()
                    hf_tok = hf_token or getattr(self, "_hf_token", "") or _load_config().get("hf_token", "")
                    dres = self._run_ai_job(
                        {"type": "diarize", "media": media_path, "hf_token": hf_tok,
                         "intervals": [[sg["start"], sg["end"]] for sg in split_segs],
                         "num_speakers": _num_spk, "exact": _exact,
                         "sensitivity": self._get_diarize_sensitivity()},
                        on_event=lambda ev: _on_ev(ev, 72, 94), cancelled=_cancelled)
                    if _cancelled():
                        return
                    for sg, lab in zip(split_segs, dres["labels"]):
                        sg["speaker"] = f"화자 {lab + 1}" if lab >= 0 else ""
                    _auto = dres["conf"]

                srt_lines = []
                for i, seg in enumerate(split_segs, 1):
                    srt_lines += [str(i), f"{format_srt_time(seg['start'])} --> {format_srt_time(seg['end'])}",
                                  f"[{seg['speaker']}] {seg['text']}" if seg["speaker"] else seg["text"], ""]

                srt_content = "\n".join(srt_lines)

                # 임시 파일로 로드
                import tempfile
                with tempfile.NamedTemporaryFile(
                        mode="w", encoding="utf-8", suffix=".srt",
                        delete=False) as tf:
                    tf.write(srt_content)
                    tmp_path = tf.name

                _pstate["target"] = 100.0

                def _done():
                    if _pstate.get("cancelled"):
                        try: _os.remove(tmp_path)
                        except Exception: pass
                        return
                    _pstate["run"] = False
                    try: prog.destroy()
                    except Exception: pass
                    self._load_srt(tmp_path)
                    try:   # 불러왔으니 임시 파일은 지움
                        _os.remove(tmp_path)
                    except OSError:
                        pass
                    if _auto is not None and len(_auto) == len(self.subtitles):
                        self._mark_auto_speakers(range(len(self.subtitles)), _auto)
                    # 저장 경로를 원본 미디어 파일과 같은 이름/위치로 미리 지정
                    # (예: movie.mp4 → movie.srt). 아직 그 경로에 실제로 쓰여진
                    # 것은 아니므로 미저장 상태로 표시해, 저장(Ctrl+S) 한 번이면
                    # 바로 그 이름으로 저장되도록 한다.
                    _media_dir  = _os.path.dirname(media_path)
                    _base = _os.path.splitext(_os.path.basename(media_path))[0]
                    self.save_path = _os.path.join(_media_dir, _base + ".srt")
                    self.filepath  = self.save_path
                    self._unsaved  = True
                    self._set_doc_title(_base)
                self.after(0, _done)

            except Exception as e:
                err = _friendly_transcribe_error(str(e))
                def _ee():
                    if _pstate.get("cancelled"):
                        return
                    _pstate["run"] = False
                    try: prog.destroy()
                    except Exception: pass
                    messagebox.showerror("오류", err, parent=self)
                self.after(0, _ee)

        threading.Thread(target=_worker, daemon=True).start()

    # ── 고유명사 사전 (자동 자막 인식 가중치, 수동 등록/관리) ─────────
    def _ensure_proper_nouns_init(self):
        """self._proper_nouns / _proper_nouns_enabled가 어떤 이유로든 아직
        없다면 안전한 기본값으로 지연 초기화한다 (구버전 파일 등과의 호환용
        방어 코드 — 정상적으로는 __init__에서 이미 설정되어 있다)."""
        if not hasattr(self, "_proper_nouns") or self._proper_nouns is None:
            self._proper_nouns = []
        if not hasattr(self, "_proper_nouns_enabled"):
            self._proper_nouns_enabled = True

    def _save_proper_nouns(self):
        """고유명사 사전을 config에 저장."""
        self._ensure_proper_nouns_init()
        cfg = _load_config()
        cfg["proper_nouns"] = self._proper_nouns
        cfg["proper_nouns_enabled"] = getattr(self, "_proper_nouns_enabled", True)
        _save_config(cfg)

    def _add_proper_noun(self, word):
        """고유명사를 사전에 등록 (수동 등록 전용, 이미 있으면 무시)."""
        self._ensure_proper_nouns_init()
        word = (word or "").strip()
        if not word or word in self._proper_nouns:
            return False
        self._proper_nouns.append(word)
        self._save_proper_nouns()
        return True

    def _remove_proper_noun(self, word):
        self._ensure_proper_nouns_init()
        if word in self._proper_nouns:
            self._proper_nouns.remove(word)
            self._save_proper_nouns()

    def _build_proper_noun_hint(self):
        """등록된 고유명사 사전을 Whisper asr_options(hotwords/initial_prompt)로 변환.
        등록된 단어는 항상(무조건) 반영된다."""
        self._ensure_proper_nouns_init()
        words = list(getattr(self, "_proper_nouns", None) or [])
        if not words:
            return {}
        # 문장형 프롬프트는 자막에 새어 나와 단어만 나열
        joined = ", ".join(words)
        opts = {"hotwords": " ".join(words),
                "initial_prompt": joined}
        return opts

    def _open_proper_noun_manager(self, on_close=None):
        """고유명사 사전 관리 창."""
        self._ensure_proper_nouns_init()
        win = tk.Toplevel(self)
        win.withdraw()
        win.title("고유명사 사전")
        win.configure(bg=BG)
        win.geometry("440x560")
        win.minsize(380, 440)
        win.transient(self)

        tk.Label(win, text="고유명사 사전", bg=BG, fg=FG,
                 font=(theme.FONT_FAMILY, 15, "bold")).pack(anchor="w", padx=24, pady=(22, 2))
        tk.Label(win, text="등록한 단어는 자동 자막에서 더 잘 알아들어요.", bg=BG, fg=FG_DIM,
                 font=(theme.FONT_FAMILY, 9)).pack(anchor="w", padx=24, pady=(0, 12))

        foot = tk.Frame(win, bg=BG)
        foot.pack(side="bottom", fill="x", padx=24, pady=(6, 18))
        del_row = tk.Frame(win, bg=BG)
        del_row.pack(side="bottom", fill="x", padx=24, pady=(0, 6))
        add_row = tk.Frame(win, bg=BG)
        add_row.pack(side="bottom", fill="x", padx=24, pady=(10, 8))

        card = tk.Frame(win, bg=BG2, highlightthickness=1, highlightbackground=BORDER)
        card.pack(fill="both", expand=True, padx=24)
        scrollbar = DarkScrollbar(card)
        scrollbar.pack(side="right", fill="y", padx=(0, 2), pady=2)
        lb = tk.Listbox(card, bg=BG2, fg=FG, selectbackground=theme.ON_BG, selectforeground=theme.ON_FG,
                        relief="flat", bd=0, highlightthickness=0, activestyle="none",
                        font=(theme.FONT_FAMILY, 10), selectmode="extended",   # Shift/Ctrl 클릭으로 다중 선택
                        yscrollcommand=scrollbar.set)
        lb.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=4)
        scrollbar.configure(command=lb.yview)
        empty = tk.Label(card, text="아직 등록한 단어가 없어요.\n아래에 단어를 입력하고 Enter를 눌러 보세요.",
                         bg=BG2, fg=theme.FG_HINT, justify="center", font=(theme.FONT_FAMILY, 9))

        def _sorted_items():
            return sorted(self._proper_nouns)

        def _refresh():
            lb.delete(0, "end")
            for w in _sorted_items():
                lb.insert("end", f"  {w}")
            if self._proper_nouns:
                empty.place_forget()
            else:
                empty.place(relx=0.5, rely=0.45, anchor="center")
        _refresh()

        new_var = tk.StringVar()
        entry = tk.Entry(add_row, textvariable=new_var, bg=BG3, fg=FG, insertbackground=FG, relief="flat",
                         highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT,
                         font=(theme.FONT_FAMILY, 10))
        entry.pack(side="left", fill="x", expand=True, ipady=5)

        def _add(*_):
            w = new_var.get().strip()
            if not w:
                return
            self._add_proper_noun(w)
            new_var.set("")
            _refresh()
        entry.bind("<Return>", _add)
        flat_button(add_row, "추가", _add, bg=ACCENT, fg="white", hover="#AE96E2",
                    font=(theme.FONT_FAMILY, 10, "bold"), padx=18, pady=6).pack(side="left", padx=(8, 0))

        def _delete(*_):
            sel = lb.curselection()
            if not sel:
                return
            items = _sorted_items()
            for w in [items[i] for i in sel if i < len(items)]:
                self._remove_proper_noun(w)
            _refresh()
        flat_button(del_row, "선택 삭제", _delete, bg=BG3, hover="#33333C", padx=14, pady=5).pack(side="left")

        def _delete_all(*_):
            if not self._proper_nouns:
                return
            if not messagebox.askyesno("고유명사 삭제", "등록된 고유명사를 모두 지울까요?", parent=win, yes="삭제", no="취소"):
                return
            self._proper_nouns.clear()
            self._save_proper_nouns()
            _refresh()
        flat_button(del_row, "전부 삭제", _delete_all, bg="#5A2A2E", fg="#FFD8D8", hover="#6E3438",
                    padx=14, pady=5).pack(side="left", padx=(8, 0))

        def _close():
            if on_close:
                try:
                    on_close()
                except Exception:
                    pass
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", _close)
        flat_button(foot, "닫기", _close, bg=BG3, hover="#33333C", font=(theme.FONT_FAMILY, 10),
                    padx=22, pady=7).pack(side="right")
        present_dialog(win, self)
        entry.focus_set()
