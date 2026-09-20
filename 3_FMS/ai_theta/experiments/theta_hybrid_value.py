# -*- coding: utf-8 -*-
"""하이브리드 θ 가 공통 θ 보다 나은가 (S15P21A106-206).

`make_hybrid_theta.py` 가 만든 θ 를 개방 조건에서 공통 θ 와 **처리량으로** 맞붙인다.

    하이브리드 θ = 예측되는 축만 GP 로 예측(그 창고는 학습에서 뺀 값) + 나머지는 공통 고정
    공통 θ       = 창고 100개 θ 의 평균

앞선 대결에서 **창고별 직접 탐색 θ 가 공통 θ 를 못 이겼다**(52창고, 양수 25/52, p=0.89).
직접 탐색 θ 는 8축을 전부 맞춘 값이라 배울 게 없는 축에서 탐색 노이즈를 싣고 있었다. 그
축들을 묶으면 손해가 사라지므로 하이브리드가 **둘 다보다** 나을 여지가 있다 — 그 가설을
여기서 끝낸다.

판정은 -138 규칙(부호가 모두 같고 |평균| > 산포)이되, 개별 창고는 짝이 2~5개뿐이라 둔하다.
**부호검정**이 진짜 판정이다. 표본이 20창고 미만이면 결론 문구를 찍지 않는다.

평가 시드 {101,103,104,105,107} 는 탐색 시드 {42,43,44} 와 분리돼 있다 (계약 §5).
"""
import argparse
import json
import os
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
SEEDS = [101, 103, 104, 105, 107]      # 평가 시드 (계약 §5)
MIN_PAIRS = 2                          # 두 θ 가 같은 시드에서 모두 성공한 짝
MIN_ROWS = 20                          # 이보다 적으면 결론을 내지 않는다


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
    p = argparse.ArgumentParser(description="하이브리드 θ vs 공통 θ (개방 조건)")
    p.add_argument("--jobs", type=int, default=40)
    p.add_argument("--dir", default=os.path.join(OUT, "theta_open"))
    p.add_argument("--limit", type=int, default=0, help="앞에서 N 창고만 (연습용)")
    a = p.parse_args()

    hyb_dir = os.path.join(a.dir, "_hybrid")
    common_path = os.path.join(hyb_dir, "theta_common.json")
    if not os.path.exists(common_path):
        raise SystemExit("_hybrid 가 없다 — make_hybrid_theta.py 를 먼저 돌릴 것")

    design = {d["name"]: d for d in json.load(open(os.path.join(a.dir, "design.json"),
                                                   encoding="utf-8"))}
    hyb = {}
    for f in sorted(os.listdir(hyb_dir)):
        if f.startswith("theta_hybrid_") and f.endswith(".json"):
            n = f[len("theta_hybrid_"):-len(".json")]
            if n in design:
                hyb[n] = os.path.join(hyb_dir, f)
    names = sorted(hyb)[:a.limit or None]
    if len(names) < MIN_ROWS:
        raise SystemExit("하이브리드 θ 가 %d개뿐 — make_hybrid_theta.py 출력을 확인할 것" % len(names))

    common = json.load(open(common_path, encoding="utf-8"))
    print("창고 %d개 · 공통 θ = 창고별 θ 의 평균" % len(names))
    print("  " + " · ".join("%s %.3f" % (k[:12], common[k]) for k in
                            ("loop_gain", "junction_penalty", "wait_cost", "station_out")))

    jobs = [(n, lab, th, s) for n in names
            for lab, th in (("hybrid", hyb[n]), ("common", common_path))
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
        pairs = [(res.get((n, "hybrid", s)), res.get((n, "common", s))) for s in SEEDS]
        pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
        if len(pairs) < MIN_PAIRS:
            thin += 1
            continue
        d = [x - y for x, y in pairs]
        mean, spread = st.fmean(d), max(d) - min(d)
        same = all(v > 0 for v in d) or all(v < 0 for v in d)
        ok = same and abs(mean) > spread
        base = st.fmean(y for _, y in pairs)
        rows.append({"name": n, "n_pair": len(pairs), "hybrid": st.fmean(x for x, _ in pairs),
                     "common": base, "diff_pct": 100 * mean / base, "spread": spread,
                     "verdict": ("예측" if mean > 0 else "공통") if ok else "묻힘"})

    print("\n=== 하이브리드 θ vs 공통 θ (개방 조건) ===")
    print("  채택 %d창고 · 짝 부족으로 제외 %d창고 · 짝 평균 %.1f개"
          % (len(rows), thin, st.fmean(r["n_pair"] for r in rows) if rows else 0))
    if len(rows) < MIN_ROWS:
        print("\n  **표본 %d창고 — 결론을 낼 수 없다.** 교착률이 너무 높아 평가가 성립하지 않는다."
              % len(rows))
        return 1

    for v in ("예측", "공통", "묻힘"):
        g = [r for r in rows if r["verdict"] == v]
        if g:
            print("  %-5s %3d개 (%4.1f%%)  평균 %+.2f%%"
                  % (v, len(g), 100 * len(g) / len(rows), st.fmean(r["diff_pct"] for r in g)))

    m = st.fmean(r["diff_pct"] for r in rows)
    win = sum(1 for r in rows if r["diff_pct"] > 0)
    n = len(rows)
    pval = min(1.0, sum(comb(n, k) for k in range(max(win, n - win), n + 1)) / 2 ** n * 2)
    print("\n  전체 평균 %+.2f%% · 양수 %d/%d · 부호검정 p = %.2e" % (m, win, n, pval))
    print("  기준선: 창고별 직접 탐색 θ 는 +0.68 % · 양수 25/52 · p = 8.9e-01 이었다")

    print()
    if m >= 1.0 and pval < 0.05:
        print("  -> **하이브리드 θ 가 공통 θ 를 이긴다.** 축을 줄인 예측이 값을 낸다 —")
        print("     견적 파이프라인에 모델을 붙일 근거가 생겼다.")
    elif abs(m) < 0.5 or pval > 0.2:
        print("  -> **없다.** 축을 골라내도 공통 θ 와 같다 — 평탄한 골짜기가 축 단위에서도 성립한다.")
        print("     θ 예측 모델은 어떤 형태로도 값을 내지 않는다는 결론이 확정된다.")
    else:
        print("  -> 작지만 방향이 있다. 크기(%+.2f%%)와 p 를 같이 보고 판단할 것." % m)

    csv_path = os.path.join(OUT, "theta_hybrid_value_v36.csv")
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        f.write("name,n_pair,hybrid_tasks_h,common_tasks_h,diff_pct,spread,verdict\n")
        for r in rows:
            f.write("%s,%d,%.1f,%.1f,%.3f,%.1f,%s\n"
                    % (r["name"], r["n_pair"], r["hybrid"], r["common"],
                       r["diff_pct"], r["spread"], r["verdict"]))
    print("  CSV %s" % csv_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
