"""자동 자막 오프라인 교정 제안 (비슷한 표기 후보 + 문맥 근거 점수). GUI 없음."""
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


SHOW_SCORE = 2      # 이 점수 이상만 보여 줌
CHECK_SCORE = 3     # 이 점수 이상은 미리 체크
NEAR_LINES = 10     # 이 줄 수 안에 바른 표기가 나오면 문맥 근거


@dataclass
class Fix:
    """한 줄에서의 교정 제안 (근거와 점수 포함)."""
    line: int                 # 자막 인덱스
    wrong: str                # 바꿀 표기 (조사 뗀 형태)
    right: str                # 바꿀 표기
    kind: str                 # "repeat"(반복 표기) | "dict"(고유명사 사전)
    score: int = 0
    reasons: list = field(default_factory=list)
    audio: str = None         # 음성 확인 결과: "right" | "wrong" | None

    @property
    def checked(self):
        return self.score >= CHECK_SCORE


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


def _tokens(text):
    """[(조사 뗀 형태, 붙은 조사·호칭)] 목록."""
    return [split_josa(m.group()) for m in _TOKEN_RE.finditer(text or "")]


def _contexts(texts):
    """형태별 문맥: {형태: [(줄, 앞 단어, 뒤 단어, 붙은 말)]}. 조사 뗀 형태와 단어 전체 둘 다 기록."""
    ctx = defaultdict(list)
    for i, t in enumerate(texts):
        words = [m.group() for m in _TOKEN_RE.finditer(t or "")]
        toks = [split_josa(w) for w in words]
        for k, (base, suffix) in enumerate(toks):
            prev = toks[k - 1][0] if k > 0 else ""
            nxt = toks[k + 1][0] if k + 1 < len(toks) else ""
            ctx[base].append((i, prev, nxt, suffix))
            if words[k] != base:   # '아홀로'처럼 조사로 잘못 잘릴 수 있는 단어 전체도
                ctx[words[k]].append((i, prev, nxt, ""))
    return ctx


def _name_suffix(occ):
    """이름 뒤 호칭 ('루파씨' 또는 '루파 씨')."""
    _, _, nxt, suffix = occ
    if suffix[:1] in _NAME_SUFFIX:
        return suffix[:1]
    return nxt if nxt in _NAME_SUFFIX else ""


def _score(fix, occ, right_ctx, n_wrong, n_right):
    """문맥 근거로 점수와 이유를 채운다."""
    line, prev, nxt, suffix = occ
    if fix.kind == "dict":
        fix.score += 1
        fix.reasons.append("고유명사 사전에 있음")
    elif n_right >= 2 * n_wrong:
        fix.score += 1
        fix.reasons.append(f"'{fix.right}' {n_right}회 · '{fix.wrong}' {n_wrong}회")
    if right_ctx:
        d = min(abs(line - r[0]) for r in right_ctx)
        if d <= NEAR_LINES:
            fix.score += 2
            fix.reasons.append(f"{d}줄 거리에 '{fix.right}'" if d else f"같은 줄에 '{fix.right}'")
        shared = []
        if prev and any(r[1] == prev for r in right_ctx):
            shared.append(f"앞말 '{prev}'")
        if nxt and any(r[2] == nxt for r in right_ctx):
            shared.append(f"뒷말 '{nxt}'")
        if shared:
            fix.score += min(2, len(shared))
            fix.reasons.append(f"'{fix.right}'와 문맥 같음 ({', '.join(shared)})")
    hon = _name_suffix(occ)
    if hon and (fix.kind == "dict" or right_ctx):
        fix.score += 1
        fix.reasons.append(f"호칭 '{hon}'가 붙음")


def suggest(texts, proper_nouns=(), min_right=3, max_wrong=2):
    """줄별 교정 제안. 글자가 비슷한 후보 중 문맥 근거가 충분한 것만 남긴다."""
    counts, whole, lines = _occurrences(texts)
    ctx = _contexts(texts)
    dict_words = [w.strip() for w in proper_nouns if w and w.strip()]
    dict_set = set(dict_words)
    pairs = {}   # wrong → (right, kind)

    # 후보 1) 고유명사 사전과 비슷한 표기 (조사 뗀 형태와 단어 전체 모두 비교)
    for base in list(counts) + [w for w in whole if w not in counts]:
        if base in dict_set or base in pairs or len(base) < 2:
            continue
        jb = to_jamo(base)
        for w in dict_words:
            if len(w) != len(base):
                continue
            lim = _allowed_jamo_diff(len(w))
            if _distance(jb, to_jamo(w), lim) <= lim:
                pairs[base] = (w, "dict")
                break

    # 후보 2) 자주 나온 표기와 비슷한 드문 표기
    def name_like(b):
        return any(_name_suffix(o) for o in ctx.get(b, []))

    frequent = [b for b, n in counts.items()
                if n >= min_right and _is_candidate(b) and (len(b) >= 3 or name_like(b))]
    for base, n in counts.items():
        if base in pairs or n > max_wrong or not _is_candidate(base):
            continue
        jb = to_jamo(base)
        lim = _allowed_jamo_diff(len(base))
        best = None
        for f in frequent:
            # 바른 쪽이 더 많이 나오기만 하면 후보로 두고, 실제 추천 여부는 문맥 점수로 정함
            if f == base or len(f) != len(base) or counts[f] <= n:
                continue
            if _distance(jb, to_jamo(f), lim) <= lim and (best is None or counts[f] > counts[best]):
                best = f
        if best:
            pairs[base] = (best, "repeat")

    out = []
    for wrong, (right, kind) in pairs.items():
        for occ in ctx.get(wrong, []):
            fix = Fix(occ[0], wrong, right, kind)
            n_wrong = counts.get(wrong) or whole.get(wrong, 0)
            n_right = counts.get(right) or whole.get(right, 0)
            _score(fix, occ, ctx.get(right, []), n_wrong, n_right)
            if fix.score >= SHOW_SCORE:
                out.append(fix)
    out.sort(key=lambda f: (f.line, -f.score))
    return out


def find_word(text, base):
    """text에서 조사 뗀 형태가 base인 첫 단어의 위치 (없으면 -1)."""
    for m in _TOKEN_RE.finditer(text or ""):
        if m.group() == base or split_josa(m.group())[0] == base:
            return m.start()
    return -1


def apply_audio(fix, heard):
    """음성 재확인 결과 반영. heard: 'right' | 'wrong' | None."""
    fix.audio = heard
    if heard == "right":
        fix.score += 3
        fix.reasons.insert(0, f"음성으로 다시 들어 보니 '{fix.right}'")
    elif heard == "wrong":
        fix.score = 0
        fix.reasons.insert(0, f"음성으로 다시 들어 보니 '{fix.wrong}' 그대로")


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


def apply(texts, fixes):
    """선택된 제안을 해당 줄에만 적용한 새 텍스트 목록. 조사는 받침에 맞춘다."""
    by_line = defaultdict(dict)
    for f in fixes:
        by_line[f.line][f.wrong] = f.right
    out = list(texts)
    for i, table in by_line.items():
        if not (0 <= i < len(out)):
            continue

        def fix(m, table=table):
            word = m.group()
            if word in table:
                return table[word]
            base, josa = split_josa(word)
            if base not in table:
                return word
            right = table[base]
            return right + _fit_josa(right, josa)

        out[i] = _TOKEN_RE.sub(fix, out[i] or "")
    return out
