# -*- coding: utf-8 -*-
# ============================================================
# 결과 동일성 검사 — 성능 최적화 회귀 (S15P21A106-136)
#
# results/b0z_sweep.csv(40주문 기준선)·load_sweep.csv(고부하)의 각 행을 같은 인자로 다시 돌려
# [SUMMARY] 의 숫자 키가 **전부 같은지**(uniform cost 는 비트 동일이 기대값) 확인한다.
# 최적화는 이 검사가 통과해야만 유효하다 (contracts/SIM_RUN_CONTRACT.md §5).
#
# 사용 (3_FMS/sim_engine):
#   python checks/check_results_identity.py                 # 전부 (헤딩 28대 포함, 수십 분)
#   python checks/check_results_identity.py --quick         # 대표 8조합 = 12행 (칸·헤딩 × 소·대 × 두 CSV, 고부하는 간격 15·25 둘, ~1분)
#   python checks/check_results_identity.py --csv results/b0z_sweep.csv --engine heading --max 4
# 종료 코드 0 = 전부 동일, 1 = 차이 있음 (차이 난 키·값 출력).
# ============================================================
import argparse
import csv
import json
import os
import subprocess
import sys
import time

ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ENGINE_DIR)
OUT = ENGINE_DIR
RES = os.path.join(OUT, "results")
PY = sys.executable
ENV = dict(os.environ, SIM_NO_PLOT="1", PYTHONIOENCODING="utf-8")
IGNORE = {"wall_s"}                                   # 실행 시간은 비교 대상 아님
META = {"engine", "load"}                             # 스윕 스크립트가 붙인 열 — SUMMARY 에 없음
B0Z_CSV = "b0z_sweep.csv"                             # 40주문 기준선 (fleet_sweep_b0z.py)
LOAD_CSV = "load_sweep.csv"                           # 고부하 L1·L2 (fleet_sweep_load.py)
DEFAULT_CSVS = [os.path.join("results", B0Z_CSV), os.path.join("results", LOAD_CSV)]
# --quick 대표 8행: (CSV, engine, n_robots, seed) — 칸·헤딩 × 소·대 × 두 CSV
QUICK = {(B0Z_CSV, "cell", 6, 42), (B0Z_CSV, "cell", 16, 7),
         (B0Z_CSV, "heading", 6, 42), (B0Z_CSV, "heading", 16, 7),
         (LOAD_CSV, "cell", 28, 42), (LOAD_CSV, "heading", 12, 42),
         (LOAD_CSV, "heading", 20, 7), (LOAD_CSV, "heading", 28, 42)}


def run_row(row):
    args = [PY, os.path.join(OUT, "sim_v2_tasks.py"), row["variant"], row["n_robots"], row["n_orders"],
            row["seed"], row["aisle_block"], f"--flow={row['flow']}", "--no-lanes", "--no-yield",
            "--footprint=legacy"]        # CSV 는 v3.3 이전 값 — 회전 마스크(v3.4 기본) 없이 재현 (-203)
    # 계약 v2: 기본 = 헤딩. CSV 의 heading 열이 비어 있으면 칸 모델 행 → --cell 로 재현.
    if row.get("heading") not in ("", None):
        args.append("--heading")
    else:
        args.append("--cell")
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
    # 정확히 같은 값을 요구한다(의도적 — 결과 비트 동일이 이 검사의 목적). 허용도 비교로 바꾸지 말 것.
    if isinstance(a, float) or isinstance(b, float):
        return float(a) == float(b)
    return str(a) == str(b)


def load_rows(csvs):
    """CSV 들을 읽어 행 목록으로. 각 행에 출처 파일명 `_src` 를 붙인다."""
    rows = []
    for path in csvs:
        full = path if os.path.isabs(path) else os.path.join(OUT, path)
        with open(full, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                r["_src"] = os.path.basename(full)
                rows.append(r)
    return rows


def select_rows(rows, quick, engine, max_per_csv):
    """--quick / --engine / --max 필터. --max 는 CSV(_src)별 앞에서 N행."""
    if quick:
        rows = [r for r in rows if (r["_src"], r["engine"], int(r["n_robots"]), int(r["seed"])) in QUICK]
    if engine:
        rows = [r for r in rows if r["engine"] == engine]
    if max_per_csv:
        count = {}
        kept = []
        for r in rows:
            count[r["_src"]] = count.get(r["_src"], 0) + 1
            if count[r["_src"]] <= max_per_csv:
                kept.append(r)
        rows = kept
    return rows


def row_label(r):
    gap = f" gap={float(r['order_gap']):g}" if r.get("order_gap") else ""
    return f"{r['_src']} {r['engine']:7s} r={int(r['n_robots']):2d} seed={int(r['seed']):2d}{gap}"


def diff_row(row, got):
    """CSV 행(문자열) vs 새 실행 SUMMARY(dict). 다른 키를 'k: 전 → 후' 문자열 목록으로."""
    diffs = []
    for k, v in row.items():
        if k.startswith("_") or k in IGNORE or k in META or v == "":
            continue
        if k not in got:
            diffs.append(f"{k}: CSV {v} / 새 실행에 키 없음")
        elif not same(v, got[k]):
            diffs.append(f"{k}: {v} → {got[k]}")
    return diffs


def check_row(r):
    """행 하나 재실행·비교. 결과 출력 후 문제 있으면 True."""
    label = row_label(r)
    got, dt, err = run_row(r)
    if got is None:
        print(f"[FAIL] {label}: 실행 실패\n{err}")
        return True
    diffs = diff_row(r, got)
    if diffs:
        print(f"[DIFF] {label} ({dt:.1f}s): " + "; ".join(diffs))
        return True
    print(f"[OK]   {label} ({dt:.1f}s)")
    return False


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv", action="append", help=f"기본: {B0Z_CSV} + {LOAD_CSV}")
    p.add_argument("--engine", choices=("cell", "heading"))
    p.add_argument("--max", type=int, default=0, help="CSV당 최대 행 수 (0 = 전부)")
    p.add_argument("--quick", action="store_true")
    a = p.parse_args()

    rows = select_rows(load_rows(a.csv or DEFAULT_CSVS), a.quick, a.engine, a.max)
    n_bad = sum(check_row(r) for r in rows)
    print(f"\n{len(rows)}행 중 차이 {n_bad}행")
    return 1 if n_bad else 0


if __name__ == "__main__":
    sys.exit(main())
