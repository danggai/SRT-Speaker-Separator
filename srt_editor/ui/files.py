"""SRT/미디어 열기·저장·내보내기."""
import os
import threading
from collections import defaultdict
from tkinter import filedialog
from tkinter import messagebox

from .. import srt_io
from ..media import MEDIA_EXTS, MEDIA_PATTERN
from ..widgets import show_toast
from ..srt_io import (
    DEFAULT_DISPLAY_PATTERN,
    display_to_regex,
    parse_srt,
    read_srt_meta,
    write_srt,
    write_srt_tagged,
)


class FileMixin:
    """SRT/미디어 열기·저장·내보내기."""

    # ── 파일 열기 ─────────────────────────────
    def _close_to_home(self):
        """현재 파일을 닫고 초기 상태(홈)로 돌아감. 미저장 시 확인."""
        if self._unsaved:
            ans = messagebox.askyesnocancel(
                "저장 확인",
                "저장하지 않은 변경사항이 있습니다.\n저장 후 닫을까요?",
                parent=self
            )
            if ans is None:   # 취소
                return
            if ans:           # 예 → 저장
                self.save_file()
                if self._unsaved:  # 저장 실패(경로 없음 등)
                    self.save_file_as()
                    if self._unsaved:
                        return

        # 초기 상태로 리셋
        self._push_undo()
        self.subtitles     = []
        self.speakers      = []
        self.speaker_colors = {}
        self.save_path     = None
        self.media_path    = None
        self._unsaved      = False
        self._undo_stack   = []
        self._redo_stack   = []

        self.player.stop()
        self.title("SRT Speaker Editer")

        self._rebuild_ts_cache()
        self._update_scrollregion()
        self._fill_slots(0)
        self._render_speakers()
        self._update_count()
        self._pb_redraw()
        # 파형 초기화
        self._waveform_pts = []
        self._wf_loading   = False
        try:
            self._set_media_label(None)
        except Exception:
            pass

        # 진짜 홈 화면(드래그앤드롭 안내 오버레이)을 다시 표시
        self._show_overlay()

    def open_file(self):
        """자막(.srt) 또는 음성/영상 파일을 선택해 연다 (드래그 앤 드롭과 같은 처리)."""
        path = filedialog.askopenfilename(
            title="자막(.srt) 또는 음성/영상 파일 선택",
            filetypes=[
                ("자막 및 미디어 파일", "*.srt " + MEDIA_PATTERN),
                ("SRT 자막 파일", "*.srt"),
                ("음성/영상 파일", MEDIA_PATTERN),
                ("모든 파일", "*.*"),
            ],
            parent=self)
        if path:
            self._open_paths([path])

    def _open_paths(self, paths):
        """열기·드래그 앤 드롭 공용: SRT는 바로, 미디어만이면 동명 SRT 또는 자동 생성."""
        srt_paths   = [p for p in paths if p.lower().endswith(".srt")]
        media_paths = [p for p in paths
                       if os.path.splitext(p.lower())[1] in MEDIA_EXTS]

        if srt_paths:
            self._load_srt(srt_paths[0])
            if media_paths:
                self._load_media(media_paths[0])
        elif media_paths:
            mp = media_paths[0]
            srt_candidate = os.path.splitext(mp)[0] + ".srt"
            if os.path.isfile(srt_candidate):
                # 동명 SRT 있으면 바로 로드
                self._load_srt(srt_candidate)
                self._load_media(mp)
            else:
                self._load_media(mp)
                self._ask_auto_transcribe(mp)
        elif paths:
            self._load_srt(paths[0])

    def _load_srt(self, path):
        try:
            self.subtitles = parse_srt(path)
        except Exception as e:
            messagebox.showerror("오류", f"파일을 읽는 중 오류가 발생했습니다:\n{e}", parent=self)
            return

        self.filepath  = path
        self.save_path = path
        # 다른 파일의 편집 기록으로 실행 취소되지 않도록 기록을 비운다
        self._undo_stack = []
        self._redo_stack = []
        _fname = os.path.splitext(os.path.basename(path))[0]
        self.title(f"{_fname} - SRT Speaker Editer")

        self.speaker_colors = {}
        # ── 파일 끝 메타 복원 ──────────────────
        meta = read_srt_meta(path)
        # 저장된 화자 순서를 먼저 따르고, 없는 화자는 등장 순서로 뒤에 추가
        self.speakers = list(dict.fromkeys(
            sp for sp in meta.get("speakers", []) if isinstance(sp, str) and sp))
        for sub in self.subtitles:
            sp = sub.get("speaker", "")
            if sp and sp not in self.speakers:
                self.speakers.append(sp)

        if "speaker_colors" in meta:
            self.speaker_colors = meta["speaker_colors"]
        if "display_pattern" in meta:
            srt_io.g_display_pattern = meta["display_pattern"]
            try:
                srt_io.g_speaker_pattern = display_to_regex(srt_io.g_display_pattern)
            except Exception:
                pass

        self._hide_overlay()
        self._unsaved = False
        self._rebuild_ts_cache()
        self._render_speakers()
        self._render_rows()

        # 동명 미디어 파일 자동 로드
        self._try_load_sibling_media(path)

    def _try_load_sibling_media(self, srt_path):
        """SRT와 같은 폴더, 같은 이름의 미디어 파일이 있으면 자동 로드"""
        base = os.path.splitext(srt_path)[0]
        for ext in MEDIA_EXTS:
            candidate = base + ext
            if os.path.isfile(candidate):
                self._load_media(candidate)
                return

    # ── 미디어 열기 ───────────────────────────
    def open_media(self):
        path = filedialog.askopenfilename(
            title="음성/영상 파일 선택",
            filetypes=[
                ("미디어 파일", MEDIA_PATTERN),
                ("모든 파일", "*.*")
            ],
            parent=self)
        if not path:
            return
        self._load_media(path)

    def _load_media(self, path):
        if not self.player._init_pygame():
            messagebox.showwarning(
                "미디어 재생 불가",
                "pygame 초기화에 실패했습니다.\n"
                "pip install pygame 후 다시 시도하세요.",
                parent=self)
            return

        self.player.stop()
        self.player._filepath = path
        self.player._position = 0.0
        self.player._duration = 0.0
        self.media_path = path

        name = os.path.basename(path)
        self._set_media_label(name)
        self.media_progress_var.set(0)
        self.lbl_dur.configure(text="…")   # 조회 중 표시
        self.lbl_pos.configure(text="0:00:00")
        self.btn_play.configure(text="▶")
        self.after(100, self._pb_redraw)

        # duration 조회를 백그라운드에서 수행 → UI 블로킹 없음
        def _fetch():
            dur = self.player._get_duration(path)
            # 여전히 같은 파일이 로드된 경우에만 반영
            def _apply():
                if self.media_path == path:
                    self.player._duration = dur
                    self.lbl_dur.configure(text=self._fmt_time(dur))
                    # 진행바 현재 위치가 0이면 비율 재계산을 위해 명시적으로 0 재설정
                    if self.media_progress_var.get() == 0:
                        self.media_progress_var.set(0)
                    self._pb_redraw()
            self.after(0, _apply)

        threading.Thread(target=_fetch, daemon=True).start()

        # 파형 추출 시작
        self._waveform_pts = []
        self._pb_redraw()
        self._extract_waveform(path)

    # ── 전체 저장 ─────────────────────────────
    def _do_write_srt(self, path):
        """실제 SRT 파일 쓰기 + 타이틀/상태 갱신. 성공 시 True 반환."""
        try:
            meta = {}
            if self.speakers:
                meta["speakers"] = list(self.speakers)
            if self.speaker_colors:
                meta["speaker_colors"] = self.speaker_colors
            if srt_io.g_display_pattern != DEFAULT_DISPLAY_PATTERN:
                meta["display_pattern"] = srt_io.g_display_pattern
            write_srt_tagged(self.subtitles, path, meta or None)
            self._unsaved = False
            self.save_path = path
            _fn = os.path.splitext(os.path.basename(path))[0]
            self.title(f"{_fn} - SRT Speaker Editer  ✓")
            self.after(800, lambda fn=_fn: self.title(f"{fn} - SRT Speaker Editer"))
            show_toast(self, f"저장했습니다  ·  {os.path.basename(path)}")
            return True
        except Exception as e:
            messagebox.showerror("저장 오류", str(e), parent=self)
            return False

    def save_file(self):
        """저장 — 경로 있으면 바로 덮어쓰기, 없으면 처음 한 번만 경로 묻기."""
        if not self.subtitles:
            messagebox.showwarning("저장", "저장할 자막이 없습니다.", parent=self)
            return
        if self.save_path:
            # 경로 확정 → 바로 덮어쓰기
            self._do_write_srt(self.save_path)
        else:
            # 처음 저장 → 경로 선택
            self.save_file_as()

    def save_file_as(self):
        """다른 이름으로 저장 — 항상 파일 선택 창 표시."""
        if not self.subtitles:
            messagebox.showwarning("저장", "저장할 자막이 없습니다.", parent=self)
            return

        # 기본 디렉터리/파일명 결정
        # 우선순위: 마지막 저장 경로 > 원본 SRT 경로 > 현재 디렉터리
        if self.save_path:
            init_dir  = os.path.dirname(self.save_path)
            init_file = os.path.basename(self.save_path)
        elif hasattr(self, "filepath") and self.filepath:
            base      = os.path.splitext(os.path.basename(self.filepath))[0]
            init_dir  = os.path.dirname(self.filepath)
            init_file = f"{base}_tagged.srt"
        else:
            init_dir  = ""
            init_file = "output.srt"

        path = filedialog.asksaveasfilename(
            title="다른 이름으로 저장",
            initialfile=init_file,
            initialdir=init_dir,
            defaultextension=".srt",
            filetypes=[("SRT 파일", "*.srt"), ("모든 파일", "*.*")],
            confirmoverwrite=False,   # OS 다이얼로그 덮어쓰기 확인 비활성
            parent=self)
        if not path:
            return

        # 파일 존재 시 간단한 확인만
        if os.path.exists(path):
            if not messagebox.askyesno(
                    "덮어쓰기 확인",
                    f"'{os.path.basename(path)}'이(가) 이미 존재합니다.\n덮어쓰시겠습니까?",
                    parent=self):
                return

        self._do_write_srt(path)

    def _update_count(self):
        total      = len(self.subtitles)
        unassigned = sum(1 for s in self.subtitles if not s["speaker"])
        if total == 0:
            self.lbl_count.configure(text="", fg="#FF9A5C")
        elif unassigned == 0:
            self.lbl_count.configure(
                text=f"✓  미지정 없음", fg="#6FCF97")
        else:
            self.lbl_count.configure(
                text=f"▼  미지정 {unassigned}개", fg="#FF9A5C")

    def _goto_next_unassigned(self):
        """현재 선택/스크롤 위치 이후 첫 번째 미지정 화자 행으로 순환 이동."""
        if not self.subtitles:
            return

        # 탐색 시작점: 마지막 이동했던 위치 → 없으면 뷰포트 상단 행
        start = getattr(self, "_last_unassigned_idx", None)
        if start is None:
            start = self._vscroll_top

        n = len(self.subtitles)
        for offset in range(1, n + 1):
            idx = (start + offset) % n
            if not self.subtitles[idx]["speaker"]:
                self._scroll_to_row(idx)
                self._set_row_highlight(idx, True)
                self._selected_row_idx = idx
                self._last_focused_idx = idx
                self._last_unassigned_idx = idx   # 다음 클릭 시 여기서부터
                # 포커스를 버튼이 아닌 루트로 이동
                self.focus_set()
                return

    # ── 내보내기 ──────────────────────────────
    def export(self):
        if not self.subtitles:
            messagebox.showwarning("내보내기", "자막이 없습니다.", parent=self)
            return
        init_dir = os.path.dirname(self.filepath) if self.filepath else ""
        out_dir = filedialog.askdirectory(title="저장할 폴더 선택",
                                          initialdir=init_dir,
                                          parent=self)
        if not out_dir:
            return

        speaker_subs  = defaultdict(list)
        untagged_subs = []
        for sub in self.subtitles:
            entry = {"timestamp": sub["timestamp"], "text": sub["text"]}
            if sub["speaker"]:
                speaker_subs[sub["speaker"]].append(entry)
            else:
                untagged_subs.append(entry)

        saved = []
        for speaker, subs in sorted(speaker_subs.items()):
            path = os.path.join(out_dir, f"{speaker}.srt")
            write_srt(subs, path)   # 내보내기는 태그 없는 순수 자막
            saved.append(f"{speaker}.srt  ({len(subs)}개)")

        if untagged_subs:
            base = os.path.splitext(os.path.basename(self.filepath or "output"))[0]
            path = os.path.join(out_dir, f"{base}_untagged.srt")
            write_srt(untagged_subs, path)
            saved.append(f"{base}_untagged.srt  ({len(untagged_subs)}개)")

        if saved:
            messagebox.showinfo(
                "내보내기 완료",
                "저장된 파일:\n\n" + "\n".join(saved) + f"\n\n📁 {out_dir}",
                parent=self)
        else:
            messagebox.showwarning("내보내기", "저장할 자막이 없습니다.", parent=self)
