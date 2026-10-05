"""음성 인식 결과(whisperx segments) → 자막 줄. 글자 수로 나누기, 단어 시간 맞추기, 헛소리 거르기, 시간 정리."""
import re

MIN_DUR = 0.3       # 이보다 짧은 줄은 늘림 (초)
MIN_RATIO = 0.45    # 줄이 이만큼 찼을 때만 문장 경계에서 일찍 끊음

# 한국어 종결어미 (문장·절 경계를 대략 판단)
_KOR_SENTENCE_ENDERS = (
    "습니다", "입니다", "합니다", "됩니다", "였습니다", "했습니다",
    "였다", "했다", "이었다",
    "이에요", "예요", "이네요", "네요", "군요", "구나", "잖아요", "잖아",
    "거든요", "거예요", "을까요", "ㄹ까요", "나요", "가요", "까요",
    "아요", "어요", "해요", "돼요", "됐어요", "했어요", "이었어요", "였어요",
    "습니까", "합니까", "인가요", "인데요", "는데요", "던데요",
    "다", "죠", "네", "까", "자", "라", "니",
)

# 조용한 구간에서 Whisper가 지어내는 대표 문장 (공백·문장부호 뺀 형태)
HALLUCINATIONS = (
    "시청해주셔서감사합니다", "시청해주셔서고맙습니다", "구독과좋아요부탁드립니다", "구독좋아요알림설정",
    "구독과좋아요", "좋아요와구독", "다음영상에서만나요", "다음시간에만나요", "mbc뉴스", "kbs뉴스",
    "sbs뉴스", "자막제공", "한글자막", "자막by", "끝까지시청해주셔서감사합니다", "오늘도시청해주셔서감사합니다",
)
_NORM_RE = re.compile(r"[\s.,!?…~\"'“”‘’()\[\]-]+")


def _norm(text):
    return _NORM_RE.sub("", text).lower()


def is_hallucination(text):
    n = _norm(text)
    return bool(n) and any(n == h or (h in n and len(n) <= len(h) + 4) for h in HALLUCINATIONS)


def clause_break_score(word):
    """어절이 문장·절 경계로 알맞은가: 2=문장부호, 1=종결어미, 0=아님."""
    if not word:
        return 0
    core = word.rstrip("\"'”’」』)]")
    if core and core[-1] in ".!?…":
        return 2
    return 1 if any(core.endswith(e) for e in _KOR_SENTENCE_ENDERS) else 0


def split_by_chars(text, max_chars):
    """글자 수 제한 안에서, 문장 경계가 있으면 거기서 먼저 끊는다."""
    if len(text) <= max_chars:
        return [text]
    words = text.split()
    if not words:
        return [text]
    lines, start, n = [], 0, len(words)
    while start < n:
        cur_len, end, last_good = 0, -1, -1
        i = start
        while i < n:
            add = len(words[i]) + (1 if i > start else 0)
            if cur_len + add > max_chars:
                break
            cur_len += add
            end = i
            if clause_break_score(words[i]) > 0 and cur_len >= max_chars * MIN_RATIO:
                last_good = i
            i += 1
        if end < start:   # 한 어절이 max_chars보다 김: 글자로 자름
            w = words[start]
            lines.extend(w[k:k + max_chars] for k in range(0, len(w), max_chars))
            start += 1
            continue
        cut = last_good if 0 <= last_good < end and end + 1 < n else end
        lines.append(" ".join(words[start:cut + 1]))
        start = cut + 1
    return lines or [text]


def _time_at(anchors):
    """(글자 위치, 시각) 기준점으로 글자 위치 → 시각 (사이는 직선 보간)."""
    def at(pos):
        if pos <= anchors[0][0]:
            return anchors[0][1]
        for (p0, t0), (p1, t1) in zip(anchors, anchors[1:]):
            if pos <= p1:
                return t0 if p1 == p0 else t0 + (t1 - t0) * (pos - p0) / (p1 - p0)
        return anchors[-1][1]
    return at


def split_segment(seg, max_chars):
    """segment 하나를 줄로 나누고, 단어 시간(없으면 글자 비례)으로 각 줄의 시간을 정한다."""
    t_s = float(seg.get("start", 0.0))
    t_e = float(seg.get("end", t_s + 1.0))
    text = (seg.get("text") or "").strip()
    lines = split_by_chars(text, max_chars)
    total = sum(len(l.replace(" ", "")) for l in lines) or 1
    # 단어 시간 기준점: 공백을 뺀 글자 위치 기준
    anchors, pos = [(0, t_s)], 0
    for w in seg.get("words") or []:
        wl = len((w.get("word") or "").replace(" ", ""))
        if "start" in w and "end" in w:
            anchors.append((pos, float(w["start"])))
            anchors.append((pos + wl, float(w["end"])))
        pos += wl
    anchors.append((max(total, pos), t_e))
    anchors.sort(key=lambda a: a[0])
    fixed, last = [], t_s   # 시각이 거꾸로 가지 않게
    for p, t in anchors:
        last = max(last, min(t, t_e))
        fixed.append((p, last))
    at = _time_at(fixed)
    out, pos = [], 0
    for line in lines:
        n = len(line.replace(" ", ""))
        out.append({"start": at(pos), "end": at(pos + n), "text": line, "speaker": seg.get("speaker", "")})
        pos += n
    return out


def finish_text(text, add_period):
    text = text.strip()
    if not text:
        return text
    if add_period:
        return text if text[-1] in "。.!?！？" else text + "."
    return text[:-1].rstrip() if text[-1] in ".。" else text   # Whisper가 붙인 온점만 뺌 (?! 유지)


def drop_repeats(lines, keep=1, run=3):
    """같은 줄이 run번 이상 연달아 나오면 keep개만 남긴다 (Whisper 반복 오류)."""
    out, i = [], 0
    while i < len(lines):
        j = i
        while j + 1 < len(lines) and _norm(lines[j + 1]["text"]) == _norm(lines[i]["text"]):
            j += 1
        out.extend(lines[i:i + (keep if j - i + 1 >= run else j - i + 1)])
        if j - i + 1 >= run:
            out[-1] = dict(out[-1], end=lines[j]["end"])
        i = j + 1
    return out


def fix_timing(lines, min_dur=MIN_DUR):
    """시간순 정렬, 앞 줄이 다음 줄과 겹치지 않게, 너무 짧은 줄은 늘림."""
    lines = sorted(lines, key=lambda l: l["start"])
    for k, l in enumerate(lines):
        nxt = lines[k + 1]["start"] if k + 1 < len(lines) else None
        if l["end"] - l["start"] < min_dur:
            l["end"] = l["start"] + min_dur
        if nxt is not None and l["end"] > nxt:
            l["end"] = max(nxt, l["start"] + 0.05)
    return lines


def build_lines(segments, max_chars=25, add_period=False):
    """whisperx segments → 자막 줄 목록 [{start, end, text, speaker}]."""
    lines = []
    for seg in segments:
        if is_hallucination(seg.get("text") or ""):
            continue
        for l in split_segment(seg, max_chars):
            l["text"] = finish_text(l["text"], add_period)
            if l["text"] and not is_hallucination(l["text"]):
                lines.append(l)
    return fix_timing(drop_repeats(lines))
