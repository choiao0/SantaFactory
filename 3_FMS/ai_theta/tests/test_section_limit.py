# -*- coding: utf-8 -*-
"""구간 대수 제한 검증 (S15P21A106-193).

마주침(소싸움)을 블록 단위 동시 대수로 묶는 규칙이다. 못 박는 것 셋.

1. **안 켜면 아무것도 안 변한다.** `--section-limit` 없이는 시뮬 경로에 규칙이 안 붙고
   SUMMARY 에 키가 안 생긴다. 기준값 3개를 다시 안 재도 되는 근거가 이것이다.
2. **진입만 막고 퇴출은 막지 않는다.** 이게 깨지면 구간이 영영 안 비워져 교착이 난다.
3. **정체 면제가 산다.** 통행 칸 전체를 타일링하면 구간 밖 대피처가 없어 순환 대기가
   실제로 난다(블록 4·6·8 × 정원 1·2·3, 8가지 전부 STALL 실측). 정체 8틱 초과 로봇을
   정원에서 푸는 게 유일한 탈출구다.

실행: 3_FMS/ 에서  python ai_theta/tests/test_section_limit.py
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

from map_loader import MAP_DIR, load_map  # noqa: E402
from pibt.heading import _PIBTStepH, step_h  # noqa: E402
from sim_v2_tasks import block_sections, parse_args  # noqa: E402


class TestBlockSections(unittest.TestCase):
    """블록 격자 자체. 맵을 안 보고 자르므로 topology.json 이 없어도 된다."""

    @classmethod
    def setUpClass(cls):
        cls.free, _, _ = load_map(MAP_DIR, aisle_block=1)

    def test_walls_are_not_sections(self):
        sec = block_sections(self.free, 3)
        self.assertTrue((sec[~self.free] == -1).all(), "벽이 구간에 들어갔다")
        self.assertTrue((sec[self.free] >= 0).all(), "통행 칸인데 구간이 없다")

    def test_block_is_k_by_k(self):
        """한 구간의 칸들이 k×k 상자 안에 들어간다 — 벽에 잘려 더 작을 수는 있다."""
        k = 3
        sec = block_sections(self.free, k)
        for sid in np.unique(sec[sec >= 0])[:200]:
            rs, cs = np.where(sec == sid)
            self.assertLessEqual(rs.max() - rs.min(), k - 1)
            self.assertLessEqual(cs.max() - cs.min(), k - 1)

    def test_k_one_gives_one_cell_each(self):
        sec = block_sections(self.free, 1)
        ids = sec[self.free]
        self.assertEqual(len(set(ids.tolist())), int(self.free.sum()))

    def test_smaller_k_makes_more_sections(self):
        n = [len(np.unique(block_sections(self.free, k)[self.free])) for k in (2, 3, 6)]
        self.assertGreater(n[0], n[1])
        self.assertGreater(n[1], n[2])


class TestEntryRule(unittest.TestCase):
    """진입만 금지 — `_entry_ok` 를 직접 친다. 전 구간이 한 블록인 장난감 격자를 쓴다."""

    def _step(self, limit, sec_free=()):
        free = np.ones((1, 6), dtype=bool)
        sec = np.zeros((1, 6), dtype=np.int16)      # 6칸 전부 구간 0
        sec[0, 3:] = 1                              # 오른쪽 3칸은 구간 1
        states = {0: (0, 1, 1), 1: (0, 4, 1)}       # 동쪽(h=1) 향한 두 대
        ps = _PIBTStepH(states, {}, None, None, free, 1.0, {}, {}, sec, limit, sec_free)
        return ps, sec

    def test_counts_are_per_robot_not_per_cell(self):
        """몸이 2칸이어도 한 구간에 1대로 센다 — 인자 이름이 '대수'다."""
        ps, _ = self._step(2)
        self.assertEqual(ps.sec_cnt.get(0), 1)
        self.assertEqual(ps.sec_cnt.get(1), 1)

    def test_entry_into_full_section_is_denied(self):
        ps, _ = self._step(1)
        self.assertFalse(ps._entry_ok(0, frozenset({(0, 3), (0, 2)})), "정원 찬 구간에 들어갔다")
        self.assertIn(0, ps.denied)

    def test_staying_and_leaving_are_always_allowed(self):
        ps, _ = self._step(1)
        self.assertTrue(ps._entry_ok(0, ps.now_cells[0]), "제자리가 막혔다")
        self.assertTrue(ps._entry_ok(1, frozenset({(0, 5), (0, 4)})), "구간 안 이동이 막혔다")
        # 구간 1 → 구간 0 은 구간 0 이 차 있어도 '퇴출' 이 아니라 '진입' 이라 막힌다.
        # 반대로 구간 0 안에 있는 0번이 구간 0 안에서 움직이는 건 늘 된다.
        self.assertTrue(ps._entry_ok(0, frozenset({(0, 0), (0, 1)})))

    def test_stagnation_release_overrides_the_limit(self):
        ps, _ = self._step(1, sec_free={0})
        self.assertTrue(ps._entry_ok(0, frozenset({(0, 3), (0, 2)})), "면제가 안 먹었다")

    def test_limit_zero_is_off(self):
        ps, _ = self._step(0)
        self.assertFalse(ps.on)
        self.assertTrue(ps._entry_ok(0, frozenset({(0, 3), (0, 2)})))


class TestBacktrackingKeepsTheCount(unittest.TestCase):
    """PIBT 는 예약을 되돌린다. 계수가 같이 안 돌아오면 구간이 영영 찬 것으로 남는다."""

    def test_release_restores_the_count(self):
        free = np.ones((1, 6), dtype=bool)
        sec = np.zeros((1, 6), dtype=np.int16)
        sec[0, 3:] = 1
        states = {0: (0, 1, 1)}
        ps = _PIBTStepH(states, {}, None, None, free, 1.0, {}, {}, sec, 2, ())
        before = dict(ps.sec_cnt)
        ps._reserve(0, (0, 3, 1), frozenset({(0, 3), (0, 2)}))
        self.assertNotEqual(dict(ps.sec_cnt), before, "예약이 계수에 반영 안 됐다")
        ps._release(0)
        self.assertEqual({k: v for k, v in ps.sec_cnt.items() if v},
                         {k: v for k, v in before.items() if v})


class TestOffByDefault(unittest.TestCase):
    """안 켜면 규칙이 통째로 없다 — 기준값 3개를 재측정 안 해도 되는 근거."""

    def test_default_limit_is_zero(self):
        a = parse_args(["t", "6", "40", "42", "1"])
        self.assertEqual(a.section_limit, 0)

    def test_grid_defaults_to_three(self):
        """실측 무릎. 크면 정체 면제로 풀려 무력해지고(8×8), 작으면 대가가 커진다(2×2)."""
        a = parse_args(["t", "6", "40", "42", "1"])
        self.assertEqual(a.section_grid, 3)

    def test_cell_model_turns_it_off(self):
        a = parse_args(["t", "6", "40", "42", "1", "--cell", "--section-limit=1"])
        self.assertEqual(a.section_limit, 0)
        self.assertTrue(any("section-limit" in w for w in a.warnings))

    def test_step_h_without_sections_is_unconstrained(self):
        """sec_map 이 None 이면 장치가 꺼진다 — 반환 3번째(denied)가 늘 비어야 한다."""
        free = np.ones((1, 4), dtype=bool)
        edge = np.ones((1, 4, 4))
        wait = np.ones((1, 4))
        dist = np.zeros((1, 4, 4))
        states = {0: (0, 1, 1)}
        _, _, denied = step_h(states, {0: dist}, edge, wait, free, [0], 1.0)
        self.assertEqual(denied, set())


if __name__ == "__main__":
    unittest.main(verbosity=2)
