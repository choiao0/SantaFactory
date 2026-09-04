# -*- coding: utf-8 -*-
# ============================================================
# B0″ 기준선 — 동기화 맵(3_FMS/map, 벽있음 ∪ v5.8) + 충전 존(기본) + TURN_TICKS=1, 칸 vs 헤딩 fleet 곡선
# (결정: docs/2026-09-03_충전존_결정.md, 구현: docs/2026-09-03_충전존_구현_설계.md, 결과: docs/2026-09-03_B0z_충전존_기준선.md)
#
# B0′(fleet_sweep_b0h: 8/31 맵, 고정 홈 12칸, 회전 2틱)를 대체한다. 조건은 B-1e/B0′와 동일:
#   로봇 {2,3,4,6,8,10,12,16} × 시드 {42, 7}, 40주문(+입고 40), 통로차단 ON, main 흐름,
#   uniform cost (θ 미적용).
# 두 계열:
#   cell    = sim_v2 --flow=main            (칸 모델, 회전 0초) — 존 기본
#   heading = sim_v2 --flow=main --heading  (2칸 차체, 90° 회전 1틱, 후진, 스윙 예약) — 존 기본
# 그래프에는 B0′ CSV(results/b0h_sweep.csv)가 있으면 점선으로 겹쳐 그린다:
#   cell 계열의 차이 = 존 효과(홈 위치만 다름), heading 계열의 차이 = 존 + 회전 2틱→1틱.
# 산출: results/b0z_sweep.csv, b0z_cell_vs_heading.png, b0z_zone_metrics.png
# 기존 결과 파일은 건드리지 않는다 (이력 보존).
# 사용: python fleet_sweep_b0z.py     (헤딩 계열이 느려 ~10분)
#       SWEEP_PLOT_ONLY=1 python fleet_sweep_b0z.py   (CSV에서 그래프만)
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
ZONE_KEYS = ("zone_wait_steps", "zone_retargets", "zone_degraded", "zone_peak", "idle_moves")


def run_one(n, seed, extra):
    t0 = time.perf_counter()
    r = subprocess.run([PY, os.path.join(OUT, "sim_v2_tasks.py"), "b0z", str(n),
                        str(N_ORDERS), str(seed), str(AISLE_BLOCK), *extra],
                       capture_output=True, text=True, encoding="utf-8", env=env)
    line = next((ln for ln in r.stdout.splitlines() if ln.startswith("[SUMMARY]")), None)
    assert line, f"실행 실패 r{n} s{seed} {extra}:\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}"
    rec = json.loads(line[len("[SUMMARY] "):])
    assert rec.get("zone") == 1, f"존이 꺼져 있음 r{n} s{seed} {extra}"
    rec["wall_s"] = round(time.perf_counter() - t0, 1)
    return rec


def read_csv(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            for k, v in r.items():
                if v != "" and k not in ("engine", "variant", "flow"):
                    r[k] = float(v)
            rows.append(r)
    return rows


CSV_PATH = os.path.join(RES, "b0z_sweep.csv")
if os.environ.get("SWEEP_PLOT_ONLY") and os.path.exists(CSV_PATH):
    rows = read_csv(CSV_PATH)
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
                      f"util {rec['util']*100:3.0f}%, zone wait {rec['zone_wait_steps']:4d} "
                      f"retarget {rec['zone_retargets']:2d} peak {rec['zone_peak']:2d}"
                      f"{more} ({rec['wall_s']}s)", flush=True)
    fields = sorted({k for r in rows for k in r})
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

B0H_PATH = os.path.join(RES, "b0h_sweep.csv")
ref_rows = read_csv(B0H_PATH) if os.path.exists(B0H_PATH) else []

# ------------------------------------------------------------
# 그래프 (시드 평균)
# ------------------------------------------------------------
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False


def series(data, engine, key):
    return [np.mean([float(r[key]) for r in data
                     if r["engine"] == engine and int(r["n_robots"]) == n and r.get(key, "") != ""])
            for n in ROBOTS]


STYLE = {"cell": ("#7f8c8d", "칸 모델 (회전 0초)"),
         "heading": ("#c0392b", "헤딩 모델 (2칸 차체·회전 1틱)")}

fig, axes = plt.subplots(1, 3, figsize=(15, 4.6))
for ax, (key, label) in zip(axes, [("tasks_per_h", "throughput [tasks/h]"),
                                   ("makespan_steps", "makespan [ticks]"),
                                   ("lead_mean_s", "lead time mean [s]")]):
    for engine, (color, name) in STYLE.items():
        ax.plot(ROBOTS, series(rows, engine, key), "o-", color=color, label=f"{name} — 존 (B0″)", lw=2)
        if ref_rows:
            ax.plot(ROBOTS, series(ref_rows, engine, key), "x--", color=color, alpha=0.55,
                    label=f"{name.split(' (')[0]} — 고정 홈 (B0′)", lw=1.2)
    ax.set_xlabel("n_robots")
    ax.set_title(label)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=7)
fig.suptitle("B0″ — 동기화 맵(벽있음 ∪ v5.8) + 충전 존 기본, 칸 vs 헤딩, main 흐름 (40 orders, aisle-block ON, "
             "uniform cost, mean of 2 seeds). 점선 = B0′(8/31 맵, 고정 홈 12칸, 회전 2틱)", fontsize=10)
plt.tight_layout()
plt.savefig(os.path.join(RES, "b0z_cell_vs_heading.png"), dpi=115)

fig, axes = plt.subplots(1, 4, figsize=(18, 4.4))
for ax, (key, label) in zip(axes, [("zone_wait_steps", "존 안 복귀 대기 [틱]"),
                                   ("zone_retargets", "복귀 목표 재선택 [회]"),
                                   ("idle_moves", "비임무 밀림 이동 [칸]"),
                                   ("zone_peak", "동시 주차 최대 [대]")]):
    for engine, (color, name) in STYLE.items():
        ax.plot(ROBOTS, series(rows, engine, key), "o-", color=color, label=name, lw=2)
    if key == "zone_peak":
        ax.plot(ROBOTS, ROBOTS, ":", color="k", alpha=0.4, label="= n_robots")
    ax.set_xlabel("n_robots")
    ax.set_title(label)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=7)
fig.suptitle("B0″ 충전 존 지표 (구현 설계 §4, mean of 2 seeds)", fontsize=11)
plt.tight_layout()
plt.savefig(os.path.join(RES, "b0z_zone_metrics.png"), dpi=115)
print("저장: results/b0z_sweep.csv, b0z_cell_vs_heading.png, b0z_zone_metrics.png")
