# -*- coding: utf-8 -*-
"""충전 존 주차 칸 (S15P21A106-281).

일이 없는 로봇이 존 입구 쪽 모서리에 빽빽이 모여(간격 1칸) 뒤에 온 로봇이 그 사이를 비집고 들어가며 밀어냈다
(est_20 12대: 시작 5~8분에 9대가 3 m × 4 m 에, 15대: 존 입구 무진전 208 로봇·분). 정해진 칸(줄 간격 3 · 열 간격 2)을
입구에서 먼 안쪽부터 채운다. 안쪽 칸으로 가는 로봇이 주차 칸 줄을 곧게 지나며 서 있는 로봇을 밀지 않도록 칸으로 들어가는
이동에 비용을 더하고(SLOT_ENTRY_COST), 밀려난 두 로봇이 서로의 칸에 서면 칸을 맞바꾼다.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kernel.core import SLOT_ENTRY_COST, FmsKernel, KernelConfig, slot_entry_cost  # noqa: E402
from kernel.states import IDLE, TO_HOME  # noqa: E402
from map_loader import (MAP_DIR, load_charge_zone, load_map, make_homes_zone,  # noqa: E402
                        park_slots)
from pibt_core import DIRS, candidates_h, dist_map_h  # noqa: E402

# 16 × 20 격자. 존 = 행 3~13 · 열 7~12. 서쪽 열 6(통로)과 남쪽 행 2 만 존 밖 통행 칸 — 북 · 동은 벽.
# 존 안 기둥 (8, 8). wallA 의 동쪽 존(서쪽 통로 · 남쪽 진입, 북 · 동 벽, 기둥 하나)을 줄인 모양.
H, W = 16, 20
ZR, ZC = range(3, 14), range(7, 13)


def synth():
    free = np.zeros((H, W), dtype=bool)
    free[2, 0:13] = True                    # 남쪽 진입 줄
    free[0:14, 6] = True                    # 서쪽 통로
    for r in ZR:
        for c in ZC:
            free[r, c] = True
    free[8, 8] = False                      # 기둥
    zone = np.zeros((H, W), dtype=bool)
    zone[3:14, 7:13] = True
    return free, zone & free


class TestParkSlots:
    def test_slots_sit_on_a_grid_away_from_the_entrance(self):
        free, zone = synth()
        slots = park_slots(free, zone)

        rows = {r for r, _ in slots}
        cols = {c for _, c in slots}
        assert all((r - max(rows)) % 3 == 0 for r in rows)                 # 줄 간격 3
        assert all((c - max(cols)) % 2 == 0 for c in cols)                 # 열 간격 2
        assert all(c != 7 for _, c in slots) and all(r != 3 for r, _ in slots)   # 통로 · 진입 줄에 맞닿은 칸은 비운다
        assert (8, 8) not in slots and all(free[rc] and zone[rc] for rc in slots)

    def test_deepest_slots_come_first(self):
        free, zone = synth()
        slots = park_slots(free, zone)

        assert slots[:3] == [(13, 12), (10, 12), (7, 12)]                 # 입구에서 가장 먼 동쪽 열을 북쪽 끝부터
        near = [rc for rc in slots if rc[1] == 8 or rc[0] == 4]           # 입구(서 · 남)에서 한 칸 들어온 칸
        assert slots[-len(near):] == near                                 # 맨 나중에 채운다

    def test_a_dead_end_pocket_beyond_the_zone_is_not_an_entrance(self):
        free, zone = synth()
        free[5:8, 13] = True                                              # 동쪽 벽 사이 막힌 틈(wallA c109 같은)
        assert park_slots(free, zone) == park_slots(*synth())

    def test_no_entrance_means_no_slots(self):
        free, zone = synth()
        free[:, 6] = False
        free[2, :] = False
        assert park_slots(free, zone) == []

    def test_initial_homes_use_the_same_order(self):
        free, zone = synth()
        assert make_homes_zone(free, zone, 4) == park_slots(free, zone)[:4]

    def test_more_robots_than_slots_still_get_homes(self):
        free, zone = synth()
        n = len(park_slots(free, zone)) + 3
        homes = make_homes_zone(free, zone, n)
        assert len(homes) == n and len(set(homes)) == n


def kernel(homes, zone, heading=False):
    free = synth()[0]
    cfg = KernelConfig(heading=heading, zone=True, capacity=1, service_steps=4)
    return FmsKernel(free, {"home": homes[0]}, np.ones((H, W, 4)), np.ones((H, W)),
                     homes, len(homes), cfg, zone_mask=zone)


class TestZoneGoal:
    def test_a_freed_robot_takes_the_deepest_free_slot(self):
        free, zone = synth()
        slots = park_slots(free, zone)
        k = kernel([(2, 0), (2, 1)], zone)
        assert k.zone_goal(0) == slots[0]

    def test_a_slot_another_robot_is_heading_to_is_skipped(self):
        free, zone = synth()
        slots = park_slots(free, zone)
        k = kernel([(2, 0), (2, 1)], zone)
        k.robots[1].update(state=TO_HOME, goal=slots[0])
        assert k.zone_goal(0) == slots[1]

    def test_a_parked_robot_keeps_its_slot_reserved(self):
        free, zone = synth()
        slots = park_slots(free, zone)
        k = kernel([(2, 0), slots[0]], zone)
        k.robots[1].update(state=IDLE, goal=slots[0])
        assert k.zone_goal(0) == slots[1]

    def test_when_every_slot_is_taken_it_falls_back_to_the_nearest_free_cell(self):
        free, zone = synth()
        slots = park_slots(free, zone)
        k = kernel([(2, 0)] + slots, zone)
        for rid, rc in enumerate(slots, start=1):
            k.robots[rid].update(state=IDLE, goal=rc)
        goal = k.zone_goal(0)
        assert goal not in slots and zone[goal]
        assert k.zone_stats["slots_full"] == 1


    def test_two_displaced_robots_on_each_others_slot_swap_slots(self):
        free, zone = synth()
        a, b = park_slots(free, zone)[:2]
        k = kernel([b, a], zone)                                          # 0 이 b 에, 1 이 a 에 서 있다
        k.robots[0].update(state=IDLE, goal=a, home=a)
        k.robots[1].update(state=IDLE, goal=b, home=b)
        k._zone_retarget()
        assert (k.robots[0]["goal"], k.robots[1]["goal"]) == (b, a)       # 제자리를 새 칸으로
        assert (k.robots[0]["home"], k.robots[1]["home"]) == (b, a)
        assert k.zone_stats["swaps"] == 1

    def test_a_displaced_robot_whose_slot_is_free_keeps_it(self):
        free, zone = synth()
        a, b = park_slots(free, zone)[:2]
        k = kernel([(5, 11), b], zone)
        k.robots[0].update(state=IDLE, goal=a, home=a)
        k.robots[1].update(state=IDLE, goal=b, home=b)
        k._zone_retarget()
        assert k.robots[0]["goal"] == a and k.zone_stats["swaps"] == 0


def walk(free, edge_cost, start, goal, limit=60):
    """거리장을 따라 첫 후보만 고른 경로(다른 로봇 없음). 지난 칸 목록."""
    dist = dist_map_h(free, goal, edge_cost)
    s, cells = start, [start[:2]]
    for _ in range(limit):
        if s[:2] == goal:
            return cells
        s = candidates_h(s, dist, edge_cost, np.ones(free.shape), free, 1.25)[0][0]
        if s[:2] != cells[-1]:
            cells.append(s[:2])
    raise AssertionError(f"{goal} 에 못 닿음: {cells}")


class TestSlotEntryCost:
    def test_only_edges_into_a_slot_cost_more(self):
        free, zone = synth()
        slots = park_slots(free, zone)
        ec = slot_entry_cost(np.ones((H, W, 4)), slots)
        r, c = slots[0]
        for h, (dr, dc) in enumerate(DIRS):
            if 0 <= r - dr < H and 0 <= c - dc < W:
                assert ec[r - dr, c - dc, h] == 1.0 + SLOT_ENTRY_COST     # 이웃 → 칸
        assert (ec[r, c] == 1.0).all()                                    # 칸 → 이웃은 제값

    def test_the_way_to_a_deep_slot_avoids_other_slots(self):
        free, zone = synth()
        slots = park_slots(free, zone)
        goal = (13, 8)                                                    # 서쪽 칸 열 북쪽 끝
        start = (3, 10, DIRS.index((1, 0)))                               # 가운데 칸 열 입구에서 북쪽을 보고 선 로봇
        straight = walk(free, np.ones((H, W, 4)), start, goal)
        assert {(4, 10), (7, 10), (10, 10), (13, 10)} <= set(straight)    # 비용이 없으면 칸 줄을 곧게 지난다
        around = walk(free, slot_entry_cost(np.ones((H, W, 4)), slots), start, goal)
        assert not set(around[1:-1]) & set(slots)                         # 비용을 더하면 칸 사이 통로로 간다

    def test_the_heading_kernel_plans_with_the_entry_cost(self):
        free, zone = synth()
        slots = park_slots(free, zone)
        k = kernel([(2, 3), (2, 5)], zone, heading=True)
        assert (k.edge_cost == slot_entry_cost(np.ones((H, W, 4)), slots)).all()
        assert (kernel([(2, 3), (2, 5)], zone).edge_cost == 1.0).all()    # 칸 모델은 그대로


class TestOfficialMap:
    def test_east_zone_fills_from_the_back(self):
        free, _, _ = load_map(MAP_DIR)
        zone = load_charge_zone(free, MAP_DIR) & free
        slots = park_slots(free, zone)

        assert len(slots) >= 15                                            # 견적 스윕 최대 15대가 모두 칸에 선다
        east, west = max(c for _, c in slots), min(c for _, c in slots)
        assert slots[0][1] == east                                         # 동쪽(안쪽) 열부터 — 첫 칸은 기둥 뒤
        n_west = sum(1 for _, c in slots if c == west)
        assert all(c == west for _, c in slots[-n_west:])                  # 통로 쪽 열은 맨 나중
        assert min(r for r, _ in slots) > int(np.nonzero(zone)[0].min())   # 남쪽 진입 줄은 비운다
