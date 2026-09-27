# -*- coding: utf-8 -*-
"""목표 칸이 서비스 중이면 조용히 기다린다 (S15P21A106-281, 계약 v3.19).

포장대에서 다른 로봇이 하역 중인데 그 포장대로 가는 로봇은 대기 상승(정체 10틱 뒤 틱마다 +1)을 받아 약 4초 뒤
후진(3 + d+1)이 대기보다 싸졌다. 물러나면 다시 전진이 가장 싸서 포장대가 빌 때까지 한 칸 왕복을 되풀이했다
(est_20 12대 6h: 한 대가 71초에 30번). 목표 칸이 HOLD 로봇에게 잡혀 있으면 그 로봇은 상승 없이 기다린다.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kernel.core import FmsKernel, KernelConfig  # noqa: E402
from kernel.states import SVC_DROP, TO_DROP, TO_PICK  # noqa: E402

H, W = 5, 12
STATION = (2, 9)


def kernel(station_calm=True):
    free = np.zeros((H, W), dtype=bool)
    free[1:4, :] = True                                        # 3줄 통로
    cfg = KernelConfig(heading=False, zone=False, capacity=1, service_steps=4, station_calm=station_calm)
    k = FmsKernel(free, {"packing[0]": STATION}, np.ones((H, W, 4)), np.ones((H, W)),
                  [STATION, (2, 7), (1, 2)], 3, cfg)
    k.robots[0].update(state=SVC_DROP, goal=STATION)          # 포장대에서 하역 중
    k.robots[1].update(state=TO_DROP, goal=STATION)           # 같은 포장대로 가는 중 — 막혀 있다
    k.robots[2].update(state=TO_PICK, goal=(3, 0))            # 상관없는 로봇
    return k


def test_a_robot_waiting_for_a_busy_station_is_calm():
    assert kernel()._goal_held() == {1}


def test_nobody_is_calm_once_the_station_is_free():
    k = kernel()
    k.robots[0].update(state=TO_PICK, goal=(3, 11))
    assert k._goal_held() == set()


def test_the_servicing_robot_itself_is_not_counted():
    k = kernel()
    assert 0 not in k._goal_held()


def test_the_switch_is_off_by_default_for_callers_that_do_not_set_it():
    assert KernelConfig().station_calm is False                # legacy · 칸 모델 호출은 v3.18 그대로
