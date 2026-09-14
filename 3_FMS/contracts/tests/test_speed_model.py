# -*- coding: utf-8 -*-
"""적재량 → 속도 함수 (S15P21A106-116). 앵커는 AI입출력명세서 §7 운영 속도(공차 1.5 · 적재 1.0)를 예로 쓴다."""
from pathlib import Path
import sys
import unittest

FMS_ROOT = Path(__file__).resolve().parents[2]
if str(FMS_ROOT) not in sys.path:
    sys.path.insert(0, str(FMS_ROOT))

from contracts.speed_model import speed_for_load  # noqa: E402

SPEC = dict(v_empty=1.5, v_full=1.0, max_load_kg=100.0)


class SpeedForLoad(unittest.TestCase):
    def test_empty_is_v_empty(self):
        self.assertAlmostEqual(speed_for_load(0.0, **SPEC), 1.5)

    def test_full_is_v_full(self):
        self.assertAlmostEqual(speed_for_load(100.0, **SPEC), 1.0)

    def test_half_load_is_midpoint(self):
        self.assertAlmostEqual(speed_for_load(50.0, **SPEC), 1.25)

    def test_overload_clamps_to_v_full(self):
        self.assertAlmostEqual(speed_for_load(250.0, **SPEC), 1.0)

    def test_v_min_floor(self):
        self.assertAlmostEqual(speed_for_load(100.0, v_min=1.2, **SPEC), 1.2)

    def test_v_cap_ceiling_plan_speed(self):
        # 물리 팀 계획 속도 0.9 를 상한으로 걸면 공차라도 0.9
        self.assertAlmostEqual(speed_for_load(0.0, v_cap=0.9, **SPEC), 0.9)

    def test_same_anchors_give_fixed_speed(self):
        # V1 (명세 §7): 공차 = 적재 = 1.0 → 무게와 무관하게 1.0
        for load in (0.0, 30.0, 100.0):
            self.assertAlmostEqual(speed_for_load(load, v_empty=1.0, v_full=1.0, max_load_kg=100.0), 1.0)

    def test_rejects_bad_anchors(self):
        with self.assertRaises(ValueError):
            speed_for_load(0.0, v_empty=1.0, v_full=1.5, max_load_kg=100.0)
        with self.assertRaises(ValueError):
            speed_for_load(0.0, v_empty=1.5, v_full=1.0, max_load_kg=0.0)
        with self.assertRaises(ValueError):
            speed_for_load(-1.0, **SPEC)
        with self.assertRaises(ValueError):
            speed_for_load(0.0, v_min=1.0, v_cap=0.9, **SPEC)


if __name__ == "__main__":
    unittest.main()
