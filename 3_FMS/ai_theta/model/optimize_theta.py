# -*- coding: utf-8 -*-
"""대리 모델 위에서 θ 를 경사상승으로 찾는다 (S15P21A106-206).

## 여기서 처음으로 경사법이 쓰인다

시뮬 자체는 미분이 안 된다 — PIBT 가 이웃 칸 중 `argmin` 을 고르므로 θ 를 미세하게 바꿔도
선택이 그대로면 처리량이 **정확히 같고**, 어느 지점에서 순위가 뒤집히면 계단처럼 점프한다.
목적함수가 조각별 상수라 기울기가 거의 모든 점에서 0 이고 경계에서는 정의되지 않는다.

그래서 시뮬을 흉내내는 **미분 가능한 대리 모델**(`train_surrogate.py`)을 세우고 **그 모델을
미분한다.** ReLU MLP 는 행렬곱 사슬이라 입력에 대한 기울기가 닫힌 형태로 나온다:

    dy/dx = W0 @ diag(z1>0) @ W1 @ diag(z2>0) @ W2      (표준화 스케일로 나눠 되돌린다)

## 두 학습 세트

    blocked  차단 전용 · 입력 12차원 · θ 7축   (맵 단위 CV R² 0.751)
    merged   차단+개방 · 입력 18차원 · θ 11축  (차단 행 R² 0.763)

`merged` 는 `aisle_block` 을 입력으로 받아 **θ 11축을 전부** 다룬다. 차단 조건 로그에는
`aisle_*` 4축이 `--exclude` 로 고정돼 아예 없으므로, 그 축들을 학습할 길은 병합뿐이다.
운영 θ 를 뽑을 때는 `--aisle-block 1` 로 고정한다.

## 평탄한 골짜기를 다루는 법

목적함수가 평평하면 `argmax` 한 점은 불안정하다. 그래서 둘을 같이 낸다.

1. **다중 시작점** — 무작위 시작점 여럿에서 경사를 태우고 상위 수렴점들의 **중심**을 쓴다.
2. **좋은 영역** — 무작위 θ 를 대량 평가해 **최적 대비 1 % 이내**인 것만 남기고 축별 폭을 잰다.

## 모델이 안 쓰는 축은 중립으로 내보낸다

최적점에서 축별 기울기 크기를 재서, 다른 축의 1 % 도 안 되는 축은 **모델이 무시하는 축**이다.
그 축의 '최적값' 은 시작점이 그대로 남은 것이라 뜻이 없으므로 `COST_NEUTRAL` 로 내보낸다.
"""
import argparse
import csv
import itertools
import json
import os
import sys

import numpy as np
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
FMS = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(FMS, "infra", "out")

RANGES = {"aisle_alt_gain": (1.0, 3.5), "aisle_alt_boost": (0.5, 1.0),
          "loop_gain": (1.0, 3.0), "main_aisle_gain": (0.5, 1.2),
          "junction_penalty": (1.0, 3.0), "station_in": (0.5, 1.0),
          "station_out": (1.0, 3.0), "wait_cost": (0.5, 3.0)}
CAT_VALUES = {"aisle_period": (1, 2, 3), "aisle_phase": (0, 1), "loop_dir": (0, 1)}
NEUTRAL = {"aisle_alt_gain": 1.0, "aisle_alt_boost": 1.0, "loop_gain": 1.0,
           "main_aisle_gain": 1.0, "junction_penalty": 1.0, "station_in": 1.0,
           "station_out": 1.0, "wait_cost": 1.0, "aisle_period": 1, "aisle_phase": 0}

SETS = {
    "blocked": {
        "csv": "surrogate_blocked.csv",
        "feats": ["aisles", "pitch", "length", "free", "fleet"],
        "cont": ["loop_gain", "main_aisle_gain", "junction_penalty",
                 "station_in", "station_out", "wait_cost"],
        "cat": ["loop_dir"],
        "sd_pct": 3.85,          # study 내 처리량 표준편차 (평균 대비 %)
    },
    "merged": {
        "csv": "surrogate_merged.csv",
        "feats": ["aisles", "pitch", "length", "free", "fleet",
                  "orders_per_robot", "aisle_block"],
        "cont": ["aisle_alt_gain", "aisle_alt_boost", "loop_gain", "main_aisle_gain",
                 "junction_penalty", "station_in", "station_out", "wait_cost"],
        "cat": ["aisle_period", "aisle_phase", "loop_dir"],
        "sd_pct": 3.85,          # aisle_block=1 기준. 개방이면 1.07 로 바뀐다
    },
}


def load(path, feats, axes):
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    cols = feats + axes
    X = np.array([[float(r[c]) for c in cols] for r in rows])
    y = np.array([float(r["z"]) for r in rows])
    maps = {}
    for r in rows:
        maps.setdefault(r["map"], {k: float(r[k]) for k in feats if k in r})
    return X, y, maps, cols, rows


def fit_mlp(X, y):
    m = make_pipeline(StandardScaler(),
                      MLPRegressor(hidden_layer_sizes=(64, 64), activation="relu",
                                   alpha=1e-3, learning_rate_init=3e-3, max_iter=600,
                                   early_stopping=True, n_iter_no_change=20,
                                   random_state=0))
    return m.fit(X, y)


class Grad:
    """ReLU MLP + StandardScaler 의 입력 기울기를 해석적으로 계산한다."""

    def __init__(self, pipe):
        sc = pipe.named_steps["standardscaler"]
        net = pipe.named_steps["mlpregressor"]
        self.mean, self.scale = sc.mean_, sc.scale_
        self.W, self.b = net.coefs_, net.intercepts_

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
        return a.ravel(), g / self.scale


def ascend(grad, base, lo, hi, idx, starts, steps=400, lr=0.05):
    n = len(starts)
    Xb = np.tile(base, (n, 1))
    Xb[:, idx] = starts
    span = hi - lo
    for _ in range(steps):
        _, g = grad.value_grad(Xb)
        step = lr * span * g[:, idx] / (np.abs(g[:, idx]).max(axis=1, keepdims=True) + 1e-9)
        Xb[:, idx] = np.clip(Xb[:, idx] + step, lo, hi)
    v, g = grad.value_grad(Xb)
    return Xb[:, idx], v, g[:, idx]


def main():
    p = argparse.ArgumentParser(description="대리 모델 위에서 θ 경사상승")
    p.add_argument("--set", default="merged", choices=list(SETS))
    p.add_argument("--aisle-block", type=int, default=1, choices=(0, 1), dest="aisle_block",
                   help="merged 전용 — 1=운영(차단), 0=개방")
    p.add_argument("--starts", type=int, default=40)
    p.add_argument("--samples", type=int, default=20000)
    p.add_argument("--within-pct", type=float, default=1.0)
    p.add_argument("--dead-ratio", type=float, default=0.01,
                   help="최대 기울기의 이 비율 미만이면 모델이 무시하는 축으로 본다")
    p.add_argument("--pin", default="auto",
                   help="최적화에서 빼고 중립에 못 박을 축 (쉼표). auto = 차단이면 aisle_* 4개")
    p.add_argument("--out", default=None)
    a = p.parse_args()

    S = SETS[a.set]
    CONT, CAT = list(S["cont"]), list(S["cat"])
    # 통로를 막으면 aisle_* 4축은 비용판에 한 비트도 안 닿는다(계약 §5). 그런데 병합 데이터의
    # 차단 행에는 그 축이 1.0 한 값뿐이라 모델이 그 방향으로는 **외삽**한다 — 실제로는 0 인
    # 변화를 4.4 % 라고 답한다. 아는 사실은 모델에 맡기지 않고 여기서 못 박는다.
    if a.pin == "auto":
        pin = ["aisle_alt_gain", "aisle_alt_boost", "aisle_period", "aisle_phase"]             if (a.set == "merged" and a.aisle_block == 1) else []
    else:
        pin = [x.strip() for x in a.pin.split(",") if x.strip()]
    pin = [c for c in pin if c in CONT + CAT]
    if pin:
        print("중립 고정 %d축: %s" % (len(pin), ", ".join(pin)))
    CONT = [c for c in CONT if c not in pin]
    CAT = [c for c in CAT if c not in pin]
    sd_pct = S["sd_pct"] if (a.set == "blocked" or a.aisle_block == 1) else 1.07
    z_per_pct = 1 / sd_pct
    out_dir = a.out or os.path.join(OUT, "theta_pred_" + a.set)
    os.makedirs(out_dir, exist_ok=True)

    # 모델 입력은 11축 전부다 — 고정 축도 열로 들어가야 한다. 최적화 대상만 CONT/CAT 로 줄인다
    X, y, maps, cols, rows = load(os.path.join(OUT, S["csv"]), S["feats"],
                                  list(S["cont"]) + list(S["cat"]))
    # merged 는 조건별로 맵 목록이 다르다 — 요청한 조건의 맵만 쓴다
    if "aisle_block" in S["feats"]:
        want = {r["map"] for r in rows if float(r["aisle_block"]) == a.aisle_block}
        maps = {k: v for k, v in maps.items() if k in want}
    print("학습 %d행 · 입력 %d차원 · θ %d축 (연속 %d + 범주 %d)"
          % (len(y), X.shape[1], len(CONT) + len(CAT), len(CONT), len(CAT)))
    print("조건 %s · 맵 %d개 · 처리량 1%% = z %.3f"
          % ("차단(운영)" if a.aisle_block else "개방", len(maps), z_per_pct))

    mlp = fit_mlp(X, y)
    grad = Grad(mlp)
    print("MLP 적합 완료 — 입력 기울기는 해석적으로 계산")

    idx = [cols.index(c) for c in CONT]
    cat_i = [cols.index(c) for c in CAT]
    lo = np.array([RANGES[c][0] for c in CONT])
    hi = np.array([RANGES[c][1] for c in CONT])
    combos = list(itertools.product(*[CAT_VALUES[c] for c in CAT]))
    print("범주형 조합 %d가지를 전부 돌린다: %s" % (len(combos), " x ".join(
        "%s(%d)" % (c, len(CAT_VALUES[c])) for c in CAT)))
    rng = np.random.default_rng(0)

    recs = []
    for name, mf in sorted(maps.items()):
        base = np.zeros(X.shape[1])
        for k, c in enumerate(cols):
            base[k] = mf.get(c, 0.0)
        if "aisle_block" in cols:
            base[cols.index("aisle_block")] = a.aisle_block
        for c in pin:
            base[cols.index(c)] = NEUTRAL[c]

        best = None
        for combo in combos:
            b = base.copy()
            for ci, v in zip(cat_i, combo):
                b[ci] = v
            starts = rng.uniform(lo, hi, size=(a.starts, len(CONT)))
            pts, vals, gs = ascend(grad, b, lo, hi, idx, starts)
            j = int(np.argmax(vals))
            if best is None or vals[j] > best[0]:
                best = (float(vals[j]), combo, b, pts, vals, gs[j])
        zbest, combo, b, pts, vals, gbest = best

        keep = pts[vals >= vals.max() - a.within_pct * z_per_pct]
        center = keep.mean(axis=0)

        # 모델이 실제로 쓰는 축인지 — 최적점 기울기 크기로 판정
        gmag = np.abs(gbest) * (hi - lo)          # 범위로 환산해 축끼리 비교 가능하게
        dead = gmag < a.dead_ratio * gmag.max()

        Sp = rng.uniform(lo, hi, size=(a.samples, len(CONT)))
        Xs = np.tile(b, (a.samples, 1))
        Xs[:, idx] = Sp
        vs, _ = grad.value_grad(Xs)
        good = Sp[vs >= vs.max() - a.within_pct * z_per_pct]
        width = ((good.max(axis=0) - good.min(axis=0)) / (hi - lo) * 100
                 if len(good) > 5 else np.full(len(CONT), np.nan))

        th = {}
        for k, c in enumerate(CONT):
            th[c] = NEUTRAL[c] if dead[k] else float(center[k])
        for c, v in zip(CAT, combo):
            th[c] = int(v)
        for c in pin:                      # 계약 스키마 11키를 유지한다
            th[c] = NEUTRAL[c]
        json.dump(th, open(os.path.join(out_dir, "theta_pred_%s.json" % name), "w",
                           encoding="utf-8"), ensure_ascii=False, indent=1)

        r = {"map": name, "z_pred": zbest, "n_converged": len(keep),
             "good_frac": len(good) / a.samples}
        r.update({c: th[c] for c in CONT + CAT})
        r.update({"w_" + c: float(width[k]) for k, c in enumerate(CONT)})
        r.update({"dead_" + c: int(dead[k]) for k, c in enumerate(CONT)})
        recs.append(r)

    csv_path = os.path.join(OUT, "theta_pred_%s_v36.csv" % a.set)
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(recs[0]))
        w.writeheader()
        w.writerows(recs)

    print("\n=== 맵별 예측 θ (경사상승 · 시작점 %d개 x 조합 %d가지) ==="
          % (a.starts, len(combos)))
    print("  %-18s%9s%9s%9s%9s%9s%9s" % ("축", "최소", "중앙", "최대", "맵간폭%", "영역폭%", "무효맵"))
    print("  " + "-" * 72)
    for k, c in enumerate(CONT):
        v = np.array([r[c] for r in recs])
        w = np.array([r["w_" + c] for r in recs], float)
        d = sum(r["dead_" + c] for r in recs)
        rlo, rhi = RANGES[c]
        print("  %-18s%9.3f%9.3f%9.3f%8.1f%%%8.0f%%%7d/%d"
              % (c, v.min(), np.median(v), v.max(),
                 100 * (v.max() - v.min()) / (rhi - rlo), np.nanmean(w), d, len(recs)))
    for c in CAT:
        v = [r[c] for r in recs]
        print("  %-18s%s" % (c, "  " + " · ".join(
            "%s→%d맵" % (k, v.count(k)) for k in sorted(set(v)))))

    print("\n  맵 %d개 · θ 파일 %s" % (len(recs), out_dir))
    print("  요약 CSV %s" % csv_path)

    live = [c for k, c in enumerate(CONT)
            if sum(r["dead_" + c] for r in recs) < len(recs) / 2]
    print("\n=== 판정 ===")
    print("  모델이 쓰는 연속 축 %d/%d: %s" % (len(live), len(CONT), ", ".join(live)))
    spans = [100 * (np.array([r[c] for r in recs]).max() - np.array([r[c] for r in recs]).min())
             / (RANGES[c][1] - RANGES[c][0]) for c in live]
    widths = [np.nanmean([r["w_" + c] for r in recs]) for c in live]
    print("  맵 간 이동폭  평균 %.1f%% · 좋은 영역 폭 평균 %.1f%% (처리량 %.0f%% 이내)"
          % (float(np.mean(spans)), float(np.nanmean(widths)), a.within_pct))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
