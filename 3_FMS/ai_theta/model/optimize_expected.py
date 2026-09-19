# -*- coding: utf-8 -*-
"""기대 처리량으로 θ 를 찾는다 — 완주 확률 x 처리량 (S15P21A106-206).

## 왜 곱인가

지금 목적함수는 **처리량 하나**다. 교착한 θ 는 벌점이 아니라 후보에서 빠질 뿐이라
(`run_study.py` 가 `TrialPruned` 만 던진다), 탐색이 "안 멈추는 쪽" 으로 끌리지 않는다.
개방 조건에서 무작위 θ 의 **61.9 %가 교착**하는데 그걸 아예 안 보고 있었다.

그리고 두 목적이 **쓰는 축이 다르다**(`theta_stall_scan.py` 3,000런 실측):

    축                처리량 중요도   교착 중요도
    loop_gain            0.630          0.010      <- 처리량 1위, 교착에는 무관
    wait_cost            0.009          0.094      <- 처리량 0, **교착 1위**
    main_aisle_gain      0.277          0.052

`wait_cost` 는 죽은 축이 아니었다. **처리량에는 영향이 없지만 멈추느냐를 정한다.** 처리량만
보면 이 축이 안 보이고, 그래서 지금 θ 는 교착 위험을 전혀 고려하지 않은 값이다.

방향도 충돌한다 — `loop_gain` 은 처리량이 낮추라 하고 완주율이 높이라 한다. 한쪽만 보고
정하면 반대쪽이 나빠지므로 **곱으로 최적화한다**:

    기대 처리량 = P(완주 | 맵, θ) x 처리량비(맵, θ)

처리량비는 그 맵 완주 런들의 평균을 1 로 둔 값이라 항상 양수다. z 를 쓰면 음수가 나와
곱이 뒤집힌다.

## 두 모델 다 미분 가능해야 한다

분류기는 MLP 를 쓴다 — 로지스틱 출력이라 `dP/dx = P(1-P) x d(로짓)/dx` 로 기울기가 닫힌
형태로 나온다. XGBoost 가 AUC 는 높지만(0.763 vs 0.715) 계단이라 경사를 못 탄다.

곱의 기울기는 곱의 미분법 그대로:

    d(P x R)/dθ = (dP/dθ) x R + P x (dR/dθ)

## 판정

처리량만 최적화한 θ 와 기대 처리량으로 최적화한 θ 를 **두 모델 각각으로** 평가해 비교한다.
기대 처리량 쪽이 완주 확률을 크게 올리면서 처리량을 조금만 잃으면 바꿀 값이 있는 것이다.
"""
import argparse
import csv
import itertools
import json
import os
import sys

import numpy as np
from sklearn.neural_network import MLPClassifier, MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
FMS = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(FMS, "infra", "out")

FEATS = ["aisles", "pitch", "length", "free", "fleet", "load_frac"]
CONT = ["aisle_alt_gain", "aisle_alt_boost", "loop_gain", "main_aisle_gain",
        "junction_penalty", "station_in", "station_out", "wait_cost"]
CATS = ["aisle_period", "aisle_phase", "loop_dir"]
RANGES = {"aisle_alt_gain": (1.0, 3.5), "aisle_alt_boost": (0.5, 1.0),
          "loop_gain": (1.0, 3.0), "main_aisle_gain": (0.5, 1.2),
          "junction_penalty": (1.0, 3.0), "station_in": (0.5, 1.0),
          "station_out": (1.0, 3.0), "wait_cost": (0.5, 3.0)}
CAT_VALUES = {"aisle_period": (1, 2, 3), "aisle_phase": (0, 1), "loop_dir": (0, 1)}


class Net:
    """ReLU MLP + StandardScaler 의 값과 입력 기울기. 분류기면 로지스틱까지 통과시킨다."""

    def __init__(self, pipe, logistic=False):
        sc = pipe.named_steps["standardscaler"]
        net = pipe.named_steps["mlpclassifier" if logistic else "mlpregressor"]
        self.mean, self.scale = sc.mean_, sc.scale_
        self.W, self.b = net.coefs_, net.intercepts_
        self.logistic = logistic

    def value_grad(self, Xb):
        a = (Xb - self.mean) / self.scale
        acts = [a]
        for i, (W, b) in enumerate(zip(self.W, self.b)):
            a = a @ W + b
            if i < len(self.W) - 1:
                a = np.maximum(a, 0.0)
            acts.append(a)
        g = np.tile(self.W[-1].ravel(), (len(Xb), 1))
        for i in range(len(self.W) - 2, -1, -1):
            g = (g * (acts[i + 1] > 0)) @ self.W[i].T
        v = a.ravel()
        g = g / self.scale
        if self.logistic:
            p = 1.0 / (1.0 + np.exp(-v))
            return p, g * (p * (1 - p))[:, None]     # dP/dx = P(1-P) * d로짓/dx
        return v, g


def load(path):
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    cols = FEATS + CONT + CATS
    X = np.array([[float(r[c]) for c in cols] for r in rows])
    ok = np.array([int(r["ok"]) for r in rows])
    tp = np.array([float(r["tasks_per_h"]) if r["tasks_per_h"] else np.nan for r in rows])
    g = np.array([r["map"] for r in rows])
    # 처리량비 — 그 맵 완주 런들의 평균을 1 로. 맵 스케일을 지우면서 항상 양수다
    ratio = np.full(len(rows), np.nan)
    for m in set(g):
        sel = (g == m) & (ok == 1)
        if sel.sum() >= 3:
            ratio[sel] = tp[sel] / np.nanmean(tp[sel])
    maps = {}
    for r in rows:
        maps.setdefault(r["map"], {k: float(r[k]) for k in FEATS})
    return X, ok, ratio, g, cols, maps


def main():
    p = argparse.ArgumentParser(description="기대 처리량(완주확률 x 처리량)으로 θ 최적화")
    p.add_argument("--csv", default=os.path.join(OUT, "theta_stall_v36.csv"))
    p.add_argument("--starts", type=int, default=40)
    p.add_argument("--steps", type=int, default=400)
    p.add_argument("--out", default=os.path.join(OUT, "theta_pred_expected"))
    a = p.parse_args()

    X, ok, ratio, g, cols, maps = load(a.csv)
    fit = np.isfinite(ratio)
    print("=== 학습 ===")
    print("  분류(완주): %d행 · 완주 %d · 교착 %d" % (len(ok), ok.sum(), (1 - ok).sum()))
    print("  회귀(처리량): %d행 (완주 런만) · 맵 %d개" % (fit.sum(), len(maps)))

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
    P, R = Net(clf, logistic=True), Net(reg)
    print("  두 모델 다 MLP — 로지스틱·선형 출력이라 입력 기울기가 닫힌 형태로 나온다")

    idx = [cols.index(c) for c in CONT]
    cat_i = [cols.index(c) for c in CATS]
    lo = np.array([RANGES[c][0] for c in CONT])
    hi = np.array([RANGES[c][1] for c in CONT])
    span = hi - lo
    combos = list(itertools.product(*[CAT_VALUES[c] for c in CATS]))
    rng = np.random.default_rng(0)
    os.makedirs(a.out, exist_ok=True)

    def ascend(base, mode):
        """mode: 'tp' 처리량만 · 'exp' 기대 처리량(곱)"""
        best = None
        for combo in combos:
            b = base.copy()
            for ci, v in zip(cat_i, combo):
                b[ci] = v
            Xb = np.tile(b, (a.starts, 1))
            Xb[:, idx] = rng.uniform(lo, hi, size=(a.starts, len(CONT)))
            for _ in range(a.steps):
                pv, pg = P.value_grad(Xb)
                rv, rg = R.value_grad(Xb)
                if mode == "tp":
                    gr = rg[:, idx]
                else:                                   # 곱의 미분법
                    gr = pg[:, idx] * rv[:, None] + pv[:, None] * rg[:, idx]
                st = 0.05 * span * gr / (np.abs(gr).max(axis=1, keepdims=True) + 1e-9)
                Xb[:, idx] = np.clip(Xb[:, idx] + st, lo, hi)
            pv, _ = P.value_grad(Xb)
            rv, _ = R.value_grad(Xb)
            obj = rv if mode == "tp" else pv * rv
            j = int(np.argmax(obj))
            if best is None or obj[j] > best[0]:
                best = (float(obj[j]), combo, Xb[j, idx].copy(), float(pv[j]), float(rv[j]))
        return best

    recs = []
    for name, mf in sorted(maps.items()):
        base = np.zeros(X.shape[1])
        for k, c in enumerate(cols):
            base[k] = mf.get(c, 0.0)
        r = {"map": name}
        for mode in ("tp", "exp"):
            _, combo, th, pv, rv = ascend(base, mode)
            r[mode + "_p"] = pv
            r[mode + "_r"] = rv
            r[mode + "_exp"] = pv * rv
            out = {c: float(th[k]) for k, c in enumerate(CONT)}
            out.update({c: int(v) for c, v in zip(CATS, combo)})
            r.update({mode + "_" + c: out[c] for c in CONT + CATS})
            if mode == "exp":
                json.dump(out, open(os.path.join(a.out, "theta_exp_%s.json" % name), "w",
                                    encoding="utf-8"), ensure_ascii=False, indent=1)
        recs.append(r)

    with open(os.path.join(OUT, "theta_expected_v36.csv"), "w", encoding="utf-8",
              newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(recs[0]))
        w.writeheader()
        w.writerows(recs)

    tp_p = np.array([r["tp_p"] for r in recs])
    tp_r = np.array([r["tp_r"] for r in recs])
    ex_p = np.array([r["exp_p"] for r in recs])
    ex_r = np.array([r["exp_r"] for r in recs])
    print("\n=== 처리량만 최적화 vs 기대 처리량 최적화 (맵 %d개 평균) ===" % len(recs))
    print("  %-22s%14s%14s%14s" % ("목적", "완주 확률", "처리량비", "기대 처리량"))
    print("  " + "-" * 66)
    print("  %-22s%13.1f%%%14.3f%14.3f" % ("처리량만", 100 * tp_p.mean(), tp_r.mean(),
                                            (tp_p * tp_r).mean()))
    print("  %-22s%13.1f%%%14.3f%14.3f" % ("기대 처리량 (곱)", 100 * ex_p.mean(),
                                            ex_r.mean(), (ex_p * ex_r).mean()))
    print("  %-22s%+12.1f%%p%+14.1f%%%+13.1f%%"
          % ("차이", 100 * (ex_p - tp_p).mean(), 100 * (ex_r / tp_r - 1).mean(),
             100 * ((ex_p * ex_r) / (tp_p * tp_r) - 1).mean()))

    print()
    print("=== 두 θ 가 어디서 갈리나 (맵 중앙값) ===")
    print("  %-20s%12s%12s%12s" % ("θ 축", "처리량만", "기대", "이동(범위%)"))
    print("  " + "-" * 58)
    for c in CONT:
        v1 = float(np.median([r["tp_" + c] for r in recs]))
        v2 = float(np.median([r["exp_" + c] for r in recs]))
        lo_, hi_ = RANGES[c]
        print("  %-20s%12.3f%12.3f%11.0f%%" % (c, v1, v2, 100 * (v2 - v1) / (hi_ - lo_)))
    for c in CATS:
        a1 = [r["tp_" + c] for r in recs]
        a2 = [r["exp_" + c] for r in recs]
        print("  %-20s%12s%12s" % (c, max(set(a1), key=a1.count), max(set(a2), key=a2.count)))

    print("\n  θ 파일 %s · 요약 %s"
          % (a.out, os.path.join(OUT, "theta_expected_v36.csv")))

    print("\n=== 판정 ===")
    dp = 100 * (ex_p - tp_p).mean()
    dr = 100 * (ex_r / tp_r - 1).mean()
    if dp > 5 and dr > -5:
        print("  완주 확률을 %+.1f%%p 올리면서 처리량은 %+.1f%% — **곱으로 최적화할 값이 있다.**" % (dp, dr))
        print("  지금 목적함수(처리량만)는 교착을 전혀 고려하지 않아 이만큼을 잃고 있다.")
    elif dp < 1:
        print("  완주 확률이 %+.1f%%p 밖에 안 오른다 — 처리량 최적 θ 가 이미 안 멈치는 쪽이다." % dp)
    else:
        print("  완주 %+.1f%%p / 처리량 %+.1f%% — 교환이 뚜렷하다. 어느 쪽을 택할지는 운영 판단." % (dp, dr))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
