"""영상 창: 재생 위치에 맞춰 영상을 보여 주고 지금 자막을 겹쳐 표시."""
import os
import threading
import tkinter as tk
from .. import dialogs as messagebox

from .. import theme
from ..config import _load_config, _save_config
from ..theme import BG, BG3, FG, FG_DIM, _apply_dark_titlebar
from ..video import VIDEO_EXTS, VideoDecoder

_POLL_MS = 30
_VIDEO_BG = "#000000"


class VideoMixin:
    """영상 창 열기·닫기와 화면 갱신."""

    def _is_video(self):
        path = getattr(self, "media_path", None)
        return bool(path) and os.path.splitext(path)[1].lower() in VIDEO_EXTS

    def _toggle_video(self, event=None):
        if event is not None and isinstance(self.focus_get(), tk.Entry):
            return
        win = getattr(self, "_video_win", None)
        if win is not None and win.winfo_exists():
            self._close_video()
            return "break"
        if not self._is_video():
            messagebox.showinfo("영상", "영상 파일(mp4, mkv 등)을 먼저 열어 주세요.", parent=self)
            return "break"
        self._with_av(self._open_video)
        return "break"

    # ── 영상 부품 받기 ───────────────────────
    def _with_av(self, then):
        """영상 부품을 불러와 then(av) 실행. 없으면 받을지 묻는다."""
        from ..video_deps import load_av
        av = load_av()
        if av is not None:
            then(av)
            return
        if getattr(self, "_av_asking", False):
            return
        self._av_asking = True
        try:
            ok = messagebox.askyesno("영상 부품", "영상을 보려면 영상 부품(약 26MB)을 받아야 해요.", parent=self, yes="받기", no="취소")
        finally:
            self._av_asking = False
        if ok:
            self._install_av(then)

    def _install_av(self, then):
        dlg = tk.Toplevel(self)
        dlg.withdraw()
        dlg.title("영상 부품 받는 중")
        dlg.configure(bg=BG)
        dlg.resizable(False, False)
        dlg.transient(self)
        tk.Label(dlg, text="영상 부품 받는 중…", bg=BG, fg=FG,
                 font=(theme.FONT_FAMILY, 10, "bold")).pack(padx=28, pady=(20, 8), anchor="w")
        bar = tk.Canvas(dlg, width=300, height=6, bg=BG3, highlightthickness=0)
        bar.pack(padx=28)
        fill = bar.create_rectangle(0, 0, 0, 6, fill=theme.ACCENT, outline="")
        lbl = tk.Label(dlg, text="", bg=BG, fg=FG_DIM, font=(theme.FONT_FAMILY, 9))
        lbl.pack(padx=28, pady=(6, 20), anchor="w")
        dlg.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - dlg.winfo_reqwidth()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - dlg.winfo_reqheight()) // 3
        dlg.geometry(f"+{max(0, x)}+{max(0, y)}")
        dlg.deiconify()
        _apply_dark_titlebar(dlg)
        dlg.grab_set()
        dlg.protocol("WM_DELETE_WINDOW", lambda: None)   # 받는 동안 닫지 않음

        def progress(done, total):
            def _upd():
                if not dlg.winfo_exists():
                    return
                if total:
                    bar.coords(fill, 0, 0, 300 * done / total, 6)
                lbl.configure(text=f"{done / 1048576:.1f} / {total / 1048576:.1f} MB" if total
                              else f"{done / 1048576:.1f} MB")
            self.after(0, _upd)

        def work():
            from ..video_deps import install_av
            try:
                av, err = install_av(progress), None
            except Exception as e:
                av, err = None, str(e)
            self.after(0, lambda: done(av, err))

        def done(av, err):
            dlg.grab_release()
            dlg.destroy()
            if err:
                messagebox.showerror("영상 부품 받기", f"받지 못했어요.\n{err}", parent=self)
                return
            then(av)
        threading.Thread(target=work, daemon=True).start()

    # ── 영상의 소리 ──────────────────────────
    def _prepare_video_audio(self, path):
        """영상의 소리를 mp3로 뽑아 재생·파형에 쓴다."""
        def start(av):
            if self.media_path != path:
                return
            self._wf_loading = True
            self._pb_redraw()

            def work():
                from ..video import extract_audio
                try:
                    audio, err = extract_audio(av, path), None
                except Exception as e:
                    audio, err = None, str(e)
                self.after(0, lambda: done(audio, err))
            threading.Thread(target=work, daemon=True).start()

        def done(audio, err):
            if self.media_path != path:
                return
            if err:
                self._wf_loading = False
                self._pb_redraw()
                messagebox.showwarning("영상", f"영상의 소리를 불러오지 못했어요.\n{err}", parent=self)
                return
            was_playing = self.player.is_playing
            self.player.stop()
            self.player._filepath = audio
            if was_playing:
                self.btn_play.configure(text="▶")
            self._extract_waveform(path, src=audio)
        self._with_av(start)

    # ── 영상 창 ─────────────────────────────
    def _open_video(self, av):
        try:
            dec = VideoDecoder(av, self.media_path)
        except Exception as e:
            messagebox.showerror("영상", f"영상을 열지 못했어요.\n{e}", parent=self)
            return
        win = tk.Toplevel(self)
        win.withdraw()
        win.title("영상")
        win.configure(bg=_VIDEO_BG)
        sw, sh = dec.size
        w = 640
        h = max(180, int(w * sh / max(1, sw)))
        x = max(0, self.winfo_rootx() + self.winfo_width() - w - 40)
        win.geometry(_load_config().get("video_geometry") or f"{w}x{h}+{x}+{self.winfo_rooty() + 80}")
        win.minsize(240, 135)
        win.transient(self)
        cv = tk.Canvas(win, bg=_VIDEO_BG, highlightthickness=0)
        cv.pack(fill="both", expand=True)
        cv.create_image(0, 0, anchor="center", tags="frame")
        win.protocol("WM_DELETE_WINDOW", self._close_video)
        for key in ("<space>", "<Left>", "<Right>", "<Up>", "<Down>", "<v>", "<V>"):
            win.bind(key, lambda e, k=key: self.event_generate(k) or "break")
        self._video_win, self._video_cv, self._video_dec = win, cv, dec
        self._video_photo = None
        self._video_sub_key = None
        self._video_size = None
        win.deiconify()
        _apply_dark_titlebar(win)
        self._video_tick()

    def _close_video(self):
        dec = getattr(self, "_video_dec", None)
        if dec is not None:
            dec.close()
        win = getattr(self, "_video_win", None)
        if win is not None and win.winfo_exists():
            cfg = _load_config()
            cfg["video_geometry"] = win.geometry()   # 다음에 같은 자리·크기로
            _save_config(cfg)
            win.destroy()
        self._video_win = self._video_dec = None
        self.focus_set()

    def _video_pos(self):
        if self.player.is_playing:
            return self.player.position
        try:
            return float(self.media_progress_var.get())
        except (tk.TclError, ValueError):
            return 0.0

    def _video_tick(self):
        win, cv, dec = self._video_win, self._video_cv, self._video_dec
        if win is None or not win.winfo_exists():
            return
        if dec.path != getattr(self, "media_path", None):   # 다른 미디어를 열었으면
            self._close_video()
            if self._is_video():
                self._toggle_video()
            return
        w, h = cv.winfo_width(), cv.winfo_height()
        if w > 1 and h > 1:
            if (w, h) != self._video_size:
                self._video_size = (w, h)
                cv.coords("frame", w / 2, h / 2)
                self._video_sub_key = None
            pos = self._video_pos()
            dec.request(pos, (w, h))
            img = dec.latest()
            if img is not None:
                from PIL import ImageTk
                self._video_photo = ImageTk.PhotoImage(img)
                cv.itemconfigure("frame", image=self._video_photo)
            self._video_draw_subs(pos, w, h)
        win.after(_POLL_MS, self._video_tick)

    def _video_draw_subs(self, pos, w, h):
        """지금 재생 위치의 자막을 영상 아래쪽에 겹쳐 표시."""
        cache = getattr(self, "_ts_cache", [])
        active = [i for i, (s, e) in enumerate(cache)
                  if s is not None and e is not None and s <= pos < e][:3]
        key = tuple((i, self.subtitles[i].get("text", ""), self.subtitles[i].get("speaker", ""))
                    for i in active if i < len(self.subtitles))
        if key == self._video_sub_key:
            return
        self._video_sub_key = key
        cv = self._video_cv
        cv.delete("sub")
        size = max(10, min(22, h // 18))
        font = (theme.FONT_FAMILY, size, "bold")
        y = h - size
        for i, text, spk in reversed(key):
            for line in reversed(text.split("\n")):
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (1, 1)):
                    cv.create_text(w / 2 + dx, y + dy, text=line, fill="#000000",
                                   font=font, anchor="s", tags="sub")
                cv.create_text(w / 2, y, text=line, fill="#FFFFFF", font=font,
                               anchor="s", tags="sub")
                y -= int(size * 1.6)
            if spk:
                sfont = (theme.FONT_FAMILY, max(8, size - 4), "bold")
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    cv.create_text(w / 2 + dx, y + dy, text=spk, fill="#000000",
                                   font=sfont, anchor="s", tags="sub")
                cv.create_text(w / 2, y, text=spk, fill=self._speaker_color(spk),
                               font=sfont, anchor="s", tags="sub")
                y -= int(size * 1.3)
            y -= size // 2
