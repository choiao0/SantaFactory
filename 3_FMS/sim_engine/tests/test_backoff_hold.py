# -*- coding: utf-8 -*-
"""스스로 물러난 로봇은 곧장 돌아오지 않는다 (S15P21A106-281, 계약 v3.20).

대기 상승으로 약 4초 뒤 물러난 로봇은 다음 틱 전진이 가장 싸서, 길이 안 열렸는데도 비운 칸으로 곧장 돌아왔다(같은 두 칸 왕복).
물러난(뒤로 한 칸, 목표에서 멀어짐, 비운 칸에 아무도 안 들어옴) 로봇에 기록을 달고, 막던 로봇이 원하던 칸을 비울 때까지
(최소 BACKOFF_HOLD_MIN 틱, 상한 backoff_hold 틱) 비운 칸에 축을 못 들이게 한다.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kernel.core import BACKOFF_HOLD_MIN, FmsKernel, KernelConfig  # noqa: E402
from kernel.states import TO_DROP, TO_PICK  # noqa: E402

H, W = 5, 14
EAST = 1                                                        # pibt DIRS (1,0) (0,1) (-1,0) (0,-1) 의 번호
HOLD = 80


def kernel():
    free = np.zeros((H, W), dtype=bool)
    free[1:4, :] = True                                         # 3줄 통로
    cfg = KernelConfig(heading=True, zone=False, capacity=1, service_steps=4, backoff_hold=HOLD)
    k = FmsKernel(free, {"packing[0]": (2, 12)}, np.ones((H, W, 4)), np.ones((H, W)), [(2, 5), (2, 7), (1, 1)], 3, cfg)
    k.robots[0].update(state=TO_DROP, goal=(2, 11), pos=(2, 5), h=EAST)   # A: 동쪽으로 가려는데
    k.robots[1].update(state=TO_PICK, goal=(1, 13), pos=(2, 7), h=EAST)   # B: 몸 (2,7)·(2,6) 이 A 의 앞 칸을 막았다
    k.robots[2].update(state=TO_PICK, goal=(1, 0), pos=(1, 1), h=EAST)
    k._stag.stag[0] = 20                                        # A 는 정체 — 대기 상승이 붙어 물러날 수 있다
    return k


def states_of(k):
    return {rid: (rb["pos"][0], rb["pos"][1], rb["h"]) for rid, rb in k.robots.items()}


def back_off(k, t=100, to=(2, 4)):
    """A 가 이번 틱 뒤로 한 칸 물러난 것처럼 만들고 기록을 단다."""
    before = states_of(k)
    wishes = k._backoff_wishes(before, None, set())
    k.robots[0]["pos"] = to
    k._note_backoffs(t, before, wishes)
    return wishes


def test_a_robot_that_backed_off_on_its_own_is_held():
    k = kernel()
    wishes = back_off(k)
    assert wishes[0] == (frozenset({(2, 6)}), frozenset({1}))  # 원하던 칸과 막던 로봇
    assert k._backoff_holds(101) == {0: (2, 5)}                 # 비운 칸에 축을 못 들인다
    assert k.backoff_holds == 1


def test_it_stays_held_while_the_blocker_is_still_there():
    k = kernel()
    back_off(k)
    assert k._backoff_holds(100 + BACKOFF_HOLD_MIN + 5) == {0: (2, 5)}


def test_it_is_released_once_the_blocker_moved_and_the_minimum_passed():
    k = kernel()
    back_off(k)
    k.robots[1]["pos"] = (2, 10)                                # B 가 비켰다
    assert k._backoff_holds(100 + BACKOFF_HOLD_MIN - 1) == {0: (2, 5)}   # 최소 시간 전엔 그대로
    assert k._backoff_holds(100 + BACKOFF_HOLD_MIN) == {}
    assert k.robots[0]["backoff"] is None


def test_it_is_released_at_the_cap_even_if_still_blocked():
    k = kernel()
    back_off(k)
    assert k._backoff_holds(100 + HOLD) == {}
    assert k.backoff_timeouts == 1


def test_a_new_goal_releases_the_hold_at_once():
    k = kernel()
    back_off(k)
    k.robots[0]["goal"] = (3, 11)                               # 충전 존 칸 재선택처럼 NAV 인 채로 목표가 바뀌었다
    assert k._backoff_holds(101) == {}
    assert k.backoff_timeouts == 0                              # 상한으로 푼 것이 아니다


def test_leaving_nav_is_not_counted_as_a_timeout():
    k = kernel()
    back_off(k)
    k.robots[0]["state"] = "SVC_DROP"
    assert k._backoff_holds(100 + HOLD) == {}
    assert k.backoff_timeouts == 0


def test_a_robot_pushed_back_is_not_held():
    k = kernel()
    before = states_of(k)
    wishes = k._backoff_wishes(before, None, set())
    k.robots[0]["pos"] = (2, 4)
    k.robots[1].update(pos=(2, 6))                              # B 가 A 가 비운 칸으로 들어왔다 = 밀림
    k._note_backoffs(100, before, wishes)
    assert k.robots[0]["backoff"] is None


def test_a_planned_reverse_that_gets_closer_is_not_held():
    k = kernel()
    k.robots[0]["goal"] = (2, 1)                                # 목표가 뒤쪽 — 뒤로 가는 것이 진전이다
    back_off(k)
    assert k.robots[0]["backoff"] is None


def test_a_robot_that_is_not_stuck_is_not_a_candidate():
    k = kernel()
    k._stag.stag[0] = 0
    assert 0 not in k._backoff_wishes(states_of(k), None, set())
