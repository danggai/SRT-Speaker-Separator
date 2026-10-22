"""이름 검수: 호칭(씨·님·쌤)이 붙어 쓰인 이름 중 발음이 비슷한 것끼리 묶어 사용자에게 표기를 고르게 함. GUI 없음."""
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from . import correction as cr

HONOR = ("씨", "님", "쌤")
_WORD_RE = re.compile(r"[가-힣]+")


@dataclass
class Group:
    variants: list                  # [(표기, 횟수)] 많은 순
    lines: dict = field(default_factory=dict)   # 표기 → 나온 줄 번호들
    default: str = ""               # 미리 고른 표기 ("" = 그대로 둠)


def _words(text):
    """(이름 후보 형태, 원래 어절, 다음 어절이 호칭인가)."""
    ws = _WORD_RE.findall(text or "")
    for i, w in enumerate(ws):
        honor_next = i + 1 < len(ws) and ws[i + 1] in HONOR
        base, suf = (w, "") if honor_next else cr.split_josa(w)   # '봉마랑 씨'의 '랑'은 조사가 아님
        yield base, suf, honor_next


def _close(a, b):
    """발음이 비슷한가: 자모 거리 짧은 이름은 2, 긴 이름(자모 7개 이상)은 3까지, 길이의 30% 이내."""
    ja, jb = cr.to_jamo(a), cr.to_jamo(b)
    limit = max(1, min(3 if min(len(ja), len(jb)) > 6 else 2, round(0.3 * max(len(ja), len(jb)))))
    return cr._distance(ja, jb, limit) <= limit


def _one_syllable_off(a, b):
    """글자 하나만 다르거나 (개똥·개통) 한 글자가 더 붙은 정도 (개똥·개똥이)."""
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1
    short, long_ = sorted((a, b), key=len)
    return len(long_) - len(short) == 1 and long_.startswith(short)


def find_groups(texts, proper_nouns=()):
    """비슷한 이름 묶음 목록 (자주 나온 묶음 먼저)."""
    named, count, lines = set(), Counter(), defaultdict(list)
    for i, t in enumerate(texts):
        for base, suf, honor_next in _words(t):
            count[base] += 1
            if not lines[base] or lines[base][-1] != i:
                lines[base].append(i)
            if len(base) >= 2 and base not in cr._COMMON and (suf.startswith(HONOR) or honor_next):
                named.add(base)
    dict_words = [w.strip() for w in proper_nouns if w and w.strip()]
    left = sorted(named, key=lambda w: -count[w])
    groups = []
    while left:
        head = left.pop(0)
        members = [head] + [w for w in left if _close(head, w)]
        left = [w for w in left if w not in members]
        anchor = next((d for d in dict_words if any(_close(d, m) for m in members)), "")
        if len(members) < 2 and not (anchor and anchor not in members):
            continue
        variants = [(w, count[w]) for w in sorted(members, key=lambda w: -count[w])]
        g = Group(variants, {w: lines[w] for w in members})
        if anchor:   # 사전에 등록한 이름이 있으면 그 표기가 기본
            g.default = anchor
        elif (variants[0][1] >= 3 and variants[0][1] >= 2 * variants[1][1]
              and all(_one_syllable_off(head, w) for w, _ in variants[1:])):   # 확실한 묶음만 미리 고름
            g.default = variants[0][0]
        groups.append(g)
    groups.sort(key=lambda g: -sum(n for _, n in g.variants))
    return groups


def apply(texts, mapping):
    """{틀린 표기: 바른 표기}대로 바꾼 글자 목록 (조사·호칭은 그대로)."""
    def fix(text):
        def sub(m):
            w = m.group(0)
            if w in mapping:
                return mapping[w]
            base, suf = cr.split_josa(w)
            return mapping[base] + suf if base in mapping else w
        return _WORD_RE.sub(sub, text or "")
    return [fix(t) for t in texts]
