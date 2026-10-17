"""고친 말 배우기: 직접 고친 기록에서 '자주 틀리는 말 → 바른 말'을 모아 자동 자막에 바로 적용. GUI 없음."""
import difflib
import re

from . import correction as cr

MIN_FIXES = 2        # 이만큼 똑같이 고친 말만 적용 (1번만 고친 것까지 쓰면 오히려 틀림이 늘었음)
MAX_WORDS = 500      # 기억하는 틀린 말 최대 개수

_WORD_RE = re.compile(r"[가-힣]+")


def _bases(text):
    return [cr.split_josa(w)[0] for w in _WORD_RE.findall(text or "")]


def learn(store, old, new):
    """한 줄을 old → new로 고쳤을 때 기록. store = {"fix": {틀린: {바른: 횟수}}, "kept": {틀린: 횟수}}."""
    fix, kept = store.setdefault("fix", {}), store.setdefault("kept", {})
    a, b = _bases(old), _bases(new)
    changed = False
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "replace" and i2 - i1 == 1 and j2 - j1 == 1:
            w, r = a[i1], b[j1]
            if w != r and len(r) >= 2 and w not in cr._COMMON and r not in cr._COMMON:
                fix.setdefault(w, {})[r] = fix.get(w, {}).get(r, 0) + 1
                changed = True
        elif op == "equal":   # 고친 줄에서 그대로 둔 말: 진짜 단어로도 쓰임
            for w in a[i1:i2]:
                if w in fix:
                    kept[w] = kept.get(w, 0) + 1
                    changed = True
    if len(fix) > MAX_WORDS:   # 적게 고친 것부터 버림
        for w in sorted(fix, key=lambda k: sum(fix[k].values()))[:len(fix) - MAX_WORDS]:
            fix.pop(w, None)
            kept.pop(w, None)
    return changed


def rules(store):
    """적용할 규칙 {틀린 말: 바른 말}: MIN_FIXES번 이상 똑같이 고쳤고, 그대로 둔 적은 없는 말만."""
    out = {}
    for w, cands in (store or {}).get("fix", {}).items():
        r, n = max(cands.items(), key=lambda kv: kv[1])
        if n >= MIN_FIXES and not store.get("kept", {}).get(w):
            out[w] = r
    return out


def apply(text, rule):
    """규칙대로 바꾼 글자와 바꾼 곳 수 (조사·호칭은 그대로)."""
    count = 0

    def sub(m):
        nonlocal count
        base, josa = cr.split_josa(m.group(0))
        if base in rule:
            count += 1
            return rule[base] + josa
        return m.group(0)
    return _WORD_RE.sub(sub, text or ""), count
