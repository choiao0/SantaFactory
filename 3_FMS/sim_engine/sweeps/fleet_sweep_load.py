# -*- coding: utf-8 -*-
# ============================================================
# 고부하 스윕 — 수요 제약 밖에서 무릎·존 정체 판정 (2026-09-04, S15P21A106-135)
# (결과: docs/2026-09-04_고부하_무릎_판정.md. 기준선 B0″: docs/2026-09-03_B0z_충전존_기준선.md)
#
# B0″까지의 스윕은 주문 40건·도착 간격 50틱이라 8~10대부터 "일감이 먼저 떨어져" 처리량이 평평해졌다
# (함정 4). 여기서는 도착 간격을 줄여 부하를 올린다 (--order-gap):
#   부하 L1: 80주문, 간격 25틱  (수요 ≈ 144 주문/h ≈ B0″ 포화점 62의 2.3배)
#   부하 L2: 120주문, 간격 15틱 (수요 ≈ 240 주문/h)
# 로봇 {8,12,16,20,24,28} — 28 = 충전 존 간격-2 배치 용량 상한(make_homes_zone). 시드 {42, 7}.
# 두 계열: cell(--cell) / heading(기본, --heading 은 호환 표기) — 둘 다 충전 존 기본, 동기화 맵, TURN_TICKS=1.
# 지표: 처리량·리드타임 + 존 지표(복귀 대기, 재선택, 예약 무시, 체류 평균/p90, 비임무 밀림).
# 산출: results/load_sweep.csv, load_throughput.png, load_zone.png
# 사용: python sweeps/fleet_sweep_load.py                 (헤딩 28대·L2 가 실행당 1~2분, 전체 30분 안팎)
#       SWEEP_PLOT_ONLY=1 python sweeps/fleet_sweep_load.py
#       SWEEP_LOADS=L1 python sweeps/fleet_sweep_load.py   (부하 하나만)
#       SWEEP_SEEDS=101,102,103 SWEEP_OUT=load_sweep_eval.csv python sweeps/fleet_sweep_load.py
#           — 다른 시드 집합을 **별도 CSV/PNG** 로 (기본 load_sweep.csv 는 동일성 검사 기준이라 덮어쓰지 않는다).
#             θ 평가 시드 후보 기준선용 (2026-09-06, -145 후속; θ감도 실험 §6-3 미합의 항목). PNG 는 load_throughput<접미>.png 식.
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
ROBOTS = [8, 12, 16, 20, 24, 28]
SEEDS = [int(x) for x in os.environ["SWEEP_SEEDS"].split(",")] if os.environ.get("SWEEP_SEEDS") else [42, 7]
AISLE_BLOCK = 1
LOADS = {"L1": (80, 25), "L2": (120, 15)}          # name -> (n_orders, order_gap)
if os.environ.get("SWEEP_LOADS"):
    LOADS = {k: v for k, v in LOADS.items() if k in os.environ["SWEEP_LOADS"].split(",")}
SERIES = [("cell", ("--flow=main", "--cell")), ("heading", ("--flow=main", "--heading"))]
env = dict(os.environ, SIM_NO_PLOT="1", PYTHONIOENCODING="utf-8")


def run_one(n, n_orders, gap, seed, extra):
    t0 = time.perf_counter()
    r = subprocess.run([PY, os.path.join(OUT, "sim_v2_tasks.py"), "load", str(n), str(n_orders),
                        str(seed), str(AISLE_BLOCK), f"--order-gap={gap}", *extra],
                       capture_output=True, text=True, encoding="utf-8", env=env)
    line = next((ln for ln in r.stdout.splitlines() if ln.startswith("[SUMMARY]")), None)
    if line is None:
        # STALL(계약 §3, exit 1) 은 정보다 — 스윕을 죽이지 말고 행에 stall=1 로 남기고 덤프는 results/stall_<...>.txt 에 보관 (2026-09-06).
        stall = next((ln for ln in r.stdout.splitlines() if ln.startswith("[STALL]")), None)
        assert stall, f"실행 실패 r{n} o{n_orders} g{gap} s{seed} {extra}:\n{r.stdout[-3000:]}\n{r.stderr[-2000:]}"
        dump = os.path.join(RES, f"stall_load_r{n}_o{n_orders}_g{gap:g}_s{seed}_{'cell' if '--cell' in extra else 'heading'}.txt")
        with open(dump, "w", encoding="utf-8") as f:
            f.write(r.stdout + r.stderr)
        print(f"  [STALL] r={n} seed={seed} gap={gap}: {stall[:60]} → {os.path.basename(dump)}", flush=True)
        return dict(variant="load", n_robots=n, n_orders=n_orders, seed=seed, aisle_block=AISLE_BLOCK, flow="main",
                    order_gap=float(gap), stall=1, stall_t=int(stall.split("t=")[1].split(",")[0]),
                    wall_s=round(time.perf_counter() - t0, 1))
    rec = json.loads(line[len("[SUMMARY] "):])
    rec["wall_s"] = round(time.perf_counter() - t0, 1)
    return rec


def read_csv(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            for k, v in r.items():
                if v != "" and k not in ("engine", "variant", "flow", "load"):
                    r[k] = float(v)
            rows.append(r)
    return rows


CSV_NAME = os.environ.get("SWEEP_OUT", "load_sweep.csv")
STEM = os.path.splitext(os.path.basename(CSV_NAME))[0]
TAG = STEM[len("load_sweep"):] if STEM.startswith("load_sweep") else "_" + STEM     # load_sweep_eval → "_eval"
CSV_PATH = os.path.join(RES, os.path.basename(CSV_NAME))
if os.environ.get("SWEEP_PLOT_ONLY") and os.path.exists(CSV_PATH):
    rows = read_csv(CSV_PATH)
else:
    rows = []
    for load, (n_orders, gap) in LOADS.items():
        for engine, extra in SERIES:
            for n in ROBOTS:
                for seed in SEEDS:
                    rec = run_one(n, n_orders, gap, seed, extra)
                    rec["engine"], rec["load"] = engine, load
                    rows.append(rec)
                    if rec.get("stall"):
                        continue
                    more = (f", rot {rec['rot_steps']}, rev {rec['rev_steps']}, replan {rec['replan_steps']}"
                            if engine == "heading" else "")
                    print(f"  {load} {engine:8s} r={n:2d} seed={seed:2d}: {rec['tasks_per_h']:6.1f} tasks/h "
                          f"({rec['orders_per_h']:5.1f} orders/h), makespan {rec['makespan_steps']:5d}, "
                          f"lead {rec['lead_mean_s']:6.1f}s, util {rec['util']*100:3.0f}%, "
                          f"zone wait {rec['zone_wait_steps']:4d} retarget {rec['zone_retargets']:2d} "
                          f"occ {rec['zone_occ_mean']:4.1f}{more} ({rec['wall_s']}s)", flush=True)
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
loads = [k for k in LOADS if any(r["load"] == k for r in rows)]
N_STALL = sum(1 for r in rows if str(r.get("stall", "")) not in ("", "0", "0.0"))


def series(load, engine, key):
    return [np.mean([float(r[key]) for r in rows
                     if r["load"] == load and r["engine"] == engine and int(r["n_robots"]) == n
                     and r.get(key, "") != ""]) for n in ROBOTS]


STYLE = {"cell": ("#7f8c8d", "칸 모델"), "heading": ("#c0392b", "헤딩 모델")}
LS = {"L1": "-", "L2": "--"}

fig, axes = plt.subplots(1, 3, figsize=(15.5, 4.8))
for ax, (key, label) in zip(axes, [("tasks_per_h", "throughput [tasks/h]"),
                                   ("lead_mean_s", "lead time mean [s]"),
                                   ("util", "util (v1 호환)")]):
    for load in loads:
        for engine, (color, name) in STYLE.items():
            ax.plot(ROBOTS, series(load, engine, key), "o" + LS[load], color=color, lw=2,
                    label=f"{name} · {load} ({LOADS[load][0]}주문, 간격 {LOADS[load][1]}틱)")
    ax.set_xlabel("n_robots")
    ax.set_title(label)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=7)
SEED_NOTE = f"mean of {len(SEEDS)} seeds" + ("" if SEEDS == [42, 7] else f" {SEEDS}") + (f", STALL {N_STALL}런 제외" if N_STALL else "")
fig.suptitle(f"고부하 스윕 — 동기화 맵, 충전 존 기본, TURN_TICKS=1, aisle-block ON, uniform cost ({SEED_NOTE})",
             fontsize=10)
plt.tight_layout()
plt.savefig(os.path.join(RES, f"load_throughput{TAG}.png"), dpi=115)

fig, axes = plt.subplots(1, 4, figsize=(19, 4.5))
for ax, (key, label) in zip(axes, [("zone_wait_steps", "존 안 복귀 대기 [틱]"),
                                   ("zone_retargets", "복귀 목표 재선택 [회]"),
                                   ("zone_occ_mean", "존 체류 평균 [대]"),
                                   ("idle_moves", "비임무 밀림 이동 [칸]")]):
    for load in loads:
        for engine, (color, name) in STYLE.items():
            ax.plot(ROBOTS, series(load, engine, key), "o" + LS[load], color=color, lw=2,
                    label=f"{name} · {load}")
    if key == "zone_occ_mean":
        ax.plot(ROBOTS, ROBOTS, ":", color="k", alpha=0.35, label="= n_robots")
    ax.set_xlabel("n_robots")
    ax.set_title(label)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=7)
fig.suptitle(f"고부하 스윕 — 충전 존 지표 ({SEED_NOTE})", fontsize=11)
plt.tight_layout()
plt.savefig(os.path.join(RES, f"load_zone{TAG}.png"), dpi=115)
print(f"저장: results/{os.path.basename(CSV_PATH)}, load_throughput{TAG}.png, load_zone{TAG}.png")
