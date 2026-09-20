# -*- coding: utf-8 -*-
"""θ 예측 모델 — GP 와 XGBoost 를 같은 데이터로 학습·비교한다 (S15P21A106-206).

입력 `(통로수, 간격, 길이, 통행칸, 대수, 상대부하)` → 출력 θ 8축(연속). 학습 데이터는
`theta_open_lhs.py` 가 합성 창고 103개에서 뽑은 θ 다(랙 통로 개방, 창고당 반복 2회).

## 두 모델을 다 붙이는 이유

| | XGBoost | GP |
|---|---|---|
| 표본 100행 | 트리가 배울 양이 아니다 — 사실상 외운다 | 소표본이 정상 범위 |
| 격자 사이 | 계단, 보간 못 함 | 부드럽게 보간 |
| 외삽 | 0 | 가능(구간이 넓어진다) |
| **측정 노이즈** | 넣을 자리 없음 | **`alpha` 에 넣는다** |
| 출력 | 값 | 값 + 불확실 구간 |

표본 크기로는 GP 가 맞지만, 관계가 계단 모양(임계값)이면 트리가 유리하다. 학습이 각각
1초라 둘 다 돌려 **leave-one-out 으로 비교**한다.

## 노이즈를 모델에 알려준다

창고마다 θ 를 2회 뽑았고 그 차이가 그 조건의 탐색 노이즈다(CSV 의 `sd_*` 열). 2회 평균을
레이블로 쓰므로 평균의 분산은 `sd²/2` 다. 그 값을 GP 의 `alpha` 로 넣으면 모델이 점을
억지로 통과하지 않는다. 앞선 재현성 측정에서 **θ 변동의 63 % 가 탐색 노이즈**였으므로
이 처리가 없으면 모델이 잡음을 외운다.

## 판정 기준 — R² 가 아니다

목적함수가 평탄해 θ 가 탐색 범위의 34~51 % 를 움직여도 처리량이 0.39 % 안에서 같다
(trial 7,286개 실측). 그래서 **θ 를 잘 맞히는 것 자체는 의미가 없다.** 이 스크립트가 내는
R² 는 "예측이 가능한가" 의 상한일 뿐이고, 쓸모는 예측한 θ 를 **시뮬에 넣어** 직접 탐색한
θ 와 처리량을 비교해야 정해진다(`theta_open_value.py`).

기준선: 축별 R² 를 **평균 예측기**(항상 전체 평균을 뱉는 모델)와 견준다. R² ≤ 0 이면
그 축은 평균만 뱉는 것보다 못하다는 뜻이다.
"""
import argparse
import csv
import json
import os
import sys

import numpy as np
from sklearn.ensemble import GradientBoostingRegressor  # noqa: F401  (xgboost 없을 때 대체)
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel
from sklearn.model_selection import LeaveOneOut
from sklearn.preprocessing import StandardScaler

AXES = ["aisle_alt_gain", "aisle_alt_boost", "loop_gain", "main_aisle_gain",
        "junction_penalty", "station_in", "station_out", "wait_cost"]
FEATS = ["aisles", "pitch", "length", "free", "fleet", "load_frac"]


def load(path):
    rows = [r for r in csv.DictReader(open(path, encoding="utf-8"))
            if int(r.get("n_rep", 1)) >= 2]
    X = np.array([[float(r[f]) for f in FEATS] for r in rows])
    y = {a: np.array([float(r[a]) for r in rows]) for a in AXES}
    # 레이블은 2회 평균이므로 그 분산은 sd^2 / 2 다
    noise = {a: np.array([float(r.get("sd_" + a, 0.0)) for r in rows]) ** 2 / 2 for a in AXES}
    names = [r["name"] for r in rows]
    return names, X, y, noise


def fit_gp(Xs, yv, alpha):
    """Matern 5/2 + ARD. ARD 는 축마다 길이 스케일을 따로 학습해 **어느 특징이 중요한지**를
    모델이 스스로 말하게 한다 — 길이 스케일이 크면 그 특징은 출력에 거의 영향이 없다."""
    k = (ConstantKernel(1.0, (1e-3, 1e3))
         * Matern(length_scale=np.ones(Xs.shape[1]), length_scale_bounds=(1e-2, 1e3), nu=2.5)
         + WhiteKernel(noise_level=1e-3, noise_level_bounds=(1e-8, 1e2)))
    gp = GaussianProcessRegressor(kernel=k, alpha=np.maximum(alpha, 1e-10),
                                  normalize_y=True, n_restarts_optimizer=2,
                                  random_state=0)
    return gp.fit(Xs, yv)


def loo_r2(make, X, yv, alpha):
    """leave-one-out 예측의 R². 100행에서는 hold-out 을 따로 떼면 남는 게 없어 LOO 를 쓴다."""
    pred = np.empty(len(yv))
    for tr, te in LeaveOneOut().split(X):
        sc = StandardScaler().fit(X[tr])
        m = make(sc.transform(X[tr]), yv[tr], alpha[tr])
        pred[te] = m.predict(sc.transform(X[te]))
    ss_res = float(((yv - pred) ** 2).sum())
    ss_tot = float(((yv - yv.mean()) ** 2).sum())
    return 1 - ss_res / ss_tot, pred


def main():
    p = argparse.ArgumentParser(description="θ 예측 모델 학습·비교")
    p.add_argument("--csv", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..",
        "infra", "out", "theta_open_lhs_v36.csv"))
    p.add_argument("--out", default=os.path.dirname(os.path.abspath(__file__)))
    a = p.parse_args()

    names, X, y, noise = load(a.csv)
    print("학습 세트 %d행 · 특징 %d개 → θ %d축" % (len(names), X.shape[1], len(AXES)))
    print("  특징: " + ", ".join(FEATS))

    try:
        from xgboost import XGBRegressor
        def make_xgb(Xs, yv, al):
            return XGBRegressor(n_estimators=300, max_depth=3, learning_rate=0.05,
                                subsample=0.8, colsample_bytree=0.8,
                                reg_lambda=1.0, random_state=0, verbosity=0).fit(Xs, yv)
        xgb_name = "XGBoost"
    except ImportError:
        def make_xgb(Xs, yv, al):
            return GradientBoostingRegressor(n_estimators=300, max_depth=3,
                                             learning_rate=0.05, random_state=0).fit(Xs, yv)
        xgb_name = "GradientBoosting(대체)"

    print("\n=== leave-one-out R² (0 이하 = 평균만 뱉는 모델보다 못하다) ===")
    print("  %-20s%10s%12s%12s" % ("θ 축", "노이즈비", "GP", xgb_name))
    print("  " + "-" * 56)
    res, gp_models = {}, {}
    for ax in AXES:
        yv, al = y[ax], noise[ax]
        # 노이즈비 = 레이블 노이즈 분산 / 전체 분산. 1에 가까우면 배울 신호가 없다.
        nr = float(al.mean() / yv.var()) if yv.var() > 0 else 1.0
        r_gp, _ = loo_r2(fit_gp, X, yv, al)
        r_xg, _ = loo_r2(lambda Xs, v, q: make_xgb(Xs, v, q), X, yv, al)
        res[ax] = {"noise_ratio": nr, "gp_r2": r_gp, "xgb_r2": r_xg}
        print("  %-20s%10.2f%12.3f%12.3f" % (ax, nr, r_gp, r_xg))
        sc = StandardScaler().fit(X)
        gp_models[ax] = (sc, fit_gp(sc.transform(X), yv, al))

    gp_avg = float(np.mean([v["gp_r2"] for v in res.values()]))
    xg_avg = float(np.mean([v["xgb_r2"] for v in res.values()]))
    print("\n  평균 R²   GP %.3f · %s %.3f" % (gp_avg, xgb_name, xg_avg))
    win = "GP" if gp_avg >= xg_avg else xgb_name
    print("  → %s 가 낫다" % win)

    print("\n=== GP 가 본 특징 중요도 (ARD 길이 스케일 — 짧을수록 중요) ===")
    print("  %-20s" % "θ 축" + "".join("%10s" % f[:9] for f in FEATS))
    print("  " + "-" * (20 + 10 * len(FEATS)))
    for ax in AXES:
        k = gp_models[ax][1].kernel_
        ls = None
        for sub in getattr(k, "k1", k), getattr(k, "k2", None):
            if sub is not None and hasattr(getattr(sub, "k2", sub), "length_scale"):
                ls = np.atleast_1d(getattr(sub, "k2", sub).length_scale)
        if ls is None or len(ls) != len(FEATS):
            continue
        print("  %-20s" % ax + "".join("%10.1f" % v for v in ls))

    out = os.path.join(a.out, "theta_model_report.json")
    json.dump({"n_rows": len(names), "features": FEATS, "axes": AXES,
               "loo_r2": res, "gp_avg_r2": gp_avg, "xgb_avg_r2": xg_avg,
               "winner": win}, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n  보고서 %s" % out)

    print("\n=== 판정 ===")
    if max(gp_avg, xg_avg) <= 0.05:
        print("  평균 R² 가 0 근처다 — **두 모델 다 평균만 뱉는다.** 기하·대수·부하로 θ 를")
        print("  예측할 수 없다는 결론이 모델 수준에서도 확인된다.")
    elif max(gp_avg, xg_avg) < 0.3:
        print("  평균 R² 가 낮다. 예측이 서긴 하지만 설명력이 약하다 —")
        print("  쓸모는 예측 θ 를 시뮬에 넣어 처리량으로 확인해야 정해진다.")
    else:
        print("  예측이 선다. 다음은 예측 θ 를 시뮬에 넣어 직접 탐색 θ 와 처리량을 비교하는 것.")
    print("  **R² 가 높아도 그것만으로는 쓸모가 없다** — 목적함수가 평탄해 θ 가 탐색 범위의")
    print("  34~51 % 를 움직여도 처리량이 0.39 % 안에서 같다(trial 7,286개 실측).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
