# -*- coding: utf-8 -*-
# ============================================================
# PIBT 실제 창고 맵 스모크 테스트 (S15P21A106-107)
#
# pibt_core.py를 확정 창고 맵(occupancy_grid.npy, 1.0m 격자로 다운샘플)에서
# 실제 규모로 검증한다. 이벤트 루프 통합 전에 확인할 것 세 가지:
#   1) 실제 지형(통로차단 ON 포함)에서 교착 없이 전원 목표 도달 (B-1d)
#   2) 매 틱 vertex/edge 충돌 없음 (pibt_mvp_demo와 동일한 전수 검사)
#   3) 틱당 계산 시간 — 시뮬 1회(수천 틱)에 감당 가능한 수준인지
#
# 시나리오:
#   A) 충전존 홈 10대 -> 스테이션 도킹 칸 (실전과 같은 OD 패턴)
#   B) 랜덤 OD 30대 스트레스 (시드 고정) — 통로 곳곳에서 교차/정면충돌 유발
#   C) 헤딩 모델(2칸 점유·회전 예약) 랜덤 OD 스트레스 — 2026-09-02 설계 §8-6
#
# 맵 로드는 map_loader 공용 모듈 사용 (통로차단 ON — fleet_sweep과 동일 방침).
#
# 사용: python pibt_smoke_real_map.py
# ============================================================
import os
import time

import numpy as np

from map_loader import load_map
from pibt_core import dist_map, dist_map_h, occupied, run, run_h, valid_state
from pibt_heading_demo import check_collisions_h
from pibt_mvp_demo import check_collisions

OUT = os.path.dirname(os.path.abspath(__file__))
FREE, st_cell, stations = load_map(OUT, aisle_block=True)
H, W = FREE.shape
print(f"[0] 맵 coarse {H}x{W}, free 칸 {int(FREE.sum())}개, 통로차단 ON")


def report(name, history, n_agents, elapsed):
    steps = len(history) - 1
    print(f"{name}: {n_agents}대 전원 도달, {steps}스텝, "
          f"총 {elapsed*1000:.0f}ms = 틱당 {elapsed/steps*1000:.2f}ms")


def scenario_stations():
    """충전존 홈 10대 -> 스테이션 도킹 칸 (B-0 최적 대수 기준)."""
    starts = {i: st_cell[f"charger[{i}]"] for i in range(6)}
    starts.update({6 + i: st_cell[f"charge_q[{i}]"] for i in range(4)})
    goal_names = ["induction[0]", "induction[1]", "aisle_buf[0]", "aisle_buf[5]",
                  "aisle_buf[10]", "consol[0]", "consol[1]", "packing[0]",
                  "packing[2]", "packing[4]"]
    goals = {i: st_cell[nm] for i, nm in enumerate(goal_names)}
    assert len(set(goals.values())) == len(goals), "목표 칸 중복"
    t0 = time.perf_counter()
    history = run(FREE, starts, goals, max_steps=600)
    elapsed = time.perf_counter() - t0
    check_collisions(history, FREE)
    for a, g in goals.items():
        assert history[-1][a] == g, f"agent{a} 미도달: {history[-1][a]} != {g}"
    report("[A] 충전존->스테이션", history, len(starts), elapsed)


def scenario_random_stress(n_agents=30, seed=42):
    """랜덤 OD 스트레스 — 통로 전역에서 교차/정면충돌 유발."""
    rng = np.random.default_rng(seed)
    free_cells = list(zip(*np.nonzero(FREE)))
    # 도달 가능성 보장: 가장 큰 연결 성분 기준점에서 dist >= 0 인 칸만 사용
    ref = dist_map(FREE, st_cell["induction[0]"])
    cells = [rc for rc in free_cells if ref[rc] >= 0]
    picks = rng.choice(len(cells), size=n_agents * 2, replace=False)
    starts = {i: cells[picks[i]] for i in range(n_agents)}
    goals = {i: cells[picks[n_agents + i]] for i in range(n_agents)}
    t0 = time.perf_counter()
    history = run(FREE, starts, goals, max_steps=800)
    elapsed = time.perf_counter() - t0
    check_collisions(history, FREE)
    for a, g in goals.items():
        assert history[-1][a] == g, f"agent{a} 미도달: {history[-1][a]} != {g}"
    report(f"[B] 랜덤 OD 스트레스(seed={seed})", history, n_agents, elapsed)


def _sample_heading_starts(order, cells, ref_h, n_agents):
    """시작 상태: 기준 목표로 갈 수 있고 서로 점유(자기+뒤 칸)가 안 겹치는 (칸, 방향) greedy 샘플."""
    starts, taken = {}, set()
    for idx in order:
        if len(starts) == n_agents:
            break
        r, c = cells[idx]
        for h in range(4):
            s = (int(r), int(c), h)
            if ref_h[s] >= 0 and not (set(occupied(s)) & taken):
                starts[len(starts)] = s
                taken |= set(occupied(s))
                break
    return starts, taken


def _goal_ok(rc, used, taken, goals):
    """목표 칸 조건: 미사용, 시작 점유와 겹치지 않음, 다른 목표와 체비쇼프 거리 ≥ 3."""
    if rc in used or rc in taken:
        return False
    return all(max(abs(rc[0] - g[0]), abs(rc[1] - g[1])) >= 3 for g in goals.values())


def _sample_heading_goals(order, cells, taken, starts, n_agents):
    """목표: order를 뒤에서부터 소비. 서로 체비쇼프 거리 ≥ 3 — 2칸 차체가 어떤 방향으로
    도착해도 목표 차체가 겹치지 않게. 1m 간격 도킹점 두 개에 1.44m 로봇 둘은 물리적으로
    양립 불가 (seed 123: 목표 칸이 이웃의 주차 차체 안에 있어 영구 핑퐁 — 배치 문제).
    각 agent의 시작 상태에서 도달 가능한 칸만 채택."""
    goals, used, gi = {}, set(), 0
    rev = list(order[::-1])
    for a in range(n_agents):
        while True:
            assert gi < len(rev), f"agent{a}: 도달 가능한 목표 후보 소진"
            rc = (int(cells[rev[gi]][0]), int(cells[rev[gi]][1]))
            gi += 1
            if _goal_ok(rc, used, taken, goals) and dist_map_h(FREE, rc)[starts[a]] >= 0:
                goals[a] = rc
                used.add(rc)
                break
    return goals


def scenario_heading_stress(n_agents=30, seed=42):
    """헤딩 모델 랜덤 OD 스트레스: 샘플링은 위 두 헬퍼, 여기서는 실행·검사만."""
    rng = np.random.default_rng(seed)
    ref = dist_map(FREE, st_cell["induction[0]"])
    cells = [rc for rc in zip(*np.nonzero(FREE)) if ref[rc] >= 0]
    order = rng.permutation(len(cells))
    ref_h = dist_map_h(FREE, st_cell["induction[0]"])   # 기준 목표로 갈 수 있는 상태만 시작으로
    starts, taken = _sample_heading_starts(order, cells, ref_h, n_agents)
    goals = _sample_heading_goals(order, cells, taken, starts, n_agents)
    t0 = time.perf_counter()
    history, cells_hist = run_h(FREE, starts, goals, max_steps=1500)
    elapsed = time.perf_counter() - t0
    check_collisions_h(history, cells_hist, FREE)
    for a, g in goals.items():
        assert history[-1][a][:2] == g, f"agent{a} 미도달: {history[-1][a]} != {g}"
    turns = sum(1 for p, c in zip(history, history[1:])
                for a in p if p[a][2] != c[a][2])
    report(f"[C] 헤딩 모델 랜덤 OD(seed={seed}, 회전 {turns}회)", history, n_agents, elapsed)


if __name__ == "__main__":
    scenario_stations()
    for seed in [42, 7, 11, 123, 999, 2026]:
        scenario_random_stress(n_agents=30, seed=seed)
    for seed in [42, 7]:                      # B-0 최적점(10대)의 6배 과밀
        scenario_random_stress(n_agents=60, seed=seed)
    for seed in [42, 7, 11]:
        scenario_heading_stress(n_agents=30, seed=seed)
    print("[DONE] 실제 창고 맵 PIBT 스모크 테스트 통과")
