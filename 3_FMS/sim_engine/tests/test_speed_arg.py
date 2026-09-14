# -*- coding: utf-8 -*-
"""--speed (S15P21A106-116, 계약 v3.3 → v4).

v3.3: 틱 길이 = CELL_M / speed. 커널 틱 동역학은 그대로, 초 환산만 바뀐다.
v4 (-194): 헤딩은 1칸이 MOVE_TICKS 틱이라 틱 길이가 그만큼 더 짧다.

    헤딩    dt = CELL_M / (speed × MOVE_TICKS)
    칸 모델  dt = CELL_M / speed              ← v3.3 과 같다

speed 의 뜻은 양쪽 다 같다 — **1칸에 걸리는 시간이 CELL_M / speed 초**다. 칸 모델을
같이 나누지 않는 이유는 그게 A/B 비교축이어서다(기준값 2317/186.4 · 2970/127.3).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from map_loader import CELL_M, load_map, load_rack_map  # noqa: E402
from order_stream import OrderStream  # noqa: E402
from pibt_core import MOVE_TICKS  # noqa: E402
from sim_v2_tasks import SERVICE_TIME_S, parse_args  # noqa: E402

import numpy as np  # noqa: E402

BASE = ["base", "6", "40", "42", "1"]


def test_default_speed_is_one_cell_per_second():
    """speed 1.0 = 1칸 1초. 헤딩은 그 1초를 MOVE_TICKS 틱으로 쪼갠다 (v4)."""
    a = parse_args(BASE)
    assert a.speed == 1.0
    assert a.dt == pytest.approx(CELL_M / (1.0 * MOVE_TICKS))
    assert a.dt * MOVE_TICKS == pytest.approx(CELL_M / 1.0)   # 1칸에 걸리는 시간은 그대로


def test_speed_sets_tick_length():
    a = parse_args(BASE + ["--speed=1.1"])
    assert a.speed == 1.1
    assert a.dt == pytest.approx(CELL_M / (1.1 * MOVE_TICKS))


def test_cell_model_keeps_the_v33_formula():
    """칸 모델은 1칸 = 1틱이라 나누지 않는다 — A/B 비교축(기준값 2개)을 지킨다."""
    for extra in (["--cell"], ["--flow=v1compat"]):
        a = parse_args(BASE + extra)
        assert not a.heading
        assert a.dt == pytest.approx(CELL_M / 1.0), extra
        # 서비스 틱은 초를 틱으로 반올림 — 칸 모델에서는 예전처럼 4틱이어야 한다
        assert round(SERVICE_TIME_S / a.dt) == 4, extra


@pytest.mark.parametrize("bad", ["--speed=0", "--speed=0.05", "--speed=6"])
def test_speed_out_of_range_rejected(bad):
    with pytest.raises(AssertionError):
        parse_args(BASE + [bad])


def test_explicit_order_seconds_become_ticks_by_dt():
    free, st_cell, stations = load_map()
    rack_map = load_rack_map()
    rack = next(iter(rack_map))
    orders = [{"order_id": 1, "ordered_at_s": 100, "lines": [{"rack_id": rack, "qty": 1}]}]
    ticks = {}
    for dt in (1.0, 2.0):
        stream = OrderStream(np.random.default_rng(0), "main", 0, 50, st_cell, stations, horizon=1000,
                             shifts=("out",), orders=orders, rack_map=rack_map, tote_units=8, dt=dt)
        ticks[dt] = stream.explicit_orders[0][0]
    assert ticks[1.0] == 100          # 100 s → 100틱 (dt 1)
    assert ticks[2.0] == 50           # 100 s → 50틱 (dt 2)
