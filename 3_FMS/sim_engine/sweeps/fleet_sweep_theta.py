# -*- coding: utf-8 -*-
# ============================================================
# B-5: θ 적용 Fleet Sweep — 절감 대수 확정 + "θ 한 벌로 충분한가" (2026-09-07, S15P21A106-149)
# (설계·결과: docs/θ_경로_기준선.md#b-5-격자와-판정-규칙)
#
# 격자: 로봇 {8,10,12,14,16,18,20,21,22,23,24,26,28} × 부하 {L1: 80주문/25틱, L2: 120주문/15틱}
#       × θ 조건 {neutral, theta_n(최근접 대수 θ, 동률 → 큰 쪽), theta_24(24대 θ 고정)} × 평가 시드 {101,103,104} (계약 v2.3 §5)
# 모델: 헤딩 기본 + 충전 존 기본 + aisle_block=1. θ 파일: ../infra/out/theta_wallA_r{8,12,16,20,24,28}_g15.json (A트랙 -142, 읽기만).
# 산출: results/theta_sweep.csv, theta_sweep_throughput.png, theta_sweep_gain.png, theta_sweep_cross.csv
# 사용: python sweeps/fleet_sweep_theta.py                       (234런, 약 20분)
#       SWEEP_PLOT_ONLY=1 python sweeps/fleet_sweep_theta.py     (CSV 로 그래프·교차표만)
#       SWEEP_ROBOTS=20,24 SWEEP_SEEDS=101 SWEEP_LOADS=L2 SWEEP_OUT=theta_sweep_smoke.csv python sweeps/fleet_sweep_theta.py   (배관 확인)
# ============================================================
import math
import os
import sys

ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ENGINE_DIR)

import numpy as np

from _common import (RES_DIR, env_list, is_stall, mean_series, out_paths, read_csv, run_sim,
                     setup_plt, spread_series, values, write_csv)

ROBOTS = env_list("SWEEP_ROBOTS", [8, 10, 12, 14, 16, 18, 20, 21, 22, 23, 24, 26, 28])
SEEDS = env_list("SWEEP_SEEDS", [101, 103, 104])
LOADS = {"L1": (80, 25), "L2": (120, 15)}                     # name -> (n_orders, order_gap)
if os.environ.get("SWEEP_LOADS"):
    LOADS = {k: v for k, v in LOADS.items() if k in os.environ["SWEEP_LOADS"].split(",")}
AISLE_BLOCK = 1
THETA_DIR = os.path.normpath(os.path.join(ENGINE_DIR, "..", "infra", "out"))
THETA_ROBOTS = [8, 12, 16, 20, 24, 28]
FIXED_THETA_N = 24
CONDS = ["neutral", "theta_n", "theta_24"]


def theta_file(n):
    """최근접 대수의 θ, 동률이면 큰 쪽 (설계 §3). 10→12, 14→16, 18→20, 21→20, 22→24, 23→24, 26→28."""
    best = min(THETA_ROBOTS, key=lambda k: (abs(k - n), -k))
    return f"theta_wallA_r{best}_g15.json"


def extra_for(cond, n):
    if cond == "neutral":
        return (), ""
    name = theta_file(n) if cond == "theta_n" else f"theta_wallA_r{FIXED_THETA_N}_g15.json"
    path = os.path.join(THETA_DIR, name)
    assert os.path.exists(path), f"θ 파일 없음: {path}"
    return (f"--theta={path}",), name


CSV_PATH, TAG = out_paths("theta_sweep.csv", "theta_sweep")

if os.environ.get("SWEEP_PLOT_ONLY") and os.path.exists(CSV_PATH):
    rows = read_csv(CSV_PATH)
else:
    rows = []
    total = len(LOADS) * len(CONDS) * len(ROBOTS) * len(SEEDS)
    k = 0
    for load, (n_orders, gap) in LOADS.items():
        for cond in CONDS:
            for n in ROBOTS:
                for seed in SEEDS:
                    k += 1
                    extra, tfile = extra_for(cond, n)
                    rec = run_sim("b5", n, n_orders, seed, AISLE_BLOCK, (f"--order-gap={gap}", *extra),
                                  stall_dump_prefix=f"stall_b5_{load}_{cond}")
                    rec["load"], rec["cond"], rec["theta_file"] = load, cond, tfile
                    rows.append(rec)
                    if is_stall(rec):
                        continue
                    print(f"  [{k:3d}/{total}] {load} {cond:8s} r={n:2d} seed={seed}: {rec['tasks_per_h']:6.1f} tasks/h, "
                          f"lead {rec['lead_mean_s']:6.1f}s, util {rec['util']*100:3.0f}%, "
                          f"replan {rec['replan_steps']:5d} ({rec['wall_s']}s) {tfile}", flush=True)
    write_csv(CSV_PATH, rows)

# ------------------------------------------------------------
# 집계
# ------------------------------------------------------------
plt = setup_plt()
loads = [k for k in LOADS if any(r["load"] == k for r in rows)]
robots = sorted({int(float(r["n_robots"])) for r in rows})
N_STALL = sum(1 for r in rows if is_stall(r))
STYLE = {"neutral": ("#7f8c8d", "중립 θ (규칙 없음)"),
         "theta_n": ("#c0392b", "대수별 θ (최근접)"),
         "theta_24": ("#2980b9", f"{FIXED_THETA_N}대 θ 고정")}
SEED_NOTE = f"평가 시드 {SEEDS} 평균" + (f", STALL {N_STALL}런 제외" if N_STALL else "")

# 1) 처리량·리드타임 곡선 (시드 산포 밴드)
fig, axes = plt.subplots(len(loads), 2, figsize=(13, 4.6 * len(loads)), squeeze=False)
for i, load in enumerate(loads):
    for ax, (key, label) in zip(axes[i], [("tasks_per_h", "throughput [tasks/h]"), ("lead_mean_s", "lead time mean [s]")]):
        for cond, (color, name) in STYLE.items():
            m = mean_series(rows, key, robots, load=load, cond=cond)
            band = spread_series(rows, key, robots, load=load, cond=cond)
            ax.plot(robots, m, "o-", color=color, lw=2, ms=4, label=name)
            ax.fill_between(robots, [b[0] for b in band], [b[1] for b in band], color=color, alpha=0.12)
        ax.set_xlabel("n_robots")
        ax.set_xticks(robots)
        ax.set_title(f"{load} ({LOADS[load][0]}주문, 간격 {LOADS[load][1]}틱) — {label}")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
fig.suptitle(f"B-5 θ 적용 Fleet Sweep — 헤딩 모델, 충전 존, aisle-block ON ({SEED_NOTE})", fontsize=10)
plt.tight_layout()
plt.savefig(os.path.join(RES_DIR, f"theta_sweep_throughput{TAG}.png"), dpi=115)

# 2) 중립 대비 개선율
fig, axes = plt.subplots(1, len(loads), figsize=(6.5 * len(loads), 4.6), squeeze=False)
for ax, load in zip(axes[0], loads):
    base = mean_series(rows, "tasks_per_h", robots, load=load, cond="neutral")
    for cond in ("theta_n", "theta_24"):
        m = mean_series(rows, "tasks_per_h", robots, load=load, cond=cond)
        gain = [(a / b - 1) * 100 if not math.isnan(b) and b > 0 else float("nan") for a, b in zip(m, base)]
        ax.plot(robots, gain, "o-", color=STYLE[cond][0], lw=2, ms=4, label=STYLE[cond][1])
    ax.axhline(0, color="k", lw=0.8, alpha=0.5)
    ax.set_xlabel("n_robots")
    ax.set_xticks(robots)
    ax.set_ylabel("Δ throughput vs neutral [%]")
    ax.set_title(f"{load} — 중립 대비 처리량 개선율")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
fig.suptitle(f"B-5 — θ 효과 ({SEED_NOTE})", fontsize=10)
plt.tight_layout()
plt.savefig(os.path.join(RES_DIR, f"theta_sweep_gain{TAG}.png"), dpi=115)

# 3) 교차표: 중립 N대 처리량을 처음 넘는 θ 최소 대수 M → 절감 N−M (설계 §5)
cross = []
print("\n교차표 (시드 평균, tasks/h)")
for load in loads:
    base = dict(zip(robots, mean_series(rows, "tasks_per_h", robots, load=load, cond="neutral")))
    for cond in ("theta_n", "theta_24"):
        th = dict(zip(robots, mean_series(rows, "tasks_per_h", robots, load=load, cond=cond)))
        for n in robots:
            b = base[n]
            if math.isnan(b):
                continue
            m = next((k for k in robots if not math.isnan(th[k]) and th[k] >= b), None)
            # 시드별 부호 일치 검사: M대 θ vs N대 중립을 같은 시드끼리 비교
            verdict = ""
            if m is not None:
                diffs = []
                for s in SEEDS:
                    a = values(rows, "tasks_per_h", load=load, cond=cond, n_robots=m, seed=s)
                    c = values(rows, "tasks_per_h", load=load, cond="neutral", n_robots=n, seed=s)
                    if a and c:
                        diffs.append(a[0] - c[0])
                verdict = "일관" if diffs and all(d >= 0 for d in diffs) else "시드 부호 갈림"
            cross.append(dict(load=load, cond=cond, neutral_n=n, neutral_tph=round(b, 1),
                              theta_m=m if m is not None else "", theta_tph=round(th[m], 1) if m is not None else "",
                              saved=(n - m) if m is not None else "", verdict=verdict))
            if n in (16, 20, 24, 28):
                print(f"  {load} {cond:8s}: 중립 {n:2d}대 {b:6.1f} ≈ θ {m if m is not None else '—':>2}대 "
                      f"{(f'{th[m]:6.1f}' if m is not None else '      ')}  절감 {(n - m) if m is not None else '—':>2}  {verdict}")
write_csv(os.path.join(RES_DIR, f"theta_sweep_cross{TAG}.csv"), cross)

# 4) θ 한 벌 판정: |theta_24 − theta_n| 이 시드 산포 안인가 (설계 §5)
print("\nθ 한 벌 판정 (|24대 θ 고정 − 대수별 θ| vs 시드 산포)")
for load in loads:
    a = mean_series(rows, "tasks_per_h", robots, load=load, cond="theta_24")
    b = mean_series(rows, "tasks_per_h", robots, load=load, cond="theta_n")
    band = spread_series(rows, "tasks_per_h", robots, load=load, cond="theta_n")
    outside = [n for n, x, y, (lo, hi) in zip(robots, a, b, band) if not (math.isnan(x) or math.isnan(y)) and abs(x - y) > (hi - lo)]
    print(f"  {load}: 산포 밖 대수 {outside if outside else '없음 → θ 한 벌 충분'}")

print(f"\n저장: results/{os.path.basename(CSV_PATH)}, theta_sweep_throughput{TAG}.png, theta_sweep_gain{TAG}.png, "
      f"theta_sweep_cross{TAG}.csv")
