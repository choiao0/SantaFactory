# -*- coding: utf-8 -*-
"""대치(standoff) 상태기계 V2 단위 테스트 (S15P21A106-79 B4 D2, 2026-09-15).

규칙 R1~R5 (docs/2026-09-15_S15P21A106-79_B4_V2_대치해소_진단과_규칙.md, 정리본 docs/이동계층_PIBT.md):
  R1 인내 — 회전 중 로봇의 임시 예약에만 막힌 로봇은 대기 상승 0
  R2 감지 — 상대가 회전 중(busy)이어도 대치 상대
  R3 역할 — 움직일 수 있는 쪽이 진다
  R5 재판정 — hd_after 뒤 L 이 못 움직이고 W 는 움직일 수 있으면 교대 1회, 상한 뒤 해제
장면은 실측 STALL 을 축소한 것: exp16(벽 앞 후진만 가능한 로봇 vs 회전하려는 로봇), 시드 42(soft_hold 위상 잠금).
커널은 맵·스테이션 없이 최소 필드만 채운 객체로 만든다 (헤딩 이동 코드만 부른다).
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pibt.geometry as geo  # noqa: E402
from fms_kernel import FmsKernel, KernelConfig  # noqa: E402
from kernel.states import TO_PICK  # noqa: E402
from pibt.geometry import occupied, stay_map_h, swing_cells  # noqa: E402
from pibt.liveness import Stagnation  # noqa: E402


@pytest.fixture(autouse=True)
def _front4():
    geo.configure(front_swing=True, front_diag=True)      # exact,front 4칸 (마스크 없음 = 벽만 회전을 막는다)
    yield
    geo.reset()


def _kernel(free, robots):
    """robots: {rid: dict(pos, h, goal, stag=0, busy=0, swing=set(), swing_soft=set())}."""
    k = FmsKernel.__new__(FmsKernel)
    k.free, (k.H, k.W) = free, free.shape
    k.edge_cost, k.wait_cost, k.turn_cost = np.ones(free.shape + (4,)), np.ones(free.shape), 1.25
    k.cfg = KernelConfig(footprint="exact,front")
    k._dist_cache_h, k._stag = {}, Stagnation()
    k.robots, k.yield_events, k.standoffs, k.standoff_swaps = {}, [], 0, 0
    for rid, spec in robots.items():
        rb = dict(state=TO_PICK, busy=0, swing=set(), swing_soft=set(), hd_peer=None, hd_role=None, hd_until=-1,
                  hd_swapped=False, hd_t0=-1, yield_peer=None, yield_hold=False, leave_from=None, goal_t=0)
        rb.update({kk: v for kk, v in spec.items() if kk != "stag"})
        k.robots[rid] = rb
        k._stag.stag[rid] = spec.get("stag", 0)
    k.rids = list(k.robots)
    return k


def _states(k):
    return {rid: (rb["pos"][0], rb["pos"][1], rb["h"]) for rid, rb in k.robots.items()}


def _dists(k, states):
    return {rid: stay_map_h(k.free, states[rid]) if rb["busy"] else k.dmap_h(rb["goal"]) for rid, rb in k.robots.items()}


def _extra(k):
    return {rid: rb["swing"] for rid, rb in k.robots.items() if rb["busy"] > 0}


# ---- exp16 축소 장면: r0 (5,2,0) 는 서쪽으로 돌고 싶고(스윙에 (5,3)), r1 (6,3,0) 은 벽 앞·양옆 벽이라 후진만 가능 ----
def _exp16():
    free = np.ones((8, 6), dtype=bool)
    free[7, :] = False                       # r1 앞 벽
    free[6, 2] = free[6, 4] = False          # r1 양옆 벽 → 회전 불가
    k = _kernel(free, {0: dict(pos=(5, 2), h=0, goal=(5, 0), stag=30),
                       1: dict(pos=(6, 3), h=0, goal=(1, 3), stag=30)})
    return k


def test_r3_movable_side_loses_exp16_shape():
    k = _exp16()
    states = _states(k)
    body, axle = k._owners(states, {})
    jd = k._judge_dists(0, 1, states)
    assert not k._can_move(1, 0, states, jd, body, axle)     # r1: 후진 칸이 r0 스윙 wish, 자기 축이 r0 soft wish
    assert k._can_move(0, 1, states, jd, body, axle)         # r0: 후진·다른 쪽 회전 가능
    order = {0: 0, 1: 1}                                     # 우선순위는 r0 앞 — V1 이면 r1 이 L 이 되어 후보 0 으로 굳었다
    assert k._judge(0, 1, order, states, body, axle) == (1, 0)


def test_r5_rejudge_after_grace_then_clear_on_timeout():
    k = _exp16()
    states = _states(k)
    k._start_standoff(0, 0, 1)                               # 일부러 잘못된 역할: W=r0, L=r1
    assert (k.robots[0]["hd_role"], k.robots[1]["hd_role"]) == ("W", "L")
    k._refresh_standoffs(k.cfg.hd_after - 1, states, {})
    assert k.robots[1]["hd_role"] == "L"                     # 유예 중엔 뒤집지 않는다
    k._refresh_standoffs(k.cfg.hd_after, states, {})
    assert (k.robots[0]["hd_role"], k.robots[1]["hd_role"]) == ("L", "W")
    assert k.yield_events[-1]["action"] == "rejudge" and k.standoff_swaps == 1
    t_swap = k.robots[0]["hd_t0"]
    k._refresh_standoffs(t_swap + k.cfg.hd_timeout - 1, states, {})
    assert k.robots[0]["hd_peer"] == 1                       # 상한 전
    k._refresh_standoffs(t_swap + k.cfg.hd_timeout, states, {})
    assert k.robots[0]["hd_peer"] is None and k.robots[1]["hd_peer"] is None   # 교대 뒤 상한 → 해제


def test_loser_forbid_includes_winner_body_wish_and_rotating_soft():
    k = _exp16()
    states = _states(k)
    k._start_standoff(0, 1, 0)                               # W=r1, L=r0
    k.robots[1]["busy"], k.robots[1]["swing_soft"] = 2, {(4, 4)}
    dists = _dists(k, states)
    forbid, forbid_axle = k._standoff_forbid(states, dists)
    assert {(6, 3), (5, 3)} <= forbid[0]                     # W 몸
    assert (4, 4) in forbid_axle[0]                          # W 회전 중 soft (R2)
    assert 1 not in forbid


# ---- 시드 42 축소 장면: r1 의 회전 soft 대각에 r5 축, r5 는 회전 중 ----
def _seed42():
    free = np.ones((9, 9), dtype=bool)
    k = _kernel(free, {1: dict(pos=(4, 4), h=0, goal=(4, 8), stag=30),
                       5: dict(pos=(5, 3), h=2, goal=(1, 3), stag=30, busy=3,
                               swing={(6, 3), (5, 2), (6, 2)}, swing_soft={(4, 3), (5, 4), (4, 2), (6, 4)})})
    return k


def test_r2_detects_standoff_with_rotating_peer():
    k = _seed42()
    states = _states(k)
    dists = _dists(k, states)
    hard, soft = k._wish_cells(1, states, dists)
    assert (5, 3) in soft                                    # r1 의 wish(동쪽 회전) soft 대각 = r5 축
    assert not k._standoff_free(5) and k._standoff_free(5, allow_busy=True)
    assert k._detect_standoffs(0, states, [1, 5], dists, _extra(k))
    assert k.robots[1]["hd_peer"] == 5 and k.robots[5]["hd_peer"] == 1
    assert k.robots[1]["hd_role"] == "L"                     # 회전 중인 r5 는 못 움직이고 r1 은 움직일 수 있다 → r1 이 L (R3)
    assert k.standoffs == 1


def test_r1_patient_only_for_temporary_holds():
    k = _seed42()
    k.robots[1]["h"], k.robots[1]["goal"] = 3, (4, 0)        # r1 서쪽을 보고 전진하려는데 (4,3) 은 r5 의 회전 중 soft
    states = _states(k)
    dists = _dists(k, states)
    soft_hold = {c: 5 for c in k.robots[5]["swing_soft"]}
    assert k._patient(states, dists, _extra(k), soft_hold) == {1}
    assert k._patient(states, dists, _extra(k), {}) == set()             # soft_hold 가 없으면 전진은 그냥 된다
    k.robots[5]["pos"], k.robots[5]["h"] = (4, 3), 1         # r5 의 **몸**이 (4,3) 에 있으면 영구 차단 → 인내 아님
    states = _states(k)
    assert k._patient(states, _dists(k, states), _extra(k), soft_hold) == set()
    k._stag.stag[1] = 5                                      # 아직 상승 전(≤ WAIT_ESC_GRACE)이면 볼 필요 없음
    k.robots[5]["pos"], k.robots[5]["h"] = (5, 3), 2
    states = _states(k)
    assert k._patient(states, _dists(k, states), _extra(k), soft_hold) == set()


# ---- R2′ (-159) 축소 장면: r0 의 전진 wish 칸 (4,3) 이 r1 의 **회전 중 스윙**(extra)에 막힘. 몸은 안 겹친다 ----
def _swing_block():
    free = np.ones((8, 6), dtype=bool)
    # r0 (5,3,2): −행 방향(위)을 보고 목표 (1,3) → 전진 wish = (4,3). r1 (3,4,1) → h=2 로 회전 중: 스윙 [(3, 3), (4, 3), (4, 4)] 에 (4,3) 포함
    k = _kernel(free, {0: dict(pos=(5, 3), h=2, goal=(1, 3), stag=40),
                       1: dict(pos=(3, 4), h=1, goal=(3, 0), stag=40, busy=3,
                               swing=set(swing_cells(3, 4, 1, 2)), swing_soft=set())})
    return k


def test_r2prime_detects_wish_blocked_by_rotating_swing():
    k = _swing_block()
    states = _states(k)
    dists = _dists(k, states)
    hard, _ = k._wish_cells(0, states, dists)
    swing = k.robots[1]["swing"]
    assert (4, 3) in hard and hard & swing and not (hard & set(occupied(states[1]))), (hard, swing)   # 스윙에만 막힘
    # 임시 예약에만 막힌 상대는 stag ≥ 2×hd_after(32) 부터 — 그 전(30)엔 R1 인내 구간, 대치 없음 (4칸 고밀도 과감지 방지)
    k._stag.stag[0] = 30
    assert not k._detect_standoffs(0, states, [0, 1], dists, _extra(k), soft_hold={}) and k.standoffs == 0
    k._stag.stag[0] = 40
    # V2(몸만 봄)라면 상대 없음 → 대치 없음. R2′: 스윙 주인 r1 이 상대.
    assert k._detect_standoffs(0, states, [0, 1], dists, _extra(k), soft_hold={})
    assert k.robots[0]["hd_peer"] == 1 and k.robots[1]["hd_peer"] == 0
    assert k.robots[0]["hd_role"] == "L"                     # 회전 중 r1 은 못 움직이고 r0 은 움직일 수 있다 → r0 이 L (R3)
    assert k.standoffs == 1
