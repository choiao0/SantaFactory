# -*- coding: utf-8 -*-
"""처음 보는 창고에서도 되는가 — 맵 하나씩 빼고 학습한다 (S15P21A106-206).

## 왜 필요한가

`optimize_expected.py` 가 낸 θ 는 **그 맵을 학습에 쓴 채로 그 맵의 θ 를 뽑은 것**이다.
시뮬 검증(`theta_expected_value.py`, 450런)에서 이렇게 나왔다.

    θ                완주율    완주시 처리량   기대 처리량
    처리량만          25.3 %      507.9         123.8
    기대 처리량(곱)    73.3 %      567.6         412.1      <- 공통 θ 대비 +72.9 % (p=5.2e-03)
    공통 θ           41.3 %      581.0         238.4

시드는 학습에 안 쓴 {103,104,105,107,109} 였으므로 **시드 일반화는 통과**했다. 남은 것은
맵이다 — 견적에 붙이려면 **처음 보는 창고**에 θ 를 내줘야 하는데, 지금 숫자는 그걸 재지 않았다.

## 하는 일

맵 30개를 하나씩 빼고, **나머지 29개로만** 분류·회귀 MLP 를 학습한 뒤 빠진 맵의 θ 를 뽑는다.
학습 코드는 `optimize_expected.py` 에서 그대로 가져온다(`Net`, `load`, 축 정의) — 기울기
구현이 갈라지면 비교가 성립하지 않는다.

## 시뮬을 돌리기 전에 먼저 보는 것

폴드마다 **빠진 맵의 100행으로 채점**한다. 이건 공짜이고, 여기서 갈리면 450런을 아낀다.

    AUC   빠진 맵의 완주/교착을 맞히는가   0.5 면 처음 보는 창고엔 아무것도 못 한다
    R²    빠진 맵의 처리량비를 맞히는가    음수면 맵 밖으로 못 나간다

in-sample 교착 분류는 AUC 0.715 였다(`stall_model_report.json`). 맵 단위로 나눴을 때
이 값이 얼마나 떨어지는지가 이 실험의 핵심 숫자다.

## 나오는 것

`theta_expected_v36.csv` 와 **열 이름이 같은** 표를 낸다. 그래서 검증은 새 스크립트 없이
그대로 돌아간다:

    python3 theta_expected_value.py --csv out/theta_expected_loo_v36.csv \
            --work out/theta_loo_eval --out out/theta_loo_value_v36.csv

이때 `tp_p`·`exp_p` 열은 **처음 보는 맵에 대한 예측**이라, 검증 스크립트가 찍는
"모델 예측 vs 실측" 표가 in-sample 때(89.6 % → 73.3 %)와 달리 정직한 보정 곡선이 된다.
"""
import argparse
import csv
import itertools
import json
import os
import sys

import numpy as np
from sklearn.metrics import roc_auc_score
from sklearn.neural_network import MLPClassifier, MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from optimize_expected import (CATS, CAT_VALUES, CONT, OUT,  # noqa: E402
                               RANGES, Net, load)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def fit_pair(X, ok, ratio, mask, seed=0):
    """빠진 맵을 뺀 행으로만 두 MLP 를 세운다 — optimize_expected.py 와 같은 설정."""
    clf = make_pipeline(StandardScaler(),
                        MLPClassifier(hidden_layer_sizes=(64, 64), alpha=1e-3,
                                      learning_rate_init=3e-3, max_iter=800,
                                      early_stopping=True, n_iter_no_change=20,
                                      random_state=seed)).fit(X[mask], ok[mask])
    m = mask & np.isfinite(ratio)
    reg = make_pipeline(StandardScaler(),
                        MLPRegressor(hidden_layer_sizes=(64, 64), alpha=1e-3,
                                     learning_rate_init=3e-3, max_iter=800,
                                     early_stopping=True, n_iter_no_change=20,
                                     random_state=seed)).fit(X[m], ratio[m])
    return clf, reg


def _rank(v):
    return np.argsort(np.argsort(np.asarray(v, float))).astype(float)


def score_holdout(clf, reg, X, ok, ratio, held):
    """빠진 맵 100행으로 채점한다 — AUC · R² · 순위상관. 한쪽 라벨뿐이면 AUC 는 None.

    처리량비는 **맵 안에서 평균 1** 로 정규화된 값이라 분산이 아주 작다(≈1±0.1). 그래서
    절대 수준이 조금만 밀려도 R² 가 크게 음수로 간다 — 다른 맵으로 학습했으니 당연하다.

    경사상승이 실제로 쓰는 것은 절대값이 아니라 **같은 맵 안에서 θ 끼리의 순서**다.
    그걸 재는 것이 순위상관(ρ)이고, 이쪽이 이 실험의 진짜 지표다.
    """
    auc = None
    if 0 < ok[held].sum() < held.sum():
        auc = float(roc_auc_score(ok[held], clf.predict_proba(X[held])[:, 1]))
    r2 = rho = None
    h = held & np.isfinite(ratio)
    if h.sum() >= 3:
        y, pred = ratio[h], reg.predict(X[h])
        ss = float(((y - y.mean()) ** 2).sum())
        r2 = 1.0 - float(((y - pred) ** 2).sum()) / ss if ss > 0 else None
        ry, rp = _rank(y), _rank(pred)
        if ry.std() > 0 and rp.std() > 0:
            rho = float(np.corrcoef(ry, rp)[0, 1])
    return auc, r2, rho


def main():
    p = argparse.ArgumentParser(description="맵 단위 LOO 로 기대 처리량 θ 를 뽑는다")
    p.add_argument("--csv", default=os.path.join(OUT, "theta_stall_v36.csv"))
    p.add_argument("--starts", type=int, default=40)
    p.add_argument("--steps", type=int, default=400)
    p.add_argument("--out", default=os.path.join(OUT, "theta_pred_loo"))
    p.add_argument("--table", default=os.path.join(OUT, "theta_expected_loo_v36.csv"))
    p.add_argument("--limit", type=int, default=0, help="앞에서 N 맵만 (연습용)")
    a = p.parse_args()

    X, ok, ratio, g, cols, maps = load(a.csv)
    names = sorted(maps)[:a.limit or None]
    print("맵 %d개 · 행 %d (완주 %d · 교착 %d) · 폴드마다 29맵으로 학습"
          % (len(names), len(ok), ok.sum(), (1 - ok).sum()))

    idx = [cols.index(c) for c in CONT]
    cat_i = [cols.index(c) for c in CATS]
    lo = np.array([RANGES[c][0] for c in CONT])
    hi = np.array([RANGES[c][1] for c in CONT])
    span = hi - lo
    combos = list(itertools.product(*[CAT_VALUES[c] for c in CATS]))
    os.makedirs(a.out, exist_ok=True)

    def ascend(P, R, base, mode, rng):
        """optimize_expected.py 의 경사상승과 같은 절차. mode: 'tp' 처리량만 · 'exp' 곱."""
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
                gr = rg[:, idx] if mode == "tp" else pg[:, idx] * rv[:, None] + pv[:, None] * rg[:, idx]
                step = 0.05 * span * gr / (np.abs(gr).max(axis=1, keepdims=True) + 1e-9)
                Xb[:, idx] = np.clip(Xb[:, idx] + step, lo, hi)
            pv, _ = P.value_grad(Xb)
            rv, _ = R.value_grad(Xb)
            obj = rv if mode == "tp" else pv * rv
            j = int(np.argmax(obj))
            if best is None or obj[j] > best[0]:
                best = (float(obj[j]), combo, Xb[j, idx].copy(), float(pv[j]), float(rv[j]))
        return best

    print("\n=== 폴드별 (빠진 맵 100행으로 채점) ===")
    print("  %-14s%9s%9s%10s%11s%11s"
          % ("빠진 맵", "AUC", "ρ", "R²", "예측 완주", "실측 완주"))
    print("  " + "-" * 62)
    recs, aucs, r2s, rhos = [], [], [], []
    for name in names:
        held = g == name
        clf, reg = fit_pair(X, ok, ratio, ~held)
        auc, r2, rho = score_holdout(clf, reg, X, ok, ratio, held)
        P, R = Net(clf, logistic=True), Net(reg)
        rng = np.random.default_rng(0)
        base = np.zeros(X.shape[1])
        for k, c in enumerate(cols):
            base[k] = maps[name].get(c, 0.0)

        r = {"map": name, "auc": "" if auc is None else round(auc, 4),
             "rho": "" if rho is None else round(rho, 4),
             "r2": "" if r2 is None else round(r2, 4)}
        for mode in ("tp", "exp"):
            _, combo, th, pv, rv = ascend(P, R, base, mode, rng)
            r[mode + "_p"], r[mode + "_r"], r[mode + "_exp"] = pv, rv, pv * rv
            out = {c: float(th[k]) for k, c in enumerate(CONT)}
            out.update({c: int(v) for c, v in zip(CATS, combo)})
            r.update({mode + "_" + c: out[c] for c in CONT + CATS})
            if mode == "exp":
                json.dump(out, open(os.path.join(a.out, "theta_loo_%s.json" % name), "w",
                                    encoding="utf-8"), ensure_ascii=False, indent=1)
        recs.append(r)
        if auc is not None:
            aucs.append(auc)
        if r2 is not None:
            r2s.append(r2)
        if rho is not None:
            rhos.append(rho)
        print("  %-14s%9s%9s%10s%10.1f%%%10.1f%%"
              % (name, "—" if auc is None else "%.3f" % auc,
                 "—" if rho is None else "%.3f" % rho,
                 "—" if r2 is None else "%.1f" % r2,
                 100 * r["exp_p"], 100 * ok[held].mean()), flush=True)

    with open(a.table, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(recs[0]))
        w.writeheader()
        w.writerows(recs)

    print("\n=== 처음 보는 맵에서의 모델 성능 ===")
    print("  교착 분류 AUC   평균 %.3f · 중앙값 %.3f · 폴드 %d개 (0.5 = 못 맞힌다)"
          % (float(np.mean(aucs)), float(np.median(aucs)), len(aucs)))
    print("                  in-sample 5-fold 는 0.715 였다 (stall_model_report.json)")
    print("  처리량 순위 ρ   평균 %.3f · 중앙값 %.3f · 폴드 %d개 (0 = θ 순서를 모른다)"
          % (float(np.mean(rhos)), float(np.median(rhos)), len(rhos)))
    print("  처리량비 R²     평균 %.1f · 중앙값 %.1f — 맵 안 분산이 ≈1±0.1 이라 절대 수준이"
          % (float(np.mean(r2s)), float(np.median(r2s))))
    print("                  조금만 밀려도 크게 음수다. 경사상승이 쓰는 것은 ρ 쪽이다.")

    tp_p = np.array([r["tp_p"] for r in recs])
    ex_p = np.array([r["exp_p"] for r in recs])
    ex_r = np.array([r["exp_r"] for r in recs])
    tp_r = np.array([r["tp_r"] for r in recs])
    print("\n=== LOO θ 가 내놓은 예측값 (in-sample 과 나란히) ===")
    print("  %-22s%14s%14s" % ("", "LOO", "in-sample"))
    print("  %-22s%13.1f%%%13.1f%%" % ("처리량만 완주확률", 100 * tp_p.mean(), 18.4))
    print("  %-22s%13.1f%%%13.1f%%" % ("기대 처리량 완주확률", 100 * ex_p.mean(), 89.6))
    print("  %-22s%14.3f%14.3f" % ("기대 처리량", (ex_p * ex_r).mean(), 1.182))

    print("\n  표 %s · θ %s" % (a.table, a.out))
    print("\n=== 판정 ===")
    m_auc, m_rho = float(np.mean(aucs)), float(np.mean(rhos))
    if m_auc < 0.55:
        print("  -> **처음 보는 창고에는 아무것도 못 한다** (AUC %.3f). 맵 안에서만 성립했다는 뜻이고," % m_auc)
        print("     450런을 더 쓸 이유가 없다. 견적에는 공통 θ 를 쓰고 모델은 접는다.")
    elif m_auc < 0.65:
        print("  -> 경계다 (AUC %.3f · ρ %.3f). in-sample 0.715 에서 떨어졌지만 동전보다는 낫다."
              % (m_auc, m_rho))
        print("     시뮬로 확인할 값은 있다 — 이득이 in-sample 의 절반 이하로 줄 것으로 본다.")
    else:
        print("  -> **맵을 넘어 일반화한다** (AUC %.3f · ρ %.3f). 견적에 붙일 근거가 선다."
              % (m_auc, m_rho))
        if m_rho < 0.2:
            print("     다만 완주 쪽만 일반화했다 — 처리량 순서는 못 맞힌다(ρ %.3f). 이득의 대부분은"
                  % m_rho)
            print("     '안 멈추는 θ' 에서 나오고 '빠른 θ' 에서 나오는 것이 아니다.")
    print("\n  다음: python3 theta_expected_value.py --csv %s \\" % os.path.basename(a.table))
    print("                --work out/theta_loo_eval --out out/theta_loo_value_v36.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
