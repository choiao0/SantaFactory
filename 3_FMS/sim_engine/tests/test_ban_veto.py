# -*- coding: utf-8 -*-
"""금지 조합표 거부 (S15P21A106-277): 회전 중 두 차체가 제어 오차(5 cm) 안으로 붙는 배치를 커널이 만들지 않는다.

09-25 점검(checks/turn_clearance.py): 운영 발자국 exact 는 est_18 10대 6시간 회전 8,539번 중 17.0 % 가
금지 조합표에 걸렸고(최소 틈 41 mm), Isaac 은 그 회전 앞에서 서로 기다리다 굳었다. 칸 규칙(front_2cell · front)은
표와 모양이 달라 0 으로 못 내린다 — 필요 없는 배치는 막고 코 대각·회전 중 들어오는 로봇은 놓친다.
그래서 표 자체로 거부한다: 도는 쪽은 이웃이 금지 배치면 안 돌고, 이웃은 도는 로봇 기준 금지 자리로 못 들어간다.
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pibt.geometry as geo  # noqa: E402
from pibt.ban import banned, build_table  # noqa: E402
from pibt.geometry import stay_map_h, swing_cells  # noqa: E402
from pibt.heading import step_h  # noqa: E402
from pibt.hgraph import dist_map_h  # noqa: E402

DIMS = (0.39, 1.11, 0.80)
TURNS = [(h, h2) for h in range(4) for h2 in ((h + 1) % 4, (h - 1) % 4)]


@pytest.fixture(autouse=True)
def _legacy_after():
    yield
    geo.reset()


def _ban_on():
    geo.configure(turn_mask=None, robot_dims=DIMS, ban=True)


class TestBanStates:
    def test_the_state_set_agrees_with_the_table_judge_everywhere(self):
        """커널은 (칸, 헤딩) 집합으로 묻고 점검 도구는 banned() 로 묻는다 — 둘이 한 칸도 달라선 안 된다."""
        _ban_on()
        tab = build_table(1.0, geo.FOOTPRINT_MARGIN_M, (DIMS[0], DIMS[1], DIMS[2] / 2))
        R = C = 5
        for h, h2 in TURNS:
            bs = geo.ban_states(R, C, h, h2)
            for r in range(R - 3, R + 4):
                for c in range(C - 3, C + 4):
                    for hb in range(4):
                        q = (r, c, hb)
                        assert (q in bs) == banned(tab, (R, C, h), (R, C, h2), [q]), (h, h2, q)

    def test_twenty_entries_like_the_physics_team_table(self):
        _ban_on()
        assert sum(len(geo.ban_states(5, 5, 0, h2)) for h2 in (1, 3)) == 20

    def test_off_means_empty(self):
        assert geo.ban_states(5, 5, 0, 1) == frozenset()
        assert not geo.ban_on()


def _scene():
    """9×9 빈 격자. A(4,4) 북향, 목표 (4,2) — 첫 수는 서쪽으로 돌기. 바로 앞 칸 (5,4) 에 B 가 동향으로 서 있다.
    B 의 몸 (5,4)·(5,3) 은 A 의 hard 칸(축·뒤·스윙 3칸) 밖이라 exact 는 돌린다 — 틈 41 mm, 표 ((1,0), h1)."""
    free = np.ones((9, 9), dtype=bool)
    states = {"A": (4, 4, 0), "B": (5, 4, 1)}
    dists = {"A": dist_map_h(free, (4, 2)), "B": dist_map_h(free, (5, 4))}
    return free, states, dists


def _step(free, states, dists, order, **kw):
    ones = np.ones(free.shape + (4,)), np.ones(free.shape)
    new, _, _ = step_h(states, dists, ones[0], ones[1], free, order, **kw)
    return new


class TestTurnVeto:
    def test_exact_turns_into_the_forty_millimetre_gap(self):
        free, states, dists = _scene()
        geo.configure(turn_mask=None, robot_dims=DIMS)
        assert _step(free, states, dists, ["A", "B"])["A"] == (4, 4, 3)

    @pytest.mark.parametrize("order", [["A", "B"], ["B", "A"]])
    def test_with_the_table_the_turn_waits_whoever_decides_first(self, order):
        free, states, dists = _scene()
        _ban_on()
        new = _step(free, states, dists, order)
        assert new["A"][2] == 0                     # 서쪽도 동쪽도 안 돈다 — 둘 다 표에 걸린다
        assert new["B"] == (5, 4, 1)


class TestStuckRelease:
    """오래 정체한 로봇은 표에서 푼다 — 코를 맞댄 1차선에서는 둘 다 못 돌아 후진·전진을 영원히 되풀이한다
    (base 2 40 42 1 · exact,ban 실측 STALL). 구간 정원(-193 sec_free)과 같은 안전판이다."""

    def test_a_released_robot_may_take_the_tight_turn(self):
        free, states, dists = _scene()
        _ban_on()
        assert _step(free, states, dists, ["A", "B"], ban_free={"A"})["A"] == (4, 4, 3)

    def test_the_released_turn_still_keeps_others_out(self):
        """풀린 로봇이 돌아도 그 회전의 금지 자리는 예약한다 — 제3자가 이번 틱 들어오지 못한다.
        B (4,3) 북향 = A 기준 ((0,−1), h0) 금지 → A 는 풀려서 돈다. C (5,5) 서향이 전진하면 (5,4) 서향 =
        ((1,0), h3) 금지 자리다."""
        free = np.ones((9, 9), dtype=bool)
        states = {"A": (4, 4, 0), "B": (4, 3, 0), "C": (5, 5, 3)}
        dists = {"A": dist_map_h(free, (4, 2)), "B": dist_map_h(free, (4, 3)), "C": dist_map_h(free, (5, 0))}
        _ban_on()
        assert (4, 3, 0) in geo.ban_states(4, 4, 0, 3) and (5, 4, 3) in geo.ban_states(4, 4, 0, 3)
        new = _step(free, states, dists, ["A", "B", "C"], ban_free={"A"})
        assert new["A"] == (4, 4, 3)
        assert new["C"] != (5, 4, 3)

    def test_without_release_the_same_turn_waits(self):
        free = np.ones((9, 9), dtype=bool)
        states = {"A": (4, 4, 0), "B": (4, 3, 0), "C": (5, 5, 3)}
        dists = {"A": dist_map_h(free, (4, 2)), "B": dist_map_h(free, (4, 3)), "C": dist_map_h(free, (5, 0))}
        _ban_on()
        assert _step(free, states, dists, ["A", "B", "C"])["A"][2] == 0


def _mid_turn_scene():
    """A 는 (4,4) 에서 북→서 회전 중(DES 는 첫 틱에 상태를 바꾼다). B 는 (5,5) 서향, 목표 (5,0) — 한 칸 전진하면
    (5,4) 서향 = A 기준 ((1,0), h3), 표에 걸린다. B 의 새 몸 (5,4)·(5,5) 는 A 의 hard 칸 밖."""
    free = np.ones((9, 9), dtype=bool)
    s0, s1 = (4, 4, 0), (4, 4, 3)
    states = {"A": s1, "B": (5, 5, 3)}
    dists = {"A": stay_map_h(free, s1), "B": dist_map_h(free, (5, 0))}
    extra = {"A": swing_cells(4, 4, 0, 3)}
    return free, states, dists, extra, {"A": (s0, s1)}


class TestNeighborVeto:
    def test_exact_lets_a_robot_roll_into_the_sweep(self):
        free, states, dists, extra, turning = _mid_turn_scene()
        geo.configure(turn_mask=None, robot_dims=DIMS)
        assert _step(free, states, dists, ["A", "B"], extra=extra, turning=turning)["B"] == (5, 4, 3)

    def test_with_the_table_no_one_enters_a_banned_pose_while_a_robot_turns(self):
        free, states, dists, extra, turning = _mid_turn_scene()
        _ban_on()
        new = _step(free, states, dists, ["A", "B"], extra=extra, turning=turning)
        assert new["B"] != (5, 4, 3)
        assert new["A"] == (4, 4, 3)

    def test_turning_is_ignored_when_the_table_is_off(self):
        free, states, dists, extra, turning = _mid_turn_scene()
        geo.reset()
        assert _step(free, states, dists, ["A", "B"], extra=extra, turning=turning)["B"] == (5, 4, 3)


class TestFootprintString:
    @pytest.mark.parametrize("fp, flags", [
        ("legacy", dict(legacy=True, front_swing=False, front_diag=False, ban=False)),
        ("exact", dict(legacy=False, front_swing=False, front_diag=False, ban=False)),
        ("exact,front", dict(legacy=False, front_swing=True, front_diag=True, ban=False)),
        ("exact,front_2cell", dict(legacy=False, front_swing=True, front_diag=False, ban=False)),
        ("exact,ban", dict(legacy=False, front_swing=False, front_diag=False, ban=True)),
        ("exact,front_2cell,ban", dict(legacy=False, front_swing=True, front_diag=False, ban=True)),
    ])
    def test_tokens(self, fp, flags):
        assert geo.footprint_flags(fp) == flags

    def test_unknown_token_is_refused(self):
        with pytest.raises(ValueError):
            geo.footprint_flags("exact,soft")

    @pytest.mark.parametrize("fp", ["legacy,ban", "ban", "exact,front,front_2cell", "front_2cell,exact"])
    def test_untested_combinations_are_refused_on_every_path(self, fp):
        """fms_core(--planner-opt footprint=…)는 CLI 검증을 안 거친다 — 판정 함수가 직접 막아야 한다."""
        with pytest.raises(ValueError):
            geo.footprint_flags(fp)

    @pytest.mark.parametrize("fp", ["exact,ban", "exact,front_2cell,ban", "exact,front,ban"])
    def test_cli_accepts_the_ban_footprints(self, fp):
        from sim_v2_tasks import parse_args
        assert parse_args(["base", "6", "40", "42", "1", f"--footprint={fp}"]).footprint == fp

    def test_cli_still_refuses_a_made_up_footprint(self):
        from sim_v2_tasks import parse_args
        with pytest.raises(AssertionError):
            parse_args(["base", "6", "40", "42", "1", "--footprint=ban"])
