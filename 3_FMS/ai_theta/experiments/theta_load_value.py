# -*- coding: utf-8 -*-
"""지점별 θ 가 고정 θ 보다 실제로 나은가 (S15P21A106-206).

`theta_load_grid.py` 가 공식 맵에서 대수 6종 x 상대부하 3종 x 반복 3 = 54 study 를 돌려
**θ 값이 지점마다 달라진다**는 것까지 보였다(`loop_gain` 신호/노이즈 2.3배). 남은 질문은
하나다 — **그 차이가 처리량을 올리는가.**

값이 달라지는 것과 결과가 나아지는 것은 다르다. 재현성 측정에서 서로 3.4배 다른 θ 들이
처리량 1.8 % 안에서 같은 값을 냈다(평탄한 골짜기). 그러니 θ 벡터가 아니라 **처리량으로**
재야 한다.

각 지점에서 두 θ 를 같은 조건(대수·상대부하·평가 시드)으로 맞붙인다:

    지점별 θ = 그 지점의 반복 3회 평균 (탐색 노이즈가 sqrt(3) 로 줄어 있다)
    고정 θ   = 지금 운영·견적이 쓰는 theta_wallA_r20_c6_v36.json

판정은 -138 규칙 — 시드별 짝차이의 부호가 모두 같고 |평균| > 산포여야 실효다. 평균만
비교하면 시드 운을 실효로 읽는다(처리량 시드 산포가 θ 효과보다 크다).

평가 시드 {101,103,104} 는 탐색 시드 {42,43,44} 와 분리돼 있다. 같은 시드로 재면 그 θ 가
외운 답을 채점하는 것이다 (계약 §5).
"""
import argparse
import itertools
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
SEEDS = [101, 103, 104]                # 평가 시드 (계약 §5)
FIXED = os.path.join(OUT, "theta_wallA_r20_c6_v36.json")
GRID = os.path.join(OUT, "theta_load")
FLEETS = (8, 12, 16, 20, 24, 28)
LOADS = (0.50, 0.75, 1.00)
AXES = ["loop_gain", "main_aisle_gain", "junction_penalty",
        "station_in", "station_out", "wait_cost"]
CATS = ["aisle_period", "aisle_phase", "loop_dir"]
TAG = re.compile(r"theta_load_r(\d+)_L(\d+)_s(\d+)\.json$")


def orders_for(rate, orders_max=250, hours=1.0, floor=100):
    """theta_load_grid.py 와 **같은 식**이어야 한다 — 주문 수가 다르면 다른 조건이다."""
    return max(floor, min(orders_max, round(rate * hours)))


def point_theta(out_dir):
    """지점별 θ = 그 지점 반복 3회의 평균. 범주형은 최빈값(평균이 뜻이 없다)."""
    got = {}
    for p in sorted(os.listdir(GRID)) if os.path.isdir(GRID) else []:
        d = os.path.join(GRID, p)
        if not os.path.isdir(d):
            continue
        for f in os.listdir(d):
            m = TAG.match(f)
            if m:
                got.setdefault((int(m.group(1)), int(m.group(2))), []).append(
                    json.load(open(os.path.join(d, f), encoding="utf-8")))
    out = {}
    for (fleet, pct), ts in got.items():
        if len(ts) < 2:
            continue
        th = {a: st.fmean(t[a] for t in ts) for a in AXES}
        th.update({c: st.mode([t[c] for t in ts]) for c in CATS})
        for a in ("aisle_alt_gain", "aisle_alt_boost"):
            th[a] = st.fmean(t[a] for t in ts)
        path = os.path.join(out_dir, "theta_point_r%d_L%d.json" % (fleet, pct))
        with open(path, "w", encoding="utf-8") as f:
            json.dump(th, f, ensure_ascii=False, indent=1)
        out[(fleet, pct)] = (path, len(ts), th)
    return out


def sim(fleet, rate, theta, seed, timeout=1800):
    orders = orders_for(rate)
    cmd = [sys.executable, "sim_v2_tasks.py", "vf", str(fleet), str(orders), str(seed), "1",
           "--order-gap=%.4f" % ((3600.0 / rate) / DT), "--capacity=%d" % CAPACITY,
           "--speed=%g" % SPEED, "--theta=" + theta]      # --map-dir 없음 = 공식 맵
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
    p = argparse.ArgumentParser(description="지점별 θ vs 고정 θ (공식 맵)")
    p.add_argument("--jobs", type=int, default=32)
    p.add_argument("--out", default=OUT)
    a = p.parse_args()

    cap_file = os.path.join(GRID, "capacity.json")
    if not os.path.exists(cap_file):
        raise SystemExit("capacity.json 이 없다 — theta_load_grid.py 를 먼저 돌릴 것")
    cap = {int(k): v for k, v in json.load(open(cap_file, encoding="utf-8")).items()}

    pt = point_theta(a.out)
    if not pt:
        raise SystemExit("theta_load 결과가 없다 — theta_load_grid.py 를 먼저 돌릴 것")
    print("지점 %d개 (각 반복 %d회 평균)" % (len(pt), max(n for _, n, _ in pt.values())))

    jobs = []
    for fleet, frac in itertools.product(FLEETS, LOADS):
        key = (fleet, round(frac * 100))
        if key not in pt:
            continue
        rate = cap[fleet] * frac
        for lab, th in (("point", pt[key][0]), ("fixed", FIXED)):
            jobs += [(fleet, frac, rate, lab, th, s) for s in SEEDS]
    print("런 %d개 · 동시 %d · 평가 시드 %s" % (len(jobs), a.jobs, SEEDS))

    t0, res = time.time(), {}
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        for j, v in zip(jobs, pool.map(lambda x: sim(x[0], x[2], x[4], x[5]), jobs)):
            res[(j[0], j[1], j[3], j[5])] = v
    print("  %.0f초" % (time.time() - t0))

    print("\n=== 지점별 θ vs 고정 θ (공식 맵 · 운영 조건) ===")
    print("  %6s%8s%12s%12s%10s%9s%8s" % ("대수", "부하", "지점별", "고정", "차이", "차이%", "판정"))
    print("  " + "-" * 66)
    rows = []
    for fleet, frac in itertools.product(FLEETS, LOADS):
        av = [res.get((fleet, frac, "point", s)) for s in SEEDS]
        bv = [res.get((fleet, frac, "fixed", s)) for s in SEEDS]
        if any(v is None for v in av + bv):
            print("  %6d%7d%%  실패" % (fleet, round(frac * 100)))
            continue
        d = [x - y for x, y in zip(av, bv)]
        mean, spread = st.fmean(d), max(d) - min(d)
        same = all(v > 0 for v in d) or all(v < 0 for v in d)
        ok = same and abs(mean) > spread
        verdict = ("지점별" if mean > 0 else "고정") if ok else "묻힘"
        pct = 100 * mean / st.fmean(bv)
        rows.append({"fleet": fleet, "load": frac, "point": st.fmean(av),
                     "fixed": st.fmean(bv), "diff_pct": pct, "spread": spread,
                     "verdict": verdict})
        print("  %6d%7d%%%12.1f%12.1f%10.1f%8.2f%%%8s"
              % (fleet, round(frac * 100), st.fmean(av), st.fmean(bv), mean, pct, verdict))

    if not rows:
        return 1
    m = st.fmean(r["diff_pct"] for r in rows)
    win = sum(1 for r in rows if r["diff_pct"] > 0)
    print("\n  전체 평균 %+.2f%% · 양수 %d/%d" % (m, win, len(rows)))
    for v in ("지점별", "고정", "묻힘"):
        g = [r for r in rows if r["verdict"] == v]
        if g:
            print("  %-6s %2d개  평균 %+.2f%%" % (v, len(g), st.fmean(r["diff_pct"] for r in g)))

    # 부호검정: 개별 지점이 묻혀도 방향이 일관되면 전체로는 실효다 (창고 판정에서 p=1.2e-08 이 그랬다)
    from math import comb
    n = len(rows)
    pval = sum(comb(n, k) for k in range(max(win, n - win), n + 1)) / 2 ** n * 2
    print("  부호검정 p = %.2e" % min(pval, 1.0))

    print()
    if m >= 2.0:
        print("  -> **지점별 θ 를 쓸 값이 있다.** 표를 견적에 붙인다.")
    elif abs(m) < 0.5:
        print("  -> **고정 θ 하나로 충분하다.** θ 값은 달라도 결과가 같다 (평탄한 골짜기).")
    else:
        print("  -> 이득이 작다. 부호검정 p 와 복잡도를 같이 보고 판단할 것.")

    csv_path = os.path.join(OUT, "theta_load_value_v36.csv")
    with open(csv_path, "w", encoding="utf-8", newline="") as fh:
        fh.write("fleet,load_frac,point_tasks_h,fixed_tasks_h,diff_pct,spread,verdict\n")
        for r in rows:
            fh.write("%d,%.2f,%.1f,%.1f,%.3f,%.1f,%s\n"
                     % (r["fleet"], r["load"], r["point"], r["fixed"],
                        r["diff_pct"], r["spread"], r["verdict"]))
    print("  CSV %s" % csv_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
