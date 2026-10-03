"""파형 추출 (별도 프로세스에서 실행)."""


def extract_waveform_pts(path, n_pts):
    """오디오 파일에서 (시간 비율, 진폭) 목록을 만든다."""
    import librosa
    import numpy as np

    # 22050Hz 모노로 로드 (mp3/wav/flac/ogg/m4a 전부 지원)
    y, sr = librosa.load(path, sr=22050, mono=True)
    hop = max(1, len(y) // n_pts)

    # 항상 axis=0이 frame_length, axis=1이 n_frames
    frames = librosa.util.frame(y, frame_length=hop, hop_length=hop)
    if frames.ndim == 1:
        frames = frames.reshape(-1, 1)

    peak = np.max(np.abs(frames), axis=0)
    rms = np.sqrt(np.mean(frames ** 2, axis=0))
    amp = np.clip(peak * 0.6 + rms * 2.5, 0.0, 1.0)
    n = int(amp.shape[0])
    return [(i / max(1, n - 1), float(amp[i])) for i in range(n)]
