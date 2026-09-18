# -*- coding: utf-8 -*-
"""차단·개방 학습 세트를 합쳐 θ 11축 전부를 학습 가능하게 만든다 (S15P21A106-206).

## 왜 합치나

차단(운영) 조건은 `--exclude` 로 `aisle_*` 4축을 고정하고 탐색했다. 그래서 그 로그에는
네 축이 **상수로도 안 나온다** — 학습할 수가 없다. 개방 조건 로그에만 11축이 다 있다.

두 조건을 한 표로 합치고 **`aisle_block` 을 입력 특징으로 넣으면** 모델이
"통로를 막으면 `aisle_*` 가 결과를 안 바꾼다" 는 교호작용을 데이터에서 직접 배운다 —
개방 행에서만 그 축이 움직이므로.

## 부하 특징을 맞춘다

차단은 주문 250건 고정, 개방은 용량 대비 상대부하다. 그대로 두면 `load_frac` 열이
`aisle_block` 과 같은 값이 돼(차단은 전부 동일) 모델이 둘을 구분하지 못한다.

그래서 **대당 주문 수**(`orders_per_robot`)로 바꾼다 — 양쪽에서 계산되고 뜻도 같다.

    차단   250 / 대수
    개방   max(100, min(250, round(용량 x 상대부하))) / 대수     (탐색 때 쓴 식 그대로)

## 차단 행의 aisle_* 는 중립값으로 채운다

비워두는 게 아니라 `COST_NEUTRAL = 1.0` 을 넣는다. 그게 **실제로 그 런에서 쓰인 값**이다
(`--exclude` 는 축을 지우는 게 아니라 중립에 못 박는 것). 추정이 아니라 사실이다.
"""
import argparse
import csv
import json
import os
import sys

import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
FMS = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(FMS, "infra", "out")

GEOM = ["aisles", "pitch", "length", "free", "fleet"]
FEATS = GEOM + ["orders_per_robot", "aisle_block"]
AXES = ["aisle_alt_gain", "aisle_alt_boost", "loop_gain", "main_aisle_gain",
        "junction_penalty", "station_in", "station_out", "wait_cost",
        "aisle_period", "aisle_phase", "loop_dir"]
NEUTRAL = {"aisle_alt_gain": 1.0, "aisle_alt_boost": 1.0,
           "aisle_period": 1, "aisle_phase": 0}
BLOCKED_ORDERS = 250          # theta_sweep.py --orders 기본값


def orders_for(rate, orders_max=250, hours=1.0, floor=100):
    """theta_open_lhs.py 와 같은 식 — 다르면 다른 조건이 된다."""
    return max(floor, min(orders_max, round(rate * hours)))


def main():
    p = argparse.ArgumentParser(description="차단·개방 학습 세트 병합 (θ 11축)")
    p.add_argument("--out", default=os.path.join(OUT, "surrogate_merged.csv"))
    a = p.parse_args()

    design = {d["name"]: d for d in json.load(
        open(os.path.join(OUT, "theta_open", "design.json"), encoding="utf-8"))}

    recs = []
    # ── 차단(운영) ─────────────────────────────────────────────────────────
    nb = 0
    for r in csv.DictReader(open(os.path.join(OUT, "surrogate_blocked.csv"),
                                 encoding="utf-8")):
        row = {k: float(r[k]) for k in GEOM}
        row["orders_per_robot"] = BLOCKED_ORDERS / row["fleet"]
        row["aisle_block"] = 1
        row.update(NEUTRAL)                       # --exclude 가 실제로 쓴 값
        row.update({k: float(r[k]) for k in AXES if k in r})
        row.update({"study": r["study"], "map": r["map"], "z": float(r["z"]),
                    "tasks_per_h": float(r["tasks_per_h"])})
        recs.append(row)
        nb += 1

    # ── 개방 ──────────────────────────────────────────────────────────────
    no = 0
    for r in csv.DictReader(open(os.path.join(OUT, "surrogate_open.csv"),
                                 encoding="utf-8")):
        d = design.get(r["map"])
        if d is None:
            continue
        row = {k: float(r[k]) for k in GEOM}
        row["orders_per_robot"] = orders_for(float(d["cap"]) * float(d["load_frac"])) / row["fleet"]
        row["aisle_block"] = 0
        row.update({k: float(r[k]) for k in AXES})
        row.update({"study": r["study"], "map": r["map"], "z": float(r["z"]),
                    "tasks_per_h": float(r["tasks_per_h"])})
        recs.append(row)
        no += 1

    cols = ["study", "map"] + FEATS + AXES + ["tasks_per_h", "z"]
    with open(a.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(recs)

    opr = np.array([r["orders_per_robot"] for r in recs])
    blk = np.array([r["aisle_block"] for r in recs])
    print("병합 %d행 = 차단 %d + 개방 %d" % (len(recs), nb, no))
    print("  맵 %d개 · 입력 %d차원 = 맵 특징 %d + θ %d축"
          % (len({r["map"] for r in recs}), len(FEATS) + len(AXES), len(FEATS), len(AXES)))
    print("  대당 주문 수  차단 %.1f~%.1f · 개방 %.1f~%.1f  (겹쳐야 한다)"
          % (opr[blk == 1].min(), opr[blk == 1].max(),
             opr[blk == 0].min(), opr[blk == 0].max()))
    for ax in ("aisle_alt_gain", "aisle_alt_boost", "aisle_period", "aisle_phase"):
        v = np.array([r[ax] for r in recs], float)
        print("  %-18s 차단 고정 %.1f · 개방 %.2f~%.2f"
              % (ax, v[blk == 1][0], v[blk == 0].min(), v[blk == 0].max()))
    print("\n→ %s" % a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
