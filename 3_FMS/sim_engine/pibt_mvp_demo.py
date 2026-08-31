# -*- coding: utf-8 -*-
# ============================================================
# PIBT 코어 MVP 검증 (S15P21A106-107)
#
# pibt_core.py를 3개 표준 시나리오로 검증. 저장소에 pytest 등 테스트
# 프레임워크가 없어 fleet_sweep.py처럼 콘솔 출력 + assert로 검증한다.
#
# 모든 시나리오에서 매 틱 vertex 충돌(같은 칸 2대)과 edge 스왑(맞교환
# 통과)을 전수 검사한다 — 최종 도착만 보면 "서로를 통과해서 도착"하는
# 버그가 통과로 위장할 수 있음 (실제로 초기 구현에서 발생했던 결함).
#
# 1) 단일 에이전트: 장애물 없는 격자에서 목표 도달 (B-1a DoD)
# 2) 좁은 통로 정면충돌: 폭 1칸 통로 양끝에서 로봇 2대가 마주보고 출발 —
#    한쪽이 방(retreat 공간)으로 물러나 비켜주고 둘 다 도달 (B-1c/1d DoD,
#    HANDOFF_v4 §8 "정면충돌 후 진입로 막힘" 재현 대상)
# 3) 결정론: 동일 설정 2회 실행, 매 틱 위치가 완전히 같은지 확인 (B-1b DoD)
#
# 사용: python pibt_mvp_demo.py
# ============================================================
import numpy as np

from pibt_core import run


def check_collisions(history, free):
    """매 틱 vertex 충돌 / edge 스왑 / 통행 불가 칸 진입 / 순간이동 전수 검사."""
    for t, pos in enumerate(history):
        cells = list(pos.values())
        assert len(cells) == len(set(cells)), \
            f"t={t} vertex 충돌: {pos}"
        for (r, c) in cells:
            assert free[r, c], f"t={t} 통행 불가 칸 진입: {pos}"
    for t, (prev, cur) in enumerate(zip(history, history[1:]), start=1):
        agents = list(prev)
        for i, a in enumerate(agents):
            dr = abs(cur[a][0] - prev[a][0]) + abs(cur[a][1] - prev[a][1])
            assert dr <= 1, f"t={t} agent{a} 순간이동: {prev[a]} -> {cur[a]}"
            for b in agents[i + 1:]:
                assert not (cur[a] == prev[b] and cur[b] == prev[a]), \
                    f"t={t} agent{a}<->{b} 스왑(맞교환 통과): {prev} -> {cur}"


def scenario_single_agent():
    H, W = 5, 5
    free = np.ones((H, W), dtype=bool)
    history = run(free, {0: (0, 0)}, {0: (4, 4)}, max_steps=50)
    check_collisions(history, free)
    assert history[-1][0] == (4, 4), f"단일 에이전트가 목표에 못 감: {history[-1]}"
    print(f"[1] 단일 에이전트: {len(history) - 1}스텝만에 (0,0) -> (4,4) 도달 OK")


def _corridor_grid():
    # 방(2칸 폭) - 통로(폭 1, 5칸) - 방(2칸 폭), 세로 3칸 높이
    H, W = 3, 9
    free = np.zeros((H, W), dtype=bool)
    free[:, 0:2] = True    # 왼쪽 방
    free[:, 7:9] = True    # 오른쪽 방
    free[1, 2:7] = True    # 가운데 통로 (r=1만)
    return free


def scenario_head_on():
    free = _corridor_grid()
    starts = {0: (1, 0), 1: (1, 8)}
    goals = {0: (1, 8), 1: (1, 0)}
    history = run(free, starts, goals, max_steps=60)
    check_collisions(history, free)
    assert history[-1][0] == goals[0] and history[-1][1] == goals[1], \
        f"정면충돌 시나리오 미해결: {history[-1]}"
    print(f"[2] 좁은 통로 정면충돌: {len(history) - 1}스텝만에 둘 다 도달, "
          f"교착·스왑 없음 OK")
    for t, pos in enumerate(history):
        print(f"    t={t:2d}  agent0={pos[0]}  agent1={pos[1]}")


def scenario_determinism():
    free = _corridor_grid()
    starts = {0: (1, 0), 1: (1, 8)}
    goals = {0: (1, 8), 1: (1, 0)}
    h1 = run(free, starts, goals, max_steps=60)
    h2 = run(free, starts, goals, max_steps=60)
    assert h1 == h2, "동일 입력인데 결과가 다름 — 우선순위 정렬이 결정론적이지 않음"
    print(f"[3] 결정론 확인: 동일 설정 2회 실행, {len(h1) - 1}스텝 전부 일치 OK")


if __name__ == "__main__":
    scenario_single_agent()
    scenario_head_on()
    scenario_determinism()
    print("[DONE] PIBT 코어 MVP 검증 3개 시나리오 전부 통과")
