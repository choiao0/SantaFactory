# -*- coding: utf-8 -*-
"""θ 가 교착을 부르는가 — 완주 여부를 직접 수집한다 (S15P21A106-206).

## 왜 필요한가

개방 조건은 trial 41,600 개 중 **34,314 개(82 %)가 교착으로 잘려나갔다.** 그런데 지금
대리 모델은 **완주한 7,205 개만** 보고 배운다 — 멈춘 것들은 존재 자체를 모른다.

    모델이 배운 것   "이 θ 는 처리량이 높더라"
    실제로 일어난 일  그 θ 를 쓴 런의 상당수가 멈췄고, 살아남은 것만 모델에 들어갔다

**생존 편향**이다(`sweep_v2.py` 에서 한 번 잡았던 것과 같은 종류). 개방 모델의 맵 단위
CV R² 가 0.110 에 머무는 원인일 가능성이 크다.

원래 탐색 로그에서 되살리려 했으나 **중단 trial 은 θ 가 기록되지 않았다**(`run_study.py` 가
`TrialPruned` 만 남긴다). TPE 재현도 실패했다 — 중단 trial 이 첫 시드의 중간값을 보고한
뒤 끊긴 경우가 많은데 그 중간값이 로그에 없어 밀도가 달라진다.

## 그래서 새로 모은다 — 훨씬 싸다

분류 모델에는 TPE 도 시드 3개도 필요 없다. **멈추는가만** 보면 된다.

    θ 고르는 법   무작위(라틴 하이퍼큐브) — TPE 와 달리 좋은 영역에 안 몰린다
    시드          1개 — 완주 여부 판정에는 평균이 필요 없다
    규모          맵 30 x θ 100 = 3,000런 (서버 --jobs 40 으로 30~40분)

무작위가 **더 나은 데이터**이기도 하다. TPE 표본은 좋은 영역에 몰려 교착 사례가 편향되는데,
공간을 고르게 덮으면 완주/교착 경계가 제대로 잡힌다.

## 나오는 것

    (맵 특징 6, θ 11축) → 완주 0/1        분류 모델의 학습 세트
    완주한 런은 처리량도 같이 남긴다        회귀 모델에 보태 쓸 수 있다

이 둘을 합치면 **기대 처리량 = 완주 확률 x 예측 처리량** 을 최적화할 수 있다. 지금 목적함수는
교착을 아예 안 본다(`run_study.py` 는 교착한 θ 를 벌주지 않고 후보에서 빼기만 한다).
"""
import argparse
import csv
import itertools
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _fms_root(start):
    """3_FMS 를 찾아 올라간다 — 이 파일을 ai_theta/experiments 에 두든 infra 에 두든 같게 돈다."""
    d = start
    for _ in range(4):
        if all(os.path.isdir(os.path.join(d, x)) for x in ("sim_engine", os.path.join("map", "synth"))):
            return d
        d = os.path.dirname(d)
    raise SystemExit("3_FMS 를 못 찾았다 — sim_engine 과 map/synth 가 있는 폴더가 위에 없다")


HERE = os.path.dirname(os.path.abspath(__file__))
FMS = _fms_root(HERE)
SIM = os.path.join(FMS, "sim_engine")
SYNTH = os.path.join(FMS, "map", "synth")
OUT = os.path.join(FMS, "infra", "out")
sys.path.insert(0, SIM)
from map_loader import CELL_M          # noqa: E402
from pibt_core import MOVE_TICKS       # noqa: E402

SPEED, CAPACITY = 0.838, 6
DT = CELL_M / (SPEED * MOVE_TICKS)
RANGES = {"aisle_alt_gain": (1.0, 3.5), "aisle_alt_boost": (0.5, 1.0),
          "loop_gain": (1.0, 3.0), "main_aisle_gain": (0.5, 1.2),
          "junction_penalty": (1.0, 3.0), "station_in": (0.5, 1.0),
          "station_out": (1.0, 3.0), "wait_cost": (0.5, 3.0)}
CAT_VALUES = {"aisle_period": (1, 2, 3), "aisle_phase": (0, 1), "loop_dir": (0, 1)}
CONT = list(RANGES)
CATS = list(CAT_VALUES)
FEATS = ["aisles", "pitch", "length", "free", "fleet", "load_frac"]
# 차단(운영) 모드는 기존 차단 sweep(theta_sweep.py)과 조건을 맞춘다 — 그래야 나중에 합친다.
REF_ROBOTS, REF_ARRIVAL_S = 20, 4.0          # 20대 = 900건/h. 대수당 부하를 고정한다
BLOCKED_ORDERS = 250                         # theta_sweep.py --orders 기본값
# 통로를 막으면 이 4축은 비용판에 한 비트도 안 닿는다(계약 §5). 무작위로 뿌리면 순수
# 노이즈 입력이 돼 분류 모델이 헛것을 배운다 — 중립에 못 박는다.
DEAD_WHEN_BLOCKED = {"aisle_alt_gain": 1.0, "aisle_alt_boost": 1.0,
                     "aisle_period": 1, "aisle_phase": 0}


def orders_for(rate, orders_max=250, hours=1.0, floor=100):
    """theta_open_lhs.py 와 **같은 식**이어야 한다 — 주문 수가 다르면 다른 조건이다."""
    return max(floor, min(orders_max, round(rate * hours)))


def lhs(n, rng):
    """라틴 하이퍼큐브 — 축마다 구간을 n 등분해 한 칸씩만 쓴다. 무작위보다 고르게 덮는다."""
    d = len(CONT)
    try:
        from scipy.stats import qmc
        u = qmc.LatinHypercube(d=d, seed=int(rng.integers(1 << 31))).random(n)
    except ImportError:
        u = np.empty((n, d))
        for j in range(d):
            u[:, j] = (rng.permutation(n) + rng.random(n)) / n
    lo = np.array([RANGES[c][0] for c in CONT])
    hi = np.array([RANGES[c][1] for c in CONT])
    return lo + u * (hi - lo)


def sim(w, theta_path, seed, timeout, block=0):
    """완주하면 (1, 처리량), 못 하면 (0, None). rc!=0 · 타임아웃 · SUMMARY 없음이 전부 교착.

    차단(block=1)은 기존 차단 sweep 과 같은 조건으로 돈다 — 주문 250건 고정, 도착 간격은
    대수당 부하를 고정하는 식(REF_ARRIVAL_S x REF_ROBOTS / 대수). 개방은 용량 대비 상대부하다.
    """
    fleet = int(w["fleet"])
    if block:
        orders, gap = BLOCKED_ORDERS, (REF_ARRIVAL_S * REF_ROBOTS / fleet) / DT
    else:
        rate = w["cap"] * w["load_frac"]
        orders, gap = orders_for(rate), (3600.0 / rate) / DT
    cmd = [sys.executable, "sim_v2_tasks.py", "vf", str(fleet),
           str(orders), str(seed), str(block),
           "--order-gap=%.4f" % gap, "--capacity=%d" % CAPACITY,
           "--speed=%g" % SPEED, "--map-dir=" + os.path.join(SYNTH, w["name"]),
           "--theta=" + theta_path]
    env = dict(os.environ, SIM_NO_PLOT="1", PYTHONIOENCODING="utf-8",
               OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=SIM, env=env, capture_output=True, text=True,
                           encoding="utf-8", timeout=timeout)
    except subprocess.TimeoutExpired:
        return 0, None, time.time() - t0
    if p.returncode == 0:
        for line in (p.stdout or "").splitlines():
            if line.startswith("[SUMMARY] "):
                return 1, json.loads(line[10:])["tasks_per_h"], time.time() - t0
    return 0, None, time.time() - t0


def main():
    p = argparse.ArgumentParser(description="θ 별 교착 여부 수집 (개방 조건)")
    p.add_argument("--maps", type=int, default=30, help="쓸 맵 수 (설계에서 고르게 뽑는다)")
    p.add_argument("--thetas", type=int, default=100, help="맵마다 무작위 θ 개수")
    p.add_argument("--seed", type=int, default=101, help="평가 시드 1개 (계약 §5)")
    p.add_argument("--jobs", type=int, default=40)
    p.add_argument("--timeout", type=int, default=900)
    p.add_argument("--rng", type=int, default=0)
    p.add_argument("--design", default=os.path.join(OUT, "theta_open", "design.json"))
    p.add_argument("--aisle-block", type=int, default=0, choices=(0, 1), dest="block",
                   help="1 = 차단(운영). aisle_* 4축을 중립에 고정하고 주문 250건 고정으로 돈다")
    p.add_argument("--out", default=None)
    a = p.parse_args()
    if a.out is None:
        a.out = os.path.join(OUT, "theta_stall_blocked_v36.csv" if a.block
                             else "theta_stall_v36.csv")

    design = json.load(open(a.design, encoding="utf-8"))
    design = [d for d in design if all(k in d for k in FEATS + ["cap"])]
    # 통로 수 순으로 정렬해 고르게 솎는다 — 큰 맵만 뽑히면 교착률이 한쪽으로 쏠린다
    design.sort(key=lambda d: (d["aisles"], d["pitch"], d["length"]))
    step = max(1, len(design) // a.maps)
    maps = design[::step][:a.maps]
    if a.block:
        # 차단 sweep 은 README 권장 대수(free / 81)를 썼다. design.json 의 fleet 는 개방 LHS 로
        # 뽑은 값이라 다르다 — 기존 차단 데이터와 합치려면 rec_fleet 으로 맞춘다.
        maps = [dict(w, fleet=w.get("rec_fleet", w["fleet"])) for w in maps]

    rng = np.random.default_rng(a.rng)
    work_dir = os.path.join(OUT, "theta_stall_tmp")
    os.makedirs(work_dir, exist_ok=True)

    jobs = []
    for w in maps:
        cont = lhs(a.thetas, rng)
        for i in range(a.thetas):
            th = {c: float(cont[i, k]) for k, c in enumerate(CONT)}
            th.update({c: int(rng.choice(CAT_VALUES[c])) for c in CATS})
            if a.block:
                th.update(DEAD_WHEN_BLOCKED)      # 차단에서 무효인 4축은 중립에 못 박는다
            path = os.path.join(work_dir, "th_%s_%03d.json" % (w["name"], i))
            json.dump(th, open(path, "w", encoding="utf-8"), ensure_ascii=False)
            jobs.append((w, th, path))

    print("맵 %d개 x θ %d개 = 런 %d개 · 동시 %d · 시드 %d · %s"
          % (len(maps), a.thetas, len(jobs), a.jobs, a.seed,
             "차단(운영) · 주문 250건 고정 · aisle_* 중립" if a.block else "개방"))
    print("  맵 통로 수 %d~%d · 대수 %d~%d"
          % (min(w["aisles"] for w in maps), max(w["aisles"] for w in maps),
             min(w["fleet"] for w in maps), max(w["fleet"] for w in maps)))

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        res = list(pool.map(lambda j: sim(j[0], j[2], a.seed, a.timeout, a.block), jobs))
    mins = (time.time() - t0) / 60

    rows = []
    for (w, th, _), (ok, tp, secs) in zip(jobs, res):
        r = {"map": w["name"], "ok": ok, "tasks_per_h": "" if tp is None else round(tp, 1),
             "secs": round(secs, 1)}
        r.update({k: w[k] for k in FEATS})
        r.update(th)
        rows.append(r)
    cols = ["map"] + FEATS + CONT + CATS + ["ok", "tasks_per_h", "secs"]
    with open(a.out, "w", encoding="utf-8", newline="") as f:
        wtr = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        wtr.writeheader()
        wtr.writerows(rows)

    ok = sum(r["ok"] for r in rows)
    print("\n  %.0f분 · 완주 %d/%d (교착률 %.1f%%)"
          % (mins, ok, len(rows), 100 * (1 - ok / len(rows))))
    print("  CSV %s" % a.out)

    if ok in (0, len(rows)):
        print("\n  한쪽으로만 나왔다 — 분류 모델을 학습할 수 없다. 조건을 손볼 것.")
        return 1

    print("\n=== 축별 완주율 (범위를 반으로 갈라서) ===")
    print("  %-20s%12s%12s%10s" % ("θ 축", "하위절반", "상위절반", "차이"))
    print("  " + "-" * 54)
    out = []
    for c in CONT:
        v = np.array([r[c] for r in rows], float)
        o = np.array([r["ok"] for r in rows], float)
        mid = sum(RANGES[c]) / 2
        a1, a2 = o[v < mid].mean(), o[v >= mid].mean()
        out.append((c, a1, a2))
    for c, a1, a2 in sorted(out, key=lambda t: -abs(t[1] - t[2])):
        print("  %-20s%11.1f%%%11.1f%%%9.1f%%p" % (c, 100 * a1, 100 * a2, 100 * (a1 - a2)))
    for c in CATS:
        v = np.array([r[c] for r in rows], float)
        o = np.array([r["ok"] for r in rows], float)
        cells = [(k, o[v == k].mean()) for k in CAT_VALUES[c] if (v == k).sum() >= 10]
        print("  %-20s%s" % (c, "  ".join("%s→%.0f%%" % (k, 100 * m) for k, m in cells)))

    print("\n=== 맵별 완주율 ===")
    for name in sorted({r["map"] for r in rows}):
        g = [r for r in rows if r["map"] == name]
        print("  %-14s %3d/%3d (%3.0f%%)  통로 %2d · 대수 %2d"
              % (name, sum(x["ok"] for x in g), len(g),
                 100 * sum(x["ok"] for x in g) / len(g), g[0]["aisles"], g[0]["fleet"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
