"""음성 인식(whisperx)·화자 분리(pyannote) 로직. GUI 의존성이 없어 평가 도구에서도 쓴다."""


def _friendly_transcribe_error(err_text: str) -> str:
    """whisperx/pyannote/torch에서 올라오는 원시 예외 메시지를 사용자가
    바로 대응할 수 있는 한국어 안내로 변환한다. 알려진 패턴이 아니면
    원본 메시지를 그대로 보여준다."""
    low = (err_text or "").lower()

    if "out of memory" in low or "cuda oom" in low:
        return ("GPU 메모리가 부족합니다 (CUDA out of memory).\n\n"
                "다음을 시도해 보세요:\n"
                "  • 다른 GPU 사용 프로그램(게임, 다른 AI 도구 등)을 끄고 재시도\n"
                "  • 설정 → 화자 분석 탭에서 처리 장치를 CPU로 변경\n"
                "  • 배치 크기를 더 낮은 값으로 변경\n"
                "  • 화자 분리 모드를 '빠름'으로 변경(더 작은 모델 사용)\n\n"
                f"(원본 오류: {err_text[:200]})")
    if "cudnn" in low or "cublas" in low or "cuda error" in low:
        return ("GPU(CUDA) 드라이버/라이브러리 오류가 발생했습니다.\n\n"
                "그래픽 드라이버를 최신으로 업데이트하거나, 설정에서 처리\n"
                "장치를 CPU로 변경한 뒤 다시 시도해 보세요.\n\n"
                f"(원본 오류: {err_text[:200]})")
    if ("401" in err_text or "gated" in low or
            ("access" in low and "token" in low) or "unauthorized" in low):
        return ("HuggingFace 토큰 인증에 실패했습니다.\n\n"
                "화자 분리 모델(pyannote)은 HuggingFace에서 별도 이용 약관\n"
                "동의가 필요합니다. 토큰이 올바른지, 그리고 아래 모델 페이지에서\n"
                "'Access repository'를 눌러 약관에 동의했는지 확인해 주세요:\n"
                "  huggingface.co/pyannote/speaker-diarization-community-1\n\n"
                f"(원본 오류: {err_text[:200]})")
    return err_text


# ── 음성 인식 / 화자 분리 공통 설정 ─────────────────────────────────
# 모드별 Whisper 프로필: (모델, beam_size, VAD onset, VAD offset)
# GPU 환경은 '정확'(large-v3)을 기본/권장으로 한다. CPU에서는 large-v3가
# 매우 느리므로 turbo 계열('균형')을 권장한다.
_ASR_MODES = {
    "fast":     ("large-v3-turbo", 1, 0.500, 0.363),
    "balanced": ("large-v3-turbo", 3, 0.500, 0.363),
    "accurate": ("large-v3",       5, 0.500, 0.363),
    # 방송 클립처럼 짧은 추임새·리액션이 많은 경우를 위해 VAD 감도를 높여
    # 짧은 발화도 놓치지 않도록 한다 (대신 잡음 구간 오인식이 약간 늘 수 있음).
    "best":     ("large-v3",       5, 0.350, 0.250),
}
_DEFAULT_ASR_MODE = "accurate"
_CPU_RECOMMENDED_ASR_MODE = "balanced"
_DIARIZE_BATCH_MAP = [2, 4, 8, 16, 32]


def _load_asr_model(whisperx, mode, device, language=None, asr_hint=None):
    """모드 프로필대로 whisperx 모델을 로드한다. (model, 모델명) 반환.
    language를 지정하면 앞 30초 기반 언어 자동 감지를 건너뛴다 (인트로에
    음악·영어가 섞여 언어를 잘못 감지해 전체 인식이 망가지는 것을 방지)."""
    wmodel, beam, onset, offset = _ASR_MODES.get(mode, _ASR_MODES[_DEFAULT_ASR_MODE])
    # CPU는 int8이 float32 대비 2~3배 빠르고 정확도 차이는 미미하다
    compute = "float16" if device == "cuda" else "int8"
    model = whisperx.load_model(
        wmodel, device,
        compute_type=compute,
        language=language or None,
        asr_options={"beam_size": beam, **(asr_hint or {})},
        vad_options={"vad_onset": onset, "vad_offset": offset},
    )
    return model, wmodel


def _diarize_exclusive(diar_model, audio, num_speakers=0, exact=False):
    """pyannote 화자 분리를 실행해 DataFrame(start, end, speaker)을 반환한다.

    pyannote 4(community-1)의 exclusive 출력을 우선 사용한다. 여러 명이 동시에
    말하는 구간에서 '가장 우세한 화자 하나'만 남긴 결과라, 자막 한 줄에
    화자 하나를 붙이는 용도에 일반 출력보다 잘 맞는다.
    num_speakers > 0일 때 exact면 정확히 N명, 아니면 최대 N명으로 제한한다."""
    import torch
    import pandas as pd
    kw = {}
    if num_speakers and int(num_speakers) > 0:
        kw["num_speakers" if exact else "max_speakers"] = int(num_speakers)
    audio_data = {"waveform": torch.from_numpy(audio[None, :]), "sample_rate": 16000}
    out = diar_model.model(audio_data, **kw)
    ann = getattr(out, "exclusive_speaker_diarization", None)
    if ann is None:
        ann = getattr(out, "speaker_diarization", out)   # 구버전 pyannote 호환
    rows = [(float(seg.start), float(seg.end), spk)
            for seg, _, spk in ann.itertracks(yield_label=True)]
    return pd.DataFrame(rows, columns=["start", "end", "speaker"])


def _apply_diarize_sensitivity(diarize_model, sensitivity):
    """화자 분리 민감도(0~100)를 pyannote 파이프라인의 클러스터링 파라미터에 반영.
    50이면 모델 기본값 그대로, 높을수록 화자를 더 잘게(예민하게) 구분한다.

    community-1(VBx 클러스터링)은 threshold를 바꿔도 화자 수가 거의 변하지
    않고, Fa(화자 간 차이에 대한 민감도)가 화자 수를 결정한다. 실측에서 기본
    Fa=0.07은 비슷한 음색의 두 화자를 한 명으로 합쳤고 0.1 이상에서 분리됐다.
    그래서 VBx면 Fa를 로그 스케일(민감도 0 → 기본값/8, 100 → 기본값×8)로,
    구버전(3.1, 응집 클러스터링)이면 threshold를 ±0.2 범위로 조절한다.
    whisperx/pyannote 버전에 따라 내부 구조가 다를 수 있으므로, 실패해도
    조용히 무시하고 파이프라인 기본 설정으로 계속 진행한다."""
    try:
        sensitivity = max(0, min(100, int(sensitivity)))
        if sensitivity == 50:
            return
        pipeline = getattr(diarize_model, "model", None)
        if pipeline is None or not hasattr(pipeline, "parameters"):
            return
        params = pipeline.parameters(instantiated=True)
        clustering = params.get("clustering") if isinstance(params, dict) else None
        if not isinstance(clustering, dict):
            return
        if "Fa" in clustering:
            clustering["Fa"] = float(clustering["Fa"]) * 8 ** ((sensitivity - 50) / 50.0)
        elif "threshold" in clustering:
            base = float(clustering["threshold"])
            thr = base + (50 - sensitivity) / 50.0 * 0.2
            clustering["threshold"] = max(0.05, min(0.95, thr))
        else:
            return
        pipeline.instantiate(params)
    except Exception:
        pass



def _assign_speakers_by_overlap(intervals, turns):
    """자막 구간 목록 [(start, end), ...]에 화자 구간 [(start, end, speaker), ...]을
    매핑해, 자막마다 화자 ID(없으면 None) 리스트를 반환한다.

    자막 구간과 겹치는 모든 화자 구간의 교집합 길이를 화자별로 합산해 가장
    오래 말한 화자를 고른다. 화자 구간끼리 겹치는 경우(동시 발화)도 모든 구간을
    보므로 놓치지 않는다. 자막 양 끝 10%는 앞뒤 자막과 경계가 애매한 부분이라
    가중치를 절반으로 낮춘다. 겹치는 구간이 없으면 중간점이 가장 가까운 화자."""
    import bisect
    diar_sorted = sorted(turns, key=lambda x: x[0])
    diar_starts = [d[0] for d in diar_sorted]
    # 화자 구간 최대 길이 — 이 값만큼 앞쪽까지만 후보로 본다
    max_len = max((d_e - d_s for d_s, d_e, _ in diar_sorted), default=0.0)

    out = []
    for t_s, t_e in intervals:
        if t_s is None or t_e is None or t_e - t_s <= 0 or not diar_sorted:
            out.append(None)
            continue
        edge = (t_e - t_s) * 0.10
        core_s, core_e = t_s + edge, t_e - edge
        scores = {}
        lo = bisect.bisect_left(diar_starts, t_s - max_len)
        hi = bisect.bisect_left(diar_starts, t_e)
        for d_s, d_e, d_spk in diar_sorted[lo:hi]:
            ov = min(d_e, t_e) - max(d_s, t_s)
            if ov <= 0:
                continue
            core_ov = max(0.0, min(d_e, core_e) - max(d_s, core_s))
            # 핵심 구간 겹침은 1.0, 양 끝 구간 겹침은 0.5 가중치
            scores[d_spk] = scores.get(d_spk, 0.0) + core_ov + (ov - core_ov) * 0.5
        if scores:
            out.append(max(scores, key=scores.__getitem__))
        else:
            t_mid = (t_s + t_e) / 2
            out.append(min(diar_sorted, key=lambda d: abs(t_mid - (d[0] + d[1]) / 2))[2])
    return out


def _split_segments_by_speaker(segments, min_run_sec=0.6):
    """assign_word_speakers로 붙은 '단어별' 화자를 기준으로, 세그먼트를 화자가
    바뀌는 지점마다 나눈다. Whisper 세그먼트는 수십 초까지 길어질 수 있어
    세그먼트 대표 화자 하나만 쓰면 주고받는 대화가 한 화자로 뭉개진다.

    단어 2개 이하이면서 min_run_sec보다 짧게 튀는 화자 구간(A A B A A)은
    오분류일 가능성이 높으므로 이웃 화자로 흡수한다."""
    out = []
    for seg in segments:
        words = seg.get("words") or []
        seg_spk = seg.get("speaker", "")
        if not words:
            out.append(seg)
            continue

        # 화자가 없는 단어(숫자 등 정렬 실패)는 앞 단어의 화자를 이어받는다
        spks, prev = [], None
        for w in words:
            s = w.get("speaker") or prev
            spks.append(s)
            prev = s
        first = next((s for s in spks if s), seg_spk)
        spks = [s or first for s in spks]

        runs = []   # [speaker, 시작 단어 idx, 끝 단어 idx]
        for i, s in enumerate(spks):
            if runs and runs[-1][0] == s:
                runs[-1][2] = i
            else:
                runs.append([s, i, i])

        def _run_dur(r):
            ws = words[r[1]:r[2] + 1]
            st = next((w["start"] for w in ws if "start" in w), None)
            en = next((w["end"] for w in reversed(ws) if "end" in w), None)
            return (en - st) if st is not None and en is not None else 0.0

        while len(runs) > 1:
            # 가장 짧게 튄 구간부터 흡수해야 정상 구간이 먼저 먹히지 않는다
            short = [(_run_dur(r), k) for k, r in enumerate(runs)
                     if r[2] - r[1] < 2 and _run_dur(r) < min_run_sec]
            if not short:
                break
            k = min(short)[1]
            nbrs = [runs[j] for j in (k - 1, k + 1) if 0 <= j < len(runs)]
            runs[k][0] = max(nbrs, key=lambda r: r[2] - r[1])[0]
            merged = []
            for r in runs:
                if merged and merged[-1][0] == r[0]:
                    merged[-1][2] = r[2]
                else:
                    merged.append(r)
            runs = merged

        if len(runs) == 1:
            seg = dict(seg)
            seg["speaker"] = runs[0][0] or seg_spk
            out.append(seg)
            continue

        cursor = seg.get("start", 0.0)
        for spk, i0, i1 in runs:
            ws = words[i0:i1 + 1]
            st = next((w["start"] for w in ws if "start" in w), cursor)
            en = next((w["end"] for w in reversed(ws) if "end" in w), st)
            cursor = en
            out.append({"start": st, "end": en,
                        "text": " ".join(w.get("word", "").strip() for w in ws).strip(),
                        "words": ws, "speaker": spk or ""})
    return out
