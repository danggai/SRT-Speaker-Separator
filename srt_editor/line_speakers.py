"""자막 줄 단위 화자 구분. 줄마다 목소리 임베딩을 뽑아 군집화하거나, 먼저 지정한 줄을 기준으로 나머지를 분류한다. GUI 의존성 없음."""
import numpy as np

SR = 16000
MIN_CROP_SEC = 1.0    # 이보다 짧은 줄은 가운데 기준으로 늘려서 임베딩
SEED_MIN_LINES = 3    # 기준 화자로 쓰려면 이 줄 수 이상 지정돼 있어야 함
SEED_MIN_SPEAKERS = 2
UNSURE_FRAC = 0.2     # 자동 지정 줄 중 확신도 하위 이 비율을 '확인 필요'로 표시


def _norm(z):
    return z / np.maximum(np.linalg.norm(z, axis=1, keepdims=True), 1e-9)


def line_embeddings(embedding_model, audio, intervals, cancelled=None):
    """줄 구간마다 임베딩 (N, D). 구간이 없거나 잘못된 줄은 NaN 행."""
    import torch
    dur = len(audio) / SR
    out, dim = [], None
    for t_s, t_e in intervals:
        if t_s is None or t_e is None or t_e <= t_s or t_s >= dur:
            out.append(None)
            continue
        if cancelled is not None and cancelled():
            return None
        if t_e - t_s < MIN_CROP_SEC:
            mid = (t_s + t_e) / 2
            t_s, t_e = mid - MIN_CROP_SEC / 2, mid + MIN_CROP_SEC / 2
        t_s, t_e = max(0.0, t_s), min(dur, t_e)
        wav = torch.from_numpy(np.ascontiguousarray(audio[int(t_s * SR):int(t_e * SR)]))[None, None, :]
        emb = np.asarray(embedding_model(wav))[0]
        dim = emb.shape[0]
        out.append(emb)
    if dim is None:
        return np.full((len(intervals), 1), np.nan)
    return np.vstack([e if e is not None else np.full(dim, np.nan) for e in out])


def _valid(x):
    return ~np.isnan(x).any(axis=1)


def _cluster(z, k):
    from sklearn.cluster import KMeans, SpectralClustering
    if len(z) >= 2 * k:
        try:
            aff = np.clip(z @ z.T, 0, 1) ** 2
            return SpectralClustering(k, affinity="precomputed", random_state=0).fit_predict(aff)
        except Exception:
            pass
    return KMeans(k, n_init=10, random_state=0).fit_predict(z)


def _centroid_conf(z, lab):
    """줄마다 자기 군집 중심과 가장 가까운 다른 중심의 유사도 차이로 만든 확신도 (0~1)."""
    ks = sorted(set(int(v) for v in lab))
    if len(ks) < 2:
        return np.ones(len(z))
    c = _norm(np.vstack([z[lab == k].mean(0) for k in ks]))
    s = z @ c.T
    own = s[np.arange(len(z)), [ks.index(int(v)) for v in lab]]
    s[np.arange(len(z)), [ks.index(int(v)) for v in lab]] = -np.inf
    return np.clip((own - s.max(1)) / 0.2, 0.0, 1.0)


def estimate_speakers(z, k_min=2, k_max=10):
    """실루엣 점수가 가장 높은 화자 수."""
    from sklearn.metrics import silhouette_score
    best, best_k = -1.0, k_min
    for k in range(k_min, min(k_max, len(z) - 1) + 1):
        lab = _cluster(z, k)
        if len(set(lab)) < 2:
            continue
        sc = silhouette_score(z, lab, metric="cosine")
        if sc > best:
            best, best_k = sc, k
    return best_k


def cluster_lines(x, k, k_max=10):
    """줄 임베딩을 k명으로 군집화 (k가 0이면 화자 수도 추정, 최대 k_max명). 반환: (줄별 군집 번호, 줄별 확신도 0~1).
    임베딩 없는 줄은 번호 -1, 확신도 0."""
    ok = _valid(x)
    labels = np.full(len(x), -1, int)
    conf = np.zeros(len(x))
    z = _norm(x[ok])
    if len(z) == 0:
        return labels, conf
    if int(k) <= 0:
        k = estimate_speakers(z, k_max=max(2, int(k_max))) if len(z) >= 6 else 1
    k = max(1, min(int(k), len(z)))
    lab = np.zeros(len(z), int) if k == 1 else _cluster(z, k)
    labels[ok] = lab
    conf[ok] = _centroid_conf(z, lab)
    return labels, conf


def seed_speakers(speaker_per_line):
    """줄별 화자 이름 목록(없으면 빈 문자열)에서 기준으로 쓸 수 있는 {줄 번호: 이름}. 조건이 안 되면 빈 dict."""
    seeds = {i: s for i, s in enumerate(speaker_per_line) if s}
    counts = {}
    for s in seeds.values():
        counts[s] = counts.get(s, 0) + 1
    if sum(1 for c in counts.values() if c >= SEED_MIN_LINES) < SEED_MIN_SPEAKERS:
        return {}
    return seeds


def assign_from_seeds(x, seeds, rounds=5, frac=0.3, c=100):
    """지정된 줄({줄 번호: 이름})로 학습하고, 확신이 높은 줄부터 스스로 라벨로 추가하며 반복해 모든 줄의 화자를 예측.
    반환: (줄별 이름, 줄별 확신도 0~1). 임베딩 없는 줄은 빈 문자열·0."""
    from sklearn.linear_model import LogisticRegression
    ok = _valid(x)
    z = _norm(np.where(ok[:, None], x, 0.0))
    names = sorted(set(seeds.values()))
    cur = {i: names.index(s) for i, s in seeds.items() if ok[i]}
    per = max(1, int(frac * int(ok.sum())))

    def fit():
        idx = np.array(list(cur))
        return LogisticRegression(C=c, max_iter=3000).fit(z[idx], np.array([cur[i] for i in idx]))

    for _ in range(rounds):
        clf = fit()
        p = clf.predict_proba(z)
        pred = clf.classes_[p.argmax(1)]
        for i in [i for i in np.argsort(-p.max(1)) if ok[i] and i not in cur][:per]:
            cur[i] = int(pred[i])
    clf = fit()
    pred = clf.classes_[clf.predict_proba(z).argmax(1)]
    conf = np.zeros(len(z))
    conf[ok] = _centroid_conf(z[ok], pred[ok])
    return [names[int(q)] if ok[i] else "" for i, q in enumerate(pred)], conf


def unsure_mask(conf, auto, frac=UNSURE_FRAC):
    """자동으로 정한 줄(auto) 가운데 확신도가 가장 낮은 frac 비율을 '확인 필요'로."""
    conf, auto = np.asarray(conf, float), np.asarray(auto, bool)
    out = np.zeros(len(conf), bool)
    if auto.sum() == 0:
        return out
    c = conf[auto]
    cut = np.quantile(c, frac)
    low = (conf < cut) | ((conf == cut) & (cut < c.max()))   # 대부분 같은 값이면 그 값은 표시하지 않음
    out[auto & low] = True
    return out