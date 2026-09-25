# -*- coding: utf-8 -*-
"""전진·회전 틱 모델 검증 (S15P21A106-194).

물리 실행기가 **연속 주행**(ADG 블렌딩)으로 가므로, 직진 런 안에서는 칸마다 서지 않는다.
우리 조건에서 잰 칸당 1.193 s 와 회전 1.450 s 로 비율 1.215 → 전진 4틱 · 회전 5틱이다.
(매 칸 정지였다면 1.929 s/칸 · 비율 0.751 → 4:3 이었다.) 못 박는 것 넷.

1. **거리장 가중은 틱 수가 아니라 배율이다.** `edge_cost` 기준이 1.0 이라 회전에 틱 수 5 를
   그대로 넣으면 회전이 전진의 5배가 된다. `TURN_COST = 5/4 = 1.25`.
2. **동작이 실제로 그 틱을 쓴다.** 안 막힌 로봇은 전진 1칸에 4틱, 90° 회전에 5틱.
3. **칸 모델은 안 변한다.** 다틱 이동은 헤딩 전용이고 `dt` 도 모델별로 갈렸다 —
   칸 모델까지 MOVE_TICKS 로 나누면 서비스 틱이 4 → 15 가 되어 A/B 비교축이 깨진다.
4. **주행거리는 밟은 칸이다.** 전에는 1칸 = 1틱이라 주행 틱을 그대로 미터로 썼는데,
   이제 한 칸이 4틱이라 그대로 두면 4배로 부풀어 오른다.

실행: 3_FMS/ 에서  python ai_theta/tests/test_tick_model.py
"""
import collections
import os
from pathlib import Path
import sys
import unittest

FMS_ROOT = Path(__file__).resolve().parents[2]
SIM_ENGINE = FMS_ROOT / "sim_engine"
for p in (str(FMS_ROOT), str(SIM_ENGINE)):
    if p not in sys.path:
        sys.path.insert(0, p)
os.environ.setdefault("SIM_NO_PLOT", "1")

from map_loader import CELL_M  # noqa: E402
from pibt.geometry import MOVE_TICKS, TURN_COST, TURN_TICKS  # noqa: E402
from kernel.core import KernelConfig  # noqa: E402
from kernel.states import NAV  # noqa: E402
import sim_v2_tasks as S  # noqa: E402

# 물리 실측(sim_check 2026-09-13)이 역산한 값
ACCEL, ALPHA = 1.10, 3.12          # m/s², rad/s²
V_MAX, W_MAX = 0.90, 1.80          # m/s, rad/s


def _trapezoid(dist, v_max, accel):
    """가속→순항→감속에 걸리는 시간[초]. 순항 구간이 없으면 삼각 프로파일."""
    d_ramp = v_max * v_max / (2 * accel)
    if 2 * d_ramp >= dist:
        return 2 * (dist / accel) ** 0.5
    return 2 * (v_max / accel) + (dist - 2 * d_ramp) / v_max


# 연속 주행에서 우리 조건으로 잰 칸당 시간 (직진 런 27,925개 · 277,647칸).
# 런마다 ramp 시간을 더해 칸 수로 나눈 값이다 — 평균 런 길이로 계산하면 안 된다.
MEASURED_S_PER_CELL = 1.193


class TestRatioFromPhysics(unittest.TestCase):
    def test_turn_time_is_the_floor(self):
        """각가속이 장비 최대라 회전 1.450 s 는 못 내린다 — 비율의 분자가 고정이다."""
        self.assertAlmostEqual(_trapezoid(3.141592653589793 / 2, W_MAX, ALPHA), 1.450, places=2)

    def test_stopping_every_cell_would_be_three_quarters(self):
        """채택 안 한 쪽. 매 칸 서면 1.929 s/칸 이라 회전이 오히려 싸진다(0.75)."""
        self.assertAlmostEqual(_trapezoid(CELL_M, V_MAX, ACCEL), 1.929, places=2)

    def test_continuous_running_makes_turns_expensive(self):
        """채택한 쪽. 연속 주행이면 칸당 1.193 s 라 비율이 1.215 → 4:5 (오차 +2.9%)."""
        turn_s = _trapezoid(3.141592653589793 / 2, W_MAX, ALPHA)
        ratio = turn_s / MEASURED_S_PER_CELL
        self.assertGreater(ratio, 1.0, "연속 주행이면 회전이 전진보다 비싸야 한다")
        self.assertAlmostEqual(TURN_TICKS / MOVE_TICKS, ratio, delta=0.05)

    def test_physics_grid_run_estimate_agrees(self):
        """물리팀 추정(평균 직진 런 12.3칸)으로 계산해도 1.3 % 안에서 같은 값이 나온다."""
        per = _trapezoid(12.3 * CELL_M, V_MAX, ACCEL) / 12.3
        self.assertAlmostEqual(per, MEASURED_S_PER_CELL, delta=0.03)

    def test_physics_grid_reproduces_their_numbers(self):
        """같은 식이 1.2 m 에서 실측(2.17 s · 1.40 s)을 낸다 — 식이 맞다는 검산."""
        self.assertAlmostEqual(_trapezoid(1.2, V_MAX, ACCEL), 2.17, delta=0.05)

    def test_turn_cost_is_a_ratio_not_a_tick_count(self):
        """틱 수 5 를 그대로 쓰면 회전이 전진의 5배가 된다. 배율은 5/4 다."""
        self.assertAlmostEqual(TURN_COST, TURN_TICKS / MOVE_TICKS)
        self.assertLess(TURN_COST, TURN_TICKS, "틱 수를 그대로 쓰면 안 된다")

    def test_kernel_divides_by_move_ticks(self):
        """cfg 를 바꿔도 커널이 배율로 환산한다."""
        free, st_cell, _ = _map()
        k = _kernel(free, st_cell, KernelConfig(turn_ticks=5, move_ticks=4))
        self.assertAlmostEqual(k.turn_cost, 1.25)
        k2 = _kernel(free, st_cell, KernelConfig(turn_ticks=1, move_ticks=1))
        self.assertAlmostEqual(k2.turn_cost, 1.0)


class TestCadence(unittest.TestCase):
    """안 막힌 로봇이 동작당 실제로 그 틱을 쓰나."""

    @classmethod
    def setUpClass(cls):
        # 박자(틱 모델)만 잰다 — 회전 발자국 규칙과 무관하다. 기본 exact,ban(계약 v3.17, -277)은 좁은 회전을 거부해
        # 대기가 늘고 「혼잡 아닌 구간이 다수」 전제가 깨진다(전진 최빈 4틱 비율 < 0.9). 그래서 exact 로 고정한다.
        a = S.parse_args(["cad", "6", "40", "42", "1", "--footprint=exact"])
        k, stream, _ = S.build(a)
        prev = {r: (k.robots[r]["pos"], k.robots[r]["h"]) for r in k.rids}
        run, started = {r: 0 for r in k.rids}, {r: None for r in k.rids}
        cls.move, cls.turn = collections.Counter(), collections.Counter()
        t = 0
        while stream.outstanding > 0:
            for task in stream.arrivals(t):
                k.submit_task(task)
            k.dispatch(t)
            if stream.outstanding == 0:
                break
            nav = {r: k.robots[r]["state"] in NAV for r in k.rids}
            k.move(t)
            for r in k.rids:
                cur = (k.robots[r]["pos"], k.robots[r]["h"])
                if cur == prev[r]:
                    run[r] += 1
                    continue
                # 구간은 그것을 **시작한** 동작의 몫이다 (끝낸 동작이 아니라)
                if started[r] is not None and nav[r]:
                    (cls.move if started[r] == "move" else cls.turn)[run[r] + 1] += 1
                started[r] = "move" if cur[0] != prev[r][0] else "turn"
                prev[r], run[r] = cur, 0
            t += 1
        cls.kernel, cls.args = k, a

    def _mode(self, counter):
        return counter.most_common(1)[0]

    def test_forward_takes_move_ticks(self):
        n, cnt = self._mode(self.move)
        self.assertEqual(n, MOVE_TICKS)
        self.assertGreater(cnt / sum(self.move.values()), 0.9, "혼잡 아닌 경우가 다수여야 한다")

    def test_turn_takes_turn_ticks(self):
        n, cnt = self._mode(self.turn)
        self.assertEqual(n, TURN_TICKS)
        self.assertGreater(cnt / sum(self.turn.values()), 0.9)

    def test_never_faster_than_the_model(self):
        """모델보다 빠를 수는 없다 — 느린 쪽(혼잡)만 허용된다."""
        self.assertFalse([n for n in self.move if n < MOVE_TICKS])
        self.assertFalse([n for n in self.turn if n < TURN_TICKS])

    def test_distance_counts_cells_not_ticks(self):
        tot = self.kernel.totals()
        self.assertLess(tot["cells"], tot["drive"], "밟은 칸이 주행 틱보다 적어야 한다")
        self.assertAlmostEqual(tot["drive"] / tot["cells"], MOVE_TICKS, delta=0.3)


class TestCellModelUnchanged(unittest.TestCase):
    """칸 모델은 A/B 비교축이다 (-177 선례). 다틱도 dt 분할도 안 받는다."""

    def test_heading_dt_is_divided_by_move_ticks(self):
        a = S.parse_args(["t", "6", "40", "42", "1"])
        self.assertAlmostEqual(a.dt, CELL_M / (1.0 * MOVE_TICKS))

    def test_cell_model_dt_is_unchanged(self):
        for extra in (["--cell"], ["--flow=v1compat"]):
            a = S.parse_args(["t", "6", "40", "42", "1"] + extra)
            self.assertFalse(a.heading)
            self.assertAlmostEqual(a.dt, CELL_M / 1.0, msg=str(extra))

    def test_service_ticks_stay_four_for_cell_model(self):
        """dt 를 같이 나누면 서비스가 4 → 15틱이 되어 기준값이 깨진다."""
        a = S.parse_args(["t", "6", "40", "42", "1", "--cell"])
        self.assertEqual(round(S.SERVICE_TIME_S / a.dt), 4)


def _map():
    from map_loader import MAP_DIR, load_map
    return load_map(MAP_DIR, aisle_block=1)


def _kernel(free, st_cell, cfg):
    import numpy as np
    from fms_kernel import FmsKernel
    from map_loader import make_homes
    H, W = free.shape
    homes = make_homes(free, st_cell, 2)
    return FmsKernel(free, st_cell, np.ones((H, W, 4)), np.ones((H, W)), homes, 2, cfg)


if __name__ == "__main__":
    unittest.main(verbosity=2)
