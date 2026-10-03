"""앱 동작 설정값과 자동 백업."""
import hashlib
import os
import pathlib
import time
from tkinter import messagebox

from ..config import _load_config, _save_config

# 설정 키 → 기본값
OPTION_DEFAULTS = {
    "startup_open_last": False,   # 시작할 때 마지막 파일 열기
    "update_check": True,         # 새 버전 알림
    "advance_after_assign": False,  # 숫자 키로 화자 지정 후 다음 줄로
    "seek_step": 5,               # ←/→ 이동 간격 (초)
    "seek_step_shift": 30,        # Shift+←/→ 이동 간격 (초)
    "new_sub_len": 5.0,           # 새 자막 기본 길이 (초)
    "click_seek": True,           # 자막 클릭 시 재생 위치 이동
    "lock_timeline": False,       # 타임라인에서 자막 시간 바꾸기 잠금
    "backup_enabled": True,       # 자동 백업
    "backup_minutes": 3,          # 자동 백업 간격 (분)
    "export_dir_mode": "ask",     # 내보내기 폴더: ask | same | fixed
    "export_dir": "",             # fixed일 때 폴더
}

BACKUP_DIR = pathlib.Path.home() / ".srt_speaker_editor_backup"


class OptionsMixin:
    """설정값 읽기/쓰기와 자동 백업."""

    def _opt(self, key):
        opts = self.__dict__.setdefault("_opt_cache", {})
        if key not in opts:
            opts[key] = _load_config().get(key, OPTION_DEFAULTS[key])
        return opts[key]

    def _set_opt(self, key, value):
        self.__dict__.setdefault("_opt_cache", {})[key] = value
        cfg = _load_config()
        cfg[key] = value
        _save_config(cfg)

    # ── 자동 백업 ─────────────────────────
    def _backup_path(self):
        src = getattr(self, "save_path", None) or getattr(self, "filepath", None) or "새 자막"
        name = os.path.splitext(os.path.basename(src))[0]
        tag = hashlib.md5(os.path.abspath(src).encode("utf-8")).hexdigest()[:8]
        return BACKUP_DIR / f"{name}__{tag}.srt"

    def _start_backup_timer(self):
        self._last_backup = time.time()
        self.after(30000, self._backup_tick)

    def _backup_tick(self):
        """저장 안 된 변경이 있으면 설정한 간격마다 백업."""
        try:
            if (self._opt("backup_enabled") and self._unsaved and self.subtitles
                    and time.time() - self._last_backup >= self._opt("backup_minutes") * 60):
                self._write_backup()
        finally:
            self.after(30000, self._backup_tick)

    def _write_backup(self):
        from ..srt_io import write_srt_tagged
        try:
            BACKUP_DIR.mkdir(exist_ok=True)
            src = getattr(self, "save_path", None) or getattr(self, "filepath", None)
            meta = {"backup_of": os.path.abspath(src) if src else "",
                    "speakers": list(self.speakers),
                    "speaker_colors": self.speaker_colors}
            write_srt_tagged(self.subtitles, str(self._backup_path()), meta)
            self._last_backup = time.time()
        except Exception as e:
            print(f"[backup] 실패: {e}")

    def _clear_backup(self):
        """지금 파일의 백업 삭제 (저장했거나 변경을 버린 경우)."""
        try:
            self._backup_path().unlink(missing_ok=True)
        except Exception:
            pass

    def _backup_files(self):
        if not BACKUP_DIR.exists():
            return []
        return sorted(BACKUP_DIR.glob("*.srt"), key=lambda p: p.stat().st_mtime, reverse=True)

    def _backup_size(self):
        return sum(p.stat().st_size for p in self._backup_files())

    def _delete_all_backups(self):
        for p in self._backup_files():
            try:
                p.unlink()
            except Exception:
                pass

    def _offer_backup_restore(self):
        """시작할 때 백업이 남아 있으면 (앱이 비정상 종료된 경우) 복구를 묻는다."""
        files = self._backup_files()
        if not files or self.subtitles:
            return
        latest = files[0]
        when = time.strftime("%m월 %d일 %H:%M", time.localtime(latest.stat().st_mtime))
        name = latest.stem.split("__")[0]
        if not messagebox.askyesno(
                "작업 복구",
                f"저장하지 않고 끝난 작업이 있어요.\n\n{name}  ({when})\n\n복구할까요?",
                parent=self):
            return
        from ..srt_io import read_srt_meta
        original = read_srt_meta(str(latest)).get("backup_of", "")
        self._load_srt(str(latest))
        # 복구한 내용은 원래 파일 이름으로, 저장 안 된 상태로 둠
        self.save_path = self.filepath = original or None
        self._set_doc_title(os.path.splitext(os.path.basename(original))[0] if original
                            else f"{name} (복구)")
        self._unsaved = True
        try:
            latest.unlink()
        except Exception:
            pass
        self._write_backup()

    def _open_last_file(self):
        """'시작할 때 마지막 파일 열기'가 켜져 있으면 최근 파일을 연다."""
        if self.subtitles or not self._opt("startup_open_last"):
            return
        recent = self._recent_files()
        if recent:
            self._open_paths([recent[0]])
