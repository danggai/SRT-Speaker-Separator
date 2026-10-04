"""모델 내려받기 진행률 표시."""
import time

from harness import eq, expect, test


@test
def format_progress_lines():
    from srt_editor.model_download import format_progress
    eq(format_progress("모델", 412 * 1048576, 3087 * 1048576), "모델  412 / 3,087 MB (13%)")
    eq(format_progress("모델", 5 * 1048576, None), "모델  5 MB", "전체 크기를 모르면 받은 양만")
    expect(format_progress("m", 10 * 1048576, 5 * 1048576).endswith("(100%)"), "100%를 넘지 않음")


@test
def download_skips_when_cached_and_reports_progress_when_not():
    from srt_editor import model_download as M
    import huggingface_hub
    calls, grown = [], [0]
    orig = (M.is_cached, M._remote_size, M._blobs_size, huggingface_hub.snapshot_download)
    try:
        M.is_cached = lambda *a, **k: True
        huggingface_hub.snapshot_download = lambda *a, **k: "경로"
        M.download("x/y", None, progress=lambda d, t: calls.append((d, t)))
        eq(calls, [], "이미 있으면 진행률을 보내지 않음")

        M.is_cached = lambda *a, **k: False
        M._remote_size = lambda *a, **k: 1000

        def fake_download(*a, **k):
            for step in (200, 500, 900):
                grown[0] = step
                time.sleep(0.45)
            return "경로"
        huggingface_hub.snapshot_download = fake_download
        M._blobs_size = lambda repo: grown[0]
        M.download("x/y", None, progress=lambda d, t: calls.append((d, t)))
        expect(len(calls) >= 3, f"진행률이 여러 번 와야 해요: {calls}")
        eq(calls[-1], (1000, 1000), "끝나면 100%로 마무리")
        expect(all(a[0] <= b[0] for a, b in zip(calls, calls[1:])), "받은 양은 줄어들지 않음")
        eq({t for _, t in calls}, {1000})
    finally:
        M.is_cached, M._remote_size, M._blobs_size, huggingface_hub.snapshot_download = orig


@test
def whisper_and_align_repo_names():
    from srt_editor import model_download as M
    eq(M.whisper_repo("large-v3"), "Systran/faster-whisper-large-v3")
    eq(M.whisper_repo("a/b"), "a/b", "저장소 이름이면 그대로")
    eq(M.align_repo("ko"), "kresnik/wav2vec2-large-xlsr-korean")
    eq(M.align_repo("en"), None, "영어 정렬 모델은 내장이라 내려받을 게 없음")
