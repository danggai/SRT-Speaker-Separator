"""화면이 필요 없는 순수 로직: SRT 읽기·쓰기, 시간 변환, 설정, 교정 엔진, 음성 처리 보조, 버전 비교."""
import json
import random
import re

from harness import eq, expect, fresh_dir, near, test, write_srt_file, ts, sample_subs


# ───────── SRT 읽기·쓰기 ─────────
def _write(path, text, enc="utf-8"):
    path.write_bytes(text.encode(enc))
    return path


@test
def srtio_parse_basic():
    from srt_editor import srt_io
    p = write_srt_file(fresh_dir() / "a.srt", sample_subs(3))
    subs = srt_io.parse_srt(str(p))
    eq(len(subs), 3, "자막 수")
    eq(subs[0]["speaker"], "민지", "첫 화자")
    eq(subs[1]["speaker"], "준호", "둘째 화자")
    eq(subs[0]["timestamp"], "00:00:00,000 --> 00:00:02,000", "시간")
    expect("[" not in subs[0]["text"], "화자 태그가 글자에 남음")


@test
def srtio_parse_bom_and_crlf():
    from srt_editor import srt_io
    d = fresh_dir()
    p1 = write_srt_file(d / "plain.srt", sample_subs(4))
    p2 = write_srt_file(d / "crlf_bom.srt", sample_subs(4), newline="\r\n", bom=True)
    eq(srt_io.parse_srt(str(p2)), srt_io.parse_srt(str(p1)), "CRLF+BOM 파일이 일반 파일과 달라요")


@test
def srtio_parse_multiline_text():
    from srt_editor import srt_io
    p = _write(fresh_dir() / "m.srt", "1\n00:00:01,000 --> 00:00:03,000\n[민지] 첫 줄\n둘째 줄\n\n2\n00:00:04,000 --> 00:00:05,000\n끝\n")
    subs = srt_io.parse_srt(str(p))
    eq(subs[0]["text"], "첫 줄\n둘째 줄", "여러 줄 자막")
    eq(subs[1]["speaker"], "", "태그 없는 자막")


@test
def srtio_parse_speaker_tag_variants():
    from srt_editor import srt_io
    p = _write(fresh_dir() / "t.srt",
               "1\n00:00:01,000 --> 00:00:02,000\n[김 철수] 공백 있는 이름\n\n"
               "2\n00:00:02,000 --> 00:00:03,000\n[A] [B] 안쪽 대괄호\n\n"
               "3\n00:00:03,000 --> 00:00:04,000\n[민지]붙여 쓴 내용\n")
    subs = srt_io.parse_srt(str(p))
    eq((subs[0]["speaker"], subs[0]["text"]), ("김 철수", "공백 있는 이름"))
    eq((subs[1]["speaker"], subs[1]["text"]), ("A", "[B] 안쪽 대괄호"))
    eq((subs[2]["speaker"], subs[2]["text"]), ("민지", "붙여 쓴 내용"))


@test
def srtio_parse_custom_pattern():
    from srt_editor import srt_io
    pat = srt_io.display_to_regex("(%): &")
    p = _write(fresh_dir() / "c.srt", "1\n00:00:01,000 --> 00:00:02,000\n(민지): 안녕\n")
    subs = srt_io.parse_srt(str(p), pattern=pat)
    eq((subs[0]["speaker"], subs[0]["text"]), ("민지", "안녕"))


@test
def srtio_display_pattern_needs_speaker_marker():
    from srt_editor import srt_io
    try:
        srt_io.display_to_regex("화자 없음 &")
    except ValueError:
        return
    raise AssertionError("% 가 없는 패턴인데 오류가 안 났어요")


@test
def srtio_empty_text_subtitle_survives_reload():
    """텍스트가 빈 자막 줄도 저장 후 다시 열면 그대로 있어야 해요 (조용히 사라지면 데이터 손실)."""
    from srt_editor import srt_io
    d = fresh_dir()
    subs = [{"timestamp": "00:00:01,000 --> 00:00:02,000", "text": "첫째", "speaker": ""},
            {"timestamp": "00:00:03,000 --> 00:00:04,000", "text": "", "speaker": ""},
            {"timestamp": "00:00:05,000 --> 00:00:06,000", "text": "셋째", "speaker": ""}]
    p = d / "e.srt"
    srt_io.write_srt_tagged(subs, str(p))
    back = srt_io.parse_srt(str(p))
    eq([s["timestamp"] for s in back], [s["timestamp"] for s in subs], "빈 자막 줄이 사라졌어요")
    eq([s["text"] for s in back], ["첫째", "", "셋째"])


@test
def srtio_tagged_roundtrip_with_meta():
    from srt_editor import srt_io
    d = fresh_dir()
    subs = sample_subs(6)
    meta = {"speakers": ["준호", "민지"], "speaker_colors": {"민지": "#112233"}, "lanes": 2}
    p = d / "r.srt"
    srt_io.write_srt_tagged(subs, str(p), meta)
    eq(srt_io.parse_srt(str(p)), subs, "저장 후 다시 읽은 자막")
    eq(srt_io.read_srt_meta(str(p)), meta, "메타")


@test
def srtio_plain_write_has_no_tags_or_meta():
    from srt_editor import srt_io
    p = fresh_dir() / "plain.srt"
    srt_io.write_srt([{"timestamp": "00:00:01,000 --> 00:00:02,000", "text": "안녕"}], str(p))
    body = p.read_text(encoding="utf-8")
    expect("[" not in body and "SRT_META" not in body, "내보내기 파일에 태그나 메타가 들어갔어요")


@test
def srtio_meta_corrupt_is_ignored():
    from srt_editor import srt_io
    p = _write(fresh_dir() / "bad.srt", "1\n00:00:01,000 --> 00:00:02,000\n안녕\n\n; SRT_META {깨진 json\n")
    eq(srt_io.read_srt_meta(str(p)), {}, "깨진 메타")
    eq(len(srt_io.parse_srt(str(p))), 1, "메타가 깨져도 자막은 읽혀야 해요")
    eq(srt_io.read_srt_meta(str(fresh_dir() / "없는파일.srt")), {}, "없는 파일")


# ───────── 시간 변환 ─────────
@test
def time_format_boundaries():
    from srt_editor.srt_io import format_srt_time as f
    eq(f(0), "00:00:00,000")
    eq(f(1.5), "00:00:01,500")
    eq(f(61.001), "00:01:01,001")
    eq(f(3661.25), "01:01:01,250")
    eq(f(-5), "00:00:00,000", "음수는 0으로")
    eq(f(1.9996), "00:00:02,000", "밀리초가 1000이 되면 초로 올려야 해요 (예전엔 '01,1000'이 됐음)")
    eq(f(59.9995), "00:01:00,000")
    eq(f(3599.9996), "01:00:00,000")


@test
def time_format_always_valid_and_close():
    from srt_editor.srt_io import format_srt_time, parse_srt_time
    rnd = random.Random(7)
    for _ in range(3000):
        x = rnd.choice([rnd.random() * 5, rnd.random() * 4000, rnd.randint(0, 5000) + 0.9996, rnd.randint(0, 99) + 0.9995])
        s = format_srt_time(x)
        expect(re.fullmatch(r"\d{2}:\d{2}:\d{2},\d{3}", s), f"{x} → '{s}' 형식이 틀려요")
        near(parse_srt_time(s), x, 0.0006, f"{x} → {s}")


@test
def time_parse_forms():
    from srt_editor.srt_io import parse_srt_time as p
    near(p("00:01:02,345"), 62.345)
    near(p("00:01:02.345"), 62.345, what="점 구분")
    near(p("  01:00:00,000 "), 3600.0, what="앞뒤 공백")
    eq(p("깨진값"), None)
    eq(p(""), None)


# ───────── 설정 파일 ─────────
@test
def config_roundtrip_missing_and_corrupt():
    import srt_editor.config as c
    from harness import ctx
    saved = list(c._CONFIG_CANDIDATES)
    try:
        p = fresh_dir() / "cfg.json"
        c._CONFIG_CANDIDATES[:] = [p]
        eq(c._load_config(), {}, "파일이 없을 때")
        expect(c._save_config({"a": 1, "한글": ["가", "나"]}), "저장 실패")
        eq(c._load_config(), {"a": 1, "한글": ["가", "나"]}, "저장 후 읽기")
        p.write_text("{깨짐", encoding="utf-8")
        eq(c._load_config(), {}, "깨진 파일은 빈 설정")
    finally:
        c._CONFIG_CANDIDATES[:] = saved


@test
def config_recent_tokens_dedupe_and_limit():
    import srt_editor.config as c
    cfg = {}
    for t in ["a", "b", "c", "d", "e", "f"]:
        c._add_recent_token(cfg, t)
    eq(cfg["recent_tokens"], ["f", "e", "d", "c", "b"], "최대 5개, 최신순")
    c._add_recent_token(cfg, "d")
    eq(cfg["recent_tokens"][0], "d", "다시 쓴 토큰이 맨 앞으로")
    eq(len(set(cfg["recent_tokens"])), len(cfg["recent_tokens"]), "중복 없음")
    c._add_recent_token(cfg, "")
    eq(len(cfg["recent_tokens"]), 5, "빈 토큰은 무시")


# ───────── 교정 엔진 ─────────
_FIX_TEXTS = ["루파가 왔어요", "루파는 어디 갔어요", "루파한테 말했는데", "루파가 웃었어요",
              "루팍이 먼저 갔어요", "그래서 루파도 같이", "오늘은 루파가 이겼어요"]


@test
def correction_suggest_and_apply_with_josa():
    from srt_editor import correction as cr
    fixes = cr.suggest(_FIX_TEXTS, proper_nouns=["루파"])
    eq([(f.line, f.wrong, f.right) for f in fixes], [(4, "루팍", "루파")], "제안")
    out = cr.apply(_FIX_TEXTS, fixes)
    eq(out[4], "루파가 먼저 갔어요", "조사는 받침에 맞게 '이'→'가'")
    eq(out[:4] + out[5:], _FIX_TEXTS[:4] + _FIX_TEXTS[5:], "다른 줄은 그대로")


@test
def correction_no_false_positives_on_plain_text():
    from srt_editor import correction as cr
    from harness import TEXTS
    eq(cr.suggest(TEXTS * 2), [], "평범한 문장에서 제안이 나오면 안 돼요")
    eq(cr.suggest([]), [], "빈 목록")


@test
def correction_split_josa():
    from srt_editor.correction import split_josa
    eq(split_josa("루파가"), ("루파", "가"))
    eq(split_josa("루파씨가"), ("루파", "씨가"))
    eq(split_josa("고양이"), ("고양이", ""), "'이'로 끝나지만 이름 일부")
    eq(split_josa("나"), ("나", ""), "너무 짧으면 떼지 않음")


# ───────── 음성 처리 보조 ─────────
@test
def speech_assign_speakers_by_overlap():
    from srt_editor.speech import _assign_speakers_by_overlap as a
    turns = [(0.0, 5.0, "A"), (5.0, 10.0, "B")]
    eq(a([(1.0, 3.0), (6.0, 9.0), (4.0, 7.0)], turns), ["A", "B", "B"], "겹침이 큰 쪽")
    eq(a([(20.0, 22.0)], turns), ["B"], "겹치는 게 없으면 가장 가까운 화자")
    eq(a([(None, 3.0), (3.0, 3.0), (5.0, 4.0)], turns), [None, None, None], "잘못된 구간")
    eq(a([(1.0, 2.0)], []), [None], "화자 구간이 없을 때")


@test
def speech_split_segments_by_speaker():
    from srt_editor.speech import _split_segments_by_speaker as sp

    def words(spks, step=0.5):
        return [{"word": f"w{i}", "start": i * step, "end": i * step + step, "speaker": s}
                for i, s in enumerate(spks)]
    seg = {"start": 0.0, "end": 4.0, "text": "x", "speaker": "A", "words": words("AAAABBBB")}
    out = sp([seg])
    eq([o["speaker"] for o in out], ["A", "B"], "화자가 바뀌는 곳에서 분할")
    short = {"start": 0.0, "end": 4.0, "text": "x", "speaker": "A", "words": words("AAABAAAA")}
    eq([o["speaker"] for o in sp([short])], ["A"], "짧게 튄 화자는 이웃에 흡수")
    nowords = {"start": 0, "end": 1, "text": "x", "speaker": "A"}
    eq(sp([nowords]), [nowords], "단어 정보가 없으면 그대로")


class _FakePipeline:
    def __init__(self, clustering):
        self.params = {"clustering": dict(clustering)}
        self.instantiated = None

    def parameters(self, instantiated=True):
        return self.params

    def instantiate(self, params):
        self.instantiated = params


class _FakeDiar:
    def __init__(self, clustering):
        self.model = _FakePipeline(clustering)


@test
def speech_diarize_sensitivity_scales_fa_or_threshold():
    from srt_editor.speech import _apply_diarize_sensitivity as ap
    d = _FakeDiar({"Fa": 0.07})
    ap(d, 50)
    eq(d.model.instantiated, None, "50은 기본값이라 건드리지 않음")
    ap(d, 100)
    near(d.model.params["clustering"]["Fa"], 0.07 * 8, 1e-9, "민감도 100은 Fa ×8")
    d2 = _FakeDiar({"Fa": 0.07})
    ap(d2, 0)
    near(d2.model.params["clustering"]["Fa"], 0.07 / 8, 1e-9, "민감도 0은 Fa ÷8")
    d3 = _FakeDiar({"threshold": 0.7})
    ap(d3, 100)
    near(d3.model.params["clustering"]["threshold"], 0.5, 1e-9, "구버전은 threshold 조절")
    ap(object(), 80)   # 모델이 없어도 오류 없이 넘어가야 함


@test
def speech_friendly_errors():
    from srt_editor.speech import _friendly_transcribe_error as fe
    expect("GPU 메모리" in fe("CUDA out of memory. Tried to allocate"), "메모리 부족 안내")
    expect("HuggingFace" in fe("401 Client Error: Unauthorized"), "토큰 인증 안내")
    expect("드라이버" in fe("cuDNN error"), "CUDA 오류 안내")
    eq(fe("알 수 없는 오류"), "알 수 없는 오류", "모르는 오류는 그대로")


@test
def speech_asr_modes_complete():
    from srt_editor import speech
    for m in ("fast", "balanced", "accurate", "best"):
        expect(m in speech._ASR_MODES, f"{m} 모드 없음")
    expect(speech._DEFAULT_ASR_MODE in speech._ASR_MODES, "기본 모드가 목록에 없음")
    eq(len(speech._DIARIZE_BATCH_MAP), 5, "GPU 사용량 단계")


# ───────── 버전 비교 ─────────
@test
def version_pick_latest_is_numeric_not_alphabetical():
    from srt_editor.version import is_newer, pick_latest
    eq(pick_latest(["1.9.0", "1.10.0", "1.2.0"]), "1.10.0", "문자열 순서로 고르면 1.9.0이 됨")
    eq(pick_latest(["v1.0.0", "v1.0.2", "0.2.0"]), "1.0.2", "v 접두사")
    eq(pick_latest(["latest", "nightly"]), None, "버전이 아닌 이름만 있으면 없음")
    eq(pick_latest([]), None)
    expect(is_newer("1.1.10", "1.1.9"), "1.1.10은 1.1.9보다 새 버전")
    expect(not is_newer("1.1.3", "1.1.3"), "같은 버전")
    expect(not is_newer("1.0.9", "1.1.0"), "낮은 버전")


@test
def media_extension_lists_consistent():
    from srt_editor.media import MEDIA_EXTS, MEDIA_PATTERN
    for e in MEDIA_EXTS:
        expect(e.startswith(".") and e == e.lower(), f"확장자 형식 {e}")
        expect("*" + e in MEDIA_PATTERN.split(), f"{e}가 파일 선택 필터에 없음")
    expect(".wav" in MEDIA_EXTS and ".mp4" in MEDIA_EXTS, "기본 형식")


@test
def safe_filename_rules():
    from srt_editor.ui.files import _safe_filename as sf
    eq(sf('a/b:c*?"<>|d'), "abcd", "쓸 수 없는 문자 제거")
    eq(sf("  끝에 점.. "), "끝에 점", "공백·점 정리")
    eq(sf("CON"), "_CON", "윈도우 예약어")
    eq(sf("민지"), "민지")
