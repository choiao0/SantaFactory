# -*- coding: utf-8 -*-
"""모델 셋을 같은 조건에서 맞붙인다 — MLP · XGBoost · 2차 다항 (S15P21A106-206).

## 답하려는 질문

"왜 MLP 를 썼나" 에 지금은 **"미분이 돼서"** 밖에 답을 못 한다. 정확도로는 XGBoost 가 두
과제 모두 앞선다(처리량 R² 0.477 vs 0.421 · 교착 AUC 0.763 vs 0.715). 그러면 XGBoost 로
θ 를 뽑는 편이 나은 것 아닌가 — 그걸 **시뮬로** 확인한다.

## 최적화를 통일해야 비교가 성립한다

XGBoost 는 계단이라 경사를 못 탄다. 그렇다고 MLP 만 경사상승을 쓰면 **모델 차이인지
최적화 차이인지 갈라지지 않는다.**

그래서 **같은 후보 θ 10만 개를 세 모델에 똑같이 주고 각자 1등을 고르게 한다.** 후보 집합이
동일하므로 남는 차이는 오직 "어느 θ 가 좋은지 보는 눈" 뿐이다.

    exp       MLP + 경사상승      (기존 판에서 이미 돌림)
    mlpsamp   MLP + 샘플링        exp 와 비교하면 **최적화 방법의 효과**
    xgb       XGBoost + 샘플링    mlpsamp 와 비교하면 **모델의 효과**
    poly      2차 다항 + 샘플링

## 모델마다 두 개씩 필요하다

목적이 곱이라 분류(완주)와 회귀(처리량)를 각각 세 벌 만든다.

    기대 처리량 = P(완주 | 맵, θ) x 처리량비(맵, θ)

2차 다항 분류는 로지스틱 회귀에 2차 항을 넣은 것이다 — 선형 모델이라 경계가 매끄럽고,
계수를 그대로 읽을 수 있어 설명용으로도 쓴다.

## 판정

나온 θ 를 `theta_expected_value.py` 로 시뮬에 넣어 **기대 처리량**으로 순위를 매긴다.
모델 자신의 점수로 채점하면 저마다 자기 θ 가 1등이라 아무 뜻이 없다.
"""
import argparse
import csv
import json
import os
import sys

import numpy as np
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.neural_network import MLPClassifier, MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import PolynomialFeatures, StandardScaler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from optimize_expected import (CAT_VALUES, CATS, CONT, FEATS,  # noqa: E402
                               RANGES, load)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
FMS = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(FMS, "infra", "out")


def mlp_pair():
    return (make_pipeline(StandardScaler(),
                          MLPClassifier(hidden_layer_sizes=(64, 64), alpha=1e-3,
                                        learning_rate_init=3e-3, max_iter=800,
                                        early_stopping=True, n_iter_no_change=20,
                                        random_state=0)),
            make_pipeline(StandardScaler(),
                          MLPRegressor(hidden_layer_sizes=(64, 64), alpha=1e-3,
                                       learning_rate_init=3e-3, max_iter=800,
                                       early_stopping=True, n_iter_no_change=20,
                                       random_state=0)))


def xgb_pair():
    try:
        from xgboost import XGBClassifier, XGBRegressor
        return (XGBClassifier(n_estimators=400, max_depth=5, learning_rate=0.05,
                              subsample=0.8, colsample_bytree=0.8, reg_lambda=1.0,
                              random_state=0, verbosity=0, n_jobs=4,
                              eval_metric="logloss"),
                XGBRegressor(n_estimators=400, max_depth=5, learning_rate=0.05,
                             subsample=0.8, colsample_bytree=0.8, reg_lambda=1.0,
                             random_state=0, verbosity=0, n_jobs=4))
    except ImportError:
        from sklearn.ensemble import (GradientBoostingClassifier,
                                      GradientBoostingRegressor)
        return (GradientBoostingClassifier(n_estimators=300, max_depth=4,
                                           learning_rate=0.05, random_state=0),
                GradientBoostingRegressor(n_estimators=300, max_depth=4,
                                          learning_rate=0.05, random_state=0))


def poly_pair():
    """2차 항을 먼저 만들고 선형 모델을 얹는다 — 계수를 그대로 읽을 수 있다."""
    return (make_pipeline(StandardScaler(), PolynomialFeatures(2, include_bias=False),
                          LogisticRegression(max_iter=3000, C=1.0)),
            make_pipeline(StandardScaler(), PolynomialFeatures(2, include_bias=False),
                          Ridge(alpha=10.0)))


MODELS = (("mlpsamp", "MLP(샘플링)", mlp_pair),
          ("xgb", "XGBoost", xgb_pair),
          ("poly", "2차 다항", poly_pair))


def main():
    p = argparse.ArgumentParser(description="모델 셋으로 홀드아웃 θ 생성 (샘플링 통일)")
    p.add_argument("--csv", default=os.path.join(OUT, "theta_stall_v36.csv"))
    p.add_argument("--holdout", default=os.path.join(OUT, "theta_holdout_v36.csv"),
                   help="맵 목록을 여기서 읽는다 — 1판과 같은 창고여야 붙는다")
    p.add_argument("--design", default=os.path.join(OUT, "theta_open", "design.json"))
    p.add_argument("--samples", type=int, default=100000, help="후보 θ 개수")
    p.add_argument("--out", default=os.path.join(OUT, "theta_models_v36.csv"))
    a = p.parse_args()

    X, ok, ratio, g, cols, trained = load(a.csv)
    fit = np.isfinite(ratio)
    print("학습 %d행 · 완주 %d · 창고 %d개" % (len(ok), ok.sum(), len(trained)))

    fitted = {}
    for key, label, mk in MODELS:
        clf, reg = mk()
        clf.fit(X, ok)
        reg.fit(X[fit], ratio[fit])
        fitted[key] = (clf, reg)
        print("  %-12s 학습 완료" % label)

    names = [r["map"] for r in csv.DictReader(open(a.holdout, encoding="utf-8"))]
    design = {d["name"]: d for d in json.load(open(a.design, encoding="utf-8"))}
    hold = [design[n] for n in names if n in design]
    print("\n홀드아웃 %d창고 · 후보 θ %d개 (세 모델에 **같은 후보**를 준다)"
          % (len(hold), a.samples))

    idx = [cols.index(c) for c in CONT]
    cat_i = [cols.index(c) for c in CATS]
    lo = np.array([RANGES[c][0] for c in CONT])
    hi = np.array([RANGES[c][1] for c in CONT])
    rng = np.random.default_rng(0)

    # 후보 θ 를 **한 번만** 뽑아 모든 창고·모든 모델에 똑같이 쓴다
    cand = rng.uniform(lo, hi, size=(a.samples, len(CONT)))
    cand_cat = np.column_stack([rng.choice(CAT_VALUES[c], a.samples) for c in CATS])

    recs = []
    for w in hold:
        base = np.zeros(X.shape[1])
        for k, c in enumerate(cols):
            base[k] = float(w[c]) if c in w else 0.0
        Xs = np.tile(base, (a.samples, 1))
        Xs[:, idx] = cand
        Xs[:, cat_i] = cand_cat

        r = {"map": w["name"], "auc": "", "rho": "", "r2": ""}
        for key, label, _ in MODELS:
            clf, reg = fitted[key]
            pv = clf.predict_proba(Xs)[:, 1]
            rv = reg.predict(Xs)
            j = int(np.argmax(pv * rv))          # 기대 처리량이 최대인 후보
            r[key + "_p"], r[key + "_r"] = float(pv[j]), float(rv[j])
            r[key + "_exp"] = float(pv[j] * rv[j])
            r.update({key + "_" + c: float(cand[j, k]) for k, c in enumerate(CONT)})
            r.update({key + "_" + c: int(cand_cat[j, k]) for k, c in enumerate(CATS)})
        recs.append(r)
        print("  %-12s %s" % (w["name"], " · ".join(
            "%s P=%.2f" % (k, r[k + "_p"]) for k, _, _ in MODELS)))

    keys = [k for k, _, _ in MODELS]
    cols_out = ["map", "auc", "rho", "r2"] + \
        [k + "_" + x for k in keys for x in ["p", "r", "exp"] + CONT + CATS]
    with open(a.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols_out, extrasaction="ignore")
        w.writeheader()
        w.writerows(recs)

    print("\n=== 모델별 예측 θ (창고 %d개 중앙값) ===" % len(recs))
    print("  %-20s" % "θ 축" + "".join("%14s" % lab for _, lab, _ in MODELS))
    print("  " + "-" * (20 + 14 * len(MODELS)))
    for c in CONT:
        print("  %-20s" % c + "".join(
            "%14.3f" % float(np.median([r[k + "_" + c] for r in recs]))
            for k, _, _ in MODELS))
    for c in CATS:
        row = "  %-20s" % c
        for k, _, _ in MODELS:
            v = [r[k + "_" + c] for r in recs]
            row += "%14s" % max(set(v), key=v.count)
        print(row)
    print("\n  %-20s" % "예측 완주확률" + "".join(
        "%13.1f%%" % (100 * np.mean([r[k + "_p"] for r in recs])) for k, _, _ in MODELS))
    print("  %-20s" % "예측 기대처리량" + "".join(
        "%14.3f" % np.mean([r[k + "_exp"] for r in recs]) for k, _, _ in MODELS))

    print("\n  CSV %s" % a.out)
    print("  이 숫자는 **모델 자신의 점수**다 — 순위는 시뮬로 정한다:")
    print("    theta_expected_value.py --csv out/theta_models_v36.csv \\")
    print("      --arms mlpsamp,xgb,poly --work out/theta_models_eval \\")
    print("      --out out/theta_models_value_v36.csv --jobs 40")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
