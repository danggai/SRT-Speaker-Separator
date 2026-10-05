"""교정 후보를 실제 음성으로 다시 확인 (해당 자막 구간만 다시 인식). GUI 없음."""
import re

try:
    from .speech import _ASR_MODES, _DEFAULT_ASR_MODE
except ImportError:   # AI 부품에서 단독 모듈로 불릴 때
    from speech import _ASR_MODES, _DEFAULT_ASR_MODE

_SR = 16000
_PAD = 0.3   # 자막 앞뒤로 더 잘라 들을 초


def _norm(text):
    return re.sub(r"\s+", "", text or "")


def judge(heard, wrong, right):
    """다시 들은 문장에 어느 표기가 나왔는지: 'right' | 'wrong' | None."""
    h = _norm(heard)
    has_right, has_wrong = right in h, wrong in h
    if has_right and not has_wrong:
        return "right"
    if has_wrong and not has_right:
        return "wrong"
    return None


def verify(media_path, items, mode=_DEFAULT_ASR_MODE, device="auto",
           on_progress=None, cancelled=lambda: False):
    """items: [(시작초, 끝초, 바꿀 표기, 바른 표기)] → 항목별 'right' | 'wrong' | None."""
    from faster_whisper import WhisperModel, decode_audio

    if device == "auto":
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            device = "cpu"
    model_name, beam = _ASR_MODES.get(mode, _ASR_MODES[_DEFAULT_ASR_MODE])[:2]
    model = WhisperModel(model_name, device=device,
                         compute_type="float16" if device == "cuda" else "int8")
    audio = decode_audio(media_path, sampling_rate=_SR)

    results = []
    for n, (start, end, wrong, right) in enumerate(items):
        if cancelled():
            break
        a = max(0, int((start - _PAD) * _SR))
        b = min(len(audio), int((end + _PAD) * _SR))
        heard = ""
        if b > a:
            # 두 표기를 똑같이 힌트로 줘서 소리에 가까운 쪽을 고르게 함
            segs, _ = model.transcribe(audio[a:b], language="ko", beam_size=max(beam, 5),
                                       initial_prompt=f"{right}, {wrong}",
                                       vad_filter=False, condition_on_previous_text=False,
                                       without_timestamps=True)
            heard = "".join(s.text for s in segs)
        results.append(judge(heard, wrong, right))
        if on_progress:
            on_progress(n + 1, len(items))
    return results
