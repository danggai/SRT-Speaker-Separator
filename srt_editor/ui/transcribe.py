"""자막 자동 생성(음성 인식)과 고유명사 사전."""
import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox

from .. import model_download, theme
from ..config import _add_recent_token, _load_config, _save_config
from ..srt_io import format_srt_time
from ..speech import (
    _ASR_MODES,
    _DEFAULT_ASR_MODE,
    _DIARIZE_BATCH_MAP,
    _diarize_exclusive,
    _friendly_transcribe_error,
    _load_asr_model,
    _split_segments_by_speaker,
)
from ..theme import ACCENT, BG, BG2, BG3, BORDER, FG, FG_DIM, FG_HINT, _apply_dark_titlebar
from ..widgets import (DarkScrollbar, NumberStepper, PurpleSlider, Segmented, ToggleSwitch, _gradient_bar_rows,
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
        _, right = self._settings_row(card, "#", "화자 수", "0이면 자동으로 정해요")
        if not hasattr(self, "_diarize_num_spk"):
            self._diarize_num_spk = tk.IntVar(value=getattr(self, "_diarize_num_spk_val", 0))
        NumberStepper(right, self._diarize_num_spk, 0, 20).pack()
        _, right = self._settings_row(card, "=", "정확히 이 인원",
                                      "끄면 '최대 N명'으로 제한해요 (출연자 수를 대략만 알 때 권장)")
        if not hasattr(self, "_diarize_spk_exact_var"):
            self._diarize_spk_exact_var = tk.BooleanVar(
                value=getattr(self, "_diarize_spk_exact_init", False))
        ToggleSwitch(right, self._diarize_spk_exact_var).pack()

        sens_holder = tk.Frame(diar_holder, bg=BG)
        sens_anchor = tk.Frame(diar_holder, bg=BG)
        sens_anchor.pack()
        card = self._settings_card(sens_holder, "분리 민감도")
        left, right = self._settings_row(
            card, "~", "분리 민감도",
            "50 = 모델 기본값. 한 사람이 여러 화자로 쪼개지면 낮추고, 다른 사람이 합쳐지면 높이세요")
        if not hasattr(self, "_diarize_sensitivity_var"):
            self._diarize_sensitivity_var = tk.IntVar(
                value=getattr(self, "_diarize_sensitivity_init", 50))
        sens_val = tk.Label(right, text=str(int(self._diarize_sensitivity_var.get())), bg=BG2, fg=FG,
                            width=4, font=(theme.FONT_FAMILY, 10, "bold"))
        sens_val.pack()

        def _sens_cmd(v):
            self._diarize_sensitivity_var.set(int(v))
            sens_val.configure(text=str(int(v)))
        PurpleSlider(left, from_=0, to=100, value=self._diarize_sensitivity_var.get(), width=340,
                     command=_sens_cmd, bg=BG2).pack(anchor="w", pady=(8, 0))

        def _sens_visibility():
            num, exact = self._get_diarize_spk_settings()
            if num > 0 and exact:
                sens_holder.pack_forget()
            else:
                sens_holder.pack(fill="x", before=sens_anchor)
        _watch(sens_holder, self._diarize_num_spk, _sens_visibility)
        _watch(sens_holder, self._diarize_spk_exact_var, _sens_visibility)
        _sens_visibility()

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

        if not hasattr(self, "_transcribe_spellcheck_var"):
            self._transcribe_spellcheck_var = tk.BooleanVar(value=getattr(self, "_transcribe_spellcheck", False))

        def _save_spell():
            self._transcribe_spellcheck = self._transcribe_spellcheck_var.get()
            cfg = _load_config(); cfg["transcribe_spellcheck"] = self._transcribe_spellcheck; _save_config(cfg)
        _, right = self._settings_row(card, "✔", "맞춤법 검사", "네이버 맞춤법 검사기 사용 (인터넷 필요)")
        ToggleSwitch(right, self._transcribe_spellcheck_var, _save_spell).pack()

        def _start():
            hf_tok = hf_tok_var.get().strip()
            if mode_var.get() == "diarize" and not hf_tok:
                messagebox.showwarning("토큰 필요",
                    "화자 분리에는 HuggingFace 토큰이 필요합니다.", parent=win)
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

    def _offer_whisperx_autoinstall(self, retry_fn):
        """whisperx가 설치되어 있지 않을 때 자동 설치를 제안하고, 동의해서
        설치가 완료되면 원래 하려던 작업(retry_fn)을 자동으로 이어서
        실행한다. 거부하거나 설치에 실패하면 조용히 끝난다(별도 안내는
        설치 실패 메시지로 대체)."""
        ans = messagebox.askyesno(
            "설치 필요",
            "자동 자막 생성/화자 분석에 필요한 whisperx 패키지가\n"
            "설치되어 있지 않습니다.\n\n"
            "지금 자동으로 설치할까요?\n"
            "(인터넷 연결 필요, 수 분 소요될 수 있습니다)\n\n"
            "설치가 끝나면 하던 작업을 자동으로 이어서 진행합니다.",
            parent=self)
        if not ans:
            return

        inst_win = tk.Toplevel(self)
        _apply_dark_titlebar(inst_win)
        inst_win.title("whisperx 설치 중...")
        inst_win.configure(bg=BG)
        inst_win.geometry("420x120")
        inst_win.resizable(False, False)
        inst_win.transient(self)
        inst_win.grab_set()
        tk.Label(inst_win, text="⏳  whisperx 설치 중...",
                 bg=BG, fg=FG, font=(theme.FONT_FAMILY, 10, "bold")).pack(pady=(24, 6))
        tk.Label(inst_win, text="pip install 실행 중 (수 분 소요될 수 있습니다)",
                 bg=BG, fg=FG_DIM, font=(theme.FONT_FAMILY, 8)).pack()
        inst_win.update()

        def _do_install():
            ok = False
            err_text = ""
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", "whisperx", "-q"])
                ok = True
            except subprocess.CalledProcessError:
                try:
                    subprocess.check_call(
                        [sys.executable, "-m", "pip", "install", "whisperx", "-q", "--user"])
                    ok = True
                except subprocess.CalledProcessError as e2:
                    err_text = str(e2)
            except Exception as e:
                err_text = str(e)

            def _finish():
                try: inst_win.destroy()
                except Exception: pass
                if ok:
                    # 감지된 설치 완료 → 하던 작업을 자동으로 이어서 실행
                    retry_fn()
                else:
                    messagebox.showerror(
                        "설치 실패",
                        "whisperx 자동 설치에 실패했습니다.\n\n"
                        "수동으로 설치 후 다시 시도해주세요:\n"
                        "pip install whisperx\n\n"
                        f"(오류: {err_text[:200]})", parent=self)
            self.after(0, _finish)

        threading.Thread(target=_do_install, daemon=True).start()

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
                import whisperx, torch, os as _os

                _dev_var = getattr(self, "_diarize_device_var", None)
                _dev_pref = _dev_var.get() if _dev_var else "auto"
                device = "cuda" if (torch.cuda.is_available() and _dev_pref != "cpu") else "cpu"
                _mode_var = getattr(self, "_diarize_mode_var", None)
                _mode = _mode_var.get() if _mode_var else getattr(self, "_diarize_mode_init", _DEFAULT_ASR_MODE)
                _lang = getattr(self, "_transcribe_language", "ko")
                _lang = None if _lang == "auto" else _lang

                def _fetch_model(repo, label, patterns, lo, hi, token=None):
                    """모델이 없으면 내려받으며 진행률(MB, %)을 표시. 이미 있으면 바로 지나감."""
                    def _cb(done, total):
                        pct = lo + (hi - lo) * (done / total) if total else lo
                        self.after(0, lambda: _set(f"{label} 내려받는 중  " + model_download.format_progress(
                            "", done, total).strip(), pct))
                    model_download.download(repo, patterns, token=token, progress=_cb,
                                            cancelled=lambda: _pstate.get("cancelled"))

                _wname = _ASR_MODES.get(_mode, _ASR_MODES[_DEFAULT_ASR_MODE])[0]
                _fetch_model(model_download.whisper_repo(_wname), "음성 인식 모델",
                             model_download.WHISPER_PATTERNS, 3, 14)
                if _pstate.get("cancelled"):
                    return
                _set(f"Whisper 모델 로드 중... ({device})", 14)
                _pn_hint = self._build_proper_noun_hint()
                model, _wmodel = _load_asr_model(whisperx, _mode, device,
                                                 language=_lang, asr_hint=_pn_hint)
                if _pstate.get("cancelled"):
                    return

                _set("음성 로드 중...", 15)
                audio = whisperx.load_audio(media_path)
                if _pstate.get("cancelled"):
                    return

                _set(f"음성 인식 중... ({device} / {_wmodel})", 20)
                if device == "cuda":
                    _bidx = getattr(self, "_diarize_batch_var", None)
                    _bidx = _bidx.get() if _bidx else getattr(self, "_diarize_batch_init", 3)
                    batch_size = _DIARIZE_BATCH_MAP[max(0, min(int(_bidx), len(_DIARIZE_BATCH_MAP) - 1))]
                else:
                    batch_size = 1
                result = model.transcribe(audio, batch_size=batch_size, language=_lang)
                del model
                if device == "cuda": torch.cuda.empty_cache()
                if _pstate.get("cancelled"):
                    return

                _set("타임스탬프 정렬 중...", 60)
                _arepo = model_download.align_repo(result["language"])
                if _arepo:
                    _fetch_model(_arepo, "정렬 모델", None, 60, 64)
                    if _pstate.get("cancelled"):
                        return
                model_a, meta = whisperx.load_align_model(
                    language_code=result["language"], device=device)
                result = whisperx.align(result["segments"], model_a, meta,
                                        audio, device, return_char_alignments=False)
                del model_a
                if device == "cuda": torch.cuda.empty_cache()
                if _pstate.get("cancelled"):
                    return

                segments = result["segments"]

                # 설정값 읽기 (먼저 읽어야 이후 로직에서 참조 가능)
                _max_chars   = getattr(self, "_transcribe_max_chars", 25)
                _add_period  = getattr(self, "_transcribe_period", False)
                _spellcheck  = getattr(self, "_transcribe_spellcheck", False)

                # 맞춤법 검사기 초기화 (활성화 시)
                _spell_checker = None
                if _spellcheck:
                    try:
                        import subprocess as _sp
                        _sp.check_call(
                            [__import__("sys").executable, "-m", "pip",
                             "install", "py-hanspell", "-q"],
                            stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
                        from hanspell import spell_checker as _sc
                        _spell_checker = _sc
                    except Exception:
                        pass

                if with_diarize:
                    _set("화자 분리 중...", 75)
                    hf_tok = hf_token or getattr(self, "_hf_token", "") or _load_config().get("hf_token", "")
                    from whisperx.diarize import DiarizationPipeline, assign_word_speakers
                    _fetch_model(model_download.DIARIZE_REPO, "화자 분리 모델", None, 75, 80, token=hf_tok)
                    if _pstate.get("cancelled"):
                        return
                    diar_model = DiarizationPipeline(token=hf_tok, device=device)
                    self._apply_diarize_sensitivity(diar_model, self._get_diarize_sensitivity())
                    _num_spk, _exact = self._get_diarize_spk_settings()
                    diar_segs  = _diarize_exclusive(diar_model, audio, _num_spk, _exact)
                    del diar_model
                    if device == "cuda": torch.cuda.empty_cache()
                    result2    = assign_word_speakers(diar_segs, result)
                    # 세그먼트 대표 화자 대신 단어별 화자로 세그먼트를 다시 나눈다
                    segments   = _split_segments_by_speaker(result2["segments"])

                if _pstate.get("cancelled"):
                    return

                # segments → SRT 텍스트 생성
                if _spellcheck and _spell_checker:
                    _set("맞춤법 검사 중...", 90)
                _set("자막 변환 중...", 95)


                # 한국어 종결어미(대략적인 문장/절 경계 판단용).
                # 정확한 형태소 분석은 아니지만, 흔한 종결 패턴을 폭넓게
                # 커버해 "글자 수만 꽉 채우고 뚝 끊기"보다 자연스러운
                # 위치에서 줄을 나누기 위한 실용적 휴리스틱.
                _KOR_SENTENCE_ENDERS = (
                    "습니다", "입니다", "합니다", "됩니다", "였습니다", "했습니다",
                    "였다", "했다", "이었다",
                    "이에요", "예요", "이네요", "네요", "군요", "구나", "잖아요", "잖아",
                    "거든요", "거예요", "을까요", "ㄹ까요", "나요", "가요", "까요",
                    "아요", "어요", "해요", "돼요", "됐어요", "했어요", "이었어요", "였어요",
                    "습니까", "합니까", "인가요", "인데요", "는데요", "던데요",
                    "다", "죠", "네", "까", "자", "라", "니",
                )

                def _clause_break_score(word):
                    """word(어절)가 문장/절 경계로 적합한지 대략 판단.
                    2=강함(문장부호로 끝남) / 1=약함(종결어미로 끝남) / 0=경계 아님."""
                    if not word:
                        return 0
                    if word[-1] in ".!?…":
                        return 2
                    core = word.rstrip("\"'”’」』)]")
                    if core and core[-1] in ".!?…":
                        return 2
                    for end in _KOR_SENTENCE_ENDERS:
                        if core.endswith(end):
                            return 1
                    return 0

                def _split_by_chars(text, max_chars):
                    """글자 수 제한 + 문장부호/종결어미 등 의미 단위 경계를 함께
                    고려해 자막 줄을 나눈다. max_chars에 도달하기 직전이라도,
                    그 안에 자연스러운 문장/절 경계(마침표·종결어미 등)가 있으면
                    거기서 먼저 끊어 어색하게 중간에서 잘리는 것을 줄인다."""
                    if len(text) <= max_chars:
                        return [text]
                    words = text.split()
                    if not words:
                        return [text]

                    MIN_RATIO = 0.45   # 이 비율 이상 채워졌을 때만 조기 종결 허용
                    lines = []
                    start = 0
                    n = len(words)
                    while start < n:
                        cur_len   = 0
                        end       = -1   # 여기까지는 확실히 max_chars 안에 들어옴
                        last_good = -1   # 문장 경계로 적합한 마지막 word index
                        i = start
                        while i < n:
                            w = words[i]
                            add_len = len(w) + (1 if i > start else 0)
                            if cur_len + add_len > max_chars:
                                break
                            cur_len += add_len
                            end = i
                            if (_clause_break_score(w) > 0
                                    and cur_len >= max_chars * MIN_RATIO):
                                last_good = i
                            i += 1

                        if end < start:
                            # 단어 하나가 max_chars보다 긴 경우: 강제 분할
                            w = words[start]
                            for ci in range(0, len(w), max_chars):
                                lines.append(w[ci:ci+max_chars])
                            start += 1
                            continue

                        cut = end
                        # 아직 더 이어질 단어가 남아있고, 그 전에 자연스러운
                        # 경계가 있었다면 거기서 끊는다.
                        if last_good >= 0 and last_good < end and (end + 1 < n):
                            cut = last_good

                        lines.append(" ".join(words[start:cut+1]))
                        start = cut + 1

                    return lines if lines else [text]

                def _split_seg_with_words(seg, max_chars, spk):
                    """whisperx word-level 타임스탬프 활용 정밀 분리.
                    words 필드 없으면 균등 시간 분배 fallback."""
                    t_s  = seg.get("start", 0)
                    t_e  = seg.get("end", t_s + 1)
                    text = seg.get("text", "").strip()
                    word_list = seg.get("words", [])  # whisperx 단어별 타임스탬프

                    lines = _split_by_chars(text, max_chars)
                    result = []

                    if len(lines) == 1:
                        result.append({"start": t_s, "end": t_e,
                                        "text": lines[0], "speaker": spk})
                        return result

                    if word_list:
                        # word-level 타임스탬프로 정밀 분리
                        wi = 0
                        for line in lines:
                            line_words = line.split()
                            seg_ws = t_s
                            seg_we = t_e
                            matched = []
                            for lw in line_words:
                                while wi < len(word_list):
                                    wobj = word_list[wi]
                                    wi += 1
                                    matched.append(wobj)
                                    break
                            # 정렬 실패 단어(숫자 등)는 타임스탬프가 없으므로 건너뛴다
                            timed = [m for m in matched if "start" in m and "end" in m]
                            if timed:
                                seg_ws = timed[0]["start"]
                                seg_we = timed[-1]["end"]
                            result.append({"start": seg_ws, "end": seg_we,
                                            "text": line, "speaker": spk})
                    else:
                        # fallback: 글자 수 비례로 시간 분배
                        dur = t_e - t_s
                        total_chars = sum(len(l) for l in lines) or 1
                        cursor = t_s
                        for line in lines:
                            ratio = len(line) / total_chars
                            sub_e = cursor + dur * ratio
                            result.append({"start": cursor, "end": sub_e,
                                            "text": line, "speaker": spk})
                            cursor = sub_e

                    return result

                # 글자 수 기준으로 segments 재분할
                split_segs = []
                for seg in segments:
                    spk = seg.get("speaker", "")
                    split_segs.extend(_split_seg_with_words(seg, _max_chars, spk))

                srt_lines = []
                for i, seg in enumerate(split_segs, 1):
                    t_s  = seg["start"]
                    t_e  = seg["end"]
                    text = seg["text"]
                    spk  = seg["speaker"]
                    # 맞춤법 검사
                    if _spell_checker and text:
                        try:
                            _res = _spell_checker.check(text)
                            text = _res.checked
                        except Exception:
                            pass
                    # 마침표 처리
                    if text:
                        if _add_period:
                            # 활성: 온점/느낌표/물음표 없으면 온점 추가
                            if text[-1] not in "。.!?!?":
                                text += "."
                        else:
                            # 비활성: Whisper가 자동으로 붙인 온점만 제거
                            # (물음표·느낌표는 의미가 있으므로 유지)
                            if text[-1] in ".。":
                                text = text[:-1].rstrip()
                    srt_lines.append(str(i))
                    srt_lines.append(f"{format_srt_time(t_s)} --> {format_srt_time(t_e)}")
                    if spk:
                        srt_lines.append(f"[{spk}] {text}")
                    else:
                        srt_lines.append(text)
                    srt_lines.append("")

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

            except ImportError:
                def _ei():
                    if _pstate.get("cancelled"):
                        return
                    _pstate["run"] = False
                    try: prog.destroy()
                    except Exception: pass
                    self._offer_whisperx_autoinstall(
                        lambda: self._auto_transcribe(media_path, with_diarize, hf_token))
                self.after(0, _ei)
            except Exception as e:
                err = _friendly_transcribe_error(str(e))
                try:
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except Exception:
                    pass
                def _ee():
                    if _pstate.get("cancelled"):
                        return
                    _pstate["run"] = False
                    try: prog.destroy()
                    except Exception: pass
                    messagebox.showerror("오류", err, parent=self)
                self.after(0, _ee)
            finally:
                # 작업이 성공/실패/취소 어떤 경우로 끝나든, 여기서 쓰던
                # 무거운 객체(모델·오디오·인식결과)들을 일괄 해제한다.
                try: del model
                except Exception: pass
                try: del model_a
                except Exception: pass
                try: del diar_model
                except Exception: pass
                try: del audio
                except Exception: pass
                try: del result
                except Exception: pass
                try: del result2
                except Exception: pass
                try: del segments
                except Exception: pass
                try: del diar_segs
                except Exception: pass
                try:
                    import gc
                    gc.collect()
                    import torch as _torch
                    if _torch.cuda.is_available():
                        _torch.cuda.empty_cache()
                        _torch.cuda.ipc_collect()
                except Exception:
                    pass

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
            if not messagebox.askyesno("전부 삭제", "등록된 고유명사를 모두 삭제할까요?", parent=win):
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
