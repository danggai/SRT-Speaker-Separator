"""실행 취소/다시 실행, 잘라내기/복사/붙여넣기, 자막 추가·분할·삭제."""
import copy
import tkinter as tk


class EditingMixin:
    """실행 취소/다시 실행, 잘라내기/복사/붙여넣기, 자막 추가·분할·삭제."""

    # ── Undo / Redo ───────────────────────────
    _UNDO_MAX = 50

    def _snapshot(self):
        # _col_w도 함께 저장해 undo/redo 시 컬럼 너비가 되돌아가지 않도록 함
        return (copy.deepcopy(self.subtitles), list(self.speakers),
                dict(self.speaker_colors), dict(self._col_w))

    def _push_undo(self):
        self._commit_undo(self._snapshot())

    def _commit_undo(self, snapshot):
        """미리 찍어둔 스냅샷을 실행 취소 기록으로 확정."""
        self._undo_stack.append(snapshot)
        if len(self._undo_stack) > self._UNDO_MAX:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def _undo(self):
        # 입력 중인 내용부터 확정 → 그 입력을 되돌림
        self._blur_all_entries()
        if not self._undo_stack:
            return
        self._redo_stack.append(self._snapshot())
        subs, spks, colors, col_w = self._undo_stack.pop()
        self._apply_snapshot(subs, spks, colors, col_w)

    def _redo(self):
        self._blur_all_entries()
        if not self._redo_stack:
            return
        self._undo_stack.append(self._snapshot())
        subs, spks, colors, col_w = self._redo_stack.pop()
        self._apply_snapshot(subs, spks, colors, col_w)

    def _apply_snapshot(self, new_subs, new_spks, new_colors=None, new_col_w=None):
        """스냅샷 복원: 가상 스크롤에서는 데이터 교체 후 전체 재렌더."""
        self.subtitles      = new_subs
        self.speakers       = new_spks
        if new_colors is not None:
            self.speaker_colors = new_colors
        # 컬럼 너비 복원 — 저장된 값이 있으면 그대로, 없으면 speaker 컬럼만 재계산
        if new_col_w is not None:
            self._col_w.update(new_col_w)
        else:
            self._auto_resize_speaker_col()
        self._unsaved = True
        self._rebuild_ts_cache()
        self._update_scrollregion()
        self._layout_header()
        self._fill_slots(min(self._vscroll_top, max(0, len(new_subs) - 1)))
        self._render_speakers()
        self._update_count()
        # 파형 타임라인 갱신
        self._wf_img_cache = None
        self._pb_redraw()

    # ── 클립보드 (자막 행 단위) ───────────────
    def _focused_idx(self):
        idx = getattr(self, "_last_focused_idx", None)
        if idx is not None and 0 <= idx < len(self.subtitles):
            return idx
        return None

    def _selected_targets(self):
        """현재 선택된 인덱스 목록 (정렬). 없으면 _last_focused_idx 단독."""
        sel = getattr(self, "_selected_rows", set())
        if sel:
            return sorted(sel)
        focused = self._focused_idx()
        return [focused] if focused is not None else []

    def _on_delete(self, event=None):
        """Del / Ctrl+D: 선택된 행 일괄 삭제."""
        if isinstance(self.focus_get(), tk.Entry):
            return
        targets = self._selected_targets()
        if not targets:
            return
        self._push_undo()
        # 뒤에서부터 삭제해야 인덱스 안 밀림
        for idx in sorted(targets, reverse=True):
            if 0 <= idx < len(self.subtitles):
                self.subtitles.pop(idx)
        self._selected_rows.clear()
        self._selected_row_idx = None
        self._rebuild_ts_cache()
        self._renumber_rows(0)
        self._update_count()
        self._render_speakers()
        self._unsaved = True
        self._wf_img_cache = None
        self._pb_redraw()
        return "break"

    def _on_cut(self, event):
        if isinstance(self.focus_get(), tk.Entry):
            return
        targets = self._selected_targets()
        if not targets:
            return
        self._clipboard = [copy.deepcopy(self.subtitles[i])
                           for i in targets if i < len(self.subtitles)]
        self._push_undo()
        for idx in sorted(targets, reverse=True):
            if 0 <= idx < len(self.subtitles):
                self.subtitles.pop(idx)
        self._selected_rows.clear()
        self._selected_row_idx = None
        self._rebuild_ts_cache()
        self._renumber_rows(0)
        self._update_count()
        self._render_speakers()
        self._unsaved = True
        self._wf_img_cache = None
        self._pb_redraw()
        return "break"

    def _on_copy(self, event):
        if isinstance(self.focus_get(), tk.Entry):
            return
        targets = self._selected_targets()
        if not targets:
            return
        self._clipboard = [copy.deepcopy(self.subtitles[i])
                           for i in targets if i < len(self.subtitles)]
        return "break"

    def _on_paste(self, event):
        if isinstance(self.focus_get(), tk.Entry):
            return
        if not self._clipboard:
            return
        # clipboard가 단일 dict(구버전)이면 리스트로 감쌈
        clips = self._clipboard if isinstance(self._clipboard, list) else [self._clipboard]
        focused = self._focused_idx()
        insert_at = (focused + 1) if focused is not None else len(self.subtitles)
        self._push_undo()
        for i, sub in enumerate(clips):
            self.subtitles.insert(insert_at + i, copy.deepcopy(sub))
        self._rebuild_ts_cache()
        self._renumber_rows(insert_at)
        self._update_count()
        self._render_speakers()
        self._unsaved = True
        # 붙여넣은 범위 선택
        new_range = set(range(insert_at, insert_at + len(clips)))
        self._selected_rows = new_range
        self._selected_row_idx = insert_at
        for idx in new_range:
            self._redraw_slot_for(idx)
        self.after(50, lambda: self._scroll_to_row(insert_at))
        self._wf_img_cache = None
        self._pb_redraw()
        return "break"

    # ── 자막 추가 ─────────────────────────────
    def add_row_at_time(self, t_sec, duration=2.0):
        """지정한 시간(t_sec)을 시작점으로 하는 새 자막을 시간 순서에 맞는
        위치에 삽입한다. 재생바의 빈 영역 우클릭, '자막 추가' 버튼(현재
        재생 위치 기준) 모두에서 재사용된다."""
        t_sec = max(0.0, t_sec)
        cache = getattr(self, "_ts_cache", [])

        # 시간 순서상 삽입될 위치 계산 (시작 시간이 t_sec보다 뒤인 첫 자막 앞)
        insert_at = len(self.subtitles)
        for i, (s, _e) in enumerate(cache):
            if s is not None and s > t_sec:
                insert_at = i
                break

        # 길이는 duration만큼, 단 다음 자막 시작 전까지만 (겹침 방지용 기본값일 뿐,
        # 사용자가 이후 자유롭게 드래그해 길이를 조절/겹칠 수 있음)
        t_end = t_sec + duration
        if insert_at < len(cache) and cache[insert_at][0] is not None:
            t_end = min(t_end, cache[insert_at][0])
        if t_end <= t_sec:
            t_end = t_sec + 0.5

        def _fmt_ts(sec):
            h = int(sec // 3600); m = int((sec % 3600) // 60); s = int(sec % 60)
            ms = int(round((sec % 1) * 1000))
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

        new_sub = {"timestamp": f"{_fmt_ts(t_sec)} --> {_fmt_ts(t_end)}",
                   "text": "", "speaker": ""}
        self._push_undo()
        self.subtitles.insert(insert_at, new_sub)
        self._rebuild_ts_cache()
        self._renumber_rows(insert_at)
        self._update_count()
        self._render_speakers()
        self._unsaved = True
        self._select_row(insert_at)
        self.after(50, lambda: self._scroll_to_row(insert_at))
        self._wf_img_cache = None
        self._pb_redraw()

    def split_subtitle_at(self, idx, pos):
        """idx번 자막을 현재 재생 위치(pos, 초)를 기준으로 앞/뒤 두 개로
        나눈다. 양쪽 다 원래 텍스트·화자를 그대로 유지한다."""
        if idx < 0 or idx >= len(self.subtitles):
            return False
        cache = getattr(self, "_ts_cache", [])
        if idx >= len(cache):
            return False
        t_s, t_e = cache[idx]
        if t_s is None or t_e is None:
            return False
        # 양쪽 다 최소 길이는 넘어야 분리 가능
        if not (t_s + self._MIN_SUB_DURATION <= pos <= t_e - self._MIN_SUB_DURATION):
            return False

        def _fmt_ts(sec):
            h = int(sec // 3600); m = int((sec % 3600) // 60); s = int(sec % 60)
            ms = int(round((sec % 1) * 1000))
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

        self._push_undo()
        sub     = self.subtitles[idx]
        text    = sub.get("text", "")
        speaker = sub.get("speaker", "")

        sub["timestamp"] = f"{_fmt_ts(t_s)} --> {_fmt_ts(pos)}"
        new_sub = {"timestamp": f"{_fmt_ts(pos)} --> {_fmt_ts(t_e)}",
                   "text": text, "speaker": speaker}
        # 뒷부분도 원본과 같은 레이어를 유지하도록 _lane을 그대로 물려준다.
        # (안 그러면 새 자막은 _lane이 없어 매번 새로 자동 배치되면서
        #  원본과 다른 레이어로 튀어버리는 버그가 있었다)
        if "_lane" in sub:
            new_sub["_lane"] = sub["_lane"]
        self.subtitles.insert(idx + 1, new_sub)

        self._rebuild_ts_cache()
        self._renumber_rows(idx)
        self._update_count()
        self._render_speakers()
        self._unsaved = True
        self._select_row(idx + 1)
        self.after(50, lambda: self._scroll_to_row(idx))
        self._wf_img_cache = None
        self._pb_redraw()
        return True

    def _subtitle_idx_at_playhead(self):
        """현재 재생 위치를 포함하는 자막 인덱스 하나를 고른다.
        여러 개가 겹쳐 있으면 선택된 행 → 선택 행과 같은 화자 → 가까운 행 순으로 고른다."""
        if not self.media_path:
            return None, None
        pos = self.media_progress_var.get()
        rows = self._get_rows_at(pos)
        if not rows:
            return None, pos
        sel = getattr(self, "_selected_row_idx", None)
        if sel in rows:
            return sel, pos
        if len(rows) > 1 and sel is not None and 0 <= sel < len(self.subtitles):
            # 겹친 자막 중 선택한 줄과 같은 화자 → 선택한 줄과 가까운 줄 순으로 고름
            spk = self.subtitles[sel].get("speaker", "")
            same = [i for i in rows if self.subtitles[i].get("speaker", "") == spk]
            return min(same or rows, key=lambda i: abs(i - sel)), pos
        return max(rows), pos

    def _add_subtitle_here(self):
        """재생 위치(미디어 없으면 선택한 줄 다음)에 자막 추가."""
        if self.media_path:
            # 재생 위치부터, 5초 안에 다음 자막이 있으면 그 시작점까지 (없으면 5초)
            self.add_row_at_time(self.media_progress_var.get(), duration=5.0)
        else:
            self.add_row(getattr(self, "_last_focused_idx", None))

    def _add_subtitle_shortcut(self, event=None):
        """단축키 A: 재생 위치에 자막 추가."""
        if isinstance(self.focus_get(), tk.Entry) or not self.subtitles:
            return
        self._add_subtitle_here()
        return "break"

    def _split_subtitle_shortcut(self, event=None):
        """단축키 S: 현재 재생 위치를 포함하는 자막을 그 위치 기준으로
        둘로 나눈다."""
        if isinstance(self.focus_get(), tk.Entry):
            return
        idx, pos = self._subtitle_idx_at_playhead()
        if idx is None:
            return "break"
        self.split_subtitle_at(idx, pos)
        return "break"

    def add_row(self, after_idx=None):
        if after_idx is None:
            after_idx = len(self.subtitles) - 1
        prev_ts_end = "00:00:00,000"
        if 0 <= after_idx < len(self.subtitles):
            ts = self.subtitles[after_idx]["timestamp"]
            parts = ts.split("-->")
            if len(parts) == 2:
                prev_ts_end = parts[1].strip()
        new_sub = {"timestamp": f"{prev_ts_end} --> {prev_ts_end}",
                   "text": "", "speaker": ""}
        insert_at = after_idx + 1
        self._push_undo()
        self.subtitles.insert(insert_at, new_sub)
        self._rebuild_ts_cache()
        self._renumber_rows(insert_at)
        self._update_count()
        self._render_speakers()
        self._unsaved = True
        self._select_row(insert_at)
        self.after(50, lambda: self._scroll_to_row(insert_at))

    # ── 자막 삭제 ─────────────────────────────
    def delete_row(self, idx):
        self._push_undo()
        self.subtitles.pop(idx)
        self._rebuild_ts_cache()
        self._renumber_rows(idx)
        self._update_count()
        self._render_speakers()
        self._unsaved = True
