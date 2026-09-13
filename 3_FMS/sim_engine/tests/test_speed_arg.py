# -*- coding: utf-8 -*-
"""--speed (S15P21A106-116, 계약 v3.3): 틱 길이 = CELL_M / speed. 커널 틱 동역학은 그대로, 초 환산만 바뀐다."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from map_loader import CELL_M, load_map, load_rack_map  # noqa: E402
from order_stream import OrderStream  # noqa: E402
from sim_v2_tasks import SERVICE_TIME_S, parse_args  # noqa: E402

import numpy as np  # noqa: E402

BASE = ["base", "6", "40", "42", "1"]


def test_default_speed_is_one_tick_per_second():
    a = parse_args(BASE)
    assert (a.speed, a.dt) == (1.0, CELL_M / 1.0)


def test_speed_sets_tick_length():
    a = parse_args(BASE + ["--speed=1.1"])
    assert a.speed == 1.1 and a.dt == pytest.approx(CELL_M / 1.1)
    # 서비스 틱은 초를 틱으로 반올림: 1.1 m/s 에서도 4틱(= 기준값과 같은 틱 동역학), 0.5 m/s 에서는 2틱
    assert round(SERVICE_TIME_S / a.dt) == 4
    assert round(SERVICE_TIME_S / parse_args(BASE + ["--speed=0.5"]).dt) == 2


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
    assert ticks[1.0] == 100 and ticks[2.0] == 50          # 100 s → 100틱(dt 1) / 50틱(dt 2)
