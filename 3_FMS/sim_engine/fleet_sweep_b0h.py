# -*- coding: utf-8 -*-
# ============================================================
# B0′ 기준선 — 회전 포함(헤딩 모델) fleet 곡선, 칸 모델과 나란히
# (결정: docs/2026-09-02_Isaac회전충돌_격자유지_PIBT확장_결정.md §4-1 ⑤)
#
# B-1e(회전 0초 기준선)를 대체하는 새 기준선. 조건은 B-1e와 동일하게 맞춰
# 두 기준선을 직접 비교할 수 있게 한다:
#   로봇 {2,3,4,6,8,10,12,16} × 시드 {42, 7}, 40주문, 통로차단 ON, main 흐름,
#   uniform cost (θ 미적용).
# 두 계열:
#   cell    = sim_v2 --flow=main            (B-1e의 pibt_main과 동일 = 회전 0초)
#   heading = sim_v2 --flow=main --heading  (2칸 차체, 90° 회전 2틱, 후진, 스윙 예약)
# 산출: results/b0h_sweep.csv, b0h_cell_vs_heading.png, b0h_heading_cost.png
# 기존 B-1e 결과 파일은 건드리지 않는다 (이력 보존).
# 사용: python fleet_sweep_b0h.py     (헤딩 계열이 느려 ~15분)
#       SWEEP_PLOT_ONLY=1 python fleet_sweep_b0h.py   (CSV에서 그래프만)
# ============================================================
import csv
import json
import os
import subprocess
import sys
import time

PY = sys.executable
OUT = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(OUT, "results")
ROBOTS = [2, 3, 4, 6, 8, 10, 12, 16]
SEEDS = [42, 7]
N_ORDERS, AISLE_BLOCK = 40, 1
env = dict(os.environ, SIM_NO_PLOT="1", PYTHONIOENCODING="utf-8")
SERIES = [("cell", ("--flow=main",)), ("heading", ("--flow=main", "--heading"))]


def run_one(n, seed, extra):
    t0 = time.perf_counter()
    r = subprocess.run([PY, os.path.join(OUT, "sim_v2_tasks.py"), "b0h", str(n),
                        str(N_ORDERS), str(seed), str(AISLE_BLOCK), *extra],
                       capture_output=True, text=True, encoding="utf-8", env=env)
    line = next((ln for ln in r.stdout.splitlines() if ln.startswith("[SUMMARY]")), None)
    assert line, f"실행 실패 r{n} s{seed} {extra}:\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}"
    rec = json.loads(line[len("[SUMMARY] "):])
    rec["wall_s"] = round(time.perf_counter() - t0, 1)
    return rec


CSV_PATH = os.path.join(RES, "b0h_sweep.csv")
if os.environ.get("SWEEP_PLOT_ONLY") and os.path.exists(CSV_PATH):
    rows = []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            for k, v in r.items():
                if v != "" and k not in ("engine", "variant", "flow"):
                    r[k] = float(v)
            rows.append(r)
else:
    rows = []
    for engine, extra in SERIES:
        for n in ROBOTS:
            for seed in SEEDS:
                rec = run_one(n, seed, extra)
                rec["engine"] = engine
                rows.append(rec)
                more = (f", rot {rec['rot_steps']}, rev {rec['rev_steps']}, "
                        f"replan {rec['replan_steps']}" if engine == "heading" else "")
                print(f"  {engine:8s} r={n:2d} seed={seed:2d}: {rec['tasks_per_h']:6.1f} tasks/h, "
                      f"makespan {rec['makespan_steps']:5d}, lead {rec['lead_mean_s']:6.1f}s, "
                      f"util {rec['util']*100:3.0f}%, turns/task {rec['turns_per_task']:4.1f}"
                      f"{more} ({rec['wall_s']}s)", flush=True)
    fields = sorted({k for r in rows for k in r})
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

# ------------------------------------------------------------
# 그래프 (시드 평균)
# ------------------------------------------------------------
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False


def series(engine, key):
    return [np.mean([float(r[key]) for r in rows
                     if r["engine"] == engine and int(r["n_robots"]) == n and r.get(key, "") != ""])
            for n in ROBOTS]


STYLE = {"cell": ("#7f8c8d", "칸 모델 (회전 0초, B-1e 기준선)"),
         "heading": ("#c0392b", "헤딩 모델 (2칸 차체·회전 2틱, B0′)")}

fig, axes = plt.subplots(1, 3, figsize=(15, 4.6))
for ax, (key, label) in zip(axes, [("tasks_per_h", "throughput [tasks/h]"),
                                   ("makespan_steps", "makespan [ticks]"),
                                   ("lead_mean_s", "lead time mean [s]")]):
    for engine, (color, name) in STYLE.items():
        ax.plot(ROBOTS, series(engine, key), "o-", color=color, label=name, lw=2)
    ax.set_xlabel("n_robots")
    ax.set_title(label)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
fig.suptitle("B0′ — 칸 모델 vs 헤딩 모델, main 흐름 (40 orders, aisle-block ON, "
             "uniform cost, mean of 2 seeds)", fontsize=11)
plt.tight_layout()
plt.savefig(os.path.join(RES, "b0h_cell_vs_heading.png"), dpi=115)

fig, axes = plt.subplots(1, 3, figsize=(15, 4.6))
n_tasks = [np.mean([float(r["tasks_per_h"]) * float(r["makespan_steps"]) / 3600
                    for r in rows if r["engine"] == "heading" and int(r["n_robots"]) == n])
           for n in ROBOTS]
for ax, (key, label) in zip(axes, [("rot_steps", "회전 소모 틱 / 태스크"),
                                   ("rev_steps", "후진 칸 / 태스크"),
                                   ("replan_steps", "재계획 틱 / 태스크")]):
    ax.plot(ROBOTS, np.array(series("heading", key)) / np.array(n_tasks), "o-",
            color="#c0392b", lw=2)
    ax.set_xlabel("n_robots")
    ax.set_title(label)
    ax.grid(alpha=0.3)
fig.suptitle("B0′ 헤딩 모델 — 회전·후진·재계획 비용 (태스크당, mean of 2 seeds)", fontsize=11)
plt.tight_layout()
plt.savefig(os.path.join(RES, "b0h_heading_cost.png"), dpi=115)
print("저장: results/b0h_sweep.csv, b0h_cell_vs_heading.png, b0h_heading_cost.png")
