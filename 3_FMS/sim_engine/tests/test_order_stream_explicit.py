# -*- coding: utf-8 -*-
"""OrderStream 명시 주문 모드 (-156). 3_FMS 에서 `python -m pytest sim_engine/tests -q`. 실제 맵·rack_buffers.json 을 읽는다."""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from map_loader import load_map, load_rack_map            # noqa: E402
from order_stream import OrderStream                       # noqa: E402

FREE, ST_CELL, STATIONS = load_map(aisle_block=True)
RACK_MAP = load_rack_map()


def order(t, *lines, oid=1):
    return {"order_id": oid, "store_id": 1, "ordered_at_s": t,
            "lines": [{"product_id": i, "rack_id": r, "qty": q} for i, (r, q) in enumerate(lines, 1)]}


def stream(orders, seed=1, **kw):
    return OrderStream(np.random.default_rng(seed), "main", 0, 50, ST_CELL, STATIONS,
                       orders=orders, rack_map=RACK_MAP, inbound_gap=48, **kw)


def drain(s, until):
    tasks = []
    for t in range(until):
        tasks += [tk for tk in s.arrivals(t) if tk["kind"] == "out"]
    return tasks


def test_rack_map_is_one_buffer_per_zone():
    assert len(RACK_MAP) == 132
    assert set(RACK_MAP.values()) == set(range(22))
    assert len({RACK_MAP[f"A{i}"] for i in range(1, 7)}) == 1            # 존 A 랙 6개 = 버퍼 1개


def test_same_buffer_lines_merge_into_one_tote_and_arrive_at_ordered_time():
    s = stream([order(120, ("A1", 1), ("A2", 5), ("A3", 2))], horizon=600)
    tasks = drain(s, 600)
    assert [tk["created"] for tk in tasks] == [120]                      # 도착 틱 = ordered_at_s
    assert tasks[0]["frm_name"] == f"aisle_buf[{RACK_MAP['A1']}]"
    assert tasks[0]["to_name"].startswith("packing[")
    assert s.n_orders == 1
    assert s.orders_skipped == 0


def test_different_buffers_split_and_tote_units_adds_totes():
    two = stream([order(10, ("A1", 1), ("B1", 1))], horizon=100)
    assert len(drain(two, 100)) == 2                                     # 버퍼 2개 → 태스크 2
    cap = stream([order(10, ("A1", 9), ("A2", 8))], horizon=100, tote_units=8)   # 같은 버퍼 qty 17 → 3토트
    tasks = drain(cap, 100)
    assert len(tasks) == 3
    assert len({tk["frm_name"] for tk in tasks}) == 1
    assert cap.orders[0]["remaining"] == 3


def test_order_over_six_totes_is_excluded():
    s = stream([order(10, ("A1", 49)), order(20, ("B1", 8), oid=2)],
               horizon=100, tote_units=8)
    assert s.orders_oversize == 1 and s.n_orders == 1
    assert len(drain(s, 100)) == 1


def test_unknown_rack_fails_fast():
    unknown = [order(0, ("Z9", 1))]
    with pytest.raises(KeyError, match="Z9"):
        stream(unknown, horizon=100)


def test_orders_outside_horizon_are_skipped_and_counted():
    s = stream([order(5, ("A1", 1), oid=1), order(7200, ("A1", 1), oid=2), order(99999, ("B1", 1), oid=3)], horizon=7200)
    assert s.n_orders == 1
    assert s.orders_skipped == 2
    assert s.order_times.tolist() == [5]


def test_same_seed_same_tasks_and_inbound_unchanged_rule():
    orders = [order(t, ("C1", 1)) for t in (3, 30, 300)]
    a, b = stream(orders, seed=7, horizon=600), stream(orders, seed=7, horizon=600)
    key = lambda s: [(tk["created"], tk["frm_name"], tk["to_name"]) for tk in drain(s, 600)]
    assert key(a) == key(b)
    assert a.n_inbound == len(a.inbound_times)                             # 입고는 in 창 간격 생성 그대로
    assert a.windows is not None
