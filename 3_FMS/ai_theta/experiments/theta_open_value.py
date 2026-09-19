# -*- coding: utf-8 -*-
"""창고별 θ 가 공통 θ 보다 실제로 나은가 — 개방 조건 (S15P21A106-206).

**마지막 관문이다.** `theta_open_lhs.py` 가 창고 103개에서 θ 를 뽑았고, 기하 상관은
R² 0.18 로 차단 조건(0.13)과 거의 같았다. 남은 질문 하나 — **그 θ 차이가 처리량을 올리는가.**

상관이 약해도 처리량이 오르면 쓸 값이 있고, 상관이 좋아도 처리량이 안 오르면 예측할 대상이
없다. 그래서 θ 벡터가 아니라 **처리량으로** 잰다. 목적함수가 평탄해 서로 3.4배 다른 θ 가
1.8 % 안에서 같은 결과를 낸 것을 이미 봤다.

    창고별 θ = 그 창고의 반복 2회 평균 (탐색 노이즈가 sqrt(2) 로 줄어 있다)
    공통 θ   = 103개 창고 θ 의 평균 — "창고를 안 보고 하나만 쓴다" 의 최선

운영 θ(theta_wallA_r20_c6_v36.json)를 공통 θ 로 쓰지 않는 이유: 그것은 **차단 조건**에서
뽑은 값이라, 비교가 "창고별이냐 아니냐" 가 아니라 "차단이냐 개방이냐" 가 돼 버린다.

## 1차 실행이 왜 실패했나 (2026-09-17)

시드 3개를 **전부** 완주해야 그 창고를 쓰도록 했더니 **100창고 중 95개가 빠졌다.**
개방 조건은 폭 1칸 통로에서 2칸 차체가 회전을 못 해 갇히고, 역산하면 런의 약 40 % 가
교착한다((1−p)^6 = 0.05 → p ≈ 0.40). 5창고로 낸 판정은 통계가 아니다.

그래서 두 가지를 고쳤다.

1. **평가 시드를 5개로** — 탐색 시드 {42,43,44} 와 겹치지 않는 5개. 성공 시드가 늘어난다
2. **짝이 되는 시드만 쓴다** — 두 θ 가 **같은 시드에서 모두** 성공한 것만 짝짓고,
   짝이 2개 이상이면 그 창고를 채택한다. 시드를 짝지어야 시드 운이 비교에 안 섞인다

판정은 -138 규칙(부호가 모두 같고 |평균| > 산포)이되, 개별 창고는 짝이 2~5개뿐이라 둔하다.
**부호검정**이 진짜 판정이다 — 창고 판정에서 42/47 양수 p=1.2e-08 이 그랬다.
표본이 20창고 미만이면 결론 문구를 찍지 않는다(1차 실행의 실수).
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
from math import comb


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
SEEDS = [101, 103, 104, 105, 107]      # 평가 시드 — 탐색 시드 {42,43,44} 와 분리 (계약 §5)
MIN_PAIRS = 2                          # 두 θ 가 같은 시드에서 모두 성공한 짝이 이만큼은 있어야 채택
MIN_ROWS = 20                          # 이보다 적으면 결론을 내지 않는다
AXES = ["aisle_alt_gain", "aisle_alt_boost", "loop_gain", "main_aisle_gain",
        "junction_penalty", "station_in", "station_out", "wait_cost"]
CATS = ["aisle_period", "aisle_phase", "loop_dir"]
NAME = re.compile(r"theta_open_(r\d+p\d+l\d+)_r\d+_L\d+_s\d+\.json$")


def orders_for(rate, orders_max=250, hours=1.0, floor=100):
    """theta_open_lhs.py 와 **같은 식**이어야 한다 — 주문 수가 다르면 다른 조건이다."""
    return max(floor, min(orders_max, round(rate * hours)))


def sim(w, theta, seed, timeout=3600):
    rate = w["cap"] * w["load_frac"]
    cmd = [sys.executable, "sim_v2_tasks.py", "vf", str(w["fleet"]),
           str(orders_for(rate)), str(seed), "0",          # 마지막 0 = 랙 통로 개방
           "--order-gap=%.4f" % ((3600.0 / rate) / DT), "--capacity=%d" % CAPACITY,
           "--speed=%g" % SPEED, "--map-dir=" + os.path.join(SYNTH, w["name"]),
           "--theta=" + theta]
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
    p = argparse.ArgumentParser(description="창고별 θ vs 공통 θ (개방 조건)")
    p.add_argument("--jobs", type=int, default=40)
    p.add_argument("--dir", default=os.path.join(OUT, "theta_open"))
    p.add_argument("--limit", type=int, default=0, help="앞에서 N 창고만 (연습용)")
    a = p.parse_args()

    design = {d["name"]: d for d in json.load(open(os.path.join(a.dir, "design.json"),
                                                   encoding="utf-8"))}
    got = {}
    for f in sorted(glob.glob(os.path.join(a.dir, "*", "theta_open_*.json"))):
        m = NAME.search(os.path.basename(f))
        if m:
            got.setdefault(m.group(1), []).append(json.load(open(f, encoding="utf-8")))
    got = {n: ts for n, ts in got.items() if n in design and len(ts) >= 2}
    names = sorted(got)[:a.limit or None]
    if len(names) < MIN_ROWS:
        raise SystemExit("반복 2회 창고가 %d개뿐 — theta_open_lhs.py 결과를 확인할 것" % len(names))

    os.makedirs(os.path.join(a.dir, "_value"), exist_ok=True)
    own = {}
    for n in names:
        th = {ax: st.fmean(t[ax] for t in got[n]) for ax in AXES}
        th.update({c: st.mode([t[c] for t in got[n]]) for c in CATS})
        pth = os.path.join(a.dir, "_value", "theta_own_%s.json" % n)
        json.dump(th, open(pth, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        own[n] = (pth, th)

    common = {ax: st.fmean(t[ax] for _, t in own.values()) for ax in AXES}
    common.update({c: st.mode([t[c] for _, t in own.values()]) for c in CATS})
    common_path = os.path.join(a.dir, "_value", "theta_common.json")
    json.dump(common, open(common_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("창고 %d개 · 공통 θ = 그 평균" % len(own))
    print("  " + " · ".join("%s %.3f" % (k[:12], common[k]) for k in
                            ("loop_gain", "junction_penalty", "wait_cost", "station_out")))

    jobs = [(n, lab, th, s) for n in names
            for lab, th in (("own", own[n][0]), ("common", common_path))
            for s in SEEDS]
    print("런 %d개 · 동시 %d · 평가 시드 %s · 짝 %d개 이상이면 채택"
          % (len(jobs), a.jobs, SEEDS, MIN_PAIRS))

    t0, res = time.time(), {}
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        for j, v in zip(jobs, pool.map(lambda x: sim(design[x[0]], x[2], x[3]), jobs)):
            res[(j[0], j[1], j[3])] = v
    ok_runs = sum(1 for v in res.values() if v is not None)
    print("  %.0f분 · 런 성공 %d/%d (교착률 %.0f%%)"
          % ((time.time() - t0) / 60, ok_runs, len(jobs),
             100 * (1 - ok_runs / len(jobs))))

    rows, thin = [], 0
    for n in names:
        pairs = [(res.get((n, "own", s)), res.get((n, "common", s))) for s in SEEDS]
        pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
        if len(pairs) < MIN_PAIRS:
            thin += 1
            continue
        d = [x - y for x, y in pairs]
        mean, spread = st.fmean(d), max(d) - min(d)
        same = all(v > 0 for v in d) or all(v < 0 for v in d)
        ok = same and abs(mean) > spread
        base = st.fmean(y for _, y in pairs)
        rows.append({"name": n, "n_pair": len(pairs), "own": st.fmean(x for x, _ in pairs),
                     "common": base, "diff_pct": 100 * mean / base, "spread": spread,
                     "verdict": ("창고별" if mean > 0 else "공통") if ok else "묻힘"})

    print("\n=== 창고별 θ vs 공통 θ (개방 조건) ===")
    print("  채택 %d창고 · 짝 부족으로 제외 %d창고 · 짝 평균 %.1f개"
          % (len(rows), thin, st.fmean(r["n_pair"] for r in rows) if rows else 0))
    if len(rows) < MIN_ROWS:
        print("\n  **표본 %d창고 — 결론을 낼 수 없다.** 교착률이 너무 높아 평가가 성립하지 않는다."
              % len(rows))
        return 1

    for v in ("창고별", "공통", "묻힘"):
        g = [r for r in rows if r["verdict"] == v]
        if g:
            print("  %-5s %3d개 (%4.1f%%)  평균 %+.2f%%"
                  % (v, len(g), 100 * len(g) / len(rows), st.fmean(r["diff_pct"] for r in g)))

    m = st.fmean(r["diff_pct"] for r in rows)
    win = sum(1 for r in rows if r["diff_pct"] > 0)
    n = len(rows)
    pval = min(1.0, sum(comb(n, k) for k in range(max(win, n - win), n + 1)) / 2 ** n * 2)
    print("\n  전체 평균 %+.2f%% · 양수 %d/%d · 부호검정 p = %.2e" % (m, win, n, pval))

    print()
    if m >= 2.0 and pval < 0.05:
        print("  -> **창고별 θ 에 쓸 값이 있다.** 예측 모델(GP·XGBoost)로 간다.")
    elif abs(m) < 0.5 or pval > 0.2:
        print("  -> **없다.** θ 값은 달라도 처리량이 같다 — 지형을 열어도 평탄한 골짜기다.")
        print("     기하·대수·부하 어느 축으로도 θ 는 예측되지 않는다는 결론이 확정된다.")
    else:
        print("  -> 작지만 방향이 있다. 크기(%+.2f%%)와 p 를 같이 보고 판단할 것." % m)

    csv_path = os.path.join(OUT, "theta_open_value_v36.csv")
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        f.write("name,n_pair,own_tasks_h,common_tasks_h,diff_pct,spread,verdict\n")
        for r in rows:
            f.write("%s,%d,%.1f,%.1f,%.3f,%.1f,%s\n"
                    % (r["name"], r["n_pair"], r["own"], r["common"],
                       r["diff_pct"], r["spread"], r["verdict"]))
    print("  CSV %s" % csv_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
