"""KPI — sim_engine/cli/report.py 의 고정 시간(lifelong) 산식을 그대로, 견적 워커 to_kpi 의 14개 키로 (SIM_VERIFY_CONTRACT §3).

report() 는 argv 네임스페이스·stdout 에 묶여 있어 여기서 같은 식을 다시 쓴다. 분모는 실제로 돈 틱 수 t_end
(docs/커널_시뮬_구조.md "처리량 분모는 T"), 리드타임 표본은 t_end 안에 완료된 태스크만. test_kernel_planner 가 report() 와 대조한다.
"""
from __future__ import annotations

import numpy as np

DT = 1.0                     # 기본 틱 길이 [초] (cli/common.DT). 실행 값은 KernelPlanner.dt (-116·-194)
CELL_M = 1.0                 # 격자 1칸 [m] — map_loader.CELL_M 과 같은 값 (주행거리 환산용)


def _mean(x) -> float:
    return float(x.mean()) if len(x) else 0.0


def _p90(x) -> float:
    return float(np.percentile(x, 90)) if len(x) else 0.0


def summary(kernel, stream, n_robots: int, t_end: int, dt: float = DT) -> dict:
    """report() 의 SUMMARY 중 KPI 로 가는 키 (같은 반올림). dt = 틱 길이[초] (report 의 a.dt)."""
    t_end = max(int(t_end), 1)
    tasks_done = kernel.tasks_done
    n_tasks = len(tasks_done)
    lat_total = np.array([tk["completed"] - tk["created"] for tk in tasks_done]) * dt
    lat_queue = np.array([tk["assigned"] - tk["created"] for tk in tasks_done]) * dt
    sim_hours = t_end * dt / 3600
    tot = kernel.totals()
    busy_v1 = tot["drive"] + 2 * tot["wait"]
    util_incl = (tot["drive"] + tot["wait"] + tot["svc"] + tot["rot"]) / (n_robots * t_end)
    conflict_wait = tot["wait"] / max(busy_v1, 1)
    orders_done = sum(1 for od in stream.orders.values() if od["completed"] is not None)
    n_in = sum(1 for tk in tasks_done if tk["kind"] == "in")
    charging = kernel.battery_summary()["charging_steps"] if getattr(kernel, "battery", False) else 0
    return dict(n_orders=int(stream.n_orders), orders_done=int(orders_done), inbound_total=int(stream.n_inbound),
                tasks_in=int(n_in), tasks_out=int(n_tasks - n_in), open_tasks=int(kernel.n_submitted - n_tasks),
                makespan_steps=int(t_end),
                tasks_per_h=round(n_tasks / sim_hours, 1), orders_per_h=round(orders_done / sim_hours, 1),
                lead_mean_s=round(_mean(lat_total), 1), lead_p90_s=round(_p90(lat_total), 1),
                queue_mean_s=round(_mean(lat_queue), 1),
                util_incl_service=round(float(util_incl), 3), conflict_wait=round(float(conflict_wait), 4),
                # 주행거리는 **밟은 칸**이다. drive 는 주행 틱이라 전진이 여러 틱이 된 뒤로
                # 칸 수와 다르다 (-194) — 예전엔 1칸 = 1틱이라 같은 값이었다. cli/report.py 와 같은 산식.
                distance_m=int(tot["cells"] * CELL_M), charging_steps=int(charging))


def des_block(s: dict, dt: float = DT) -> dict:
    """SUMMARY → 견적 워커 to_kpi 와 같은 키 (infra/worker/estimate_worker.py to_kpi). dt = 워커의 SUMMARY dt_s."""
    return dict(orders_total=s["n_orders"], orders_completed=s["orders_done"],
                inbound_total=s["inbound_total"], inbound_completed=s["tasks_in"],
                makespan_s=int(round(s["makespan_steps"] * dt)),
                lead_time_mean_s=s["lead_mean_s"], lead_time_p90_s=s["lead_p90_s"], queue_time_mean_s=s["queue_mean_s"],
                throughput_orders_per_h=s["orders_per_h"], throughput_tasks_per_h=s["tasks_per_h"],
                amr_utilization=s["util_incl_service"], conflict_wait_ratio=s["conflict_wait"],
                distance_total_m=s["distance_m"], charge_downtime_s=int(round(s["charging_steps"] * dt)))
