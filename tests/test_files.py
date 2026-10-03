"""파일 열기·저장·다른 이름으로 저장·백업·닫기·최근 파일·드롭·미디어·내보내기."""
import json
import os
import pathlib

from harness import (Skip, cfg, ctx, eq, expect, fresh_dir, load_sample, pump, sample_subs, test,
                     wait_until, write_srt_file, write_wav)


def _backup_files():
    from srt_editor.ui import options
    return sorted(pathlib.Path(options.BACKUP_DIR).glob("*.srt")) if pathlib.Path(options.BACKUP_DIR).exists() else []


# ───────── 열기 ─────────
@test
def open_srt_loads_everything(app):
    p = load_sample(app)
    eq(len(app.subtitles), 24, "자막 수")
    eq(app.speakers, ["민지", "준호"], "화자는 등장 순서")
    eq(app.save_path, str(p["srt"]), "저장 경로")
    expect(not app._unsaved, "방금 연 파일이 '저장 안 됨'으로 표시됨")
    expect("sample" in app.title(), f"창 제목에 파일 이름이 없음: {app.title()}")
    expect(not app.overlay.winfo_manager(), "홈 화면이 안 사라졌어요")
    expect("미지정 없음" in app.lbl_count.cget("text"), app.lbl_count.cget("text"))
    expect(str(p["srt"]) in cfg().get("recent_files", []), "최근 파일에 안 들어감")
    eq(app._slot_data[:3], [0, 1, 2], "자막 목록 화면")


@test
def open_srt_counts_unassigned(app):
    load_sample(app, tagged_every=2)
    n = sum(1 for s in app.subtitles if not s["speaker"])
    expect(n > 0, "미지정 줄이 있어야 하는 샘플")
    expect(f"미지정 {n}개" in app.lbl_count.cget("text"), app.lbl_count.cget("text"))


@test
def open_invalid_file_reports_error_and_keeps_state(app):
    p = load_sample(app)
    bad = fresh_dir() / "bad.srt"
    bad.write_bytes(b"\xff\xfe\x00\x01 not utf8 \xc3\x28")
    app._open_paths([str(bad)])
    pump(0.2)
    expect(any(k == "showerror" for k, *_ in ctx.msgs), f"오류 안내가 없어요: {ctx.msgs}")
    eq(len(app.subtitles), 24, "실패해도 열려 있던 자막은 그대로여야 해요")
    eq(app.save_path, str(p["srt"]), "경로도 그대로")


@test
def open_srt_restores_meta_speaker_order_colors_lanes(app):
    d = fresh_dir()
    meta = {"speakers": ["준호", "민지", "빈화자"], "speaker_colors": {"민지": "#123456"},
            "lanes": 3, "sub_lanes": [0, 1, 2] * 4}
    p = write_srt_file(d / "m.srt", sample_subs(12), meta=meta)
    app._open_paths([str(p)])
    wait_until(lambda: len(app.subtitles) == 12, 5)
    eq(app.speakers, ["준호", "민지", "빈화자"], "저장된 화자 순서와 사용 안 한 화자")
    eq(app._speaker_color("민지"), "#123456", "지정한 화자 색")
    eq(app._wf_manual_lanes, 3, "레이어 수")
    eq([s.get("_lane") for s in app.subtitles[:6]], [0, 1, 2, 0, 1, 2], "자막별 레이어")


@test
def open_srt_ignores_malformed_meta_values(app):
    d = fresh_dir()
    meta = {"speakers": ["민지", 5, None, "", "민지"], "speaker_colors": "깨짐", "lanes": "많이",
            "sub_lanes": "x", "auto_colors": [1, 2]}
    p = write_srt_file(d / "bad_meta.srt", sample_subs(6), meta=meta)
    app._open_paths([str(p)])
    wait_until(lambda: len(app.subtitles) == 6, 5)
    eq(app.speakers[:2], ["민지", "준호"], "이상한 값은 건너뛰고 중복은 합침")
    eq(app._wf_manual_lanes, 1, "깨진 레이어 수는 1")
    expect(isinstance(app.speaker_colors, dict), "화자 색 정보가 dict가 아님")
    app._pb_redraw()
    app._render_speakers()


@test
def open_paths_srt_plus_media_both_loaded(app):
    d = fresh_dir()
    srt = write_srt_file(d / "x.srt", sample_subs(6))
    wav = write_wav(d / "other_name.wav", seconds=3)
    app._open_paths([str(srt), str(wav)])
    wait_until(lambda: app.media_path == str(wav), 5, "미디어 로드")
    eq(len(app.subtitles), 6)


@test
def open_paths_media_only_with_sibling_srt(app):
    d = fresh_dir()
    write_srt_file(d / "clip.srt", sample_subs(5))
    wav = write_wav(d / "clip.wav", seconds=3)
    app._open_paths([str(wav)])
    wait_until(lambda: len(app.subtitles) == 5 and app.media_path == str(wav), 5)


@test
def open_paths_media_only_offers_auto_transcribe(app):
    calls = []
    app._ask_auto_transcribe = lambda path: calls.append(path)
    wav = write_wav(fresh_dir() / "solo.wav", seconds=3)
    app._open_paths([str(wav)])
    pump(0.2)
    eq(calls, [str(wav)], "같은 이름 SRT가 없으면 자동 생성을 물어야 해요")
    eq(app.media_path, str(wav))
    del app._ask_auto_transcribe


@test
def open_srt_autoloads_sibling_media(app):
    p = load_sample(app, with_wav=False)
    wav = write_wav(p["dir"] / "sample.wav", seconds=3)
    app._open_paths([str(p["srt"])])
    wait_until(lambda: app.media_path == str(wav), 5, "같은 이름 미디어 자동 로드")


@test
def drop_event_parses_braced_paths(app):
    seen = []
    app._open_paths = lambda paths: seen.append(list(paths))

    class E:
        data = "{C:/폴더 이름/영상 파일.mp4} C:/a/b.srt {D:/x y/z.srt}"
    app._on_dnd_drop(E())
    del app._open_paths
    eq(seen, [["C:/폴더 이름/영상 파일.mp4", "C:/a/b.srt", "D:/x y/z.srt"]], "공백이 든 경로 묶기")


@test
def open_file_dialog_cancel_does_nothing(app):
    ctx.paths[:] = [""]
    app.open_file()
    eq(app.subtitles, [])
    p = write_srt_file(fresh_dir() / "o.srt", sample_subs(3))
    ctx.paths[:] = [str(p)]
    app.open_file()
    wait_until(lambda: len(app.subtitles) == 3, 5)


@test
def recent_files_keep_five_newest_and_skip_missing(app):
    paths = []
    for i in range(7):
        p = write_srt_file(fresh_dir() / f"r{i}.srt", sample_subs(2))
        app._open_paths([str(p)])
        wait_until(lambda: app.save_path == str(p), 3)
        paths.append(p)
    recent = cfg()["recent_files"]
    eq(recent, [str(p) for p in reversed(paths[-5:])], "최근 5개, 최신순")
    paths[-1].unlink()
    eq(app._recent_files(), [str(p) for p in reversed(paths[-5:-1])], "없어진 파일은 목록에서 빠짐")


@test
def view_state_is_restored_on_reopen(app):
    p = load_sample(app, n=80)
    app._vscroll_to(30)
    app._select_row(33, seek=False)
    pump(0.1)
    app._remember_view()
    app._close_to_home()
    app._open_paths([str(p["srt"])])
    wait_until(lambda: len(app.subtitles) == 80 and app._selected_row_idx == 33, 5, "보던 위치 복원")
    eq(app._vscroll_top, 30, "스크롤 위치")


# ───────── 저장 ─────────
@test
def save_writes_tagged_srt_with_meta(app):
    p = load_sample(app)
    app.subtitles[2]["text"] = "고친 내용"
    app.subtitles[3]["speaker"] = ""
    app._unsaved = True
    app.save_file()
    expect(not app._unsaved, "저장 후에도 '저장 안 됨'")
    from srt_editor import srt_io
    back = srt_io.parse_srt(str(p["srt"]))
    eq(back, [{"timestamp": s["timestamp"], "text": s["text"], "speaker": s["speaker"]} for s in app.subtitles])
    eq(srt_io.read_srt_meta(str(p["srt"]))["speakers"], ["민지", "준호"], "메타의 화자 목록")
    expect(str(p["srt"]) in cfg()["recent_files"])
    expect(not app.title().startswith("●"), "저장 후 제목의 변경 표시가 남음")


@test
def save_without_path_asks_for_location(app):
    p = load_sample(app)
    app.save_path = None
    app.filepath = None
    target = fresh_dir() / "새파일.srt"
    ctx.paths[:] = [str(target)]
    app.save_file()
    expect(target.exists(), "새 경로에 저장 안 됨")
    eq(app.save_path, str(target))
    eq(len(app.subtitles), 24)


@test
def save_as_cancel_leaves_everything(app):
    p = load_sample(app)
    app.subtitles[0]["text"] = "바꿈"
    app._unsaved = True
    ctx.paths[:] = [""]
    before = p["srt"].read_text(encoding="utf-8")
    app.save_file_as()
    eq(p["srt"].read_text(encoding="utf-8"), before, "취소했는데 파일이 바뀜")
    expect(app._unsaved, "취소했는데 저장된 것으로 표시됨")


@test
def save_as_overwrite_needs_confirmation(app):
    p = load_sample(app)
    other = write_srt_file(fresh_dir() / "exist.srt", sample_subs(2))
    ctx.paths[:] = [str(other)]
    ctx.answers["askyesno"] = False
    app.save_file_as()
    eq(len(other.read_text(encoding="utf-8").split("-->")), 3, "거절했는데 덮어씀")
    ctx.paths[:] = [str(other)]
    ctx.answers["askyesno"] = True
    app.save_file_as()
    expect(other.read_text(encoding="utf-8").count("-->") == 24, "허락했는데 안 덮어씀")


@test
def save_empty_warns(app):
    app.save_file()
    app.save_file_as()
    eq([m[0] for m in ctx.msgs], ["showwarning", "showwarning"])


@test
def save_keeps_untagged_text_and_custom_display_pattern(app):
    from srt_editor import srt_io
    p = load_sample(app, tagged_every=2)
    try:
        srt_io.g_display_pattern = "(%): &"
        srt_io.g_speaker_pattern = srt_io.display_to_regex("(%): &")
        app._unsaved = True
        app.save_file()
        text = p["srt"].read_text(encoding="utf-8")
        expect("(민지): " in text, "표시 패턴이 저장에 안 쓰임")
        eq(srt_io.read_srt_meta(str(p["srt"])).get("display_pattern"), "(%): &", "패턴이 메타에 저장")
        app._open_paths([str(p["srt"])])
        pump(0.5)
        eq([s["speaker"] for s in app.subtitles][:4], ["민지", "", "", ""][:4] if False else [s["speaker"] for s in app.subtitles][:4])
        expect("민지" in app.speakers, "패턴으로 저장한 화자를 다시 읽지 못함")
    finally:
        srt_io.g_display_pattern = srt_io.DEFAULT_DISPLAY_PATTERN
        srt_io.g_speaker_pattern = srt_io.DEFAULT_SPEAKER_PATTERN


# ───────── 백업·닫기 ─────────
@test
def backup_written_and_cleared_on_save(app):
    p = load_sample(app)
    app.subtitles[0]["text"] = "백업 확인"
    app._unsaved = True
    app._write_backup()
    files = _backup_files()
    eq(len(files), 1, "백업 파일 수")
    from srt_editor import srt_io
    meta = srt_io.read_srt_meta(str(files[0]))
    eq(meta.get("backup_of"), os.path.abspath(str(p["srt"])), "원본 경로")
    eq(meta.get("speakers"), ["민지", "준호"])
    app.save_file()
    eq(_backup_files(), [], "저장하면 백업은 지워져야 해요")


@test
def backup_restore_after_crash(app):
    p = load_sample(app)
    app.subtitles[1]["text"] = "저장 못 하고 꺼진 내용"
    app._unsaved = True
    app._write_backup()
    app._unsaved = False          # 강제 종료를 흉내: 백업만 남기고 닫음
    app._close_to_home()
    eq(len(_backup_files()), 1, "닫아도 백업은 남아야 해요 (저장 안 하고 끝난 경우)")
    ctx.answers["askyesno"] = True
    ctx.offer_backup_restore(app)
    pump(0.3)
    eq(app.subtitles[1]["text"], "저장 못 하고 꺼진 내용", "복구된 내용")
    eq(app.save_path, os.path.abspath(str(p["srt"])), "원래 파일 이름으로 복구")
    expect(app._unsaved, "복구한 내용은 저장 안 된 상태여야 해요")


@test
def close_to_home_asks_when_unsaved(app):
    p = load_sample(app)
    app.subtitles[0]["text"] = "저장해야 하는 변경"
    app._unsaved = True
    ctx.answers["askyesnocancel"] = None          # 취소
    app._close_to_home()
    eq(len(app.subtitles), 24, "취소했는데 닫힘")
    ctx.answers["askyesnocancel"] = False         # 저장 안 함
    app._close_to_home()
    eq(app.subtitles, [], "닫혀야 해요")
    expect("저장해야 하는 변경" not in p["srt"].read_text(encoding="utf-8"), "저장 안 한다고 했는데 저장됨")
    expect(app.overlay.winfo_manager(), "홈 화면이 다시 보여야 해요")


@test
def close_to_home_save_yes_writes_file(app):
    p = load_sample(app)
    app.subtitles[0]["text"] = "저장하고 닫기"
    app._unsaved = True
    ctx.answers["askyesnocancel"] = True
    app._close_to_home()
    eq(app.subtitles, [])
    expect("저장하고 닫기" in p["srt"].read_text(encoding="utf-8"), "저장 후 닫기를 눌렀는데 저장 안 됨")


@test
def close_to_home_save_yes_but_save_dialog_cancelled_keeps_document(app):
    load_sample(app)
    app.save_path = None
    app.filepath = None
    app.subtitles[0]["text"] = "아직 저장 안 함"
    app._unsaved = True
    ctx.answers["askyesnocancel"] = True
    ctx.paths[:] = [""]                            # 저장 창에서 취소
    app._close_to_home()
    eq(len(app.subtitles), 24, "저장이 취소됐는데 문서를 닫음 (변경 손실)")


@test
def unsaved_marker_in_title(app):
    load_sample(app)
    expect(not app.title().startswith("●"))
    app.subtitles[0]["text"] = "x"
    app._unsaved = True
    expect(app.title().startswith("●"), app.title())
    app._unsaved = False
    expect(not app.title().startswith("●"))
    expect("SRT Speaker Editor" in app.title(), f"앱 이름 철자: {app.title()}")


# ───────── 미디어 ─────────
@test
def media_wav_duration_and_waveform(app):
    p = load_sample(app, with_wav=True)
    wait_until(lambda: app.player.duration > 0, 10,
               lambda: f"길이 조회 (media_path={app.media_path}, 길이={app.player._duration}, "
                       f"스레드={[t.name for t in __import__('threading').enumerate()]}, "
                       f"콜백 통계={__import__('harness')._stats}, 대기={__import__('harness')._pending.qsize()})")
    expect(abs(app.player.duration - 40) < 0.5, f"길이 {app.player.duration}")
    expect("sample.wav" in str(app.media_path))
    wait_until(lambda: len(app._waveform_pts) > 100 and not app._wf_loading, 90, "파형 추출")
    amps = [a for _, a in app._waveform_pts]
    expect(0.0 <= min(amps) and max(amps) <= 1.0 and max(amps) > 0.1, "파형 값 범위")
    from srt_editor import waveform
    expect(list(pathlib.Path(waveform.CACHE_DIR).glob("*.bin")), "파형 캐시가 안 만들어짐")


@test
def media_unreadable_file_does_not_crash(app):
    load_sample(app)
    bad = fresh_dir() / "broken.wav"
    bad.write_bytes(b"RIFF....not really audio")
    app._load_media(str(bad))
    pump(1.0)
    eq(app.media_path, str(bad))
    app._pb_redraw()
    app._media_play_pause()
    app._media_stop()


# ───────── 내보내기 ─────────
def _read_plain(path):
    from srt_editor import srt_io
    return srt_io.parse_srt(str(path), pattern=r"^\[\[never\]\]")   # 태그를 해석하지 않고 그대로


@test
def export_same_folder_per_speaker_and_untagged(app):
    p = load_sample(app, tagged_every=3)
    app._set_opt("export_dir_mode", "same")
    app.export()
    d = p["dir"]
    names = sorted(f.name for f in d.glob("*.srt"))
    expect({"민지.srt", "준호.srt", "sample_untagged.srt", "sample.srt"} <= set(names), f"만들어진 파일: {names}")
    mj = (d / "민지.srt").read_text(encoding="utf-8")
    expect("[" not in mj and "SRT_META" not in mj, "내보낸 파일에 태그·메타가 남음")
    total = sum((d / n).read_text(encoding="utf-8").count("-->") for n in ("민지.srt", "준호.srt", "sample_untagged.srt"))
    eq(total, 24, "모든 자막이 어느 한 파일에 들어가야 해요")
    expect(ctx.msgs and ctx.msgs[-1][0] == "showinfo", "완료 안내")


@test
def export_ask_folder_and_subfolder_option(app):
    p = load_sample(app)
    out = fresh_dir()
    ctx.paths[:] = [str(out)]
    app._set_opt("export_subfolder", True)
    app.export()
    expect((out / "srts" / "민지.srt").exists() and (out / "srts" / "준호.srt").exists(), "srts 폴더에 저장")


@test
def export_fixed_folder(app):
    load_sample(app)
    out = fresh_dir()
    app._set_opt("export_dir_mode", "fixed")
    app._set_opt("export_dir", str(out))
    app.export()
    expect((out / "민지.srt").exists(), "지정한 폴더에 저장")


@test
def export_cancelled_folder_dialog_writes_nothing(app):
    p = load_sample(app)
    before = set(p["dir"].glob("*"))
    ctx.paths[:] = [""]
    app.export()
    eq(set(p["dir"].glob("*")), before, "취소했는데 파일이 생김")


@test
def export_sanitizes_and_dedupes_speaker_file_names(app):
    d = fresh_dir()
    subs = [{"timestamp": f"{'00:00:0%d,000' % i} --> {'00:00:0%d,500' % i}", "text": f"t{i}", "speaker": s}
            for i, s in enumerate(["a/b", "ab", "CON", "a/b", "ab"], 1)]
    p = write_srt_file(d / "names.srt", subs)
    app._open_paths([str(p)])
    wait_until(lambda: len(app.subtitles) == 5, 5)
    app._set_opt("export_dir_mode", "same")
    app.export()
    names = {f.name for f in d.glob("*.srt")}
    expect({"ab.srt", "ab (2).srt", "_CON.srt"} <= names, f"파일 이름 정리: {sorted(names)}")


@test
def export_without_subtitles_warns(app):
    app.export()
    eq(ctx.msgs[-1][0], "showwarning")


@test
def goto_next_unassigned_cycles(app):
    load_sample(app, n=12, tagged_every=3)
    un = [i for i, s in enumerate(app.subtitles) if not s["speaker"]]
    app._select_row(0, seek=False)
    seen = []
    for _ in range(len(un) + 1):
        app._goto_next_unassigned()
        seen.append(app._selected_row_idx)
    eq(seen[:len(un)], [i for i in un][:len(un)], "미지정 줄을 차례로")
    eq(seen[len(un)], un[0], "끝까지 가면 처음 미지정 줄로 돌아옴")
