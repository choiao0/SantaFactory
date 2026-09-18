# -*- coding: utf-8 -*-
"""대수 x 물량이 θ 를 움직이는가 (S15P21A106-206).

**공식 맵 하나**에서 대수 5종 x 부하 4종 = 20지점, 각 지점을 샘플러 시드 3개로
반복해 60 study. 맵이 하나로 고정된 이상 실제로 쓸모 있는 축은 이쪽이다 —
견적이 물량을 받아 대수를 내는데, 거기에 θ 까지 같이 내면 바로 붙는다.

**반복이 필수다.** 앞선 재현성 측정에서 θ 변동의 63 % 가 탐색 노이즈로 나왔다
(같은 창고를 다시 탐색해도 그만큼 달라진다). 지점마다 한 번만 뽑으면 지점 간
차이가 신호인지 노이즈인지 또 못 가른다. 3회 반복의 산포가 곧 노이즈 자다.

격자는 이미 아는 운영점을 품는다: 20대 900건/h 는 v3.6 θ 를 뽑은 조건이고,
18대 / 24대는 -194 대수표의 6,000건 / 9,000건 권장값이다.

읽는 법:
  지점간 산포 >> 반복 산포  ->  대수·물량이 θ 를 정한다. 표를 쓴다
  지점간 산포 ~= 반복 산포  ->  묻힌다. 고정 θ 하나로 충분하다
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

SPEED, CAPACITY, SEEDS = 0.838, 6, "42,43,44"
FLEETS = (14, 18, 20, 24, 28)          # 28 = 공식 맵 충전 존 상한 (계약 1절)
RATES = (600, 900, 1200, 1500)         # 주문/h. 900 = v3.6 θ 조건, 1500 = 9,000건/6h
SAMPLER_SEEDS = (1, 2, 3)
AXES = ["loop_gain", "main_aisle_gain", "junction_penalty",
        "station_in", "station_out", "wait_cost"]


def tag(fleet, rate, sseed):
    return "r%d_q%d_s%d" % (fleet, rate, sseed)


def paths(out_dir, fleet, rate, sseed):
    t = tag(fleet, rate, sseed)
    d = os.path.join(out_dir, t)
    return d, os.path.join(d, "theta_grid_%s.json" % t), os.path.join(d, "meta_grid_%s.json" % t)


def study(job, trials, orders, out_dir):
    fleet, rate, sseed = job
    d, theta, _ = paths(out_dir, fleet, rate, sseed)
    if os.path.exists(theta):
        return fleet, rate, sseed, 0.0, "건너뜀"
    os.makedirs(d, exist_ok=True)
    cmd = [sys.executable, "run_study.py",
           "--study", "grid_" + tag(fleet, rate, sseed),
           "--robots", str(fleet), "--orders", str(orders), "--trials", str(trials),
           "--seeds", SEEDS, "--capacity", str(CAPACITY), "--speed", "%g" % SPEED,
           "--arrival-s", "%.4f" % (3600.0 / rate),
           "--sampler-seed", str(sseed),
           "--sim-engine", SIM, "--fms-root", FMS, "--out", d]
    # --map-dir 을 안 준다 = 공식 맵. 인자가 하나도 안 붙어 기존 실행과 글자 단위로 같다.
    env = dict(os.environ, SIM_NO_PLOT="1", PYTHONIOENCODING="utf-8",
               OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    env.pop("OPTUNA_STORAGE", None)
    t0 = time.time()
    with open(os.path.join(d, "run.log"), "w", encoding="utf-8") as f:
        rc = subprocess.run(cmd, cwd=WORKER, env=env, stdout=f,
                            stderr=subprocess.STDOUT).returncode
    ok = rc == 0 and os.path.exists(theta)
    return fleet, rate, sseed, time.time() - t0, ("OK" if ok else "실패 rc=%d" % rc)


def main():
    p = argparse.ArgumentParser(description="대수 x 물량 → θ")
    p.add_argument("--jobs", type=int, default=60)
    p.add_argument("--trials", type=int, default=150)
    p.add_argument("--orders", type=int, default=250)
    p.add_argument("--out", default=os.path.join(OUT, "theta_grid"))
    a = p.parse_args()

    jobs = [(f, q, s) for f in FLEETS for q in RATES for s in SAMPLER_SEEDS]
    os.makedirs(a.out, exist_ok=True)
    print("대수 %s x 부하 %s x 반복 %d = %d study · 동시 %d · trial %d"
          % (list(FLEETS), list(RATES), len(SAMPLER_SEEDS), len(jobs), a.jobs, a.trials))

    t0, nok = time.time(), 0
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        for fleet, rate, sseed, el, msg in pool.map(
                lambda j: study(j, a.trials, a.orders, a.out), jobs):
            nok += msg in ("OK", "건너뜀")
            print("  %2d대 %4d건/h s%d  %6.1f분  %-10s  (완료 %d/%d · 경과 %.0f분)"
                  % (fleet, rate, sseed, el / 60, msg, nok, len(jobs),
                     (time.time() - t0) / 60), flush=True)

    cell, best = {}, {}
    for f, q in itertools.product(FLEETS, RATES):
        for s in SAMPLER_SEEDS:
            _, th, meta = paths(a.out, f, q, s)
            if os.path.exists(th):
                cell.setdefault((f, q), []).append(json.load(open(th, encoding="utf-8")))
            if os.path.exists(meta):
                m = json.load(open(meta, encoding="utf-8"))
                best.setdefault((f, q), []).append(m["objective"]["value"])

    full = {k: v for k, v in cell.items() if len(v) >= 3}
    print("\n=== 반복 3회 성공한 지점 %d / %d ===" % (len(full), len(FLEETS) * len(RATES)))
    if len(full) < 4:
        print("  판정 불가 — 성공한 지점이 너무 적다")
        return 1

    print("\n=== θ 가 지점마다 다른가 ===")
    print("  %-20s%14s%14s%9s" % ("축", "지점내(반복)", "지점간", "비율"))
    print("  " + "-" * 58)
    ratios = []
    for ax in AXES:
        within = st.fmean([st.stdev([t[ax] for t in ts]) for ts in full.values()])
        means = [st.fmean([t[ax] for t in ts]) for ts in full.values()]
        between = st.stdev(means)
        if between == 0:
            continue
        ratios.append(within / between)
        # 지점이 설명하는 분산 = 1 - (지점내/지점간)^2 ... 단 지점간은 평균의 산포라
        # 이미 노이즈가 1/3 로 줄어 있다. 보정해서 원 단일표본 기준으로 환산한다.
        print("  %-20s%14.3f%14.3f%9.2f" % (ax, within, between, within / between))

    r = st.fmean(ratios)
    print("\n  평균 비율 %.2f  (반복 산포 ÷ 지점 평균의 산포)" % r)
    if r <= 0.7:
        print("  -> 지점 간 차이가 반복 노이즈보다 크다.")
        print("     **대수·물량이 θ 를 움직인다** — 아래 표를 쓸 수 있다.")
    elif r >= 1.3:
        print("  -> 지점을 바꿔도 같은 창고를 다시 탐색한 것과 다를 바 없다.")
        print("     **묻힌다** — 고정 θ 하나로 충분하다.")
    else:
        print("  -> 경계다. 신호와 노이즈가 비슷하다.")

    print("\n=== 처리량 (반복 3회 평균) — 대수표와 겹쳐 읽는다 ===")
    print("  %6s" % "대수" + "".join("%12s" % ("%d건/h" % q) for q in RATES))
    print("  " + "-" * (6 + 12 * len(RATES)))
    for f in FLEETS:
        row = "  %6d" % f
        for q in RATES:
            v = best.get((f, q))
            row += "%12s" % ("%.1f" % st.fmean(v) if v else "-")
        print(row)

    print("\n=== θ 표 (지점별 반복 평균) ===")
    print("  %6s%8s" % ("대수", "건/h") + "".join("%10s" % a[:9] for a in AXES))
    print("  " + "-" * (14 + 10 * len(AXES)))
    for f in FLEETS:
        for q in RATES:
            ts = full.get((f, q))
            if not ts:
                continue
            print("  %6d%8d" % (f, q)
                  + "".join("%10.3f" % st.fmean([t[ax] for t in ts]) for ax in AXES))

    out_csv = os.path.join(OUT, "theta_grid_v36.csv")
    with open(out_csv, "w", encoding="utf-8", newline="") as fh:
        fh.write("fleet,rate,n," + ",".join(AXES) + ",best_mean,best_spread\n")
        for f in FLEETS:
            for q in RATES:
                ts, bv = cell.get((f, q)), best.get((f, q))
                if not ts:
                    continue
                fh.write("%d,%d,%d," % (f, q, len(ts))
                         + ",".join("%.4f" % st.fmean([t[ax] for t in ts]) for ax in AXES)
                         + ",%.1f,%.1f\n" % (st.fmean(bv), max(bv) - min(bv)))
    print("\n  CSV %s" % out_csv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
