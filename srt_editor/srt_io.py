"""SRT 파싱/저장과 화자 태그 패턴."""
import json
import re


# ─────────────────────────────────────────────
#  전역 설정 (화자 구분 패턴)
#  저장 형식:  [화자명] 자막내용
#  패턴 표기:  [%] &   (% = 화자, & = 내용)
#  예시: [Alice] 안녕하세요  →  화자=Alice, 내용=안녕하세요
# ─────────────────────────────────────────────
DEFAULT_SPEAKER_PATTERN = r"^\[([^\]]+)\]\s*"
g_speaker_pattern = DEFAULT_SPEAKER_PATTERN

# 사용자에게 보여주는 표시 패턴 (% = 화자명, & = 자막내용)
DEFAULT_DISPLAY_PATTERN = "[%] &"
g_display_pattern = DEFAULT_DISPLAY_PATTERN


def display_to_regex(display: str) -> str:
    """
    사용자 표시 패턴(% = 화자명, & = 자막내용)을 내부 정규식으로 변환.
    % → 첫 번째 캡처 그룹 (.+?), & → 나머지 내용 (무시, 패턴 끝)
    """
    # % 와 & 위치 찾기
    pct = display.find('%')
    amp = display.find('&')
    if pct < 0:
        raise ValueError("패턴에 % (화자명 위치)가 없습니다.")

    # % 앞 부분을 regex 이스케이프, % → (.+?), & 이전까지 구분자 이스케이프
    prefix = display[:pct]
    if amp >= 0 and amp > pct:
        between = display[pct + 1:amp]
    else:
        between = display[pct + 1:]

    regex = "^" + re.escape(prefix) + r"([^\n]+?)" + re.escape(between.rstrip()) + r"\s*"
    return regex

# ─────────────────────────────────────────────
#  SRT 파싱 / 저장
# ─────────────────────────────────────────────
def parse_srt(filepath, pattern=None):
    global g_speaker_pattern
    pat = pattern if pattern is not None else g_speaker_pattern
    with open(filepath, "r", encoding="utf-8-sig") as f:
        content = f.read()
    blocks = re.split(r"\n\s*\n", content.strip())
    subs = []
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        timestamp = lines[1].strip()
        text = "\n".join(lines[2:]).strip()
        try:
            match = re.match(pat, text)
        except re.error:
            match = None
        if match and match.lastindex and match.lastindex >= 1:
            speaker = match.group(1).strip()
            clean   = text[match.end():].strip()
        else:
            speaker = ""
            clean   = text
        subs.append({"timestamp": timestamp, "text": clean, "speaker": speaker})
    return subs


def write_srt(subtitles, filepath):
    lines = []
    for i, sub in enumerate(subtitles, start=1):
        lines.append(str(i))
        lines.append(sub["timestamp"])
        lines.append(sub["text"])
        lines.append("")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_srt_tagged(subtitles, filepath, meta: dict = None):
    global g_display_pattern
    lines = []
    for i, sub in enumerate(subtitles, start=1):
        lines.append(str(i))
        lines.append(sub["timestamp"])
        spk  = sub.get("speaker", "")
        text = sub.get("text", "")
        if spk:
            # 표시 패턴 적용: % → 화자명, & → 내용
            tagged = g_display_pattern.replace("%", spk).replace("&", text)
        else:
            tagged = text
        lines.append(tagged)
        lines.append("")
    if meta:
        lines.append(f"; SRT_META {json.dumps(meta, ensure_ascii=False)}")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


_META_RE = re.compile(r"^;\s*SRT_META\s+(\{.*\})\s*$")

def read_srt_meta(filepath) -> dict:
    """SRT 파일 끝의 ; SRT_META {...} 줄을 읽어 dict 반환. 없으면 {}."""
    try:
        with open(filepath, "r", encoding="utf-8-sig") as f:
            for line in reversed(f.readlines()):
                line = line.rstrip()
                if not line:
                    continue
                m = _META_RE.match(line)
                if m:
                    return json.loads(m.group(1))
                break   # 마지막 비어있지 않은 줄이 메타가 아니면 없는 것
    except Exception:
        pass
    return {}
