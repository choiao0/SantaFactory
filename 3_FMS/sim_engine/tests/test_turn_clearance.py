# -*- coding: utf-8 -*-
"""회전 여유 점검 (S15P21A106-277): DES 궤적의 회전마다 칸 관문·금지 조합표·실제 틈을 잰다.

합성 궤적으로 세 경우를 가른다 — 칸 관문은 막지만 몸은 먼 것(과대 검출), 금지 조합표에
걸리는 것(제어 오차 5 cm 를 감당 못 함), 아무 문제 없는 것.
"""
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "checks"))

import turn_clearance as TC  # noqa: E402

DT = 0.2778
DIRS = [(1, 0), (0, 1), (-1, 0), (0, -1)]     # 0=N(+r) 1=E(+c) 2=S 3=W — pibt.geometry 와 같다


def xy(r, c):
    """export_isaac._xy 와 같은 규약: x = (c+0.5)·1.0 − 0.4, y = (r+0.5)·1.0."""
    return round((c + 0.5) - 0.4, 2), round(r + 0.5, 2)


def yaw(h):
    dr, dc = DIRS[h]
    return round(math.atan2(dr, dc), 4)


def doc_from(states, t0=0.0, slice_block=None):
    """states = {로봇: [(r, c, h), ...틱마다]} → 내보내기 JSON 모양."""
    robots, headings = {}, {}
    for rid, seq in states.items():
        robots[str(rid)] = [[round(t0 + k * DT, 3), *xy(r, c)] for k, (r, c, _) in enumerate(seq)]
        headings[str(rid)] = [[round(t0 + k * DT, 3), yaw(h)] for k, (_, _, h) in enumerate(seq)]
    d = {"dt_s": DT, "model": "heading", "robots": robots, "headings": headings,
         "actions": {}, "tasks": []}
    if slice_block:
        d["slice"] = slice_block
    return d


def turning(r, c, h0, h1, n=8, at=2):
    """(r, c) 에서 h0 로 서 있다가 `at` 틱에 h1 로 도는 로봇."""
    return [(r, c, h0)] * at + [(r, c, h1)] * (n - at)


def parked(r, c, h, n=8):
    return [(r, c, h)] * n


class TestStates:
    def test_export_rows_turn_back_into_grid_states(self):
        st = TC.states_from_export(doc_from({0: [(5, 7, 0), (5, 7, 1), (6, 7, 2), (6, 6, 3)]}))
        assert [s for _, s in st["0"]] == [(5, 7, 0), (5, 7, 1), (6, 7, 2), (6, 6, 3)]

    def test_a_heading_change_in_place_is_a_turn_and_a_move_is_not(self):
        st = TC.states_from_export(doc_from({0: [(5, 5, 1), (5, 5, 1), (5, 5, 0), (6, 5, 0)]}))
        ev = TC.turn_events(st)
        assert len(ev) == 1
        assert ev[0].robot == "0" and ev[0].k == 2
        assert ev[0].s0 == (5, 5, 1) and ev[0].s1 == (5, 5, 0)


class TestClearance:
    def check(self, states, **kw):
        return TC.scan(doc_from(states), **kw)

    def test_a_far_robot_changes_nothing(self):
        rep = self.check({0: turning(5, 5, 1, 0), 1: parked(20, 20, 1)})
        assert rep["turns"] == 1
        assert rep["gate2"] == 0 and rep["banned"] == 0
        assert rep["min_gap_m"] is None                       # 가까운 로봇이 없었다

    def test_a_tail_in_the_front_cell_trips_the_cell_gate_but_the_bodies_are_far(self):
        # A 는 (5,5) 에서 동(E)을 보고 북으로 돈다. 앞 칸 (5,6) 에 B 의 **뒤 차체**만 있다
        # (B 축 (5,7), 동향). 코 반경 0.559 · B 뒤끝 2 − 1.11 = 0.89 → 틈 ≈ 0.33 m.
        rep = self.check({0: turning(5, 5, 1, 0), 1: parked(5, 7, 1)})
        assert rep["gate2"] == 1 and rep["banned"] == 0
        assert rep["over_block"] == 1                         # 칸은 막는데 몸은 10 cm 넘게 떨어졌다
        assert rep["min_gap_m"] == pytest.approx(0.331, abs=0.01)

    def test_an_axle_in_the_front_cell_is_a_banned_turn(self):
        # A (5,5) 북향 → 서로 돈다. B 축이 바로 앞 칸 (6,5), 동향 — 금지 조합표 ((1,0), h1).
        # B 옆면 r = 5.6, A 코 모서리 반경 0.559 → 틈 41 mm.
        rep = self.check({0: turning(5, 5, 0, 3), 1: parked(6, 5, 1)})
        assert rep["gate2"] == 1 and rep["banned"] == 1 and rep["over_block"] == 0
        assert rep["min_gap_m"] == pytest.approx(0.041, abs=0.005)
        ex = rep["examples"][0]
        assert ex["robot"] == "0" and ex["other"] == "1" and ex["s0"] == [5, 5, 0]

    def test_a_robot_that_arrives_during_the_turn_counts(self):
        # B 는 회전이 시작한 뒤(k=3)에 앞 칸으로 들어온다 — 회전은 5틱 걸린다.
        b = [(8, 5, 1)] * 3 + [(6, 5, 1)] * 5
        rep = self.check({0: turning(5, 5, 0, 3), 1: b})
        assert rep["banned"] == 1

    def test_a_robot_leaving_as_the_turn_starts_is_a_handoff_not_a_banned_pose(self):
        # B 가 앞 칸 (6,5) 에 있다가 회전이 시작하는 틱(k=2)에 (6,4) 로 후진해 앞 칸을 비운다. DES 는
        # 그 틱에 칸을 푼다 — 둘이 같이 서 있던 적은 없으니 금지 배치는 아니고, B 의 몸이 빠지는(후진 12틱)
        # 동안 쓸고 들어가는 **인계**다. 후진한 자리 (6,4) 는 조합표 밖 · 틈 ≈ 0.3 m.
        b = [(6, 5, 1)] * 2 + [(6, 4, 1)] * 6
        rep = self.check({0: turning(5, 5, 0, 3), 1: b})
        assert rep["banned"] == 0 and rep["handoff_banned"] == 1
        assert rep["handoff_gap_lt_100mm"] == 1

    def test_only_turns_inside_the_window_are_counted(self):
        st = {0: turning(5, 5, 0, 3, n=12, at=2), 1: parked(6, 5, 1, n=12)}
        rep = TC.scan(doc_from(st), lo_s=5 * DT, hi_s=12 * DT)
        assert rep["turns"] == 0

    def test_the_slice_block_sets_the_window(self):
        sl = {"t0_s": 5 * DT, "window_s": 7 * DT, "warmup_s": 5 * DT}
        rep = TC.scan(doc_from({0: turning(5, 5, 0, 3, n=12, at=2), 1: parked(6, 5, 1, n=12)},
                               slice_block=sl))
        assert rep["turns"] == 0 and rep["window"] == [pytest.approx(5 * DT), pytest.approx(12 * DT)]
