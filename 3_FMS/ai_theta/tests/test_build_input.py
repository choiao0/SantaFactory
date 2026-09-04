# -*- coding: utf-8 -*-
"""AI 입력 텐서 생성 검증 (S15P21A106-134).

명세 §4~§9 의 채널 정의·정규화 규칙과, from_theta 와 같은 토폴로지를 보는지를
실제 맵 위에서 확인한다. 흐름 분배(accumulate_flow)는 손으로 답을 알 수 있는
작은 격자에서 따로 검증한다.

실행: 3_FMS/ 에서  python ai_theta/tests/test_build_input.py
"""

from pathlib import Path
import sys
import unittest

import numpy as np

FMS_ROOT = Path(__file__).resolve().parents[2]
SIM_ENGINE = FMS_ROOT / "sim_engine"
for p in (str(FMS_ROOT), str(SIM_ENGINE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from from_theta import extract_topology  # noqa: E402
from map_loader import load_map  # noqa: E402

from ai_theta.data.build_input import (  # noqa: E402
    DIR_E,
    DIR_N,
    DIR_S,
    DIR_W,
    SCENARIO_SIZE,
    STATIC_CHANNELS,
    TASK_CHANNELS,
    TOPOLOGY_CHANNELS,
    ZONE_ORDER,
    accumulate_flow,
    build_guidance_input,
    multi_source_dist,
    od_distribution,
    stack_channels,
)

N_AGENTS, ORDER_RATE = 10, 40


class FlowAccumulationTest(unittest.TestCase):
    """accumulate_flow — 정답을 손으로 셀 수 있는 3×3 빈 격자."""

    def setUp(self):
        self.free = np.ones((3, 3), dtype=bool)
        self.src = (0, 0)          # 남서 모서리
        self.dst = (2, 2)          # 북동 모서리
        target = np.zeros((3, 3), dtype=bool)
        target[self.dst] = True
        self.dist = multi_source_dist(self.free, target)

    def test_direction_totals_follow_od_displacement(self):
        # 남서→북동 4걸음: 북 2 + 동 2. 어느 최단경로든 같다.
        out = np.zeros((4, 3, 3))
        accumulate_flow(self.free, self.dist, self.src, 1.0, out)
        self.assertAlmostEqual(out[DIR_N].sum(), 2.0, places=9)
        self.assertAlmostEqual(out[DIR_E].sum(), 2.0, places=9)
        self.assertEqual(out[DIR_S].sum(), 0.0)
        self.assertEqual(out[DIR_W].sum(), 0.0)

    def test_mass_splits_evenly_at_every_fork(self):
        # 출발 칸에서 북·동 두 갈래 → 각 0.5. 그 다음 칸들도 갈래 수로 균등.
        out = np.zeros((4, 3, 3))
        accumulate_flow(self.free, self.dist, self.src, 1.0, out)
        self.assertAlmostEqual(out[DIR_N][0, 0], 0.5, places=9)
        self.assertAlmostEqual(out[DIR_E][0, 0], 0.5, places=9)
        # 가운데 칸 (1,1) 은 두 경로로 들어와 두 갈래로 나간다 → 각 0.25
        self.assertAlmostEqual(out[DIR_N][1, 1], 0.25, places=9)
        self.assertAlmostEqual(out[DIR_E][1, 1], 0.25, places=9)

    def test_probability_scales_linearly(self):
        a = np.zeros((4, 3, 3))
        b = np.zeros((4, 3, 3))
        accumulate_flow(self.free, self.dist, self.src, 1.0, a)
        accumulate_flow(self.free, self.dist, self.src, 0.3, b)
        self.assertTrue(np.allclose(b, 0.3 * a))

    def test_unreachable_source_adds_nothing(self):
        free = self.free.copy()
        free[1, :] = False                     # 가운데 행을 막아 분리
        target = np.zeros((3, 3), dtype=bool)
        target[self.dst] = True
        dist = multi_source_dist(free, target)
        out = np.zeros((4, 3, 3))
        accumulate_flow(free, dist, self.src, 1.0, out)
        self.assertEqual(out.sum(), 0.0)


class GuidanceInputOnRealMapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inp = build_guidance_input(n_agents=N_AGENTS, order_rate=ORDER_RATE)
        cls.free, cls.st_cell, _ = load_map()                 # 공식 맵 3_FMS/map
        cls.topo = extract_topology(cls.free, cls.st_cell)
        cls.H, cls.W = cls.free.shape

    # ── 형태·순서 (명세 §8, §14) ─────────────────────────────────────────
    def test_shapes_match_contract(self):
        self.assertEqual(self.inp.static_map.shape, (STATIC_CHANNELS, self.H, self.W))
        self.assertEqual(self.inp.task_profile.shape, (TASK_CHANNELS, self.H, self.W))
        self.assertEqual(self.inp.topology_tensor.shape, (TOPOLOGY_CHANNELS, self.H, self.W))
        self.assertEqual(self.inp.scenario.shape, (SCENARIO_SIZE,))
        self.assertEqual(stack_channels(self.inp).shape, (39, self.H, self.W))

    def test_stack_order_is_static_then_task_then_topology(self):
        t = stack_channels(self.inp)
        self.assertTrue(np.array_equal(t[:18], self.inp.static_map))
        self.assertTrue(np.array_equal(t[18:24], self.inp.task_profile))
        self.assertTrue(np.array_equal(t[24:], self.inp.topology_tensor))

    def test_all_channels_within_unit_range(self):
        t = stack_channels(self.inp)
        self.assertGreaterEqual(t.min(), 0.0)
        self.assertLessEqual(t.max(), 1.0 + 1e-6)
        self.assertTrue(np.all(np.isfinite(t)))

    # ── 창고 생김새 (명세 §4) ─────────────────────────────────────────────
    def test_obstacle_and_walkable_partition_the_grid(self):
        sm = self.inp.static_map
        self.assertTrue(np.array_equal(sm[0] + sm[1], np.ones((self.H, self.W), np.float32)))
        self.assertTrue(np.array_equal(sm[1].astype(bool), self.free))

    def test_main_and_sub_aisle_are_disjoint_and_match_topology(self):
        sm = self.inp.static_map
        main, sub = sm[2].astype(bool), sm[3].astype(bool)
        self.assertFalse((main & sub).any())
        # AI 입력과 from_theta 가 같은 구조를 봐야 한다 — 이 파일의 존재 이유
        self.assertTrue(np.array_equal(main, self.topo.main_aisle & self.free))
        self.assertTrue(np.array_equal(sm[4].astype(bool), self.topo.junction & self.free))
        self.assertTrue(np.array_equal(sm[5].astype(bool), self.topo.station & self.free))
        # 작은 통로 = 랙 사이 세로 통로 = 11개 × (21행 × 3열). 2026-09-03 맵 동기화로 랙 1 m 연장(19행 → 21행)
        self.assertEqual(int(sub.sum()), 11 * 63)

    def test_zone_channels_are_one_hot(self):
        # 명세 §4 "구역은 반드시 채널을 나눠서" — 한 칸이 두 구역에 속하지 않는다
        zones = self.inp.static_map[6:13]
        self.assertEqual(zones.shape[0], len(ZONE_ORDER))
        self.assertLessEqual(zones.sum(axis=0).max(), 1.0)

    def test_charge_zone_rectangle_is_included(self):
        # 3_FMS/map/charge_zone.json: c=103~108 × r=48~66 (장애물 제외)
        charging = self.inp.static_map[12].astype(bool)
        inside = charging[48:67, 103:109]
        self.assertGreater(inside.sum(), 50)              # 6×19=114 중 기둥 제외
        self.assertTrue(np.all(charging[48:67, 103:109] <= self.free[48:67, 103:109]))

    def test_degree_counts_free_neighbours(self):
        deg = self.inp.static_map[13]
        self.assertTrue(np.all(deg[~self.free] == 0))
        # 값 = 이웃 수 / 4 이므로 0.25 단위
        self.assertTrue(np.allclose(deg * 4, np.round(deg * 4)))
        # 맵에는 사방이 막힌 고립 free 칸이 있다 (wallA 실측 16칸 — 다운샘플 잔재).
        # 로봇이 갈 수 없는 칸이라 degree 0 이 맞고, 스테이션이 거기 있으면 안 된다.
        isolated = self.free & (deg == 0)
        self.assertLess(int(isolated.sum()), int(self.free.sum()) * 0.01)
        self.assertFalse((isolated & self.inp.static_map[5].astype(bool)).any())

    def test_distance_channels_are_zero_at_source_and_normalised(self):
        sm = self.inp.static_map
        for ch, zone_ch in ((14, 6), (15, 11), (16, 12)):
            with self.subTest(channel=ch):
                src = sm[zone_ch].astype(bool) & self.free
                self.assertTrue(np.all(sm[ch][src] == 0.0))
                self.assertLessEqual(sm[ch].max(), 1.0)
        pick = np.zeros((self.H, self.W), bool)
        for name, rc in self.st_cell.items():
            if name.startswith("aisle_buf"):
                pick[rc] = True
        self.assertTrue(np.all(sm[17][pick] == 0.0))

    # ── 짐 흐름 (명세 §5) ─────────────────────────────────────────────────
    def test_densities_sum_to_one(self):
        tp = self.inp.task_profile
        self.assertAlmostEqual(float(tp[0].sum()), 1.0, places=5)
        self.assertAlmostEqual(float(tp[1].sum()), 1.0, places=5)
        self.assertAlmostEqual(float(tp[2:6].sum()), 1.0, places=5)   # §5-2 전체 합 1

    def test_pickup_and_dropoff_land_on_the_right_station_kinds(self):
        tp = self.inp.task_profile
        pickup_kinds = {"aisle_buf", "inbound_buf"}
        drop_kinds = {"aisle_buf", "packing"}
        for name, rc in self.st_cell.items():
            kind = name.split("[")[0]
            with self.subTest(station=name):
                if tp[0][rc] > 0:
                    self.assertIn(kind, pickup_kinds)
                if tp[1][rc] > 0:
                    self.assertIn(kind, drop_kinds)
        self.assertEqual(int((tp[0] > 0).sum()), 22 + 3)   # aisle_buf 22 + inbound_buf 3
        self.assertEqual(int((tp[1] > 0).sum()), 22 + 5)   # aisle_buf 22 + packing 5

    def test_od_distribution_is_a_probability_over_sim_v2_rules(self):
        pairs = od_distribution(self.st_cell)
        self.assertAlmostEqual(sum(p for _, _, p in pairs), 1.0, places=9)
        self.assertEqual(len(pairs), 22 * 5 + 3 * 22)        # 출고 110 + 입고 66

    def test_demand_flows_only_on_walkable_cells(self):
        flow = self.inp.task_profile[2:6].sum(axis=0)
        self.assertTrue(np.all(flow[~self.free] == 0))

    # ── 통로 구조 (명세 §6) ───────────────────────────────────────────────
    def test_topology_channels_match_from_theta(self):
        tt = self.inp.topology_tensor
        rank = self.topo.v_aisle_rank
        self.assertTrue(np.array_equal(tt[0].astype(bool), rank >= 0))
        self.assertTrue(np.array_equal(tt[3].astype(bool), self.topo.loop_fwd >= 0))
        for d in range(4):
            with self.subTest(dir=d):
                self.assertTrue(np.array_equal(tt[4 + d].astype(bool), self.topo.loop_fwd == d))
                self.assertTrue(np.array_equal(tt[8 + d].astype(bool), self.topo.station_dir == d))

    def test_loop_and_entry_direction_channels_are_one_hot(self):
        tt = self.inp.topology_tensor
        self.assertTrue(np.array_equal(tt[4:8].sum(axis=0), tt[3]))         # 순환로 칸마다 방향 1개
        self.assertEqual(int(tt[8:12].sum()), int(self.inp.static_map[5].sum()))  # 작업자리마다 1개

    def test_aisle_rank_is_normalised_by_max_rank(self):
        # §9 통로 번호 ÷ 그 방향 최대 번호. rank 0 통로는 0, 마지막 통로는 1
        tt = self.inp.topology_tensor
        rank = self.topo.v_aisle_rank
        self.assertAlmostEqual(float(tt[2][rank == 10].max()), 1.0, places=6)
        self.assertEqual(float(tt[2][rank == 0].max()), 0.0)
        self.assertAlmostEqual(float(tt[2][rank == 5].max()), 0.5, places=6)

    def test_rank_modulo_channels_cover_only_vertical_aisles(self):
        tt = self.inp.topology_tensor
        v = tt[0].astype(bool)
        rank = self.topo.v_aisle_rank
        self.assertTrue(np.array_equal(tt[12].astype(bool), v & (rank % 2 == 1)))
        self.assertTrue(np.array_equal(tt[13].astype(bool), v & (rank % 3 == 1)))
        self.assertTrue(np.array_equal(tt[14].astype(bool), v & (rank % 3 == 2)))
        self.assertFalse((tt[13].astype(bool) & tt[14].astype(bool)).any())

    # ── 운영조건 (명세 §7, §9) ────────────────────────────────────────────
    def test_scenario_values(self):
        s = self.inp.scenario
        walkable = int(self.free.sum())
        self.assertEqual(s[0], N_AGENTS)
        self.assertEqual(s[1], ORDER_RATE)
        self.assertAlmostEqual(float(s[2]), N_AGENTS / walkable, places=7)
        self.assertAlmostEqual(float(s[3]), walkable / (self.H * self.W), places=6)
        self.assertAlmostEqual(float(s[4]), self.W / self.H, places=6)
        self.assertEqual(s[5], s[6])                  # §7-1 V1: 적재·공차 속도 동일
        self.assertAlmostEqual(float(s[7]), 0.641, places=5)
        self.assertAlmostEqual(float(s[8]), 1.44, places=5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
