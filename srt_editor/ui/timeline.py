"""미디어 패널: 재생바·파형·자막 레이어·확대/스크롤·볼륨."""
import threading
import tkinter as tk

from .. import theme
from ..theme import ACCENT, BG2, BG3, FG, FG_DIM, MEDIA_BG
from ..widgets import Tooltip


class TimelineMixin:
    """미디어 패널: 재생바·파형·자막 레이어·확대/스크롤·볼륨."""

    def _setup_media_dnd(self, widget):
        """미디어 패널 위젯에 드래그드롭 바인딩 (tkinterdnd2)"""
        if not self._dnd_enabled:
            return
        try:
            from tkinterdnd2 import DND_FILES
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_dnd_drop)
        except Exception:
            pass

    def _build_media_panel(self, parent):
        panel = tk.Frame(parent, bg=MEDIA_BG)
        panel.pack(fill="x", side="bottom")
        self.media_panel = panel
        self._media_panel = panel   # 스크롤 바인딩용

        tk.Frame(panel, bg=ACCENT, height=2).pack(fill="x")

        inner = tk.Frame(panel, bg=MEDIA_BG)
        inner.pack(fill="x", padx=14, pady=(6, 6))

        # ── 상단: 파일명 + 열기 버튼 ──────────
        top_row = tk.Frame(inner, bg=MEDIA_BG)
        top_row.pack(fill="x", pady=(0, 4))

        self.lbl_media = tk.Label(top_row,
            text="🎵  음성/영상 파일을 여기에 드래그하거나 버튼으로 여세요",
            bg=MEDIA_BG, fg=FG_DIM, font=(theme.FONT_FAMILY, 9), anchor="w")
        self.lbl_media.pack(side="left", fill="x", expand=True)

        def _add_row_and_defocus():
            if self.media_path:
                # 현재 재생 위치를 시작점으로, 5초 이내에 다음 자막이 있으면
                # 그 시작점을, 없으면 5초 뒤를 종료점으로 하는 자막 추가.
                self.add_row_at_time(self.media_progress_var.get(), duration=5.0)
            else:
                self.add_row(getattr(self, "_last_focused_idx", None))
            self.focus_set()   # 스페이스바로 버튼이 재실행되는 것 방지

        def _split_and_defocus():
            idx, pos = self._subtitle_idx_at_playhead()
            if idx is not None:
                self.split_subtitle_at(idx, pos)
            self.focus_set()

        def _add_layer_and_defocus():
            self._wf_add_layer()
            self.focus_set()
            _refresh_layer_btn_state()

        def _remove_layer_and_defocus():
            if getattr(self, "_wf_manual_lanes", 1) > 1:
                self._wf_remove_layer()
                self.focus_set()
            _refresh_layer_btn_state()

        _IDLE, _HOVER, _DIM_FG = "#1A1A2A", BG2, "#45454F"

        def _btn_group(parent, caption):
            """캡션 + 아이콘 버튼들을 담는 그룹 프레임(하나의 테두리 공유)."""
            wrap = tk.Frame(parent, bg=_IDLE,
                            highlightthickness=1, highlightbackground="#252535")
            row = tk.Frame(wrap, bg=_IDLE)
            row.pack(side="top", padx=4, pady=(4, 0))
            tk.Label(wrap, text=caption, bg=_IDLE, fg=FG_DIM,
                     font=(theme.FONT_FAMILY, 7)).pack(side="top", pady=(1, 3))
            return wrap, row

        def _icon_only_btn(parent, icon, command, tooltip):
            """그룹 안에 들어가는 테두리 없는 작은 아이콘 버튼."""
            lbl = tk.Label(parent, text=icon, bg=_IDLE, fg=FG,
                           font=(theme.FONT_FAMILY, 13, "bold"), cursor="hand2", padx=7)
            lbl.bind("<Button-1>", lambda e: command())
            lbl.bind("<Enter>", lambda e: lbl.configure(bg=_HOVER)
                     if getattr(lbl, "_enabled", True) else None)
            lbl.bind("<Leave>", lambda e: lbl.configure(bg=_IDLE))
            Tooltip(lbl, tooltip, delay=500)
            return lbl

        # ── '레이어' 그룹: 레이어 추가 / 제거 ──
        layer_wrap, layer_row = _btn_group(top_row, "레이어")
        _layer_minus_lbl = _icon_only_btn(layer_row, "－", _remove_layer_and_defocus,
                                          "레이어 제거")
        _layer_minus_lbl.pack(side="left")
        _icon_only_btn(layer_row, "＋", _add_layer_and_defocus,
                      "레이어 추가").pack(side="left")
        layer_wrap.pack(side="right", padx=(6, 0))

        def _refresh_layer_btn_state():
            can_remove = getattr(self, "_wf_manual_lanes", 1) > 1
            _layer_minus_lbl._enabled = can_remove
            _layer_minus_lbl.configure(
                fg=FG if can_remove else _DIM_FG,
                cursor="hand2" if can_remove else "arrow",
                bg=_IDLE)
        _refresh_layer_btn_state()

        # ── '자막' 그룹: 자막 추가 / 나누기 ──
        sub_wrap, sub_row = _btn_group(top_row, "자막")
        _icon_only_btn(sub_row, "✂", _split_and_defocus,
                      "자막 나누기  [S]").pack(side="left")
        _icon_only_btn(sub_row, "＋", _add_row_and_defocus,
                      "자막 추가").pack(side="left")
        sub_wrap.pack(side="right", padx=(6, 0))

        # ── 파형 Canvas (100px) ────────────────
        self.media_progress_var = tk.DoubleVar(value=0)
        self._pb_canvas = tk.Canvas(inner, height=100, bg="#0D0D14",
                                    highlightthickness=1,
                                    highlightbackground="#252535",
                                    cursor="hand2")
        self._pb_canvas.pack(fill="x", pady=(0, 0))
        self._pb_dragging  = False
        self._waveform_pts = []
        self._wf_loading   = False

        # 줌/스크롤 상태: _wf_zoom=1.0~10.0, _wf_offset=0.0~1.0 (좌측 비율)
        self._wf_zoom   = 1.0
        self._wf_offset = 0.0   # 보이는 구간의 시작 비율
        self._wf_manual_lanes = 1   # 자막 레인(레이어) 수 — 사용자가 우클릭으로 직접 조절

        self._pb_canvas.bind("<ButtonPress-1>",   self._pb_press)
        self._pb_canvas.bind("<B1-Motion>",        self._pb_drag)
        self._pb_canvas.bind("<ButtonRelease-1>", self._pb_release)
        self._pb_canvas.bind("<Configure>",       self._pb_configure)
        self._pb_canvas.bind("<Motion>",          self._wf_on_motion)
        self._pb_canvas.bind("<MouseWheel>",      self._wf_mousewheel)
        self._pb_canvas.bind("<Control-MouseWheel>", self._wf_zoom_wheel)
        self._pb_canvas.bind("<Button-3>",           self._pb_right_click)
        # panel 생성 완료 후 모든 자식 위젯에 스크롤 바인딩
        self._pb_configure_job = None

        # ── 파형 스크롤바 ─────────────────────
        self._wf_hsb = tk.Canvas(inner, height=10, bg="#1A1A2A",
                                  highlightthickness=0, cursor="sb_h_double_arrow")
        self._wf_hsb.pack(fill="x", pady=(1, 0))
        self._wf_hsb.bind("<ButtonPress-1>",   self._wf_hsb_press)
        self._wf_hsb.bind("<B1-Motion>",        self._wf_hsb_drag)
        self._wf_hsb.bind("<ButtonRelease-1>", self._wf_hsb_release)
        self._wf_hsb_dragging = False
        self._wf_hsb_drag_x0  = 0
        self._wf_hsb_off0     = 0.0

        # ── 컨트롤 행 (버튼 + 볼륨) ───────────
        ctrl = tk.Frame(inner, bg=MEDIA_BG)
        ctrl.pack(fill="x", pady=(5, 0))

        self.lbl_pos = tk.Label(ctrl, text="0:00:00", bg=MEDIA_BG, fg=ACCENT,
                                font=(theme.FONT_FAMILY, 9, "bold"), width=8, anchor="w",
                                cursor="hand2")
        self.lbl_pos.pack(side="left")
        self.lbl_pos.bind("<Button-1>", self._copy_current_time)
        Tooltip(self.lbl_pos, "클릭: 현재 시간을 자막 타임스탬프 형식으로 복사", delay=400)

        btn_group = tk.Frame(ctrl, bg=MEDIA_BG)
        btn_group.pack(side="left", expand=True)

        # 재생 컨트롤 — 배경 MEDIA_BG와 동일, 테두리 없음
        _pc = dict(bg=MEDIA_BG, fg=FG, relief="flat", bd=0, cursor="hand2",
                   activebackground=BG3, activeforeground=FG,
                   font=(theme.FONT_FAMILY, 11), padx=10, pady=3, takefocus=0)

        self.btn_stop = tk.Button(btn_group, text="⏮", **_pc,
                  command=self._media_stop)
        self.btn_stop.pack(side="left", padx=1)
        self.btn_prev = tk.Button(btn_group, text="⏪", **_pc,
                  command=lambda: self._media_seek(-5))
        self.btn_prev.pack(side="left", padx=1)

        self.btn_play = tk.Button(btn_group, text="▶",
                                  bg=ACCENT, fg="white",
                                  font=(theme.FONT_FAMILY, 13, "bold"),
                                  relief="flat", bd=0, cursor="hand2",
                                  activebackground="#7B5FB4", activeforeground="white",
                                  padx=14, pady=3, takefocus=0,
                                  command=self._media_play_pause)
        self.btn_play.pack(side="left", padx=6)

        self.btn_next = tk.Button(btn_group, text="⏩", **_pc,
                  command=lambda: self._media_seek(+5))
        self.btn_next.pack(side="left", padx=1)

        # 줌 컨트롤 — 주변 배경과 동일색, 테두리 없음
        zoom_wrap = tk.Frame(ctrl, bg=MEDIA_BG)
        zoom_wrap.pack(side="left", padx=(12, 0))
        tk.Button(zoom_wrap, text="−", bg=MEDIA_BG, fg=FG, relief="flat", bd=0,
                  font=(theme.FONT_FAMILY, 10), padx=6, pady=2, cursor="hand2",
                  activebackground=BG3,
                  command=self._wf_zoom_out).pack(side="left")
        self.lbl_zoom = tk.Label(zoom_wrap, text="1×", bg=MEDIA_BG, fg=FG_DIM,
                                 font=(theme.FONT_FAMILY, 9), width=4)
        self.lbl_zoom.pack(side="left")
        tk.Button(zoom_wrap, text="+", bg=MEDIA_BG, fg=FG, relief="flat", bd=0,
                  font=(theme.FONT_FAMILY, 10), padx=6, pady=2, cursor="hand2",
                  activebackground=BG3,
                  command=self._wf_zoom_in).pack(side="left")

        self.lbl_dur = tk.Label(ctrl, text="0:00:00", bg=MEDIA_BG, fg=FG_DIM,
                                font=(theme.FONT_FAMILY, 9), width=8, anchor="e")
        self.lbl_dur.pack(side="right")

        vol_frame = tk.Frame(ctrl, bg=MEDIA_BG)
        vol_frame.pack(side="right", padx=(0, 12))

        self._vol_icon = tk.Label(vol_frame, text="🔊", bg=MEDIA_BG, fg=FG,
                                  font=(theme.FONT_FAMILY, 11), cursor="hand2")
        self._vol_icon.pack(side="left", padx=(0, 4))
        self._vol_icon.bind("<Button-1>", self._toggle_mute)

        self._vol_canvas = tk.Canvas(vol_frame, width=80, height=18,
                                     bg=MEDIA_BG, highlightthickness=0,
                                     cursor="hand2")
        self._vol_canvas.pack(side="left")

        self._vol_pct = tk.Label(vol_frame, text="100%", bg=MEDIA_BG, fg=FG,
                                 font=(theme.FONT_FAMILY, 9, "bold"), width=4, anchor="w")
        self._vol_pct.pack(side="left", padx=(4, 0))

        self._vol_var = 100
        self._vol_before_mute = 100
        self._vol_dragging = False

        self._vol_canvas.bind("<ButtonPress-1>",   self._vol_press)
        self._vol_canvas.bind("<B1-Motion>",        self._vol_drag)
        self._vol_canvas.bind("<ButtonRelease-1>", self._vol_release)
        self._vol_canvas.bind("<Configure>",       self._vol_redraw)
        self.after(100, self._vol_redraw)

        for w in [panel, inner, top_row, self.lbl_media, ctrl, btn_group]:
            w.bind("<Enter>", lambda e: None)

    # ── 파형 Canvas 헬퍼 ─────────────────────
    def _wf_view_range(self):
        """현재 줌/오프셋 기준 보이는 구간 (start_ratio, end_ratio) 반환."""
        zoom = max(1.0, getattr(self, "_wf_zoom", 1.0))
        off  = getattr(self, "_wf_offset", 0.0)
        span = 1.0 / zoom
        start = max(0.0, min(off, 1.0 - span))
        end   = start + span
        # offset을 clamp된 값으로 동기화
        self._wf_offset = start
        return start, end

    def _wf_ratio_to_x(self, ratio, cw):
        """전체 비율 → 현재 뷰 내 x픽셀."""
        start, end = self._wf_view_range()
        span = end - start
        if span <= 0:
            return 0
        return int((ratio - start) / span * cw)

    def _wf_x_to_ratio(self, x, cw):
        """현재 뷰 내 x픽셀 → 전체 비율."""
        start, end = self._wf_view_range()
        span = end - start
        return max(0.0, min(start + (x / cw) * span, 1.0))

    def _pb_configure(self, event=None):
        """창 크기 변경 시 디바운싱 — 100ms 내 추가 이벤트 없을 때만 redraw."""
        if self._pb_configure_job:
            try:
                self.after_cancel(self._pb_configure_job)
            except Exception:
                pass
        self._pb_configure_job = self.after(100, self._pb_invalidate)

    def _pb_invalidate(self):
        """파형 이미지 캐시를 무효화하고 전체 redraw."""
        self._wf_img_cache = None
        self._pb_redraw()

    # 재생바 자막 영역에 표시할 최대 레인(줄) 수. 그 이상 겹치면 마지막
    # 레인을 공유(겹쳐 그려짐)한다.
    _WF_ABS_MAX_LANES = 6   # 수동으로 추가할 수 있는 레인 수의 절대 상한
    _WF_LANE_H    = 22    # 자막 레인(줄) 하나의 높이
    _PB_BASE_CANVAS_H = 100   # 자막 1레인 기준 재생바 캔버스 기본 높이

    def _compute_subtitle_lanes(self, cache):
        """자막들의 시간 겹침을 분석해 각 자막을 레인(줄) 번호(0부터)에
        배정한다. 레인 수는 자동으로 늘어나지 않고, 사용자가 우클릭 메뉴의
        '레이어 추가'로 직접 설정한 개수(self._wf_manual_lanes, 기본 1)만큼만
        사용한다. 그보다 많이 겹치면 초과분은 마지막 레인을 함께 쓴다.

        ⚠ 안정화: 한 번 배정된 레인은(드래그로 직접 옮겼든, 자동으로 배정
        됐든) subtitle["_lane"]에 저장해두고 계속 유지한다. 그래서 자막
        하나를 드래그해서 레인을 옮겨도, 그 자막만 바뀔 뿐 겹쳐있던 다른
        자막들은 이미 있던 자기 레인에 그대로 남아있는다(우르르 재배치되지
        않음). 레인이 아직 없는(새로 추가된) 자막만 빈 레인에 새로 배치되고,
        그 결과도 그대로 저장되어 이후엔 계속 유지된다.
        반환: (lanes: {자막idx: 레인번호}, 레인 수 — 항상 수동 설정값)"""
        max_lanes = max(1, min(getattr(self, "_wf_manual_lanes", 1),
                               self._WF_ABS_MAX_LANES))
        items = [(i, t_s, t_e) for i, (t_s, t_e) in enumerate(cache)
                 if t_s is not None and t_e is not None]
        if not items:
            return {}, max_lanes
        items.sort(key=lambda x: x[1])

        lane_end = [0.0] * max_lanes
        lanes = {}

        # 1차: 이미 레인이 정해진(드래그로 옮겼든 이전에 자동 배정됐든)
        # 자막은 그 레인을 그대로 유지한다.
        for idx, t_s, t_e in items:
            pinned = self.subtitles[idx].get("_lane") if idx < len(self.subtitles) else None
            if isinstance(pinned, int) and 0 <= pinned < max_lanes:
                lanes[idx] = pinned
                lane_end[pinned] = max(lane_end[pinned], t_e)

        # 2차: 레인이 아직 없는(새로 생긴) 자막만 빈 레인을 찾아 배치
        for idx, t_s, t_e in items:
            if idx in lanes:
                continue
            placed = False
            for lane in range(max_lanes):
                if lane_end[lane] <= t_s:
                    lane_end[lane] = t_e
                    lanes[idx] = lane
                    placed = True
                    break
            if not placed:
                # 최대 레인 초과 → 마지막 레인에 강제 배정(그 경우만 겹쳐 보임)
                last = max_lanes - 1
                lane_end[last] = max(lane_end[last], t_e)
                lanes[idx] = last

        # 이번에 정해진 레인을 자막에 다시 저장 — 다음 재계산 때도 유지되게
        for idx, lane in lanes.items():
            if idx < len(self.subtitles):
                self.subtitles[idx]["_lane"] = lane

        return lanes, max_lanes

    def _pb_redraw(self, event=None):
        c  = self._pb_canvas
        cw = c.winfo_width()
        ch = c.winfo_height()
        if cw <= 1:
            self.after(50, self._pb_redraw)
            return

        from PIL import Image, ImageDraw, ImageTk

        dur    = self.player.duration if self.player.duration > 0 else 0
        pos    = self.media_progress_var.get()
        start_r, end_r = self._wf_view_range()

        # dur=0이면 캐시에서 산출
        cache = getattr(self, "_ts_cache", [])
        if dur > 0:
            dur_ = dur
        else:
            ends = [t_e for _, t_e in cache if t_e is not None]
            dur_ = max(ends) if ends else 1.0

        # ── 자막 레인(줄) 배정 ──────────────────
        # 레인 수는 자동으로 늘어나지 않고, 우클릭 메뉴의 '레이어 추가/
        # 제거'로 사용자가 직접 설정한 개수(_wf_manual_lanes, 기본 1)를
        # 그대로 쓴다. 시간대가 겹치는 자막은 그 레인 수 안에서 서로 다른
        # 줄에 배치된다. 이 계산은 자막 타이밍(cache) 또는 레인 수 자체가
        # 바뀔 때만 다시 하면 되므로 — 이미지 캐시 히트 여부와는 무관하게 —
        # ts_cache 객체가 바뀌었는지(identity)만 저렴하게 확인해 재사용한다.
        # (재생헤드만 움직이는 매 프레임에는 그대로 캐시된 값을 씀)
        if getattr(self, "_wf_lanes_src", None) is cache:
            lanes     = self._wf_lanes
            num_lanes = self._wf_num_lanes
        else:
            lanes, num_lanes = self._compute_subtitle_lanes(cache)
            self._wf_lanes     = lanes
            self._wf_num_lanes = num_lanes
            self._wf_lanes_src = cache

        # ── 레이아웃 상수 ──────────────────────
        LANE_H = self._WF_LANE_H
        SUB_H  = LANE_H * num_lanes   # 자막 영역 전체 높이(겹치면 최대 3줄)
        GAP    = 1           # 자막/파형 구분선
        TICK_H = 16          # 하단 시간 눈금 영역

        # 겹치는 자막이 많아 레인이 늘어나도 파형이 보이는 높이는 항상
        # 일정하게 유지되도록, 늘어난 레인만큼 캔버스 전체 높이를 늘린다
        # (그렇지 않으면 파형 영역이 레인 수만큼 눌려서 거의 안 보이게 됨).
        # cache_key를 만들기 전에 확정해야 리사이즈된 높이로 이미지 캐시가
        # 올바르게 갱신된다.
        target_ch = self._PB_BASE_CANVAS_H + (num_lanes - 1) * LANE_H
        if abs(ch - target_ch) > 1:
            c.configure(height=target_ch)
        ch = target_ch

        sub_top = 0
        sub_bot = SUB_H
        wf_top  = SUB_H + GAP
        wf_bot  = ch - TICK_H
        wf_h    = wf_bot - wf_top
        wf_mid  = wf_top + wf_h // 2   # 파형 중앙 (두 채널 경계)
        self._wf_sub_h = SUB_H   # 히트테스트 등 다른 곳에서도 참조

        # ── 캐시 키 ───────────────────────────
        cache_key = (cw, ch, round(self._wf_zoom, 4), round(self._wf_offset, 6),
                     id(self._waveform_pts),
                     tuple((s.get("speaker",""), s.get("timestamp",""))
                            for s in (self.subtitles or [])),
                     round(dur_, 2))

        cached = getattr(self, "_wf_img_cache", None)
        cache_hit = bool(cached and cached[0] == cache_key)

        head_x = self._wf_ratio_to_x(pos / dur if dur > 0 else 0, cw)

        if cache_hit:
            img_tk = cached[1]
        else:
            img    = Image.new("RGB", (cw, ch), "#0D0D0F")
            draw   = ImageDraw.Draw(img)
            pixels = img.load()

            # ── A. 자막 타임라인 행 ───────────
            # 배경
            draw.rectangle([0, sub_top, cw, sub_bot], fill="#131318")
            # 구분선
            draw.line([0, sub_bot, cw, sub_bot], fill="#2A2A3A", width=1)

            # 자막 블록 — 한글 지원 폰트 로드
            try:
                from PIL import ImageFont
                import sys as _sys, os as _os
                _candidates = (
                    ["C:/Windows/Fonts/malgun.ttf",
                     "C:/Windows/Fonts/NanumGothic.ttf",
                     "C:/Windows/Fonts/gulim.ttc"]
                    if _sys.platform == "win32" else
                    ["/System/Library/Fonts/AppleSDGothicNeo.ttc",
                     "/Library/Fonts/NanumGothic.ttf"]
                    if _sys.platform == "darwin" else
                    ["/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
                     "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
                )
                font = None
                for _fp in _candidates:
                    if _os.path.exists(_fp):
                        font = ImageFont.truetype(_fp, 10)
                        break
            except Exception:
                font = None

            # 레인 구분선 + 왼쪽에 레인 번호(1,2,3...) 표시
            for _lane_i in range(num_lanes):
                _ly = _lane_i * LANE_H
                if _lane_i > 0:
                    draw.line([0, _ly, cw, _ly], fill="#20202A", width=1)
                draw.text((3, _ly + 5), str(_lane_i + 1), fill="#55555F", font=font)

            if cache and self.subtitles:
                drag = getattr(self, "_wf_sub_drag", None)
                for i, (t_s, t_e) in enumerate(cache):
                    if t_s is None or t_e is None:
                        continue
                    if drag and drag["idx"] == i:
                        t_s = drag.get("t_s", t_s)
                        t_e = drag.get("t_e", t_e)
                    r_s, r_e = t_s / dur_, t_e / dur_
                    if r_e < start_r or r_s > end_r:
                        continue
                    x1 = int(self._wf_ratio_to_x(max(r_s, start_r), cw))
                    x2 = int(self._wf_ratio_to_x(min(r_e, end_r), cw))
                    x2 = max(x1 + 2, x2)

                    lane = lanes.get(i, 0)
                    if drag and drag["idx"] == i and "target_lane" in drag:
                        lane = drag["target_lane"]
                    ln_top = lane * LANE_H
                    ln_bot = ln_top + LANE_H

                    spk   = self.subtitles[i].get("speaker", "")
                    raw   = self._speaker_color(spk) if spk else "#404055"
                    h_hex = raw.lstrip("#")
                    fr, fg_, fb = int(h_hex[0:2],16), int(h_hex[2:4],16), int(h_hex[4:6],16)
                    # 어둡게 (화자 색 30% + 배경 70%)
                    BG_R, BG_G, BG_B = 0x13, 0x13, 0x18
                    fill_rgb = (int(fr*0.30+BG_R*0.70),
                                int(fg_*0.30+BG_G*0.70),
                                int(fb*0.30+BG_B*0.70))
                    fill_hex = f"#{fill_rgb[0]:02x}{fill_rgb[1]:02x}{fill_rgb[2]:02x}"
                    # 블록 채우기 (1px 위아래 여백)
                    draw.rectangle([x1+1, ln_top+3, x2, ln_bot-3], fill=fill_hex)
                    # 좌측 색상 강조선 (1px)
                    draw.line([x1+1, ln_top+3, x1+1, ln_bot-3], fill=raw, width=1)

                    # 텍스트 (폭이 허용되는 만큼)
                    box_w = x2 - x1 - 6
                    if box_w >= 14:
                        text = self.subtitles[i].get("text", "").replace("\n", " ").strip()
                        if text:
                            CHAR_W = 6
                            max_ch = max(1, box_w // CHAR_W)
                            if len(text) > max_ch:
                                text = text[:max_ch - 1] + "…"
                            ty = ln_top + (LANE_H - 12) // 2
                            text_col = f"#{min(255,fr+80):02x}{min(255,fg_+80):02x}{min(255,fb+80):02x}"
                            if font:
                                draw.text((x1 + 5, ty), text, fill=text_col, font=font)
                            else:
                                draw.text((x1 + 5, ty), text, fill=text_col)

                # 레인 구분선 (2줄 이상일 때만, 겹침을 시각적으로 구분)
                if num_lanes > 1:
                    for ln in range(1, num_lanes):
                        y = ln * LANE_H
                        draw.line([0, y, cw, y], fill="#232330", width=1)

            # ── B. 파형 (상단 채널 ↑ + 하단 채널 ↓) ──
            draw.rectangle([0, wf_top, cw, wf_bot], fill="#0D0D14")
            # 중앙 분리선
            draw.line([0, wf_mid, cw, wf_mid], fill="#1A1A28", width=1)

            wf = getattr(self, "_waveform_pts", [])
            if wf:
                margin  = (end_r - start_r) / max(cw, 1)
                pts_vis = [(rx, amp) for rx, amp in wf
                           if start_r - margin <= rx <= end_r + margin]
                if not pts_vis:
                    pts_vis = wf

                # 데이터 포인트 → x픽셀 매핑 (최대값)
                x_amp_raw = {}
                for rx, amp in pts_vis:
                    x = int(self._wf_ratio_to_x(rx, cw))
                    if 0 <= x < cw:
                        x_amp_raw[x] = max(x_amp_raw.get(x, 0.0), amp)

                # 선형 보간: 데이터 없는 픽셀은 인접 포인트 사이를 부드럽게 채움
                if x_amp_raw:
                    filled_xs = sorted(x_amp_raw)
                    x_amp = {}
                    for i in range(len(filled_xs)):
                        xa = filled_xs[i]
                        aa = x_amp_raw[xa]
                        x_amp[xa] = aa
                        if i + 1 < len(filled_xs):
                            xb = filled_xs[i + 1]
                            ab = x_amp_raw[xb]
                            for xi in range(xa + 1, xb):
                                t = (xi - xa) / (xb - xa)
                                x_amp[xi] = aa + (ab - aa) * t
                    # 양 끝 채우기
                    for xi in range(0, filled_xs[0]):
                        x_amp[xi] = x_amp_raw[filled_xs[0]]
                    for xi in range(filled_xs[-1] + 1, cw):
                        x_amp[xi] = x_amp_raw[filled_xs[-1]]
                else:
                    x_amp = {}

                half_h  = wf_h // 2 - 2   # 채널 하나의 최대 높이
                WF_BASE = (0x1E, 0x1E, 0x3A)
                WF_PLAY = (0x3A, 0x2A, 0x5A)

                for x in range(cw):
                    amp = x_amp.get(x, 0.0)
                    if False:  # 구 코드 제거
                        amp = 0.0
                    px = int(amp * half_h)
                    col = WF_PLAY if x <= head_x else WF_BASE

                    # 상단 채널 (wf_mid 기준 위쪽으로)
                    y0_top = max(wf_top,  wf_mid - px)
                    y1_top = wf_mid
                    for y in range(y0_top, y1_top):
                        pixels[x, y] = col

                    # 하단 채널 (wf_mid 기준 아래쪽으로)
                    y0_bot = wf_mid + 1
                    y1_bot = min(wf_bot, wf_mid + px + 1)
                    for y in range(y0_bot, y1_bot):
                        pixels[x, y] = col

            elif dur_ > 0:
                draw.rectangle([0, wf_mid-1, cw, wf_mid+1], fill="#2A2A4A")
                if head_x > 0:
                    draw.rectangle([0, wf_mid-1, head_x, wf_mid+1], fill=ACCENT)

            # ── C. 시간 눈금 ─────────────────────
            if dur > 0:
                span_sec = (end_r - start_r) * dur
                for tick in [0.1, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600]:
                    if span_sec / tick <= self._WF_MAX_TICKS_ON_SCREEN:
                        tick_step = tick; break
                else:
                    tick_step = 600
                t = (int(start_r * dur / tick_step)) * tick_step
                while t <= end_r * dur:
                    if t > dur: break
                    x = self._wf_ratio_to_x(t / dur, cw)
                    if 0 <= x <= cw:
                        draw.line([x, wf_bot, x, wf_bot+4], fill="#444466")
                        h_ = int(t//3600); m_ = int((t%3600)//60); s_ = int(t%60)
                        ms = int((t*10)%10)
                        lbl = (f"{m_}:{s_:02d}.{ms}" if tick_step < 1
                               else f"{h_}:{m_:02d}:{s_:02d}" if h_
                               else f"{m_}:{s_:02d}")
                        draw.text((x+3, wf_bot+2), lbl, fill="#555577")
                    t += tick_step

            img_tk = ImageTk.PhotoImage(img)
            self._wf_img_cache = (cache_key, img_tk)

        # ── Canvas 오버레이 ───────────────────
        # 배경(파형/자막 블록)이 캐시 히트이고 드래그 중도 아니라면 — 즉 이번
        # 호출이 순전히 재생헤드 이동(재생 중 매 프레임 폴링)뿐이라면 — 캔버스
        # 전체를 지우고 이미지·핸들을 통째로 다시 그리는 대신 재생헤드 좌표만
        # 옮긴다. 재생 중 초당 수십 번 호출되는 이 함수에서 매번 delete("all")
        # 후 전체 아이템을 재생성하는 것이 가장 큰 렉의 원인이었다.
        drag_active = getattr(self, "_wf_sub_drag", None) is not None
        fast_path = (cache_hit and not drag_active
                     and getattr(self, "_wf_last_img", None) is img_tk
                     and c.find_withtag("bgimg"))

        if fast_path:
            if dur > 0:
                c.coords("head_line", head_x, 0, head_x, ch)
                c.coords("head_poly", head_x-5, sub_top, head_x+5, sub_top, head_x, sub_top+7)
            return

        c.delete("all")
        c.create_image(0, 0, anchor="nw", image=img_tk, tags="bgimg")
        self._wf_last_img = img_tk

        # 재생 헤드
        if dur > 0:
            c.create_line(head_x, 0, head_x, ch, fill="white", width=1, tags=("head", "head_line"))
            c.create_polygon(head_x-5, sub_top, head_x+5, sub_top, head_x, sub_top+7,
                             fill="white", outline="", tags=("head", "head_poly"))

        # 드래그 핸들 (파형 영역 기준)
        if cache and self.subtitles:
            drag = getattr(self, "_wf_sub_drag", None)
            HW   = self._WF_HANDLE_W
            for i, (t_s, t_e) in enumerate(cache):
                if t_s is None or t_e is None:
                    continue
                ts = t_s; te = t_e
                if drag and drag["idx"] == i:
                    ts = drag.get("t_s", ts)
                    te = drag.get("t_e", te)
                r_s, r_e = ts / dur_, te / dur_
                if r_e < start_r or r_s > end_r:
                    continue
                x1 = self._wf_ratio_to_x(max(r_s, start_r), cw)
                x2 = max(x1+2, self._wf_ratio_to_x(min(r_e, end_r), cw))
                spk   = self.subtitles[i].get("speaker", "")
                color = self._speaker_color(spk) if spk else "#404055"
                snapped_s = drag and drag["idx"]==i and drag["mode"]=="head_start"
                snapped_e = drag and drag["idx"]==i and drag["mode"]=="head_end"
                moving    = drag and drag["idx"]==i and drag["mode"]=="move"
                ln = lanes.get(i, 0)
                if drag and drag["idx"] == i and "target_lane" in drag:
                    ln = drag["target_lane"]
                ln_top = ln * LANE_H
                ln_bot = ln_top + LANE_H
                if moving:
                    # 이동 중인 자막은 테두리로 강조
                    c.create_rectangle(x1, ln_top+1, x2, ln_bot-1,
                                       outline="#FFFFFF", width=1)
                # 핸들은 그 자막이 있는 레인 높이에
                c.create_rectangle(x1,    ln_top, x1+HW, ln_bot,
                                   fill="#FFFFFF" if snapped_s else color, outline="")
                c.create_rectangle(x2-HW, ln_top, x2,    ln_bot,
                                   fill="#FFFFFF" if snapped_e else color, outline="")

        if getattr(self, "_wf_loading", False):
            c.create_text(cw//2, wf_top + (wf_bot-wf_top)//2,
                         text="파형 분석 중...", fill="#555577", font=(theme.FONT_FAMILY, 9))

        self._wf_hsb_redraw()

    def _wf_hit_test(self, x, y):
        """재생바 자막 히트테스트.

        우선순위: 리사이즈 핸들 > 자막 바디 > 빈 타임라인.
        - 핸들: 두 자막이 맞닿아 핸들이 같은 위치에 겹치는 경우, 커서가 그
          자막의 '안쪽'(경계를 넘지 않은 쪽)에 있는 핸들을 우선한다.
          그 다음 가장 가까운 핸들이 이기고, 그래도 동률이면 z-index
          (리스트 뒤쪽 = 나중에 그려짐)가 높은 쪽이 이긴다.
        - 바디: 겹치는 자막이 여러 개면 z-index가 가장 높은 것을 우선 히트로
          반환하되, 겹치는 전체 스택도 함께 돌려줘 클릭 시 순환 선택에 쓴다.

        반환값:
            {"type": "handle", "idx": i, "mode": "head_start"/"head_end"} |
            {"type": "body", "idx": i, "stack": [...]} |
            {"type": "empty"}
        """
        LANE_H    = self._WF_LANE_H
        lanes     = getattr(self, "_wf_lanes", {})
        num_lanes = getattr(self, "_wf_num_lanes", 1)
        SUB_H = LANE_H * num_lanes
        if y > SUB_H:
            return {"type": "empty"}
        lane_idx = int(y // LANE_H)

        dur   = self.player.duration
        cache = getattr(self, "_ts_cache", [])
        if dur <= 0:
            ends = [t_e for _, t_e in cache if t_e is not None]
            dur = max(ends) if ends else 0

        if dur <= 0 or not cache or not self.subtitles:
            return {"type": "empty"}

        cw = self._pb_canvas.winfo_width()
        start_r, end_r = self._wf_view_range()
        HW = max(self._WF_HANDLE_W + 3, 7)

        # 현재 뷰포트에 보이는 자막들의 픽셀 범위 (커서가 있는 레인의
        # 자막만 대상으로 한다 — 겹쳐서 다른 줄에 그려진 자막은 제외)
        visible = []
        for i, (t_s, t_e) in enumerate(cache):
            if t_s is None or t_e is None:
                continue
            if lanes.get(i, 0) != lane_idx:
                continue
            r_s, r_e = t_s / dur, t_e / dur
            if r_e < start_r or r_s > end_r:
                continue
            x1 = self._wf_ratio_to_x(max(r_s, start_r), cw)
            x2 = self._wf_ratio_to_x(min(r_e, end_r), cw)
            visible.append((i, x1, x2))

        # 1순위: 리사이즈 핸들
        # 두 자막이 맞닿아 핸들이 같은 위치에 겹칠 때, 커서가 그 자막의
        # '안쪽'(경계를 아직 넘지 않은 쪽)에 있는 핸들을 우선 선택한다.
        # → 앞 자막의 끝 핸들을 잡으려는데 뒷 자막의 시작 핸들이 대신 잡히는
        #    문제를 방지. 그 다음 가장 가까운 핸들, 그래도 동률이면 z-index
        #    (인덱스 큰 쪽)가 승리한다.
        best_key = None
        best_hit = None
        for i, x1, x2 in visible:
            for mode, xh in (("head_start", x1), ("head_end", x2)):
                d = abs(x - xh)
                if d <= HW:
                    if mode == "head_end":
                        outside = 1 if x > xh else 0   # 경계 넘으면 바깥(다음 자막 쪽)
                    else:
                        outside = 1 if x < xh else 0   # 경계 못 미치면 바깥(이전 자막 쪽)
                    key = (outside, d, -i)   # 안쪽 우선 → 거리 우선 → z-index 큰 쪽 승리
                    if best_key is None or key < best_key:
                        best_key = key
                        best_hit = {"type": "handle", "idx": i, "mode": mode}
        if best_hit is not None:
            return best_hit

        # 2순위: 자막 바디 — 겹치는 모든 자막 중 z-index(인덱스) 높은 게 최상단
        stack = sorted((i for i, x1, x2 in visible if x1 <= x <= x2), reverse=True)
        if stack:
            return {"type": "body", "idx": stack[0], "stack": stack}

        # 3순위: 빈 타임라인
        return {"type": "empty"}

    def _wf_cycle_click(self, stack, default_idx):
        """겹친 자막 바디를 같은 위치에서 반복 클릭하면 z-index 역순으로 순환 선택."""
        stack = sorted(set(stack), reverse=True)   # z-index 높은 것부터
        if len(stack) <= 1:
            return default_idx
        last_stack = getattr(self, "_wf_last_click_stack", None)
        last_idx   = getattr(self, "_wf_last_click_idx", None)

        if last_stack == stack and last_idx in stack:
            pos = stack.index(last_idx)
            next_idx = stack[(pos + 1) % len(stack)]
        else:
            next_idx = stack[0]   # 새 위치 클릭 → 최상단(z-index 최상위)부터

        self._wf_last_click_stack = stack
        self._wf_last_click_idx   = next_idx
        return next_idx

    def _wf_on_motion(self, event):
        """마우스 위치에 따라 커서 변경 + hover 자막 추적."""
        hit = self._wf_hit_test(event.x, event.y)
        if hit["type"] == "handle":
            self._wf_hovered_idx = hit["idx"]
            self._pb_canvas.configure(cursor="sb_h_double_arrow")
        elif hit["type"] == "body":
            self._wf_hovered_idx = hit["idx"]
            self._pb_canvas.configure(cursor="fleur")
        elif event.y <= getattr(self, "_wf_sub_h", 22):
            self._wf_hovered_idx = None
            self._pb_canvas.configure(cursor="tcross")
        else:
            self._wf_hovered_idx = None
            self._pb_canvas.configure(cursor="hand2")

    def _pb_press(self, event):
        x, y = event.x, event.y
        self._pb_press_x = x
        self._pb_press_y = y

        # ── 드래그 캡처: 이 프레스에서 확정된 타겟을 버튼을 뗄 때까지 고정한다.
        # 이후 _pb_drag/_pb_release는 hover가 아니라 여기서 만든 drag 상태
        # (self._wf_sub_drag)만 참조하므로, 드래그 중 커서가 다른 자막 위를
        # 지나가도 타겟이 바뀌지 않는다.
        hit = self._wf_hit_test(x, y)

        if hit["type"] == "handle":
            self._start_handle_drag(hit["mode"], hit["idx"])
            return

        if hit["type"] == "body":
            shift_lock = bool(event.state & 0x0001)   # Shift 키
            self._start_body_drag(hit["idx"], x, y, shift_lock, stack=hit["stack"])
            return

        # ── 빈 타임라인 / 파형 영역 → 재생 위치 스크럽 ──
        self._wf_sub_drag = None
        self._pb_dragging = True
        self._pb_canvas.configure(cursor="hand2")
        pos = self._pb_pos_from_x(x)
        self.media_progress_var.set(pos)
        self.lbl_pos.configure(text=self._fmt_time(pos))
        self._pb_redraw()

    def _start_handle_drag(self, mode, idx):
        """리사이즈 핸들 드래그 상태 초기화. 변경 전 상태를 여기서 찍어 두고,
        실제로 바뀐 경우에만 release에서 실행 취소 기록으로 확정한다."""
        cache = getattr(self, "_ts_cache", [])
        self._wf_sub_drag = {
            "undo_snap": self._snapshot(),
            "mode": mode, "idx": idx,
            "t_s": cache[idx][0],
            "t_e": cache[idx][1],
        }
        self._pb_dragging = False
        self._pb_sub_click_idx = None
        self._pb_canvas.configure(cursor="sb_h_double_arrow")

    def _on_shift_key_change(self, event, pressed=None):
        """재생바에서 자막을 드래그하는 도중, 마우스를 움직이지 않고 Shift
        키만 눌렀다 떼도 미리보기(흰 박스)가 그 즉시(마우스 이동 없이도)
        목표 위치로 갱신되도록 한다. pressed=True/False로 명시적으로 호출."""
        drag = getattr(self, "_wf_sub_drag", None)
        if not drag or drag.get("mode") != "move":
            return
        drag["shift_lock"] = bool(pressed)
        if pressed:
            drag["t_s"] = drag["orig_t_s"]
            drag["t_e"] = drag["orig_t_e"]
        self._pb_redraw()

    def _start_body_drag(self, idx, x, y, shift_lock, stack=None):
        """자막 바디 드래그 시작 — 기본적으로 길이 고정한 채 좌우(타이밍)로
        이동한다. 위아래로 움직이면 자막이 속한 레이어(레인)도 함께 바뀐다.
        shift_lock=True(Shift 누른 채 드래그)면 타이밍은 전혀 건드리지 않고
        레이어 이동만 한다. 변경 전 상태는 여기서 찍어 두고, 실제로 바뀐
        경우에만 release에서 실행 취소 기록으로 확정한다."""
        cache = getattr(self, "_ts_cache", [])
        cur_lane = getattr(self, "_wf_lanes", {}).get(idx, 0)
        self._wf_sub_drag = {
            "undo_snap": self._snapshot(),
            "mode": "move", "idx": idx,
            "t_s": cache[idx][0], "t_e": cache[idx][1],
            "orig_t_s": cache[idx][0], "orig_t_e": cache[idx][1],
            "press_x": x, "press_y": y,
            "orig_lane": cur_lane, "target_lane": cur_lane,
            "shift_lock": shift_lock,
            "stack": stack or [idx],
        }
        self._pb_dragging = False
        self._pb_sub_click_idx = idx
        self._pb_canvas.configure(cursor="fleur")
        self._pb_redraw()   # 마우스를 움직이기 전에도 즉시 미리보기(흰 박스)가 보이도록

    def _pb_drag(self, event):
        drag = getattr(self, "_wf_sub_drag", None)
        if drag:
            dur = self.player.duration
            if dur <= 0:
                return
            cw = self._pb_canvas.winfo_width()

            if drag["mode"] == "move":
                # 세로 위치로 목표 레이어(레인) 계산
                num_lanes = max(1, getattr(self, "_wf_num_lanes", 1))
                target_lane = max(0, min(num_lanes - 1,
                                         int(event.y // self._WF_LANE_H)))
                drag["target_lane"] = target_lane

                # Shift 상태는 프레스 시점이 아니라 매 순간 실시간으로 확인한다.
                # (드래그 중간에 Shift를 누르거나 떼도 즉시 반영되도록)
                shift_now = bool(event.state & 0x0001)
                drag["shift_lock"] = shift_now   # release에서도 이 최신 상태를 그대로 씀

                if shift_now:
                    # Shift 드래그: 지금까지 옮긴 타이밍은 무시하고 드래그를
                    # "시작하기 전"의 원래 시간으로 되돌린 채 레이어만 이동한다.
                    drag["t_s"] = drag["orig_t_s"]
                    drag["t_e"] = drag["orig_t_e"]
                    self._pb_redraw()
                    return

                # 자막 전체 이동 — 길이는 고정. 다른 자막(레이어가 달라도
                # 상관없이 전부 대상) 시작/끝점·재생헤드에 스냅한다.
                # 후보가 여러 개면 그중 가장 가까운 것에 붙는다.
                press_ratio = self._wf_x_to_ratio(drag["press_x"], cw)
                cur_ratio   = self._wf_x_to_ratio(event.x, cw)
                delta_sec   = (cur_ratio - press_ratio) * dur
                span = drag["orig_t_e"] - drag["orig_t_s"]
                new_s = drag["orig_t_s"] + delta_sec
                new_s = max(0.0, min(new_s, max(0.0, dur - span)))
                new_e = new_s + span

                idx = drag["idx"]
                span_sec_view = (1.0 / max(1.0, self._wf_zoom)) * dur
                snap_sec = span_sec_view * 8 / max(cw, 1)

                # 스냅 후보: 다른 모든 자막의 시작/끝점(레이어 무관) + 재생헤드
                candidates = []
                for j, (js, je) in enumerate(self._ts_cache):
                    if j == idx:
                        continue
                    if js is not None:
                        candidates.append(js)
                    if je is not None:
                        candidates.append(je)
                candidates.append(self.media_progress_var.get())

                # 시작점 또는 끝점 중 후보에 가장 가깝게 붙는 오프셋을 찾는다
                best_delta = None
                for c in candidates:
                    for edge in (new_s, new_e):
                        d = c - edge
                        if abs(d) < snap_sec and (best_delta is None or abs(d) < abs(best_delta)):
                            best_delta = d
                if best_delta is not None:
                    new_s += best_delta
                    new_e += best_delta

                drag["t_s"] = new_s
                drag["t_e"] = new_e
                self._pb_redraw()
                return

            # 리사이즈(핸들 드래그) — 최소 길이 강제 + 인접 자막 경계·재생헤드 스냅
            # (다른 자막과 자유롭게 겹칠 수도 있음 — 스냅 범위 밖이면 그대로 이동)
            idx   = drag["idx"]
            cache = self._ts_cache
            t = max(0.0, self._wf_x_to_ratio(event.x, cw) * dur)
            # 스냅 임계값: 현재 뷰에서 8px에 해당하는 초
            span_sec = (1.0 / max(1.0, self._wf_zoom)) * dur
            snap_sec = span_sec * 8 / max(cw, 1)

            if drag["mode"] == "head_start":
                t = min(t, drag["t_e"] - self._MIN_SUB_DURATION)
                # 스냅 후보: 다른 자막의 끝점 + 재생 헤드
                snap_candidates = []
                for j, (js, je) in enumerate(cache):
                    if j == idx or je is None:
                        continue
                    if abs(je - t) < snap_sec:
                        snap_candidates.append(je)
                pos = self.media_progress_var.get()
                if abs(pos - t) < snap_sec:
                    snap_candidates.append(pos)
                if snap_candidates:
                    t = min(snap_candidates, key=lambda v: abs(v - t))
                drag["t_s"] = max(0.0, t)
            else:
                t = max(t, drag["t_s"] + self._MIN_SUB_DURATION)
                # 스냅 후보: 다른 자막의 시작점 + 재생 헤드
                snap_candidates = []
                for j, (js, je) in enumerate(cache):
                    if j == idx or js is None:
                        continue
                    if abs(js - t) < snap_sec:
                        snap_candidates.append(js)
                pos = self.media_progress_var.get()
                if abs(pos - t) < snap_sec:
                    snap_candidates.append(pos)
                if snap_candidates:
                    t = min(snap_candidates, key=lambda v: abs(v - t))
                drag["t_e"] = t

            self._pb_redraw()
            return
        if not self._pb_dragging:
            return
        pos = self._pb_pos_from_x(event.x)
        self.media_progress_var.set(pos)
        self.lbl_pos.configure(text=self._fmt_time(pos))
        self._pb_redraw()

    def _pb_release(self, event):
        drag      = getattr(self, "_wf_sub_drag", None)
        press_x   = getattr(self, "_pb_press_x", event.x)
        press_y   = getattr(self, "_pb_press_y", event.y)
        moved     = max(abs(event.x - press_x), abs(event.y - press_y))
        CLICK_THR = 5   # 이 픽셀 이하 이동이면 클릭으로 판정

        self._pb_canvas.configure(cursor="hand2")

        if drag:
            idx = drag["idx"]

            # 거의 안 움직였으면 → 클릭으로 판정 (타임스탬프/레이어 변경 없음)
            if moved <= CLICK_THR:
                self._wf_sub_drag = None
                if drag["mode"] == "move":
                    # 자막 바디 클릭 — 같은 위치를 다시 클릭하면 겹친 자막들을 순환 선택
                    # (재생 위치는 옮기지 않고 '선택'만 한다)
                    target_idx = self._wf_cycle_click(drag.get("stack") or [idx], idx)
                    if target_idx < len(self.subtitles):
                        self._select_row(target_idx, seek=False)
                    else:
                        self._pb_redraw()
                else:
                    cache = getattr(self, "_ts_cache", [])
                    t_s = cache[idx][0] if idx < len(cache) else None
                    if t_s is not None:
                        self._do_seek(t_s)
                    else:
                        self._pb_redraw()
                return

            # 실제 드래그 → 타임스탬프(Shift 드래그면 생략) + 레이어 적용
            # (실제로 바뀐 경우에만 시작 시점 스냅샷을 실행 취소 기록으로 확정)
            changed = False
            if 0 <= idx < len(self.subtitles):
                if drag["mode"] == "move" and drag.get("shift_lock"):
                    # Shift 드래그: 타이밍은 그대로 두고 레이어만 반영
                    pass
                else:
                    t_s = drag.get("t_s", self._ts_cache[idx][0])
                    t_e = drag.get("t_e", self._ts_cache[idx][1])
                    def _fmt_ts(sec):
                        h=int(sec//3600); m=int((sec%3600)//60); s=int(sec%60)
                        ms=int(round((sec%1)*1000))
                        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
                    new_ts = f"{_fmt_ts(t_s)} --> {_fmt_ts(t_e)}"
                    if self.subtitles[idx].get("timestamp") != new_ts:
                        self.subtitles[idx]["timestamp"] = new_ts
                        self._ts_cache[idx] = (t_s, t_e)
                        changed = True

                if drag["mode"] == "move" and "target_lane" in drag:
                    new_lane = drag["target_lane"]
                    if new_lane != drag.get("orig_lane"):
                        self.subtitles[idx]["_lane"] = new_lane
                        self._wf_lanes_src = None   # 레인 재계산 강제
                        changed = True

                if changed:
                    self._commit_undo(drag["undo_snap"])
                    self._unsaved = True
                    self._redraw_slot_for(idx)
            self._wf_sub_drag = None
            self._wf_img_cache = None   # 이미지 캐시 무효화
            self._pb_redraw()
            return

        self._pb_dragging = False
        if not self.media_path:
            return
        self._do_seek(self._pb_pos_from_x(event.x))

    def _pb_right_click(self, event):
        """재생바 우클릭 — 자막 바디/핸들 위일 때만 자막 행과 동일한
        컨텍스트 메뉴(선택 포함)를 띄운다. (레이어/자막 추가·나누기는
        타임라인 상단 버튼으로 이동함)"""
        hit = self._wf_hit_test(event.x, event.y)

        if hit["type"] in ("handle", "body"):
            idx = hit["idx"]
            if idx not in getattr(self, "_selected_rows", set()):
                self._select_row(idx)
            self._show_context_menu(event, idx)
            return

    def _wf_add_layer(self):
        """재생바 자막 레인을 하나 더 늘린다(수동, 절대 상한까지)."""
        cur = getattr(self, "_wf_manual_lanes", 1)
        if cur >= self._WF_ABS_MAX_LANES:
            return
        self._wf_manual_lanes = cur + 1
        self._wf_lanes_src = None   # 레인 재계산 강제
        self._wf_img_cache = None
        self._pb_redraw()

    def _wf_remove_layer(self):
        """재생바 자막 레인을 하나 줄인다(최소 1)."""
        cur = getattr(self, "_wf_manual_lanes", 1)
        if cur <= 1:
            return
        self._wf_manual_lanes = cur - 1
        self._wf_lanes_src = None   # 레인 재계산 강제
        self._wf_img_cache = None
        self._pb_redraw()

    def _do_seek(self, pos, update_selection=True):
        """지정 위치로 seek.
        update_selection=True(기본): 재생바 직접 이동 시, 해당 위치 자막을 선택으로 설정.
        update_selection=False: 내부 seek(재생/정지, 좌우키 등)에서 호출 시 현재 선택 자막을 변경하지 않음."""
        was_playing = self.player.is_playing
        self.player.seek_to(pos)
        self.media_progress_var.set(pos)
        self.lbl_pos.configure(text=self._fmt_time(pos))

        new_rows = self._get_rows_at(pos)

        # 하이라이트 갱신
        if new_rows != self._playing_rows:
            changed = self._playing_rows.symmetric_difference(new_rows)
            self._playing_rows = new_rows
            for idx in changed:
                self._redraw_slot_for(idx)

        # 재생바 직접 이동 시에만 해당 자막을 선택으로 설정
        if update_selection and new_rows:
            anchor = min(new_rows)
            old_sel = set(self._selected_rows) | ({self._selected_row_idx} if self._selected_row_idx is not None else set())
            self._selected_rows = set(new_rows)
            self._selected_row_idx = anchor
            self._last_focused_idx = anchor
            for idx in old_sel.symmetric_difference(self._selected_rows):
                self._redraw_slot_for(idx)
            self._scroll_to_row(anchor)

        self._pb_redraw()
        if was_playing:
            self.btn_play.configure(text="⏸")
            self._start_progress_poll()

    def _wf_hsb_redraw(self):
        c = getattr(self, "_wf_hsb", None)
        if c is None: return
        cw = c.winfo_width(); ch = c.winfo_height()
        if cw <= 1: return
        c.delete("all")
        c.create_rectangle(0, 0, cw, ch, fill="#1A1A2A", outline="")
        if self._wf_zoom <= 1.0: return
        start, end = self._wf_view_range()
        x1 = int(start * cw)
        x2 = max(x1+12, int(end * cw))
        c.create_rectangle(x1, 1, x2, ch-1, fill="#3A3A5A", outline="#555577")

    def _wf_hsb_press(self, e):
        self._wf_hsb_dragging = True
        self._wf_hsb_drag_x0  = e.x
        self._wf_hsb_off0     = self._wf_offset

    def _wf_hsb_drag(self, e):
        if not self._wf_hsb_dragging: return
        cw = self._wf_hsb.winfo_width()
        if cw <= 1: return
        span = 1.0 / max(1.0, self._wf_zoom)
        self._wf_offset = max(0.0, min(self._wf_hsb_off0 + (e.x - self._wf_hsb_drag_x0) / cw, 1.0 - span))
        self._pb_redraw()

    def _wf_hsb_release(self, e):
        self._wf_hsb_dragging = False

    def _wf_mousewheel(self, e):
        # 파형 뷰 구간 이동 (재생 위치 무관)
        # 위 스크롤 → 앞, 아래 스크롤 → 뒤 / Shift: 5배 빠르게
        span  = 1.0 / max(1.0, self._wf_zoom)
        step  = span * 0.2 if (e.state & 0x1) else span * 0.03
        delta = -step if e.delta > 0 else step
        self._wf_offset = max(0.0, min(self._wf_offset + delta, 1.0 - span))
        self._pb_redraw()
        return "break"


    # 시간 눈금이 표시할 수 있는 가장 작은 단위(초). _pb_redraw의 눈금
    # 후보 목록[0.1, 0.5, 1, 2, ...]과 반드시 일치해야 한다.
    _WF_MIN_TICK_SEC = 0.1
    _WF_MAX_TICKS_ON_SCREEN = 24   # 한 화면에 보이는 눈금 최대 개수(_pb_redraw와 동일)

    def _wf_max_zoom(self):
        """더 확대해도 눈금 단위가 0.1초보다 더 세밀해지지 않는(=의미가
        없어지는) 지점을 기준으로 최대 확대 배율을 정수로 계산한다.
        고정된 배율(예: 128배) 대신, 미디어 길이에 따라 '한 틱당 길이'가
        일정 수준(0.1초) 이하로는 내려가지 않도록 동적으로 정한다."""
        dur = self.player.duration if self.player.duration > 0 else 0
        if dur <= 0:
            return 128
        min_span = self._WF_MIN_TICK_SEC * self._WF_MAX_TICKS_ON_SCREEN
        return max(1, int(round(dur / min_span)))

    def _wf_zoom_wheel(self, e):
        cw = self._pb_canvas.winfo_width()
        # 마우스 위치를 pivot으로
        pivot = self._wf_x_to_ratio(e.x, cw) if cw > 1 else None
        if e.delta > 0: self._wf_zoom_in(pivot=pivot)
        else:           self._wf_zoom_out(pivot=pivot)
        return "break"

    def _wf_zoom_in(self, pivot=None):
        old_zoom = self._wf_zoom
        self._wf_zoom = min(float(self._wf_max_zoom()), self._wf_zoom * 1.5)
        self._wf_adjust_offset(old_zoom, pivot)
        self._update_zoom_label()
        self._pb_redraw()

    def _wf_zoom_out(self, pivot=None):
        old_zoom = self._wf_zoom
        self._wf_zoom = max(1.0, self._wf_zoom / 1.5)
        self._wf_adjust_offset(old_zoom, pivot)
        self._update_zoom_label()
        self._pb_redraw()

    def _wf_adjust_offset(self, old_zoom, pivot=None):
        """줌 변경 후 pivot 비율이 같은 화면 위치에 유지되도록 offset 조정.
        pivot=None 이면 현재 재생 헤드 위치를 pivot으로 사용."""
        if pivot is None:
            dur = self.player.duration
            pivot = (self.media_progress_var.get() / dur) if dur > 0 else 0.5
        span = 1.0 / self._wf_zoom
        # pivot이 뷰에서 차지하던 상대 위치(0~1) 유지
        old_span  = 1.0 / max(1.0, old_zoom)
        rel = (pivot - self._wf_offset) / old_span if old_span > 0 else 0.5
        rel = max(0.0, min(rel, 1.0))
        new_offset = pivot - rel * span
        self._wf_offset = max(0.0, min(new_offset, 1.0 - span))

    def _update_zoom_label(self):
        z = self._wf_zoom
        try:
            self.lbl_zoom.configure(text=f"{z:.0f}×" if z == int(z) else f"{z:.1f}×")
        except Exception:
            pass

    def _pb_pos_from_x(self, x):
        cw  = self._pb_canvas.winfo_width()
        dur = self.player.duration if self.player.duration > 0 else 1
        return self._wf_x_to_ratio(x, cw) * dur

    # ── 볼륨 제어 (커스텀 Canvas 바) ──────────
    def _vol_redraw(self, event=None):
        """볼륨 바 Canvas 다시 그리기."""
        c = self._vol_canvas
        cw = c.winfo_width()
        ch = c.winfo_height()
        if cw <= 1:
            self.after(50, self._vol_redraw)
            return
        c.delete("all")
        v = self._vol_var          # 0~100
        ratio = v / 100.0
        filled = int(cw * ratio)
        track_y = ch // 2

        # 트랙 배경 (라운드 효과는 rect로 근사)
        c.create_rectangle(0, track_y - 4, cw, track_y + 4,
                           fill="#2A2A2A", outline="", tags="track")
        # 채워진 부분 — ACCENT보다 약간 어두운 단일 색
        if filled > 0:
            c.create_rectangle(0, track_y - 4, filled, track_y + 4,
                               fill="#7A5FB0", outline="", tags="fill")
        # 핸들
        hx = max(6, min(filled, cw - 6))
        c.create_oval(hx - 6, track_y - 6, hx + 6, track_y + 6,
                      fill="white", outline="#555555", width=1, tags="handle")

    def _vol_from_x(self, x):
        cw = self._vol_canvas.winfo_width()
        return max(0, min(100, int(x / cw * 100)))

    def _vol_press(self, event):
        self._vol_dragging = True
        self._set_volume(self._vol_from_x(event.x))

    def _vol_drag(self, event):
        if not self._vol_dragging:
            return
        self._set_volume(self._vol_from_x(event.x))

    def _vol_release(self, event):
        self._vol_dragging = False
        self._set_volume(self._vol_from_x(event.x))

    def _set_volume(self, v):
        """볼륨 값(0~100) 반영: 플레이어·UI·아이콘 모두 갱신."""
        v = max(0, min(100, v))
        self._vol_var = v
        self.player._volume = v
        self._vol_pct.configure(text=f"{v}%")
        # 아이콘
        if v == 0:
            self._vol_icon.configure(text="🔇")
        elif v < 40:
            self._vol_icon.configure(text="🔉")
        else:
            self._vol_icon.configure(text="🔊")
        self._vol_redraw()
        # 재생 중이어도 끊김 없이 실시간으로 볼륨만 반영
        self.player.set_volume(v)

    def _toggle_mute(self, event=None):
        """볼륨 아이콘 클릭 → 음소거/복원 토글."""
        if self._vol_var > 0:
            self._vol_before_mute = self._vol_var
            self._set_volume(0)
        else:
            self._set_volume(self._vol_before_mute if self._vol_before_mute > 0 else 80)

    def _extract_waveform(self, path):
        """librosa 로 파형 추출 (mp3 포함 전 포맷 지원, ffmpeg 불필요) — UI 블로킹 없음."""
        self._wf_loading = True
        self._waveform_pts = []
        self._pb_redraw()

        cw    = max(self._pb_canvas.winfo_width(), 800)
        N_PTS = max(4000, min(cw * 128, 32000))

        def _ensure_pip(*pkgs):
            import subprocess as _sp, sys as _sys
            for pkg in pkgs:
                try:
                    __import__(pkg)
                except ImportError:
                    _sp.check_call(
                        [_sys.executable, "-m", "pip", "install", pkg, "-q"],
                        stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)

        def _worker():
            import traceback
            try:
                _ensure_pip("librosa", "numpy", "soundfile", "audioread")
                import librosa, numpy as np

                # 22050Hz 모노로 로드 (mp3/wav/flac/ogg/m4a 전부 지원)
                y, sr = librosa.load(path, sr=22050, mono=True)
                total  = len(y)
                hop    = max(1, total // N_PTS)

                # librosa.util.frame: 버전에 따라 shape (frame_length, n_frames)
                frames = librosa.util.frame(y, frame_length=hop, hop_length=hop)
                # 항상 axis=0이 frame_length, axis=1이 n_frames
                if frames.ndim == 1:
                    frames = frames.reshape(-1, 1)

                peak    = np.max(np.abs(frames), axis=0)   # (n_frames,)
                rms     = np.sqrt(np.mean(frames ** 2, axis=0))
                amp_arr = np.clip(peak * 0.6 + rms * 2.5, 0.0, 1.0)
                n_frames = int(amp_arr.shape[0])

                # x: 0~1 시간축 비율
                pts = [(i / max(1, n_frames - 1), float(amp_arr[i]))
                       for i in range(n_frames)]

                UPDATE_EVERY = 500
                for i in range(UPDATE_EVERY, len(pts), UPDATE_EVERY):
                    snapshot = pts[:i]
                    def _partial(s=snapshot):
                        if self.media_path == path:
                            self._waveform_pts = s
                            self._pb_redraw()
                    self.after(0, _partial)

                def _apply():
                    if self.media_path == path:
                        self._waveform_pts = pts
                        self._wf_loading   = False
                        self._pb_redraw()
                self.after(0, _apply)

            except Exception:
                traceback.print_exc()   # 콘솔에 오류 출력
                def _done():
                    self._wf_loading = False
                    self._pb_redraw()
                self.after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()
