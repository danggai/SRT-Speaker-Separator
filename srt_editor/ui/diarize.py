"""화자 분석(화자 분리 후 기존 자막에 화자 매핑)과 관련 설정."""
import math
import threading
import tkinter as tk
from .. import dialogs as messagebox

from .. import ai_runtime, line_speakers, theme
from ..config import _add_recent_token, _load_config, _save_config
from ..speech import _apply_diarize_sensitivity as _apply_diarize_sensitivity_impl
from ..speech import _DEFAULT_ASR_MODE, _friendly_transcribe_error
from ..theme import ACCENT, BG, BG2, BG3, BORDER, FG, FG_DIM, FG_HINT, FONT_MONO, ON_BG
from ..widgets import (DimOverlay, NumberStepper, PopupMenu, Segmented, ToggleSwitch, _gradient_bar_rows,
                       _mix, _watch, ask_choice, flat_button, present_dialog, slide)

GLOW_MIN_CHECK = 10   # 확인 필요 줄이 이만큼 이상이고
GLOW_MIN_FIXED = 3    # 그중 이만큼 고쳤으면 '다시 분석' 점등
GLOW_DIM, GLOW_BRIGHT = ON_BG, "#4A3D78"
GLOW_FRAMES, GLOW_STEP_MS = 20, 110   # 약 2.2초 주기
CHECK_CUT_DEFAULT = 0.3   # 확신도를 모를 때(다시 연 파일) ? 유지 기준


class DiarizeMixin:
    """화자 분석(화자 분리 후 기존 자막에 화자 매핑)과 관련 설정."""

    def _hf_token_row(self, parent, var):
        """HuggingFace 토큰 입력칸 + 표시/숨김 + 최근 사용 목록 (화자 분석·자막 생성 창 공용)."""
        row = tk.Frame(parent, bg=parent.cget("bg"))
        entry = tk.Entry(row, textvariable=var, show="*", bg=BG3, fg=FG, insertbackground=FG,
                         font=(FONT_MONO, 9), relief="flat", highlightthickness=1,
                         highlightbackground=BORDER, highlightcolor=ACCENT)
        entry.pack(side="left", fill="x", expand=True, ipady=4)

        def _toggle():
            hidden = entry.cget("show") == "*"
            entry.configure(show="" if hidden else "*")
            eye.configure(text="숨김" if hidden else "표시")
        eye = flat_button(row, "표시", _toggle, bg=BG3, hover="#33333C", padx=10, pady=4)
        eye.pack(side="left", padx=(6, 0))

        recent = getattr(self, "_recent_tokens", [])
        if recent:
            def _pick(t):
                var.set(t)
                entry.configure(show="*")
                eye.configure(text="표시")

            def _show_recent():
                menu = PopupMenu(self)
                for t in recent:
                    menu.add_command(label=t[:8] + "…" + t[-4:] if len(t) > 14 else t,
                                     command=lambda t=t: _pick(t))
                menu.tk_popup(btn.winfo_rootx(), btn.winfo_rooty() + btn.winfo_height() + 2)
            btn = flat_button(row, "최근 사용", _show_recent, bg=BG3, hover="#33333C", padx=10, pady=4)
            btn.pack(side="left", padx=(6, 0))
        return row

    def _speaker_count_rows(self, card, seed_note=False):
        """출연자 수 + '인원이 확실해요' (화자 분석·자막 생성 창 공용). 0명이면 확실 여부 줄은 숨김."""
        desc = "0이면 자동"
        if seed_note:
            desc += " · 미리 지정한 화자가 있으면 무시"
        _, right = self._settings_row(card, "#", "출연자 수", desc)
        if not hasattr(self, "_diarize_num_spk"):
            self._diarize_num_spk = tk.IntVar(value=getattr(self, "_diarize_num_spk_val", 0))
        NumberStepper(right, self._diarize_num_spk, 0, 20).pack()
        left, right = self._settings_row(card, "=", "인원이 확실해요", "")
        if not hasattr(self, "_diarize_spk_exact_var"):
            self._diarize_spk_exact_var = tk.BooleanVar(
                value=getattr(self, "_diarize_spk_exact_init", False))
        ToggleSwitch(right, self._diarize_spk_exact_var).pack()
        row = left.master
        sep = card.winfo_children()[-2]   # _settings_row가 줄 앞에 넣은 구분선
        hint = tk.Label(left, bg=BG2, fg=FG_DIM, justify="left", anchor="w", font=(theme.FONT_FAMILY, 9))
        hint.pack(fill="x", pady=(2, 0))

        def _update():
            try:
                num = int(self._diarize_num_spk.get())
                exact = bool(self._diarize_spk_exact_var.get())
            except (tk.TclError, ValueError):
                return
            if num > 0:
                hint.configure(text=f"정확히 {num}명" if exact else f"최대 {num}명")
                if not sep.winfo_manager():
                    sep.pack(fill="x", padx=14, **({"before": row} if row.winfo_manager() else {}))
            elif sep.winfo_manager():
                sep.pack_forget()
            slide(row, num > 0, animate=state["ready"], fill="x", padx=14, pady=12)
        state = {"ready": False}   # 처음 그릴 때는 애니메이션 없이
        _watch(row, self._diarize_num_spk, _update)
        _watch(row, self._diarize_spk_exact_var, _update)
        _update()
        state["ready"] = True

    def _build_diarize_tab(self, parent, footer_parent=None, on_close=None):
        """화자 분석 창 내용 (설정창과 같은 카드 스타일). 실행 버튼 행은 footer_parent에 둔다."""
        if footer_parent is None:
            footer_parent = parent
        self._diarize_close = on_close   # 분석을 시작하면 이 창을 닫고 메인 창에 진행 카드
        self._settings_title(parent, "화자 자동 분석",
                             "화자마다 3~5줄을 먼저 지정하면 더 정확해요.")

        card = self._settings_card(parent, "계정")
        left, _ = self._settings_row(card, "K", "HuggingFace 토큰", "분석 모델을 내려받을 때 필요해요")
        self._hf_token_var = tk.StringVar(value=getattr(self, "_hf_token", ""))
        self._hf_token_row(left, self._hf_token_var).pack(fill="x", pady=(8, 0))

        card = self._settings_card(parent, "출연자 수")
        self._speaker_count_rows(card, seed_note=True)

        # 인식 모드는 자동 자막 생성에서만 쓰지만, 설정 저장에 필요해 변수는 만들어 둔다
        if not hasattr(self, "_diarize_mode_var"):
            self._diarize_mode_var = tk.StringVar(
                value=getattr(self, "_diarize_mode_init", _DEFAULT_ASR_MODE))

        # 연산: 처리 장치 + GPU 사용량 (5단계)
        card = self._settings_card(parent, "연산")
        _, right = self._settings_row(card, "◉", "처리 장치",
                                      "GPU 우선: CUDA 가능하면 GPU, 아니면 CPU로 자동 전환")
        if not hasattr(self, "_diarize_device_var"):
            self._diarize_device_var = tk.StringVar(
                value=getattr(self, "_diarize_device_init", "auto"))
        Segmented(right, [("GPU 우선", "auto"), ("CPU", "cpu")], self._diarize_device_var).pack()

        _BATCH_MAP, _BATCH_LABEL = [2, 4, 8, 16, 32], ["최소", "낮음", "보통", "권장", "최대"]
        _VRAM_HINT = ["~2 GB", "~4 GB", "~6 GB", "~8 GB", "~12 GB+"]
        if not hasattr(self, "_diarize_batch_var"):
            self._diarize_batch_var = tk.IntVar(value=getattr(self, "_diarize_batch_init", 3))
        left, _ = self._settings_row(card, "▮", "GPU 사용량")
        gpu_lbl = tk.Label(left, bg=BG2, fg=ACCENT, font=(theme.FONT_FAMILY, 9, "bold"), anchor="w")
        gpu_lbl.pack(fill="x", pady=(2, 0))
        _SL_W, _SL_H, _PAD, _N = 360, 52, 20, len(_BATCH_MAP)
        sl = tk.Canvas(left, width=_SL_W, height=_SL_H, bg=BG2, highlightthickness=0)
        sl.pack(anchor="w", pady=(4, 0))
        _TY, _TRACK_W, _on = _SL_H // 2 - 4, _SL_W - 2 * _PAD, [True]

        def _x(i):
            return _PAD + int(i / (_N - 1) * _TRACK_W)

        def _draw(idx):
            sl.delete("all")
            dim = not _on[0]
            track, fill = ("#2A2A33", "#44444F") if dim else (BG3, ACCENT)
            sl.create_rectangle(_PAD, _TY - 2, _SL_W - _PAD, _TY + 2, fill=track, outline="")
            if idx > 0:
                sl.create_rectangle(_PAD, _TY - 2, _x(idx), _TY + 2, fill=fill, outline="")
            for i in range(_N):
                r = 7 if i == idx else 5
                active = i <= idx
                sl.create_oval(_x(i) - r, _TY - r, _x(i) + r, _TY + r,
                               fill=fill if active else track, outline=fill if active else track)
                if i == idx and not dim:
                    sl.create_oval(_x(i) - 2, _TY - 2, _x(i) + 2, _TY + 2, fill="white", outline="")
                sl.create_text(_x(i), _TY + 16, text=_BATCH_LABEL[i], anchor="n",
                               fill=(FG_DIM if dim else FG) if i == idx else (FG_HINT if dim else FG_DIM),
                               font=(theme.FONT_FAMILY, 8, "bold" if i == idx else "normal"))

        def _on_batch(*_):
            idx = max(0, min(self._diarize_batch_var.get(), _N - 1))
            _draw(idx)
            gpu_lbl.configure(text=f"batch {_BATCH_MAP[idx]}  ·  VRAM {_VRAM_HINT[idx]}")

        def _click(e):
            if _on[0]:
                self._diarize_batch_var.set(min(range(_N), key=lambda i: abs(e.x - _x(i))))
                _on_batch()
        sl.bind("<Button-1>", _click)
        sl.bind("<B1-Motion>", _click)

        def _on_device(*_):
            _on[0] = self._diarize_device_var.get() != "cpu"
            gpu_lbl.configure(fg=ACCENT if _on[0] else FG_DIM)
            _on_batch()
        _watch(sl, self._diarize_device_var, _on_device)
        _on_device()

        btn_row = tk.Frame(footer_parent, bg=BG)
        btn_row.pack(fill="x", padx=24, pady=(12, 14))
        def _start():
            # 직접 지정한 줄이 모자라면 먼저 안내
            seeds = line_speakers.seed_speakers(
                ["" if s.get("_auto") else s.get("speaker", "") for s in self.subtitles])
            if on_close and self.subtitles and not seeds:
                ans = ask_choice(self, "화자 분석",
                                 "각 화자별로 **5줄가량 지정 후 분석**하면 더 정확한 결과를 얻을 수 있습니다.\n"
                                 "이대로 진행할까요?", "지정하러 가기", "진행")   # 지정하러 가기로 유도
                if ans is None:
                    return
                if ans:
                    on_close()
                    return
            self._run_diarize_whisperx()

        flat_button(btn_row, "화자 분석 시작", _start, bg=ACCENT, fg="white",
                    hover="#AE96E2", font=(theme.FONT_FAMILY, 10, "bold"),
                    padx=22, pady=8).pack(side="right")
        if on_close:
            flat_button(btn_row, "닫기", on_close, bg=BG3, hover="#33333C",
                        font=(theme.FONT_FAMILY, 10), padx=18, pady=8).pack(side="right", padx=(0, 8))

    def _has_auto_lines(self):
        return any(s.get("_auto") for s in self.subtitles)

    def _on_diarize_button(self):
        """분석한 적 있으면 고친 줄을 기준으로 바로 다시 분석, 아니면 분석 창."""
        seeds = line_speakers.seed_speakers(
            ["" if s.get("_auto") else s.get("speaker", "") for s in self.subtitles])
        has_check = any(s.get("_check") for s in self.subtitles)
        if not (seeds and has_check and self.media_path and getattr(self, "_hf_token", "")):
            self._open_diarize_dialog()   # 기준 줄이 모자라면 군집이 화자를 새로 만들므로 창에서 고르게
            return
        var = getattr(self, "_hf_token_var", None)
        try:
            if var is None or not var.get().strip():
                self._hf_token_var = tk.StringVar(self, value=self._hf_token)
        except tk.TclError:
            self._hf_token_var = tk.StringVar(self, value=self._hf_token)
        self._diarize_close = None
        self._run_diarize_whisperx(only_check=True)

    def _update_diarize_button(self):
        btn = getattr(self, "_tb_btns", {}).get("화자 분석")
        if btn is None:
            return
        again = any(s.get("_check") for s in self.subtitles)
        if again != getattr(self, "_diarize_btn_again", False):
            self._diarize_btn_again = again
            if again:
                btn.set_label("?", "? 줄만 분석", "확인 필요(?) 줄만 다시 분석\n나머지 줄은 그대로 · 우클릭: 분석 설정",
                              icon_fg="#E8C547")
            else:
                btn.set_label("🎙", "화자 분석", "화자 자동 분석")
        # 확인 필요 줄이 많고 그중 몇 줄을 고쳤으면 다시 분석하라고 은은하게 점등
        was = [s for s in self.subtitles if s.get("_was_check")]
        fixed = sum(1 for s in was if not s.get("_auto"))   # 직접 고친 ? 줄
        glow = again and len(was) >= GLOW_MIN_CHECK and fixed >= GLOW_MIN_FIXED
        if glow != getattr(self, "_diarize_glow", False):
            self._diarize_glow = glow
            if glow:
                self._diarize_pulse(0)
            else:
                btn.set_glow(None)

    def _diarize_pulse(self, step):
        btn = self._tb_btns.get("화자 분석")
        if not getattr(self, "_diarize_glow", False) or btn is None:
            return
        t = 0.5 - 0.5 * math.cos(2 * math.pi * step / GLOW_FRAMES)
        try:
            btn.set_glow(_mix(GLOW_DIM, GLOW_BRIGHT, round(t * 8) / 8))   # 9단계로 묶어 둥근 배경 이미지 재사용
            self._diarize_pulse_after = self.after(GLOW_STEP_MS, lambda: self._diarize_pulse(step + 1))
        except tk.TclError:
            pass

    def _open_diarize_dialog(self):
        """툴바 버튼 → 화자 자동 분석 창."""
        if not self.media_path:
            messagebox.showwarning("화자 분석", "미디어 파일을 먼저 열어 주세요.", parent=self)
            return
        win = tk.Toplevel(self)
        win.withdraw()
        win.title("화자 자동 분석")
        win.configure(bg=BG)
        win.geometry("600x700")
        win.minsize(520, 460)
        win.transient(self)

        def _close():
            self._save_diarize_settings()
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", _close)
        outer, inner, footer = self._make_scrollable(win, with_footer=True)
        outer.pack(fill="both", expand=True)
        self._build_diarize_tab(inner, footer_parent=footer, on_close=_close)
        present_dialog(win, self)

    def _save_diarize_settings(self):
        """현재 화자 분석 설정을 파일에 저장."""
        # tk 위젯은 창 닫힌 후 소멸될 수 있으므로 try/except로 각각 읽기
        def _safe_get(var, fallback):
            try:
                return var.get() if var else fallback
            except Exception:
                return fallback

        hf_tok      = _safe_get(getattr(self, "_hf_token_var",     None), getattr(self, "_hf_token", "")).strip()
        num_spk     = _safe_get(getattr(self, "_diarize_num_spk",  None), getattr(self, "_diarize_num_spk_val", 0))
        mode        = _safe_get(getattr(self, "_diarize_mode_var", None), getattr(self, "_diarize_mode_init", _DEFAULT_ASR_MODE))
        device_pref = _safe_get(getattr(self, "_diarize_device_var", None), getattr(self, "_diarize_device_init", "auto"))
        batch_idx   = _safe_get(getattr(self, "_diarize_batch_var", None), 3)
        sensitivity = _safe_get(getattr(self, "_diarize_sensitivity_var", None), getattr(self, "_diarize_sensitivity_init", 50))
        spk_exact   = _safe_get(getattr(self, "_diarize_spk_exact_var", None), getattr(self, "_diarize_spk_exact_init", False))

        _cfg = _load_config()
        if hf_tok:
            _cfg["hf_token"] = hf_tok
            _add_recent_token(_cfg, hf_tok)
            self._hf_token      = hf_tok
            self._recent_tokens = _cfg.get("recent_tokens", [])
        _cfg["num_speakers"]   = num_spk
        _cfg["diarize_mode"]   = mode
        _cfg["diarize_device"] = device_pref
        _cfg["diarize_batch"]  = batch_idx
        _cfg["diarize_sensitivity"] = sensitivity
        _cfg["diarize_sens_scale"]  = 2
        _cfg["diarize_spk_exact"]   = bool(spk_exact)
        _save_config(_cfg)
        self._diarize_spk_exact_init = bool(spk_exact)
        self._diarize_num_spk_val = num_spk
        self._diarize_mode_init   = mode
        self._diarize_device_init = device_pref
        self._diarize_batch_init  = batch_idx
        self._diarize_sensitivity_init = sensitivity

    def _get_diarize_spk_settings(self):
        """(화자 수, 정확히 고정 여부). 0=자동, 고정 아니면 최대 인원."""
        num_spk_var = getattr(self, "_diarize_num_spk", None)
        try:
            num_spk = int(num_spk_var.get()) if num_spk_var is not None \
                      else int(getattr(self, "_diarize_num_spk_val", 0))
        except Exception:
            num_spk = 0
        exact_var = getattr(self, "_diarize_spk_exact_var", None)
        try:
            exact = bool(exact_var.get()) if exact_var is not None \
                    else bool(getattr(self, "_diarize_spk_exact_init", False))
        except Exception:
            exact = False
        return max(0, num_spk), exact

    def _get_diarize_sensitivity(self):
        """현재 설정된 화자 분리 민감도(0~100)를 반환. UI가 아직 없으면 저장된/기본값 사용."""
        var = getattr(self, "_diarize_sensitivity_var", None)
        if var is not None:
            try:
                return max(0, min(100, int(var.get())))
            except Exception:
                pass
        return max(0, min(100, int(getattr(self, "_diarize_sensitivity_init", 50))))

    def _apply_diarize_sensitivity(self, diarize_model, sensitivity):
        """화자 분리 민감도를 파이프라인에 반영 (speech._apply_diarize_sensitivity)."""
        _apply_diarize_sensitivity_impl(diarize_model, sensitivity)

    def _run_diarize_whisperx(self, only_check=False):
        """WhisperX로 화자 분리 실행 (백그라운드 스레드). only_check면 '확인 필요' 줄만 다시 정함."""
        _only = {i for i, s in enumerate(self.subtitles) if s.get("_check")} if only_check else None
        if not self.media_path:
            messagebox.showwarning("화자 분석", "미디어 파일을 먼저 열어 주세요.", parent=self)
            return
        if not self.subtitles:
            messagebox.showwarning("화자 분석", "자막을 먼저 열어 주세요.", parent=self)
            return

        token   = getattr(self, "_hf_token_var", None)
        hf_tok  = token.get().strip() if token else ""
        if not hf_tok:
            messagebox.showwarning("화자 분석", "HuggingFace 토큰을 입력해 주세요.", parent=self)
            return

        if not ai_runtime.ai_python():
            self._open_ai_install_dialog(on_done=self._run_diarize_whisperx, needed=True)
            return

        num_spk_var = getattr(self, "_diarize_num_spk", None)
        num_spk = num_spk_var.get() if num_spk_var else 0
        self._hf_token            = hf_tok
        self._diarize_num_spk_val = num_spk

        # 설정 저장 (토큰·화자 수·모드)
        _cfg = _load_config()
        _cfg["hf_token"]     = hf_tok
        _cfg["num_speakers"] = num_spk
        _cfg["diarize_mode"] = getattr(self, "_diarize_mode_var", tk.StringVar()).get()
        _cfg["diarize_spk_exact"]   = self._get_diarize_spk_settings()[1]
        _cfg["diarize_sensitivity"] = self._get_diarize_sensitivity()
        _cfg["diarize_sens_scale"]  = 2
        _add_recent_token(_cfg, hf_tok)
        self._recent_tokens  = _cfg.get("recent_tokens", [])
        _save_config(_cfg)

        # 진행 표시: 분석 창은 닫고, 메인 창을 흐리게 덮은 카드(모달)에 표시
        import time as _time
        _num_spk, _exact = self._get_diarize_spk_settings()   # 창을 닫기 전에 읽음
        _sens = self._get_diarize_sensitivity()
        close = getattr(self, "_diarize_close", None)
        self._diarize_close = None
        if close:
            try:
                close()
            except tk.TclError:
                pass
        prog_win = DimOverlay(self)
        card = prog_win.card

        tk.Label(card, text="화자 분석 중", bg=BG2, fg=FG,
                 font=(theme.FONT_FAMILY, 11, "bold")).pack(pady=(18, 2))

        # 현재 단계 텍스트
        self._diarize_status_lbl = tk.Label(card, text="초기화 중...",
                                             bg=BG2, fg=FG, font=(theme.FONT_FAMILY, 9, "bold"))
        self._diarize_status_lbl.pack()

        # 단계별 서브 상태 (점 애니메이션 + 경과시간)
        _sub_lbl = tk.Label(card, text="", bg=BG2, fg=FG_DIM, font=(theme.FONT_FAMILY, 8))
        _sub_lbl.pack(pady=(1, 0))

        # ── 그라데이션 웨이브 프로그레스바 ──
        BAR_W, BAR_H = 380, 20
        bar_canvas = tk.Canvas(card, width=BAR_W, height=BAR_H,
                               bg=BG3, highlightthickness=1,
                               highlightbackground=BORDER)
        bar_canvas.pack(pady=(10, 6))

        # 시간 정보 행 (경과 / 예상)
        time_row = tk.Frame(card, bg=BG2)
        time_row.pack(fill="x", padx=32, pady=(2, 0))
        _elapsed_lbl = tk.Label(time_row, text="경과  0:00", bg=BG2, fg=FG_DIM,
                                font=(theme.FONT_FAMILY, 8), anchor="w")
        _elapsed_lbl.pack(side="left")
        _eta_lbl = tk.Label(time_row, text="", bg=BG2, fg=ACCENT,
                            font=(theme.FONT_FAMILY, 10, "bold"), anchor="e")
        _eta_lbl.pack(side="right")

        # 단계 타임라인 — 전체 너비에 균등 분배
        STEP_LABELS = ["import", "audio", "model", "diarize", "map"]
        STEP_NAMES  = ["준비", "음성로드", "모델로드", "목소리분석", "화자구분"]
        step_row = tk.Frame(card, bg=BG2)
        step_row.pack(fill="x", padx=32, pady=(8, 0))
        _step_lbls = []
        for sname in STEP_NAMES:
            lbl = tk.Label(step_row, text=sname, bg=BG3, fg=FG_DIM,
                           font=(theme.FONT_FAMILY, 7), pady=3,
                           relief="flat", anchor="center")
            lbl.pack(side="left", fill="x", expand=True, padx=1)
            _step_lbls.append(lbl)

        # 진행 상태
        _prog_state = {
            "target": 0.0, "current": 0.0, "wave_phase": 0.0, "running": True,
            "step_key": None, "step_start": _time.time(), "global_start": _time.time(),
            "dot_tick": 0, "cancelled": False,
        }

        def _cancel_diarize(*_):
            """중단 버튼 또는 창 닫기(X) — 화자 분석을 취소한다.
            실행 중인 whisper/pyannote 연산 자체를 즉시 강제 종료할 수는
            없지만(라이브러리가 중간에 끊는 기능을 제공하지 않음), 취소
            플래그를 세워 결과가 나와도 화면에 반영하지 않고, 진행 창을
            바로 닫아 사용자가 더 기다리지 않도록 한다."""
            if _prog_state.get("cancelled"):
                return
            _prog_state["cancelled"] = True
            _prog_state["running"] = False
            try: prog_win.destroy()
            except Exception: pass

        flat_button(card, "중단", _cancel_diarize, bg="#3A2A2A", fg="#E08080", hover="#4A3232",
                    padx=16, pady=5).pack(pady=(12, 16))

        # 단계별 누적 % (예상시간 제거 — 실측 기반으로 계산)
        _STEPS = {
            "import":      5,
            "audio":       12,
            "model":       25,
            "diarize":     92,
            "map":         97,
            "done":        100,
        }
        _STEP_ORDER = ["import","audio","model","diarize","map","done"]

        def _fmt_time(sec):
            sec = int(sec)
            return f"{sec//60}:{sec%60:02d}"

        # PhotoImage 픽셀 렌더
        _bar_img = tk.PhotoImage(width=BAR_W, height=BAR_H)
        bar_canvas.create_image(0, 0, anchor="nw", image=_bar_img)
        _pct_id = bar_canvas.create_text(BAR_W // 2, BAR_H // 2,
                                         text="0%", fill=FG_DIM,
                                         font=(theme.FONT_FAMILY, 8, "bold"))

        def _draw_bar():
            if not _prog_state["running"]:
                return
            try:
                now   = _time.time()
                cur   = _prog_state["current"]
                phase = _prog_state["wave_phase"]
                fill_w = int(BAR_W * cur / 100)

                _bar_img.put(_gradient_bar_rows(BAR_W, BAR_H, fill_w, phase, BG3))
                bar_canvas.itemconfigure(_pct_id,
                    text=f"{int(cur)}%",
                    fill="white" if fill_w > BAR_W // 2 else FG_DIM)

                # ── 경과 시간 ──
                elapsed = now - _prog_state["global_start"]
                _elapsed_lbl.configure(text=f"경과  {_fmt_time(elapsed)}")

                # ── 예상 남은 시간 ──
                # 오디오 길이 기반 각 단계 예상 종료 시각으로 역산
                # (프로그레스바 추정치 사용 X → 늘어나는 현상 방지)
                step_key = _prog_state["step_key"]
                if step_key:
                    _stage_est = _prog_state.get("stage_estimates", {})
                    if _stage_est:
                        remaining = 0.0
                        for sk in _STEP_ORDER:
                            if sk == "done":
                                continue
                            est = _stage_est.get(sk, 0.0)
                            wall = _prog_state.get(f"wall_{sk}", None)
                            if wall is None:
                                # 아직 시작 안 한 단계 → 예상치 전부 합산
                                remaining += est
                            elif sk == step_key:
                                # 현재 진행 중인 단계 → 실제 경과 빼고 남은 것만
                                elapsed_in_step = now - wall
                                remaining += max(0.0, est - elapsed_in_step)
                            # 이미 완료된 단계는 0
                        if remaining > 5:
                            _eta_lbl.configure(text=f"예상 잔여  ~{_fmt_time(remaining)}")
                        elif remaining > 0:
                            _eta_lbl.configure(text="거의 완료...")
                    else:
                        _eta_lbl.configure(text="계산 중...")

                # ── 단계 타임라인 색상 ──
                if step_key in STEP_LABELS:
                    cur_idx = STEP_LABELS.index(step_key)
                    for i, lbl in enumerate(_step_lbls):
                        if i < cur_idx:
                            lbl.configure(bg="#1E4A2E", fg="#4CAF50")   # 완료: 초록
                        elif i == cur_idx:
                            lbl.configure(bg=ACCENT, fg="white")         # 현재: 강조
                        else:
                            lbl.configure(bg=BG3, fg=FG_DIM)             # 대기: 회색

                # ── 점 애니메이션 (현재 단계 살아있음 표시) ──
                tick = _prog_state["dot_tick"]
                dots = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
                step_elapsed_s = now - _prog_state["step_start"]
                _sub_lbl.configure(
                    text=f"{dots[tick % len(dots)]}  {_fmt_time(step_elapsed_s)} 경과")
                _prog_state["dot_tick"] += 1

                # ── ease-out ──
                _prog_state["wave_phase"] += 0.18
                diff = _prog_state["target"] - cur
                if abs(diff) > 0.05:
                    _prog_state["current"] += diff * 0.07
                else:
                    _prog_state["current"] = _prog_state["target"]

                prog_win.after(100, _draw_bar)  # 10fps (시간 표시는 1초 정밀도면 충분)
            except Exception:
                pass

        prog_win.after(100, _draw_bar)

        def _set_status(msg, step_key=None):
            try:
                self._diarize_status_lbl.configure(text=msg)
                if step_key and step_key in _STEPS:
                    t = _time.time()
                    _prog_state["target"]          = float(_STEPS[step_key])
                    _prog_state["step_key"]        = step_key
                    _prog_state["step_start"]      = t
                    _prog_state["dot_tick"]        = 0
                    _prog_state[f"wall_{step_key}"] = t  # 단계별 실제 시작 시각
            except Exception:
                pass

        def _tick_progress(step_key, elapsed_sec, total_est_sec):
            """긴 단계 내부에서 세부 진행률 추정 업데이트 (30초마다 호출)."""
            try:
                if step_key not in _STEPS:
                    return
                step_start_pct = {"diarize": 25.0}.get(step_key, None)
                step_end_pct = float(_STEPS[step_key])
                if step_start_pct is None:
                    return
                ratio = min(0.92, elapsed_sec / max(1, total_est_sec))
                new_target = step_start_pct + (step_end_pct - step_start_pct) * ratio
                if new_target > _prog_state["target"]:
                    _prog_state["target"] = new_target
            except Exception:
                pass

        # 사용자가 직접 지정한 줄만 기준으로 씀 (분석이 자동으로 채운 줄은 다시 분석할 때 새로 정함)
        _line_seeds = line_speakers.seed_speakers(
            ["" if s.get("_auto") else s.get("speaker", "") for s in self.subtitles])
        _line_intervals = [[t_s, t_e] if t_s is not None and t_e is not None else None
                           for t_s, t_e in getattr(self, "_ts_cache", [])]
        _gpu = bool((ai_runtime.installed_info() or {}).get("cuda"))
        _prog_state["stage_estimates"] = {"import": 8.0, "audio": 3.0, "model": 10.0,
                                          "diarize": len(_line_intervals) * (0.03 if _gpu else 0.08), "map": 2.0}

        def _ticker():
            while _prog_state["running"] and not _prog_state.get("cancelled"):
                if _prog_state.get("step_key") == "diarize":
                    _tick_progress("diarize", _time.time() - _prog_state.get("wall_diarize", _time.time()),
                                   _prog_state["stage_estimates"]["diarize"])
                _time.sleep(0.5)

        def _on_ev(ev):
            if ev.get("type") != "status":
                return
            step, msg, pct = ev.get("step"), ev.get("msg", ""), ev.get("pct")

            def ui():
                if step in _STEPS and step != _prog_state.get("step_key"):
                    _set_status(msg, step)
                else:
                    try:
                        self._diarize_status_lbl.configure(text=msg)
                    except Exception:
                        pass
                if pct is not None:
                    _prog_state["target"] = max(_prog_state["target"], min(float(pct), 99.0))
            self.after(0, ui)

        def _worker():
            try:
                _set_status("AI 부품 시작 중...", "import")
                threading.Thread(target=_ticker, daemon=True).start()
                res = self._run_ai_job(
                    {"type": "diarize", "media": self.media_path, "hf_token": hf_tok,
                     "intervals": _line_intervals, "seeds": {str(k): v for k, v in _line_seeds.items()},
                     "num_speakers": _num_spk, "exact": _exact, "sensitivity": _sens},
                    on_event=_on_ev, cancelled=lambda: _prog_state.get("cancelled"))
                if _prog_state.get("cancelled"):
                    return

                def _apply():
                    if _prog_state.get("cancelled"):
                        return
                    _prog_state["running"] = False
                    try:
                        prog_win.destroy()
                    except Exception:
                        pass
                    if res.get("mode") == "seeded":
                        self._apply_line_speakers(res["names"], True, res["conf"], only=_only)
                    else:
                        self._apply_line_speakers(res["labels"], False, res["conf"])
                self.after(0, _apply)
            except Exception as e:
                err_msg = _friendly_transcribe_error(str(e))

                def _err():
                    if _prog_state.get("cancelled"):
                        return
                    _prog_state["running"] = False
                    try: prog_win.destroy()
                    except Exception: pass
                    messagebox.showerror("화자 분석 오류", err_msg, parent=self)
                self.after(0, _err)

        threading.Thread(target=_worker, daemon=True).start()

    def _mark_auto_speakers(self, indices, conf):
        """분석이 정한 줄에 '자동' 표시를 남기고, 자동 줄 중 확신도가 낮은 줄을 '확인 필요'로 표시."""
        for i in indices:
            sub = self.subtitles[i]
            sub["_auto"] = True
            sub["_conf"] = float(conf[i])
        mask = line_speakers.unsure_mask([s.get("_conf", 1.0) for s in self.subtitles],
                                         [bool(s.get("_auto")) for s in self.subtitles])
        for sub, m in zip(self.subtitles, mask):
            if m:
                sub["_check"] = sub["_was_check"] = True
            else:
                sub.pop("_check", None)
                sub.pop("_was_check", None)
        self._update_check_count()

    def _recheck_lines(self, result, conf, only):
        """'? 재분석': 확인 필요 줄만 새 결과로 바꾸고, 여전히 애매한 줄만 ? 유지."""
        old = [self.subtitles[i]["_conf"] for i in only if "_conf" in self.subtitles[i]]
        cut = max(old) if old else CHECK_CUT_DEFAULT   # 기존 ? 줄 중 가장 높던 확신도 이하면 그대로 ?
        changed = 0
        for i in only:
            sub = self.subtitles[i]
            if not sub.get("_check") or not result[i]:   # 그 사이 직접 고친 줄은 건드리지 않음
                continue
            changed += sub.get("speaker") != result[i]
            sub["speaker"] = result[i]
            sub["_conf"] = float(conf[i])
            if conf[i] > cut:
                sub.pop("_check", None)
        for sub in self.subtitles:   # 이번에 반영한 고친 줄·풀린 줄은 다음 점등 계산에서 뺌
            if not sub.get("_check"):
                sub.pop("_was_check", None)
        left = sum(1 for s in self.subtitles if s.get("_check"))
        self._update_check_count()
        return f"? {len(only)}줄 중 {changed}줄의 화자를 바꿨어요." + (f"\n아직 애매한 줄 {left}줄" if left else "")

    def _apply_line_speakers(self, result, seeded, conf=None, only=None):
        """줄 단위 화자 구분 결과 적용. seeded면 이름 목록(직접 지정한 줄 외 모두 채움), 아니면 군집 번호(새 화자 추가)."""
        conf = conf if conf is not None else [1.0] * len(self.subtitles)
        self._push_undo()
        done = []
        if seeded and only is not None:
            msg = self._recheck_lines(result, conf, only)
            self._after_line_speakers(msg)
            return
        if seeded:
            for i, (sub, name) in enumerate(zip(self.subtitles, result)):
                if name and (not sub.get("speaker") or sub.get("_auto")):
                    sub["speaker"] = name
                    done.append(i)
            head = f"{len(done)}줄을 채웠어요."
        else:
            names, n = {}, 1
            for lab in sorted({int(v) for v in result if v >= 0}):
                while f"화자 {n}" in self.speakers:
                    n += 1
                names[lab] = f"화자 {n}"
                self.speakers.append(names[lab])
                n += 1
            for i, (sub, lab) in enumerate(zip(self.subtitles, result)):
                if lab >= 0:
                    sub["speaker"] = names[int(lab)]
                    done.append(i)
            head = f"{len(done)}줄을 {len(names)}명으로 나눴어요."
        self._mark_auto_speakers(done, conf)
        n_check = sum(1 for s in self.subtitles if s.get("_check"))
        msg = head
        if n_check:
            msg += f"\n확인 필요 {n_check}줄 (번호 앞 ?)"
        self._after_line_speakers(msg)

    def _after_line_speakers(self, msg):
        self._unsaved = True
        self._auto_resize_speaker_col()
        self._fill_slots(self._vscroll_top)
        self._render_speakers()
        self._update_count()
        self._wf_img_cache = None
        self._pb_redraw()
        messagebox.showinfo("화자 분석 완료", msg, parent=self)
