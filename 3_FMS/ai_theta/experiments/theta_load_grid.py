# -*- coding: utf-8 -*-
"""공식 맵에서 대수 × **상대부하** 가 θ 를 바꾸는가 (S15P21A106-206).

**시연·운영과 같은 조건**이다 — 공식 맵 하나, 랙 통로 차단(`aisle_block=1`).
견적이 사용자에게서 받는 것도 대수와 물량 둘뿐이라, 여기서 갈리면 그대로 제품에 붙는다.

## 지난 판(theta_grid)이 왜 틀렸나

부하를 **절대값**(600·900·1200·1500건/h)으로 줬다. 그런데 14대의 실제 용량이 420주문/h 라
네 지점이 **전부 과부하 한 점**이었다. 실측이 남아 있다 — 13대에 585건/h 를 넣었더니
"843 태스크/시간(327 주문/시간)", 공급의 56 % 만 처리했다. 공급을 2.5배 올려도 처리량이
2~4 % 밖에 안 늘어난 것이 그 증거다. **물량을 바꾼 게 아니라 같은 조건을 네 번 잰 것**이다.

θ 가 일하는 구간은 따로 있다:

    부하 50 %   한가함   — 로봇이 서로 안 마주친다. θ 가 할 일이 없다
    부하 75 %   붐빔     — **여기가 핵심**
    부하 100 %  딱 맞음  — **여기도**
    부하 125 %  과부하   — 뭘 해도 막힌다  ← 지난번엔 이 오른쪽만 봤다

그래서 부하를 **그 대수의 용량 대비 비율**로 준다. 대수마다 자기 눈금을 쓰므로 모든 구성이
한가함 → 과부하를 똑같이 가로지른다.

## 용량은 먼저 잰다

각 대수를 **포화시켜** 돌려 achieved orders/h 를 읽는다(중립 θ · 시드 1개 · 6런 · 1분).
그 값이 100 % 의 눈금이다. 여기서 잰 값을 쓰지 않고 이전 CSV 를 끌어오면 대수 8·12·16 이 없다.

## 대수 하한이 8 인 이유

로봇이 그보다 적으면 서로 안 마주쳐 혼잡 자체가 없다. 계약 §5 와 map/synth/README 의
"8대는 효과가 약하고 28대는 시드마다 부호가 갈린다" 가 그 관찰이다. 28 은 공식 맵 충전 존
상한(MAX_ROBOTS)이라 견적이 받을 수 있는 위쪽 끝을 덮는다.
"""
import argparse
import itertools
import json
import os
import statistics as st
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor


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
WORKER = os.path.join(FMS, "infra", "worker")
OUT = os.path.join(FMS, "infra", "out")
sys.path.insert(0, SIM)
from map_loader import CELL_M          # noqa: E402
from pibt_core import MOVE_TICKS       # noqa: E402

SPEED, CAPACITY, SEEDS = 0.838, 6, "42,43,44"
DT = CELL_M / (SPEED * MOVE_TICKS)
FLEETS = (8, 12, 16, 20, 24, 28)       # 28 = 공식 맵 충전 존 상한 (계약 §1)
LOADS = (0.50, 0.75, 1.00)             # 용량 대비 비율. 125 % 는 지난 판(theta_grid)이
                                       # 이미 본 구간이다 — 전부 과부하라 +0.14 % 로 묻혔다
SAMPLER_SEEDS = (1, 2, 3)              # 반복 — 탐색 노이즈를 재야 신호와 구분된다
AXES = ["loop_gain", "main_aisle_gain", "junction_penalty",
        "station_in", "station_out", "wait_cost"]
NEUTRAL = {"aisle_alt_gain": 1.0, "aisle_alt_boost": 1.0, "loop_gain": 1.0,
           "main_aisle_gain": 1.0, "junction_penalty": 1.0, "station_in": 1.0,
           "station_out": 1.0, "wait_cost": 1.0,
           "aisle_period": 1, "aisle_phase": 0, "loop_dir": 0}


def measure_capacity(fleet, orders, neutral_path, timeout=1800):
    """그 대수가 소화하는 최대 주문/h. 일부러 과포화(간격 0.5초)로 넣고 achieved 를 읽는다."""
    cmd = [sys.executable, "sim_v2_tasks.py", "vf", str(fleet), str(orders), "101", "1",
           "--order-gap=%.4f" % (0.5 / DT), "--capacity=%d" % CAPACITY,
           "--speed=%g" % SPEED, "--theta=" + neutral_path]
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


def tag(fleet, frac, sseed):
    return "r%d_L%d_s%d" % (fleet, round(frac * 100), sseed)


def paths(out_dir, fleet, frac, sseed):
    t = tag(fleet, frac, sseed)
    d = os.path.join(out_dir, t)
    return d, os.path.join(d, "theta_load_%s.json" % t), os.path.join(d, "meta_load_%s.json" % t)


def orders_for(rate, orders_max, hours=1.0, floor=100):
    """그 부하에서 `hours` 시간쯤 돌 만큼의 주문 수.

    주문 수를 고정하면 **저부하 칸이 터진다** — 8대·부하 50 % 는 64건/h 라 250건이면 시뮬
    시간이 3.9 시간, 그 칸 하나가 12 시간을 먹는다. 부하에 비례해 줄이면 모든 칸이 비슷한
    길이가 되고, 그래야 격자 전체가 하룻밤에 들어온다.
    바닥(floor)을 두는 것은 주문이 너무 적으면 표본이 얇아 시드 산포가 커지기 때문이다."""
    return max(floor, min(orders_max, round(rate * hours)))


def study(job, trials, orders_max, out_dir, cap, prune):
    fleet, frac, sseed = job
    d, theta, _ = paths(out_dir, fleet, frac, sseed)
    if os.path.exists(theta):
        return fleet, frac, sseed, 0.0, "건너뜀"
    os.makedirs(d, exist_ok=True)
    rate = cap[fleet] * frac                              # 주문/h
    orders = orders_for(rate, orders_max)
    cmd = [sys.executable, "run_study.py",
           "--study", "load_" + tag(fleet, frac, sseed),
           "--robots", str(fleet), "--orders", str(orders), "--trials", str(trials),
           "--seeds", SEEDS, "--capacity", str(CAPACITY), "--speed", "%g" % SPEED,
           "--arrival-s", "%.4f" % (3600.0 / rate),
           "--sampler-seed", str(sseed),
           "--sim-engine", SIM, "--fms-root", FMS, "--out", d]
    if prune:
        cmd.append("--prune")          # 가망 없는 θ 를 시드 1개에서 끊는다 (약 −33 %)
    # --map-dir 을 안 준다 = 공식 맵. --aisle-block 기본 1 = 운영 조건.
    env = dict(os.environ, SIM_NO_PLOT="1", PYTHONIOENCODING="utf-8",
               OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    env.pop("OPTUNA_STORAGE", None)
    t0 = time.time()
    with open(os.path.join(d, "run.log"), "w", encoding="utf-8") as f:
        rc = subprocess.run(cmd, cwd=WORKER, env=env, stdout=f,
                            stderr=subprocess.STDOUT).returncode
    ok = rc == 0 and os.path.exists(theta)
    return fleet, frac, sseed, time.time() - t0, ("OK" if ok else "실패 rc=%d" % rc)


def main():
    p = argparse.ArgumentParser(description="공식 맵 · 대수 × 상대부하 → θ")
    p.add_argument("--jobs", type=int, default=64)
    p.add_argument("--trials", type=int, default=150)
    p.add_argument("--orders", type=int, default=250)
    p.add_argument("--out", default=os.path.join(OUT, "theta_load"))
    p.add_argument("--cap-only", action="store_true", help="용량만 재고 끝 (1분)")
    p.add_argument("--no-prune", action="store_true",
                   help="가지치기를 끈다 (기본은 켬 — run_study --prune)")
    a = p.parse_args()
    os.makedirs(a.out, exist_ok=True)

    neutral_path = os.path.join(a.out, "_neutral.json")
    with open(neutral_path, "w", encoding="utf-8") as f:
        json.dump(NEUTRAL, f)

    cap_file = os.path.join(a.out, "capacity.json")
    if os.path.exists(cap_file):
        cap = {int(k): v for k, v in json.load(open(cap_file, encoding="utf-8")).items()}
        print("용량 (저장된 값 사용)")
    else:
        print("① 용량 측정 — 대수별로 과포화시켜 achieved 주문/h 를 읽는다")
        with ThreadPoolExecutor(max_workers=len(FLEETS)) as pool:
            vals = list(pool.map(lambda f: measure_capacity(f, a.orders, neutral_path), FLEETS))
        cap = {f: v for f, v in zip(FLEETS, vals) if v}
        if len(cap) != len(FLEETS):
            raise SystemExit("용량 측정 실패: %s" % [f for f in FLEETS if f not in cap])
        json.dump({str(k): v for k, v in cap.items()},
                  open(cap_file, "w", encoding="utf-8"), indent=1)

    print("  %6s%12s" % ("대수", "용량 주문/h")
          + "".join("%14s" % ("%d%% (건/h·주문)" % (x * 100)) for x in LOADS))
    print("  " + "-" * (18 + 14 * len(LOADS)))
    sim_h = 0.0
    for f in FLEETS:
        row = "  %6d%12.0f" % (f, cap[f])
        for x in LOADS:
            rate = cap[f] * x
            n = orders_for(rate, a.orders)
            sim_h += n / rate
            row += "%14s" % ("%.0f · %d건" % (rate, n))
        print(row)
    print("  런 하나가 도는 시뮬 시간 합계 %.1f h (칸당 평균 %.2f h)"
          % (sim_h, sim_h / (len(FLEETS) * len(LOADS))))
    os.unlink(neutral_path)
    if a.cap_only:
        return 0

    jobs = [(f, L, s) for f in FLEETS for L in LOADS for s in SAMPLER_SEEDS]
    print("\n② 격자 — 대수 %d × 부하 %d × 반복 %d = %d study · 동시 %d · trial %d"
          % (len(FLEETS), len(LOADS), len(SAMPLER_SEEDS), len(jobs), a.jobs, a.trials))

    t0, nok = time.time(), 0
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        for fleet, frac, sseed, el, msg in pool.map(
                lambda j: study(j, a.trials, a.orders, a.out, cap, not a.no_prune), jobs):
            nok += msg in ("OK", "건너뜀")
            print("  %2d대 부하%3d%% s%d  %6.1f분  %-10s  (완료 %d/%d · 경과 %.0f분)"
                  % (fleet, round(frac * 100), sseed, el / 60, msg, nok, len(jobs),
                     (time.time() - t0) / 60), flush=True)

    cell, best = {}, {}
    for f, L in itertools.product(FLEETS, LOADS):
        for s in SAMPLER_SEEDS:
            _, th, meta = paths(a.out, f, L, s)
            if os.path.exists(th):
                cell.setdefault((f, L), []).append(json.load(open(th, encoding="utf-8")))
            if os.path.exists(meta):
                best.setdefault((f, L), []).append(
                    json.load(open(meta, encoding="utf-8"))["objective"]["value"])

    full = {k: v for k, v in cell.items() if len(v) >= 3}
    print("\n=== 반복 3회 성공한 지점 %d / %d ===" % (len(full), len(FLEETS) * len(LOADS)))
    if len(full) < 6:
        print("  판정 불가 — 성공한 지점이 너무 적다")
        return 1

    print("\n=== θ 가 지점마다 다른가 ===")
    print("  %-20s%14s%14s%9s" % ("축", "지점내(반복)", "지점간", "비율"))
    print("  " + "-" * 58)
    ratios = []
    for ax in AXES:
        within = st.fmean([st.stdev([t[ax] for t in ts]) for ts in full.values()])
        between = st.stdev([st.fmean([t[ax] for t in ts]) for ts in full.values()])
        if between == 0:
            continue
        ratios.append(within / between)
        print("  %-20s%14.3f%14.3f%9.2f" % (ax, within, between, within / between))
    r = st.fmean(ratios)
    print("\n  평균 비율 %.2f  (반복 산포 ÷ 지점 평균의 산포)" % r)
    if r <= 0.7:
        print("  -> 지점 간 차이가 반복 노이즈보다 크다. **대수·물량이 θ 를 움직인다.**")
        print("     아래 표를 견적에 붙일 수 있다.")
    elif r >= 1.3:
        print("  -> 지점을 바꿔도 같은 지점을 다시 탐색한 것과 다를 바 없다. **묻힌다.**")
        print("     고정 θ 하나로 충분하다 — 이번엔 θ 가 일하는 구간까지 보고 내린 결론이다.")
    else:
        print("  -> 경계다. 신호와 노이즈가 비슷하다.")

    print("\n=== 최적 처리량 (반복 평균, tasks/h) ===")
    print("  %6s" % "대수" + "".join("%12s" % ("부하%d%%" % (x * 100)) for x in LOADS))
    print("  " + "-" * (6 + 12 * len(LOADS)))
    for f in FLEETS:
        print("  %6d" % f + "".join(
            "%12s" % ("%.1f" % st.fmean(best[(f, L)]) if best.get((f, L)) else "-") for L in LOADS))

    print("\n=== θ 표 (지점별 반복 평균) ===")
    print("  %6s%8s" % ("대수", "부하") + "".join("%10s" % x[:9] for x in AXES))
    print("  " + "-" * (14 + 10 * len(AXES)))
    for f in FLEETS:
        for L in LOADS:
            ts = full.get((f, L))
            if ts:
                print("  %6d%7d%%" % (f, round(L * 100))
                      + "".join("%10.3f" % st.fmean([t[ax] for t in ts]) for ax in AXES))

    csv_path = os.path.join(OUT, "theta_load_grid_v36.csv")
    with open(csv_path, "w", encoding="utf-8", newline="") as fh:
        fh.write("fleet,load_frac,rate_per_h,n," + ",".join(AXES) + ",best_mean,best_spread\n")
        for f in FLEETS:
            for L in LOADS:
                ts, bv = cell.get((f, L)), best.get((f, L))
                if not ts:
                    continue
                fh.write("%d,%.2f,%.1f,%d," % (f, L, cap[f] * L, len(ts))
                         + ",".join("%.4f" % st.fmean([t[ax] for t in ts]) for ax in AXES)
                         + ",%.1f,%.1f\n" % (st.fmean(bv), max(bv) - min(bv)))
    print("\n  CSV %s" % csv_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
