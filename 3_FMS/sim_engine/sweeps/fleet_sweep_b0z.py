# -*- coding: utf-8 -*-
# ============================================================
# B0″ 기준선 — 동기화 맵(3_FMS/map, 벽있음 ∪ v5.8) + 충전 존(기본) + TURN_TICKS=1, 칸 vs 헤딩 fleet 곡선
# (결정·구현: docs/맵_충전존.md#충전-존-결정, 결과: docs/θ_경로_기준선.md#기준선-계보)
#
# B0′(fleet_sweep_b0h — -152에서 삭제, CSV는 results/archive/: 8/31 맵, 고정 홈 12칸, 회전 2틱)를 대체한다. 조건은 B-1e/B0′와 동일:
#   로봇 {2,3,4,6,8,10,12,16} × 시드 {42, 7}, 40주문(+입고 40), 통로차단 ON, main 흐름,
#   uniform cost (θ 미적용).
# 두 계열:
#   cell    = sim_v2 --flow=main --cell     (칸 모델, 회전 0초) — 존 기본. 계약 v2부터 --cell 이 opt-in
#   heading = sim_v2 --flow=main --heading  (2칸 차체, 90° 회전 1틱, 후진, 스윙 예약) — 존 기본, 계약 v2 기본 모델
# 그래프에는 B0′ CSV(results/archive/b0h_sweep.csv, 레거시 정리 -152로 이동)가 있으면 점선으로 겹쳐 그린다:
#   cell 계열의 차이 = 존 효과(홈 위치만 다름), heading 계열의 차이 = 존 + 회전 2틱→1틱.
# 산출: results/b0z_sweep.csv, b0z_cell_vs_heading.png, b0z_zone_metrics.png
# 기존 결과 파일은 건드리지 않는다 (이력 보존).
# 사용: python sweeps/fleet_sweep_b0z.py     (헤딩 계열이 느려 ~10분)
#       SWEEP_PLOT_ONLY=1 python sweeps/fleet_sweep_b0z.py   (CSV에서 그래프만)
#       SWEEP_OUT=b0z_sweep_v4.csv python sweeps/fleet_sweep_b0z.py
#           — **별도 CSV/PNG** 로 (기본 b0z_sweep.csv 는 동일성 검사 기준이라 덮어쓰지 않는다).
#             fleet_sweep_load.py 의 SWEEP_OUT 과 같은 규약이다. 계약이 바뀌어 결과가 달라질 때
#             쓴다 — v3(-177) 은 손으로 복사했고, v4(-194) 부터 이 인자로 뜬다. PNG 는 b0z_*<접미>.png.
# ============================================================
import csv
import json
import os
import subprocess
import sys
import time

ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ENGINE_DIR)
PY = sys.executable
OUT = ENGINE_DIR
RES = os.path.join(OUT, "results")
ROBOTS = [2, 3, 4, 6, 8, 10, 12, 16]
SEEDS = [42, 7]
N_ORDERS, AISLE_BLOCK = 40, 1
env = dict(os.environ, SIM_NO_PLOT="1", PYTHONIOENCODING="utf-8")
SERIES = [("cell", ("--flow=main", "--cell")), ("heading", ("--flow=main", "--heading"))]
# zone_peak 는 2026-09-04 zone_occ_mean/p90(존 체류 분포)으로 교체됨 — CSV 이력 호환을 위해 둘 다 허용
OCC_KEY = "zone_occ_mean"


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


CSV_NAME = os.environ.get("SWEEP_OUT", "b0z_sweep.csv")
STEM = os.path.splitext(os.path.basename(CSV_NAME))[0]
TAG = STEM[len("b0z_sweep"):] if STEM.startswith("b0z_sweep") else "_" + STEM   # b0z_sweep_v4 → "_v4"
CSV_PATH = os.path.join(RES, os.path.basename(CSV_NAME))
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
                      f"retarget {rec['zone_retargets']:2d} occ {rec.get(OCC_KEY, rec.get('zone_peak', 0)):4.1f}"
                      f"{more} ({rec['wall_s']}s)", flush=True)
    fields = sorted({k for r in rows for k in r})
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

B0H_PATH = os.path.join(RES, "archive", "b0h_sweep.csv")
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
plt.savefig(os.path.join(RES, f"b0z_cell_vs_heading{TAG}.png"), dpi=115)

fig, axes = plt.subplots(1, 4, figsize=(18, 4.4))
for ax, (key, label) in zip(axes, [("zone_wait_steps", "존 안 복귀 대기 [틱]"),
                                   ("zone_retargets", "복귀 목표 재선택 [회]"),
                                   ("idle_moves", "비임무 밀림 이동 [칸]"),
                                   (OCC_KEY, "존 체류 평균 [대]")]):
    if key == OCC_KEY and not any(OCC_KEY in r for r in rows):   # 구 CSV(zone_peak)면 그 열로 대체
        key, label = "zone_peak", "동시 주차 최대 [대] (구 지표)"
    for engine, (color, name) in STYLE.items():
        ax.plot(ROBOTS, series(rows, engine, key), "o-", color=color, label=name, lw=2)
    if key in (OCC_KEY, "zone_peak"):
        ax.plot(ROBOTS, ROBOTS, ":", color="k", alpha=0.4, label="= n_robots")
    ax.set_xlabel("n_robots")
    ax.set_title(label)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=7)
fig.suptitle("B0″ 충전 존 지표 (구현 설계 §4, mean of 2 seeds)", fontsize=11)
plt.tight_layout()
plt.savefig(os.path.join(RES, f"b0z_zone_metrics{TAG}.png"), dpi=115)
print(f"저장: results/{STEM}.csv, b0z_cell_vs_heading{TAG}.png, b0z_zone_metrics{TAG}.png")
