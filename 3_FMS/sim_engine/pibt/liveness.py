# -*- coding: utf-8 -*-
from .geometry import occupied
from .hgraph import hgraph_for

# 대기 상승(escalation) — 라이브니스 장치 (설계 §6, 2026-09-02 실측 근거):
#   2칸 차체에서는 뒤차가 앞차의 뒤 칸을 원하면 앞차는 회전도 못 한다(스윙에 그 칸이
#   포함) → 밀어내기가 연쇄 실패. 이때 매 로봇의 최선 후보는 늘 "대기"(d+1)라
#   회전(d+4)·후진(d+4)을 아무도 택하지 않아 매듭이 영구화된다(30대 스트레스에서
#   13대가 500틱+ 정지 실측). GRACE틱 넘게 기다린 로봇의 대기 점수를 매 틱 올려
#   스스로 우회·후진하게 한다. 평상시(짧은 대기)에는 작동하지 않는다.
WAIT_ESC_GRACE = 10   # 이 틱 수까지의 대기는 정상 (-194 로 틱이 2.07배 잘아졌다: 5 → 10)
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
REPLAN_AFTER = 16     # -194: 틱이 잘아진 만큼 (8 → 16)
REPLAN_RADIUS = 3
REPLAN_HOLD = 12      # 재계획 거리장 유지 틱 (-194: 6 → 12). 매 틱 재계산하면 두 로봇이 서로를 장애물로
                      # 동시에 재계획→동시 회전→되돌림의 대칭 진동(주기 4틱, 실측)

# 우회 비용 상한 (-247, D). 재계획은 「가까운 길이 막혔다」만 보고 우회로를 주는데 **그 우회가
# 얼마나 비싼지는 안 본다.** 반경 3 안의 로봇 하나 때문에 목표 5칸 앞에서 201칸짜리 길을 받는다
# (12대 600건 실측: 재계획 9,370건 중 추가 30칸 초과가 1.8 %, 최대 +202칸).
# 그러면 stag 가 평소 거리장으로 재이므로 멀어지는 내내 안 풀리고, 재계획이 12틱마다 다시 걸려
# 로봇이 74칸을 갔다가 **같은 칸으로 돌아온다**(679틱 = 189초, 진전 0).
# 몇 틱 기다리는 쪽이 압도적으로 싼 자리다 — 1칸이 MOVE_TICKS 틱이므로 N칸 우회는 4N 틱이다.
# 0 = 상한 없음(지금과 비트 동일).
REPLAN_MAX_EXTRA = 0


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

    def __init__(self, free, edge_cost, turn_cost, hold=REPLAN_HOLD, max_extra=REPLAN_MAX_EXTRA):
        self.cache = ReplanCache(free, edge_cost, turn_cost)
        self.hold_len = hold
        self.max_extra = max_extra      # 우회 추가 비용 상한 [칸]. 0 = 없음 (-247)
        self.hold = {}          # agent -> (dist, 만료 tick, goal)

    def dist_for(self, a, t, states, extra, goal, base, stag):
        """base: 평소 거리장. 정체(stag > REPLAN_AFTER)면 재계획 거리장을 만들어 hold_len틱
        유지한다. 유지 중엔 상대가 움직여도 계획을 바꾸지 않는다 (진동 방지)."""
        h = self.hold.get(a)
        if h is not None and t < h[1] and h[2] == goal and h[0][states[a]] >= 0:
            return h[0]
        if stag > REPLAN_AFTER:
            dm = self.cache.dist(states, extra, a, goal)
            if dm[states[a]] >= 0 and self._worth(dm, base, states[a]):
                self.hold[a] = (dm, t + self.hold_len, goal)
                return dm
        self.hold.pop(a, None)
        return base

    def _worth(self, dm, base, s):
        """우회가 상한 안인가 (-247). 평소 거리가 -1(원래 못 감)이면 우회가 유일한 길이라 항상 쓴다."""
        if not self.max_extra:
            return True
        b = base[s]
        return b < 0 or dm[s] - b <= self.max_extra


class ReplanCache:
    """(goal, 막힌 칸 집합) → 재계획 거리장. 정체 상황은 드물어 크기가 작다.
    2026-09-04: HGraph.dist 증분 복구 — 기본 거리장에서 막힌 칸의 영향을 받은 상태만 다시 푼다 (전체 재계산과 값 동일)."""

    def __init__(self, free, edge_cost, turn_cost, limit=512):
        self.free, self.edge_cost, self.turn_cost, self.limit = free, edge_cost, turn_cost, limit
        self.graph = hgraph_for(free, edge_cost, turn_cost)
        self.cache = {}

    def dist(self, states, extra, me, goal):
        H, W = self.free.shape
        r0, c0 = states[me][:2]
        blocked = set()
        for a, s in states.items():
            if a == me:
                continue
            for (r, c) in set(occupied(s)) | set(extra.get(a, ())):
                if max(abs(r - r0), abs(c - c0)) <= REPLAN_RADIUS and 0 <= r < H and 0 <= c < W and self.free[r, c]:
                    blocked.add((r, c))
        key = (goal, frozenset(blocked))
        if key not in self.cache:
            if len(self.cache) >= self.limit:
                self.cache.clear()
            self.cache[key] = self.graph.dist(goal, blocked)          # 증분 복구 (HGraph.dist)
        return self.cache[key]

