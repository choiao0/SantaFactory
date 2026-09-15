# -*- coding: utf-8 -*-
"""목표 상태에는 대기 상승(bias)을 붙이지 않는다 (S15P21A106-204 물리 팀 보고 2026-09-14).

bias 를 안고 목표에 도착하면 첫 틱에 "나가기(1+d) < 대기(1+bias)" 로 떠나고, 목표가 뒤쪽이면 후진 배율 3 으로 d=3 이라
"돌아오기(3+0) < 대기(1+bias+3)" 도 성립해 목표↔옆 칸 왕복이 굳는다(12대 cross 4/6 시드 실측). 수정 뒤 목표 상태의 1순위는 대기.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pibt.geometry import TURN_COST  # noqa: E402
from pibt.heading import candidates_h  # noqa: E402
from pibt.hgraph import dist_map_h  # noqa: E402
from pibt.liveness import WAIT_ESC_CAP  # noqa: E402


def _setup():
    free = np.ones((7, 7), dtype=bool)
    edge = np.ones((7, 7, 4)); wait = np.ones((7, 7))
    goal = (3, 3)
    return free, edge, wait, dist_map_h(free, goal, edge, TURN_COST)


def test_wait_is_first_at_goal_even_with_max_bias():
    free, edge, wait, dist = _setup()
    for h in range(4):
        first = candidates_h((3, 3, h), dist, edge, wait, free, TURN_COST, bias=WAIT_ESC_CAP)[0][0]
        assert first == (3, 3, h), f"h={h}: 목표에서 떠난다 → {first}"


def test_bias_still_applies_off_goal():
    free, edge, wait, dist = _setup()
    s = (2, 3, 2)                                            # 목표 (3,3) 이 h=2 기준 바로 뒤 → 대기 d=3, 후진 d=0
    cands = candidates_h(s, dist, edge, wait, free, TURN_COST, bias=WAIT_ESC_CAP)
    assert cands[0][0] == (3, 3, 2), "후진으로 목표에 든다"
    assert cands[-1][0] == s, "목표 밖에서는 대기 상승이 그대로 붙어 대기가 꼴찌"
