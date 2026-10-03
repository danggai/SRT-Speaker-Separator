"""자막 자동 생성(음성 인식)과 고유명사 사전."""
import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox

from .. import theme
from ..config import _add_recent_token, _load_config, _save_config
from ..speech import (
    _DEFAULT_ASR_MODE,
    _DIARIZE_BATCH_MAP,
    _diarize_exclusive,
    _friendly_transcribe_error,
    _load_asr_model,
    _split_segments_by_speaker,
)
from ..theme import ACCENT, BG, BG2, BG3, BORDER, FG, FG_DIM, FONT_MONO, _apply_dark_titlebar
from ..widgets import PurpleSlider, _gradient_bar_rows


class TranscribeMixin:
    """자막 자동 생성(음성 인식)과 고유명사 사전."""

    def _ask_auto_transcribe(self, media_path):
        """자막 자동 생성 여부 및 방식 선택 팝업."""
        win = tk.Toplevel(self)
        _apply_dark_titlebar(win)
        win.title("자막 자동 생성")
        win.configure(bg=BG)
        win.geometry("420x490")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()

        tk.Label(win, text="🎙  자막 자동 생성",
                 bg=BG, fg=FG, font=(theme.FONT_FAMILY, 11, "bold")).pack(pady=(16, 4))
        tk.Label(win,
                 text=f"{os.path.basename(media_path)}\n\ub3d9\uc77c\ud55c SRT \ud30c\uc77c\uc774 \uc5c6\uc2b5\ub2c8\ub2e4. \uc790\ub3d9 \uc0dd\uc131\ud560\uae4c\uc694?",
                 bg=BG, fg=FG_DIM, font=(theme.FONT_FAMILY, 9), justify="center").pack(pady=(0, 10))

        mode_var = tk.StringVar(value="text")
        mode_row = tk.Frame(win, bg=BG)
        mode_row.pack()
        tk.Radiobutton(mode_row, text="텍스트만  (빠름)",
                       variable=mode_var, value="text",
                       bg=BG, fg=FG, selectcolor=BG3,
                       activebackground=BG, font=(theme.FONT_FAMILY, 9)).pack(side="left", padx=8)
        tk.Radiobutton(mode_row, text="화자 분리까지  (느림)",
                       variable=mode_var, value="diarize",
                       bg=BG, fg=FG, selectcolor=BG3,
                       activebackground=BG, font=(theme.FONT_FAMILY, 9)).pack(side="left", padx=8)

        # ── 화자 분리 설정 패널 (diarize 선택 시 표시) ──────────
        _saved_tok = getattr(self, "_hf_token", "") or _load_config().get("hf_token", "")
        hf_tok_var = tk.StringVar(value=_saved_tok)

        diar_frame = tk.Frame(win, bg=BG)

        # HF 토큰
        _tok_row = tk.Frame(diar_frame, bg=BG)
        _tok_row.pack(fill="x", padx=10, pady=(8, 4))
        tk.Label(_tok_row, text="HuggingFace 토큰", bg=BG, fg=FG_DIM,
                 font=(theme.FONT_FAMILY, 8), width=16, anchor="w").pack(side="left")
        tok_entry = tk.Entry(_tok_row, textvariable=hf_tok_var, show="*",
                             bg=BG3, fg=FG, insertbackground=FG,
                             font=(FONT_MONO, 8), relief="flat",
                             highlightthickness=1, highlightbackground=BORDER,
                             highlightcolor=ACCENT)
        tok_entry.pack(side="left", fill="x", expand=True, ipady=2)
        # 👁 토큰 표시 토글
        def _tog_tok():
            tok_entry.configure(show="" if tok_entry.cget("show") == "*" else "*")
        tk.Button(_tok_row, text="👁", bg=BG, fg=FG_DIM, relief="flat", bd=0,
                  font=(theme.FONT_FAMILY, 9), padx=4, cursor="hand2",
                  activebackground=BG3, command=_tog_tok).pack(side="left", padx=(4,0))

        # 화자 수
        _spk_row = tk.Frame(diar_frame, bg=BG)
        _spk_row.pack(fill="x", padx=10, pady=(0, 4))
        tk.Label(_spk_row, text="화자 수 (0=자동)", bg=BG, fg=FG_DIM,
                 font=(theme.FONT_FAMILY, 8), width=16, anchor="w").pack(side="left")
        if not hasattr(self, "_diarize_num_spk"):
            self._diarize_num_spk = tk.IntVar(
                value=getattr(self, "_diarize_num_spk_val", 0))
        tk.Spinbox(_spk_row, from_=0, to=20, textvariable=self._diarize_num_spk,
                   bg=BG3, fg=FG, insertbackground=FG, buttonbackground=BG3,
                   relief="flat", highlightthickness=1, highlightbackground=BORDER,
                   font=(theme.FONT_FAMILY, 8), width=5).pack(side="left")
        if not hasattr(self, "_diarize_spk_exact_var"):
            self._diarize_spk_exact_var = tk.BooleanVar(
                value=getattr(self, "_diarize_spk_exact_init", False))
        tk.Checkbutton(_spk_row, variable=self._diarize_spk_exact_var,
                       text="정확히 이 인원 (해제 시 최대 인원)",
                       bg=BG, fg=FG_DIM, selectcolor=BG3, activebackground=BG,
                       font=(theme.FONT_FAMILY, 8), cursor="hand2").pack(side="left", padx=(8, 0))

        # 화자 분리 민감도 — 높을수록 화자를 더 잘게(예민하게) 구분
        # 인원을 정확히 고정했을 때는 민감도가 의미 없으므로 슬라이더를 숨긴다.
        _sens_row = tk.Frame(diar_frame, bg=BG)
        tk.Label(_sens_row, text="분리 민감도", bg=BG, fg=FG_DIM,
                 font=(theme.FONT_FAMILY, 8), width=16, anchor="w").pack(side="left")
        if not hasattr(self, "_diarize_sensitivity_var"):
            self._diarize_sensitivity_var = tk.IntVar(
                value=getattr(self, "_diarize_sensitivity_init", 50))
        _sens_val = tk.Label(_sens_row, bg=BG, fg=FG, font=(theme.FONT_FAMILY, 8), width=4)
        _sens_val.pack(side="right")
        def _sens_upd(*_):
            v = int(self._diarize_sensitivity_var.get())
            _sens_val.configure(text=str(v))
        def _sens_cmd(v):
            self._diarize_sensitivity_var.set(int(v))
            _sens_upd()
        _sens_upd()
        _sens_slider = PurpleSlider(_sens_row, from_=0, to=100,
                     value=self._diarize_sensitivity_var.get(),
                     width=160, height=16, command=_sens_cmd, bg=BG)
        _sens_slider.pack(side="left", padx=(6, 0))

        def _sens_visibility_upd(*_):
            # 창이 닫힌 뒤 다른 창에서 같은 변수를 바꿔도 남은 콜백이 오류를 내지 않도록
            if not _sens_row.winfo_exists():
                return
            num, exact = self._get_diarize_spk_settings()
            if num > 0 and exact:
                _sens_row.pack_forget()
            else:
                _sens_row.pack(fill="x", padx=10, pady=(0, 8))
        # 이전에 열렸던 다이얼로그의 콜백이 남아있지 않도록 정리 후 등록
        for _v in (self._diarize_num_spk, self._diarize_spk_exact_var):
            for _t in _v.trace_info():
                _v.trace_remove(_t[0], _t[1])
            _v.trace_add("write", _sens_visibility_upd)
        _sens_visibility_upd()

        # ── 자막 설정 인라인 ──────────────────────────────────
        tk.Frame(win, bg=BORDER, height=1).pack(fill="x", padx=16, pady=(12, 8))
        tk.Label(win, text="자막 설정", bg=BG, fg=FG,
                 font=(theme.FONT_FAMILY, 9, "bold")).pack(anchor="w", padx=16)

        # 글자 수 슬라이더
        _cs_row = tk.Frame(win, bg=BG)
        _cs_row.pack(fill="x", padx=16, pady=(6, 0))
        tk.Label(_cs_row, text="문장 당 글자 수", bg=BG, fg=FG_DIM,
                 font=(theme.FONT_FAMILY, 8), width=16, anchor="w").pack(side="left")
        if not hasattr(self, "_transcribe_max_chars_var"):
            self._transcribe_max_chars_var = tk.IntVar(
                value=getattr(self, "_transcribe_max_chars", 25))
        _CS_MIN, _CS_MAX = 10, 50
        tk.Label(_cs_row, text="자", bg=BG, fg=FG_DIM,
                 font=(theme.FONT_FAMILY, 8)).pack(side="right")
        _cs_entry_var = tk.StringVar(value=str(self._transcribe_max_chars_var.get()))
        _cs_entry = tk.Entry(_cs_row, textvariable=_cs_entry_var, width=4,
                              bg=BG3, fg=FG, insertbackground=FG, justify="center",
                              relief="flat", highlightthickness=1,
                              highlightbackground=BORDER, highlightcolor=ACCENT,
                              font=(theme.FONT_FAMILY, 8))
        _cs_entry.pack(side="right", padx=(0, 2))
        def _cs_upd(*_):
            try:
                v = int(self._transcribe_max_chars_var.get())
                self._transcribe_max_chars = v
                _cs_entry_var.set(str(v))
                cfg = _load_config(); cfg["transcribe_max_chars"] = v; _save_config(cfg)
            except Exception: pass
        _cs_upd()
        def _cs_slider_cmd(v):
            self._transcribe_max_chars_var.set(int(v))
            _cs_upd()
        _cs_slider = PurpleSlider(win, from_=_CS_MIN, to=_CS_MAX,
                     value=self._transcribe_max_chars_var.get(),
                     width=360, command=_cs_slider_cmd, bg=BG)
        _cs_slider.pack(padx=16, pady=(2, 6))
        def _cs_entry_commit(*_):
            try:
                v = int(_cs_entry_var.get())
            except Exception:
                v = self._transcribe_max_chars_var.get()
            v = max(_CS_MIN, min(_CS_MAX, v))
            self._transcribe_max_chars_var.set(v)
            _cs_slider.set(v, fire=False)
            _cs_upd()
        _cs_entry.bind("<Return>",   _cs_entry_commit)
        _cs_entry.bind("<FocusOut>", _cs_entry_commit)

        # 연산 디바이스 (화자분리 설정 공유)
        _dev_row = tk.Frame(win, bg=BG)
        _dev_row.pack(fill="x", padx=16, pady=(0, 4))
        tk.Label(_dev_row, text="연산 디바이스", bg=BG, fg=FG_DIM,
                 font=(theme.FONT_FAMILY, 8), width=16, anchor="w").pack(side="left")
        if not hasattr(self, "_diarize_device_var"):
            self._diarize_device_var = tk.StringVar(
                value=getattr(self, "_diarize_device_init", "auto"))
        for _txt, _val in [("🚀 GPU 우선", "auto"), ("CPU", "cpu")]:
            tk.Radiobutton(_dev_row, text=_txt, value=_val,
                           variable=self._diarize_device_var,
                           bg=BG, fg=FG_DIM, selectcolor=BG3,
                           activebackground=BG, font=(theme.FONT_FAMILY, 8),
                           cursor="hand2").pack(side="left", padx=(0, 8))

        # 인식 모드 (텍스트만/화자 분리 모두 적용)
        _mode_row = tk.Frame(win, bg=BG)
        _mode_row.pack(fill="x", padx=16, pady=(0, 4))
        tk.Label(_mode_row, text="인식 모드", bg=BG, fg=FG_DIM,
                 font=(theme.FONT_FAMILY, 8), width=16, anchor="w").pack(side="left")
        if not hasattr(self, "_diarize_mode_var"):
            self._diarize_mode_var = tk.StringVar(
                value=getattr(self, "_diarize_mode_init", _DEFAULT_ASR_MODE))
        for _ml, _mv in [("⚡ 빠름","fast"),("⚖ 균형","balanced"),("🎯 정확","accurate"),("🔬 최고정확","best")]:
            tk.Radiobutton(_mode_row, text=_ml, value=_mv,
                           variable=self._diarize_mode_var,
                           bg=BG, fg=FG_DIM, selectcolor=BG3,
                           activebackground=BG, font=(theme.FONT_FAMILY, 7),
                           cursor="hand2").pack(side="left", padx=(0,4))
        _mode_hint = tk.Label(win, bg=BG, fg=FG_DIM, font=(theme.FONT_FAMILY, 7), anchor="w")
        _mode_hint.pack(fill="x", padx=16, pady=(0, 4))
        def _mode_hint_upd(*_):
            if self._diarize_device_var.get() == "cpu":
                _mode_hint.configure(text="  CPU 사용 시 ⚖ 균형 권장 (🎯/🔬는 매우 느릴 수 있음)")
            else:
                _mode_hint.configure(text="  GPU 사용 시 🎯 정확 권장 · 🔬는 짧은 추임새까지 잡음")
        _mode_hint_upd()
        _dev_trace = self._diarize_device_var.trace_add("write", _mode_hint_upd)
        win.bind("<Destroy>", lambda e: (e.widget is win) and
                 self._diarize_device_var.trace_remove("write", _dev_trace), add="+")

        # 인식 언어
        _lang_row = tk.Frame(win, bg=BG)
        _lang_row.pack(fill="x", padx=16, pady=(0, 4))
        tk.Label(_lang_row, text="인식 언어", bg=BG, fg=FG_DIM,
                 font=(theme.FONT_FAMILY, 8), width=16, anchor="w").pack(side="left")
        _lang_var = tk.StringVar(value=getattr(self, "_transcribe_language", "ko"))
        def _save_lang():
            self._transcribe_language = _lang_var.get()
            cfg = _load_config(); cfg["transcribe_language"] = _lang_var.get(); _save_config(cfg)
        for _txt, _val in [("한국어 고정 (권장)", "ko"), ("자동 감지", "auto")]:
            tk.Radiobutton(_lang_row, text=_txt, value=_val, variable=_lang_var,
                           command=_save_lang,
                           bg=BG, fg=FG_DIM, selectcolor=BG3,
                           activebackground=BG, font=(theme.FONT_FAMILY, 8),
                           cursor="hand2").pack(side="left", padx=(0, 8))

        # 마침표 + 맞춤법
        _opt_row = tk.Frame(win, bg=BG)
        _opt_row.pack(fill="x", padx=16, pady=(0, 4))
        if not hasattr(self, "_transcribe_period_var"):
            self._transcribe_period_var = tk.BooleanVar(
                value=getattr(self, "_transcribe_period", False))
        def _save_period_inline():
            v = self._transcribe_period_var.get()
            self._transcribe_period = v
            cfg = _load_config(); cfg["transcribe_period"] = v; _save_config(cfg)
        tk.Checkbutton(_opt_row, variable=self._transcribe_period_var,
                       bg=BG, fg=FG_DIM, selectcolor=BG3, activebackground=BG,
                       font=(theme.FONT_FAMILY, 8), cursor="hand2",
                       text="문장 끝 마침표",
                       command=_save_period_inline).pack(side="left")
        if not hasattr(self, "_transcribe_spellcheck_var"):
            self._transcribe_spellcheck_var = tk.BooleanVar(
                value=getattr(self, "_transcribe_spellcheck", False))
        def _save_spell_inline():
            v = self._transcribe_spellcheck_var.get()
            self._transcribe_spellcheck = v
            cfg = _load_config(); cfg["transcribe_spellcheck"] = v; _save_config(cfg)
        tk.Checkbutton(_opt_row, variable=self._transcribe_spellcheck_var,
                       bg=BG, fg=FG_DIM, selectcolor=BG3, activebackground=BG,
                       font=(theme.FONT_FAMILY, 8), cursor="hand2",
                       text="맞춤법 검사",
                       command=_save_spell_inline).pack(side="left", padx=(12, 0))

        # ── 화자 분리 설정 (diarize 선택 시 자막설정 아래에 표시) ──
        _diar_sep = tk.Frame(win, bg=BORDER, height=1)
        _diar_hdr = tk.Label(win, text="화자 분리 설정", bg=BG, fg=FG,
                             font=(theme.FONT_FAMILY, 9, "bold"))

        btn_row = tk.Frame(win, bg=BG)
        btn_row.pack(pady=12)

        _anim_job = [None]

        def _animate_height(target_h, on_done=None):
            """창 높이를 target_h까지 부드럽게 애니메이션."""
            if _anim_job[0]:
                win.after_cancel(_anim_job[0])
            def _step():
                try:
                    cur_h = win.winfo_height()
                    diff  = target_h - cur_h
                    if abs(diff) <= 2:
                        win.geometry(f"420x{target_h}")
                        if on_done: on_done()
                        return
                    # ease-out: 차이의 30%씩 이동
                    step = max(2, int(abs(diff) * 0.3)) * (1 if diff > 0 else -1)
                    win.geometry(f"420x{cur_h + step}")
                    _anim_job[0] = win.after(12, _step)
                except Exception:
                    pass
            _step()

        def _on_mode_change(*_):
            if mode_var.get() == "diarize":
                _diar_sep.pack(fill="x", padx=16, pady=(8, 8))
                _diar_hdr.pack(anchor="w", padx=16)
                diar_frame.pack(fill="x", padx=16, pady=(4, 0))
                btn_row.pack_forget()
                btn_row.pack(pady=12)
                _animate_height(600)
            else:
                def _hide():
                    _diar_sep.pack_forget()
                    _diar_hdr.pack_forget()
                    diar_frame.pack_forget()
                _animate_height(490, on_done=_hide)
        mode_var.trace_add("write", _on_mode_change)

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

        tk.Button(btn_row, text="생성 시작", bg=ACCENT, fg="white",
                  relief="flat", bd=0, padx=16, pady=5, cursor="hand2",
                  font=(theme.FONT_FAMILY, 9, "bold"),
                  activebackground="#7B5FB4",
                  command=_start).pack(side="left", padx=6)
        tk.Button(btn_row, text="취소", bg=BG3, fg=FG,
                  relief="flat", bd=0, padx=16, pady=5, cursor="hand2",
                  font=(theme.FONT_FAMILY, 9),
                  activebackground=BG2,
                  command=win.destroy).pack(side="left", padx=6)

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
        import threading, tempfile, time as _time

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

                _model_t0 = _time.time()
                _model_loading = {"on": True}
                def _model_load_tick():
                    if not _model_loading["on"] or _pstate.get("cancelled"):
                        return
                    elapsed = int(_time.time() - _model_t0)
                    hint = (" (최초 실행 시 모델 다운로드로 수 분 정도 걸릴 수"
                            " 있습니다. 계속 이 문구가 보여도 정상입니다)"
                            if elapsed >= 8 else "")
                    _set(f"Whisper 모델 로드 중... ({device}) · {elapsed}초 경과{hint}", 5)
                    self.after(1000, _model_load_tick)
                self.after(1000, _model_load_tick)

                _set(f"Whisper 모델 로드 중... ({device})", 5)
                _pn_hint = self._build_proper_noun_hint()
                model, _wmodel = _load_asr_model(whisperx, _mode, device,
                                                 language=_lang, asr_hint=_pn_hint)
                _model_loading["on"] = False
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


                def _fmt_ts(sec):
                    h=int(sec//3600); m=int((sec%3600)//60)
                    s=int(sec%60);   ms=int((sec%1)*1000)
                    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

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
                    srt_lines.append(f"{_fmt_ts(t_s)} --> {_fmt_ts(t_e)}")
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
                    self.title(f"{_base} (미저장) - SRT Speaker Editer")
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
        # initial_prompt는 모든 30초 청크 앞에 붙으므로, 문장형 안내문을 넣으면
        # 그 문장이 자막에 그대로 새어 나오는 환각이 생길 수 있다. 단어만 나열한다.
        joined = ", ".join(words)
        opts = {"hotwords": " ".join(words),
                "initial_prompt": joined}
        return opts

    def _open_proper_noun_manager(self, on_close=None):
        """고유명사 사전 관리 다이얼로그."""
        self._ensure_proper_nouns_init()
        win = tk.Toplevel(self)
        _apply_dark_titlebar(win)
        win.title("고유명사 사전")
        win.configure(bg=BG)
        win.geometry("380x460")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()

        tk.Label(win, text="고유명사 사전", bg=BG, fg=FG,
                 font=(theme.FONT_FAMILY, 11, "bold")).pack(anchor="w", padx=16, pady=(14, 2))
        tk.Label(win,
                 text="자주 등장하는 이름·지명·전문용어를 직접 등록하면 다음\n"
                      "자막 생성부터 인식 가중치가 높아집니다. 자동으로 추가되는\n"
                      "단어는 없으며, 여기서 등록/삭제한 목록만 반영됩니다.",
                 bg=BG, fg=FG_DIM, font=(theme.FONT_FAMILY, 8), justify="left"
                 ).pack(anchor="w", padx=16, pady=(0, 8))

        list_frame = tk.Frame(win, bg=BG)
        list_frame.pack(fill="both", expand=True, padx=16)
        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")
        lb = tk.Listbox(list_frame, bg=BG3, fg=FG, selectbackground=ACCENT,
                         relief="flat", highlightthickness=1, highlightbackground=BORDER,
                         font=(theme.FONT_FAMILY, 9), activestyle="none",
                         selectmode="extended",   # Shift/Ctrl 클릭으로 범위/다중 선택
                         yscrollcommand=scrollbar.set)
        lb.pack(side="left", fill="both", expand=True)
        scrollbar.configure(command=lb.yview)

        def _sorted_items():
            return sorted(self._proper_nouns)

        def _refresh():
            lb.delete(0, "end")
            for w in _sorted_items():
                lb.insert("end", f"  {w}")

        _refresh()

        add_row = tk.Frame(win, bg=BG)
        add_row.pack(fill="x", padx=16, pady=(8, 4))
        new_var = tk.StringVar()
        entry = tk.Entry(add_row, textvariable=new_var, bg=BG3, fg=FG,
                          insertbackground=FG, relief="flat",
                          highlightthickness=1, highlightbackground=BORDER,
                          highlightcolor=ACCENT, font=(theme.FONT_FAMILY, 9))
        entry.pack(side="left", fill="x", expand=True, ipady=3)

        def _add(*_):
            w = new_var.get().strip()
            if not w:
                return
            self._add_proper_noun(w)
            new_var.set("")
            _refresh()
        entry.bind("<Return>", _add)
        tk.Button(add_row, text="+ 추가", bg=ACCENT, fg="white", relief="flat", bd=0,
                  cursor="hand2", font=(theme.FONT_FAMILY, 9, "bold"), padx=10,
                  activebackground="#7B5FB4", command=_add).pack(side="left", padx=(6, 0))

        del_row = tk.Frame(win, bg=BG)
        del_row.pack(fill="x", padx=16, pady=(0, 10))

        def _delete(*_):
            sel = lb.curselection()
            if not sel:
                return
            items = _sorted_items()
            words = [items[i] for i in sel if i < len(items)]
            for w in words:
                self._remove_proper_noun(w)
            _refresh()
        tk.Button(del_row, text="선택 삭제", bg="#2A2A2A", fg=FG, relief="flat", bd=0,
                  cursor="hand2", font=(theme.FONT_FAMILY, 9), padx=10, pady=4,
                  activebackground="#333333", command=_delete
                  ).pack(side="left")

        def _delete_all(*_):
            if not self._proper_nouns:
                return
            if not messagebox.askyesno("전부 삭제",
                                        "등록된 고유명사를 모두 삭제할까요?",
                                        parent=win):
                return
            self._proper_nouns.clear()
            self._save_proper_nouns()
            _refresh()
        tk.Button(del_row, text="전부 삭제", bg="#2A2A2A", fg="#E08080", relief="flat", bd=0,
                  cursor="hand2", font=(theme.FONT_FAMILY, 9), padx=10, pady=4,
                  activebackground="#3A2A2A", command=_delete_all
                  ).pack(side="left", padx=(6, 0))

        def _close():
            if on_close:
                try:
                    on_close()
                except Exception:
                    pass
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", _close)
        tk.Button(win, text="닫기", bg="#2A2A2A", fg=FG, relief="flat", bd=0,
                  cursor="hand2", font=(theme.FONT_FAMILY, 10), padx=16, pady=6,
                  activebackground="#333333", command=_close
                  ).pack(pady=(0, 14))

    def _build_proper_noun_section(self, parent):
        """'고유명사 사전' 요약 + 관리 버튼 (자동자막 설정 탭 / 자막 생성
        팝업 공용). 등록된 단어는 항상 자동 반영된다. 새 Frame을 만들어
        parent에 pack하고 반환한다."""
        self._ensure_proper_nouns_init()
        pn_frame = tk.Frame(parent, bg=BG)
        pn_frame.pack(fill="x", padx=20, pady=(4, 2))

        tk.Label(pn_frame, text="고유명사 사전", bg=BG, fg=FG,
                 font=(theme.FONT_FAMILY, 9, "bold")).pack(side="left")

        _pn_count_lbl = tk.Label(pn_frame, bg=BG, fg=FG_DIM, font=(theme.FONT_FAMILY, 8))
        _pn_count_lbl.pack(side="left", padx=(6, 0))
        def _refresh_count():
            _pn_count_lbl.configure(text=f"({len(getattr(self, '_proper_nouns', None) or [])}개 등록됨)")
        _refresh_count()

        tk.Button(pn_frame, text="사전 관리", bg="#2A2A2A", fg=FG, relief="flat", bd=0,
                  cursor="hand2", font=(theme.FONT_FAMILY, 8), padx=8, pady=2,
                  activebackground="#333333",
                  command=lambda: self._open_proper_noun_manager(on_close=_refresh_count)
                  ).pack(side="right")
        tk.Label(parent,
                 text="  자주 나오는 이름·지명·전문용어를 직접 등록하면 자동 자막\n"
                      "  생성 시 인식 가중치가 항상 반영됩니다. (자동으로 추가되지\n"
                      "  않으며, 등록/삭제는 아래 '사전 관리'에서 직접 합니다)",
                 bg=BG, fg=FG_DIM, font=(theme.FONT_FAMILY, 8), justify="left", anchor="w"
                 ).pack(fill="x", padx=20, pady=(0, 6))
        return pn_frame
