# -*- coding: utf-8 -*-
"""헤딩 정면 조우 양보의 우선순위·임시 목표·상한.

문턱(yield_after)과 상한(yield_ticks)은 **KernelConfig 에서 읽는다.** 틱 길이가 바뀌면
같이 재조정되는 값이라(-194 에서 8→16 · 20→40) 숫자를 박으면 그때마다 깨진다.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kernel.core import FmsKernel, KernelConfig  # noqa: E402
from kernel.states import TO_DROP, TO_HOME  # noqa: E402


CFG = KernelConfig(heading=True, zone=False, yield_rule=True)


def make_kernel():
    free = np.ones((9, 9), dtype=bool)
    cfg = KernelConfig(heading=True, zone=False, yield_rule=True)
    return FmsKernel(free, {"a": (4, 3), "b": (4, 4)},
                     np.ones((9, 9, 4)), np.ones((9, 9)),
                     [(4, 3), (4, 6)], 2, cfg,
                     lane_dir=np.full((9, 9), -1, dtype=np.int8))


def face(k):
    a, b = k.robots[0], k.robots[1]
    a.update(pos=(4, 3), h=1, heading=1, goal=(4, 8), state=TO_DROP, goal_t=0)
    b.update(pos=(4, 4), h=3, heading=3, goal=(4, 0), state=TO_HOME, goal_t=5)
    a["waitc"] = CFG.yield_after      # 문턱을 갓 넘긴 상태
    return {rid: (rb["pos"][0], rb["pos"][1], rb["h"]) for rid, rb in k.robots.items()}


def dists(k):
    return {rid: k.dmap_h(rb["goal"]) for rid, rb in k.robots.items()}


def test_lower_priority_robot_gets_separate_temporary_target():
    k = make_kernel()
    states = face(k)
    original = k.robots[1]["goal"]
    k._detect_headons(10, states, k._priority_h(10), dists(k))
    y = k.robots[1]
    assert y["yield_peer"] == 0 and y["yield_target"] in ((3, 4), (5, 4))
    assert y["goal"] == original and y["yield_until"] == 10 + CFG.yield_ticks
    assert k.yield_events[-1]["yielder"] == 1


def test_yield_clears_at_the_tick_limit():
    k = make_kernel()
    states = face(k)
    k._detect_headons(10, states, k._priority_h(10), dists(k))
    k._refresh_yields(10 + CFG.yield_ticks, states)
    assert k.robots[1]["yield_peer"] is None and k.robots[1]["yield_target"] is None
