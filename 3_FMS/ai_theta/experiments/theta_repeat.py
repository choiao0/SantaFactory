# -*- coding: utf-8 -*-
"""같은 창고를 여러 번 탐색해 θ 재현성을 잰다 (S15P21A106-206).

**왜 재나.** 창고 85개에서 θ 를 하나씩 뽑아 놓고 "창고마다 θ 가 다른데 기하로
설명이 안 된다" 고 말하려면, 먼저 **같은 창고를 다시 탐색했을 때 같은 θ 가
나오는지** 를 알아야 한다. 안 나오면 그 '창고마다 다름' 은 창고가 만든 게 아니다.

창고 10개 x 샘플러 시드 5개 = 50 study. 맵 · 대수 · 부하 · 평가 시드 전부 같고
**--sampler-seed 만 다르다**. run_study 는 이 값을 TPESampler 에 넘긴다 — 같은 값을
주면 워커마다 같은 후보를 내므로 병렬 탐색에서는 비우는 인자인데, 여기서는
반대로 **재현성을 재는 손잡이**로 쓴다.

study 하나가 단일 스레드라 더 못 쪼갠다. 그래서 코어를 채우는 길은 study 수를
늘리는 것이다 — 3회 반복으로 낸 표준편차는 그 자체가 크게 흔들려서 5회로 잡는다.

**처리량도 같이 본다.** θ 가 반복마다 딴판인데 최적 처리량은 비슷하다면, 목적함수가
평탄한 골짜기(능선)라는 직접 증거다 — 어느 θ 를 집어도 결과가 같다는 뜻이니
'그 창고의 최적 θ' 라는 것이 애초에 하나로 정해지지 않는다.

읽는 법:
  창고내 산포 ~= 창고간 산포  ->  θ 가 유일하게 결정되지 않는다
  창고내 산포 <<  창고간 산포  ->  창고별 θ 는 실재하나 기하로 못 잡는다
"""
import argparse
import glob
import json
import os
import re
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
SYNTH = os.path.join(FMS, "map", "synth")
WORKER = os.path.join(FMS, "infra", "worker")
OUT = os.path.join(FMS, "infra", "out")

REF_ROBOTS, REF_ARRIVAL_S = 20, 4.0     # -194 기준 조건 (20대 900건/h)
SPEED, CAPACITY, SEEDS = 0.838, 6, "42,43,44"
AXES = ["loop_gain", "main_aisle_gain", "junction_penalty",
        "station_in", "station_out", "wait_cost"]
# 기하 공간에 고루 퍼지게 골랐다 — 한쪽 구석만 보면 재현성이 그 구석 성질일 수 있다.
# 전부 권장 대수 12~24(θ 판정 가능) · 충전 존 충분 · 이미 θ 가 있는 창고다.
PICK = ["r6p6l21", "r6p7l25", "r8p6l21", "r8p7l25", "r9p6l21",
        "r9p7l25", "r11p6l17", "r11p7l21", "r13p5l29", "r13p6l25"]
SAMPLER_SEEDS = [1, 2, 3, 4, 5]
ROW = re.compile(r"^\|\s*.(r(\d+)p(\d+)l(\d+)).\s*\|")
OWN = re.compile(r"theta_synth_(r\d+p\d+l\d+)_r(\d+)_c6_v36\.json$")


def fleets():
    got = {}
    with open(os.path.join(SYNTH, "README.md"), encoding="utf-8") as f:
        for line in f:
            m = ROW.match(line)
            if m:
                col = [c.strip() for c in line.strip().strip("|").split("|")]
                got[m.group(1)] = int(col[6])
    return got


def paths(out_dir, name, sseed):
    tag = "%s_s%d" % (name, sseed)
    d = os.path.join(out_dir, tag)
    return d, os.path.join(d, "theta_rep_%s.json" % tag), os.path.join(d, "meta_rep_%s.json" % tag)


def study(job, trials, orders, out_dir):
    name, fleet, sseed = job
    d, theta, _ = paths(out_dir, name, sseed)
    if os.path.exists(theta):
        return name, sseed, 0.0, "건너뜀"
    os.makedirs(d, exist_ok=True)
    cmd = [sys.executable, "run_study.py",
           "--study", "rep_%s_s%d" % (name, sseed),
           "--map-dir", os.path.join(SYNTH, name),
           "--robots", str(fleet), "--orders", str(orders), "--trials", str(trials),
           "--seeds", SEEDS, "--capacity", str(CAPACITY), "--speed", "%g" % SPEED,
           "--arrival-s", "%.4f" % (REF_ARRIVAL_S * REF_ROBOTS / fleet),
           "--sampler-seed", str(sseed),          # 여기만 다르다
           "--sim-engine", SIM, "--fms-root", FMS, "--out", d]
    env = dict(os.environ, SIM_NO_PLOT="1", PYTHONIOENCODING="utf-8",
               OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    env.pop("OPTUNA_STORAGE", None)                # study 끼리 완전히 독립
    t = time.time()
    with open(os.path.join(d, "run.log"), "w", encoding="utf-8") as f:
        rc = subprocess.run(cmd, cwd=WORKER, env=env, stdout=f,
                            stderr=subprocess.STDOUT).returncode
    ok = rc == 0 and os.path.exists(theta)
    return name, sseed, time.time() - t, ("OK" if ok else "실패 rc=%d" % rc)


def across_warehouse_spread():
    """대조군: 창고 85개 **사이**의 θ 산포 (어젯밤 뽑아 둔 것)."""
    vals = {a: [] for a in AXES}
    for p in glob.glob(os.path.join(OUT, "synth_v36", "*", "theta_*.json")):
        if OWN.search(os.path.basename(p)):
            t = json.load(open(p, encoding="utf-8"))
            for a in AXES:
                vals[a].append(t[a])
    return {a: st.stdev(v) for a, v in vals.items() if len(v) > 1}


def main():
    p = argparse.ArgumentParser(description="θ 탐색 재현성")
    p.add_argument("--jobs", type=int, default=50)
    p.add_argument("--trials", type=int, default=150)
    p.add_argument("--orders", type=int, default=250)
    p.add_argument("--out", default=os.path.join(OUT, "theta_repeat"))
    a = p.parse_args()

    fl = fleets()
    jobs = [(n, fl[n], s) for n in PICK for s in SAMPLER_SEEDS]
    os.makedirs(a.out, exist_ok=True)
    print("창고 %d개 x 샘플러 시드 %d개 = %d study · 동시 %d · trial %d"
          % (len(PICK), len(SAMPLER_SEEDS), len(jobs), a.jobs, a.trials))
    print("  " + ", ".join("%s(%d대)" % (n, fl[n]) for n in PICK))

    t0, nok = time.time(), 0
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        for name, sseed, el, msg in pool.map(
                lambda j: study(j, a.trials, a.orders, a.out), jobs):
            nok += msg in ("OK", "건너뜀")
            print("  %-12s sampler=%d  %6.1f분  %-10s  (완료 %d · 경과 %.0f분)"
                  % (name, sseed, el / 60, msg, nok, (time.time() - t0) / 60), flush=True)

    got, best = {}, {}
    for n in PICK:
        for s in SAMPLER_SEEDS:
            _, th, meta = paths(a.out, n, s)
            if os.path.exists(th):
                got.setdefault(n, []).append(json.load(open(th, encoding="utf-8")))
            if os.path.exists(meta):
                m = json.load(open(meta, encoding="utf-8"))
                best.setdefault(n, []).append(m["objective"]["value"])

    usable = {n: ts for n, ts in got.items() if len(ts) >= 3}
    print("\n=== 반복 %d회 이상 성공한 창고 %d개로 판정 ===" % (3, len(usable)))
    if not usable:
        print("  판정 불가 — 성공한 study 가 너무 적다")
        return 1

    across = across_warehouse_spread()
    print("\n  %-20s%14s%14s%9s" % ("축", "창고내 산포", "창고간(85개)", "비율"))
    print("  " + "-" * 58)
    ratios = []
    for ax in AXES:
        within = [st.stdev([t[ax] for t in ts]) for ts in usable.values()]
        if not within or ax not in across:
            continue
        w, b = st.fmean(within), across[ax]
        ratios.append(w / b)
        print("  %-20s%14.3f%14.3f%9.2f" % (ax, w, b, w / b))

    ratio = st.fmean(ratios)
    print("\n  평균 비율 %.2f" % ratio)
    if ratio >= 0.7:
        print("  -> 같은 창고를 다시 탐색해도 창고끼리만큼 흔들린다.")
        print("     θ 가 **유일하게 결정되지 않는다** — '창고별 최적 θ' 가 잘 정의되지 않는다.")
    elif ratio <= 0.4:
        print("  -> 같은 창고는 비슷한 θ 로 수렴한다.")
        print("     창고별 θ 는 **실재**하고, 기하 3개로 못 잡는 것이 문제다.")
    else:
        print("  -> 중간이다. 탐색 잡음과 창고 신호가 비슷한 크기다.")

    print("\n=== θ 는 흔들리는데 처리량은? (평탄한 골짜기인가) ===")
    print("  %-12s%8s%14s%12s%10s" % ("창고", "반복", "최적 tasks/h", "산포", "산포%"))
    print("  " + "-" * 58)
    for n in PICK:
        v = best.get(n)
        if v and len(v) >= 3:
            m, sp = st.fmean(v), max(v) - min(v)
            print("  %-12s%8d%14.1f%12.1f%9.2f%%" % (n, len(v), m, sp, 100 * sp / m))
    allsp = [100 * (max(v) - min(v)) / st.fmean(v) for v in best.values() if len(v) >= 3]
    if allsp:
        print("\n  평균 산포 %.2f%% — 이게 작을수록 '어느 θ 를 집어도 결과가 같다'" % st.fmean(allsp))

    print("\n  같은 창고 반복별 θ (일부 축)")
    for n, ts in list(usable.items())[:4]:
        print("    %s" % n)
        for ax in ("loop_gain", "junction_penalty", "wait_cost"):
            print("      %-18s " % ax + "  ".join("%6.3f" % t[ax] for t in ts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
