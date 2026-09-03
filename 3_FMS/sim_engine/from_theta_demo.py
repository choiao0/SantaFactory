# -*- coding: utf-8 -*-
# ============================================================
# B-2 검증 데모 — from_theta() v2 검산 + 더미 θ 회피 확인 (DoD)
# (설계: docs/2026-09-01_B2_from_theta_설계.md §3 v2 개정·§6)
#
# 1부: from_theta 성질 검산 (assert)
#   [1] 중립 θ(GuidanceTheta.neutral()) → uniform 1.0
#   [2] 극단 θ: 출력 범위 [COST_MIN, COST_MAX] + 포화 없음 (max ≤ max_realizable_edge_cost)
#   [3] 통로 내부 그룹 방향 부호 (period=1, phase=0 → 짝수 통로 북행 < 남행)
#   [4] 규칙별 단독 검사: loop 역행 / 교차로 진입만 / station in·out + entry_dir 표
#   [5] 배타: loop ∧ 교차로 진입이 겹치는 간선 = loop_gain 하나만
# 2부: 더미 θ(교대 순환 극단)로 sim_v2 실행, uniform 대비 통로 방향 분극 assert.
#   극단 θ 완주 자체가 가중 거리항 라이브니스 회귀 (2026-09-02 결정 §5).
#
# 사용: python from_theta_demo.py   (~1분, sim_v2 2회 포함)
# ============================================================
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict

import numpy as np

from from_theta import extract_topology, from_theta, load_theta
from map_loader import load_map
from contracts.guidance_types import (COST_MAX, COST_MIN, GuidanceTheta,
                                      max_realizable_edge_cost)

OUT = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(OUT, "results")
N, E, S, W = 0, 1, 2, 3


def _eq(a, b, tol=1e-6):
    """부동소수점 근사 동등 (SonarQube S1244: float `==` 금지). 비용은 float32 곱이라 tol 1e-6."""
    return bool(np.isclose(a, b, rtol=0.0, atol=tol))

NEUTRAL = asdict(GuidanceTheta.neutral())
# 더미 θ: 교대 순환을 범위 극단(gain 3.5, boost 0.5)으로.
# 비가중 BFS 거리항에서는 gain ≥ wait+1 이라 영구 정체(2026-09-01 실측 STALL)
# 였던 값 — 가중 다익스트라(2026-09-02 결정)로 정체 없이 완주해야 한다.
DUMMY = dict(NEUTRAL, aisle_alt_gain=3.5, aisle_alt_boost=0.5)


def theta_of(d):
    p = os.path.join(tempfile.gettempdir(), "theta_b2_tmp.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(d, f)
    return load_theta(p)


def main():
    free, st_cell, _ = load_map(OUT)
    topo = extract_topology(free, st_cell, verbose=True)

    # ── 1부: 검산 ──────────────────────────────────────────
    g = from_theta(free, topo, theta_of(NEUTRAL))
    assert np.allclose(g.edge_cost, 1.0) and np.allclose(g.wait_cost, 1.0), "중립 θ가 uniform이 아니다"
    print("[1] 중립 θ (GuidanceTheta.neutral) → uniform 1.0 : OK")

    extreme = theta_of(dict(NEUTRAL, aisle_alt_gain=3.5, aisle_alt_boost=0.5, loop_gain=3.0,
                            main_aisle_gain=1.2, junction_penalty=3.0, station_in=0.5,
                            station_out=3.0, wait_cost=3.0))
    g = from_theta(free, topo, extreme)
    assert g.edge_cost.min() >= COST_MIN and g.edge_cost.max() <= COST_MAX
    cap = max_realizable_edge_cost(extreme)
    assert g.edge_cost.max() <= cap + 1e-6, f"포화: max {g.edge_cost.max()} > 실현 상한 {cap}"
    print(f"[2] 극단 θ: 범위 [{COST_MIN}, {COST_MAX}] 안, max {g.edge_cost.max():.2f} ≤ "
          f"실현 상한 {cap:.2f} (배타 규칙, 포화 없음) : OK")

    g = from_theta(free, topo, theta_of(DUMMY))
    on = topo.v_aisle_rank >= 0
    even = on & (topo.v_aisle_rank % 2 == 0)
    odd = on & (topo.v_aisle_rank % 2 == 1)
    inner = np.zeros_like(on)
    inner[49:66] = True                                  # 통로 내부 간선(양 끝 같은 통로)
    assert np.all(g.edge_cost[..., N][even & inner] < g.edge_cost[..., S][even & inner])
    assert np.all(g.edge_cost[..., S][odd & inner] < g.edge_cost[..., N][odd & inner])
    print("[3] 통로 내부 그룹 방향 부호 (짝수=북, 홀수=남) : OK")

    # [4] 규칙별 단독 검사 — 알려진 간선으로
    ec = from_theta(free, topo, theta_of(dict(NEUTRAL, loop_gain=2.0))).edge_cost
    assert _eq(ec[44, 60, E], 2.0) and _eq(ec[44, 60, W], 1.0), "남 밴드 순방향=서, 역행=동"
    assert _eq(ec[70, 60, W], 2.0) and _eq(ec[70, 60, E], 1.0), "북 밴드 순방향=동, 역행=서"
    ec = from_theta(free, topo, theta_of(dict(NEUTRAL, junction_penalty=3.0))).edge_cost
    assert _eq(ec[46, 70, N], 3.0), "교차로 경계 진입 (46,70)→(47,70)"
    assert _eq(ec[47, 70, E], 1.0) and _eq(ec[47, 70, S], 1.0), "교차로 내부·이탈 간선은 1.0"
    ec = from_theta(free, topo, theta_of(dict(NEUTRAL, station_in=0.5, station_out=3.0))).edge_cost
    pk = st_cell["packing[0]"]                           # (40,64), entry_dir=N
    assert topo.station_dir[pk] == N
    assert _eq(ec[pk[0] + 1, pk[1], S], 0.5), "packing 진입 (41,64)→S"
    assert _eq(ec[pk][N], 3.0) and _eq(ec[pk][E], 1.0), "packing 이탈 역주행 N만 벌금"
    ab = st_cell["aisle_buf[11]"]                        # (46,35), entry_dir=S (규칙 2)
    assert topo.station_dir[ab] == S and _eq(ec[ab[0] - 1, ab[1], N], 0.5) and _eq(ec[ab][S], 3.0)
    ib = st_cell["inbound_buf[0]"]                       # (52,24), entry_dir=E (규칙 2)
    assert topo.station_dir[ib] == E and _eq(ec[ib[0], ib[1] + 1, W], 0.5) and _eq(ec[ib][E], 3.0)
    n_dock = int((topo.station_dir >= 0).sum())
    print(f"[4] 규칙별 단독: loop 역행 / 교차로 진입만 / station in·out (도킹 칸 {n_dock}개, "
          f"packing N · aisle_buf S/N · inbound E) : OK")

    # [5] 배타: (47,69)→E 는 남 밴드 역행(loop) 이자 교차로(47,70..72) 진입
    ec = from_theta(free, topo, theta_of(dict(NEUTRAL, loop_gain=2.0, junction_penalty=3.0))).edge_cost
    assert _eq(ec[47, 69, E], 2.0), f"배타 위반: loop∧교차로 간선 = {ec[47, 69, E]} (기대 loop_gain 2.0)"
    ec2 = from_theta(free, topo, theta_of(dict(NEUTRAL, loop_gain=2.0, main_aisle_gain=1.2))).edge_cost
    assert _eq(ec2[44, 60, E], 2.4), "main_aisle_gain은 독립으로 항상 곱"
    print("[5] 배타 규칙 (loop > 교차로) + main_aisle_gain 독립 곱 : OK")

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
        print(f"[6] sim_v2 {label:7s}: {summary[0][:110]}")
    print("    (극단 θ 3.5에서 STALL 없이 완주 — 가중 거리항 라이브니스 OK)")

    def nshare(npz, mask):
        flow = np.load(npz)["dir_flow"]
        n, s = flow[..., 0][mask].sum(), flow[..., 2][mask].sum()
        return n / max(n + s, 1), int(n + s)

    f_uni = os.path.join(RES, "sim_v2_b2demo_r10_main_dirflow.npz")
    f_th = os.path.join(RES, "sim_v2_b2demo_r10_main_th_dirflow.npz")
    (e_uni, ne_u), (o_uni, no_u) = nshare(f_uni, even), nshare(f_uni, odd)
    (e_th, ne_t), (o_th, no_t) = nshare(f_th, even), nshare(f_th, odd)
    print(f"[7] 짝수 통로 북행 점유율: uniform {e_uni:.2f} (n={ne_u}) → θ {e_th:.2f} (n={ne_t})")
    print(f"    홀수 통로 북행 점유율: uniform {o_uni:.2f} (n={no_u}) → θ {o_th:.2f} (n={no_t})")
    gap_uni, gap_th = e_uni - o_uni, e_th - o_th
    print(f"    그룹 간 분극 격차(짝수-홀수): uniform {gap_uni:+.2f} → θ {gap_th:+.2f}")
    assert e_th > e_uni and o_th < o_uni, "분극 방향이 θ 그룹 규칙과 반대"
    assert gap_th > gap_uni + 0.15, "그룹 간 분극 격차가 충분히 벌어지지 않음"
    print("[8] DoD: 더미 θ 방향 분극(회피) 확인 : OK")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))
    lim, nets = 0, []
    for f in (f_uni, f_th):
        flow = np.load(f)["dir_flow"]
        net = np.where(on, flow[..., 0] - flow[..., 2], 0)
        nets.append(net)
        lim = max(lim, abs(net).max())
    for ax, net, title in zip(axes, nets, ("uniform", "dummy θ (alt 3.5/0.5)")):
        ax.imshow(np.where(free, 1.0, 0.25), cmap="gray", vmin=0, vmax=1, origin="lower")
        im = ax.imshow(np.where(on, net, np.nan), cmap="coolwarm", vmin=-lim, vmax=lim,
                       origin="lower")
        ax.set_title(f"net northbound flow — {title}")
        ax.set_xlim(28, 100)
        ax.set_ylim(38, 76)
    plt.colorbar(im, ax=axes, shrink=0.8, label="N moves − S moves")
    png = os.path.join(RES, "b2_from_theta_dirflow.png")
    plt.savefig(png, dpi=110, bbox_inches="tight")
    print(f"[9] 저장: {os.path.basename(png)} + 히트맵 2장 (results/)")
    print("[PASS] B-2 from_theta v2 검증 전부 통과")


if __name__ == "__main__":
    main()
