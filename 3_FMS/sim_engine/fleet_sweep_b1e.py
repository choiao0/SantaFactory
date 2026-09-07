# -*- coding: utf-8 -*-
# ============================================================
# B-1e 벤치마크 — A*(sim_v1) vs PIBT(sim_v2 --flow=v1compat) 정면 비교
# + 새 흐름(sim_v2 --flow=main) fleet 곡선
#
# 조건: 로봇 {2,3,4,6,8,10,12,16} × 시드 {42, 7}, 40주문, 통로차단 ON.
# v1compat은 rng 소비 순서까지 v1과 동일 → 두 엔진이 같은 주문 스트림 처리.
# 산출: results/b1e_sweep.csv, b1e_astar_vs_pibt.png,
#       results/fleet_sweep_v2_main.csv, fleet_sweep_v2_main.png
# 지위(2026-09-03): 이력 벤치마크. pibt_main 은 --fixed-homes 로 당시 구성(고정 홈 12칸)을 재현한다.
#       현재 기준선은 fleet_sweep_b0z.py (충전 존 기본, 헤딩 모델).
# ============================================================
import csv
import json
import os
import subprocess
import sys

PY = sys.executable
OUT = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(OUT, "results")
os.makedirs(RES, exist_ok=True)
ROBOTS = [2, 3, 4, 6, 8, 10, 12, 16]
SEEDS = [42, 7]
env = dict(os.environ, SIM_NO_PLOT="1", PYTHONIOENCODING="utf-8")


def run_one(script, n, seed, extra=()):
    r = subprocess.run([PY, os.path.join(OUT, script), "base", str(n), "40",
                        str(seed), "1", *extra],
                       capture_output=True, text=True, encoding="utf-8", env=env)
    line = next((ln for ln in r.stdout.splitlines()
                 if ln.startswith("[SUMMARY]")), None)
    assert line, f"실행 실패 {script} r{n} s{seed}:\n{r.stdout}\n{r.stderr}"
    return json.loads(line[len("[SUMMARY] "):])


CSV_PATH = os.path.join(RES, "b1e_sweep.csv")
if os.environ.get("SWEEP_PLOT_ONLY") and os.path.exists(CSV_PATH):
    # 기존 CSV에서 그래프만 재생성 (시뮬 재실행 없이)
    rows = []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            for k, v in r.items():
                if v != "" and k not in ("engine", "variant", "flow"):
                    r[k] = float(v)
            rows.append(r)
else:
    rows = []
    for engine, script, extra in [("astar_v1", "sim_v1_tasks.py", ()),
                                  ("pibt_v1compat", "sim_v2_tasks.py", ("--flow=v1compat",)),
                                  # 2026-09-03 충전 존이 main 기본값이 됨 → 이력 CSV 재현엔 고정 홈 명시
                                  ("pibt_main", "sim_v2_tasks.py", ("--flow=main", "--fixed-homes"))]:
        for n in ROBOTS:
            for seed in SEEDS:
                rec = run_one(script, n, seed, extra)
                rec["engine"] = engine
                rows.append(rec)
                print(f"  {engine:14s} r={n:2d} seed={seed:2d}: "
                      f"{rec['tasks_per_h']:6.1f} tasks/h, makespan {rec['makespan_steps']:5d}, "
                      f"lead {rec['lead_mean_s']:6.1f}s, util {rec['util']*100:3.0f}%")

    fields = sorted({k for r in rows for k in r})
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        wcsv = csv.DictWriter(f, fieldnames=fields)
        wcsv.writeheader()
        wcsv.writerows(rows)

# ------------------------------------------------------------
# 곡선 (시드 평균)
# ------------------------------------------------------------
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False


def series(engine, key):
    return [np.mean([r[key] for r in rows
                     if r["engine"] == engine and r["n_robots"] == n])
            for n in ROBOTS]


STYLE = {"astar_v1": ("#2980b9", "A* (v1)"),
         "pibt_v1compat": ("#e74c3c", "PIBT (v1compat)")}

fig, axes = plt.subplots(1, 3, figsize=(15, 4.6))
panels = [("tasks_per_h", "throughput [tasks/h]"),
          ("makespan_steps", "makespan [ticks]"),
          ("lead_mean_s", "lead time mean [s]")]
for ax, (key, label) in zip(axes, panels):
    for engine, (color, name) in STYLE.items():
        ax.plot(ROBOTS, series(engine, key), "o-", color=color, label=name, lw=2)
    ax.set_xlabel("n_robots")
    ax.set_title(label)
    ax.grid(alpha=0.3)
    ax.legend()
fig.suptitle("B-1e — A* vs PIBT, 동일 주문 스트림 (40 orders, aisle-block ON, "
             "uniform cost, mean of 2 seeds)", fontsize=11)
plt.tight_layout()
plt.savefig(os.path.join(RES, "b1e_astar_vs_pibt.png"), dpi=115)

fig, axes = plt.subplots(1, 3, figsize=(15, 4.6))
panels = [("tasks_per_h", "throughput [tasks/h]"),
          ("queue_mean_s", "dispatch queue mean [s]"),
          ("lead_mean_s", "lead time mean [s]")]
for ax, (key, label) in zip(axes, panels):
    ax.plot(ROBOTS, series("pibt_main", key), "o-", color="#27ae60", lw=2)
    ax.set_xlabel("n_robots")
    ax.set_title(label)
    ax.grid(alpha=0.3)
fig.suptitle("sim_v2 main flow — 입고 40 + 출고 40주문(통로 합치기), "
             "aisle-block ON, mean of 2 seeds", fontsize=11)
plt.tight_layout()
plt.savefig(os.path.join(RES, "fleet_sweep_v2_main.png"), dpi=115)
print("저장: results/b1e_sweep.csv, b1e_astar_vs_pibt.png, fleet_sweep_v2_main.png")
