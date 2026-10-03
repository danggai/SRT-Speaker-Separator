"""재생 제어, 키보드 이동, 재생 위치 하이라이트."""
import re
import tkinter as tk
from tkinter import ttk


class PlaybackMixin:
    """재생 제어, 키보드 이동, 재생 위치 하이라이트."""

    # ── 미디어 컨트롤 ────────────────────────
    def _on_space_key(self, event):
        """스페이스바: 자막 내용 Entry 편집 중이면 무시, 그 외 재생/정지."""
        focused = self.focus_get()
        # 자막 content Entry 편집 중이면 스페이스 통과
        if isinstance(focused, tk.Entry):
            for wi in self._slot_widgets:
                if wi.get("content") is focused:
                    return
        # 버튼에 포커스가 있으면 앱으로 돌려서 이중 호출 방지
        if isinstance(focused, (tk.Button, ttk.Button)):
            self.focus_set()
        self._media_play_pause()
        return "break"

    def _on_left_key(self, event):
        if isinstance(self.focus_get(), tk.Entry):
            return
        step = self._opt("seek_step_shift") if (event.state & 0x1) else self._opt("seek_step")
        self._media_seek(-step)
        return "break"

    def _on_right_key(self, event):
        if isinstance(self.focus_get(), tk.Entry):
            return
        step = self._opt("seek_step_shift") if (event.state & 0x1) else self._opt("seek_step")
        self._media_seek(+step)
        return "break"

    def _extend_selection(self, delta):
        """Shift+방향키: 선택을 시작한 앵커(_selection_anchor)는 계속 고정한
        채, 커서를 delta만큼 옮겨 범위 선택을 확장/축소한다.
        마지막으로 이동한 행은 _selected_row_idx(= '현재 선택한 행')로
        기억해서, 이후 Shift 없는 조작(방향키 이동, 자막 추가 등)은 이
        행을 기준으로 이어지도록 한다. 앵커 자체는 이후 새로 단독 선택을
        하기 전까지 바뀌지 않는다."""
        if not self.subtitles:
            return
        anchor = getattr(self, "_selection_anchor", None)
        if anchor is None:
            anchor = getattr(self, "_selected_row_idx", None)
        if anchor is None:
            # 아직 아무 것도 선택된 게 없으면 일반 이동과 동일하게 동작
            # (이 행이 다음 Shift 확장의 새 앵커가 됨)
            idx = self._current_nav_idx()
            new_idx = max(0, min(len(self.subtitles) - 1, idx + delta))
            self._select_row(new_idx)
            self._scroll_to_row(new_idx)
            return

        cur = getattr(self, "_selected_row_idx", None)
        if cur is None:
            cur = anchor
        new_cur = max(0, min(len(self.subtitles) - 1, cur + delta))
        if new_cur == cur:
            return

        self._selection_anchor = anchor   # 앵커는 계속 고정
        lo, hi = min(anchor, new_cur), max(anchor, new_cur)
        old = set(self._selected_rows) | {anchor, cur}
        self._selected_rows    = set(range(lo, hi + 1))
        self._selected_row_idx = new_cur   # '현재 선택한 행' = 마지막 이동 위치
        self._last_focused_idx = new_cur
        for idx in old.symmetric_difference(self._selected_rows):
            self._redraw_slot_for(idx)
        self._scroll_to_row(new_cur)

    def _on_shift_arrow_up(self, event):
        if isinstance(self.focus_get(), tk.Entry):
            return
        self._extend_selection(-1)
        return "break"

    def _on_shift_arrow_down(self, event):
        if isinstance(self.focus_get(), tk.Entry):
            return
        self._extend_selection(1)
        return "break"

    def _on_arrow_up(self, event):
        if isinstance(self.focus_get(), tk.Entry):
            return
        if not self.subtitles:
            return "break"
        # 재생 중이면 현재 재생 위치 기준, 아니면 선택 행 기준
        idx = self._current_nav_idx()
        new_idx = max(0, idx - 1)
        if new_idx != idx:
            self._select_row(new_idx)
            self._scroll_to_row(new_idx)
        return "break"

    def _on_arrow_down(self, event):
        if isinstance(self.focus_get(), tk.Entry):
            return
        if not self.subtitles:
            return "break"
        idx = self._current_nav_idx()
        new_idx = min(len(self.subtitles) - 1, idx + 1)
        if new_idx != idx:
            self._select_row(new_idx)
            self._scroll_to_row(new_idx)
        return "break"

    def _page_size(self):
        """현재 창(테이블 뷰포트) 높이에 맞춘 '한 페이지'당 행 수.
        창 크기가 바뀌면 winfo_height()가 그때그때 반영되므로 자동으로
        같이 변한다."""
        return max(1, self.canvas.winfo_height() // self.ROW_H)

    def _on_page_up(self, event):
        if isinstance(self.focus_get(), tk.Entry):
            return
        if not self.subtitles:
            return "break"
        idx = self._current_nav_idx()
        new_idx = max(0, idx - self._page_size())
        if new_idx != idx:
            self._select_row(new_idx)
            self._scroll_to_row(new_idx)
        return "break"

    def _on_page_down(self, event):
        if isinstance(self.focus_get(), tk.Entry):
            return
        if not self.subtitles:
            return "break"
        idx = self._current_nav_idx()
        new_idx = min(len(self.subtitles) - 1, idx + self._page_size())
        if new_idx != idx:
            self._select_row(new_idx)
            self._scroll_to_row(new_idx)
        return "break"

    def _current_nav_idx(self):
        """위아래 이동의 기준 인덱스.
        재생 중이든 아니든 항상 현재 선택/포커스 행 기준으로 동작."""
        idx = getattr(self, "_selected_row_idx", None)
        if idx is None:
            idx = getattr(self, "_last_focused_idx", None)
        return idx if idx is not None else 0

    def _media_play_pause(self):
        if not self.media_path:
            return
        if self.player.is_playing:
            self.player.pause()
            self.btn_play.configure(text="▶")
            self._stop_progress_poll()
            # 하이라이트 유지 — _playing_rows 건드리지 않음
        else:
            self.player.play()
            self.btn_play.configure(text="⏸")
            self._start_progress_poll()

    def _media_stop(self):
        self.player.stop()
        self.btn_play.configure(text="▶")
        self.media_progress_var.set(0)
        self.lbl_pos.configure(text="0:00:00")
        self._stop_progress_poll()
        self._pb_redraw()
        old = self._playing_rows.copy()
        self._playing_rows.clear()
        for idx in old:
            self._redraw_slot_for(idx)

    def _media_seek(self, delta):
        if not self.media_path:
            return
        was_playing = self.player.is_playing
        # poll을 먼저 멈춰야 seek 중 is_playing=False 구간에서 poll이 오작동하지 않음
        self._stop_progress_poll()
        self.player.seek(delta)
        pos = self.player.position
        self.media_progress_var.set(pos)
        self.lbl_pos.configure(text=self._fmt_time(pos))
        self._pb_redraw()
        if was_playing:
            self.btn_play.configure(text="⏸")
            # 재생 안정화 후 poll 시작
            self.after(150, self._start_progress_poll)

    def _on_seek_drag(self, val):
        """진행바 드래그 중 위치 레이블만 갱신 (호환용)"""
        self.lbl_pos.configure(text=self._fmt_time(float(val)))

    def _on_seek_release(self, event):
        """진행바 놓았을 때 해당 위치로 seek (호환용) — 선택 자막은 변경하지 않음"""
        if not self.media_path:
            return
        pos = self.media_progress_var.get()
        was_playing = self.player.is_playing
        self._stop_progress_poll()
        self.player.seek_to(pos)
        if was_playing:
            self.btn_play.configure(text="⏸")
            self.after(150, self._start_progress_poll)

    # ── 진행바 폴링 ──────────────────────────
    def _start_progress_poll(self):
        self._stop_progress_poll()
        self._poll_progress()

    @staticmethod
    def _ts_to_sec(ts_str):
        """'HH:MM:SS,mmm' 또는 'HH:MM:SS.mmm' → float 초. 실패 시 None."""
        m = re.match(r"(\d+):(\d+):(\d+)[,.](\d+)", ts_str.strip())
        if not m:
            return None
        h, mi, s, ms = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        return h * 3600 + mi * 60 + s + ms / 1000.0

    def _get_rows_at(self, pos_sec):
        """현재 재생 위치(초)에 해당하는 자막 행 인덱스 집합 반환.
        _ts_cache(미리 파싱된 float 쌍)를 사용해 regex 반복 호출을 피한다."""
        result = set()
        cache = getattr(self, "_ts_cache", None)
        if cache is None:
            return result
        for i, (t_start, t_end) in enumerate(cache):
            if t_start is None or t_end is None:
                continue
            if t_start <= pos_sec <= t_end:
                result.add(i)
        return result

    ROW_PLAYING = "#1A2A1A"   # 재생 중 하이라이트 색상 (어두운 초록)

    def _set_playing_highlight(self, idx, on: bool):
        """재생 위치 하이라이트를 켜거나 끔 — 슬롯 재렌더로 처리."""
        is_selected = (idx == getattr(self, "_selected_row_idx", None) or idx in getattr(self, "_selected_rows", set()))
        if is_selected:
            return
        self._redraw_slot_for(idx)

    def _update_playback_highlight(self, pos_sec):
        """재생 위치 하이라이트만 갱신 — 선택(_selected_rows)은 건드리지 않음."""
        new_rows = self._get_rows_at(pos_sec)
        if new_rows == self._playing_rows:
            return
        # 빈 구간이면 강조 해제
        changed = self._playing_rows.symmetric_difference(new_rows)
        self._playing_rows = new_rows
        for idx in changed:
            self._redraw_slot_for(idx)

    def _poll_progress(self):
        if self.player.is_playing:
            pos = self.player.position
            prev_pos = getattr(self, "_last_polled_pos", -1.0)
            self._last_polled_pos = pos

            if abs(pos - prev_pos) >= 0.01:
                self.media_progress_var.set(pos)
                self.lbl_pos.configure(text=self._fmt_time(pos))
                dur = self.player.duration
                if dur > 0:
                    self.lbl_dur.configure(text=self._fmt_time(dur))
                # 줌 상태에서 재생헤드가 뷰 밖으로 나가면 뷰 이동
                self._wf_follow_playhead(pos)
                self._pb_redraw()

            self._update_playback_highlight(pos)
            self._seek_job = self.after(16, self._poll_progress)
        else:
            self._last_polled_pos = -1.0
            self.btn_play.configure(text="▶")
            self._seek_job = None

    def _wf_follow_playhead(self, pos):
        """재생 중 헤드가 뷰 밖으로 나가지 않도록 부드럽게 오프셋 추종."""
        dur = self.player.duration
        if dur <= 0 or self._wf_zoom <= 1.0:
            return
        pos_r = pos / dur
        start, end = self._wf_view_range()
        span = end - start
        # 헤드를 뷰의 30%~70% 사이에 유지 (ease toward center)
        target_center = pos_r
        new_offset = target_center - span * 0.35
        new_offset = max(0.0, min(new_offset, 1.0 - span))
        # 현재 오프셋과 너무 차이나지 않으면 스킵 (작은 움직임은 무시)
        if abs(new_offset - self._wf_offset) < span * 0.01:
            return
        # ease: 현재 → 목표를 10% 씩 이동 (부드러운 추종)
        self._wf_offset += (new_offset - self._wf_offset) * 0.15

    def _stop_progress_poll(self):
        if self._seek_job:
            self.after_cancel(self._seek_job)
            self._seek_job = None

    @staticmethod
    def _fmt_time(seconds):
        seconds = int(seconds)
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        return f"{h}:{m:02d}:{s:02d}"

    @staticmethod
    def _sec_to_srt_ts(sec):
        """초 단위 시간을 자막 시작/종료시간과 동일한 SRT 타임스탬프
        형식(00:00:00,000)으로 변환."""
        sec = max(0.0, sec)
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        ms = int(round((sec % 1) * 1000))
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    def _copy_current_time(self, event=None):
        """현재 재생 위치 라벨 클릭 — 자막 시작/종료시간과 동일한 형식으로
        클립보드에 복사."""
        pos = self.media_progress_var.get()
        ts = self._sec_to_srt_ts(pos)
        try:
            self.clipboard_clear()
            self.clipboard_append(ts)
        except Exception:
            return
        # 짧은 시각 피드백(잠깐 흰색으로 반짝)
        try:
            orig_fg = self.lbl_pos.cget("fg")
            self.lbl_pos.configure(fg="#FFFFFF")
            self.after(200, lambda: self.lbl_pos.configure(fg=orig_fg))
        except Exception:
            pass
