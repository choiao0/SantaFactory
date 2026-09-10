"""fms_core.world — 격자↔월드 변환이 map_loader/export_isaac 규약과 같은가, 헤딩↔yaw, 액션 분류."""
import math

import pytest

from fms_core import world as W
from fms_core.kernel_planner import ensure_sim_engine


def test_constants_match_map_loader():
    ensure_sim_engine()
    import map_loader
    from pibt.geometry import DIRS
    assert (W.CELL_M, W.OFFSET_M) == (map_loader.CELL_M, map_loader.OFFSET_M)
    assert tuple(DIRS) == W.DIRS


@pytest.mark.parametrize("cell", [(0, 0), (40, 36), (48, 103), (106, 115)])
def test_cell_center_round_trips(cell):
    x, y = W.cell_center(cell)
    assert W.world_to_cell(x, y) == cell


def test_cell_center_values():
    assert W.cell_center((40, 36)) == pytest.approx((36.1, 40.5))
    assert W.world_to_cell(36.0, 40.8) == (40, 36)            # Isaac 기본 spawn (36, 40.8) 은 칸 (40, 36)


@pytest.mark.parametrize("h,yaw", [(0, math.pi / 2), (1, 0.0), (2, -math.pi / 2), (3, math.pi)])
def test_heading_yaw(h, yaw):
    assert W.heading_yaw(h) == pytest.approx(yaw)
    assert W.yaw_heading(yaw) == h
    assert W.yaw_heading(yaw + 0.3) == h                        # 30° 안 흔들림은 같은 헤딩


def test_yaw_heading_wraps():
    assert W.yaw_heading(-math.pi) == 3
    assert W.yaw_heading(2 * math.pi) == 1


@pytest.mark.parametrize("before,after,kind", [
    ((5, 5, 0), (5, 5, 0), W.WAIT), ((5, 5, 0), (5, 5, 1), W.TURN), ((5, 5, 0), (6, 5, 0), W.FORWARD),
    ((5, 5, 1), (5, 6, 1), W.FORWARD), ((5, 5, 0), (4, 5, 0), W.REVERSE), ((5, 5, 3), (5, 6, 3), W.REVERSE),
    ((5, 5, 0), (5, 6, 0), W.JUMP), ((5, 5, 0), (6, 5, 1), W.JUMP), ((5, 5, 0), (7, 5, 0), W.JUMP)])
def test_move_kind(before, after, kind):
    assert W.move_kind(before, after) == kind


def test_spawn_string_uses_cell_centres():
    assert W.spawn_string([(48, 103), (50, 103)]) == "103.1,48.5;103.1,50.5"
