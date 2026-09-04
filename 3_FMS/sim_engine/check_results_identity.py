# -*- coding: utf-8 -*-
# ============================================================
# 결과 동일성 검사 — 성능 최적화 회귀 (S15P21A106-136)
#
# results/b0z_sweep.csv(40주문 기준선)·load_sweep.csv(고부하)의 각 행을 같은 인자로 다시 돌려
# [SUMMARY] 의 숫자 키가 **전부 같은지**(uniform cost 는 비트 동일이 기대값) 확인한다.
# 최적화는 이 검사가 통과해야만 유효하다 (contracts/SIM_RUN_CONTRACT.md §5).
#
# 사용 (3_FMS/sim_engine):
#   python check_results_identity.py                 # 전부 (헤딩 28대 포함, 수십 분)
#   python check_results_identity.py --quick         # 대표 8행 (칸·헤딩 × 소·대 × 두 CSV, ~3분)
#   python check_results_identity.py --csv results/b0z_sweep.csv --engine heading --max 4
# 종료 코드 0 = 전부 동일, 1 = 차이 있음 (차이 난 키·값 출력).
# ============================================================
import argparse
import csv
import json
import os
import subprocess
import sys
import time

OUT = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(OUT, "results")
PY = sys.executable
ENV = dict(os.environ, SIM_NO_PLOT="1", PYTHONIOENCODING="utf-8")
IGNORE = {"wall_s"}                                   # 실행 시간은 비교 대상 아님
QUICK = [("b0z_sweep.csv", "cell", 6, 42), ("b0z_sweep.csv", "cell", 16, 7),
         ("b0z_sweep.csv", "heading", 6, 42), ("b0z_sweep.csv", "heading", 16, 7),
         ("load_sweep.csv", "cell", 28, 42), ("load_sweep.csv", "heading", 12, 42),
         ("load_sweep.csv", "heading", 20, 7), ("load_sweep.csv", "heading", 28, 42)]


def run_row(row):
    args = [PY, os.path.join(OUT, "sim_v2_tasks.py"), row["variant"], row["n_robots"], row["n_orders"],
            row["seed"], row["aisle_block"], f"--flow={row['flow']}"]
    if row.get("heading") not in ("", None):
        args.append("--heading")
    if row.get("order_gap") not in ("", None):
        args.append(f"--order-gap={float(row['order_gap']):g}")
    if row.get("zone") in ("", None) and row["flow"] == "main":
        args.append("--fixed-homes")
    t0 = time.perf_counter()
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", env=ENV, cwd=OUT)
    line = next((ln for ln in r.stdout.splitlines() if ln.startswith("[SUMMARY]")), None)
    if not line:
        return None, time.perf_counter() - t0, (r.stdout[-800:] + r.stderr[-800:])
    return json.loads(line[len("[SUMMARY] "):]), time.perf_counter() - t0, ""


def same(a, b):
    if isinstance(a, float) or isinstance(b, float):
        return float(a) == float(b)
    return str(a) == str(b)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv", action="append", help="기본: b0z_sweep.csv + load_sweep.csv")
    p.add_argument("--engine", choices=("cell", "heading"))
    p.add_argument("--max", type=int, default=0, help="CSV당 최대 행 수 (0 = 전부)")
    p.add_argument("--quick", action="store_true")
    a = p.parse_args()
    csvs = a.csv or ["results/b0z_sweep.csv", "results/load_sweep.csv"]

    rows = []
    for path in csvs:
        full = path if os.path.isabs(path) else os.path.join(OUT, path)
        with open(full, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                r["_src"] = os.path.basename(full)
                rows.append(r)
    if a.quick:
        pick = set(QUICK)
        rows = [r for r in rows if (r["_src"], r["engine"], int(r["n_robots"]), int(r["seed"])) in pick]
    if a.engine:
        rows = [r for r in rows if r["engine"] == a.engine]
    if a.max:
        per = {}
        rows = [r for r in rows if per.setdefault(r["_src"], []).append(r) or len(per[r["_src"]]) <= a.max]

    n_bad = 0
    for r in rows:
        label = f"{r['_src']} {r['engine']:7s} r={int(r['n_robots']):2d} seed={int(r['seed']):2d}" + \
                (f" gap={float(r['order_gap']):g}" if r.get("order_gap") else "")
        got, dt, err = run_row(r)
        if got is None:
            n_bad += 1
            print(f"[FAIL] {label}: 실행 실패\n{err}")
            continue
        diffs = []
        for k, v in r.items():
            if k.startswith("_") or k in IGNORE or k in ("engine", "load") or v == "":
                continue
            if k not in got:
                diffs.append(f"{k}: CSV {v} / 새 실행에 키 없음")
            elif not same(v, got[k]):
                diffs.append(f"{k}: {v} → {got[k]}")
        if diffs:
            n_bad += 1
            print(f"[DIFF] {label} ({dt:.1f}s): " + "; ".join(diffs))
        else:
            print(f"[OK]   {label} ({dt:.1f}s)")
    print(f"\n{len(rows)}행 중 차이 {n_bad}행")
    return 1 if n_bad else 0


if __name__ == "__main__":
    sys.exit(main())
