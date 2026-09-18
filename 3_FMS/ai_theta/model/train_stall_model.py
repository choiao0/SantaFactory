# -*- coding: utf-8 -*-
"""교착 예측 모델 — (맵, θ) → 완주 확률 (S15P21A106-206).

## 왜 필요한가

개방 조건에서 trial 41,600 개 중 **34,314 개(82 %)가 교착으로 잘려나갔다.** 그런데 처리량
대리 모델은 **완주한 것만** 보고 배운다 — 멈춘 것들은 존재 자체를 모른다. **생존 편향**이다.

학습곡선이 그 증거다. 차단 조건은 맵을 5배로 늘리면 R² 가 0.64 → 0.75 로 정상적으로 오르는데,
개방은 0.117 → −0.018 → 0.075 → 0.091 → 0.142 로 **오르내린다.** 단조가 아니면 데이터
부족이 아니라 신호가 잡음에 묻힌 것이고, 살아남은 표본을 더 모아도 편향은 그대로다.

그래서 `theta_stall_scan.py` 가 **무작위 θ 로 완주/교착을 고르게 수집**했다. 그 표로 여기서
분류 모델을 학습한다.

## 판정 기준은 정확도가 아니라 AUC 다

교착률이 50 % 근처면 정확도는 그럭저럭 나오지만, 한쪽으로 치우치면 "전부 완주" 라고만 해도
정확도가 높아진다. **AUC** 는 그 함정이 없다 — 무작위로 고른 완주 런과 교착 런 한 쌍을
줬을 때 완주 쪽에 더 높은 확률을 주는 비율이다.

    AUC 0.5   동전 던지기 (아무것도 못 배웠다)
    AUC 0.7   쓸 만하다
    AUC 0.9   잘 맞힌다

## 이 모델이 어디에 쓰이나

처리량 모델과 곱해 **기대 처리량**을 만든다. 지금 목적함수는 교착을 아예 안 본다
(`run_study.py` 는 교착한 θ 를 벌주지 않고 후보에서 빼기만 한다).

    기대 처리량 = 완주 확률(맵, θ) x 예측 처리량(맵, θ)

연기 시험 12건에서 이미 `loop_gain` 이 처리량과 완주율에서 **반대 방향**으로 나왔다 —
처리량은 낮추라 하고 완주율은 높이라 한다. 그 교환관계를 여기서 숫자로 잡는다.

MLP 분류기는 `predict_proba` 가 미분 가능해서 **경사상승에 그대로 쓸 수 있다.**
"""
import argparse
import csv
import json
import os
import sys

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.inspection import permutation_importance
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold
from sklearn.neural_network import MLPClassifier
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


def load(path):
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    cols = FEATS + CONT + CATS
    X = np.array([[float(r[c]) for c in cols] for r in rows])
    y = np.array([int(r["ok"]) for r in rows])
    g = np.array([r["map"] for r in rows])
    tp = np.array([float(r["tasks_per_h"]) if r["tasks_per_h"] else np.nan for r in rows])
    return X, y, g, tp, cols, rows


def mlp():
    return make_pipeline(StandardScaler(),
                         MLPClassifier(hidden_layer_sizes=(64, 64), activation="relu",
                                       alpha=1e-3, learning_rate_init=3e-3, max_iter=800,
                                       early_stopping=True, n_iter_no_change=20,
                                       random_state=0))


def logit():
    return make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=1.0))


def xgb():
    try:
        from xgboost import XGBClassifier
        return XGBClassifier(n_estimators=400, max_depth=5, learning_rate=0.05,
                             subsample=0.8, colsample_bytree=0.8, reg_lambda=1.0,
                             random_state=0, verbosity=0, n_jobs=4,
                             eval_metric="logloss")
    except ImportError:
        from sklearn.ensemble import GradientBoostingClassifier
        return GradientBoostingClassifier(n_estimators=300, max_depth=4,
                                          learning_rate=0.05, random_state=0)


def cv_auc(make, X, y, g, folds=5):
    """맵 단위 K-fold — 처음 보는 창고에서 교착을 맞히는지 본다."""
    pred = np.empty(len(y), float)
    last = None
    for tr, te in GroupKFold(n_splits=folds).split(X, y, g):
        if len(set(y[tr])) < 2:
            pred[te] = y[tr].mean()
            continue
        m = make()
        m.fit(X[tr], y[tr])
        pred[te] = m.predict_proba(X[te])[:, 1]
        last = (m, X[te], y[te])
    return roc_auc_score(y, pred), pred, last


def main():
    p = argparse.ArgumentParser(description="교착 예측 모델 학습·검증")
    p.add_argument("--csv", default=os.path.join(OUT, "theta_stall_v36.csv"))
    p.add_argument("--folds", type=int, default=5)
    p.add_argument("--out", default=HERE)
    a = p.parse_args()

    if not os.path.exists(a.csv):
        raise SystemExit("%s 가 없다 — theta_stall_scan.py 를 먼저 돌릴 것" % a.csv)
    X, y, g, tp, cols, rows = load(a.csv)
    base = max(y.mean(), 1 - y.mean())
    print("=== 교착 예측 · %d행 · 맵 %d개 · 입력 %d차원 ==="
          % (len(y), len(set(g)), X.shape[1]))
    print("  완주 %d · 교착 %d (교착률 %.1f%%)" % (y.sum(), (1 - y).sum(), 100 * (1 - y.mean())))
    print("  기준선: 무조건 다수 쪽으로 찍으면 정확도 %.1f%% · AUC 0.500" % (100 * base))
    if len(set(y)) < 2:
        print("  한쪽으로만 나왔다 — 학습 불가")
        return 1

    print()
    print("  %-14s%12s%12s" % ("모델", "맵단위 AUC", "정확도"))
    print("  " + "-" * 38)
    res, models = {}, {}
    for name, make in (("MLP", mlp), ("XGBoost", xgb), ("로지스틱", logit)):
        auc, pred, last = cv_auc(make, X, y, g, a.folds)
        acc = ((pred >= 0.5).astype(int) == y).mean()
        res[name] = {"auc": float(auc), "acc": float(acc)}
        models[name] = last
        print("  %-14s%12.3f%11.1f%%" % (name, auc, 100 * acc))

    best = max(res, key=lambda k: res[k]["auc"])
    print("\n  가장 나은 것: %s (AUC %.3f)" % (best, res[best]["auc"]))

    if models[best] is not None:
        m, Xte, yte = models[best]
        pi = permutation_importance(m, Xte, yte, n_repeats=10, random_state=0,
                                    scoring="roc_auc", n_jobs=1)
        order = np.argsort(-pi.importances_mean)
        print("\n  === 입력 중요도 (섞었을 때 AUC 가 얼마나 떨어지나) ===")
        print("  %-20s%12s%10s" % ("입력", "중요도", "종류"))
        print("  " + "-" * 44)
        for i in order:
            print("  %-20s%12.4f%10s"
                  % (cols[i], pi.importances_mean[i], "맵" if cols[i] in FEATS else "θ"))
        imp = {cols[i]: float(pi.importances_mean[i]) for i in order}
    else:
        imp = {}

    # 처리량과 완주율이 같은 방향인가 — 충돌하면 목적함수를 곱으로 바꿔야 한다
    print("\n  === 축별 완주율 vs 처리량 (범위를 반으로 갈라서) ===")
    print("  %-20s%11s%11s%10s%11s" % ("θ 축", "완주 하위", "완주 상위", "완주차", "처리량차"))
    print("  " + "-" * 64)
    conflict = []
    for c in CONT:
        v = X[:, cols.index(c)]
        mid = sum(RANGES[c]) / 2
        lo_m, hi_m = v < mid, v >= mid
        if lo_m.sum() < 20 or hi_m.sum() < 20:
            continue
        d_ok = y[lo_m].mean() - y[hi_m].mean()
        t_lo = np.nanmean(tp[lo_m & (y == 1)]) if (lo_m & (y == 1)).sum() else np.nan
        t_hi = np.nanmean(tp[hi_m & (y == 1)]) if (hi_m & (y == 1)).sum() else np.nan
        d_tp = t_lo - t_hi
        if np.isfinite(d_tp) and d_ok * d_tp < 0:
            conflict.append(c)
        print("  %-20s%10.1f%%%10.1f%%%9.1f%%p%10.1f%s"
              % (c, 100 * y[lo_m].mean(), 100 * y[hi_m].mean(), 100 * d_ok, d_tp,
                 "  <- 충돌" if c in conflict else ""))
    for c in CATS:
        v = X[:, cols.index(c)]
        cells = [(int(k), y[v == k].mean()) for k in np.unique(v) if (v == k).sum() >= 20]
        if cells:
            print("  %-20s%s" % (c, "  ".join("%d→%.0f%%" % (k, 100 * m) for k, m in cells)))

    out = os.path.join(a.out, "stall_model_report.json")
    json.dump({"n_rows": len(y), "n_maps": len(set(g)),
               "stall_rate": float(1 - y.mean()), "cv": res, "best": best,
               "importance": imp, "conflict_axes": conflict},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n  보고서 %s" % out)

    auc = res[best]["auc"]
    print("\n=== 판정 ===")
    if auc < 0.6:
        print("  AUC %.3f — 교착이 θ 로 설명되지 않는다." % auc)
        print("  맵 구조(폭 1칸 통로 데드엔드)가 원인이고 θ 로는 못 피한다는 뜻 — B트랙 건이다.")
    elif auc < 0.8:
        print("  AUC %.3f — θ 가 교착에 영향을 준다. 기대 처리량(완주확률 x 처리량)으로" % auc)
        print("  목적함수를 바꿀 근거가 선다.")
    else:
        print("  AUC %.3f — 교착을 θ 로 상당히 피할 수 있다." % auc)
        print("  지금 목적함수가 교착을 안 보는 것이 명백한 손실이다.")
    if conflict:
        print("  **처리량과 완주율이 충돌하는 축: %s**" % ", ".join(conflict))
        print("  이 축들은 한쪽만 보고 정하면 반대쪽이 나빠진다 — 곱으로 최적화해야 한다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
