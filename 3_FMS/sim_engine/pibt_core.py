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
#   contracts/guidance_types.py의 Guidance와 동일한 shape.
#
# 거리항 (docs/2026-09-02_Isaac회전충돌_격자유지_PIBT확장_결정.md §5):
#   dist_map(edge_cost=None) = 비가중 BFS (v1compat·기존 벤치마크 경로, 불변).
#   dist_map(edge_cost=...)  = θ 가중 다익스트라. 후보 score = edge + dist가
#   정합해져 전진(= d)이 대기(= wait + d)를 항상 이김 → 비가중일 때의
#   영구 정체(gain ≥ wait+1)가 사라지고, 비싼 통로는 dist 자체가 커져
#   진입 시점부터 우회가 유도된다.
# ============================================================
from collections import deque
from heapq import heappop, heappush

import numpy as np

DIRS = [(1, 0), (0, 1), (-1, 0), (0, -1)]  # 0=N 1=E 2=S 3=W


def dist_map(free, goal, edge_cost=None):
    """goal까지의 정적 최단 비용. 도달 불가 칸은 -1.
    edge_cost=None → 비가중 BFS(int32, 칸 수).
    edge_cost (H,W,4) → 가중 다익스트라(float64):
        dist[u] = min_d edge_cost[u, d] + dist[u + DIRS[d]]
    u에서 '나가는' 엣지 비용으로, goal에서 역방향(선행 칸 방향)으로 완화한다."""
    H, W = free.shape
    if edge_cost is None:
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

    dm = np.full((H, W), -1.0, dtype=np.float64)
    done = np.zeros((H, W), dtype=bool)
    dm[goal] = 0.0
    pq = [(0.0, goal)]
    while pq:
        dv, (r, c) = heappop(pq)
        if done[r, c]:
            continue
        done[r, c] = True
        for d, (dr, dc) in enumerate(DIRS):
            ur, uc = r - dr, c - dc                  # u + DIRS[d] == (r, c)
            if 0 <= ur < H and 0 <= uc < W and free[ur, uc] and not done[ur, uc]:
                nd = dv + float(edge_cost[ur, uc, d])
                if dm[ur, uc] < 0 or nd < dm[ur, uc]:
                    dm[ur, uc] = nd
                    heappush(pq, (nd, (ur, uc)))
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
    weighted = edge_cost is not None          # 비용이 주어지면 거리항도 가중
    if edge_cost is None:
        edge_cost = np.ones((H, W, 4), dtype=np.float64)
    if wait_cost is None:
        wait_cost = np.ones((H, W), dtype=np.float64)
    agents = list(starts)
    positions = dict(starts)
    dists = {a: dist_map(free, goals[a], edge_cost if weighted else None)
             for a in agents}
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


# ============================================================
# 헤딩 모델 — 상태 (r, c, h), 2칸 점유, 제자리 회전 액션, 스윙 칸 예약
# (설계: docs/2026-09-02_PIBT_헤딩_2칸점유_회전예약_설계.md)
#
#   pos(s)  = (r, c)              앞축(구동축)이 있는 칸 — 칸 중심에 정렬
#   rear(s) = (r, c) - DIRS[h]    뒤 차체(≈1.24m)가 있는 칸
#   occupied(s) = {pos, rear}     로봇 1대 = 2칸
#   valid(s)  ⇔ pos, rear 모두 free (벽에 등을 대고 설 수 없다)
#   액션: 전진(edge_cost) / 좌·우 90° 회전(turn_cost, 스윙 3칸 필요) / 대기
#         / 후진 1칸 (edge_cost[pos, 반대방향] × REVERSE_FACTOR)
#   swing(h→h') = {rear(h), rear(h'), 그 사이 대각 칸}
#
#   후진이 필요한 이유 (2026-09-02 실측): 벽에 붙은 레인(예: 충전기 열 c=108,
#   동쪽 c=109 벽)에서는 벽 쪽으로 뒤 칸이 필요한 방향으로 회전할 수 없어
#   로봇이 레인에 갇힌다. 실제 로봇은 후진 후 회전(3점 회전)으로 빠져나온다.
#
# 위의 칸 모델(dist_map/step/run)은 그대로 두고(v1compat·B-1e 보존), 헤딩
# 모델은 *_h 함수로 병행 제공한다. sim_v2는 --heading 플래그로 선택.
# ============================================================
REAR_CELLS = 1      # 설계 §1: 뒤 차체 1.24m → 뒤 칸 1개 (앞축 위치 실측 후 확정)
TURN_TICKS = 2      # 설계 §1: 90° ≈ 1.75s @0.9rad/s → 2틱 (각속도 실측 후 확정)
REVERSE_FACTOR = 3.0  # 후진 1칸 비용 배율 — 느리고 시야 없는 동작이라 마지막 수단 (3점 회전용)

# 대기 상승(escalation) — 라이브니스 장치 (설계 §6, 2026-09-02 실측 근거):
#   2칸 차체에서는 뒤차가 앞차의 뒤 칸을 원하면 앞차는 회전도 못 한다(스윙에 그 칸이
#   포함) → 밀어내기가 연쇄 실패. 이때 매 로봇의 최선 후보는 늘 "대기"(d+1)라
#   회전(d+4)·후진(d+4)을 아무도 택하지 않아 매듭이 영구화된다(30대 스트레스에서
#   13대가 500틱+ 정지 실측). GRACE틱 넘게 기다린 로봇의 대기 점수를 매 틱 올려
#   스스로 우회·후진하게 한다. 평상시(짧은 대기)에는 작동하지 않는다.
WAIT_ESC_GRACE = 5    # 이 틱 수까지의 대기는 정상(서비스 대기 4틱보다 길게)
WAIT_ESC_RATE = 1.0   # 초과 대기 1틱당 대기 점수 가산
WAIT_ESC_CAP = 20.0   # 가산 상한


def wait_bias(stag):
    """정체 틱 수(거리 개선 없는 연속 틱) → 대기 후보 점수 가산."""
    return min(WAIT_ESC_CAP, WAIT_ESC_RATE * max(0, stag - WAIT_ESC_GRACE))


# 정체 재계획 (stuck re-plan) — 라이브니스 장치 2 (설계 §6):
#   dist는 다른 로봇을 모른다. 벽을 보고 도킹한 로봇이 사방이 막히거나, 목표에
#   주차한 로봇 뒤가 벽이면 밀어내기가 불가한데 dist는 계속 "그 칸으로 가라"고
#   하므로 로봇이 회전↔되돌림을 반복한다(진동, 실측). 정체가 REPLAN_AFTER틱을
#   넘으면 주변(체비쇼프 반경 REPLAN_RADIUS) 로봇 점유 칸을 임시 장애물로 넣고
#   거리장을 다시 계산해 실제 우회로를 준다. 우회로가 없으면 원래 dist로 대기.
REPLAN_AFTER = 8
REPLAN_RADIUS = 3
REPLAN_HOLD = 6       # 재계획 거리장 유지 틱 — 매 틱 재계산하면 두 로봇이 서로를 장애물로
                      # 동시에 재계획→동시 회전→되돌림의 대칭 진동(주기 4틱, 실측)


class Stagnation:
    """agent별 '거리 개선 없음' 연속 틱 수. 진동(회전↔되돌림)도 정체로 잡는다."""

    def __init__(self):
        self.best = {}     # agent -> (goal, 지금까지 최소 dist, 직전 dist)
        self.stag = {}     # agent -> 연속 무개선 틱

    def update(self, a, goal, d):
        g, b, prev = self.best.get(a, (None, None, None))
        settled = d <= 0 and prev is not None and prev <= 0     # 2틱 연속 목표에 머묾
        if g != goal or b is None or d < b or settled:
            # 개선했거나 목표에 '머물러' 있으면 정체 아님. 도착 즉시 리셋하면
            # (a) 홈 로봇의 bias 누적 회전은 막지만, (b) 목표↔옆 칸 핑퐁(0,3,0,3…)도
            # 매번 리셋되어 재계획이 영영 안 걸린다 (seed 11 실측). 그래서 2틱 연속.
            self.best[a] = (goal, d if (g != goal or b is None) else min(b, d), d)
            self.stag[a] = 0
        else:
            self.best[a] = (g, b, d)
            self.stag[a] = self.stag.get(a, 0) + 1
        return self.stag[a]

    def get(self, a):
        return self.stag.get(a, 0)


def stuck_free(free, states, extra, me, radius=REPLAN_RADIUS):
    """me 주변 다른 로봇의 점유 칸을 막은 free 마스크 (재계획용)."""
    f = free.copy()
    r0, c0 = states[me][:2]
    for a, s in states.items():
        if a == me:
            continue
        for (r, c) in set(occupied(s)) | set(extra.get(a, ())):
            if max(abs(r - r0), abs(c - c0)) <= radius:
                f[r, c] = False
    return f


class Replanner:
    """정체 로봇의 거리장 선택: 재계획(주변 로봇 = 장애물) + 히스테리시스(REPLAN_HOLD틱 유지)."""

    def __init__(self, free, edge_cost, turn_cost, hold=REPLAN_HOLD):
        self.cache = ReplanCache(free, edge_cost, turn_cost)
        self.hold_len = hold
        self.hold = {}          # agent -> (dist, 만료 tick, goal)

    def dist_for(self, a, t, states, extra, goal, base, stag):
        """base: 평소 거리장. 정체(stag > REPLAN_AFTER)면 재계획 거리장을 만들어 hold_len틱
        유지한다. 유지 중엔 상대가 움직여도 계획을 바꾸지 않는다 (진동 방지)."""
        h = self.hold.get(a)
        if h is not None and t < h[1] and h[2] == goal and h[0][states[a]] >= 0:
            return h[0]
        if stag > REPLAN_AFTER:
            dm = self.cache.dist(states, extra, a, goal)
            if dm[states[a]] >= 0:
                self.hold[a] = (dm, t + self.hold_len, goal)
                return dm
        self.hold.pop(a, None)
        return base


class ReplanCache:
    """(goal, 막힌 칸 집합) → dist_map_h. 정체 상황은 드물어 크기가 작다."""

    def __init__(self, free, edge_cost, turn_cost, limit=512):
        self.free, self.edge_cost, self.turn_cost, self.limit = free, edge_cost, turn_cost, limit
        self.cache = {}

    def dist(self, states, extra, me, goal):
        f = stuck_free(self.free, states, extra, me)
        blocked = frozenset(zip(*np.nonzero(self.free & ~f)))
        key = (goal, blocked)
        if key not in self.cache:
            if len(self.cache) >= self.limit:
                self.cache.clear()
            self.cache[key] = dist_map_h(f, goal, self.edge_cost, self.turn_cost)
        return self.cache[key]


def rear_cell(r, c, h):
    return (r - DIRS[h][0], c - DIRS[h][1])


def occupied(s):
    r, c, h = s
    return ((r, c), rear_cell(r, c, h))


def _inb(free, rc):
    H, W = free.shape
    return 0 <= rc[0] < H and 0 <= rc[1] < W and free[rc]


def valid_state(free, s):
    r, c, h = s
    return _inb(free, (r, c)) and _inb(free, rear_cell(r, c, h))


def swing_cells(r, c, h, h2):
    """h→h2(90°) 회전 중 뒤 차체가 쓸고 가는 칸 3개."""
    d1, d2 = DIRS[h], DIRS[h2]
    return {rear_cell(r, c, h), rear_cell(r, c, h2),
            (r - d1[0] - d2[0], c - d1[1] - d2[1])}


def turn_ok(free, r, c, h, h2):
    """(r,c)에서 h→h2 회전 가능: 양쪽 상태 valid + 스윙 대각 칸 free."""
    if not (valid_state(free, (r, c, h)) and valid_state(free, (r, c, h2))):
        return False
    d1, d2 = DIRS[h], DIRS[h2]
    return _inb(free, (r - d1[0] - d2[0], c - d1[1] - d2[1]))


_stay_cache_h = {}


def stay_map_h(free, s):
    """서비스 중·회전 중 고정용: 상태 s만 0, 나머지 -1 → 후보가 대기 하나뿐.
    (읽기 전용 캐시 — 틱마다 (H,W,4) 배열을 새로 만들면 헤딩 모델이 10배 느려진다.)"""
    key = (free.shape, s)
    m = _stay_cache_h.get(key)
    if m is None:
        if len(_stay_cache_h) > 4096:
            _stay_cache_h.clear()
        m = np.full(free.shape + (4,), -1.0, dtype=np.float64)
        m[s] = 0.0
        _stay_cache_h[key] = m
    return m


def dist_map_h(free, goal, edge_cost=None, turn_cost=None):
    """(칸, 방향) 그래프 위 goal까지의 최소 비용 (H, W, 4). 도달 불가/invalid 상태는 -1.
    goal 칸의 valid한 모든 방향이 0 (도착 방향 무관). 역방향 다익스트라:
      전진 선행 u=(r-dr, c-dc, h): edge_cost[u, h]     (u가 valid)
      회전 선행 u=(r, c, h±1):    turn_cost           (turn_ok(u→(r,c,h)))"""
    H, W = free.shape
    if edge_cost is None:
        edge_cost = np.ones((H, W, 4), dtype=np.float64)
    if turn_cost is None:
        turn_cost = float(TURN_TICKS)
    dm = np.full((H, W, 4), -1.0, dtype=np.float64)
    done = np.zeros((H, W, 4), dtype=bool)
    pq = []
    for h in range(4):
        if valid_state(free, (goal[0], goal[1], h)):
            dm[goal[0], goal[1], h] = 0.0
            heappush(pq, (0.0, (goal[0], goal[1], h)))
    while pq:
        dv, (r, c, h) = heappop(pq)
        if done[r, c, h]:
            continue
        done[r, c, h] = True
        dr, dc = DIRS[h]
        ur, uc = r - dr, c - dc
        if valid_state(free, (ur, uc, h)) and not done[ur, uc, h]:
            nd = dv + float(edge_cost[ur, uc, h])
            if dm[ur, uc, h] < 0 or nd < dm[ur, uc, h]:
                dm[ur, uc, h] = nd
                heappush(pq, (nd, (ur, uc, h)))
        br, bc = r + dr, c + dc                       # 후진 선행: 한 칸 앞에서 뒤로
        if valid_state(free, (br, bc, h)) and not done[br, bc, h]:
            nd = dv + float(edge_cost[br, bc, (h + 2) % 4]) * REVERSE_FACTOR
            if dm[br, bc, h] < 0 or nd < dm[br, bc, h]:
                dm[br, bc, h] = nd
                heappush(pq, (nd, (br, bc, h)))
        for h1 in ((h + 1) % 4, (h - 1) % 4):
            if not done[r, c, h1] and turn_ok(free, r, c, h1, h):
                nd = dv + turn_cost
                if dm[r, c, h1] < 0 or nd < dm[r, c, h1]:
                    dm[r, c, h1] = nd
                    heappush(pq, (nd, (r, c, h1)))
    return dm


def candidates_h(s, dist, edge_cost, wait_cost, free, turn_cost, bias=0.0):
    """s에서 가능한 다음 상태 후보를 score 오름차순으로: [(상태, 점유칸 집합), ...].
    score = 액션 비용 + dist[결과 상태]. 대기 후보에는 bias(대기 상승)가 더해진다.
    대기 후보의 점유칸은 호출자가 extra(회전 중 스윙)까지 합쳐 덮어쓴다."""
    r, c, h = s
    scored = []
    if dist[r, c, h] >= 0:
        scored.append((wait_cost[r, c] + bias + dist[r, c, h], 0, s, frozenset(occupied(s))))
    dr, dc = DIRS[h]
    rr, cc = r + dr, c + dc
    if _inb(free, (rr, cc)) and dist[rr, cc, h] >= 0:
        scored.append((edge_cost[r, c, h] + dist[rr, cc, h], 1, (rr, cc, h),
                       frozenset(((rr, cc), (r, c)))))
    for i, h2 in enumerate(((h + 1) % 4, (h - 1) % 4)):
        if dist[r, c, h2] >= 0 and turn_ok(free, r, c, h, h2):
            scored.append((turn_cost + dist[r, c, h2], 2 + i, (r, c, h2),
                           frozenset({(r, c)} | swing_cells(r, c, h, h2))))
    br, bc = r - dr, c - dc                            # 후진: pos→rear, rear→rear의 뒤
    if valid_state(free, (br, bc, h)) and dist[br, bc, h] >= 0:
        scored.append((edge_cost[r, c, (h + 2) % 4] * REVERSE_FACTOR + dist[br, bc, h],
                       4, (br, bc, h), frozenset(occupied((br, bc, h)))))
    scored.sort(key=lambda x: (x[0], x[1]))
    return [(st, cells) for _, _, st, cells in scored]


class _PIBTStepH:
    """헤딩 모델 한 틱: 칸 하나 → 칸 집합으로 일반화한 우선순위 상속 + 백트래킹."""

    def __init__(self, states, dists, edge_cost, wait_cost, free, turn_cost, extra,
                 bias):
        self.states = states
        self.dists = dists
        self.edge_cost = edge_cost
        self.wait_cost = wait_cost
        self.free = free
        self.turn_cost = turn_cost
        self.bias = bias                       # agent -> 대기 점수 가산
        self.now_cells = {a: frozenset(set(occupied(s)) | set(extra.get(a, ())))
                          for a, s in states.items()}
        self.occ_now = {}
        for a, cells in self.now_cells.items():
            for cell in cells:
                assert cell not in self.occ_now, \
                    f"시작 점유 겹침: {cell} agent {self.occ_now[cell]} & {a}"
                self.occ_now[cell] = a
        self.next_of = {}       # agent -> 다음 상태
        self.next_cells = {}    # agent -> 예약 칸 집합
        self.occ_next = {}      # cell -> 예약 agent

    def _reserve(self, a, s2, cells):
        self.next_of[a] = s2
        self.next_cells[a] = cells
        for cell in cells:
            self.occ_next[cell] = a

    def _release(self, a):
        for cell in self.next_cells.pop(a):
            if self.occ_next.get(cell) == a:       # 밀린 쪽이 제자리 예약으로
                del self.occ_next[cell]            # 덮어썼으면 보존
        del self.next_of[a]

    def resolve(self, a, parent=None):
        cur = self.states[a]
        for s2, cells in candidates_h(cur, self.dists[a], self.edge_cost,
                                      self.wait_cost, self.free, self.turn_cost,
                                      self.bias.get(a, 0.0)):
            if s2 == cur:
                cells = self.now_cells[a]                   # 대기 = 현 점유(스윙 포함) 유지
            if any(self.occ_next.get(cell, a) != a for cell in cells):
                continue                                    # 타 agent 예약 칸
            if parent is not None and cells & self.now_cells[parent]:
                continue                                    # 부모와 맞교환(swap) 금지
            self._reserve(a, s2, cells)
            ok = True
            for cell in sorted(cells):
                k = self.occ_now.get(cell)
                if k is not None and k != a and k not in self.next_of:
                    if not self.resolve(k, a):              # 점유자 밀어내기 실패
                        ok = False
                        break
            if not ok:
                self._release(a)
                continue
            return True
        self._reserve(a, cur, self.now_cells[a])            # 갈 곳 없음 → 제자리
        return False


def step_h(states, dists, edge_cost, wait_cost, free, priority_order,
           turn_cost=None, extra=None, bias=None):
    """헤딩 모델 한 틱. states: {a: (r,c,h)}, dists: {a: (H,W,4)},
    extra: {a: 추가 점유 칸(회전 중 스윙)}, bias: {a: 대기 점수 가산(wait_bias)}.
    반환 (다음 상태 dict, 예약 칸 dict)."""
    if turn_cost is None:
        turn_cost = float(TURN_TICKS)
    ps = _PIBTStepH(states, dists, edge_cost, wait_cost, free, turn_cost,
                    extra or {}, bias or {})
    for a in priority_order:
        if a not in ps.next_of:
            ps.resolve(a)
    return dict(ps.next_of), dict(ps.next_cells)


def dump_candidates_h(states, dists, goals, extra, bias, free, edge_cost, wait_cost,
                      turn_cost, only=None, label=lambda a: f"agent{a}"):
    """정체 진단: 각 agent의 후보 상태·거리·차단 agent를 출력 (run_h / sim_v2 공용)."""
    occ = {}
    for a, s in states.items():
        for cell in set(occupied(s)) | set(extra.get(a, ())):
            occ[cell] = a
    for a, s in states.items():
        if only is not None and a not in only:
            continue
        d = dists[a]
        print(f"  {label(a)} {s} goal={goals[a]} dist={d[s]:.1f} bias={bias.get(a, 0):.0f}")
        for st, cc in candidates_h(s, d, edge_cost, wait_cost, free, turn_cost):
            kind = ("wait" if st == s else "turn" if st[:2] == s[:2]
                    else "fwd" if (st[0] - s[0], st[1] - s[1]) == DIRS[s[2]] else "rev")
            blk = {cell: occ[cell] for cell in cc if occ.get(cell, a) != a}
            print(f"     {kind:4s} -> {st} dist={d[st]:.1f} blocked_by={blk}")


def run_h(free, starts, goals, edge_cost=None, wait_cost=None, max_steps=200,
          turn_cost=None, turn_ticks=TURN_TICKS):
    """starts: {a: (r,c,h)}, goals: {a: (r,c)}. 회전은 turn_ticks 틱 소모
    (첫 틱에 방향 전환, 나머지는 스윙 칸을 점유한 채 대기).
    반환 (history, cells_hist): history[t] = {a: 상태}, cells_hist[t] = {a: t→t+1
    동안 점유·예약한 칸}. 전원 도달 못 하면 SystemExit."""
    H, W = free.shape
    if edge_cost is None:
        edge_cost = np.ones((H, W, 4), dtype=np.float64)
    if wait_cost is None:
        wait_cost = np.ones((H, W), dtype=np.float64)
    if turn_cost is None:
        turn_cost = float(turn_ticks)
    agents = list(starts)
    states = dict(starts)
    for a, s in states.items():
        assert valid_state(free, s), f"agent{a} 시작 상태 invalid: {s}"
    dists = {a: dist_map_h(free, goals[a], edge_cost, turn_cost) for a in agents}
    for a in agents:
        assert dists[a][states[a]] >= 0, f"agent{a} 시작에서 목표 도달 불가: {states[a]}"
    busy = {a: 0 for a in agents}
    swing = {a: set() for a in agents}
    stag = Stagnation()
    replan = Replanner(free, edge_cost, turn_cost)
    for a in agents:
        stag.update(a, goals[a], dists[a][states[a]])
    age = {a: 0 for a in agents}      # 목표 미도달 연속 틱 — 원 PIBT 우선순위 (단조 증가)
    history, cells_hist = [dict(states)], []

    def at_goal(a):
        return states[a][:2] == goals[a]

    for t in range(max_steps):
        if all(at_goal(a) for a in agents):
            return history, cells_hist
        # 우선순위는 단조 증가하는 age로 — 정체 카운터(stag)로 매기면 밀린 쪽이 다음 틱에
        # 우선권을 얻어 되밀고, 매 틱 뒤집히며 정면 핑퐁 진동이 된다 (seed 11 실측).
        prio = sorted(agents, key=lambda a: (-age[a], a))
        extra = {a: swing[a] for a in agents if busy[a] > 0}
        d_now = {}
        for a in agents:
            if busy[a] > 0:
                d_now[a] = stay_map_h(free, states[a])
            elif not at_goal(a):
                d_now[a] = replan.dist_for(a, t, states, extra, goals[a], dists[a], stag.get(a))
            else:
                d_now[a] = dists[a]
        bias = {a: wait_bias(stag.get(a)) for a in agents}
        new, cells = step_h(states, d_now, edge_cost, wait_cost, free, prio,
                            turn_cost, extra, bias)
        for a in agents:
            s0, s1 = states[a], new[a]
            if s1[:2] == s0[:2] and s1[2] != s0[2]:          # 회전 시작
                busy[a] = turn_ticks - 1
                swing[a] = swing_cells(s0[0], s0[1], s0[2], s1[2])
            elif busy[a] > 0:
                busy[a] -= 1
                if busy[a] == 0:
                    swing[a] = set()
            stag.update(a, goals[a], dists[a][s1])
            age[a] = 0 if s1[:2] == goals[a] else age[a] + 1
        states = new
        history.append(dict(states))
        cells_hist.append(cells)
    if all(at_goal(a) for a in agents):
        return history, cells_hist
    stuck = {a: states[a] for a in agents if not at_goal(a)}
    print(f"[정체 진단] 미도달 {len(stuck)}대 (stag: {[stag.get(a) for a in stuck]}, "
          f"busy: {[busy[a] for a in stuck]})")
    for a in stuck:
        print(f"  agent{a} 최근 상태: {[h[a] for h in history[-8:]]}")
    near = set(stuck)
    for a in list(stuck):
        r0, c0 = states[a][:2]
        near |= {b for b in agents if max(abs(states[b][0] - r0), abs(states[b][1] - c0)) <= 3}
    dump_candidates_h(states, d_now, goals, extra, bias, free, edge_cost, wait_cost,
                      turn_cost, only=near)
    raise SystemExit(f"PIBT(헤딩) 정체: {max_steps}스텝 내 미도달 {stuck}")
