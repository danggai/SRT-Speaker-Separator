"""자동 자막: 인식 결과를 자막 줄로 나누기·다듬기와 불러오기."""
import os

from harness import ctx, eq, expect, fresh_dir, load_sample, test, wait_until


def _tp():
    from srt_editor import transcript_post
    return transcript_post


@test
def split_uses_word_times_and_interpolates_missing_ones():
    T = _tp()
    seg = {"start": 10.0, "end": 16.0, "text": "오늘은 새로 나온 게임을 같이 해 볼 거예요 정말 재밌을 것 같아요",
           "words": [{"word": "오늘은", "start": 10.0, "end": 10.5}, {"word": "새로", "start": 10.6, "end": 10.9},
                     {"word": "나온", "start": 11.0, "end": 11.3}, {"word": "게임을", "start": 11.4, "end": 11.9},
                     {"word": "같이", "start": 12.0, "end": 12.3}, {"word": "해"},   # 정렬 실패 단어
                     {"word": "볼", "start": 12.6, "end": 12.8}, {"word": "거예요", "start": 12.9, "end": 13.5},
                     {"word": "정말", "start": 14.0, "end": 14.4}, {"word": "재밌을", "start": 14.5, "end": 15.0},
                     {"word": "것", "start": 15.1, "end": 15.2}, {"word": "같아요", "start": 15.3, "end": 15.9}]}
    lines = T.split_segment(seg, 16)
    expect(len(lines) >= 2, f"나뉘어야 함: {lines}")
    eq(lines[0]["start"], 10.0, "첫 줄은 첫 단어 시작")
    eq(lines[-1]["end"], 15.9, "끝 줄은 마지막 단어 끝")
    for a, b in zip(lines, lines[1:]):
        expect(a["end"] <= b["start"] + 1e-6, f"줄끼리 겹치지 않음: {a} {b}")
        expect(a["end"] < 16.0, "단어 시간을 못 찾아도 문장 전체 시간을 받지 않음")


@test
def hallucinations_and_repeats_are_removed():
    T = _tp()
    segs = [{"start": 0, "end": 2, "text": "안녕하세요 여러분"},
            {"start": 3, "end": 5, "text": "시청해 주셔서 감사합니다."},
            {"start": 6, "end": 7, "text": "감사합니다"},
            {"start": 8, "end": 9, "text": "아 진짜"}, {"start": 9, "end": 10, "text": "아 진짜"},
            {"start": 10, "end": 11, "text": "아 진짜"}, {"start": 11, "end": 12, "text": "아 진짜"},
            {"start": 13, "end": 14, "text": "MBC 뉴스 김철수입니다"}]
    lines = T.build_lines(segs, 25)
    eq([l["text"] for l in lines], ["안녕하세요 여러분", "감사합니다", "아 진짜", "MBC 뉴스 김철수입니다"],
       "지어낸 문장은 빼고, 실제로 말할 법한 '감사합니다'와 긴 문장은 남김")
    eq((lines[2]["start"], lines[2]["end"]), (8, 12), "반복 줄은 하나로 합치고 시간은 이어 붙임")


@test
def timing_fix_removes_overlap_and_stretches_tiny_lines():
    T = _tp()
    lines = T.fix_timing([{"start": 0.0, "end": 2.5, "text": "a"}, {"start": 2.0, "end": 2.05, "text": "b"},
                          {"start": 5.0, "end": 6.0, "text": "c"}])
    eq([(l["start"], l["end"]) for l in lines], [(0.0, 2.0), (2.0, 2.3), (5.0, 6.0)])


@test
def period_option_adds_or_strips_whisper_period():
    T = _tp()
    eq(T.finish_text("안녕하세요.", False), "안녕하세요")
    eq(T.finish_text("진짜?", False), "진짜?")
    eq(T.finish_text("안녕하세요", True), "안녕하세요.")


@test
def auto_transcribe_loads_lines_and_removes_temp_file(app):
    import tempfile
    p = load_sample(app, n=4, with_wav=True)
    before = set(os.listdir(tempfile.gettempdir()))
    segs = [{"start": 0.5, "end": 2.0, "text": "안녕하세요 여러분."},
            {"start": 2.5, "end": 4.0, "text": "시청해주셔서 감사합니다"},
            {"start": 4.5, "end": 6.0, "text": "오늘 방송 시작할게요"}]
    app._run_ai_job = lambda job, on_event=None, cancelled=None: {"segments": segs, "language": "ko"}
    app._auto_transcribe(str(p["wav"]))
    wait_until(lambda: len(app.subtitles) == 2 and app.subtitles[0]["text"] == "안녕하세요 여러분", 5)
    eq([s["text"] for s in app.subtitles], ["안녕하세요 여러분", "오늘 방송 시작할게요"])
    left = [f for f in set(os.listdir(tempfile.gettempdir())) - before if f.endswith(".srt")]
    eq(left, [], "임시 SRT는 지움")
    expect(app.save_path.endswith(".srt") and app._unsaved, "미디어 이름으로 저장 대기")
