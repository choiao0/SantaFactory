# -*- coding: utf-8 -*-
"""합성 창고 112개 · 랙 통로 개방 · 공간 채우기 θ 탐색 (S15P21A106-206).

**마지막 시뮬이다.** 목표는 `(창고 기하, 대수, 부하) → θ` 예측 모델의 학습 데이터를 만드는 것.

## 왜 통로를 여나

운영 조건(`aisle_block=1`)에서는 로봇이 랙 사이 통로에 못 들어가 **다니는 공간이 바깥 사각 링
하나**다. 합성 창고가 바꾸는 세 인자(통로 개수·간격·길이)는 전부 그 안쪽이라, AMR 관점에서는
링 둘레만 늘었다 줄었다 한다(실측: 통행칸 1050 ↔ 2601, 모양은 둘 다 두께 고정 사각 링).
링에서 A→B 는 시계/반시계 둘뿐이라 θ 가 고를 것이 없다.

통로를 열면 통로 6개짜리와 16개짜리가 **진짜로 다른 경로망**이 된다. 그래야 "창고 기하가 θ 를
바꾸는가" 를 지형 차이로 물을 수 있다. **운영 조건이 아니므로 여기서 뽑은 θ 는 쓰지 않는다** —
원인을 가르는 실험이다.

통로를 열면 `aisle_*` 4개가 살아나 탐색 축이 7 → 11 개가 된다(차단에서는 from_theta 의 통로
rank 구간이 차단 구간과 겹쳐 비트 단위로 무효라 중립 고정한다, 계약 §5).

## 왜 공간 채우기인가

축이 다섯(통로수·간격·길이·대수·부하)이라 격자는 `112 x 3 x 3 = 1,008` study 가 된다. 공간
채우기(라틴 하이퍼큐브)는 **창고마다 (대수, 부하)를 하나씩 다르게** 줘서 112 점으로 5차원을
덮는다. 대가는 표로 못 읽는다는 것 — 모델이 주변 점에서 보간해야 한다.

## 부하는 반드시 상대값이다

앞선 두 판이 부하를 절대값으로 줘서 **전부 포화 구간**이었고, 그래서 신호가 죽었다. 상대부하로
고친 뒤에야 처리량이 부하에 72~85 % 반응했고 `loop_gain` 에 신호/노이즈 2.3 배가 나왔다.
통로를 열면 통행칸이 23~35 % 늘어 **용량이 달라지므로 눈금을 여기서 다시 잰다**.

## 반복 2회

창고당 θ 를 한 번만 뽑으면 그 값의 63 % 가 탐색 노이즈다(재현성 측정). 2회 평균이면 노이즈
분산이 절반이 되고, 모델이 설명할 수 있는 천장이 37 % → 54 % 로 오른다. **점을 늘리는 것보다
레이블을 깨끗하게 하는 것이 크다** — 정답지가 흔들리면 점이 많아도 못 배운다.
"""
import argparse
import json
import os
import re
import statistics as st
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np


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
WORKER = os.path.join(FMS, "infra", "worker")
OUT = os.path.join(FMS, "infra", "out")
sys.path.insert(0, SIM)
from map_loader import CELL_M          # noqa: E402
from pibt_core import MOVE_TICKS       # noqa: E402

SPEED, CAPACITY, SEEDS = 0.838, 6, "42,43,44"
DT = CELL_M / (SPEED * MOVE_TICKS)
FLEET_MULT = (0.70, 1.30)              # 권장 대수(free/81) 대비 배수 범위
LOAD_FRAC = (0.45, 1.05)               # 개방 조건 용량 대비 비율. ① 에서 낮은 쪽에 구조가 있었다
FLEET_MIN = 8                          # 그보다 적으면 로봇이 안 마주쳐 θ 가 할 일이 없다
SAMPLER_SEEDS = (1, 2)                 # 반복 2회 — 레이블 노이즈를 절반으로
AXES = ["loop_gain", "main_aisle_gain", "junction_penalty",
        "station_in", "station_out", "wait_cost"]
NEUTRAL = {"aisle_alt_gain": 1.0, "aisle_alt_boost": 1.0, "loop_gain": 1.0,
           "main_aisle_gain": 1.0, "junction_penalty": 1.0, "station_in": 1.0,
           "station_out": 1.0, "wait_cost": 1.0,
           "aisle_period": 1, "aisle_phase": 0, "loop_dir": 0}
ROW = re.compile(r"^\|\s*.(r(\d+)p(\d+)l(\d+)).\s*\|")


def warehouses():
    """README 표 — 표도 생성물이라 여기서 다시 세면 어긋난다."""
    out = []
    with open(os.path.join(SYNTH, "README.md"), encoding="utf-8") as f:
        for line in f:
            m = ROW.match(line)
            if not m:
                continue
            col = [c.strip() for c in line.strip().strip("|").split("|")]
            out.append(dict(name=m.group(1), aisles=int(m.group(2)), pitch=int(m.group(3)),
                            length=int(m.group(4)), free=int(col[5]),
                            rec_fleet=int(col[6]), zone=int(col[7])))
    return out


def assign(ws, seed=0):
    """라틴 하이퍼큐브: 창고마다 (대수 배수, 부하 비율)을 하나씩. 각 축이 고르게 덮인다.

    축마다 [0,1) 을 n 구간으로 쪼개 구간마다 한 점씩 뽑고 섞는다. 그래서 n 점만으로도
    두 축이 전 구간에 고르게 퍼진다 — 격자처럼 곱으로 늘지 않는다.
    """
    n = len(ws)
    rng = np.random.default_rng(seed)
    u = np.stack([(rng.permutation(n) + rng.random(n)) / n for _ in range(2)], axis=1)
    for w, (a, b) in zip(ws, u):
        mult = FLEET_MULT[0] + a * (FLEET_MULT[1] - FLEET_MULT[0])
        # 충전 존 상한을 넘으면 시뮬이 assert 로 죽는다 — 여기서 먼저 자른다 (계약 §1)
        w["fleet"] = int(min(max(round(w["rec_fleet"] * mult), FLEET_MIN), w["zone"]))
        w["load_frac"] = LOAD_FRAC[0] + b * (LOAD_FRAC[1] - LOAD_FRAC[0])
    return ws


def orders_for(rate, orders_max=250, hours=1.0, floor=100):
    """부하에 맞춰 주문 수를 줄인다 — 고정하면 저부하 칸의 시뮬 시간이 몇 배로 튄다."""
    return max(floor, min(orders_max, round(rate * hours)))


def measure_capacity(w, neutral_path, orders=150, timeout=2400):
    """개방 조건에서 그 (창고, 대수)가 소화하는 최대 주문/h. 과포화로 넣고 achieved 를 읽는다."""
    cmd = [sys.executable, "sim_v2_tasks.py", "vf", str(w["fleet"]), str(orders), "101", "0",
           "--order-gap=%.4f" % (0.5 / DT), "--capacity=%d" % CAPACITY,
           "--speed=%g" % SPEED, "--map-dir=" + os.path.join(SYNTH, w["name"]),
           "--theta=" + neutral_path]           # 위치인자 4번째 0 = aisle_block 개방
    env = dict(os.environ, SIM_NO_PLOT="1", PYTHONIOENCODING="utf-8",
               OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    try:
        p = subprocess.run(cmd, cwd=SIM, env=env, capture_output=True, text=True,
                           encoding="utf-8", timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    for line in (p.stdout or "").splitlines():
        if line.startswith("[SUMMARY] "):
            return json.loads(line[10:])["orders_per_h"]
    return None


def tag(w, sseed):
    return "open_%s_r%d_L%d_s%d" % (w["name"], w["fleet"], round(w["load_frac"] * 100), sseed)


def study(job, trials, out_dir, prune):
    w, sseed = job
    t = tag(w, sseed)
    d = os.path.join(out_dir, t)
    theta = os.path.join(d, "theta_%s.json" % t)
    if os.path.exists(theta):
        return w["name"], sseed, 0.0, "건너뜀"
    os.makedirs(d, exist_ok=True)
    rate = w["cap"] * w["load_frac"]
    cmd = [sys.executable, "run_study.py",
           "--study", t,
           "--map-dir", os.path.join(SYNTH, w["name"]),
           "--robots", str(w["fleet"]), "--orders", str(orders_for(rate)),
           "--trials", str(trials), "--seeds", SEEDS,
           "--capacity", str(CAPACITY), "--speed", "%g" % SPEED,
           "--arrival-s", "%.4f" % (3600.0 / rate),
           "--aisle-block", "0",           # 개방 — 창고마다 다른 경로망
           "--exclude", "",                # aisle_* 4개가 살아난다 → 탐색 축 11
           "--sampler-seed", str(sseed),
           "--sim-engine", SIM, "--fms-root", FMS, "--out", d]
    if prune:
        cmd.append("--prune")
    env = dict(os.environ, SIM_NO_PLOT="1", PYTHONIOENCODING="utf-8",
               OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    env.pop("OPTUNA_STORAGE", None)
    t0 = time.time()
    with open(os.path.join(d, "run.log"), "w", encoding="utf-8") as f:
        rc = subprocess.run(cmd, cwd=WORKER, env=env, stdout=f,
                            stderr=subprocess.STDOUT).returncode
    ok = rc == 0 and os.path.exists(theta)
    return w["name"], sseed, time.time() - t0, ("OK" if ok else "실패 rc=%d" % rc)


def main():
    p = argparse.ArgumentParser(description="창고 112개 · 개방 · 공간 채우기 θ 탐색")
    p.add_argument("--jobs", type=int, default=40)
    p.add_argument("--trials", type=int, default=200)
    p.add_argument("--out", default=os.path.join(OUT, "theta_open"))
    p.add_argument("--lhs-seed", type=int, default=0, dest="lhs_seed")
    p.add_argument("--cap-only", action="store_true", help="용량만 재고 끝")
    p.add_argument("--no-prune", action="store_true")
    p.add_argument("--limit", type=int, default=0)
    a = p.parse_args()
    os.makedirs(a.out, exist_ok=True)

    ws = assign(warehouses(), a.lhs_seed)[:a.limit or None]
    neutral_path = os.path.join(a.out, "_neutral.json")
    with open(neutral_path, "w", encoding="utf-8") as f:
        json.dump(NEUTRAL, f)

    cap_file = os.path.join(a.out, "capacity.json")
    if os.path.exists(cap_file):
        cap = json.load(open(cap_file, encoding="utf-8"))
        print("용량 (저장된 값 사용) %d창고" % len(cap))
    else:
        print("① 개방 조건 용량 측정 — %d런" % len(ws))
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=a.jobs) as pool:
            vals = list(pool.map(lambda w: measure_capacity(w, neutral_path), ws))
        cap = {w["name"]: v for w, v in zip(ws, vals) if v}
        print("  %.0f분 · 성공 %d/%d" % ((time.time() - t0) / 60, len(cap), len(ws)))
        json.dump(cap, open(cap_file, "w", encoding="utf-8"), indent=1)
    ws = [w for w in ws if w["name"] in cap]
    for w in ws:
        w["cap"] = cap[w["name"]]

    print("\n  %-10s%6s%6s%6s%7s%8s%9s%10s"
          % ("창고", "통로", "간격", "길이", "대수", "용량", "부하%", "주문"))
    print("  " + "-" * 64)
    for w in ws[:6]:
        rate = w["cap"] * w["load_frac"]
        print("  %-10s%6d%6d%6d%7d%8.0f%8.0f%%%10d"
              % (w["name"], w["aisles"], w["pitch"], w["length"], w["fleet"],
                 w["cap"], w["load_frac"] * 100, orders_for(rate)))
    print("  ... (%d창고)" % len(ws))
    json.dump([{k: w[k] for k in ("name", "aisles", "pitch", "length", "free",
                                  "rec_fleet", "zone", "fleet", "load_frac", "cap")}
               for w in ws], open(os.path.join(a.out, "design.json"), "w", encoding="utf-8"),
              indent=1)
    os.unlink(neutral_path)
    if a.cap_only:
        return 0

    jobs = [(w, s) for w in ws for s in SAMPLER_SEEDS]
    print("\n② 탐색 — %d창고 x 반복 %d = %d study · 동시 %d · trial %d · 탐색축 11개"
          % (len(ws), len(SAMPLER_SEEDS), len(jobs), a.jobs, a.trials))

    t0, nok = time.time(), 0
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        for name, sseed, el, msg in pool.map(
                lambda j: study(j, a.trials, a.out, not a.no_prune), jobs):
            nok += msg in ("OK", "건너뜀")
            print("  %-12s s%d %6.1f분 %-10s (완료 %d/%d · 경과 %.0f분)"
                  % (name, sseed, el / 60, msg, nok, len(jobs),
                     (time.time() - t0) / 60), flush=True)
    print("\n끝. 총 %.0f분" % ((time.time() - t0) / 60))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
