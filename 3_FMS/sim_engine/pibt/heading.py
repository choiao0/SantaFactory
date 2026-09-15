# -*- coding: utf-8 -*-

import numpy as np

from .geometry import (DIRS, MOVE_TICKS, REVERSE_FACTOR, TURN_COST, TURN_TICKS, _inb,
                       front_cells, front_swing_on, occupied, stay_map_h, swing_cells,
                       turn_mask, turn_ok, valid_state)
from .hgraph import dist_map_h
from .liveness import Replanner, Stagnation, wait_bias


def candidates_h(s, dist, edge_cost, wait_cost, free, turn_cost, bias=0.0):
    """s에서 가능한 다음 상태 후보를 score 오름차순으로: [(상태, 점유칸 집합, soft 칸 집합), ...].
    score = 액션 비용 + dist[결과 상태]. 대기 후보에는 bias(대기 상승)가 더해진다.
    대기 후보의 점유칸은 호출자가 extra(회전 중 스윙)까지 합쳐 덮어쓴다.
    soft 칸(-203) = 회전 중 코가 스치는 앞 2칸: 다른 로봇의 **축**이 있거나 들어오면 못 돈다(뒤 칸은 무관)."""
    r, c, h = s
    none = frozenset()
    scored = []
    if dist[r, c, h] >= 0:
        # 목표 상태(dist 0)에는 대기 상승을 붙이지 않는다 (-204 물리 팀 보고 2026-09-14): bias 를 안고 도착하면 "나가기(1+d) < 대기(1+bias)"
        # 로 첫 틱에 목표를 떠나고, 뒤쪽 1칸은 후진 배율 3 으로 d=3 이라 "돌아오기(3) < 대기(1+bias+3)" 도 성립해 왕복이 굳는다.
        # Stagnation 은 2틱 연속 머물러야 리셋되므로(seed 11) 스스로 못 풀린다. kernel 은 도착 즉시 상태 전이라 무관(비트 동일).
        b = 0.0 if dist[r, c, h] == 0 else bias
        scored.append((wait_cost[r, c] + b + dist[r, c, h], 0, s, frozenset(occupied(s)), none))
    dr, dc = DIRS[h]
    rr, cc = r + dr, c + dc
    if _inb(free, (rr, cc)) and dist[rr, cc, h] >= 0:
        scored.append((edge_cost[r, c, h] + dist[rr, cc, h], 1, (rr, cc, h),
                       frozenset(((rr, cc), (r, c))), none))
    for i, h2 in enumerate(((h + 1) % 4, (h - 1) % 4)):
        if dist[r, c, h2] >= 0 and turn_ok(free, r, c, h, h2):
            scored.append((turn_cost + dist[r, c, h2], 2 + i, (r, c, h2),
                           frozenset({(r, c)} | swing_cells(r, c, h, h2)), frozenset(front_cells(r, c, h, h2))))
    br, bc = r - dr, c - dc                            # 후진: pos→rear, rear→rear의 뒤
    if valid_state(free, (br, bc, h)) and dist[br, bc, h] >= 0:
        scored.append((edge_cost[r, c, (h + 2) % 4] * REVERSE_FACTOR + dist[br, bc, h],
                       4, (br, bc, h), frozenset(occupied((br, bc, h))), none))
    scored.sort(key=lambda x: (x[0], x[1]))
    return [(st, cells, soft) for _, _, st, cells, soft in scored]


class _PIBTStepH:
    """헤딩 모델 한 틱: 칸 하나 → 칸 집합으로 일반화한 우선순위 상속 + 백트래킹."""

    def __init__(self, states, dists, edge_cost, wait_cost, free, turn_cost, extra,
                 bias, sec_map=None, sec_limit=0, sec_free=(), forbid=None, forbid_axle=None, soft_hold=None):
        self.states = states
        self.forbid = forbid or {}             # agent -> 금지 칸 (-79 대치: 지는 쪽은 이기는 쪽의 몸·원하는 자리에 못 들어간다)
        # agent -> 축 금지 칸 (-79): 다음 상태의 축이 여기 있으면 안 됨. 대치의 지는 쪽(이기는 쪽 soft 칸) + soft 밀기로 임시 부여.
        self.forbid_axle = {a: set(v) for a, v in (forbid_axle or {}).items()}
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
        self.release_failed_push = turn_mask() is not None or front_swing_on()   # 회전 발자국 모드(exact)에서만 (-203)
        # soft 칸 (-203): 회전하는 로봇의 앞 2칸. 축(pos)만 막는다 — 지금 축이 있거나(pos_now) 이번 틱 축이 들어오는(pos_next)
        # 로봇이 있으면 그 회전은 안 되고, 반대로 soft 예약된 칸에는 다른 로봇이 축을 들여놓지 못한다. 뒤 칸은 자유.
        self.pos_now = {s[:2]: a for a, s in states.items()}
        self.pos_next = {}      # cell -> 이번 틱 축이 놓일 agent
        self.soft_next = dict(soft_hold or {})   # cell -> soft 예약 agent. 회전 진행 중(-194 다틱) 로봇의 soft 칸은 미리 채워 온다 (-79)
        self.next_soft = {}     # agent -> soft 칸 집합
        # 구간 대수 제한 (S15P21A106-193). sec_map 은 칸 -> 구간번호(-1 = 구간 밖).
        self.sec_map = sec_map
        self.sec_limit = sec_limit
        self.sec_free = frozenset(sec_free)    # 정체 판정된 로봇 = 정원 면제
        self.denied = set()                    # 이번 틱 정원 때문에 후보가 막힌 agent
        self.sec_now = {a: self._secs(c) for a, c in self.now_cells.items()} if self.on else {}
        self.sec_cnt = {}                      # 구간 -> 그 구간에 있는 로봇 수
        for secs in self.sec_now.values():     # 아직 안 정해진 로봇은 현 위치로 센다
            for s in secs:
                self.sec_cnt[s] = self.sec_cnt.get(s, 0) + 1

    @property
    def on(self):
        return self.sec_map is not None and self.sec_limit > 0

    def _secs(self, cells):
        """칸 집합이 걸친 구간 번호들. 몸이 두 칸이라 두 구간에 걸칠 수 있다."""
        m = self.sec_map
        out = set()
        for r, c in cells:
            k = int(m[r, c])
            if k >= 0:
                out.add(k)
        return out

    def _entry_ok(self, a, cells):
        """정원이 찬 구간으로 **진입**하는가. 안→안·안→밖·제자리는 항상 허용한다.

        퇴출을 막지 않으니 구간은 언제나 비워질 수 있다. 그래도 순환 대기는 막지 못한다 —
        A 가 S1 을, B 가 S2 를 기다리는데 A 가 S2 에, B 가 S1 에 있으면 둘 다 제자리가 된다.
        통행 칸 전체를 타일링하면 구간 밖 대피처가 없어 이게 실제로 난다 (실측: 블록 4·6·8 ×
        정원 1·2·3, 8가지 전부 STALL). 그래서 정체한 로봇은 정원에서 푼다 (sec_free). (-193)
        """
        if not self.on or a in self.sec_free:
            return True
        now = self.sec_now[a]
        for s in self._secs(cells) - now:
            if self.sec_cnt.get(s, 0) >= self.sec_limit:
                self.denied.add(a)
                return False
        return True

    def _count(self, a, cells, sign):
        """예약 확정(+1)·되돌리기(-1): 로봇 하나의 귀속을 현 위치 ↔ 예약 위치로 옮긴다.

        즉 sec_cnt[s] 는 항상 "미정 로봇은 지금 있는 구간, 확정 로봇은 갈 구간" 기준
        대수다. 그래서 우선순위 순서대로 자리가 찬다 — 먼저 결정된 쪽이 들어간다.
        """
        if not self.on:
            return
        now, nxt = self.sec_now[a], self._secs(cells)
        for s in nxt - now:
            self.sec_cnt[s] = self.sec_cnt.get(s, 0) + sign
        for s in now - nxt:
            self.sec_cnt[s] = self.sec_cnt.get(s, 0) - sign

    def _reserve(self, a, s2, cells, soft=frozenset()):
        self.next_of[a] = s2
        self.next_cells[a] = cells
        for cell in cells:
            self.occ_next[cell] = a
        self.pos_next[s2[:2]] = a
        self.next_soft[a] = soft
        for cell in soft:
            self.soft_next[cell] = a
        self._count(a, cells, +1)          # 미정(현 위치) → 확정(예약 위치)로 계수 이전

    def _release(self, a):
        self._count(a, self.next_cells[a], -1)
        for cell in self.next_cells.pop(a):
            if self.occ_next.get(cell) == a:       # 밀린 쪽이 제자리 예약으로
                del self.occ_next[cell]            # 덮어썼으면 보존
        pos = self.next_of.pop(a)[:2]
        if self.pos_next.get(pos) == a:
            del self.pos_next[pos]
        for cell in self.next_soft.pop(a):
            if self.soft_next.get(cell) == a:
                del self.soft_next[cell]

    def _soft_blocked(self, a, s2, soft):
        """soft 충돌: 내 앞 2칸에 다른 축이 있거나/들어오거나, 내 축이 놓일 칸을 다른 로봇이 soft 예약했다."""
        if self.soft_next.get(s2[:2], a) != a:
            return True
        return any(self.pos_now.get(cell, a) != a or self.pos_next.get(cell, a) != a for cell in soft)

    def _make_room(self, a, cur, soft, parent):
        """soft 밀기(-79 V1b): 회전 후보가 다른 로봇의 **축**(pos_now)에 막혔고 그 로봇들이 아직 미결정이면, 나는 제자리를 예약하고
        그들에게 '축을 soft 칸 밖으로'(forbid_axle) 제약을 준 채 재귀 해결한다 — hard 밀기(_push_occupants)의 축 버전.
        이번 틱 결정된 축(pos_next)이나 이미 정해진 로봇이 막고 있으면 못 밀고 False."""
        if front_swing_on() is False:
            return False
        owners = {self.pos_now[c] for c in soft if self.pos_now.get(c, a) != a}
        if not owners or any(k in self.next_of for k in owners):
            return False
        if any(self.pos_next.get(c, a) != a for c in soft):
            return False
        if parent is not None and self.now_cells[a] & self.now_cells[parent]:
            return False
        self._reserve(a, cur, self.now_cells[a])
        saved = {k: self.forbid_axle.get(k) for k in owners}
        for k in owners:
            self.forbid_axle[k] = set(saved[k] or ()) | set(soft)
        ok = True
        for k in sorted(owners):
            if k in self.next_of:
                # 앞 owner 의 재귀 밀기로 이미 결정된 로봇 — 다시 풀면 예약이 꼬여 점유 겹침(실측 exp22 --section-limit=2).
                # 결정된 축이 soft 밖이면 그대로 두고, 안이면 실패.
                if self.next_of[k][:2] in soft:
                    ok = False
                    break
                continue
            if not self.resolve(k, a):
                ok = False
                if self.release_failed_push:
                    self._release(k)
                break
        for k in owners:
            if saved[k] is None:
                self.forbid_axle.pop(k, None)
            else:
                self.forbid_axle[k] = saved[k]
        if ok:
            return True
        self._release(a)
        return False

    def _push_occupants(self, a, cells):
        """cells 의 현 점유자(자기 제외, 미결정)를 칸 순서대로 밀어낸다. 하나라도 실패하면 False."""
        for cell in sorted(cells):
            k = self.occ_now.get(cell)
            if k is not None and k != a and k not in self.next_of:
                if not self.resolve(k, a):              # 점유자 밀어내기 실패
                    if self.release_failed_push:
                        # 실패한 점유자의 '제자리' 예약을 되돌린다 — 그 예약은 내(a) 예약과 겹쳐서 생긴 것인데 나는 이제 이 후보를
                        # 버린다. 남겨 두면 k 는 이 틱에 다시 결정되지 않아(next_of 에 있음) 앞이 비어 있어도 못 움직인다.
                        # 2칸 차체에선 "내 뒤 칸이 될 자리를 비워 달라"는 밀기가 한 틱에 성립하지 않아(k 가 전진해도 옛 pos 가
                        # k 의 뒤 칸) 매 틱 같은 실패가 되풀이되고, 회전 마스크로 k·a 둘 다 돌 수 없는 자리(존 구석·랙 옆)면
                        # 영구 정지가 된다 (-203 실측: 28대 존 구석 4대 6시간 정지). legacy(v3.3 비트 동일)에는 적용하지 않는다.
                        self._release(k)
                    return False
        return True

    def resolve(self, a, parent=None):
        cur = self.states[a]
        for s2, cells, soft in candidates_h(cur, self.dists[a], self.edge_cost,
                                            self.wait_cost, self.free, self.turn_cost,
                                            self.bias.get(a, 0.0)):
            if s2 == cur:
                cells = self.now_cells[a]                   # 대기 = 현 점유(스윙 포함) 유지
            if any(self.occ_next.get(cell, a) != a for cell in cells):
                continue                                    # 타 agent 예약 칸
            if cells & self.forbid.get(a, frozenset()):
                continue                                    # 대치 금지 칸 (-79 V1)
            fa = self.forbid_axle.get(a)
            if fa and s2[:2] in fa:
                continue                                    # 축 금지 칸 (-79 V1b)
            if self._soft_blocked(a, s2, soft):
                if self._make_room(a, cur, soft, parent):
                    return True                             # soft 밀기 성공: 이번 틱 대기, 다음 틱 회전 (-79 V1b)
                continue                                    # 앞 칸 축 충돌 (-203)
            if parent is not None and cells & self.now_cells[parent]:
                continue                                    # 부모와 맞교환(swap) 금지
            if not self._entry_ok(a, cells):
                continue                                    # 정원 찬 구간 진입 금지
            self._reserve(a, s2, cells, soft)
            if self._push_occupants(a, cells):
                return True
            self._release(a)
        self._reserve(a, cur, self.now_cells[a])            # 갈 곳 없음 → 제자리
        return False


def step_h(states, dists, edge_cost, wait_cost, free, priority_order,
           turn_cost=None, extra=None, bias=None, sec_map=None, sec_limit=0, sec_free=(), forbid=None,
           forbid_axle=None, soft_hold=None):
    """헤딩 모델 한 틱. states: {a: (r,c,h)}, dists: {a: (H,W,4)},
    extra: {a: 추가 점유 칸(회전 중 스윙)}, bias: {a: 대기 점수 가산(wait_bias)}.
    sec_map/sec_limit: 구간 대수 제한(-193) — sec_limit 0 이면 장치가 통째로 꺼진다.
    반환 (다음 상태 dict, 예약 칸 dict, 정원 때문에 막힌 agent 집합)."""
    if turn_cost is None:
        turn_cost = float(TURN_COST)
    ps = _PIBTStepH(states, dists, edge_cost, wait_cost, free, turn_cost,
                    extra or {}, bias or {}, sec_map, sec_limit, sec_free, forbid, forbid_axle, soft_hold)
    for a in priority_order:
        if a not in ps.next_of:
            ps.resolve(a)
    return dict(ps.next_of), dict(ps.next_cells), ps.denied


def _occupancy(states, extra):
    """cell -> agent (몸 + 스윙 칸)."""
    occ = {}
    for a, s in states.items():
        for cell in set(occupied(s)) | set(extra.get(a, ())):
            occ[cell] = a
    return occ


def _action_kind(s, st):
    if st == s:
        return "wait"
    if st[:2] == s[:2]:
        return "turn"
    return "fwd" if (st[0] - s[0], st[1] - s[1]) == DIRS[s[2]] else "rev"


def dump_candidates_h(states, dists, goals, extra, bias, free, edge_cost, wait_cost,
                      turn_cost, only=None, label=lambda a: f"agent{a}"):
    """정체 진단: 각 agent의 후보 상태·거리·차단 agent를 출력 (run_h / sim_v2 공용)."""
    occ = _occupancy(states, extra)
    axle = {s[:2]: a for a, s in states.items()}
    for a, s in states.items():
        if only is not None and a not in only:
            continue
        d = dists[a]
        print(f"  {label(a)} {s} goal={goals[a]} dist={d[s]:.1f} bias={bias.get(a, 0):.0f}")
        for st, cc, soft in candidates_h(s, d, edge_cost, wait_cost, free, turn_cost):
            blk = {cell: occ[cell] for cell in cc if occ.get(cell, a) != a}
            blk.update({cell: axle[cell] for cell in soft if axle.get(cell, a) != a})    # soft: 앞 칸의 축
            print(f"     {_action_kind(s, st):4s} -> {st} dist={d[st]:.1f} blocked_by={blk}")


def _default_costs_h(free, edge_cost, wait_cost, turn_cost, turn_ticks):
    H, W = free.shape
    if edge_cost is None:
        edge_cost = np.ones((H, W, 4), dtype=np.float64)
    if wait_cost is None:
        wait_cost = np.ones((H, W), dtype=np.float64)
    if turn_cost is None:
        # 거리장 가중은 '전진 1칸 대비 배율'(geometry.TURN_COST = TURN_TICKS / MOVE_TICKS). 예전엔 float(turn_ticks)=5.0 을 써
        # 커널(1.25)과 거리장이 갈려 같은 시드에서 다른 계획이 나왔다 (물리 팀 제안 2026-09-15, 틱 모델 정합).
        turn_cost = float(TURN_COST)
    return edge_cost, wait_cost, turn_cost


def _all_at_goal_h(states, goals, agents):
    return all(states[a][:2] == goals[a] for a in agents)


def _dists_now_h(agents, states, goals, dists, busy, replan, stag, extra, t, free):
    """이번 틱 거리장: 회전 중 = stay, 미도달 = 재계획 거리장(정체 시), 도달 = 기본."""
    d_now = {}
    for a in agents:
        if busy[a] > 0:
            d_now[a] = stay_map_h(free, states[a])
        elif states[a][:2] != goals[a]:
            d_now[a] = replan.dist_for(a, t, states, extra, goals[a], dists[a], stag.get(a))
        else:
            d_now[a] = dists[a]
    return d_now


def _after_step_h(agents, states, new, goals, dists, busy, swing, stag, age, turn_ticks, move_ticks=MOVE_TICKS):
    """회전·이동 시작/진행 부기, 정체 카운터, 우선순위 age 갱신.
    커널(`kernel/core.py` `_advance`)과 같은 틱 모델: 회전은 turn_ticks 틱(스윙 칸 점유), 전진·후진은 move_ticks 틱
    (칸은 첫 틱에 옮기고 나머지는 busy 로 제자리 — 몸 2칸이 새 칸 + 떠난 칸을 그대로 쥔다). 예전 run_h 는 전진 1틱이라
    커널과 거리장·점유 시간이 갈렸다 (틱 모델 정합, 2026-09-15)."""
    for a in agents:
        s0, s1 = states[a], new[a]
        if s1[:2] == s0[:2] and s1[2] != s0[2]:          # 회전 시작
            busy[a] = turn_ticks - 1
            swing[a] = swing_cells(s0[0], s0[1], s0[2], s1[2])
        elif s1[:2] != s0[:2]:                            # 전진·후진 시작
            busy[a] = move_ticks - 1
            swing[a] = set()
        elif busy[a] > 0:
            busy[a] -= 1
            if busy[a] == 0:
                swing[a] = set()
        stag.update(a, goals[a], dists[a][s1])
        age[a] = 0 if s1[:2] == goals[a] else age[a] + 1


def _raise_stuck_h(agents, states, goals, stag, busy, history, d_now, extra, bias,
                   free, edge_cost, wait_cost, turn_cost, max_steps):
    stuck = {a: states[a] for a in agents if states[a][:2] != goals[a]}
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


def run_h(free, starts, goals, edge_cost=None, wait_cost=None, max_steps=200,
          turn_cost=None, turn_ticks=TURN_TICKS, move_ticks=MOVE_TICKS):
    """starts: {a: (r,c,h)}, goals: {a: (r,c)}. 커널과 같은 틱 모델(-194·틱 모델 정합 2026-09-15):
    회전은 turn_ticks 틱(첫 틱에 방향 전환, 나머지는 스윙 칸을 점유한 채 대기), 전진·후진은 move_ticks 틱
    (첫 틱에 칸을 옮기고 나머지는 제자리). 거리장 turn_cost 기본 = TURN_COST(전진 1칸 대비 배율).
    반환 (history, cells_hist): history[t] = {a: 상태}, cells_hist[t] = {a: t→t+1
    동안 점유·예약한 칸}. 전원 도달 못 하면 SystemExit. max_steps 는 틱 — 전진 1칸이 move_ticks 틱임에 맞춰 잡을 것."""
    edge_cost, wait_cost, turn_cost = _default_costs_h(free, edge_cost, wait_cost, turn_cost, turn_ticks)
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
    d_now, extra, bias = {}, {}, {}   # 정체 진단용 (마지막 틱 값)

    for t in range(max_steps):
        if _all_at_goal_h(states, goals, agents):
            return history, cells_hist
        # 우선순위는 단조 증가하는 age로 — 정체 카운터(stag)로 매기면 밀린 쪽이 다음 틱에
        # 우선권을 얻어 되밀고, 매 틱 뒤집히며 정면 핑퐁 진동이 된다 (seed 11 실측).
        prio = sorted(agents, key=lambda a: (-age[a], a))
        extra = {a: swing[a] for a in agents if busy[a] > 0}
        d_now = _dists_now_h(agents, states, goals, dists, busy, replan, stag, extra, t, free)
        bias = {a: wait_bias(stag.get(a)) for a in agents}
        new, cells, _ = step_h(states, d_now, edge_cost, wait_cost, free, prio,
                               turn_cost, extra, bias)
        _after_step_h(agents, states, new, goals, dists, busy, swing, stag, age, turn_ticks, move_ticks)
        states = new
        history.append(dict(states))
        cells_hist.append(cells)
    if _all_at_goal_h(states, goals, agents):
        return history, cells_hist
    _raise_stuck_h(agents, states, goals, stag, busy, history, d_now, extra, bias,
                   free, edge_cost, wait_cost, turn_cost, max_steps)
