# -*- coding: utf-8 -*-
# ============================================================
# θ 탐색 예산 측정 (S15P21A106-137)
#
# SIM_RUN_CONTRACT §4 실행 시간 표는 B트랙 로컬(py 3.14 / numpy 2.5.1) 실측이다.
# v2·성능 최적화(-136) 이후 값으로 갱신되었으므로 컨테이너에서 다시 잰다.
# 탐색 예산은 **워커가 실제로 도는 환경**에서 재야 하므로(컨테이너: py 3.11.9 /
# numpy 2.4.6) 같은 조건을 여기서 다시 잰다. 두 값이 다르면 계약 표가 틀린 게
# 아니라 환경이 다른 것이다 — 어느 쪽 숫자로 예산을 잡을지가 요점.
#
# 중립 θ 로 잰다. 극단 θ 는 정체를 만들어 시간이 튀는데(계약 §3), 예산은
# 평균적인 trial 을 기준으로 잡아야 하기 때문이다.
#
# 사용:
#   python measure_runtime.py --sim-engine ../../sim_engine        # 로컬
#   docker compose run --rm worker python /opt/worker/measure_runtime.py
# ============================================================
import argparse
import os
import statistics
import sys
import time

_WORKER_DIR = os.path.dirname(os.path.abspath(__file__))
if _WORKER_DIR not in sys.path:
    sys.path.insert(0, _WORKER_DIR)

from objective import SimFailed, run_once, write_theta  # noqa: E402

# (로봇, 주문, order_gap) — 계약 §4 표와 같은 격자에 권장 탐색 조건을 더한 것
GRID = [
    (8, 120, 15),
    (16, 120, 15),
    (20, 120, 15),
    (24, 120, 15),
    (28, 120, 15),
]
NEUTRAL = {
    "aisle_alt_gain": 1.0, "aisle_alt_boost": 1.0, "loop_gain": 1.0,
    "main_aisle_gain": 1.0, "junction_penalty": 1.0, "station_in": 1.0,
    "station_out": 1.0, "wait_cost": 1.0,
    "aisle_period": 1, "aisle_phase": 0, "loop_dir": 0,
}


def measure(sim_engine, robots, orders, order_gap, seeds, cell, timeout_s):
    """조건 하나를 seed 별로 돌려 (초 리스트, KPI 리스트) 를 돌려준다."""
    path = write_theta(NEUTRAL)
    secs, kpis = [], []
    try:
        for seed in seeds:
            t0 = time.perf_counter()
            try:
                summary = run_once(sim_engine, path, robots, orders, seed,
                                   aisle_block=1, tag="measure",
                                   cell=cell, order_gap=order_gap,
                                   timeout_s=timeout_s)
            except SimFailed as exc:
                secs.append(time.perf_counter() - t0)
                kpis.append(None)
                print(f"    seed {seed}: 실패 — {exc}".replace("\n", " ")[:160])
                continue
            secs.append(time.perf_counter() - t0)
            kpis.append(summary["tasks_per_h"])
    finally:
        os.unlink(path)
    return secs, kpis


def budget_line(sec_per_run, seeds, trials):
    """trial 당 시간과 study 전체 시간을 사람이 읽는 문자열로."""
    per_trial = sec_per_run * seeds
    total_h = per_trial * trials / 3600.0
    return f"trial당 {per_trial:.0f} s / {trials} trial ≈ {total_h:.1f} 시간"


def main(argv=None):
    p = argparse.ArgumentParser(description="θ 탐색 예산 측정")
    p.add_argument("--sim-engine", default="/work/sim_engine", dest="sim_engine")
    p.add_argument("--seeds", default="42,43", help="쉼표 구분")
    # 계약 v2: 헤딩이 기본, 칸 모델이 --cell opt-in
    p.add_argument("--cell", action="store_true", help="칸 모델(점로봇)")
    p.add_argument("--timeout", type=int, default=600)
    p.add_argument("--trials", type=int, default=100, help="예산 환산에 쓸 trial 수")
    p.add_argument("--budget-seeds", type=int, default=3, dest="budget_seeds",
                   help="예산 환산에 쓸 시드 수 (측정 시드 수와 별개)")
    args = p.parse_args(argv)
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]

    model = "칸" if args.cell else "헤딩"
    import numpy
    print(f"환경: python {sys.version.split()[0]} / numpy {numpy.__version__}")
    print(f"모델: {model} · aisle_block=1 · flow=main · 중립 θ · 측정 시드 {seeds}\n")
    print(f"{'로봇':>4} {'주문':>5} {'간격':>4} {'평균 s':>8} {'최대 s':>8} "
          f"{'tasks/h':>9}  예산({args.budget_seeds}시드 × {args.trials} trial)")
    print("-" * 92)

    rows = []
    for robots, orders, gap in GRID:
        secs, kpis = measure(args.sim_engine, robots, orders, gap, seeds,
                             args.cell, args.timeout)
        ok = [k for k in kpis if k is not None]
        mean_s = statistics.fmean(secs)
        kpi_txt = f"{statistics.fmean(ok):.1f}" if ok else "실패"
        print(f"{robots:>4} {orders:>5} {gap:>4} {mean_s:>8.1f} {max(secs):>8.1f} "
              f"{kpi_txt:>9}  {budget_line(mean_s, args.budget_seeds, args.trials)}")
        rows.append((robots, orders, gap, mean_s, kpi_txt))
    return 0


if __name__ == "__main__":
    sys.exit(main())
