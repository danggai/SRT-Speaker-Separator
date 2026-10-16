"""단축키 익히기: 지금 쓸 수 있는 키 한 줄 표시, 마우스로 한 동작에 단축키 알림."""
import time
import tkinter as tk

from .. import theme
from ..config import _load_config, _save_config
from ..theme import FG_DIM, FG_FAINT
from ..widgets import show_toast

_TIP_TIMES = 2      # 같은 알림은 이 횟수까지만
_TIP_GAP_SEC = 60   # 알림 사이 최소 간격
_LEARNED = 99

# 마우스 동작 → 알림 문구
TIPS = {
    "edge": "재생하면서 Q·W로 시작·끝을 바로 찍을 수 있어요",
    "nudge": "Alt+←/→로 시작을 0.05초씩 옮길 수 있어요 (Shift: 끝)",
    "split": "S 키로도 나눌 수 있어요",
    "merge": "M 키로도 합칠 수 있어요",
    "add": "Ctrl+A로도 자막을 추가할 수 있어요",
    "delete": "Delete·Ctrl+D로도 지울 수 있어요",
    "speaker": "숫자키 1~9로도 화자를 정할 수 있어요",
    "play": "Space로 재생·멈춤",
}


class TipsMixin:
    """단축키 익히기."""

    # ── 상황별 단축키 한 줄 ────────────────────
    def _build_ctx_keys(self, parent, bg):
        self._ctx_keys_bar = tk.Frame(parent, bg=bg, height=18)
        self._ctx_keys_bar.pack(fill="x")
        self._ctx_keys_bar.pack_propagate(False)
        self._ctx_keys_box = tk.Frame(self._ctx_keys_bar, bg=bg)
        self._ctx_keys_box.place(relx=0.5, rely=0.5, anchor="center")
        self._ctx_keys_shown = None

    def _ctx_key_pairs(self):
        """지금 상황에서 보여 줄 (키, 설명) 목록."""
        if not getattr(self, "subtitles", None) or not self._opt("context_keys"):
            return []
        focus = self.focus_get()
        for wi in getattr(self, "_slot_widgets", ()):
            if focus is wi["content"]:
                mods = getattr(self, "_ctx_mods", ())
                if "ctrl" in mods:
                    return [("Ctrl+Space", "다시 듣기"), ("Ctrl+Enter", "저장하고 다음 줄"), ("Ctrl+Z", "되돌리기")]
                if "shift" in mods:
                    return [("Shift+Enter", "줄바꿈"), ("Shift+Tab", "이전 줄")]
                return [("↑↓", "옆 줄 고치기"), ("Ctrl+Space", "다시 듣기"), ("Enter", "저장"), ("Esc", "취소")]
            if focus in (wi["ts_s"], wi["ts_e"]):
                return [("Enter", "저장")]
        if isinstance(focus, tk.Entry):
            return []
        mods = getattr(self, "_ctx_mods", ())
        if "ctrl" in mods:
            return [("Ctrl+Z", "실행 취소"), ("Ctrl+←→", "0.1초 이동"), ("Ctrl+클릭", "여러 줄 고르기"),
                    ("Ctrl+경계 드래그", "옆 줄도 같이"), ("Ctrl+F·H", "검색·바꾸기")]
        if "shift" in mods:
            return [("Shift+↑↓", "여러 줄 고르기"), ("Shift+클릭", "범위 고르기"), ("Shift+←→", "5초 이동"),
                    ("Shift+드래그", "레이어만 옮기기")]
        if len(getattr(self, "_selected_rows", ())) > 1:
            return [("M", "합치기"), ("1~9", "화자"), ("Ctrl+D", "삭제"), ("Esc", "선택 해제")]
        if getattr(self, "_selected_row_idx", None) is None:
            return [("↑↓", "줄 고르기"), ("Space", "재생")]
        if self.player.is_playing:
            return [("Q", "시작 찍기"), ("W", "끝 찍고 다음 줄"), ("S", "여기서 나누기"), ("Space", "멈춤")]
        pairs = [("Space", "재생"), ("Enter", "글자 고치기"), ("Q·W", "시간 찍기"), ("1~9", "화자")]
        if any(s.get("_check") for s in self.subtitles):
            pairs.append(("F", "? 줄 듣기"))
        return pairs

    def _update_ctx_keys(self, event=None):
        box = getattr(self, "_ctx_keys_box", None)
        if box is None:
            return
        pairs = self._ctx_key_pairs()
        if pairs == self._ctx_keys_shown:
            return
        self._ctx_keys_shown = pairs
        for w in box.winfo_children():
            w.destroy()
        bg = box.cget("bg")
        for i, (k, desc) in enumerate(pairs):
            tk.Label(box, text=k, bg=bg, fg=FG_DIM, font=(theme.FONT_FAMILY, 8, "bold")).pack(
                side="left", padx=(14 if i else 0, 3))
            tk.Label(box, text=desc, bg=bg, fg=FG_FAINT, font=(theme.FONT_FAMILY, 8)).pack(side="left")

    def _ctx_mod_key(self, mod, pressed):
        """Ctrl·Shift를 누르고 있는 동안 그 키와 함께 쓰는 단축키를 보여 줌."""
        mods = self.__dict__.setdefault("_ctx_mods", set())
        (mods.add if pressed else mods.discard)(mod)
        self._update_ctx_keys()

    def _ctx_mods_clear(self):
        """창 밖으로 포커스가 나가면 (떼는 이벤트를 못 받으니) 누른 키 표시 해제."""
        try:
            if self.focus_get() is not None:
                return
        except (KeyError, tk.TclError):
            pass
        if getattr(self, "_ctx_mods", None):
            self._ctx_mods.clear()
            self._update_ctx_keys()

    def _schedule_ctx_keys(self):
        """여러 곳에서 불려도 한 번만 갱신."""
        if getattr(self, "_ctx_keys_job", None):
            return

        def run():
            self._ctx_keys_job = None
            self._update_ctx_keys()
        self._ctx_keys_job = self.after_idle(run)

    # ── 마우스로 한 동작에 단축키 알림 ─────────
    def _tip(self, key):
        """마우스로 key 동작을 했을 때 단축키 알림 (몇 번만, 너무 자주는 안 띄움)."""
        if not self._opt("key_tips") or key not in TIPS:
            return
        now = time.time()
        if now - getattr(self, "_last_tip_at", 0) < _TIP_GAP_SEC:
            return
        cfg = _load_config()
        counts = cfg.get("tip_counts", {})
        if counts.get(key, 0) >= _TIP_TIMES:
            return
        counts[key] = counts.get(key, 0) + 1
        cfg["tip_counts"] = counts
        _save_config(cfg)
        self._last_tip_at = now
        show_toast(self, TIPS[key], duration_ms=3500, icon="✦")

    def _tip_learned(self, key):
        """단축키로 직접 했으면 그 알림은 더 띄우지 않음."""
        learned = self.__dict__.setdefault("_tips_learned", set())
        if key in learned:
            return
        learned.add(key)
        cfg = _load_config()
        counts = cfg.get("tip_counts", {})
        if counts.get(key, 0) < _LEARNED:
            counts[key] = _LEARNED
            cfg["tip_counts"] = counts
            _save_config(cfg)
