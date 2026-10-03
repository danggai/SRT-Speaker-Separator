"""SRT/미디어 열기·저장·내보내기."""
import os
import re
import tempfile
import threading
from collections import defaultdict
from tkinter import filedialog
from tkinter import messagebox

from .. import srt_io
from ..config import _load_config, _save_config
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

_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
             *(f"LPT{i}" for i in range(1, 10))}


def _safe_filename(name):
    """파일 이름에 쓸 수 없는 문자를 뺀 이름."""
    name = _BAD_CHARS.sub("", name).strip().rstrip(".")
    if name.upper() in _RESERVED:
        name = f"_{name}"
    return name


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
            if not ans:       # 아니오 → 변경을 버리므로 백업도 지움
                self._clear_backup()
            if ans:           # 예 → 저장
                self.save_file()
                if self._unsaved:  # 저장 실패(경로 없음 등)
                    self.save_file_as()
                    if self._unsaved:
                        return

        self._remember_view()
        # 초기 상태로 리셋
        self._push_undo()
        self.subtitles     = []
        self.speakers      = []
        self.speaker_colors = {}
        self._auto_kept    = {}
        self.save_path     = None
        self.media_path    = None
        self._unsaved      = False
        self._undo_stack   = []
        self._redo_stack   = []

        self.player.stop()
        self._set_doc_title(None)

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

    _MAX_RECENT_FILES = 5

    def _add_recent_file(self, path):
        """최근 파일 목록 맨 앞에 추가 (임시 폴더의 파일은 제외)."""
        import tempfile
        path = os.path.abspath(path)
        if os.path.dirname(path) == os.path.abspath(tempfile.gettempdir()):
            return
        cfg = _load_config()
        recent = [p for p in cfg.get("recent_files", []) if p != path]
        cfg["recent_files"] = [path] + recent[:self._MAX_RECENT_FILES - 1]
        _save_config(cfg)

    _MAX_VIEW_STATES = 30

    def _remember_view(self):
        """지금 파일의 스크롤 위치와 선택한 줄을 기억 (다음에 열 때 복원)."""
        path = getattr(self, "save_path", None) or getattr(self, "filepath", None)
        if not path or not self.subtitles:
            return
        import tempfile
        path = os.path.abspath(path)
        if os.path.dirname(path) == os.path.abspath(tempfile.gettempdir()):
            return   # 튜토리얼 예제 등 임시 파일은 기억하지 않음
        cfg = _load_config()
        views = cfg.get("view_states", {})
        views.pop(path, None)
        views[path] = {"top": self._vscroll_top, "sel": getattr(self, "_selected_row_idx", None)}
        while len(views) > self._MAX_VIEW_STATES:   # 오래된 것부터 지움
            views.pop(next(iter(views)))
        cfg["view_states"] = views
        _save_config(cfg)

    def _restore_view(self, path):
        view = _load_config().get("view_states", {}).get(os.path.abspath(path))
        if not view or not self.subtitles:
            return
        n = len(self.subtitles)
        top = view.get("top") or 0
        if 0 < top < n:
            self._vscroll_to(top)
        sel = view.get("sel")
        if isinstance(sel, int) and 0 <= sel < n:
            self._select_row(sel, seek=False)

    def _recent_files(self):
        """존재하는 최근 파일 목록."""
        return [p for p in _load_config().get("recent_files", []) if os.path.isfile(p)]

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
        self._remember_view()   # 열려 있던 파일의 위치부터 기억
        try:
            self.subtitles = parse_srt(path)
        except Exception as e:
            messagebox.showerror("오류", f"파일을 읽는 중 오류가 발생했습니다:\n{e}", parent=self)
            return

        self.filepath  = path
        self.save_path = path
        self._add_recent_file(path)
        # 다른 파일의 편집 기록으로 실행 취소되지 않도록 기록을 비운다
        self._undo_stack = []
        self._redo_stack = []
        _fname = os.path.splitext(os.path.basename(path))[0]
        self._set_doc_title(_fname)

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

        self._restore_speaker_colors(meta.get("speaker_colors"))
        self._restore_auto_colors(meta.get("auto_colors"))
        if "display_pattern" in meta:
            srt_io.g_display_pattern = meta["display_pattern"]
            try:
                srt_io.g_speaker_pattern = display_to_regex(srt_io.g_display_pattern)
            except Exception:
                pass

        self._restore_lanes(meta)

        self._hide_overlay()
        self._unsaved = False
        self._rebuild_ts_cache()
        self._render_speakers()
        self._render_rows()
        self.after_idle(lambda p=path: self._restore_view(p))   # 마지막으로 보던 위치로

        # 동명 미디어 파일 자동 로드
        self._try_load_sibling_media(path)

    def _add_lane_meta(self, meta):
        """레이어 수와 자막별 레이어를 메타에 기록."""
        n = getattr(self, "_wf_manual_lanes", 1)
        if n > 1:
            meta["lanes"] = n
            meta["sub_lanes"] = [s.get("_lane", 0) if isinstance(s.get("_lane"), int) else 0
                                 for s in self.subtitles]

    def _restore_lanes(self, meta):
        """메타의 레이어 수와 자막별 레이어를 복원."""
        n = meta.get("lanes", 1)
        self._wf_manual_lanes = max(1, min(n, self._WF_ABS_MAX_LANES)) if isinstance(n, int) else 1
        sub_lanes = meta.get("sub_lanes")
        if isinstance(sub_lanes, list) and len(sub_lanes) == len(self.subtitles):
            for sub, ln in zip(self.subtitles, sub_lanes):
                if isinstance(ln, int):
                    sub["_lane"] = ln
        self._wf_lanes_src = None
        self._wf_img_cache = None

    def _try_load_sibling_media(self, srt_path):
        """SRT와 같은 폴더, 같은 이름의 미디어 파일이 있으면 자동 로드"""
        base = os.path.splitext(srt_path)[0]
        for ext in MEDIA_EXTS:
            candidate = base + ext
            if os.path.isfile(candidate):
                self._load_media(candidate)
                return

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

        # 파형 추출 시작 (영상은 소리를 뽑은 뒤)
        self._waveform_pts = []
        self._pb_redraw()
        if self._is_video():
            self._prepare_video_audio(path)
        else:
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
            auto = self._auto_color_meta()
            if auto:
                meta["auto_colors"] = auto
            if srt_io.g_display_pattern != DEFAULT_DISPLAY_PATTERN:
                meta["display_pattern"] = srt_io.g_display_pattern
            self._add_lane_meta(meta)
            write_srt_tagged(self.subtitles, path, meta or None)
            self._clear_backup()   # 저장했으니 백업은 필요 없음 (경로가 바뀌기 전 이름으로 지움)
            self._unsaved = False
            self.save_path = path
            self._add_recent_file(path)
            self._remember_view()
            _fn = os.path.splitext(os.path.basename(path))[0]
            self._set_doc_title(_fn)
            self._update_title("  ✓")
            self.after(800, self._update_title)
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

        # 현재 선택 줄 다음부터 (선택 없으면 화면 맨 위 줄부터) 순환 탐색
        start = getattr(self, "_selected_row_idx", None)
        if start is None or start >= len(self.subtitles):
            start = self._vscroll_top - 1

        n = len(self.subtitles)
        for offset in range(1, n + 1):
            idx = (start + offset) % n
            if not self.subtitles[idx]["speaker"]:
                self._scroll_to_row(idx)
                self._select_row(idx)   # 숫자 키가 이 줄에 적용되도록 선택도 옮김
                self.focus_set()
                return

    # ── 내보내기 ──────────────────────────────
    def export(self):
        if not self.subtitles:
            messagebox.showwarning("내보내기", "자막이 없습니다.", parent=self)
            return
        src = getattr(self, "save_path", None) or self.filepath
        init_dir = os.path.dirname(os.path.abspath(src)) if src else ""
        if init_dir and os.path.normcase(init_dir) == os.path.normcase(
                os.path.abspath(tempfile.gettempdir())):
            init_dir = ""   # 임시 폴더면 같은 폴더로 내보내지 않음
        mode = self._opt("export_dir_mode")
        if mode == "same" and init_dir:
            out_dir = init_dir
        elif mode == "fixed" and os.path.isdir(self._opt("export_dir")):
            out_dir = self._opt("export_dir")
        else:
            out_dir = filedialog.askdirectory(title="저장할 폴더 선택",
                                              initialdir=init_dir,
                                              parent=self)
        if not out_dir:
            return
        if self._opt("export_subfolder"):
            out_dir = os.path.join(out_dir, "srts")
            os.makedirs(out_dir, exist_ok=True)

        speaker_subs  = defaultdict(list)
        untagged_subs = []
        for sub in self.subtitles:
            entry = {"timestamp": sub["timestamp"], "text": sub["text"]}
            if sub["speaker"]:
                speaker_subs[sub["speaker"]].append(entry)
            else:
                untagged_subs.append(entry)

        saved, used = [], set()
        for speaker, subs in sorted(speaker_subs.items()):
            name = _safe_filename(speaker) or "화자"
            base_name, n = name, 2
            while name.lower() in used:   # 문자를 빼서 이름이 겹치면 번호 붙임
                name = f"{base_name} ({n})"
                n += 1
            used.add(name.lower())
            path = os.path.join(out_dir, f"{name}.srt")
            write_srt(subs, path)   # 내보내기는 태그 없는 순수 자막
            saved.append(f"{name}.srt  ({len(subs)}개)")

        if untagged_subs:
            base = os.path.splitext(os.path.basename(src or "output"))[0]
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
