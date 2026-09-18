# -*- coding: utf-8 -*-
"""대리 모델 학습·검증 — (맵, θ) → 처리량 (S15P21A106-206).

## 관문

이 스크립트가 내는 **맵 단위 교차검증 R²** 가 관문이다. 처리량 예측이 서야 그 위에서
θ 를 최적화하는 것(`optimize_theta.py`)이 뜻이 있다. 0 근처면 거기서 멈춘다.

레이블 `z` 는 study 안에서 표준화한 처리량이라, **"study 평균만 뱉는 모델" 의 R² 가 정확히
0** 이다. 기준선이 공짜로 따라온다.

## 맵 단위로 갈라야 한다

행 단위로 뭉치를 나누면 같은 맵의 다른 trial 이 학습에 남아 "이 맵은 loop_gain 1.4 가
좋더라" 를 이미 아는 상태로 채점한다. **맵을 통째로 빼야** 처음 보는 창고를 재는 것이 된다
(`GroupKFold`, group = 맵 이름).

맵이 85~95개라 leave-one-out 은 85번 학습이라 비싸고 얻는 것도 없다. 5-fold 로 충분하다.

## 모델 셋을 같이 세우는 이유

| | 역할 | 입력 미분 |
|---|---|---|
| MLP | 최적화용 — 다음 단계에서 θ 에 대한 경사를 탄다 | 해석적으로 구현 가능 |
| 2차 다항 | **설명용** — 계수를 그대로 읽는다. 교호작용항 포함 | 닫힌 형태 |
| XGBoost | **상한 확인용** — MLP 가 이보다 못하면 MLP 구조가 문제 | 계단이라 불가 |

MLP 와 2차 다항이 비슷한 최적 θ 를 가리키면 서로가 서로를 검증한다.
"""
import argparse
import csv
import json
import os
import sys

import numpy as np
from sklearn.inspection import permutation_importance
from sklearn.linear_model import Ridge
from sklearn.model_selection import GroupKFold
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import PolynomialFeatures, StandardScaler

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
FMS = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(FMS, "infra", "out")

SETS = {
    "blocked": ("차단 (운영)", "surrogate_blocked.csv",
                ["aisles", "pitch", "length", "free", "fleet"],
                ["loop_gain", "main_aisle_gain", "junction_penalty",
                 "station_in", "station_out", "wait_cost", "loop_dir"]),
    "open": ("개방", "surrogate_open.csv",
             ["aisles", "pitch", "length", "free", "fleet", "load_frac"],
             ["aisle_alt_gain", "aisle_alt_boost", "loop_gain", "main_aisle_gain",
              "junction_penalty", "station_in", "station_out", "wait_cost",
              "aisle_period", "aisle_phase", "loop_dir"]),
    # 병합 — θ 11축을 전부 학습할 수 있는 유일한 경로 (merge_surrogate_set.py)
    "merged": ("차단+개방 병합", "surrogate_merged.csv",
               ["aisles", "pitch", "length", "free", "fleet",
                "orders_per_robot", "aisle_block"],
               ["aisle_alt_gain", "aisle_alt_boost", "loop_gain", "main_aisle_gain",
                "junction_penalty", "station_in", "station_out", "wait_cost",
                "aisle_period", "aisle_phase", "loop_dir"]),
}


def load(path, feats, axes):
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    cols = feats + axes
    X = np.array([[float(r[c]) for c in cols] for r in rows])
    y = np.array([float(r["z"]) for r in rows])
    g = np.array([r["map"] for r in rows])
    return X, y, g, cols, rows


def mlp():
    return make_pipeline(StandardScaler(),
                         MLPRegressor(hidden_layer_sizes=(64, 64), activation="relu",
                                      alpha=1e-3, learning_rate_init=3e-3,
                                      max_iter=600, early_stopping=True,
                                      n_iter_no_change=20, random_state=0))


def poly():
    return make_pipeline(StandardScaler(), PolynomialFeatures(2, include_bias=False),
                         Ridge(alpha=10.0))


def xgb():
    try:
        from xgboost import XGBRegressor
        return XGBRegressor(n_estimators=500, max_depth=6, learning_rate=0.05,
                            subsample=0.8, colsample_bytree=0.8, reg_lambda=1.0,
                            random_state=0, verbosity=0, n_jobs=4)
    except ImportError:
        from sklearn.ensemble import GradientBoostingRegressor
        return GradientBoostingRegressor(n_estimators=400, max_depth=4,
                                         learning_rate=0.05, random_state=0)


def cv_r2(make, X, y, g, folds=5):
    """맵 단위 K-fold. 예측을 모아 한 번에 R² 를 낸다 (fold 별 R² 평균보다 안정적)."""
    pred = np.empty(len(y))
    last = None
    for tr, te in GroupKFold(n_splits=folds).split(X, y, g):
        m = make()
        m.fit(X[tr], y[tr])
        pred[te] = m.predict(X[te])
        last = (m, X[te], y[te])
    ss_res = float(((y - pred) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    return 1 - ss_res / ss_tot, pred, last


def main():
    p = argparse.ArgumentParser(description="대리 모델 학습·검증")
    p.add_argument("--set", default="blocked", choices=list(SETS) + ["both"])
    p.add_argument("--folds", type=int, default=5)
    p.add_argument("--out", default=HERE)
    a = p.parse_args()

    report = {}
    prev = os.path.join(a.out, "surrogate_report.json")
    if os.path.exists(prev):
        # --set 을 따로 돌려도 앞 조건 결과가 살아 있게 병합한다
        report.update(json.load(open(prev, encoding="utf-8")))
    keys = list(SETS) if a.set == "both" else [a.set]
    for key in keys:
        label, fname, feats, axes = SETS[key]
        path = os.path.join(OUT, fname)
        if not os.path.exists(path):
            print("%s — %s 가 없다. build_surrogate_set.py 를 먼저 돌릴 것" % (label, fname))
            continue
        X, y, g, cols, rows = load(path, feats, axes)
        print("=== %s · %d행 · 맵 %d개 · 입력 %d차원 ==="
              % (label, len(y), len(set(g)), X.shape[1]))
        print("  레이블 z 는 study 내 표준화 → **평균 예측기 R² = 0**")
        print()
        print("  %-14s%12s%14s" % ("모델", "맵단위 CV R²", "설명하는 분산"))
        print("  " + "-" * 40)

        res, models = {}, {}
        for name, make in (("MLP", mlp), ("2차 다항", poly), ("XGBoost", xgb)):
            r2, pred, last = cv_r2(make, X, y, g, a.folds)
            res[name] = r2
            models[name] = last
            print("  %-14s%12.3f%13.0f%%" % (name, r2, 100 * max(r2, 0)))

        best = max(res, key=res.get)
        print("\n  가장 나은 것: %s (R² %.3f)" % (best, res[best]))

        # 순열 중요도 — 마지막 fold 의 검증 세트에서. 어느 입력이 예측을 좌우하나
        m, Xte, yte = models[best]
        pi = permutation_importance(m, Xte, yte, n_repeats=10, random_state=0, n_jobs=1)
        order = np.argsort(-pi.importances_mean)
        print("\n  === 입력 중요도 (섞었을 때 R² 가 얼마나 떨어지나) ===")
        print("  %-20s%12s%10s" % ("입력", "중요도", "종류"))
        print("  " + "-" * 44)
        for i in order:
            kind = "맵" if cols[i] in feats else "θ"
            print("  %-20s%12.4f%10s" % (cols[i], pi.importances_mean[i], kind))

        # 2차 다항 계수 — 설명용. 전체 데이터로 한 번 더 적합해서 계수를 읽는다
        pm = poly().fit(X, y)
        names = pm.named_steps["polynomialfeatures"].get_feature_names_out(cols)
        coef = pm.named_steps["ridge"].coef_
        idx = np.argsort(-np.abs(coef))[:12]
        print("\n  === 2차 다항 상위 계수 (표준화된 입력 기준) ===")
        print("  %-34s%12s" % ("항", "계수"))
        print("  " + "-" * 46)
        for i in idx:
            print("  %-34s%12.4f" % (names[i], coef[i]))

        report[key] = {"label": label, "n_rows": len(y), "n_maps": len(set(g)),
                       "cv_r2": res, "best": best,
                       "importance": {cols[i]: float(pi.importances_mean[i])
                                      for i in order},
                       "top_poly": {str(names[i]): float(coef[i]) for i in idx}}
        print()

    out = os.path.join(a.out, "surrogate_report.json")
    json.dump(report, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("보고서 %s" % out)

    for key, r in report.items():
        best = r["cv_r2"][r["best"]]
        print("\n=== %s 판정 ===" % r["label"])
        if best < 0.05:
            print("  CV R² %.3f — 모델이 study 평균만 뱉는다. **여기서 멈춘다.**" % best)
            print("  처리량이 (맵, θ) 로 예측되지 않으므로 그 위의 θ 최적화는 뜻이 없다.")
        elif best < 0.25:
            print("  CV R² %.3f — 예측이 서긴 하지만 약하다." % best)
            print("  최적화는 해볼 수 있으나, 나온 θ 는 반드시 시뮬로 확인해야 한다.")
        else:
            print("  CV R² %.3f — 처음 보는 맵의 처리량을 예측한다." % best)
            print("  그 위에서 θ 를 최적화할 근거가 선다 → optimize_theta.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
