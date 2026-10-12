"""재생용 소리: 위치 색인을 넣은 FLAC이고 원본과 시간이 같아야 함 (WAV는 재생 엔진이 시작 위치의 소수점을 버림)."""
from harness import eq, expect, fresh_dir, test, write_wav


@test
def play_audio_is_flac_with_seektable_and_same_timing(app):
    import numpy as np
    import av
    import mutagen.flac as mf
    from srt_editor import video
    d = fresh_dir()
    src = write_wav(d / "src.wav", seconds=40)
    expect(video.needs_play_audio(str(src)), "WAV도 재생용 소리를 만들어야 해요 (소수점 위치 문제)")
    out = video.extract_audio(av, str(src))
    expect(out.endswith(".flac"), f"재생용 소리 형식: {out}")
    expect(not video.needs_play_audio(out), "이미 만든 재생용 소리는 다시 만들지 않음")
    f = mf.FLAC(out)
    pts = [p.first_sample for p in f.seektable.seekpoints]
    eq(len(pts), 4, "10초마다 위치 색인")
    expect(pts == sorted(pts) and pts[0] == 0, f"색인 순서 {pts}")

    def pcm(path):
        with av.open(path) as c:
            res = av.AudioResampler(format="s16", layout="mono", rate=video.PLAY_RATE)
            return np.concatenate([f.to_ndarray().reshape(-1) for fr in c.decode(audio=0)
                                   for f in res.resample(fr)]).astype(np.float32)
    a, b = pcm(str(src)), pcm(out)
    expect(abs(len(a) - len(b)) < 100, f"길이가 원본과 같음 ({len(a)} / {len(b)})")
    n = min(len(a), len(b)) - 100
    expect(np.abs(a[:n] - b[:n]).max() <= 1, "내용이 원본과 같음 (무손실, 시간 어긋남 없음)")


@test
def speed_audio_is_flac_with_seektable(app):
    import mutagen.flac as mf
    from srt_editor import stretch
    d = fresh_dir()
    src = write_wav(d / "src.wav", seconds=40)
    out = stretch.render(str(src), 2.0)
    expect(str(out).endswith(".flac"), f"배속 소리 형식: {out}")
    f = mf.FLAC(str(out))
    expect(abs(f.info.length - 20) < 0.2, f"2배속 길이 {f.info.length}")
    expect(len(f.seektable.seekpoints) >= 2, "위치 색인")
