# -*- coding: utf-8 -*-
"""합성 창고 생성기 검증 (S15P21A106-139).

두 가지를 못 박는다.

1. **공식 맵은 하나도 안 변한다.** 토폴로지 좌표를 topology_spec 으로 옮겼지만
   공식 맵에는 topology.json 이 없어 wallA 상수로 떨어진다 → 기존 값 그대로.
2. **wallA 를 파라미터로 다시 만들 수 있다.** 링(순환 밴드) 영역의 1 m 통행성과
   토폴로지 배열이 공식 맵과 정확히 같다. 규칙이 실측 창고를 설명한다는 증거다.

그 위에 합성 창고 여러 개를 실제로 만들어 map_loader → from_theta → build_input
경로가 도는지 확인한다.

실행: 3_FMS/ 에서  python ai_theta/tests/test_synth_warehouse.py
"""

from collections import deque
from pathlib import Path
import json
import shutil
import sys
import tempfile
import unittest

import numpy as np

FMS_ROOT = Path(__file__).resolve().parents[2]
SIM_ENGINE = FMS_ROOT / "sim_engine"
MAP_PKG = FMS_ROOT / "map"
for p in (str(FMS_ROOT), str(SIM_ENGINE), str(MAP_PKG)):
    if p not in sys.path:
        sys.path.insert(0, p)

from from_theta import (BAND_E_COLS, BAND_N_ROWS, BAND_S_ROWS, BAND_W_COLS,  # noqa: E402
                        JUNCTION_ROWS, VA_ROWS, VA_XS_M, extract_topology, from_theta)
from map_loader import (CELL_M, MAP_DIR, OFFSET_M, load_charge_zone, load_map,  # noqa: E402
                        load_topology_spec, make_homes_zone)
from topology_spec import WALL_A, TopologySpec, load_spec  # noqa: E402
from contracts.guidance_types import GuidanceTheta  # noqa: E402

import synth_warehouse as sw  # noqa: E402

# 공식 맵 실측 (2026-09-08, 리팩토링 전 develop 에서 잰 값)
WALL_A_COUNTS = dict(free=9333, free_blk=8640, rank=693, main=1337, loop=1765,
                     junction=66, station_dir=43)
N_RANDOM = 12          # 무작위 스펙 표본 수 (테스트 시간 ~2 s)


def _reachable(free, start):
    H, W = free.shape
    seen = np.zeros_like(free)
    seen[start] = True
    q = deque([start])
    while q:
        r, c = q.popleft()
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            rr, cc = r + dr, c + dc
            if 0 <= rr < H and 0 <= cc < W and free[rr, cc] and not seen[rr, cc]:
                seen[rr, cc] = True
                q.append((rr, cc))
    return seen


class TopologySpecTest(unittest.TestCase):
    """스펙이 예전 wallA 상수와 같은 값을 말하는가."""

    def test_wall_a_centers_match_old_formula(self):
        old = [int((x + OFFSET_M) / CELL_M) for x in VA_XS_M]
        self.assertEqual(list(WALL_A.va_centers), old)

    def test_wall_a_bands_match_from_theta_constants(self):
        self.assertEqual(WALL_A.va_rows, VA_ROWS)
        self.assertEqual(WALL_A.band_s_rows, BAND_S_ROWS)
        self.assertEqual(WALL_A.band_n_rows, BAND_N_ROWS)
        self.assertEqual(WALL_A.band_w_cols, BAND_W_COLS)
        self.assertEqual(WALL_A.band_e_cols, BAND_E_COLS)
        self.assertEqual(WALL_A.junction_rows, JUNCTION_ROWS)

    def test_official_map_has_no_spec_file_so_falls_back(self):
        self.assertFalse((Path(MAP_DIR) / "topology.json").exists())
        self.assertEqual(load_topology_spec(MAP_DIR), WALL_A)

    def test_json_round_trip(self):
        self.assertEqual(TopologySpec.from_dict(json.loads(json.dumps(WALL_A.to_dict()))), WALL_A)

    def test_validation_rejects_overlapping_geometry(self):
        bad = dict(WALL_A.to_dict())
        bad.pop("schema")
        bad["band_w_cols"] = [20, 40]        # 서 밴드가 랙 블록을 파고든다
        with self.assertRaises(AssertionError):
            TopologySpec(**bad)


class OfficialMapUnchangedTest(unittest.TestCase):
    """스펙 도입 전후로 공식 맵 결과가 같아야 한다 (회귀 방지)."""

    def test_counts(self):
        free, st_cell, _ = load_map()
        topo = extract_topology(free, st_cell)
        self.assertEqual(int(free.sum()), WALL_A_COUNTS["free"])
        self.assertEqual(int((topo.v_aisle_rank >= 0).sum()), WALL_A_COUNTS["rank"])
        self.assertEqual(int(topo.main_aisle.sum()), WALL_A_COUNTS["main"])
        self.assertEqual(int((topo.loop_fwd >= 0).sum()), WALL_A_COUNTS["loop"])
        self.assertEqual(int(topo.junction.sum()), WALL_A_COUNTS["junction"])
        self.assertEqual(int((topo.station_dir >= 0).sum()), WALL_A_COUNTS["station_dir"])

    def test_aisle_block_uses_spec(self):
        self.assertEqual(int(load_map(aisle_block=True)[0].sum()), WALL_A_COUNTS["free_blk"])

    def test_explicit_spec_equals_default(self):
        free, st_cell, _ = load_map()
        a = extract_topology(free, st_cell)
        b = extract_topology(free, st_cell, spec=WALL_A)
        for attr in ("v_aisle_rank", "main_aisle", "loop_fwd", "junction", "station_dir"):
            self.assertTrue(np.array_equal(getattr(a, attr), getattr(b, attr)), attr)


class WallAProfileTest(unittest.TestCase):
    """파라미터로 적은 wallA 가 공식 맵의 링 영역을 그대로 재현하는가."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="synth_wallA_")
        cls.spec = sw.wall_a_profile()
        sw.write_set(cls.spec, cls.tmp)
        cls.ref_free, cls.ref_st, _ = load_map(MAP_DIR)
        cls.got_free, cls.got_st, _ = load_map(cls.tmp)
        cls.topo = load_topology_spec(cls.tmp)
        cls.ring = np.zeros(cls.ref_free.shape, dtype=bool)
        (r0, r1), (c0, c1) = cls.topo.ring_rows, cls.topo.ring_cols
        cls.ring[r0:r1, c0:c1] = True

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_same_grid_shape(self):
        self.assertEqual(self.got_free.shape, self.ref_free.shape)

    def test_topology_spec_equals_wall_a_constants(self):
        self.assertEqual(self.topo, WALL_A)

    def test_ring_passability_identical(self):
        diff = int(((self.ref_free != self.got_free) & self.ring).sum())
        self.assertEqual(diff, 0, "링 영역 1 m 통행성이 공식 맵과 다르다")

    def test_topology_arrays_identical_in_ring(self):
        rt = extract_topology(self.ref_free, self.ref_st)
        gt = extract_topology(self.got_free, self.got_st, spec=self.topo)
        for attr in ("v_aisle_rank", "main_aisle", "loop_fwd", "junction"):
            with self.subTest(attr):
                d = int(((getattr(rt, attr) != getattr(gt, attr)) & self.ring).sum())
                self.assertEqual(d, 0)

    def test_station_kinds_and_counts_match(self):
        def counts(st):
            out = {}
            for k in st:
                out[k.split("[")[0]] = out.get(k.split("[")[0], 0) + 1
            return out
        self.assertEqual(counts(self.got_st), counts(self.ref_st))

    def test_only_stations_outside_the_ring_moved(self):
        """링 밖 부속 구역(r74~88)은 모형에 없다 — 옮겨지는 스테이션은 그 3종뿐."""
        moved = {k for k in set(self.ref_st) & set(self.got_st)
                 if self.ref_st[k] != self.got_st[k]}
        self.assertEqual(moved, {"input[0]", "output[1]", "returns[0]", "returns[1]"})
        for name in moved - {"input[0]"}:            # input[0] 은 r39 → r40, 링 경계 한 칸
            self.assertFalse(self.ring[self.ref_st[name]], f"{name} 은 원래 링 밖이어야")

    def test_charge_zone_matches(self):
        ref = load_charge_zone(self.ref_free, MAP_DIR)
        got = load_charge_zone(self.got_free, self.tmp)
        self.assertTrue(np.array_equal(ref, got))


class RackVariantTest(unittest.TestCase):
    """랙 블록만 바꾸는 변주 — 데이터셋 기본 모드."""

    def test_wall_a_is_a_member_of_the_family(self):
        """통로 11개·간격 6·길이 21 = 공식 맵 토폴로지. 합성과 실측이 같은 규칙에서 나온다."""
        self.assertEqual(sw.rack_variant_spec(11, 6, 21).topology(), WALL_A)
        self.assertEqual(sw.rack_variant_spec(11, 6, 21).name, "r11p6l21")

    def test_every_combination_builds(self):
        """격자 전체가 배치 규칙(간격 3)을 만족한다 — 뽑는 개수를 늘려도 안 깨진다."""
        specs = sw.rack_variant_grid(len(sw.RACK_VARIANT_AISLES) * len(sw.RACK_VARIANT_PITCH)
                                     * len(sw.RACK_VARIANT_LEN))
        for spec in specs:
            with self.subTest(spec.name):
                blocked, topo = sw.build_blocked(spec)
                self.assertEqual(topo.n_aisles, spec.n_aisles)
                self.assertEqual(sw.close_station_pairs(sw.place_stations(spec, topo)), [])

    def test_rejects_layouts_with_no_racks(self):
        """통로가 맞닿아 랙 블록이 빈 홀이 되는 조합은 만들지 않는다 — 창고가 아닌 것이 섞인다."""
        for half, pitch in ((1, 3), (2, 4), (2, 5), (3, 7)):
            with self.subTest(half=half, pitch=pitch):
                with self.assertRaises(AssertionError):
                    sw.WarehouseSpec(name="x", n_aisles=5, aisle_pitch=pitch,
                                     aisle_half_width=half, aisle_len=21)

    def test_accepted_layouts_actually_have_racks(self):
        for half, pitch in ((1, 4), (1, 6), (2, 6), (2, 8)):
            with self.subTest(half=half, pitch=pitch):
                spec = sw.WarehouseSpec(name="x", n_aisles=5, aisle_pitch=pitch,
                                        aisle_half_width=half, aisle_len=21,
                                        station_lines=sw.RACK_VARIANT_STATION_LINES)
                blocked, topo = sw.build_blocked(spec)
                rack = blocked[topo.va_rows[0]:topo.va_rows[1],
                               topo.band_w_cols[1]:topo.band_e_cols[0]]
                self.assertGreater(int(rack.sum()), 0)

    def test_grid_picks_are_distinct_and_deterministic(self):
        names = [s.name for s in sw.rack_variant_grid(12)]
        self.assertEqual(len(set(names)), 12)
        self.assertEqual(names, [s.name for s in sw.rack_variant_grid(12)])

    def test_bands_and_station_counts_are_held_at_wall_a(self):
        """변인은 랙 기하 하나 — 밴드 두께와 스테이션 개수는 창고마다 같아야 한다."""
        base = None
        for spec in sw.rack_variant_grid(12):
            with self.subTest(spec.name):
                self.assertEqual((spec.band_s, spec.band_n, spec.band_w, spec.band_e),
                                 (7, 6, 12, 10))
                counts = spec.station_counts()
                counts.pop("aisle_buf")            # 통로마다 2개라 통로 수를 따라간다
                if base is None:
                    base = counts
                self.assertEqual(counts, base)


class RandomWarehouseTest(unittest.TestCase):
    """무작위 스펙이 실제로 쓸 수 있는 맵 세트를 내는가."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="synth_rand_")
        rng = np.random.default_rng(20260908)
        cls.dirs = []
        for i in range(N_RANDOM):
            spec = sw.random_spec(rng, f"w{i:02d}", seed=20260908)
            d = str(Path(cls.tmp) / spec.name)
            sw.write_set(spec, d)
            cls.dirs.append((spec, d))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_downsample_round_trip(self):
        """0.1 m 격자를 다시 다운샘플하면 의도한 1 m 통행성이 정확히 나온다."""
        for spec, d in self.dirs:
            with self.subTest(spec.name):
                blocked, _ = sw.build_blocked(spec)
                self.assertTrue(np.array_equal(load_map(d)[0], ~blocked))

    def test_station_cells_round_trip(self):
        """cell_to_xy 로 적은 좌표가 map_loader 를 거쳐 같은 칸으로 돌아온다."""
        for spec, d in self.dirs:
            with self.subTest(spec.name):
                blocked, topo = sw.build_blocked(spec)
                want = sw.place_stations(spec, topo)
                _, st_cell, _ = load_map(d)
                for kind, pts in want.items():
                    for i, rc in enumerate(pts):
                        self.assertEqual(st_cell[f"{kind}[{i}]"], rc)

    def test_topology_matches_the_spec_it_shipped(self):
        """세트가 들고 온 topology.json 이 레이아웃과 어긋나지 않는다."""
        for spec, d in self.dirs:
            with self.subTest(spec.name):
                free, st_cell, _ = load_map(d)
                topo = load_topology_spec(d)
                self.assertEqual(topo, spec.topology())
                t = extract_topology(free, st_cell, spec=topo)
                # 통로 rank 는 0..n-1 이 전부 나타나고, 교차로는 통로마다 위·아래 두 목
                self.assertEqual(sorted(set(np.unique(t.v_aisle_rank)) - {-1}),
                                 list(range(topo.n_aisles)))
                width = 2 * topo.va_half_width + 1
                self.assertEqual(int(t.junction.sum()), 2 * topo.n_aisles * width)

    def test_aisle_block_closes_every_aisle(self):
        for spec, d in self.dirs:
            with self.subTest(spec.name):
                topo = load_topology_spec(d)
                free = load_map(d, aisle_block=True)[0]
                r0, r1 = topo.va_rows
                for center in topo.va_centers:
                    c0, c1 = topo.aisle_cols(center)
                    self.assertFalse(free[r0:r1, c0:c1].any())

    def test_all_stations_reachable_from_each_other(self):
        for spec, d in self.dirs:
            with self.subTest(spec.name):
                free, st_cell, _ = load_map(d, aisle_block=True)
                seen = _reachable(free, st_cell["packing[0]"])
                unreachable = [k for k, rc in st_cell.items() if not seen[rc]]
                self.assertEqual(unreachable, [])

    def test_charge_zone_seats_a_fleet(self):
        for spec, d in self.dirs:
            with self.subTest(spec.name):
                free = load_map(d, aisle_block=True)[0]
                zone = load_charge_zone(free, d) & free
                make_homes_zone(free, zone, 8)        # 예외 없이 8대가 앉으면 통과

    def test_no_close_station_pairs(self):
        """2칸 차체가 겹칠 간격(체비쇼프 <3)은 만들지 않는다 — 커널이 경고하는 조건."""
        for spec, d in self.dirs:
            with self.subTest(spec.name):
                cells = sw.place_stations(spec, spec.topology())
                self.assertEqual(sw.close_station_pairs(cells), [])

    def test_from_theta_runs_on_synthetic_maps(self):
        theta = GuidanceTheta.neutral()
        theta.loop_gain, theta.wait_cost = 3.0, 2.0
        for spec, d in self.dirs:
            with self.subTest(spec.name):
                free, st_cell, _ = load_map(d, aisle_block=True)
                g = from_theta(free, extract_topology(free, st_cell, spec=load_spec(d)), theta)
                self.assertEqual(g.edge_cost.shape, free.shape + (4,))
                self.assertTrue(np.isfinite(g.edge_cost).all())

    def test_spec_json_round_trip(self):
        for spec, d in self.dirs:
            with self.subTest(spec.name):
                again = sw.load_spec_file(d)
                self.assertEqual(again.to_dict(), spec.to_dict())


class BuildInputTest(unittest.TestCase):
    """AI 입력 텐서가 wallA 아닌 창고에서도 나온다 — 로드맵 3단계의 전제."""

    def test_tensor_on_a_synthetic_map(self):
        from ai_theta.data.build_input import build_guidance_input, stack_channels
        tmp = tempfile.mkdtemp(prefix="synth_input_")
        try:
            spec = sw.random_spec(np.random.default_rng(7), "w_input")
            sw.write_set(spec, tmp)
            inp = build_guidance_input(n_agents=12, order_rate=120, map_dir=tmp)
            x = stack_channels(inp)
            free = load_map(tmp)[0]
            self.assertEqual(x.shape, (39,) + free.shape)
            self.assertTrue(np.isfinite(x).all())
            self.assertGreater(float(inp.topology_tensor.sum()), 0.0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
