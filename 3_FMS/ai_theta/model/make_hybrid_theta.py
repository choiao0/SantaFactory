# -*- coding: utf-8 -*-
"""하이브리드 θ — 예측되는 축만 예측하고 나머지는 공통값에 고정한다 (S15P21A106-206).

## 왜 하이브리드인가

개방 조건에서 **창고별 직접 탐색 θ 가 공통 θ 를 못 이겼다**(52창고, +0.68 %, 양수 25/52,
p=0.89). 그런데 직접 탐색 θ 는 8축을 전부 그 창고에 맞춘 값이라, **배울 게 없는 축에서는
탐색 노이즈를 그대로 싣고 있다**. 재현성 측정에서 θ 변동의 63 % 가 탐색 노이즈였다.

그 축들을 공통값에 묶어두면 그 손해가 사라진다. 그래서 하이브리드가 창고별 θ 와 공통 θ
**둘 다보다** 나을 여지가 논리적으로 있다 — 이게 이 스크립트가 만드는 가설이다.

    예측 축   LOO R² 가 0 보다 유의미하게 큰 축만      → GP 예측값
    나머지    배울 게 없다고 판정된 축                  → 공통값 고정
    범주형    aisle_period · aisle_phase · loop_dir     → 공통 최빈값

## 자기 답 채점 금지

창고 i 의 θ 를 예측할 때 **그 창고를 학습에서 뺀다**(leave-one-out). 안 그러면 모델이 외운
값을 그대로 뱉고, 그걸 시뮬에 넣어 "예측이 잘 맞는다"는 결론이 나온다.

## 축을 고르는 기준

LOO R² 는 이미 held-out 추정치라 in-sample 과 다르다. 다만 8축 중에서 고르는 행위 자체는
같은 데이터를 두 번 보는 것이므로, **최종 판정은 R² 가 아니라 처리량**이다
(`theta_hybrid_value.py`). 여기서 고른 축은 가설이지 결론이 아니다.
"""
import argparse
import glob
import json
import os
import re
import statistics as st
import sys

import numpy as np
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel
from sklearn.model_selection import LeaveOneOut
from sklearn.preprocessing import StandardScaler

# 윈도우 콘솔이 cp949 라 — · θ 같은 글자에서 죽는다. 서버(UTF-8)에서는 아무 영향이 없다.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
FMS = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(FMS, "..", "contracts"))
sys.path.insert(0, os.path.join(FMS, "contracts"))
try:
    from guidance_types import THETA_CONTINUOUS_RANGES as RANGES
except ImportError:                     # 계약 파일이 경로에 없을 때를 위한 사본
    RANGES = {"aisle_alt_gain": (1.0, 3.5), "aisle_alt_boost": (0.5, 1.0),
              "loop_gain": (1.0, 3.0), "main_aisle_gain": (0.5, 1.2),
              "junction_penalty": (1.0, 3.0), "station_in": (0.5, 1.0),
              "station_out": (1.0, 3.0), "wait_cost": (0.5, 3.0)}

AXES = list(RANGES)
CATS = ["aisle_period", "aisle_phase", "loop_dir"]
FEATS = ["aisles", "pitch", "length", "free", "fleet", "load_frac"]
NAME = re.compile(r"theta_open_(r\d+p\d+l\d+)_r\d+_L\d+_s\d+\.json$")


def load(theta_dir):
    """창고별 θ 반복들을 모은다 — 반복 2회 이상만 쓴다(레이블 노이즈가 절반이 된다)."""
    design = {d["name"]: d for d in json.load(
        open(os.path.join(theta_dir, "design.json"), encoding="utf-8"))}
    got = {}
    for f in sorted(glob.glob(os.path.join(theta_dir, "*", "theta_open_*.json"))):
        m = NAME.search(os.path.basename(f))
        if m:
            got.setdefault(m.group(1), []).append(json.load(open(f, encoding="utf-8")))
    got = {n: ts for n, ts in got.items() if n in design and len(ts) >= 2}
    names = sorted(got)
    X = np.array([[float(design[n][f]) for f in FEATS] for n in names])
    y = {a: np.array([st.fmean(t[a] for t in got[n]) for n in names]) for a in AXES}
    # 두 회차의 차이가 그 조건의 탐색 노이즈. 2회 평균이 레이블이므로 분산은 sd^2 / 2
    noise = {a: np.array([st.stdev([t[a] for t in got[n]]) for n in names]) ** 2 / 2
             for a in AXES}
    cats = {c: st.mode([t[c] for n in names for t in got[n]]) for c in CATS}
    return names, design, X, y, noise, cats


def fit_gp(Xs, yv, alpha):
    k = (ConstantKernel(1.0, (1e-3, 1e3))
         * Matern(length_scale=np.ones(Xs.shape[1]), length_scale_bounds=(1e-2, 1e3), nu=2.5)
         + WhiteKernel(noise_level=1e-3, noise_level_bounds=(1e-8, 1e2)))
    return GaussianProcessRegressor(kernel=k, alpha=np.maximum(alpha, 1e-10),
                                    normalize_y=True, n_restarts_optimizer=2,
                                    random_state=0).fit(Xs, yv)


def loo_predict(X, yv, alpha):
    """창고 i 를 빼고 학습해 i 를 예측한다. 이 값이 그대로 하이브리드 θ 에 들어간다."""
    pred = np.empty(len(yv))
    for tr, te in LeaveOneOut().split(X):
        sc = StandardScaler().fit(X[tr])
        pred[te] = fit_gp(sc.transform(X[tr]), yv[tr], alpha[tr]).predict(sc.transform(X[te]))
    ss_res = float(((yv - pred) ** 2).sum())
    ss_tot = float(((yv - yv.mean()) ** 2).sum())
    return pred, 1 - ss_res / ss_tot


def main():
    p = argparse.ArgumentParser(description="하이브리드 θ 생성 (예측 축 + 공통 고정)")
    p.add_argument("--dir", default=os.path.join(FMS, "infra", "out", "theta_open"))
    p.add_argument("--min-r2", type=float, default=0.05,
                   help="이 값 이상인 축만 예측한다 (기본 0.05)")
    p.add_argument("--axes", default="", help="쉼표로 축을 직접 지정 (R² 판정을 건너뛴다)")
    a = p.parse_args()

    names, design, X, y, noise, cats = load(a.dir)
    print("창고 %d개 · 특징 %d개 · θ %d축" % (len(names), X.shape[1], len(AXES)))

    print("\n=== 축별 LOO R² (개방 조건) ===")
    print("  %-20s%10s%12s%10s" % ("θ 축", "LOO R²", "예측 산포", "판정"))
    print("  " + "-" * 52)
    pred, chosen = {}, []
    want = [s.strip() for s in a.axes.split(",") if s.strip()]
    for ax in AXES:
        pv, r2 = loo_predict(X, y[ax], noise[ax])
        lo, hi = RANGES[ax]
        pred[ax] = np.clip(pv, lo, hi)          # 탐색 범위 밖으로 나간 예측은 잘라낸다
        take = (ax in want) if want else (r2 >= a.min_r2)
        if take:
            chosen.append(ax)
        print("  %-20s%10.3f%12.3f%10s"
              % (ax, r2, float(pred[ax].std()), "예측" if take else "공통고정"))

    if not chosen:
        print("\n  R² 가 %.2f 를 넘는 축이 없다 — 하이브리드가 공통 θ 와 같아진다." % a.min_r2)
        return 1

    common = {ax: float(y[ax].mean()) for ax in AXES}
    common.update(cats)
    out_dir = os.path.join(a.dir, "_hybrid")
    os.makedirs(out_dir, exist_ok=True)
    json.dump(common, open(os.path.join(out_dir, "theta_common.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    for i, n in enumerate(names):
        th = dict(common)
        for ax in chosen:
            th[ax] = float(pred[ax][i])
        json.dump(th, open(os.path.join(out_dir, "theta_hybrid_%s.json" % n), "w",
                           encoding="utf-8"), ensure_ascii=False, indent=1)

    print("\n=== 하이브리드 θ %d개 → %s ===" % (len(names), out_dir))
    print("  예측 축 %d개: %s" % (len(chosen), ", ".join(chosen)))
    print("  고정 축 %d개: %s" % (len(AXES) - len(chosen),
                                 ", ".join(x for x in AXES if x not in chosen)))

    # 예측이 공통값에서 얼마나 움직이는가 — 안 움직이면 대결 결과가 무승부로 나올 수밖에 없다
    print("\n=== 공통값 대비 이동폭 (탐색 범위 대비) ===")
    print("  %-20s%12s%12s%10s" % ("예측 축", "공통값", "평균 이동", "범위 %"))
    print("  " + "-" * 54)
    for ax in chosen:
        lo, hi = RANGES[ax]
        mv = float(np.abs(pred[ax] - common[ax]).mean())
        print("  %-20s%12.3f%12.3f%9.1f%%" % (ax, common[ax], mv, 100 * mv / (hi - lo)))

    print("\n  판정은 R² 가 아니라 처리량이다 — theta_hybrid_value.py 로 공통 θ 와 붙인다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
