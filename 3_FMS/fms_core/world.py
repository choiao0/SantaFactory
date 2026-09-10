"""격자 ↔ 월드 좌표 · 헤딩 ↔ yaw — sim_engine/map_loader 규약과 VDA 5050 nodePosition 사이의 변환. 순수.

규약(map_loader.py:14 · map/README.md): 칸 c ↔ x ∈ [c−0.4, c+0.6), 행 r ↔ y ∈ [r, r+1). 칸 중심 = 로봇 구동축 중점.
헤딩 h 는 pibt.geometry.DIRS 인덱스(0=N=+y=+행, 1=E=+x=+열, 2=S, 3=W). Isaac odom 은 월드 절대 좌표(m)라 프레임 변환은 없다.
상수는 sim_engine 을 import 하지 않고 여기 복제한다 — 테스트(test_world)가 map_loader 값과 대조한다.
"""
from __future__ import annotations

import math
from typing import Iterable

CELL_M, OFFSET_M = 1.0, 0.4
DIRS = ((1, 0), (0, 1), (-1, 0), (0, -1))       # 0=N 1=E 2=S 3=W — pibt.geometry.DIRS 와 동일
WAIT, FORWARD, REVERSE, TURN, JUMP = "wait", "forward", "reverse", "turn", "jump"


def cell_center(cell: tuple) -> tuple:
    """(r, c) → (x, y) 칸 중심 [m]."""
    r, c = cell
    return (c * CELL_M + CELL_M / 2 - OFFSET_M, r * CELL_M + CELL_M / 2)


def world_to_cell(x: float, y: float) -> tuple:
    """(x, y) [m] → (r, c). map_loader._station_cells 와 같은 내림 규칙."""
    return (int(math.floor(y / CELL_M)), int(math.floor((x + OFFSET_M) / CELL_M)))


def heading_yaw(h: int) -> float:
    """h → yaw [rad]: 0→π/2, 1→0, 2→−π/2, 3→π (cli/export_isaac 의 atan2(dr, dc) 와 동일)."""
    dr, dc = DIRS[h]
    return math.atan2(dr, dc)


def yaw_heading(yaw: float) -> int:
    """yaw → 가장 가까운 90° 헤딩 h."""
    q = int(round(yaw / (math.pi / 2))) % 4        # 0=E 1=N 2=W 3=S
    return (1, 0, 3, 2)[q]


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def move_kind(before: tuple, after: tuple) -> str:
    """(r, c, h) 전후 → 커널 헤딩 모델의 한 틱 액션: wait · forward · reverse · turn. 그 밖(칸 모델 등)은 jump."""
    (r0, c0, h0), (r1, c1, h1) = before, after
    if (r0, c0) == (r1, c1):
        return WAIT if h0 == h1 else TURN
    if h0 != h1:
        return JUMP
    dr, dc = DIRS[h0]
    if (r1, c1) == (r0 + dr, c0 + dc):
        return FORWARD
    if (r1, c1) == (r0 - dr, c0 - dc):
        return REVERSE
    return JUMP


def spawn_string(cells: Iterable[tuple]) -> str:
    """홈 칸 목록 → Isaac WSIM_SPAWN 문자열 'x,y;x,y' (칸 중심, sim-runner 가 그대로 넘긴다)."""
    return ";".join(f"{x:g},{y:g}" for x, y in (cell_center(c) for c in cells))
