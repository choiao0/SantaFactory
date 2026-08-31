# -*- coding: utf-8 -*-
# ============================================================
# PIBT(Priority Inheritance with Backtracking) 코어 — MVP
#
# sim_v1_tasks.py의 이벤트 루프/도킹 대기슬롯 로직과 분리된 독립 모듈.
# drive()가 "도착시각을 미리 안다"는 시공간 A*의 계약에 기존 dispatch/assign이
# 의존하고 있어, PIBT는 이 모듈 안에서 매 틱 단위 이동만 담당하고
# 기존 이벤트 루프와의 통합은 별도 이슈에서 다룬다.
#
# 구현은 원 논문(Okumura et al., IJCAI 2019)의 예약 방식 그대로:
#   - 후보 칸을 잠정 예약(occ_next)한 뒤 점유자에게 재귀로 "비켜라" 전파,
#     실패하면 예약을 되돌리고 다음 후보 시도 (backtracking).
#   - 부모(밀어낸 쪽)의 현재 칸은 후보에서 제외 → 1:1 맞교환(swap) 차단.
#     3대 이상의 순환 회전(rotation)은 허용 — 논문과 동일, 충돌 없음.
#   - 재귀 중(잠정 예약 보유)인 에이전트는 "이번 틱 이동 확정" 취급이라
#     재귀가 자기 조상으로 되돌아가지 않는다.
#
# 좌표·방향 규칙 (7_Docs/AI/AI입출력명세서.md §3, 프로젝트 전역 고정):
#   (r, c) = (y, x). r 증가 = 북쪽, c 증가 = 동쪽.
#   방향 인덱스 0=북(r+1,c) 1=동(r,c+1) 2=남(r-1,c) 3=서(r,c-1), 반대=(방향+2)%4.
#   edge_cost[r, c, d] = (r,c)에서 방향 d로 나갈 때 비용.
#   contracts/guidance_types.py의 Guidance와 동일한 shape — 실제 θ가
#   들어와도 이 모듈은 안 바뀐다 (from_theta 배관은 별도 이슈).
# ============================================================
from collections import deque

import numpy as np

DIRS = [(1, 0), (0, 1), (-1, 0), (0, -1)]  # 0=N 1=E 2=S 3=W


def dist_map(free, goal):
    """goal까지의 정적 최단거리(BFS, 4-연결). 도달 불가 칸은 -1."""
    H, W = free.shape
    dm = np.full((H, W), -1, dtype=np.int32)
    dm[goal] = 0
    q = deque([goal])
    while q:
        r, c = q.popleft()
        for dr, dc in DIRS:
            rr, cc = r + dr, c + dc
            if 0 <= rr < H and 0 <= cc < W and free[rr, cc] and dm[rr, cc] < 0:
                dm[rr, cc] = dm[r, c] + 1
                q.append((rr, cc))
    return dm


def candidates(pos, dist, edge_cost, wait_cost, free):
    """pos에서 갈 수 있는 다음 칸(제자리 포함) 후보를 score 오름차순으로.
    score = edge_cost[r,c,dir] + dist[다음칸], 제자리는 wait_cost + dist[현재칸].
    AI입출력명세서 §12 "PIBT score = edge_cost + dist" 그대로.
    목표 칸(dist=0)에서는 제자리(1.0+0)가 모든 이동(1.0+1 이상)보다 싸서
    자연히 정지 — 도달 상태를 따로 특별취급하지 않는다."""
    r, c = pos
    H, W = free.shape
    scored = []
    if dist[r, c] >= 0:
        scored.append((wait_cost[r, c] + dist[r, c], pos))
    for d, (dr, dc) in enumerate(DIRS):
        rr, cc = r + dr, c + dc
        if 0 <= rr < H and 0 <= cc < W and free[rr, cc] and dist[rr, cc] >= 0:
            scored.append((edge_cost[r, c, d] + dist[rr, cc], (rr, cc)))
    scored.sort(key=lambda x: x[0])
    return [p for _, p in scored]


class _PIBTStep:
    """한 틱 분량의 우선순위 상속 + 백트래킹 해소. step()에서만 생성."""

    def __init__(self, positions, dists, edge_cost, wait_cost, free):
        self.positions = positions   # agent -> (r, c), 이번 틱 시작 시점 (불변)
        self.dists = dists           # agent -> dist_map(free, goal)
        self.edge_cost = edge_cost
        self.wait_cost = wait_cost
        self.free = free
        self.next_of = {}            # agent -> 다음 칸 (재귀 중엔 잠정, 리턴 후 확정)
        self.occ_next = {}           # cell -> 그 칸을 예약한 agent
        self.occ_now = {pos: a for a, pos in positions.items()}

    def resolve(self, a, parent=None):
        """a의 다음 칸을 정한다. 이동할 곳을 찾으면 True.
        전부 실패하면 제자리를 예약하고 False (호출한 부모는 백트래킹)."""
        cur = self.positions[a]
        for cand in candidates(cur, self.dists[a], self.edge_cost,
                               self.wait_cost, self.free):
            if cand in self.occ_next:                      # 이미 예약된 칸
                continue
            if parent is not None and cand == self.positions[parent]:
                continue                                   # 부모와 맞교환(swap) 금지
            self.next_of[a] = cand                         # 잠정 예약
            self.occ_next[cand] = a
            k = self.occ_now.get(cand)
            if k is not None and k != a and k not in self.next_of:
                if not self.resolve(k, a):                 # 점유자 밀어내기 실패
                    del self.next_of[a]                    # → 예약 롤백, 다음 후보
                    if self.occ_next.get(cand) == a:       # (k가 제자리 예약으로
                        del self.occ_next[cand]            #  덮어썼으면 보존)
                    continue
            return True
        self.next_of[a] = cur                              # 갈 곳 없음 → 제자리
        self.occ_next[cur] = a
        return False


def step(positions, dists, edge_cost, wait_cost, free, priority_order):
    """한 틱 진행. priority_order: 이번 틱에 처리할 순서로 정렬된 agent id 리스트.
    반환: 전 agent의 다음 칸 dict(새 객체)."""
    ps = _PIBTStep(positions, dists, edge_cost, wait_cost, free)
    for a in priority_order:
        if a not in ps.next_of:
            ps.resolve(a)
    return dict(ps.next_of)


def run(free, starts, goals, edge_cost=None, wait_cost=None, max_steps=200):
    """starts/goals: {agent_id: (r, c)}.
    우선순위: 제자리 대기 누적이 큰 로봇 우선(starvation 방지), 동률이면
    agent id 오름차순 — 매 틱 결정론적으로 동일 순서 (B-1b).
    반환: history — list[dict agent->pos], 인덱스 0이 초기 배치.
    max_steps 안에 전원 도달 못 하면 SystemExit(정체)."""
    H, W = free.shape
    if edge_cost is None:
        edge_cost = np.ones((H, W, 4), dtype=np.float64)
    if wait_cost is None:
        wait_cost = np.ones((H, W), dtype=np.float64)
    agents = list(starts)
    positions = dict(starts)
    dists = {a: dist_map(free, goals[a]) for a in agents}
    wait_counter = {a: 0 for a in agents}
    history = [dict(positions)]

    for _ in range(max_steps):
        if all(positions[a] == goals[a] for a in agents):
            return history
        priority_order = sorted(agents, key=lambda a: (-wait_counter[a], a))
        positions = step(positions, dists, edge_cost, wait_cost, free,
                         priority_order)
        for a in agents:
            if positions[a] == goals[a] or positions[a] != history[-1][a]:
                wait_counter[a] = 0
            else:
                wait_counter[a] += 1
        history.append(dict(positions))
    if all(positions[a] == goals[a] for a in agents):
        return history
    stuck = {a for a in agents if positions[a] != goals[a]}
    raise SystemExit(f"PIBT 정체: {max_steps}스텝 내 미도달 {stuck}")
