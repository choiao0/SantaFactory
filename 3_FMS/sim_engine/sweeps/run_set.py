# -*- coding: utf-8 -*-
"""B5 시험 세트 병렬 실행 (S15P21A106-79). 런은 독립이라 프로세스 풀로 N배.

    python sweeps/run_set.py [--set=b5|base7|six] [--jobs=N] [--out=results/set_<tag>.csv] [--tag=<라벨>] [--extra=--flag ...]
      --set    b5   = 계획 §4 S1~S9 (S7·S8 은 주문 파일이 있을 때만; SET_ORDERS_DIR 환경변수)
               base7 = base 6 40 × 시드 {42,7,43,44,101,103,104}
               six   = 6,000건/6h 워커 조건 × {24,28}대 × 시드 {101,103,104} (SET_ORDERS_DIR/orders6000_s<seed>_cap10.json,
                       ordered_at_s 는 [0, 21600) 기준 — 하루 시각이면 slice_orders.rescale_orders 로 먼저 옮길 것; -79 D3)
      --jobs   동시 프로세스 수 (기본 os.cpu_count()-1)
      --extra  모든 런에 덧붙일 인자(여러 번 가능). 예: --extra=--footprint=exact,front_2cell
    출력: CSV 한 줄 = 런 하나 (name, args, stall, makespan_steps, tasks_per_h, yield_events, conflict_wait, wall_s, + SUMMARY 키).
    표준 출력에 요약 표.  STALL 덤프는 results/stall_set_*.txt (sweeps/_common.run_sim).
    요약 표의 sat/h·sd_tick 은 계약 §2 조건부 키 saturated_tph·standoff_ticks (-230) — 6h 세트(six)의 판정 지표다.
    tasks/h 는 six 처럼 도착이 웨이브인 런에서 뒤 구간의 수요 제한이 섞여 용량을 못 나타낸다.
"""
import csv
import os
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import RES_DIR, run_sim  # noqa: E402

ORDERS_DIR = os.environ.get("SET_ORDERS_DIR", "")
# 6,000건/6h 워커 조건 (견적 워커와 같은 환산, 계약 §5-1): speed 0.9 → dt = 1 m / (0.9 × MOVE_TICKS 4) = 0.2778 s,
# 6h = 77,760틱, 토트당 서비스 5 s = 18틱, 토트 10개들이·개인 주문 상한 10개(2026-09-15 결정: 주문 1건 = 토트 1개, 상한은 주문 파일에서 적용). 1틱 시절 값(19440·5)은 -194 다틱에서 4배 짧았다 (D3 2026-09-15 수정).
SIX_K = ["--theta=../infra/out/theta_wallA_r24_g15.json", "--speed=0.9", "--horizon=77760", "--shifts=out",
         "--capacity=6", "--tote-units=10", "--svc-per-tote=18"]


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
    def _six(seed):
        path = os.path.join(ORDERS_DIR, f"orders6000_s{seed}_cap10.json")
        return path if ORDERS_DIR and os.path.exists(path) else None
    for seed in (101, 103):
        path = _six(seed)
        if path:
            b5.append((f"S{7 if seed == 101 else 8}_6000_s{seed}", ("x", 24, 0, seed, 1), SIX_K + [f"--orders-file={path}"]))
    base7 = [(f"base_s{s}", ("base", 6, 40, s, 1), []) for s in (42, 7, 43, 44, 101, 103, 104)]
    # six = 6,000건/6h × {24, 28}대 × 평가 시드 {101, 103, 104} (D3 판정용). 주문 파일은 SET_ORDERS_DIR 에 orders6000_s<seed>_cap10.json
    six = [(f"six_r{n}_s{s}", ("x", n, 0, s, 1), SIX_K + [f"--orders-file={_six(s)}"])
           for s in (101, 103, 104) for n in (24, 28) if _six(s)]
    return {"b5": b5, "base7": base7, "six": six}


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
    print(f"{'name':<22}{'stall':>6}{'makespan':>10}{'tasks/h':>9}{'sat/h':>8}{'sd_tick':>9}{'yield':>7}{'wall_s':>8}")
    for r in recs:
        print(f"{r['name']:<22}{r.get('stall', 0):>6}{str(r.get('makespan_steps', '')):>10}"
              f"{str(r.get('tasks_per_h', '')):>9}{str(r.get('saturated_tph', '-')):>8}"
              f"{str(r.get('standoff_ticks', '-')):>9}"
              f"{str(r.get('yield_events', '')):>7}{r.get('wall_s', ''):>8}")
    print(f"→ {out}")


if __name__ == "__main__":
    main(sys.argv[1:])
