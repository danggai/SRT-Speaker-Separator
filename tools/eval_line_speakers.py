"""줄 단위 화자 구분(srt_editor/line_speakers.py) 정확도 평가.

정답 SRT(`[화자] 내용` 형식)와 미디어로, 앱의 '화자 분석'이 쓰는 두 방식을 잰다.
  군집   화자 수만 알려 주고 줄을 군집화 (화자 라벨→정답 이름은 겹침이 최대가 되게 1:1 매칭)
  선지정  화자당 N줄을 먼저 지정했을 때 나머지 줄의 정확도 (무작위 6회 평균)

사용법:
  python tools/eval_line_speakers.py --media 원본.mp3 --ref 정답.srt --k 6 --seeds 3 5 10
"""
import argparse
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import eval_accuracy as E  # noqa: E402
from srt_editor import line_speakers as L  # noqa: E402


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--media", required=True)
    p.add_argument("--ref", required=True)
    p.add_argument("--k", type=int, default=0, help="군집 화자 수 (0이면 앱처럼 스스로 추정)")
    p.add_argument("--seeds", type=int, nargs="*", default=[3, 5, 10], help="화자당 선지정 줄 수")
    p.add_argument("--device", default="cpu", choices=["cpu", "cuda"])
    a = p.parse_args()

    import warnings
    warnings.filterwarnings("ignore")
    import whisperx
    from whisperx.diarize import DiarizationPipeline

    ref = [r for r in E.parse_srt(a.ref) if r["speaker"]]
    names = sorted({r["speaker"] for r in ref})
    y = np.array([names.index(r["speaker"]) for r in ref])
    audio = whisperx.load_audio(a.media)
    pipe = DiarizationPipeline(token=E._hf_token(), device=a.device)
    x = L.line_embeddings(pipe.model._embedding, audio, [(r["start"], r["end"]) for r in ref])
    ok = ~np.isnan(x).any(axis=1)
    print(f"줄 {len(ref)}개 (임베딩 {int(ok.sum())}개), 화자 {len(names)}명")

    from scipy.optimize import linear_sum_assignment
    k = a.k
    lab, _ = L.cluster_lines(x, k)
    ids = sorted(set(lab[ok]))
    m = np.array([[np.sum((lab == i) & (y == j)) for j in range(len(names))] for i in ids])
    ri, ci = linear_sum_assignment(-m)
    mapping = {ids[i]: j for i, j in zip(ri, ci)}
    print(f"군집(k={k or "자동"} → {len(ids)}명): 줄 정확도 {np.mean([mapping.get(l) == t for l, t in zip(lab, y)]):.1%}")

    for n_lab in a.seeds:
        accs = []
        for rep in range(6):
            rng = np.random.default_rng(rep)
            idx = []
            for j in range(len(names)):
                c = np.where(y == j)[0]
                if len(c) > n_lab:
                    idx += list(rng.choice(c, n_lab, replace=False))
            seeds = {int(i): names[y[i]] for i in idx}
            pred, _ = L.assign_from_seeds(x, seeds)
            rest = [i for i in range(len(y)) if i not in seeds]
            accs.append(np.mean([pred[i] == names[y[i]] for i in rest]))
        print(f"선지정(화자당 {n_lab}줄): 나머지 줄 정확도 {np.mean(accs):.1%}")


if __name__ == "__main__":
    main()
