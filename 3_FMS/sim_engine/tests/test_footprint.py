# -*- coding: utf-8 -*-
"""회전 발자국 (S15P21A106-203): 앞 스윙 5칸 + 0.1 m 정적 마스크. 합성 맵, configure/reset 으로 상태 격리."""
import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from map_loader import K, OX, front_swing, turn_mask_from_grid  # noqa: E402
from pibt.geometry import DEFAULT_FOOTPRINT  # noqa: E402
import pibt.geometry as geo  # noqa: E402
from pibt.geometry import DIRS, front_cells, swing_cells, turn_ok  # noqa: E402
from pibt.hgraph import HGraph, _dist_map_h_ref  # noqa: E402

DIMS = (0.39, 1.11, 0.80)
N = 5                                   # 합성 맵 5×5 칸, 로봇은 중앙 (2,2)
R = C = 2
TURNS = [(h, h2) for h in range(4) for h2 in ((h + 1) % 4, (h - 1) % 4)]


@pytest.fixture(autouse=True)
def _legacy_after():
    yield
    geo.reset()


def _grid(rack_rows=(), rack_cols=range(2 * K, 3 * K)):
    """0.1 m 원본(패딩 전). 패딩 좌표 (row, col) 로 랙(값 2)을 놓는다 — col 은 OX 만큼 빼서 원본에."""
    g = np.zeros((N * K, N * K - OX), dtype=np.uint8)
    for row in rack_rows:
        for col in rack_cols:
            g[row, col - OX] = 2
    return g


def _free(grid):
    m2 = np.pad(np.isin(grid, (1, 2, 5, 6)).astype(np.uint8), ((0, 0), (OX, 0)), constant_values=1)
    return m2.reshape(N, K, N, K).max(axis=(1, 3)) == 0


def test_front_swing_general_formula():
    assert front_swing((0.39, 1.11, 0.80))          # 0.559 > 0.5
    assert front_swing((0.40, 1.03, 0.66))          # 0.518 > 0.5
    assert not front_swing((0.30, 1.0, 0.60))       # 0.424


def test_swing_cells_hard_3_and_front_cells_soft_2():
    assert swing_cells(R, C, 0, 1) == {(1, 2), (2, 1), (1, 1)}       # 옛 뒤·새 뒤·대각 (hard)
    assert front_cells(R, C, 0, 1) == set()                          # legacy: soft 없음
    geo.configure(front_swing=True)
    assert swing_cells(R, C, 0, 1) == {(1, 2), (2, 1), (1, 1)}       # hard 는 그대로
    assert front_cells(R, C, 0, 1) == {(3, 2), (2, 3)}               # 앞(옛 헤딩)·앞(새 헤딩)
    for h, h2 in TURNS:
        cells = front_cells(R, C, h, h2)
        assert len(cells) == 2
        assert (R + DIRS[h][0], C + DIRS[h][1]) in cells
        assert (R + DIRS[h2][0], C + DIRS[h2][1]) in cells


def test_mask_open_space_allows_all_8_turns():
    m = turn_mask_from_grid(_grid(), DIMS)
    assert m.shape == (N, N, 4, 4)
    for h, h2 in TURNS:
        assert m[R, C, h, h2]
    assert not m[R, C, 0, 2]                                        # 180° 는 미정의 = False
    assert not m[R, C, 0, 0]                                        # 제자리도 미정의 = False


NOSE_TURNS = {(0, 1), (0, 3), (1, 0), (3, 0)}     # 옛 또는 새 헤딩이 h=0(랙 쪽) 인 회전 = 코가 랙 쪽으로 스윙


def test_mask_rack_at_front_cell_edge_blocks_nose_turns():
    # 앞 칸(h=0 → 행 3) 경계 첫 0.1 m 줄에 랙: 코 반경 hypot(0.44, 0.45) = 0.63 > 0.5 → 침범.
    # h=2 가 낀 회전 4개는 뒤 차체(1.16 m)가 같은 줄을 쓸어 마스크만으로도 False (valid_state 도 막는다).
    grid = _grid(rack_rows=[3 * K])
    m = turn_mask_from_grid(grid, DIMS)
    assert all(not m[R, C, h, h2] for h, h2 in TURNS)
    free = _free(grid)
    assert {(h, h2) for h, h2 in TURNS if turn_ok(free, R, C, h, h2)} == NOSE_TURNS   # legacy: 앞 칸 안 봄
    geo.configure(turn_mask=m, front_swing=True)
    assert not any(turn_ok(free, R, C, h, h2) for h, h2 in TURNS)                    # exact: 코 침범 → 전부 금지


def test_mask_rack_set_back_is_allowed():
    # 랙을 경계에서 0.2 m 뒤로(행 3 의 세 번째 줄): 코 최대 0.63 < 0.7 → 허용. 1 m 격자에서는 그 칸이 막힌 칸이라
    # "앞 칸 free 요구" 규칙이면 전부 금지됐을 것 — 마스크가 더 정밀하다. 뒤 차체가 닿는 h=2 회전만 False.
    grid = _grid(rack_rows=[3 * K + 2])
    m = turn_mask_from_grid(grid, DIMS)
    assert {(h, h2) for h, h2 in TURNS if m[R, C, h, h2]} == NOSE_TURNS
    assert not _free(grid)[3, 2]
    free = _free(grid)
    legacy = {(h, h2) for h, h2 in TURNS if turn_ok(free, R, C, h, h2)}
    geo.configure(turn_mask=m, front_swing=True)
    assert {(h, h2) for h, h2 in TURNS if turn_ok(free, R, C, h, h2)} == legacy == NOSE_TURNS


def test_sweep_radius_matches_geometry():
    from map_loader import _sweep_offsets
    off = _sweep_offsets(DIMS, 0.05, 0, 1)
    far = np.hypot(off[:, 0] + 0.5 - K / 2, off[:, 1] + 0.5 - K / 2) * 0.1     # 칸 중심 거리(m)
    assert far.max() <= math.hypot(1.16, 0.45) + 0.1 * math.sqrt(2)
    assert off[:, 0].max() == K // 2 + 6                              # 코 0.63 m → 앞 칸 두 번째 줄까지(인덱스 5+6)


def test_turn_ok_legacy_ignores_mask_and_exact_uses_it():
    grid = _grid(rack_rows=[3 * K])
    free = _free(grid)
    assert turn_ok(free, R, C, 0, 1)                                 # legacy: 앞 칸은 안 본다
    geo.configure(turn_mask=turn_mask_from_grid(grid, DIMS), front_swing=True)
    assert not turn_ok(free, R, C, 0, 1)
    geo.reset()
    assert turn_ok(free, R, C, 0, 1)


def test_hgraph_static_edges_follow_mask_and_match_reference():
    grid = _grid(rack_rows=[3 * K])
    free = _free(grid)
    geo.configure(turn_mask=turn_mask_from_grid(grid, DIMS), front_swing=True)
    goal = (1, 3)
    fast = HGraph(free).dist(goal)
    ref = _dist_map_h_ref(free, goal)
    assert np.array_equal(fast, ref)
    geo.reset()
    legacy = HGraph(free).dist(goal)
    assert np.array_equal(legacy, _dist_map_h_ref(free, goal))
    assert (fast[free] >= 0).sum() <= (legacy[free] >= 0).sum()        # 마스크는 간선을 빼기만 한다
    assert not np.array_equal(fast, legacy)


def test_configure_does_not_touch_stay_cache():
    free = _free(_grid())
    before = geo.stay_map_h(free, (R, C, 0))
    geo.configure(front_swing=True)
    assert geo.stay_map_h(free, (R, C, 0)) is before


# ---- CLI (-203 커밋 ②): --footprint / --robot-dims ----
from sim_v2_tasks import parse_args  # noqa: E402

BASE = ["base", "6", "40", "42", "1"]


def test_cli_defaults_exact_and_dims():
    """기본 발자국은 **단일 출처**(geometry.DEFAULT_FOOTPRINT)에서 온다(-251). 문자열을 여기
    다시 적으면 기본값이 두 벌이 된다 — 값이 바뀌면 이 줄의 리터럴도 같이 바꾼다."""
    a = parse_args(BASE)
    assert a.footprint == DEFAULT_FOOTPRINT == "exact"
    assert a.robot_dims == (0.39, 1.11, 0.80)
    assert a.yield_rule


def test_cli_legacy_and_custom_dims():
    a = parse_args(BASE + ["--footprint=legacy", "--robot-dims=0.40,1.03,0.66"])
    assert a.footprint == "legacy"
    assert a.robot_dims == (0.40, 1.03, 0.66)


def test_cli_cell_model_is_always_legacy():
    assert parse_args(BASE + ["--cell"]).footprint == "legacy"
    assert parse_args(BASE + ["--flow=v1compat"]).footprint == "legacy"


def test_cli_front_forces_yield_rule():
    a = parse_args(BASE + ["--footprint=exact,front", "--no-yield"])
    assert a.yield_rule
    assert any("exact,front" in w for w in a.warnings)


def test_cli_rejects_bad_footprint():
    with pytest.raises(AssertionError):
        parse_args(BASE + ["--footprint=soft"])


# ---- 밀기 실패 되돌림 (v3.5, exact 모드) ----
from pibt.hgraph import dist_map_h  # noqa: E402
from pibt.heading import step_h  # noqa: E402


def _push_scene():
    """A(4,1) 가 +row 를 보고 앞은 격자 밖, 양옆 (4,0)·(4,2) 는 벽이라 회전 불가 → 후진만 가능(존 구석에서 코가 랙을 향한 상황).
    후진하면 A 의 뒤 칸이 K(2,1) 의 pos. K 는 -col 을 보고 앞 칸 (2,0) 이 목표. K 의 모든 후보가 자기 pos (2,1) 을 포함해
    A 의 예약과 겹친다 → 밀기 실패 → K 강제 제자리."""
    free = np.ones((5, 3), dtype=bool)
    free[4, 0] = free[4, 2] = False
    states = {"A": (4, 1, 0), "K": (2, 1, 3)}
    dists = {"A": dist_map_h(free, (0, 1)), "K": dist_map_h(free, (2, 0))}
    return free, states, dists


def test_failed_push_release_lets_the_pushed_robot_move_in_exact_mode():
    free, states, dists = _push_scene()
    geo.configure(turn_mask=np.ones(free.shape + (4, 4), dtype=bool))   # exact 모드(마스크 있음) — 회전은 벽이 막는다
    ones = np.ones(free.shape + (4,)), np.ones(free.shape)
    new, _, _ = step_h(states, dists, ones[0], ones[1], free, ["A", "K"])
    assert new["A"] == (4, 1, 0)                          # A 는 이 틱엔 못 물러난다 (K 의 옛 pos 가 K 의 뒤 칸)
    assert new["K"] == (2, 0, 3)                          # K 는 앞이 비어 있으니 간다 → 다음 틱에 A 가 물러날 수 있다


def test_failed_push_keeps_forced_stay_in_legacy_mode():
    free, states, dists = _push_scene()
    geo.reset()
    ones = np.ones(free.shape + (4,)), np.ones(free.shape)
    new, _, _ = step_h(states, dists, ones[0], ones[1], free, ["A", "K"])
    assert new["A"] == (4, 1, 0)
    assert new["K"] == (2, 1, 3)                          # legacy: 밀기 실패의 강제 제자리가 남는다 (v3.3 비트 동일 유지)


def test_front_cells_4_with_mixed_diagonals():
    """-79: front_diag 면 앞 2(f0,f1) + 섞임 대각 2(mA,mB) = 4칸(soft). 코 대각·뒤 대각은 제외, hard 와 겹치지 않는다."""
    geo.configure(front_swing=True, front_diag=True)
    cells = front_cells(R, C, 0, 1)                                   # d1=(1,0), d2=(0,1)
    assert cells == {(3, 2), (2, 3), (3, 1), (1, 3)}                  # f0, f1, mA=(r+1, c-1), mB=(r-1, c+1)
    assert not (cells & swing_cells(R, C, 0, 1))                       # 몸 칸(hard)과 겹치지 않음
    for h, h2 in TURNS:
        assert len(front_cells(R, C, h, h2)) == 4
        assert not (front_cells(R, C, h, h2) & swing_cells(R, C, h, h2))
    geo.configure(front_swing=False, front_diag=True)
    assert front_cells(R, C, 0, 1) == set()
    assert not geo.front_diag_on()


def test_pitch_gating_in_configure():
    """규칙 함수 쪽 pitch 게이팅: 코 반경 × 2 ≤ pitch 면 규칙 불필요(∅)."""
    assert geo.front_needed(DIMS, 1.0)
    assert not geo.front_needed(DIMS, 1.2)
    geo.configure(front_swing=True, front_diag=True, robot_dims=DIMS, pitch=1.2)
    assert front_cells(R, C, 0, 1) == set()
    geo.configure(front_swing=True, front_diag=True, robot_dims=DIMS, pitch=1.0)
    assert len(front_cells(R, C, 0, 1)) == 4
