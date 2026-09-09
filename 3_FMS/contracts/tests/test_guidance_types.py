"""AI입출력명세서 §11의 GuidanceTheta 계약 테스트.

범위: θ 13개의 의미·범위 확정분만 검증한다. from_theta 구현이나 PIBT 스코어에
관한 것은 B트랙 이슈이므로 여기서 다루지 않는다
(docs/θ_경로_기준선.md#비용-규약과-주의점).
"""

from dataclasses import fields, replace
from pathlib import Path
import sys
import unittest

import numpy as np

FMS_ROOT = Path(__file__).resolve().parents[2]
if str(FMS_ROOT) not in sys.path:
    sys.path.insert(0, str(FMS_ROOT))

from contracts.guidance_types import (  # noqa: E402
    COST_MAX,
    COST_MIN,
    COST_NEUTRAL,
    EDGE_RULE_PRECEDENCE,
    GuidanceTheta,
    LOOP_DIR_CCW,
    LOOP_DIR_CW,
    THETA_CATEGORICAL_VALUES,
    THETA_CONTINUOUS_RANGES,
    THETA_FIELD_ORDER,
    max_realizable_edge_cost,
    min_realizable_edge_cost,
)


def theta_at_lower_bounds():
    return GuidanceTheta(
        **{name: bounds[0] for name, bounds in THETA_CONTINUOUS_RANGES.items()},
        aisle_period=1,
        aisle_phase=0,
        loop_dir=LOOP_DIR_CW,
    )


def theta_at_upper_bounds():
    return GuidanceTheta(
        **{name: bounds[1] for name, bounds in THETA_CONTINUOUS_RANGES.items()},
        aisle_period=3,
        aisle_phase=1,
        loop_dir=LOOP_DIR_CCW,
    )


class GuidanceThetaContractTest(unittest.TestCase):
    def test_field_order_matches_spec_section_11_3(self):
        dataclass_order = tuple(field.name for field in fields(GuidanceTheta))
        self.assertEqual(dataclass_order, THETA_FIELD_ORDER)
        self.assertEqual(
            theta_at_lower_bounds().as_vector(),
            [1.0, 0.5, 1.0, 0.5, 1.0, 0.5, 1.0, 0.5, 1, 0, 0, 1.0, 1.0],
        )

    def test_all_continuous_boundaries_are_allowed(self):
        theta_at_lower_bounds().validate()
        theta_at_upper_bounds().validate()

    def test_continuous_outside_range_is_rejected(self):
        base = theta_at_lower_bounds()
        for name, (lower, upper) in THETA_CONTINUOUS_RANGES.items():
            with self.subTest(name=name, side="lower"):
                with self.assertRaises(ValueError):
                    replace(base, **{name: lower - 0.01}).validate()
            with self.subTest(name=name, side="upper"):
                with self.assertRaises(ValueError):
                    replace(base, **{name: upper + 0.01}).validate()

    def test_non_finite_continuous_value_is_rejected(self):
        base = theta_at_lower_bounds()
        for value in (np.nan, np.inf, -np.inf):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    replace(base, wait_cost=value).validate()

    def test_all_categorical_values_are_allowed(self):
        base = theta_at_lower_bounds()
        for name, allowed in THETA_CATEGORICAL_VALUES.items():
            for value in allowed:
                with self.subTest(name=name, value=value):
                    replace(base, **{name: value}).validate()

    def test_fractional_or_unknown_category_is_rejected(self):
        base = theta_at_lower_bounds()
        with self.assertRaises(TypeError):
            replace(base, aisle_period=1.5).validate()
        with self.assertRaises(ValueError):
            replace(base, aisle_period=4).validate()
        with self.assertRaises(ValueError):
            replace(base, aisle_phase=2).validate()
        with self.assertRaises(ValueError):
            replace(base, loop_dir=-1).validate()


class ThetaRangeSanityTest(unittest.TestCase):
    """v2에서 하한을 0.4 -> 0.5로 올린 근거를 불변식으로 고정한다."""

    def test_no_continuous_lower_bound_falls_below_clamp_floor(self):
        # clamp 하한보다 낮은 하한은 단독 적용 시 항상 잘리므로 죽은 구간이 된다.
        for name, (lower, _) in THETA_CONTINUOUS_RANGES.items():
            with self.subTest(name=name):
                self.assertGreaterEqual(lower, COST_MIN)

    def test_neutral_value_is_representable_for_every_multiplier(self):
        # 중립 θ(전 배율 1.0)가 계약 범위 안에 있어야 B0 기준선 회귀가 가능하다.
        GuidanceTheta.neutral().validate()
        for name, (lower, upper) in THETA_CONTINUOUS_RANGES.items():
            with self.subTest(name=name):
                self.assertLessEqual(lower, COST_NEUTRAL)
                self.assertGreaterEqual(upper, COST_NEUTRAL)

    def test_neutral_theta_has_no_multiplier_other_than_one(self):
        neutral = GuidanceTheta.neutral()
        for _, names in EDGE_RULE_PRECEDENCE:
            for name in names:
                with self.subTest(name=name):
                    self.assertEqual(getattr(neutral, name), COST_NEUTRAL)


class RealizableCostBoundTest(unittest.TestCase):
    """배타 규칙(EDGE_RULE_PRECEDENCE)이 실제로 상한 포화를 없애는지 확인한다."""

    def test_v3_lane_multiplier_can_reach_upper_clamp(self):
        worst = theta_at_upper_bounds()
        self.assertEqual(max_realizable_edge_cost(worst), COST_MAX)

    def test_lower_clamp_saturation_is_still_possible(self):
        # 알려진 잔여 문제: 큰 통로 내부 순방향 간선은 0.5 * 0.5 = 0.25 로 잘린다.
        cheapest = theta_at_lower_bounds()
        self.assertEqual(min_realizable_edge_cost(cheapest), COST_MIN)

    def test_neutral_theta_realizes_exactly_the_neutral_cost(self):
        neutral = GuidanceTheta.neutral()
        self.assertEqual(max_realizable_edge_cost(neutral), COST_NEUTRAL)
        self.assertEqual(min_realizable_edge_cost(neutral), COST_NEUTRAL)


if __name__ == "__main__":
    unittest.main()
