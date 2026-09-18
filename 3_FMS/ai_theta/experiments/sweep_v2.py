# -*- coding: utf-8 -*-
"""합성 창고 θ 전수 측정 (S15P21A106-206).

창고 112개 x θ 3종(중립 · 고정 v3.6 · 그 창고에서 뽑은 것) x 평가 시드 3개.
한 번 돌려서 세 질문에 다 답한다.

  (1) 일반화   고정 θ 가 남의 창고에서도 중립보다 나은가
  (2) 예측     창고별 θ 가 고정 θ 를 이기는가 (이겨야 예측할 대상이 있다)
  (3) 설계     통로수 · 간격 · 길이가 처리량을 어떻게 바꾸는가

**스톨을 버리지 않는다.** 앞선 판(geometry_sweep)은 실패한 시드를 조용히 빼고
남은 것만 평균 냈다. 그래서 고정 θ 가 교착한 창고가 '승리' 로 집계됐다 —
생존 편향이다. 여기서는 완주 수(n)를 같이 남기고 **3시드를 다 완주한 창고만**
(1)(2) 비교에 쓴다. 완주 못 한 것은 그 자체가 결과다.

대수는 README 권장 대수(free / 81), 부하는 그 대수에 비례(-194 기준 20대 900건/h).
로봇당 초과수요를 같게 해야 창고마다 똑같이 포화하고, 그래야 처리량이 '수요' 가
아니라 '능력' 을 잰다.
"""
import argparse
import csv
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
OUT = os.path.join(FMS, "infra", "out")
sys.path.insert(0, SIM)
from map_loader import CELL_M          # noqa: E402
from pibt_core import MOVE_TICKS       # noqa: E402

REF_ROBOTS, REF_ARRIVAL_S = 20, 4.0
SPEED, CAPACITY = 0.838, 6
DT = CELL_M / (SPEED * MOVE_TICKS)
SEEDS = [101, 103, 104]                 # 평가 시드 (계약 5절) — 탐색 시드 {42,43,44} 와 분리
FIXED = os.path.join(OUT, "theta_wallA_r20_c6_v36.json")
NEUTRAL = {"aisle_alt_gain": 1.0, "aisle_alt_boost": 1.0, "loop_gain": 1.0,
           "main_aisle_gain": 1.0, "junction_penalty": 1.0, "station_in": 1.0,
           "station_out": 1.0, "wait_cost": 1.0,
           "aisle_period": 1, "aisle_phase": 0, "loop_dir": 0}
ROW = re.compile(r"^\|\s*.(r(\d+)p(\d+)l(\d+)).\s*\|")
OWN = re.compile(r"theta_synth_(r\d+p\d+l\d+)_r(\d+)_c6_v36\.json$")
LABELS = ("neutral", "fixed", "own")


def warehouses():
    out = []
    with open(os.path.join(SYNTH, "README.md"), encoding="utf-8") as f:
        for line in f:
            m = ROW.match(line)
            if m:
                col = [c.strip() for c in line.strip().strip("|").split("|")]
                out.append({"name": m.group(1), "aisles": int(m.group(2)),
                            "pitch": int(m.group(3)), "length": int(m.group(4)),
                            "free": int(col[5]), "fleet": int(col[6]), "zone": int(col[7])})
    return out


def own_thetas():
    got = {}
    for f in glob.glob(os.path.join(OUT, "synth_v36", "*", "theta_*.json")):
        m = OWN.search(os.path.basename(f))
        if m:
            got[m.group(1)] = f
    return got


def run_one(job, orders, timeout):
    """런 하나. 실패를 None 이 아니라 **이유와 함께** 돌려준다."""
    w, label, theta, seed = job
    gap = (REF_ARRIVAL_S * REF_ROBOTS / w["fleet"]) / DT
    cmd = [sys.executable, "sim_v2_tasks.py", "vf", str(w["fleet"]), str(orders),
           str(seed), "1", "--order-gap=%.4f" % gap, "--capacity=%d" % CAPACITY,
           "--speed=%g" % SPEED, "--map-dir=" + os.path.join(SYNTH, w["name"]),
           "--theta=" + theta]
    env = dict(os.environ, SIM_NO_PLOT="1", PYTHONIOENCODING="utf-8",
               OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    try:
        p = subprocess.run(cmd, cwd=SIM, env=env, capture_output=True, text=True,
                           encoding="utf-8", timeout=timeout)
    except subprocess.TimeoutExpired:
        return w, label, seed, None, "타임아웃"
    for line in (p.stdout or "").splitlines():
        if line.startswith("[SUMMARY] "):
            return w, label, seed, json.loads(line[10:])["tasks_per_h"], ""
    tail = (p.stderr or "").strip().splitlines()
    why = tail[-1][:60] if tail else "출력 없음"
    return w, label, seed, None, ("스톨" if "정체" in why else why)


def judge(a, b):
    """-138 실효 판정: 시드별 짝차이의 부호가 모두 같고 |평균| > 산포.

    평균만 보면 시드 운을 실효로 읽는다 — 처리량 시드 산포가 θ 효과보다 크다."""
    d = [x - y for x, y in zip(a, b)]
    mean, spread = st.fmean(d), max(d) - min(d)
    same = all(v > 0 for v in d) or all(v < 0 for v in d)
    ok = same and abs(mean) > spread
    return mean, spread, (("우세" if mean > 0 else "열세") if ok else "묻힘")


def band(rows, key, title):
    print("\n  %s" % title)
    print("  %6s%8s%12s%10s%12s" % ("값", "창고", "tasks/h", "대당", "고정vs중립"))
    print("  " + "-" * 50)
    for v in sorted({r[key] for r in rows}):
        g = [r for r in rows if r[key] == v]
        print("  %6d%8d%12.1f%10.1f%11.1f%%"
              % (v, len(g), st.fmean(r["fixed_mean"] for r in g),
                 st.fmean(r["fixed_mean"] / r["fleet"] for r in g),
                 st.fmean(r["gain_vs_neutral"] for r in g)))


def main():
    p = argparse.ArgumentParser(description="합성 창고 θ 전수 측정")
    p.add_argument("--jobs", type=int, default=64, help="동시 시뮬 수 (그대로 쓴다)")
    p.add_argument("--orders", type=int, default=250)
    p.add_argument("--timeout", type=int, default=900)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--out", default=os.path.join(OUT, "synth_sweep_v2.csv"))
    a = p.parse_args()

    neutral_path = os.path.join(OUT, "_neutral_theta.json")
    os.makedirs(OUT, exist_ok=True)
    with open(neutral_path, "w", encoding="utf-8") as f:
        json.dump(NEUTRAL, f)

    ws, own = warehouses()[:a.limit or None], own_thetas()
    jobs = []
    for w in ws:
        for label, th in (("neutral", neutral_path), ("fixed", FIXED),
                          ("own", own.get(w["name"]))):
            if th:
                jobs += [(w, label, th, s) for s in SEEDS]
    print("창고 %d개 · 런 %d개 · 동시 %d" % (len(ws), len(jobs), a.jobs))

    t0, res, fails, done = time.time(), {}, [], 0
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        for w, label, seed, val, why in pool.map(
                lambda j: run_one(j, a.orders, a.timeout), jobs):
            res.setdefault((w["name"], label), {})[seed] = val
            done += 1
            if val is None:
                fails.append((w["name"], label, seed, why))
            if done % 50 == 0 or done == len(jobs):
                print("  %4d/%d  실패 %d  (경과 %.0f분)"
                      % (done, len(jobs), len(fails), (time.time() - t0) / 60), flush=True)
    os.unlink(neutral_path)

    rows = []
    for w in ws:
        r = dict(w)
        for label in LABELS:
            vals = [v for v in (res.get((w["name"], label)) or {}).values() if v is not None]
            r[label + "_n"] = len(vals)
            r[label + "_mean"] = round(st.fmean(vals), 1) if vals else ""
        rows.append(r)

    full = [r for r in rows if r["neutral_n"] == 3 and r["fixed_n"] == 3]
    for r in full:
        r["gain_vs_neutral"] = 100 * (r["fixed_mean"] - r["neutral_mean"]) / r["neutral_mean"]
    duel = [r for r in full if r["own_n"] == 3]
    for r in duel:
        m, sp, v = judge([res[(r["name"], "own")][s] for s in SEEDS],
                         [res[(r["name"], "fixed")][s] for s in SEEDS])
        r["own_vs_fixed_pct"] = 100 * m / r["fixed_mean"]
        r["own_spread"] = round(sp, 1)
        r["verdict"] = v

    with open(a.out, "w", encoding="utf-8", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=sorted({k for r in rows for k in r}),
                            extrasaction="ignore")
        wr.writeheader()
        wr.writerows(rows)

    print("\n=== 0. 완주 (3시드 다 도는가) ===")
    for label in LABELS:
        have = [r for r in rows if label != "own" or r["own_n"] or own.get(r["name"])]
        n3 = sum(1 for r in have if r[label + "_n"] == 3)
        n0 = sum(1 for r in have if r[label + "_n"] == 0)
        print("  %-8s 대상 %3d창고 · 3/3 완주 %3d (%5.1f%%) · 전멸 %d"
              % (label, len(have), n3, 100 * n3 / max(len(have), 1), n0))
    if fails:
        why = {}
        for _, label, _, w2 in fails:
            why[(label, w2)] = why.get((label, w2), 0) + 1
        print("  실패 %d런 — " % len(fails) + " / ".join(
            "%s %s %d" % (k[0], k[1], v)
            for k, v in sorted(why.items(), key=lambda x: -x[1])[:6]))

    print("\n=== 1. 일반화: 고정 θ vs 중립 (양쪽 3/3 완주 %d창고) ===" % len(full))
    if full:
        pos = [r for r in full if r["gain_vs_neutral"] > 0]
        print("  중립보다 나은 창고 %d/%d · 평균 %+.1f%%"
              % (len(pos), len(full), st.fmean(r["gain_vs_neutral"] for r in full)))

    print("\n=== 2. 예측: 창고별 θ vs 고정 θ (양쪽 3/3 완주 %d창고) ===" % len(duel))
    for v in ("우세", "열세", "묻힘"):
        g = [r for r in duel if r["verdict"] == v]
        extra = "  평균 %+.1f%%" % st.fmean(r["own_vs_fixed_pct"] for r in g) if g else ""
        print("  창고별 θ %-4s %3d개 (%5.1f%%)%s"
              % (v, len(g), 100 * len(g) / max(len(duel), 1), extra))
    if duel:
        print("  전체 평균 %+.2f%% (양수 = 창고별 탐색이 이득)"
              % st.fmean(r["own_vs_fixed_pct"] for r in duel))

    print("\n=== 3. 설계 인자별 응답 (고정 θ · %d창고) ===" % len(full))
    if full:
        band(full, "aisles", "통로 수")
        band(full, "pitch", "통로 중심 간격")
        band(full, "length", "통로 길이")
    print("\n  CSV %s" % a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
