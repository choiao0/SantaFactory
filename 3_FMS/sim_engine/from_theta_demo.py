# -*- coding: utf-8 -*-
# ============================================================
# B-2 검증 데모 — from_theta() 검산 + 더미 θ 회피 확인 (DoD)
# (설계: docs/2026-09-01_B2_from_theta_설계.md §6)
#
# 1부: from_theta 성질 검산 (assert)
#   - 중립 θ(연속 8개 전부 1.0) → uniform과 동일
#   - 출력 범위 [0.5, 5.0] 클립
#   - 그룹 방향 부호 (period=1, phase=0 → 짝수 통로 북행이 남행보다 쌈)
#   - 순환로 역행 벌금 / 도킹 칸 퇴장 벌금
# 2부: 더미 θ(교대 순환 극단)로 sim_v2 실행, uniform 대비
#   짝수 통로 북행 점유율 상승을 assert — "회피가 보인다"의 정량판.
#   히트맵·방향 흐름 PNG는 results/에 저장 (기존 파일 덮어쓰지 않는 새 이름).
#
# 사용: python from_theta_demo.py   (~1분, sim_v2 2회 포함)
# ============================================================
import json
import os
import subprocess
import sys
import tempfile

import numpy as np

from from_theta import (CLIP_HI, CLIP_LO, extract_topology, from_theta,
                        load_theta)
from map_loader import load_map

OUT = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(OUT, "results")

NEUTRAL = dict(aisle_alt_gain=1.0, aisle_alt_boost=1.0, loop_gain=1.0,
               main_aisle_gain=1.0, junction_penalty=1.0, station_in=1.0,
               station_out=1.0, wait_cost=1.0,
               aisle_period=1, aisle_phase=0, loop_dir=0)
# 더미 θ: 교대 순환만 강하게. 단 라이브니스 제약(설계 §4) 안쪽으로 —
# gain ≥ wait_cost+1 이면 "비싼 방향 전진"보다 "제자리 대기"가 매 틱 이겨서
# 영구 정체가 된다 (gain 3.5로 실측 STALL 확인, 2026-09-01).
DUMMY = dict(NEUTRAL, aisle_alt_gain=1.8, aisle_alt_boost=0.5)


def theta_of(d):
    p = os.path.join(tempfile.gettempdir(), "theta_b2_tmp.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(d, f)
    return load_theta(p)


def main():
    free, st_cell, _ = load_map(OUT)
    topo = extract_topology(free, st_cell)

    # ── 1부: 검산 ──────────────────────────────────────────
    g = from_theta(free, topo, theta_of(NEUTRAL))
    assert np.all(g.edge_cost == 1.0) and np.all(g.wait_cost == 1.0), \
        "중립 θ가 uniform이 아니다"
    print("[1] 중립 θ → uniform 1.0 : OK")

    extreme = dict(NEUTRAL, aisle_alt_gain=3.5, junction_penalty=3.0,
                   main_aisle_gain=0.5, station_in=0.4, station_out=3.0,
                   loop_gain=3.0, wait_cost=3.0)
    g = from_theta(free, topo, theta_of(extreme))
    assert g.edge_cost.min() >= CLIP_LO and g.edge_cost.max() <= CLIP_HI
    assert g.wait_cost.min() >= CLIP_LO and g.wait_cost.max() <= CLIP_HI
    print(f"[2] 극단 θ 출력 범위 [{CLIP_LO}, {CLIP_HI}] 클립 : OK")

    g = from_theta(free, topo, theta_of(DUMMY))
    on = topo.v_aisle_rank >= 0
    even = on & (topo.v_aisle_rank % 2 == 0)
    odd = on & (topo.v_aisle_rank % 2 == 1)
    assert np.all(g.edge_cost[..., 0][even] < g.edge_cost[..., 2][even]), \
        "짝수 통로에서 북행이 남행보다 싸야 함 (period=1, phase=0)"
    assert np.all(g.edge_cost[..., 2][odd] < g.edge_cost[..., 0][odd]), \
        "홀수 통로는 남행 선호여야 함"
    print("[3] 그룹 방향 부호 (짝수=북, 홀수=남) : OK")

    g = from_theta(free, topo, theta_of(dict(NEUTRAL, loop_gain=2.0,
                                             station_out=2.5)))
    south_band = topo.loop_fwd == 3                      # 남 밴드 순방향=서
    assert np.all(g.edge_cost[..., 1][south_band] >= 2.0), "순환 역행 벌금 누락"
    assert np.all(g.edge_cost[topo.station] >= 2.0), "도킹 칸 퇴장 벌금 누락"
    print("[4] 순환 역행·도킹 퇴장 벌금 : OK")

    # ── 2부: 더미 θ 회피 (DoD) ─────────────────────────────
    dummy_path = os.path.join(RES, "theta_b2_dummy.json")
    with open(dummy_path, "w", encoding="utf-8") as f:
        json.dump(DUMMY, f, indent=1)

    env = dict(os.environ, SIM_DIRFLOW="1", PYTHONIOENCODING="utf-8")
    base_args = [sys.executable, "sim_v2_tasks.py", "b2demo", "10", "40", "42",
                 "0", "--flow=main"]
    for label, extra in (("uniform", []), ("theta", [f"--theta={dummy_path}"])):
        r = subprocess.run(base_args + extra, cwd=OUT, env=env,
                           capture_output=True, text=True, encoding="utf-8")
        assert r.returncode == 0, f"sim_v2 {label} 실행 실패:\n{r.stdout}\n{r.stderr}"
        summary = [ln for ln in r.stdout.splitlines() if "[SUMMARY]" in ln]
        print(f"[5] sim_v2 {label:7s}: {summary[0][:110]}")

    def nshare(npz, mask):
        flow = np.load(npz)["dir_flow"]
        n, s = flow[..., 0][mask].sum(), flow[..., 2][mask].sum()
        return n / max(n + s, 1), int(n + s)

    f_uni = os.path.join(RES, "sim_v2_b2demo_r10_main_dirflow.npz")
    f_th = os.path.join(RES, "sim_v2_b2demo_r10_main_th_dirflow.npz")
    (e_uni, ne_u), (o_uni, no_u) = nshare(f_uni, even), nshare(f_uni, odd)
    (e_th, ne_t), (o_th, no_t) = nshare(f_th, even), nshare(f_th, odd)
    print(f"[6] 짝수 통로 북행 점유율: uniform {e_uni:.2f} (n={ne_u}) → "
          f"θ {e_th:.2f} (n={ne_t})")
    print(f"    홀수 통로 북행 점유율: uniform {o_uni:.2f} (n={no_u}) → "
          f"θ {o_th:.2f} (n={no_t})")
    gap_uni, gap_th = e_uni - o_uni, e_th - o_th
    print(f"    그룹 간 분극 격차(짝수-홀수): uniform {gap_uni:+.2f} → θ {gap_th:+.2f}")
    assert e_th > e_uni and o_th < o_uni, "분극 방향이 θ 그룹 규칙과 반대"
    assert gap_th > gap_uni + 0.15, "그룹 간 분극 격차가 충분히 벌어지지 않음"
    print("[7] DoD: 더미 θ 방향 분극(회피) 확인 : OK")

    # 비교 PNG — 통로 칸의 순북행(북-남) 흐름
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))
    lim = 0
    nets = []
    for f in (f_uni, f_th):
        flow = np.load(f)["dir_flow"]
        net = np.where(on, flow[..., 0] - flow[..., 2], 0)
        nets.append(net)
        lim = max(lim, abs(net).max())
    for ax, net, title in zip(axes, nets, ("uniform", "dummy θ (alt 1.8/0.5)")):
        ax.imshow(np.where(free, 1.0, 0.25), cmap="gray", vmin=0, vmax=1,
                  origin="lower")
        im = ax.imshow(np.where(on, net, np.nan), cmap="coolwarm",
                       vmin=-lim, vmax=lim, origin="lower")
        ax.set_title(f"net northbound flow — {title}")
        ax.set_xlim(28, 100)
        ax.set_ylim(38, 76)
    plt.colorbar(im, ax=axes, shrink=0.8, label="N moves − S moves")
    png = os.path.join(RES, "b2_from_theta_dirflow.png")
    plt.savefig(png, dpi=110, bbox_inches="tight")
    print(f"[8] 저장: {os.path.basename(png)} + 히트맵 2장 (results/)")
    print("[PASS] B-2 from_theta 검증 전부 통과")


if __name__ == "__main__":
    main()
