"""화자 분석(화자 분리 후 기존 자막에 화자 매핑)과 관련 설정."""
import os
import threading
import tkinter as tk
from tkinter import messagebox

from .. import theme
from ..config import _add_recent_token, _load_config, _save_config
from ..speech import _apply_diarize_sensitivity as _apply_diarize_sensitivity_impl
from ..speech import (
    _DEFAULT_ASR_MODE,
    _assign_speakers_by_overlap,
    _diarize_exclusive,
    _friendly_transcribe_error,
)
from ..theme import ACCENT, BG, BG3, BORDER, FG, FG_DIM, FONT_MONO, _apply_dark_titlebar
from ..widgets import PurpleSlider, _gradient_bar_rows


class DiarizeMixin:
    """화자 분석(화자 분리 후 기존 자막에 화자 매핑)과 관련 설정."""

    def _build_diarize_tab(self, parent, footer_parent=None):
        """설정창 내 화자 자동 분석 탭. footer_parent를 주면 실행 버튼 행을
        그쪽에 배치한다(스크롤 영역 밖에 고정하기 위함)."""
        if footer_parent is None:
            footer_parent = parent
        # WhisperX 섹션
        tk.Label(parent, text="WhisperX 화자 분리", bg=BG, fg=FG,
                 font=(theme.FONT_FAMILY, 11, "bold")).pack(anchor="w", padx=20, pady=(18, 2))
        tk.Label(parent,
                 text="WhisperX + pyannote를 사용해 오디오에서 화자를 자동 분리합니다.\n"
                      "HuggingFace 토큰이 필요하며 처음 실행 시 모델을 다운로드합니다.",
                 bg=BG, fg=FG_DIM, font=(theme.FONT_FAMILY, 9), justify="left"
                 ).pack(anchor="w", padx=20, pady=(0, 10))

        # HuggingFace 토큰
        hf_frame = tk.Frame(parent, bg=BG)
        hf_frame.pack(fill="x", padx=20, pady=(0, 2))
        tk.Label(hf_frame, text="HuggingFace 토큰", bg=BG, fg=FG,
                 font=(theme.FONT_FAMILY, 9, "bold"), width=18, anchor="w"
                 ).pack(side="left")
        self._hf_token_var = tk.StringVar(
            value=getattr(self, "_hf_token", ""))
        _tok_entry = tk.Entry(hf_frame, textvariable=self._hf_token_var, show="*",
                 bg=BG3, fg=FG, insertbackground=FG,
                 font=(FONT_MONO, 9), relief="flat",
                 highlightthickness=1, highlightbackground=BORDER,
                 highlightcolor=ACCENT)
        _tok_entry.pack(side="left", fill="x", expand=True, ipady=3)

        # 👁 암호화 토글 버튼
        _show_var = tk.BooleanVar(value=False)
        def _toggle_show():
            _show_var.set(not _show_var.get())
            _tok_entry.configure(show="" if _show_var.get() else "*")
            _eye_btn.configure(text="🙈" if _show_var.get() else "👁")
        _eye_btn = tk.Button(hf_frame, text="👁", bg=BG3, fg=FG_DIM,
                             relief="flat", bd=0, cursor="hand2",
                             font=(theme.FONT_FAMILY, 10), padx=6,
                             activebackground=BG3, activeforeground=FG,
                             command=_toggle_show)
        _eye_btn.pack(side="left", padx=(4, 0))

        # 최근 토큰 드롭다운
        _recent = getattr(self, "_recent_tokens", [])
        if _recent:
            def _pick_recent(val):
                self._hf_token_var.set(val)
                _show_var.set(False)
                _tok_entry.configure(show="*")
                _eye_btn.configure(text="👁")
            _recent_var = tk.StringVar(value="")
            _recent_menu = tk.OptionMenu(hf_frame, _recent_var,
                                         *[t[:8] + "…" + t[-4:] if len(t) > 14 else t
                                           for t in _recent])
            _recent_menu.configure(bg=BG3, fg=FG_DIM, relief="flat", bd=0,
                                   font=(theme.FONT_FAMILY, 8), padx=4,
                                   activebackground=BG3, activeforeground=FG,
                                   highlightthickness=0, indicatoron=False,
                                   text="🕘")
            _recent_menu["menu"].configure(bg=BG3, fg=FG, activebackground=ACCENT,
                                            font=(FONT_MONO, 8))
            _recent_menu.pack(side="left", padx=(2, 0))
            # OptionMenu 선택 시 실제 전체 토큰 삽입
            def _on_recent_select(*_):
                idx_label = _recent_var.get()
                for t in _recent:
                    label = t[:8] + "…" + t[-4:] if len(t) > 14 else t
                    if label == idx_label:
                        _pick_recent(t)
                        break
                _recent_var.set("")
            _recent_var.trace_add("write", _on_recent_select)

        # 화자 수
        spk_frame = tk.Frame(parent, bg=BG)
        spk_frame.pack(fill="x", padx=20, pady=(0, 8))
        tk.Label(spk_frame, text="화자 수 (0=자동)", bg=BG, fg=FG,
                 font=(theme.FONT_FAMILY, 9, "bold"), width=18, anchor="w"
                 ).pack(side="left")
        self._diarize_num_spk = tk.IntVar(value=getattr(self, "_diarize_num_spk_val", 0))
        tk.Spinbox(spk_frame, from_=0, to=20, width=5,
                   textvariable=self._diarize_num_spk,
                   bg=BG3, fg=FG, insertbackground=FG,
                   buttonbackground=BG3, relief="flat",
                   font=(theme.FONT_FAMILY, 10)).pack(side="left", padx=(0, 8))
        if not hasattr(self, "_diarize_spk_exact_var"):
            self._diarize_spk_exact_var = tk.BooleanVar(
                value=getattr(self, "_diarize_spk_exact_init", False))
        tk.Checkbutton(spk_frame, variable=self._diarize_spk_exact_var,
                       text="정확히 이 인원",
                       bg=BG, fg=FG, selectcolor=BG3, activebackground=BG,
                       activeforeground=FG, font=(theme.FONT_FAMILY, 9),
                       cursor="hand2").pack(side="left")
        tk.Label(parent,
                 text="  해제 시 '최대 N명'으로 제한 (출연자 수를 대략만 알 때 권장)",
                 bg=BG, fg=FG_DIM, font=(theme.FONT_FAMILY, 8), anchor="w"
                 ).pack(fill="x", padx=20, pady=(0, 8))

        # 분석 모드
        mode_frame = tk.Frame(parent, bg=BG)
        mode_frame.pack(fill="x", padx=20, pady=(0, 8))
        tk.Label(mode_frame, text="인식 모드", bg=BG, fg=FG,
                 font=(theme.FONT_FAMILY, 9, "bold"), width=18, anchor="w"
                 ).pack(side="left")
        if not hasattr(self, "_diarize_mode_var"):
            self._diarize_mode_var = tk.StringVar(value=getattr(self, "_diarize_mode_init", _DEFAULT_ASR_MODE))
        mode_inner = tk.Frame(mode_frame, bg=BG)
        mode_inner.pack(side="left")
        _MODES = [
            ("⚡ 빠름",      "fast",     "속도 우선 — 정확도 소폭 감소"),
            ("⚖ 균형",      "balanced", "속도·정확도 균형 (CPU 권장)"),
            ("🎯 정확",      "accurate", "정확도 우선 (GPU 권장, 기본)"),
            ("🔬 최고 정확", "best",     "짧은 추임새까지 인식, 가장 느림"),
        ]
        for label, val, tip in _MODES:
            rb = tk.Radiobutton(mode_inner, text=label, value=val,
                                variable=self._diarize_mode_var,
                                bg=BG, fg=FG, selectcolor=BG3,
                                activebackground=BG, activeforeground=FG,
                                font=(theme.FONT_FAMILY, 9), cursor="hand2")
            rb.pack(side="left", padx=(0, 6))
            # 툴팁
            def _bind_tip(w, t=tip):
                def _show(e): pass  # 간단히 title로 대체
            _bind_tip(rb)

        # 모드 설명 레이블
        # 인식 모드는 '자동 자막 생성'의 음성 인식에만 쓰인다. 기존 SRT에 화자를
        # 붙이는 '화자 분석'은 음성 인식 없이 화자 분리만 수행한다.
        _mode_tips = {
            "fast":     "⚡ large-v3-turbo, beam 1 — 빠른 속도, 짧은 발화 놓칠 수 있음",
            "balanced": "⚖ large-v3-turbo, beam 3 — CPU 환경 권장",
            "accurate": "🎯 large-v3, beam 5 — GPU 환경 권장 (기본)",
            "best":     "🔬 large-v3, beam 5 + 민감한 음성 감지 — 짧은 추임새·리액션까지",
        }
        _tip_lbl = tk.Label(parent, text=_mode_tips.get(self._diarize_mode_var.get(), ""),
                            bg=BG, fg=FG_DIM, font=(theme.FONT_FAMILY, 8), anchor="w")
        _tip_lbl.pack(fill="x", padx=20, pady=(0, 0))
        tk.Label(parent, text="  ※ 자동 자막 생성 시에만 적용 (화자 분석은 음성 인식을 거치지 않음)",
                 bg=BG, fg=FG_DIM, font=(theme.FONT_FAMILY, 8), anchor="w"
                 ).pack(fill="x", padx=20, pady=(0, 4))
        def _on_mode_change(*_):
            _tip_lbl.configure(text=_mode_tips.get(self._diarize_mode_var.get(), ""))
        self._diarize_mode_var.trace_add("write", _on_mode_change)

        # 화자 분리 민감도 — 높을수록 화자를 더 잘게(예민하게) 구분
        # 인원을 정확히 고정했을 때는 민감도가 의미 없으므로 슬라이더를 숨긴다.
        _sens_container = tk.Frame(parent, bg=BG)

        sens_frame = tk.Frame(_sens_container, bg=BG)
        sens_frame.pack(fill="x", padx=20, pady=(0, 8))
        tk.Label(sens_frame, text="분리 민감도", bg=BG, fg=FG,
                 font=(theme.FONT_FAMILY, 9, "bold"), width=18, anchor="w"
                 ).pack(side="left")
        if not hasattr(self, "_diarize_sensitivity_var"):
            self._diarize_sensitivity_var = tk.IntVar(
                value=getattr(self, "_diarize_sensitivity_init", 50))
        _sens_val_lbl = tk.Label(sens_frame, bg=BG, fg=FG, font=(theme.FONT_FAMILY, 9), width=4)
        _sens_val_lbl.pack(side="right")
        def _sens_upd(*_):
            _sens_val_lbl.configure(text=str(int(self._diarize_sensitivity_var.get())))
        def _sens_cmd(v):
            self._diarize_sensitivity_var.set(int(v))
            _sens_upd()
        _sens_upd()
        _sens_slider = PurpleSlider(sens_frame, from_=0, to=100,
                     value=self._diarize_sensitivity_var.get(),
                     width=220, command=_sens_cmd, bg=BG)
        _sens_slider.pack(side="left", padx=(0, 6))
        tk.Label(_sens_container,
                 text="  50 = 모델 기본값. 한 사람이 여러 화자로 쪼개지면 낮추고, 다른 사람이 합쳐지면 높이세요",
                 bg=BG, fg=FG_DIM, font=(theme.FONT_FAMILY, 8), anchor="w"
                 ).pack(fill="x", padx=20, pady=(0, 6))

        # 민감도 컨테이너가 항상 같은 자리에 다시 나타나도록 위치 표시용 프레임
        _sens_anchor = tk.Frame(parent, bg=BG)
        _sens_anchor.pack(fill="x")

        def _sens_visibility_upd(*_):
            # 창이 닫힌 뒤 다른 창에서 같은 변수를 바꿔도 남은 콜백이 오류를 내지 않도록
            if not _sens_container.winfo_exists():
                return
            num, exact = self._get_diarize_spk_settings()
            if num > 0 and exact:
                _sens_container.pack_forget()
            else:
                _sens_container.pack(fill="x", before=_sens_anchor)
        # 이전에 열렸던 탭의 콜백이 남아있지 않도록 정리 후 등록
        for _v in (self._diarize_num_spk, self._diarize_spk_exact_var):
            for _t in _v.trace_info():
                _v.trace_remove(_t[0], _t[1])
            _v.trace_add("write", _sens_visibility_upd)
        _sens_visibility_upd()

        # 디바이스 선택
        dev_frame = tk.Frame(parent, bg=BG)
        dev_frame.pack(fill="x", padx=20, pady=(4, 8))
        tk.Label(dev_frame, text="연산 디바이스", bg=BG, fg=FG,
                 font=(theme.FONT_FAMILY, 9, "bold"), width=18, anchor="w"
                 ).pack(side="left")
        if not hasattr(self, "_diarize_device_var"):
            self._diarize_device_var = tk.StringVar(
                value=getattr(self, "_diarize_device_init", "auto"))
        dev_inner = tk.Frame(dev_frame, bg=BG)
        dev_inner.pack(side="left")
        for label, val in [("🚀 GPU 우선 (기본)", "auto"), ("🖥 CPU 강제", "cpu")]:
            tk.Radiobutton(dev_inner, text=label, value=val,
                           variable=self._diarize_device_var,
                           bg=BG, fg=FG, selectcolor=BG3,
                           activebackground=BG, activeforeground=FG,
                           font=(theme.FONT_FAMILY, 9), cursor="hand2"
                           ).pack(side="left", padx=(0, 10))
        tk.Label(parent,
                 text="  GPU 우선: CUDA 가능 시 GPU 사용, 불가 시 CPU 자동 전환",
                 bg=BG, fg=FG_DIM, font=(theme.FONT_FAMILY, 8), anchor="w"
                 ).pack(fill="x", padx=20, pady=(0, 6))

        # GPU 사용량 — 캔버스 커스텀 5단계 슬라이더
        _BATCH_MAP   = [2, 4, 8, 16, 32]
        _BATCH_LABEL = ["최소", "낮음", "보통", "권장", "최대"]
        _VRAM_HINT   = ["~2 GB", "~4 GB", "~6 GB", "~8 GB", "~12 GB+"]
        _BATCH_DEFAULT = 3

        if not hasattr(self, "_diarize_batch_var"):
            self._diarize_batch_var = tk.IntVar(
                value=getattr(self, "_diarize_batch_init", _BATCH_DEFAULT))

        # 헤더 행
        gpu_hdr = tk.Frame(parent, bg=BG)
        gpu_hdr.pack(fill="x", padx=20, pady=(0, 4))
        tk.Label(gpu_hdr, text="GPU 사용량", bg=BG, fg=FG,
                 font=(theme.FONT_FAMILY, 9, "bold"), width=18, anchor="w"
                 ).pack(side="left")
        _gpu_val_lbl = tk.Label(gpu_hdr, bg=BG, fg=ACCENT,
                                font=(theme.FONT_FAMILY, 9, "bold"), anchor="w")
        _gpu_val_lbl.pack(side="left")

        # 캔버스 슬라이더
        _SL_W, _SL_H = 360, 52   # 레이블 잘림 방지
        _N = len(_BATCH_MAP)
        _sl_cv = tk.Canvas(parent, width=_SL_W, height=_SL_H,
                           bg=BG, highlightthickness=0)
        _sl_cv.pack(padx=20, anchor="w", pady=(0, 2))

        # 트랙 Y 중앙
        _TY = _SL_H // 2
        _PAD = 20   # 양쪽 여백
        _TRACK_W = _SL_W - _PAD * 2
        _enabled = [True]

        def _step_x(i):
            return _PAD + int(i / (_N - 1) * _TRACK_W)

        def _draw_slider(idx):
            _sl_cv.delete("all")
            dim = not _enabled[0]
            track_color  = "#333344" if dim else BG3
            fill_color   = "#444455" if dim else ACCENT
            dot_off      = "#2A2A3A" if dim else BG3
            dot_on       = "#444455" if dim else ACCENT
            dot_border   = "#333344" if dim else ACCENT
            label_active = FG_DIM if dim else FG
            label_dim    = "#444455" if dim else FG_DIM

            # 트랙 배경
            _sl_cv.create_rectangle(_PAD, _TY-2, _SL_W-_PAD, _TY+2,
                                    fill=track_color, outline="")
            # 채워진 부분
            if idx > 0:
                _sl_cv.create_rectangle(_PAD, _TY-2, _step_x(idx), _TY+2,
                                        fill=fill_color, outline="")

            for i in range(_N):
                x = _step_x(i)
                active = i <= idx
                # 노브
                r = 7 if i == idx else 5
                color = dot_on if active else dot_off
                border = dot_border if active else track_color
                _sl_cv.create_oval(x-r, _TY-r, x+r, _TY+r,
                                   fill=color, outline=border, width=1)
                # 선택된 노브에 내부 흰 점
                if i == idx and not dim:
                    _sl_cv.create_oval(x-2, _TY-2, x+2, _TY+2,
                                       fill="white", outline="")
                # 레이블
                lbl_color = label_active if i == idx else label_dim
                lbl_font  = (theme.FONT_FAMILY, 8, "bold") if i == idx else (theme.FONT_FAMILY, 7)
                _sl_cv.create_text(x, _TY + 14, text=_BATCH_LABEL[i],
                                   fill=lbl_color, font=lbl_font, anchor="n")

        def _on_batch(*_):
            idx = max(0, min(self._diarize_batch_var.get(), _N-1))
            _draw_slider(idx)
            bs  = _BATCH_MAP[idx]
            vrm = _VRAM_HINT[idx]
            _gpu_val_lbl.configure(text=f"batch {bs}  —  VRAM {vrm}")

        def _sl_click(e):
            if not _enabled[0]: return
            # 클릭 x → 가장 가까운 스텝
            best_i, best_d = 0, 9999
            for i in range(_N):
                d = abs(e.x - _step_x(i))
                if d < best_d:
                    best_d, best_i = d, i
            self._diarize_batch_var.set(best_i)
            _on_batch()

        _sl_cv.bind("<Button-1>", _sl_click)
        _sl_cv.bind("<B1-Motion>", _sl_click)

        def _on_device_change(*_):
            is_gpu = self._diarize_device_var.get() != "cpu"
            _enabled[0] = is_gpu
            _gpu_val_lbl.configure(fg=ACCENT if is_gpu else FG_DIM)
            _on_batch()
        self._diarize_device_var.trace_add("write", _on_device_change)
        _on_batch()
        _on_device_change()

        # 구분선
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=20, pady=10)

        # SpeechBrain 섹션 (UI만, 미구현)
        tk.Label(parent, text="SpeechBrain 화자 분리 (준비 중)", bg=BG, fg="#444455",
                 font=(theme.FONT_FAMILY, 11, "bold")).pack(anchor="w", padx=20, pady=(0, 2))
        tk.Label(parent,
                 text="토큰 없이 로컬에서 실행 가능한 방식입니다. (추후 지원 예정)",
                 bg=BG, fg="#444455", font=(theme.FONT_FAMILY, 9), justify="left"
                 ).pack(anchor="w", padx=20, pady=(0, 10))

        sb_frame = tk.Frame(parent, bg=BG)
        sb_frame.pack(fill="x", padx=20, pady=(0, 8))
        tk.Label(sb_frame, text="모델", bg=BG, fg="#444455",
                 font=(theme.FONT_FAMILY, 9, "bold"), width=18, anchor="w").pack(side="left")
        tk.Entry(sb_frame, bg=BG3, fg="#444455",
                 font=(FONT_MONO, 9), relief="flat",
                 highlightthickness=1, highlightbackground="#333333",
                 state="disabled").pack(side="left", fill="x", expand=True, ipady=3)

        # 실행 버튼 (footer_parent — 스크롤 영역 밖, 창 하단 고정)
        btn_row = tk.Frame(footer_parent, bg=BG)
        btn_row.pack(fill="x", padx=20, pady=(8, 10))
        tk.Button(btn_row, text="🎙  WhisperX로 화자 분석 시작",
                  bg=ACCENT, fg="white", relief="flat", bd=0, cursor="hand2",
                  font=(theme.FONT_FAMILY, 10, "bold"), padx=18, pady=6,
                  activebackground="#7B5FB4",
                  command=self._run_diarize_whisperx
                  ).pack(side="left")
        tk.Button(btn_row, text="SpeechBrain (준비 중)",
                  bg="#2A2A2A", fg="#444455", relief="flat", bd=0,
                  font=(theme.FONT_FAMILY, 10), padx=14, pady=6,
                  state="disabled").pack(side="left", padx=(8, 0))

    def _open_diarize_dialog(self):
        """툴바 버튼 → 설정창 화자 분석 탭 직접 열기."""
        if not self.media_path:
            messagebox.showwarning("화자 분석", "미디어 파일을 먼저 불러오세요.", parent=self)
            return
        win = tk.Toplevel(self)
        _apply_dark_titlebar(win)
        win.title("화자 자동 분석")
        win.configure(bg=BG)
        win.geometry("560x540")
        win.minsize(460, 380)
        win.resizable(True, True)
        win.transient(self)
        win.grab_set()
        def _on_diarize_win_close():
            self._save_diarize_settings()
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", _on_diarize_win_close)

        # 실행 버튼 행은 스크롤 영역 밖에 두고 먼저 하단에 고정 배치
        _diar_footer = tk.Frame(win, bg=BG)
        _diar_footer.pack(side="bottom", fill="x")
        tk.Frame(win, bg=BORDER, height=1).pack(side="bottom", fill="x")

        _diar_outer, _diar_inner = self._make_scrollable(win)
        _diar_outer.pack(fill="both", expand=True)
        self._build_diarize_tab(_diar_inner, footer_parent=_diar_footer)

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
        """(화자 수, 정확히 고정 여부) 반환. 화자 수 0 = 자동.
        고정이 아니면 화자 수는 '최대 N명' 상한으로 쓰인다."""
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

    def _run_diarize_whisperx(self):
        """WhisperX로 화자 분리 실행 (백그라운드 스레드)."""
        if not self.media_path:
            messagebox.showwarning("화자 분석", "미디어 파일을 먼저 불러오세요.", parent=self)
            return
        if not self.subtitles:
            messagebox.showwarning("화자 분석", "SRT 자막을 먼저 불러오세요.", parent=self)
            return

        token   = getattr(self, "_hf_token_var", None)
        hf_tok  = token.get().strip() if token else ""
        if not hf_tok:
            messagebox.showwarning("화자 분석",
                "HuggingFace 토큰을 입력하세요.\n"
                "https://huggingface.co/settings/tokens 에서 발급받을 수 있습니다.",
                parent=self)
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

        # 진행 다이얼로그
        import time as _time
        prog_win = tk.Toplevel(self)
        _apply_dark_titlebar(prog_win)
        prog_win.title("화자 분석 중...")
        prog_win.configure(bg=BG)
        prog_win.geometry("440x260")
        prog_win.resizable(False, False)
        prog_win.transient(self)
        prog_win.grab_set()

        tk.Label(prog_win, text="🎙  화자 자동 분석 중...", bg=BG, fg=FG,
                 font=(theme.FONT_FAMILY, 11, "bold")).pack(pady=(18, 2))

        # 현재 단계 텍스트
        self._diarize_status_lbl = tk.Label(prog_win, text="초기화 중...",
                                             bg=BG, fg=FG, font=(theme.FONT_FAMILY, 9, "bold"))
        self._diarize_status_lbl.pack()

        # 단계별 서브 상태 (점 애니메이션 + 경과시간)
        _sub_lbl = tk.Label(prog_win, text="", bg=BG, fg=FG_DIM, font=(theme.FONT_FAMILY, 8))
        _sub_lbl.pack(pady=(1, 0))

        # ── 그라데이션 웨이브 프로그레스바 ──
        BAR_W, BAR_H = 380, 20
        bar_canvas = tk.Canvas(prog_win, width=BAR_W, height=BAR_H,
                               bg=BG3, highlightthickness=1,
                               highlightbackground=BORDER)
        bar_canvas.pack(pady=(10, 6))

        # 시간 정보 행 (경과 / 예상)
        time_row = tk.Frame(prog_win, bg=BG)
        time_row.pack(fill="x", padx=32, pady=(2, 0))
        _elapsed_lbl = tk.Label(time_row, text="경과  0:00", bg=BG, fg=FG_DIM,
                                font=(theme.FONT_FAMILY, 8), anchor="w")
        _elapsed_lbl.pack(side="left")
        _eta_lbl = tk.Label(time_row, text="", bg=BG, fg=ACCENT,
                            font=(theme.FONT_FAMILY, 10, "bold"), anchor="e")
        _eta_lbl.pack(side="right")

        # 단계 타임라인 — 전체 너비에 균등 분배
        STEP_LABELS = ["import", "audio", "model", "diarize", "map"]
        STEP_NAMES  = ["임포트", "음성로드", "모델로드", "화자분리", "매핑"]
        step_row = tk.Frame(prog_win, bg=BG)
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

        prog_win.protocol("WM_DELETE_WINDOW", _cancel_diarize)

        tk.Button(prog_win, text="중단", bg="#3A2A2A", fg="#E08080",
                  relief="flat", bd=0, cursor="hand2",
                  font=(theme.FONT_FAMILY, 9), padx=14, pady=4,
                  activebackground="#4A3232",
                  command=_cancel_diarize).pack(pady=(10, 0))

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

        def _worker():
            try:
                _set_status("whisperx 임포트 중...", "import")
                import whisperx
                import torch

                # ── GPU 진단 ──────────────────────────────────────────
                _cuda_build   = torch.cuda.is_available()
                _cuda_ver     = torch.version.cuda if _cuda_build else None
                _gpu_name     = torch.cuda.get_device_name(0) if _cuda_build else None
                _torch_ver    = torch.__version__

                # 디바이스 결정
                _force_cpu_once = getattr(self, "_force_cpu_once", False)
                self._force_cpu_once = False   # 1회성 — 바로 소모
                _dev_pref = getattr(self, "_diarize_device_var", None)
                _dev_pref = _dev_pref.get() if _dev_pref else "auto"
                if _force_cpu_once:
                    _dev_pref = "cpu"   # GPU 설치 제안을 "아니오"로 답한 직후 재시도
                if _dev_pref == "cpu":
                    device = "cpu"
                    _dev_reason = "CPU 강제 모드"
                elif not _cuda_build:
                    device = "cpu"
                    _dev_reason = f"CUDA 불가 (torch {_torch_ver} — CPU 전용 빌드일 수 있음)"
                else:
                    device = "cuda"
                    _dev_reason = f"GPU: {_gpu_name}  |  CUDA {_cuda_ver}"

                _set_status(f"디바이스: {_dev_reason}", "import")

                # CUDA 빌드가 아닌데 GPU 우선 선택이면 → 자동 재설치 제안
                if _dev_pref != "cpu" and not _cuda_build:
                    import tkinter.messagebox as _mb
                    import subprocess, sys

                    # NVIDIA 드라이버에서 지원 CUDA 버전 감지
                    def _detect_cuda_tag():
                        try:
                            out = subprocess.check_output(
                                ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                                stderr=subprocess.DEVNULL, text=True).strip()
                            # 드라이버 버전으로 CUDA 지원 버전 추정
                            drv = float(out.split("\n")[0].split(".")[0])
                            if drv >= 525: return "cu121"
                            if drv >= 520: return "cu118"
                            return "cu117"
                        except Exception:
                            return "cu121"  # 기본값

                    def _ask_and_install():
                        # ⚠ 핵심 수정: prog_win이 모달(grab_set)로 떠있는 상태에서
                        # 그 위에 또 다른 모달 대화상자(askyesno)를 띄우면, 새
                        # 대화상자가 포커스를 제대로 받지 못해 사실상 응답 불가능한
                        # 상태로 멈춰버린다 — "모델 체크하다가 진행이 안 되는" 것처럼
                        # 보이던 원인이 바로 이것. 새 대화상자를 띄우기 전에 먼저
                        # prog_win의 grab을 반드시 풀어준다.
                        try:
                            prog_win.grab_release()
                        except Exception:
                            pass
                        try:
                            prog_win.destroy()
                        except Exception:
                            pass

                        cuda_tag = _detect_cuda_tag()
                        ans = _mb.askyesno(
                            "GPU torch 자동 설치",
                            f"현재 torch ({_torch_ver}) 가 CPU 전용 빌드라 GPU를 쓸 수 없어요.\n\n"
                            f"CUDA 빌드 torch ({cuda_tag}) 를 지금 자동 설치할까요?\n"
                            f"(설치 후 앱이 자동 재시작됩니다)\n\n"
                            "아니오 선택 시 CPU로 계속 진행합니다.",
                            parent=self
                        )
                        if not ans:
                            # 실제로 CPU 모드로 분석을 재시작한다 (안내 문구대로 동작하도록).
                            self._force_cpu_once = True
                            self._run_diarize_whisperx()
                            return

                        # 설치 진행 (별도 창)
                        inst_win = tk.Toplevel(self)
                        _apply_dark_titlebar(inst_win)
                        inst_win.title("torch 설치 중...")
                        inst_win.configure(bg=BG)
                        inst_win.geometry("400x120")
                        inst_win.resizable(False, False)
                        inst_win.transient(self)
                        inst_win.grab_set()
                        tk.Label(inst_win,
                                 text=f"⏳  torch+{cuda_tag} 설치 중...",
                                 bg=BG, fg=FG, font=(theme.FONT_FAMILY, 10, "bold")
                                 ).pack(pady=(24, 6))
                        _inst_sub = tk.Label(inst_win,
                                 text="pip install 실행 중 (수 분 소요될 수 있습니다)",
                                 bg=BG, fg=FG_DIM, font=(theme.FONT_FAMILY, 8))
                        _inst_sub.pack()
                        inst_win.update()

                        def _update_sub(text):
                            try: _inst_sub.configure(text=text)
                            except Exception: pass

                        def _do_pip():
                            idx_url = f"https://download.pytorch.org/whl/{cuda_tag}"
                            cmd_base = [
                                sys.executable, "-m", "pip", "install",
                                "torch", "torchaudio",
                                "--index-url", idx_url,
                                "--upgrade",
                                "--force-reinstall",   # CPU 빌드를 확실히 덮어씀
                            ]

                            def _run_cmd(extra_args=[]):
                                """pip 실행 후 stdout/stderr 캡처해서 반환."""
                                result = subprocess.run(
                                    cmd_base + extra_args,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT,
                                    text=True
                                )
                                return result.returncode, result.stdout

                            def _verify_cuda():
                                """설치 후 실제 CUDA 동작 여부 확인."""
                                try:
                                    result = subprocess.run(
                                        [sys.executable, "-c",
                                         "import torch; print(torch.cuda.is_available()); "
                                         "print(torch.__version__)"],
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        text=True, timeout=30
                                    )
                                    lines = result.stdout.strip().splitlines()
                                    cuda_ok = len(lines) >= 1 and lines[0].strip() == "True"
                                    ver = lines[1].strip() if len(lines) >= 2 else "?"
                                    return cuda_ok, ver
                                except Exception as e:
                                    return False, str(e)

                            # 1차: 일반 설치
                            self.after(0, lambda: _update_sub("pip 설치 중... (수 분 소요)"))
                            rc, out = _run_cmd()

                            if rc != 0:
                                # 2차: --user 재시도
                                self.after(0, lambda: _update_sub("권한 문제 → --user 모드로 재시도 중..."))
                                rc, out = _run_cmd(["--user"])

                            if rc != 0:
                                # 3차: UAC 관리자 승격
                                def _try_admin(log=out):
                                    try: inst_win.destroy()
                                    except Exception: pass
                                    ans2 = _mb.askyesno(
                                        "설치 실패 — 관리자 권한 필요",
                                        f"pip 설치가 실패했습니다.\n\n"
                                        f"오류 내용:\n{log[-300:]}\n\n"
                                        "관리자 권한으로 다시 시도할까요? (UAC 창이 뜹니다)",
                                        parent=self)
                                    if ans2:
                                        try:
                                            import ctypes
                                            args = (f"-m pip install torch torchaudio "
                                                    f"--index-url {idx_url} --upgrade --force-reinstall")
                                            ctypes.windll.shell32.ShellExecuteW(
                                                None, "runas", sys.executable, args, None, 1)
                                            _mb.showinfo("설치 진행 중",
                                                "관리자 권한으로 설치를 시작했습니다.\n"
                                                "완료 후 앱을 직접 재시작해주세요.",
                                                parent=self)
                                        except Exception as e2:
                                            _mb.showerror("설치 실패",
                                                f"관리자 설치도 실패했습니다.\n{e2}",
                                                parent=self)
                                self.after(0, _try_admin)
                                return

                            # 설치 성공 → CUDA 실제 동작 검증
                            self.after(0, lambda: _update_sub("설치 완료 — CUDA 동작 검증 중..."))
                            cuda_ok, ver = _verify_cuda()

                            if not cuda_ok:
                                def _bad_install(log=out, v=ver):
                                    try: inst_win.destroy()
                                    except Exception: pass
                                    _mb.showerror(
                                        "GPU 활성화 실패",
                                        f"pip 설치는 완료됐지만 CUDA가 여전히 비활성 상태입니다.\n"
                                        f"(torch {v})\n\n"
                                        "가능한 원인:\n"
                                        "• NVIDIA 드라이버가 너무 오래됨 → 드라이버 업데이트 필요\n"
                                        f"• CUDA 태그 불일치 (현재: {cuda_tag}) → "
                                        "다른 버전 시도 필요\n\n"
                                        "pip 출력 로그:\n" + log[-400:],
                                        parent=self)
                                self.after(0, _bad_install)
                                return

                            def _restart(v=ver):
                                try: inst_win.destroy()
                                except Exception: pass
                                _mb.showinfo("설치 완료",
                                    f"torch {v} GPU 빌드 설치 완료!\n"
                                    "앱을 재시작합니다.",
                                    parent=self)
                                self.destroy()
                                _frozen = getattr(sys, "frozen", False)
                                if _frozen:
                                    os.execv(sys.executable, [sys.executable])
                                else:
                                    os.execv(sys.executable, [sys.executable] + sys.argv)
                            self.after(0, _restart)

                        import threading as _t2
                        _t2.Thread(target=_do_pip, daemon=True).start()

                    self.after(0, _ask_and_install)
                    # 설치 완료 전까지 분석은 중단 (창 닫히면서 자연스럽게 종료)
                    return

                # CPU 스레드 최대한 활용
                cpu_count = os.cpu_count() or 4
                torch.set_num_threads(cpu_count)

                # 기존 SRT의 자막 타이밍에 화자만 붙이는 작업이므로 음성 인식·정렬은
                # 필요 없다. pyannote의 화자 구간을 자막 구간과 직접 겹쳐 매핑한다.
                def _progress_ticker(step_key, est_sec):
                    """0.5초마다 세부 진행률 업데이트."""
                    t0 = _time.time()
                    while _prog_state["running"] and _prog_state["step_key"] == step_key:
                        _tick_progress(step_key, _time.time() - t0, est_sec)
                        _time.sleep(0.5)

                _set_status("음성 로드 중...", "audio")
                audio = whisperx.load_audio(self.media_path)
                if _prog_state.get("cancelled"):
                    return

                import threading as _threading

                # 오디오 길이 기반 단계별 예상시간 계산
                audio_dur = len(audio) / 16000.0
                _est_diarize = audio_dur / (40.0 if device == "cuda" else 3.0)
                _prog_state["stage_estimates"] = {
                    "import":  2.0,
                    "audio":   3.0,
                    "model":   10.0,
                    "diarize": _est_diarize,
                    "map":     1.0,
                }

                _set_status(f"화자 분리 모델 로드 중... ({device})", "model")
                from whisperx.diarize import DiarizationPipeline
                diarize_model = DiarizationPipeline(token=hf_tok, device=device)
                self._apply_diarize_sensitivity(diarize_model, self._get_diarize_sensitivity())
                if _prog_state.get("cancelled"):
                    return

                _set_status("화자 분리 중...", "diarize")
                _t = _threading.Thread(
                    target=_progress_ticker, args=("diarize", _est_diarize), daemon=True)
                _t.start()
                _num_spk, _exact = self._get_diarize_spk_settings()
                diarize_segments = _diarize_exclusive(diarize_model, audio, _num_spk, _exact)
                if _prog_state.get("cancelled"):
                    return

                _set_status("화자 매핑 중...", "map")
                turns = [{"start": r.start, "end": r.end, "speaker": r.speaker}
                         for r in diarize_segments.itertuples(index=False)]

                def _apply():
                    if _prog_state.get("cancelled"):
                        return
                    try:
                        _set_status("완료!", "done")
                        prog_win.after(300, prog_win.destroy)
                    except Exception:
                        pass
                    self._apply_diarize_result(turns)

                self.after(0, _apply)

            except ImportError:
                def _err_import():
                    if _prog_state.get("cancelled"):
                        return
                    try: prog_win.destroy()
                    except Exception: pass
                    self._offer_whisperx_autoinstall(self._run_diarize_whisperx)
                self.after(0, _err_import)
            except Exception as e:
                err_msg = _friendly_transcribe_error(str(e))
                try:
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except Exception:
                    pass
                def _err():
                    if _prog_state.get("cancelled"):
                        return
                    try: prog_win.destroy()
                    except Exception: pass
                    messagebox.showerror("화자 분석 오류", err_msg, parent=self)
                self.after(0, _err)
            finally:
                # 작업이 성공/실패/취소 어떤 경우로 끝나든, 여기서 쓰던
                # 무거운 객체(모델·오디오·분리결과)들을 일괄 해제한다.
                try: del diarize_model
                except Exception: pass
                try: del audio
                except Exception: pass
                try: del diarize_segments
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

    def _apply_diarize_result(self, segments):
        """WhisperX 결과를 기존 SRT 자막에 화자 매핑으로 적용."""
        if not segments:
            messagebox.showinfo("화자 분석", "분석 결과가 없습니다.", parent=self)
            return

        # WhisperX 세그먼트에서 (start, end, speaker) 추출
        diar = []
        for seg in segments:
            spk = seg.get("speaker", "")
            if spk:
                diar.append((seg["start"], seg["end"], spk))

        if not diar:
            messagebox.showinfo("화자 분석",
                "화자 정보를 추출하지 못했습니다.\n"
                "HuggingFace 토큰과 pyannote 모델 접근 권한을 확인하세요.",
                parent=self)
            return

        # WhisperX 화자 ID → 앱 화자명 매핑 (SPEAKER_00 → 화자 N)
        spk_ids = sorted(set(s for _, _, s in diar))
        spk_map = {}
        n = 1  # 카운터를 루프 밖에서 관리해 sid마다 재초기화되지 않도록 수정
        for sid in spk_ids:
            # 기존 이름과 겹치지 않는 번호 찾기
            while True:
                name = f"화자 {n}"
                if name not in self.speakers:
                    break
                n += 1
            self.speakers.append(name)
            spk_map[sid] = name
            n += 1  # 방금 쓴 번호는 건너뛰어 다음 sid가 중복되지 않도록

        self._push_undo()

        cache = getattr(self, "_ts_cache", [])
        for i, sid in enumerate(_assign_speakers_by_overlap(cache, diar)):
            name = spk_map.get(sid, "") if sid else ""
            if name:
                self.subtitles[i]["speaker"] = name

        self._unsaved = True
        self._auto_resize_speaker_col()
        self._fill_slots(self._vscroll_top)
        self._render_speakers()
        self._update_count()
        self._wf_img_cache = None
        self._pb_redraw()

        n_mapped = sum(1 for s in self.subtitles if s.get("speaker"))
        messagebox.showinfo("화자 분석 완료",
            f"총 {len(self.subtitles)}개 자막 중 {n_mapped}개에 화자를 배정했습니다.\n"
            f"감지된 화자: {', '.join(spk_map.values())}\n\n"
            "결과를 확인하고 필요하면 수동으로 수정하세요.",
            parent=self)
