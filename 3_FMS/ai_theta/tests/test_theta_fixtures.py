# -*- coding: utf-8 -*-
"""규칙별 θ 세트를 실제 from_theta 출력과 대조한다 (S15P21A106-126).

범위는 sim_engine/from_theta_demo.py 가 [1]~[5]로 다루지 않는 부분이다.
demo는 범주형 3개를 전부 neutral 기본값(period=1 / phase=0 / loop_dir=0)으로만
쓰기 때문에, aisle_period·aisle_phase·loop_dir 이 실제로 반영되는지는 검증되지
않은 상태였다. 여기서 그 부분을 채운다.

실행: 3_FMS/ 에서  python ai_theta/tests/test_theta_fixtures.py
"""

from pathlib import Path
import sys
import unittest

import numpy as np

FMS_ROOT = Path(__file__).resolve().parents[2]        # 3_FMS/
SIM_ENGINE = FMS_ROOT / "sim_engine"                  # from_theta 는 flat import 를 쓴다
for p in (str(FMS_ROOT), str(SIM_ENGINE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from contracts.guidance_types import GuidanceTheta  # noqa: E402
from from_theta import extract_topology, from_theta  # noqa: E402
from map_loader import load_map  # noqa: E402

from ai_theta.theta_fixtures import (  # noqa: E402
    AISLE_FIXTURES,
    E,
    FIXTURES,
    N,
    N_VERTICAL_AISLES,
    S,
    W,
    by_name,
)

# 통로 내부 간선만 보는 행 구간. from_theta.VA_ROWS = (47, 68) 이므로 양 끝 행을
# 제외해야 "양 끝이 같은 aisle_id"인 간선만 남는다 (from_theta_demo 와 동일 구간).
# 2026-09-03 맵 동기화(랙 1 m 연장)로 (49, 66) → (48, 67).
AISLE_INNER_ROWS = slice(48, 67)

# 링 위의 알려진 셀 — from_theta_demo [4]가 쓰는 좌표.
SOUTH_BAND_CELL = (44, 60)   # 남 밴드: 시계 순방향 = 서
NORTH_BAND_CELL = (70, 60)   # 북 밴드: 시계 순방향 = 동

# 방향 델타 (pibt_core.DIRS 와 동일: 0=북 1=동 2=남 3=서)
DELTAS = ((1, 0), (0, 1), (-1, 0), (0, -1))


def neighbor_values(a, d, fill):
    """out[r, c] = a[방향 d 의 이웃]. 격자 밖은 fill.

    from_theta 의 _shift 를 쓰지 않고 따로 구현한다 — 검증 대상의 코드를 그대로
    빌려오면 같은 버그를 함께 통과시킨다.
    """
    dr, dc = DELTAS[d]
    out = np.roll(a, (-dr, -dc), axis=(0, 1))
    if dr:
        out[-1 if dr > 0 else 0, :] = fill
    if dc:
        out[:, -1 if dc > 0 else 0] = fill
    return out


def neighbor_mask(mask, d):
    return neighbor_values(mask, d, False)


def claimed_before_loop(topo, free, d):
    """loop 보다 앞선 그룹(station_spur, intersection_entry)이 방향 d 간선을 선점하나.

    배타 순서는 θ 값이 아니라 **기하로** 판정된다. station_in 이 중립 1.0 이어도
    그 간선은 '적용됨'으로 표시되어 뒤 그룹(loop 등)의 배율이 걸리지 않는다.
    즉 다른 파라미터를 1.0으로 두는 것만으로는 규칙이 완전히 격리되지 않는다.
    """
    passable = free & neighbor_mask(free, d)
    nb_entry = neighbor_values(topo.station_dir, d, np.int8(-1))
    station_in_edge = passable & (nb_entry >= 0) & (nb_entry == (d + 2) % 4)
    station_out_edge = passable & (topo.station_dir >= 0) & (topo.station_dir == d)
    junction_entry = passable & ~topo.junction & neighbor_mask(topo.junction, d)
    return station_in_edge | station_out_edge | junction_entry


def pick_dir(edge_cost, dir_index):
    """edge_cost[r, c, dir_index[r, c]] — 셀마다 다른 방향을 골라 뽑는다."""
    return np.take_along_axis(edge_cost, dir_index[..., None], axis=-1)[..., 0]


class FixtureShapeTest(unittest.TestCase):
    """세트가 '규칙 하나만 켠 상태'라는 전제를 구조적으로 보장한다."""

    def test_every_fixture_validates(self):
        for f in FIXTURES:
            with self.subTest(name=f.name):
                f.theta.validate()

    def test_nothing_outside_declared_fields_deviates_from_neutral(self):
        # 이게 깨지면 '나머지는 전부 1.0'이 무너져서, 히트맵에 나온 패턴이 어느
        # 규칙 때문인지 특정할 수 없게 된다. 세트 전체의 존재 이유가 사라진다.
        # 반대 방향(선언했지만 중립과 같은 값)은 허용한다 — LOOP_ONEWAY_CW 의
        # loop_dir=0 처럼 읽는 사람을 위해 일부러 명시한 경우가 있다.
        neutral = GuidanceTheta.neutral()
        for f in FIXTURES:
            deviating = {
                name for name in vars(neutral)
                if getattr(f.theta, name) != getattr(neutral, name)
            }
            with self.subTest(name=f.name):
                self.assertTrue(
                    deviating <= set(f.overrides),
                    f"선언하지 않은 필드가 중립에서 벗어남: {deviating - set(f.overrides)}",
                )

    def test_aisle_pref_covers_every_vertical_aisle(self):
        for f in AISLE_FIXTURES:
            with self.subTest(name=f.name):
                self.assertEqual(len(f.aisle_pref), N_VERTICAL_AISLES)
                self.assertTrue(set(f.aisle_pref) <= {N, S})

    def test_expected_and_hint_are_filled(self):
        for f in FIXTURES:
            with self.subTest(name=f.name):
                self.assertTrue(f.expected.strip())
                self.assertTrue(f.failure_hint.strip())


class FromThetaAgainstFixturesTest(unittest.TestCase):
    """실제 from_theta 출력과 기대 결과를 대조한다."""

    @classmethod
    def setUpClass(cls):
        free, st_cell, _ = load_map()                         # 공식 맵 3_FMS/map
        cls.free = free
        cls.topo = extract_topology(free, st_cell)

    def _edge_cost(self, fixture):
        return from_theta(self.free, self.topo, fixture.theta).edge_cost

    def test_neutral_is_uniform(self):
        # 이게 깨지면 아래 결과는 전부 무의미하다. 가장 먼저 본다.
        ec = self._edge_cost(by_name("NEUTRAL"))
        self.assertTrue(np.allclose(ec, 1.0))

    def test_aisle_direction_matches_hand_computed_table(self):
        """범주형 aisle_period / aisle_phase 검증 (demo 미커버).

        fixture 의 aisle_pref 는 from_theta 의 group 공식을 쓰지 않고 손으로
        전개한 표다. 공식이 틀리면(몫 대신 나머지, phase 부호 반전 등) 여기서 걸린다.
        """
        rank = self.topo.v_aisle_rank
        for f in AISLE_FIXTURES:
            ec = self._edge_cost(f)
            for aisle_id, pref in enumerate(f.aisle_pref):
                cells = np.zeros_like(rank, dtype=bool)
                cells[AISLE_INNER_ROWS] = True
                cells &= rank == aisle_id
                with self.subTest(name=f.name, aisle=aisle_id, pref="N" if pref == N else "S"):
                    self.assertTrue(cells.any(), "통로 내부 간선을 못 찾음: 행 구간 확인")
                    cheap = ec[..., pref][cells]
                    costly = ec[..., (pref + 2) % 4][cells]
                    self.assertTrue(np.all(cheap < costly))

    def test_phase_flip_inverts_every_aisle(self):
        base, flipped = by_name("AISLE_ONEWAY_MAX"), by_name("AISLE_PHASE_1")
        for a, b in zip(base.aisle_pref, flipped.aisle_pref):
            self.assertEqual(b, (a + 2) % 4)

        ec_base = self._edge_cost(base)
        ec_flip = self._edge_cost(flipped)
        inner = np.zeros(self.topo.v_aisle_rank.shape, dtype=bool)
        inner[AISLE_INNER_ROWS] = True
        inner &= self.topo.v_aisle_rank >= 0
        # 통로 내부에서 북/남 비용이 서로 맞바뀌어야 한다.
        self.assertTrue(np.allclose(ec_base[..., N][inner], ec_flip[..., S][inner]))
        self.assertTrue(np.allclose(ec_base[..., S][inner], ec_flip[..., N][inner]))

    def test_loop_dir_selects_circulation_sense_at_known_cells(self):
        """범주형 loop_dir 검증 (demo 는 loop_dir=0 만 확인)."""
        cw = self._edge_cost(by_name("LOOP_ONEWAY_CW"))
        ccw = self._edge_cost(by_name("LOOP_ONEWAY_CCW"))
        gain = by_name("LOOP_ONEWAY_CW").theta.loop_gain

        # 남 밴드: 시계 순방향 = 서 → CW 는 동행(역방향)이 비싸다
        self.assertAlmostEqual(float(cw[SOUTH_BAND_CELL][E]), gain, places=5)
        self.assertAlmostEqual(float(cw[SOUTH_BAND_CELL][W]), 1.0, places=5)
        # 북 밴드: 시계 순방향 = 동 → CW 는 서행이 비싸다
        self.assertAlmostEqual(float(cw[NORTH_BAND_CELL][W]), gain, places=5)
        self.assertAlmostEqual(float(cw[NORTH_BAND_CELL][E]), 1.0, places=5)

        # CCW 는 정확히 반대여야 한다
        self.assertAlmostEqual(float(ccw[SOUTH_BAND_CELL][W]), gain, places=5)
        self.assertAlmostEqual(float(ccw[SOUTH_BAND_CELL][E]), 1.0, places=5)
        self.assertAlmostEqual(float(ccw[NORTH_BAND_CELL][E]), gain, places=5)
        self.assertAlmostEqual(float(ccw[NORTH_BAND_CELL][W]), 1.0, places=5)

    def test_loop_dir_penalizes_the_opposite_sense_on_every_interior_loop_cell(self):
        """링 전체에서 loop_dir 이 벌금 방향을 뒤집는지.

        두 부류를 검사에서 뺀다. 둘 다 합의된 규칙대로 동작한 결과다.

        1) 링 경계 셀 — from_theta 는 "양 끝이 링"인 간선에만 규칙을 적용하므로,
           링 진행축의 두 이웃 중 하나가 링 밖이면 CW 와 CCW 가 서로 다른 이웃을
           보게 되어 대칭이 성립하지 않는다 (밴드 첫 행/끝 열).
        2) 상위 그룹이 선점한 간선 — 배타 순서가 θ 값이 아니라 기하로 판정되므로,
           station_in 이 중립 1.0 이어도 그 간선에는 loop_gain 이 걸리지 않는다.
           실측 wallA 에서 1개 셀(43,93)이 여기 해당한다.
        """
        cw = self._edge_cost(by_name("LOOP_ONEWAY_CW"))
        ccw = self._edge_cost(by_name("LOOP_ONEWAY_CCW"))
        gain = by_name("LOOP_ONEWAY_CW").theta.loop_gain

        fwd = self.topo.loop_fwd                      # 시계 방향 접선, -1 = 링 아님
        on_loop = fwd >= 0
        nb_on = np.stack([neighbor_mask(on_loop, d) for d in range(4)], axis=-1)

        cw_dir = np.clip(fwd, 0, 3).astype(np.intp)   # 시계 방향
        ccw_dir = (cw_dir + 2) % 4                    # 반시계 방향
        interior = on_loop & pick_dir(nb_on, cw_dir) & pick_dir(nb_on, ccw_dir)

        claimed = np.stack(
            [claimed_before_loop(self.topo, self.free, d) for d in range(4)], axis=-1
        ).astype(np.int8)
        interior &= ~pick_dir(claimed, cw_dir).astype(bool)
        interior &= ~pick_dir(claimed, ccw_dir).astype(bool)
        self.assertGreater(interior.sum(), 0, "내부 링 셀을 못 찾음")

        # CW(시계 순방향)에서는 반시계 이동이 벌금, 시계 이동은 1.0
        self.assertTrue(np.allclose(pick_dir(cw, ccw_dir)[interior], gain))
        self.assertTrue(np.allclose(pick_dir(cw, cw_dir)[interior], 1.0))
        # CCW 는 정확히 반대
        self.assertTrue(np.allclose(pick_dir(ccw, cw_dir)[interior], gain))
        self.assertTrue(np.allclose(pick_dir(ccw, ccw_dir)[interior], 1.0))

    def test_main_aisle_gain_applies_only_when_both_ends_are_main(self):
        """main_aisle_gain 단독 (demo 는 1.2 를 loop 와 곱한 형태로만 확인)."""
        fixture = by_name("MAIN_AISLE_PREFER")
        ec = self._edge_cost(fixture)
        gain = fixture.theta.main_aisle_gain
        main = self.topo.main_aisle

        for d in range(4):
            passable = self.free & neighbor_mask(self.free, d)
            both_main = passable & main & neighbor_mask(main, d)
            one_end = passable & ~both_main
            with self.subTest(dir=d):
                self.assertTrue(np.allclose(ec[..., d][both_main], gain))
                # 다른 배율이 전부 1.0이므로 나머지 간선은 손대지 않아야 한다
                self.assertTrue(np.allclose(ec[..., d][one_end], 1.0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
