# -*- coding: utf-8 -*-
"""폭 1 통로 추출 (S15P21A106-79 §3.1). 합성 맵: 세로 통로 2개(길이 4·2), 막다른 통로 1개, 폭 2 통로 1개(통로 아님), 가로 통로 1개."""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pibt.corridor import find_segments, summarize  # noqa: E402


def _map(rows):
    return np.array([[ch == "." for ch in row] for row in rows])


def test_vertical_segments_with_portals_and_dead_end():
    free = _map([
        "..........",
        "..#.#..#.#",   # 세로 통로 col3(rows1-4, 길이4), col8(rows1-2, 길이2 → row3 막힘 = 막다른)
        "..#.#..#.#",
        "..#.#..###",
        "..#.#.....",
        "..........",
    ])
    seg_id, segs = find_segments(free)
    by_cells = {s.cells: s for s in segs}
    a = by_cells[((1, 3), (2, 3), (3, 3), (4, 3))]
    assert a.axis == 0
    assert a.portal_a == (0, 3)
    assert a.portal_b == (5, 3)
    b = by_cells[((1, 8), (2, 8))]
    assert b.portal_a == (0, 8)
    assert b.portal_b is None                       # 막다른 통로
    assert seg_id[2, 3] == a.sid
    assert seg_id[0, 3] == -1                       # 입구는 통로 칸 아님


def test_width_2_is_not_a_corridor_and_horizontal_detected():
    free = _map([
        "########",
        "#..#####",   # 폭 2 세로 통로 (cols 1,2) → 통로 아님
        "#..#####",
        "#..#####",
        "#......#",   # 가로 통로 row4 cols 3..6 (상하 막힘) — cols1,2 는 위가 비어 통로 아님
        "########",
    ])
    seg_id, segs = find_segments(free)
    assert all(seg_id[r, c] == -1 for r in (1, 2, 3) for c in (1, 2))
    horiz = [s for s in segs if s.axis == 1]
    assert len(horiz) == 1
    assert horiz[0].cells == ((4, 3), (4, 4), (4, 5), (4, 6))
    assert horiz[0].portal_a == (4, 2)
    assert horiz[0].portal_b is None
    n, hist, dead = summarize(segs)
    assert n == len(segs)
    assert hist[4] == 1
