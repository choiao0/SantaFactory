# -*- coding: utf-8 -*-
"""대수별 θ 가 고정 θ 보다 실제로 나은가 (S15P21A106-206).

θ **값**이 대수에 따라 달라 보이는 것과, 그 θ 를 써서 **처리량이 오르는** 것은
다른 문제다. 목적함수가 평탄해 서로 다른 θ 가 1.8 % 안에서 같은 결과를 내는 것을
이미 봤으므로(재현성 측정), 값의 차이가 아니라 결과의 차이를 재야 한다.

theta_grid 가 대수 5종 x 물량 4종 x 반복 3 = 60개를 뽑아 뒀다. 물량 축은 신호가
없었고(전 구간 포화) 대수 축만 약한 상관이 남았으므로, **그 대수의 12개를 평균해**
'그 대수의 θ' 를 만들고 고정 θ 와 맞붙인다. 12개 평균이면 탐색 노이즈가 sqrt(12)
로 줄어 지점 하나를 쓰는 것보다 훨씬 단단하다.

판정은 -138 규칙: 시드별 짝차이의 부호가 모두 같고 |평균| > 산포여야 실효.
평가 시드 {101,103,104} — 탐색 시드 {42,43,44} 와 겹치면 외운 답을 채점하게 된다.
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
OUT = os.path.join(FMS, "infra", "out")
sys.path.insert(0, SIM)
from map_loader import CELL_M          # noqa: E402
from pibt_core import MOVE_TICKS       # noqa: E402

SPEED, CAPACITY = 0.838, 6
DT = CELL_M / (SPEED * MOVE_TICKS)
SEEDS = [101, 103, 104]
RATE = 900                              # 고정 θ 를 뽑은 부하 (-194: arrival-s 4 = 900건/h)
FIXED = os.path.join(OUT, "theta_wallA_r20_c6_v36.json")
GRID = os.path.join(OUT, "theta_grid")
FLEETS = (14, 18, 20, 24, 28)
TAG = re.compile(r"theta_grid_r(\d+)_q(\d+)_s(\d+)\.json$")
AXES = ["loop_gain", "main_aisle_gain", "junction_penalty",
        "station_in", "station_out", "wait_cost"]
CATS = ["aisle_period", "aisle_phase", "loop_dir"]


def fleet_theta(out_dir):
    """대수별 θ = 그 대수에서 뽑은 12개(물량 4 x 반복 3)의 평균.

    범주형은 평균이 뜻이 없으니 최빈값으로 간다. aisle_* 는 aisle_block=1 에서
    비트 단위로 무효라 어차피 중립 고정이다 (계약 5절)."""
    got = {}
    for p in glob.glob(os.path.join(GRID, "*", "theta_grid_*.json")):
        m = TAG.search(os.path.basename(p))
        if m:
            got.setdefault(int(m.group(1)), []).append(
                json.load(open(p, encoding="utf-8")))
    out = {}
    for f, ts in got.items():
        th = {a: st.fmean(t[a] for t in ts) for a in AXES}
        th.update({c: st.mode([t[c] for t in ts]) for c in CATS})
        for a in ("aisle_alt_gain", "aisle_alt_boost"):
            th[a] = st.fmean(t[a] for t in ts)
        path = os.path.join(out_dir, "theta_fleet_r%d.json" % f)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(th, fh, ensure_ascii=False, indent=1)
        out[f] = (path, len(ts), th)
    return out


def sim(fleet, theta, seed, orders, timeout=1800):
    gap = (3600.0 / RATE) / DT
    cmd = [sys.executable, "sim_v2_tasks.py", "vf", str(fleet), str(orders),
           str(seed), "1", "--order-gap=%.4f" % gap, "--capacity=%d" % CAPACITY,
           "--speed=%g" % SPEED, "--theta=" + theta]          # --map-dir 없음 = 공식 맵
    env = dict(os.environ, SIM_NO_PLOT="1", PYTHONIOENCODING="utf-8",
               OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    try:
        p = subprocess.run(cmd, cwd=SIM, env=env, capture_output=True, text=True,
                           encoding="utf-8", timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    for line in (p.stdout or "").splitlines():
        if line.startswith("[SUMMARY] "):
            return json.loads(line[10:])["tasks_per_h"]
    return None


def main():
    p = argparse.ArgumentParser(description="대수별 θ 의 값어치")
    p.add_argument("--jobs", type=int, default=30)
    p.add_argument("--orders", type=int, default=250)
    p.add_argument("--out", default=OUT)
    a = p.parse_args()

    fth = fleet_theta(a.out)
    if not fth:
        print("theta_grid 결과가 없다 — theta_grid.py 를 먼저 돌릴 것")
        return 1
    print("대수별 θ (그 대수의 %d개 평균)" % max(n for _, n, _ in fth.values()))
    print("  %6s%6s" % ("대수", "n") + "".join("%11s" % x[:10] for x in AXES))
    print("  " + "-" * (12 + 11 * len(AXES)))
    for f in FLEETS:
        if f in fth:
            _, n, th = fth[f]
            print("  %6d%6d" % (f, n) + "".join("%11.3f" % th[x] for x in AXES))
    fx = json.load(open(FIXED, encoding="utf-8"))
    print("  %6s%6s" % ("고정", "-") + "".join("%11.3f" % fx[x] for x in AXES))

    jobs = [(f, lab, th, s) for f in FLEETS if f in fth
            for lab, th in (("own", fth[f][0]), ("fixed", FIXED))
            for s in SEEDS]
    print("\n런 %d개 · 동시 %d · 부하 %d건/h · 평가 시드 %s"
          % (len(jobs), a.jobs, RATE, SEEDS))

    t0, res = time.time(), {}
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        for (f, lab, _, s), v in zip(jobs, pool.map(
                lambda j: sim(j[0], j[2], j[3], a.orders), jobs)):
            res[(f, lab, s)] = v
    print("  %.0f초" % (time.time() - t0))

    print("\n=== 대수별 θ vs 고정 θ (공식 맵) ===")
    print("  %6s%12s%12s%10s%10s%8s" % ("대수", "대수별", "고정", "차이", "차이%", "판정"))
    print("  " + "-" * 60)
    diffs = []
    for f in FLEETS:
        av = [res.get((f, "own", s)) for s in SEEDS]
        bv = [res.get((f, "fixed", s)) for s in SEEDS]
        if any(v is None for v in av + bv):
            print("  %6d  실패" % f)
            continue
        d = [x - y for x, y in zip(av, bv)]
        mean, spread = st.fmean(d), max(d) - min(d)
        same = all(v > 0 for v in d) or all(v < 0 for v in d)
        ok = same and abs(mean) > spread
        verdict = ("대수별" if mean > 0 else "고정") if ok else "묻힘"
        pct = 100 * mean / st.fmean(bv)
        diffs.append(pct)
        print("  %6d%12.1f%12.1f%10.1f%9.2f%%%8s"
              % (f, st.fmean(av), st.fmean(bv), mean, pct, verdict))

    if diffs:
        m = st.fmean(diffs)
        print("\n  전체 평균 %+.2f%%  (양수 = 대수별 θ 가 이득)" % m)
        if abs(m) < 0.5:
            print("  -> **고정 θ 하나로 충분하다.** 대수별로 나눠 봐야 얻는 것이 없다.")
        elif m >= 2.0:
            print("  -> 대수별 θ 를 쓸 값이 있다. 대수 축 추세선을 얹는다.")
        else:
            print("  -> 이득이 작다. 복잡도를 늘릴 만한지는 판단이 필요하다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
