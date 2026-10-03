"""자동 자막 오프라인 교정 제안 (반복 단어 통일, 고유명사 사전). GUI 없음."""
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

_CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
_JUNG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
_JONG = ("", "ㄱ", "ㄲ", "ㄳ", "ㄴ", "ㄵ", "ㄶ", "ㄷ", "ㄹ", "ㄺ", "ㄻ", "ㄼ", "ㄽ", "ㄾ",
         "ㄿ", "ㅀ", "ㅁ", "ㅂ", "ㅄ", "ㅅ", "ㅆ", "ㅇ", "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ")

# 단어 뒤에 붙는 조사·호칭 (긴 것부터 떼어낸다)
_JOSA = sorted([
    "이랑", "에게", "한테", "에서", "까지", "부터", "으로", "처럼", "보다", "께서", "이나", "이란",
    "이", "가", "은", "는", "을", "를", "의", "에", "도", "만", "랑", "와", "과", "로", "야", "아",
], key=len, reverse=True)
_HONORIFIC = ("씨", "님")   # 조사 앞에 붙는 호칭 ('루파씨의' = 루파 + 씨 + 의)
_JOSA_SET = set(_JOSA)

# 비슷하게 생겼지만 서로 다른 흔한 말 — 통일 대상에서 제외
_COMMON = set("""
그거 그게 이거 이게 저거 저게 거기 여기 저기 그냥 근데 진짜 정말 너무 아니 이제 그럼 그래 그런 이런 저런
우리 저희 제가 내가 니가 너가 나도 저도 뭐가 뭐야 어디 언제 누가 그쵸 그죠 맞아 맞죠 네네 아뇨 아니요
그리고 그래서 그러면 그러니까 하나 둘 셋 오늘 내일 어제 지금 아까 다시 같이 많이 조금 약간 엄청 완전
""".split())

# 서술어 어미로 끝나는 말은 제외
_PREDICATE_END = set("다요어아지네게고서니까죠냐래데며면자해했던든는은을음요잖나라봐줘")

# 두 글자 단어는 이 호칭과 쓰인 적 있는 이름만 통일 대상
_NAME_SUFFIX = ("씨", "님")

_TOKEN_RE = re.compile(r"[가-힣]+")


def to_jamo(s):
    out = []
    for ch in s:
        code = ord(ch) - 0xAC00
        if 0 <= code < 11172:
            out.append(_CHO[code // 588])
            out.append(_JUNG[(code % 588) // 28])
            if code % 28:
                out.append(_JONG[code % 28])
        else:
            out.append(ch)
    return out


def _distance(a, b, limit):
    """편집 거리 (limit 초과 시 limit+1)."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        best = i
        for j, cb in enumerate(b, 1):
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            cur.append(v)
            best = min(best, v)
        if best > limit:
            return limit + 1
        prev = cur
    return prev[-1]


# 조사·호칭으로 끝나 보이지만 한 단어인 말
_NO_SPLIT = set("""
아가씨 아저씨 날씨 글씨 솜씨 마음씨 말씨 맵씨 하느님 하나님 선생님 어머님 아버님 형님 누님 손님
사장님 부장님 팀장님 고객님 여러분 아이 고양이 강아지 거기 여기 저기
""".split())


def split_josa(word):
    """'루파씨가' → ('루파', '씨가'). 남는 말이 2글자 미만이면 떼지 않는다."""
    for w in _NO_SPLIT:
        if word.startswith(w) and (len(word) == len(w) or word[len(w):] in _JOSA_SET):
            return w, word[len(w):]
    base, suffix = word, ""
    for j in _JOSA:
        if base.endswith(j) and len(base) - len(j) >= 2:
            base, suffix = base[:-len(j)], j
            break
    for h in _HONORIFIC:
        if base.endswith(h) and len(base) - len(h) >= 2:
            base, suffix = base[:-len(h)], h + suffix
            break
    return base, suffix


def _allowed_jamo_diff(n_syllables):
    return 1 if n_syllables <= 2 else 2


def _is_candidate(base):
    return len(base) >= 2 and base not in _COMMON and base[-1] not in _PREDICATE_END


@dataclass
class Suggestion:
    kind: str                 # "repeat"(반복 단어 통일) | "dict"(고유명사 사전)
    wrong: str                # 바꿀 표기 (조사 뗀 형태)
    right: str                # 바꿀 표기
    count: int                # wrong이 나온 횟수
    right_count: int = 0      # right가 나온 횟수 (반복 단어 통일 근거)
    lines: list = field(default_factory=list)   # wrong이 나온 자막 인덱스

    @property
    def reason(self):
        if self.kind == "dict":
            return "고유명사 사전"
        return f"'{self.right}' {self.right_count}회 / '{self.wrong}' {self.count}회"


def _occurrences(texts):
    """(조사 뗀 단어별 횟수, 단어 전체 형태별 횟수, 형태 → 등장 자막 인덱스 목록)."""
    counts, whole, lines = Counter(), Counter(), defaultdict(list)

    def mark(key, i):
        if not lines[key] or lines[key][-1] != i:
            lines[key].append(i)

    for i, t in enumerate(texts):
        for m in _TOKEN_RE.finditer(t or ""):
            word = m.group()
            base, _ = split_josa(word)
            counts[base] += 1
            whole[word] += 1
            mark(base, i)
            mark(word, i)
    return counts, whole, lines


def suggest(texts, proper_nouns=(), min_right=3, max_wrong=2, ratio=3):
    """교정 제안 목록 생성."""
    counts, whole, lines = _occurrences(texts)
    dict_words = [w.strip() for w in proper_nouns if w and w.strip()]
    dict_set = set(dict_words)
    out, taken = [], set()

    # 1) 고유명사 사전 (조사 떼기 전 단어 전체도 비교)
    forms = {}
    for word, n in whole.items():
        forms.setdefault(word, n)
    for base, n in counts.items():
        forms.setdefault(base, n)
    for form, n in forms.items():
        if form in dict_set or form in taken or len(form) < 2:
            continue
        jf = to_jamo(form)
        for w in dict_words:
            if len(w) != len(form):
                continue
            lim = _allowed_jamo_diff(len(w))
            if _distance(jf, to_jamo(w), lim) <= lim:
                out.append(Suggestion("dict", form, w, n, whole.get(w, 0) + counts.get(w, 0),
                                      lines[form]))
                taken.add(form)
                taken.add(split_josa(form)[0])
                break

    # 2) 반복 단어 통일
    def name_like(b):
        return any(w.startswith(b + s) for w in whole for s in _NAME_SUFFIX)

    frequent = [b for b, n in counts.items()
                if n >= min_right and _is_candidate(b) and (len(b) >= 3 or name_like(b))]
    for base, n in counts.items():
        if base in taken or n > max_wrong or not _is_candidate(base):
            continue
        jb = to_jamo(base)
        lim = _allowed_jamo_diff(len(base))
        best = None
        for f in frequent:
            if f == base or len(f) != len(base) or counts[f] < ratio * n:
                continue
            if _distance(jb, to_jamo(f), lim) <= lim and (best is None or counts[f] > counts[best]):
                best = f
        if best:
            out.append(Suggestion("repeat", base, best, n, counts[best], lines[base]))

    out.sort(key=lambda s: (s.kind != "dict", -s.right_count, s.wrong))
    return out


# 받침 유무에 따라 바뀌는 조사: (받침 있을 때, 없을 때)
_JOSA_PAIRS = [("이", "가"), ("은", "는"), ("을", "를"), ("과", "와"), ("이랑", "랑"),
               ("으로", "로"), ("아", "야"), ("이나", "나"), ("이란", "란")]


def _has_batchim(word):
    code = ord(word[-1]) - 0xAC00
    return 0 <= code < 11172 and code % 28 != 0


def _fit_josa(word, josa):
    """바뀐 단어의 받침에 맞게 조사 형태를 고친다. ('루팍'+'이' → '루파'+'가')"""
    for with_b, without_b in _JOSA_PAIRS:
        if josa in (with_b, without_b):
            return with_b if _has_batchim(word) else without_b
    return josa


def apply(texts, suggestions):
    """선택된 제안을 적용한 새 텍스트 목록. 단어 부분만 바꾸고 조사는 받침에 맞춘다."""
    table = {s.wrong: s.right for s in suggestions}
    if not table:
        return list(texts)

    def fix(m):
        word = m.group()
        if word in table:          # 단어 전체가 바꿀 대상 (예: '아훌로' → '아홀로')
            return table[word]
        base, josa = split_josa(word)
        if base not in table:
            return word
        right = table[base]
        return right + _fit_josa(right, josa)

    return [_TOKEN_RE.sub(fix, t or "") for t in texts]
