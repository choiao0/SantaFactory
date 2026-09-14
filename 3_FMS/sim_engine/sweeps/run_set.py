# -*- coding: utf-8 -*-
"""B5 시험 세트 병렬 실행 (S15P21A106-79). 런은 독립이라 프로세스 풀로 N배.

    python sweeps/run_set.py [--set=b5|base7] [--jobs=N] [--out=results/set_<tag>.csv] [--tag=<라벨>] [--extra=--flag ...]
      --set    b5   = 계획 §4 S1~S9 (S7·S8 은 주문 파일이 있을 때만; SET_ORDERS_DIR 환경변수)
               base7 = base 6 40 × 시드 {42,7,43,44,101,103,104}
      --jobs   동시 프로세스 수 (기본 os.cpu_count()-1)
      --extra  모든 런에 덧붙일 인자(여러 번 가능). 예: --extra=--footprint=exact,front_2cell
    출력: CSV 한 줄 = 런 하나 (name, args, stall, makespan_steps, tasks_per_h, yield_events, conflict_wait, wall_s, + SUMMARY 키).
    표준 출력에 요약 표.  STALL 덤프는 results/stall_set_*.txt (sweeps/_common.run_sim).
"""
import csv
import os
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import RES_DIR, run_sim  # noqa: E402

ORDERS_DIR = os.environ.get("SET_ORDERS_DIR", "")
SIX_K = ["--theta=../infra/out/theta_wallA_r24_g15.json", "--speed=0.9", "--horizon=19440", "--shifts=out",
         "--capacity=6", "--tote-units=8", "--svc-per-tote=5"]


def _sets():
    b5 = [
        ("S1_base7", ("base", 6, 40, 7, 1), []),
        ("S2_base44", ("base", 6, 40, 44, 1), []),
        ("S3_base101", ("base", 6, 40, 101, 1), []),
        ("S4_base42", ("base", 6, 40, 42, 1), []),
        ("S5_exp22", ("exp", 22, 120, 101, 1), ["--order-gap=15"]),
        ("S6_exp16", ("exp", 16, 120, 102, 1), ["--order-gap=15"]),
        ("S9_base44_nolanes", ("base", 6, 40, 44, 1), ["--no-lanes"]),
    ]
    for seed in (101, 103):
        path = os.path.join(ORDERS_DIR, f"orders6000_s{seed}_cap24.json")
        if ORDERS_DIR and os.path.exists(path):
            b5.append((f"S{7 if seed == 101 else 8}_6000_s{seed}", ("x", 24, 0, seed, 1), SIX_K + [f"--orders-file={path}"]))
    base7 = [(f"base_s{s}", ("base", 6, 40, s, 1), []) for s in (42, 7, 43, 44, 101, 103, 104)]
    return {"b5": b5, "base7": base7}


def _one(item):
    name, (tag, n, orders, seed, ab), extra = item
    rec = run_sim(tag, n, orders, seed, ab, extra=extra, stall_dump_prefix="stall_set")
    rec["name"], rec["args"] = name, " ".join(extra)
    rec.setdefault("stall", 0)
    return rec


def main(argv):
    opt = {k: v for k, v in (a[2:].split("=", 1) for a in argv if a.startswith("--") and "=" in a)}
    extra = [a.split("=", 1)[1] for a in argv if a.startswith("--extra=")]
    which = opt.get("set", "b5")
    jobs = int(opt.get("jobs", max(1, (os.cpu_count() or 2) - 1)))
    tag = opt.get("tag", which)
    out = opt.get("out", os.path.join(RES_DIR, f"set_{tag}.csv"))
    items = [(name, args, list(ex) + extra) for name, args, ex in _sets()[which]]
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        recs = list(pool.map(_one, items))
    keys = ["name", "args", "stall", "makespan_steps", "tasks_per_h", "yield_events", "conflict_wait", "wall_s"]
    allkeys = keys + sorted({k for r in recs for k in r} - set(keys))
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=allkeys)
        w.writeheader()
        w.writerows(recs)
    print(f"{'name':<22}{'stall':>6}{'makespan':>10}{'tasks/h':>9}{'yield':>7}{'wall_s':>8}")
    for r in recs:
        print(f"{r['name']:<22}{r.get('stall', 0):>6}{str(r.get('makespan_steps', '')):>10}"
              f"{str(r.get('tasks_per_h', '')):>9}{str(r.get('yield_events', '')):>7}{r.get('wall_s', ''):>8}")
    print(f"→ {out}")


if __name__ == "__main__":
    main(sys.argv[1:])
