# -*- coding: utf-8 -*-
"""홀드아웃 창고의 θ 를 예측하고 모델을 파일로 남긴다 (S15P21A106-206).

## 무엇을 하나

1. 스톨 스캔 3,000행으로 **MLP 두 개**를 학습한다 — 완주 분류 + 처리량 회귀
2. 그 가중치를 `theta_model.joblib` 에 **저장**한다 (데모에서 재학습하지 않도록)
3. 학습에 **한 번도 안 쓴 창고**를 골라 θ 를 뽑는다
4. `theta_expected_value.py` 가 읽는 형식으로 CSV 를 쓴다

## 홀드아웃이 왜 필요한가

스톨 스캔은 `design.json` 104창고 중 **30개**만 썼다. 나머지 74개는 모델이 존재조차 모른다.
LOO 는 "그 창고를 빼고 학습" 이라 같은 것을 재지만, 시연에서 **"이 창고는 학습에 안 썼다"**
고 말하려면 실제로 안 쓴 창고여야 한다.

통로 수가 고르게 퍼지도록 솎는다 — 큰 창고만 뽑히면 교착률이 한쪽으로 쏠린다.

## 두 비교군을 다 뽑는 이유

    tp    처리량만 최대화        목적함수에서 완주율을 빼면 어떻게 되는지
    exp   완주확률 x 처리량      주인공

검증 러너가 여기에 `expmean`(exp θ 들의 평균)과 `common`(운영 θ)을 더해 4개로 붙인다.
`exp - expmean` 이 창고별 맞춤 단독 효과다.

## 저장 형식

    theta_model.joblib   {clf, reg, cols, feats, cont, cats}

`predict_theta.py` 가 이 파일만 읽어 0.1초에 θ 를 낸다 — 학습 데이터도 sklearn 학습도
필요 없다.
"""
import argparse
import csv
import itertools
import json
import os
import sys

import numpy as np
from joblib import dump
from sklearn.neural_network import MLPClassifier, MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from optimize_expected import (CAT_VALUES, CATS, CONT, FEATS, Net,  # noqa: E402
                               RANGES, load)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
FMS = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(FMS, "infra", "out")


def ascend(P, R, base, idx, lo, hi, mode, starts, rng, steps=400, lr=0.05):
    """기대 처리량(또는 처리량 단독) 위에서 경사상승. 곱의 기울기는 곱의 미분법 그대로."""
    span = hi - lo
    Xb = np.tile(base, (starts, 1))
    Xb[:, idx] = rng.uniform(lo, hi, size=(starts, len(idx)))
    for _ in range(steps):
        pv, pg = P.value_grad(Xb)
        rv, rg = R.value_grad(Xb)
        gr = rg[:, idx] if mode == "tp" else \
            pg[:, idx] * rv[:, None] + pv[:, None] * rg[:, idx]
        st = lr * span * gr / (np.abs(gr).max(axis=1, keepdims=True) + 1e-9)
        Xb[:, idx] = np.clip(Xb[:, idx] + st, lo, hi)
    pv, _ = P.value_grad(Xb)
    rv, _ = R.value_grad(Xb)
    obj = rv if mode == "tp" else pv * rv
    j = int(np.argmax(obj))
    return Xb[j, idx].copy(), float(pv[j]), float(rv[j])


def main():
    p = argparse.ArgumentParser(description="홀드아웃 창고 θ 예측 + 모델 저장")
    p.add_argument("--csv", default=os.path.join(OUT, "theta_stall_v36.csv"))
    p.add_argument("--design", default=os.path.join(OUT, "theta_open", "design.json"))
    p.add_argument("--maps", type=int, default=20, help="홀드아웃 창고 수")
    p.add_argument("--starts", type=int, default=40)
    p.add_argument("--model", default=os.path.join(HERE, "theta_model.joblib"))
    p.add_argument("--out", default=os.path.join(OUT, "theta_holdout_v36.csv"))
    a = p.parse_args()

    X, ok, ratio, g, cols, trained = load(a.csv)
    fit = np.isfinite(ratio)
    print("=== 학습 ===")
    print("  분류(완주) %d행 · 완주 %d · 교착 %d (교착률 %.1f%%)"
          % (len(ok), ok.sum(), (1 - ok).sum(), 100 * (1 - ok.mean())))
    print("  회귀(처리량) %d행 · 학습 창고 %d개" % (fit.sum(), len(trained)))

    clf = make_pipeline(StandardScaler(),
                        MLPClassifier(hidden_layer_sizes=(64, 64), alpha=1e-3,
                                      learning_rate_init=3e-3, max_iter=800,
                                      early_stopping=True, n_iter_no_change=20,
                                      random_state=0)).fit(X, ok)
    reg = make_pipeline(StandardScaler(),
                        MLPRegressor(hidden_layer_sizes=(64, 64), alpha=1e-3,
                                     learning_rate_init=3e-3, max_iter=800,
                                     early_stopping=True, n_iter_no_change=20,
                                     random_state=0)).fit(X[fit], ratio[fit])
    dump({"clf": clf, "reg": reg, "cols": cols, "feats": FEATS,
          "cont": CONT, "cats": CATS, "ranges": RANGES, "cat_values": CAT_VALUES,
          "trained_maps": sorted(trained)}, a.model)
    print("  모델 저장 %s (%.0f KB)" % (a.model, os.path.getsize(a.model) / 1024))

    # ── 홀드아웃 고르기 — 학습에 한 번도 안 쓴 창고에서 통로 수가 고르게 ──
    design = [d for d in json.load(open(a.design, encoding="utf-8"))
              if all(k in d for k in FEATS) and d["name"] not in trained]
    design.sort(key=lambda d: (d["aisles"], d["pitch"], d["length"]))
    step = max(1, len(design) // a.maps)
    hold = design[::step][:a.maps]
    print("\n=== 홀드아웃 ===")
    print("  후보 %d창고(학습 %d개 제외) → %d개 선정 · 통로 %d~%d · 대수 %d~%d"
          % (len(design), len(trained), len(hold),
             min(h["aisles"] for h in hold), max(h["aisles"] for h in hold),
             min(h["fleet"] for h in hold), max(h["fleet"] for h in hold)))

    P, R = Net(clf, logistic=True), Net(reg)
    idx = [cols.index(c) for c in CONT]
    cat_i = [cols.index(c) for c in CATS]
    lo = np.array([RANGES[c][0] for c in CONT])
    hi = np.array([RANGES[c][1] for c in CONT])
    combos = list(itertools.product(*[CAT_VALUES[c] for c in CATS]))
    rng = np.random.default_rng(0)

    recs = []
    for w in hold:
        base = np.zeros(X.shape[1])
        for k, c in enumerate(cols):
            base[k] = float(w[c]) if c in w else 0.0
        r = {"map": w["name"], "auc": "", "rho": "", "r2": ""}
        for mode in ("tp", "exp"):
            best = None
            for combo in combos:
                b = base.copy()
                for ci, v in zip(cat_i, combo):
                    b[ci] = v
                th, pv, rv = ascend(P, R, b, idx, lo, hi, mode, a.starts, rng)
                obj = rv if mode == "tp" else pv * rv
                if best is None or obj > best[0]:
                    best = (obj, combo, th, pv, rv)
            _, combo, th, pv, rv = best
            r[mode + "_p"], r[mode + "_r"], r[mode + "_exp"] = pv, rv, pv * rv
            r.update({mode + "_" + c: float(th[k]) for k, c in enumerate(CONT)})
            r.update({mode + "_" + c: int(v) for c, v in zip(CATS, combo)})
        recs.append(r)

    cols_out = ["map", "auc", "rho", "r2"] + \
        [m + "_" + x for m in ("tp", "exp")
         for x in ["p", "r", "exp"] + CONT + CATS]
    with open(a.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols_out, extrasaction="ignore")
        w.writeheader()
        w.writerows(recs)

    print("\n=== 예측 θ (홀드아웃 %d창고 중앙값) ===" % len(recs))
    print("  %-20s%12s%12s" % ("θ 축", "처리량만", "기대(곱)"))
    print("  " + "-" * 46)
    for c in CONT:
        print("  %-20s%12.3f%12.3f"
              % (c, float(np.median([r["tp_" + c] for r in recs])),
                 float(np.median([r["exp_" + c] for r in recs]))))
    for c in CATS:
        v1 = [r["tp_" + c] for r in recs]
        v2 = [r["exp_" + c] for r in recs]
        print("  %-20s%12s%12s" % (c, max(set(v1), key=v1.count),
                                   max(set(v2), key=v2.count)))
    print("\n  모델이 예측한 완주 확률  처리량만 %.1f%% · 기대(곱) %.1f%%"
          % (100 * np.mean([r["tp_p"] for r in recs]),
             100 * np.mean([r["exp_p"] for r in recs])))
    print("  (LOO 실측은 각각 50.0%% · 64.0% 였다 — 모델은 낙관 쪽으로 빗나간다)")
    print("\n  CSV %s" % a.out)
    print("  다음: 이 CSV 와 θ 를 서버로 올려 theta_expected_value.py 로 400런")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
