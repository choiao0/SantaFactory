# -*- coding: utf-8 -*-
# ============================================================
# Fleet Sweep (빌드 순서 5단계) — 확정 맵 기준 대수 스윕
#
# 조건: 로봇 {2,3,4,6,8,10,12} x 시드 {42, 7}, 단일 확정 맵(occupancy_grid.npy)
#       통로차단 ON(보수적 초기실험 방침), 수요 고정(40주문 = 120태스크,
#       도착 간격 평균 50스텝). θ 미구현 → 전 간선 1.0 uniform.
# 산출: fleet_sweep_results.csv (SimRun 레코드), fleet_sweep.png (곡선)
# ============================================================
import csv
import json
import os
import subprocess
import sys

PY = sys.executable
OUT = os.path.dirname(os.path.abspath(__file__))
SIM = os.path.join(OUT, "sim_v1_tasks.py")
RESULTS_DIR = os.path.join(OUT, "results")
os.makedirs(RESULTS_DIR, exist_ok=True)
ROBOTS = [2, 3, 4, 6, 8, 10, 12]
VARIANT = "base"
SEEDS = [42, 7]

env = dict(os.environ, SIM_NO_PLOT="1", PYTHONIOENCODING="utf-8")
rows = []
for n in ROBOTS:
    for seed in SEEDS:
        r = subprocess.run(
            [PY, SIM, VARIANT, str(n), "40", str(seed), "1"],
            capture_output=True, text=True, encoding="utf-8", env=env)
        line = next((ln for ln in r.stdout.splitlines()
                     if ln.startswith("[SUMMARY]")), None)
        assert line, f"실행 실패 r{n} s{seed}:\n{r.stdout}\n{r.stderr}"
        rec = json.loads(line[len("[SUMMARY] "):])
        rows.append(rec)
        print(f"  r={n:2d} seed={seed:2d}: "
              f"{rec['tasks_per_h']:6.1f} tasks/h, lead {rec['lead_mean_s']:6.1f}s, "
              f"util {rec['util']*100:3.0f}%, 충돌대기 {rec['conflict_wait']*100:4.1f}%")

with open(os.path.join(RESULTS_DIR, "fleet_sweep_results.csv"), "w", newline="",
          encoding="utf-8") as f:
    wcsv = csv.DictWriter(f, fieldnames=rows[0].keys())
    wcsv.writeheader()
    wcsv.writerows(rows)

# ------------------------------------------------------------
# 곡선: 시드 평균, 처리량 / 리드타임 / 충돌대기
# ------------------------------------------------------------
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def series(key):
    vals = []
    for n in ROBOTS:
        v = [r[key] for r in rows if r["n_robots"] == n]
        vals.append(np.mean(v))
    return vals


fig, axes = plt.subplots(1, 3, figsize=(15, 4.6))
panels = [("tasks_per_h", "throughput [tasks/h]"),
          ("lead_mean_s", "lead time mean [s]"),
          ("conflict_wait", "conflict-wait ratio")]
for ax, (key, label) in zip(axes, panels):
    ax.plot(ROBOTS, series(key), "o-", color="#2980b9", lw=2)
    ax.set_xlabel("n_robots")
    ax.set_title(label)
    ax.grid(alpha=0.3)
axes[2].yaxis.set_major_formatter(lambda v, _: f"{v*100:.0f}%")
fig.suptitle("Fleet Sweep — fixed demand 40 orders (120 tasks), aisle-block ON, "
             "uniform edge cost (no θ), mean of 2 seeds", fontsize=11)
plt.tight_layout()
plt.savefig(os.path.join(RESULTS_DIR, "fleet_sweep.png"), dpi=115)
print("저장: fleet_sweep_results.csv / fleet_sweep.png")
