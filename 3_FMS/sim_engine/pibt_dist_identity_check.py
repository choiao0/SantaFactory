# -*- coding: utf-8 -*-
# ============================================================
# 헤딩 거리장 동일성 검사 — HGraph.dist vs 참조 구현 _dist_map_h_ref (S15P21A106-136)
#
# 1) 전체 계산: 실맵 목표(스테이션·존 칸·랜덤) 60개에서 (H,W,4) 전부 비트 동일 (uniform 비용)
# 2) 막힌 칸 패치: 랜덤 로봇 배치로 만든 막힌 칸 집합 40개 — 참조는 free 를 직접 막아 계산
# 3) 증분 복구 시간 vs 참조 전체 재계산 시간
# 4) θ 비용(비정수): 값 차이 ≤ 1e-9 (동률 경로 선택 차이만 허용)
# 사용: python pibt_dist_identity_check.py    (~1분)
# ============================================================
import time

import numpy as np

from map_loader import load_map, load_charge_zone, zone_cells
from pibt_core import REPLAN_RADIUS, TURN_TICKS, HGraph, _dist_map_h_ref, dist_map_h

FREE, st_cell, _ = load_map(aisle_block=True)
H, W = FREE.shape
rng = np.random.default_rng(136)
ZONE = zone_cells(FREE, load_charge_zone(FREE) & FREE)
free_cells = list(zip(*np.nonzero(FREE)))


def same_arrays(a, b, tol=0.0):
    if tol == 0.0:
        return np.array_equal(a, b)
    ok = (a < 0) == (b < 0)
    return bool(ok.all()) and bool(np.all(np.abs(a[a >= 0] - b[b >= 0]) <= tol))


def main():
    ec = np.ones((H, W, 4), dtype=np.float64)
    tc = float(TURN_TICKS)
    goals = list(st_cell.values())[:30] + ZONE[::8][:15] + [free_cells[i] for i in rng.choice(len(free_cells), 15, replace=False)]

    # [1] 전체 계산 동일성 + 시간
    t_ref = t_new = 0.0
    for g in goals:
        t0 = time.perf_counter(); a = _dist_map_h_ref(FREE, g, ec, tc); t_ref += time.perf_counter() - t0
        t0 = time.perf_counter(); b = dist_map_h(FREE, g, ec, tc); t_new += time.perf_counter() - t0
        assert same_arrays(a, b), f"[1] 전체 계산 불일치 goal={g}"
    print(f"[1] 전체 계산 {len(goals)}개 목표 비트 동일 : OK  (참조 {t_ref/len(goals)*1000:.1f} ms → 새 {t_new/len(goals)*1000:.1f} ms/회, 첫 회 테이블 생성 포함)")

    # [2] 막힌 칸 패치 (재계획 상황 재현): 로봇 me 주변 다른 로봇 점유 칸을 막음
    graph = HGraph(FREE, ec, tc)
    n_ok = 0
    t_ref = t_rep = 0.0
    for k in range(40):
        me = free_cells[rng.integers(len(free_cells))]
        others = [free_cells[i] for i in rng.choice(len(free_cells), 6, replace=False)]
        # me 근처로 끌어오기 (반경 3 안)
        blocked = set()
        for (r, c) in others:
            rr = int(np.clip(me[0] + rng.integers(-REPLAN_RADIUS, REPLAN_RADIUS + 1), 0, H - 1))
            cc = int(np.clip(me[1] + rng.integers(-REPLAN_RADIUS, REPLAN_RADIUS + 1), 0, W - 1))
            if FREE[rr, cc] and (rr, cc) != me:
                blocked.add((rr, cc))
        goal = goals[k % len(goals)]
        f = FREE.copy()
        for (r, c) in blocked:
            f[r, c] = False
        graph.base(goal)                                   # 기본 풀이는 캐시 (재계획 시간에서 제외)
        t0 = time.perf_counter(); a = _dist_map_h_ref(f, goal, ec, tc); t_ref += time.perf_counter() - t0
        t0 = time.perf_counter(); b = graph.dist(goal, blocked); t_rep += time.perf_counter() - t0
        assert same_arrays(a, b), f"[2] 증분 복구 불일치 goal={goal} blocked={sorted(blocked)}"
        n_ok += 1
    print(f"[2][3] 막힌 칸 {n_ok}건 증분 복구 = 참조 전체 재계산 비트 동일 : OK  (참조 {t_ref/n_ok*1000:.1f} ms → 증분 {t_rep/n_ok*1000:.2f} ms/회)")

    # [4] θ 비용: from_theta 더미 θ 로 비정수 비용
    from from_theta import extract_topology, from_theta, load_theta
    import json, os, tempfile
    from contracts.guidance_types import GuidanceTheta
    from dataclasses import asdict
    th = dict(asdict(GuidanceTheta.neutral()), aisle_alt_gain=2.5, aisle_alt_boost=0.7, loop_gain=1.5,
              junction_penalty=1.3, station_in=0.6, station_out=1.7, main_aisle_gain=1.1)
    p = os.path.join(tempfile.gettempdir(), "theta_identity_tmp.json")
    json.dump(th, open(p, "w", encoding="utf-8"))
    g = from_theta(FREE, extract_topology(FREE, st_cell), load_theta(p))
    ec_t = g.edge_cost.astype(np.float64)
    worst = 0.0
    for goal in goals[:20]:
        a = _dist_map_h_ref(FREE, goal, ec_t, tc)
        b = dist_map_h(FREE, goal, ec_t, tc)
        assert ((a < 0) == (b < 0)).all(), f"[4] 도달성 불일치 goal={goal}"
        worst = max(worst, float(np.max(np.abs(a[a >= 0] - b[b >= 0]))))
    print(f"[4] θ 비용 20개 목표: 도달성 동일, 최대 값 차이 {worst:.2e} (동률 경로 부동소수 차이 허용 1e-9) : {'OK' if worst <= 1e-9 else 'FAIL'}")
    assert worst <= 1e-9
    print("[PASS] 헤딩 거리장 동일성 검사 통과")


if __name__ == "__main__":
    main()
