#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
isaac_drive.py — pibt_core.py의 헤딩 플랜을 Isaac Sim에서 실제로 주행시키는 계층.

    pibt_core.run_h()  ──>  액션 추출  ──>  ADG  ──>  주행 루프  ──>  Isaac Sim
    (이산, 틱 동기)          (이 파일)      (이 파일)   (이 파일)      (articulation)

pibt_core.py는 손대지 않는다. 이 파일이 하는 일은 그 출력을 **연속 시간에서
안전하게** 실행하는 것이다.

실행:
    python3 isaac_drive.py --selftest        # Isaac Sim 없이 전체 루프 검증
    python3 isaac_drive.py --sweep-audit     # 예약 칸 vs 실제 스윕 비교
    (Isaac Sim 안에서)  from isaac_drive import FleetController, ...

===========================================================================
왜 이 계층이 필요한가
===========================================================================
`run_h`는 **틱 동기** 모델이다. 모든 로봇이 틱 t에서 동시에 상태를 바꾸고,
그 순간의 점유가 겹치지 않으면 충돌이 없다. Isaac Sim에서는 이게 성립하지
않는다 — 로봇마다 가속·마찰·컨트롤러 오차가 달라서 같은 틱을 끝내는 시각이
다르다. 시간표를 그대로 따르면 먼저 끝난 로봇이 아직 비워지지 않은 칸에
들어간다.

ADG는 시간표를 버리고 **순서**만 남긴다. 규칙 하나:

    선행 액션이 '완료'되어야 다음 액션을 시작할 수 있다

그리고 이 파일의 핵심 주장은 '완료'의 정의에 있다:

    ★ 완료 = 다음 로봇이 필요한 칸에서 내 차체가 완전히 빠져나온 시점
      ("목표 칸 도달"이 아니다)

pibt_core의 기하에서 이 구분이 특히 크다. 격자 기준점은 **구동축**이고
차체는 진행 방향 **반대쪽으로 1.03 m** 매달려 있다(`REAR_CELLS = 1`). 구동축이
목표 칸 중심에 도착한 순간에도 꼬리는 아직 이전 칸 안에 있다.

===========================================================================
★ 피벗은 뒷바퀴다 — 그리고 그게 pibt_core와 충돌한다
===========================================================================
`pibt_core`의 주석은 `pos`를 "앞축(구동축)"이라 쓰고 차체가 **뒤쪽** 칸을
쓴다고 본다:

    occupied(s) = {pos, pos - DIRS[h]}

실측 결과 피벗은 **뒷바퀴**다. 그러면 차체는 앞으로 뻗으므로 실제 점유는
`pos + DIRS[h]` — pibt_core가 예약하는 칸의 **반대쪽**이다. 플래너가 비어
있다고 본 칸에 차체가 들어가 있게 된다.

세 조합을 같은 맵·같은 시드로 돌린 결과:

    조합                                  점유 일치  플랜상 겹침  주행 겹침  완주
    A 차체가 뒤로,  offset=0               O          0          0     6/6
    B 차체가 앞으로, offset=0  (틀린 조합)   X        107          0     0/6
    C 차체가 앞으로, offset=2               O          0          0     6/6

B가 **주행 중 충돌 0인데 완주 0/6**인 점을 보라. 이 계층이 ADG를 실제 차체
기하로 짓기 때문에, 플랜이 틀리면 부딪히는 대신 **멈춘다.** 안전한 실패
모드이고, 물리 시뮬에서 원인 모를 충돌을 쫓는 것보다 훨씬 낫다.

**해결(C)은 pibt_core의 기하를 고치는 게 아니라 헤딩을 다시 라벨링하는 것.**
`heading_offset = 2`, 즉 `h_phys = (h + 2) % 4`로 읽으면

    pibt_core의 `pos - DIRS[h]`  ==  물리적으로 `pos + DIRS[h_phys]`

가 되어 `swing_cells`·`turn_ok`의 대각 칸까지 부호가 같이 뒤집혀 정확히
맞는다. 이 파일의 기본값이다.

### 주의: 점유 칸만 봐서는 A와 C를 구별할 수 없다

A와 C는 **완전히 같은 칸 집합**을 낸다 (대칭이므로). 다른 것은 그 상태에서
로봇이 물리적으로 **어느 쪽을 보고 있는지**다. 그래서 `audit()`의 점유 일치
검사는 "틀린 조합(B)"을 잡아 줄 뿐이고, A냐 C냐는 **실물을 봐야** 정해진다.
구별하는 가장 싼 방법:

    Isaac에서 로봇 하나를 (r, c, h=1) 상태로 놓고 전진 명령을 준다.
    c가 증가하면 A, 감소하면 C.

바꿔 말하면 이 정정이 실제로 바꾼 것은 두 가지뿐이다 — 안전이 아니라
**바라보는 방향**과 **비용 라벨**이다. 셀 예약·ADG·충돌 안전성은 그대로다.

### 남는 대가는 안전이 아니라 효율이다  (§PIBT_NOTE)

라벨링을 하면 pibt_core의 '전진'이 물리적으로는 후진이 된다. 그래서
`REVERSE_FACTOR = 3.0`이 **물리적 전진**에 붙고 물리적 후진이 공짜가 된다:

    원본 pibt_core   : 주행 거리의 94.7%가 물리적 후진
    비용 라벨 수정    : 10.6%  (남는 건 3점 회전 — 원래 후진이 필요한 경우)

둘 다 무충돌 완주 10/10이므로 **안전 문제는 아니다.** 다만 센서가 없는
방향으로 대부분을 달리게 된다. 고칠 곳은 `pibt_core`의 비용 라벨 8군데이고
(`candidates_h` 2, `HGraph.__init__` 4, `_dist_map_h_ref` 2), 기하는 손댈 게
없다. `pibt_core_cost_fix.diff` 참조.

===========================================================================
pibt_core.py에서 읽어낸 기하 (실측값)
===========================================================================
    pos(s)  = (r, c)             피벗이 있는 칸 — 칸 중심에 정렬
    rear(s) = (r, c) - DIRS[h]   pibt_core가 예약하는 두 번째 칸
    occupied(s) = {pos, rear}    로봇 1대 = 2칸

    (heading_offset = 2 에서 rear(s)는 물리적으로 차체 **앞쪽** 칸이다)

    REAR_CELLS = 1     구동축 뒤 차체 1.03 m  (Isaac 실측, 2026-09-03)
    TURN_TICKS = 1     90° 회전 0.76 s        (Isaac 실측)
                       -> omega ~= 2.07 rad/s
    REVERSE_FACTOR = 3.0

    swing(h->h2) = {rear(h), rear(h2), 그 사이 대각}

이 모델이 성립하는 pitch 구간:

    REAR_CELLS=1 이려면        rear > pitch/2      ->  pitch < 2.06 m
    swing이 3칸이려면(앞단이     hypot(front, W/2)
    자기 칸에 머묾)            < pitch/2           ->  pitch > 1.09 m

즉 **pitch ~= 1.1 ~ 2.0 m** 에서만 맞는 모델이다. 이 범위 밖이면 `swing_cells`
가 실제 스윕을 과소보고한다. `RobotGeom.audit()`가 확인해 준다.

좌표 규칙은 pibt_core를 그대로 따른다: `(r, c) = (y, x)`, r 증가 = 북,
c 증가 = 동, `DIRS[h]` 0=N 1=E 2=S 3=W.

===========================================================================
★ 측정된 것: 전진 예약이 꼬리 칸을 빠뜨린다
===========================================================================
`candidates_h`의 전진 후보는 `{새 pos, 이전 pos}`를 예약한다. 그런데 구동축이
새 pos로 가는 도중 차체 뒤쪽은 아직 **그 이전 칸**(= `rear(s0)`)에 있다.

    move (16,22,W) -> (16,21,W)
        예약    {(16,21), (16,22)}
        실제    {(16,21), (16,22), (16,23)}      <- (16,23) 누락

틱 동기 모델에서는 문제가 아니다. 틱 t와 t+1의 점유만 겹치지 않으면 되고,
그 사이 시각은 모델에 없다. 연속 실행에는 그 시각이 있다.

12대 / 창고 / slip·lag 주입, 같은 플랜·같은 주행에서 ADG의 근거만 바꿨을 때:

    ADG를 지은 근거                   주행    차체 겹침 이벤트
    실제 스윕 (swept_cells)            6            0
    pibt_core 예약 (cells_hist)        6       10,148

그래서 이 파일은 ADG를 `cells_hist`가 아니라 `RobotGeom.swept_cells()`로
짓는다. 전이 504건 중 291건에서 예약이 실제보다 작았다.
`--sweep-audit`로 직접 셀 수 있다.

**pibt_core는 고칠 필요가 없다.** 이산 시뮬레이터로서는 옳다. 부족한 것은
연속 실행용 예약이고, 그건 이 계층의 일이다.

===========================================================================
붙이는 순서 — 이 파일은 1단계다
===========================================================================
    1단계  KinematicDriver     물리 없음, 적분만. ADG 계약 검증.   <- --selftest
    2단계  DifferentialDriver  Isaac articulation, 바퀴 속도 명령
    3단계  라이더 + 재계획      report_obstacle() 훅이 준비되어 있음

1단계를 건너뛰면 충돌이 났을 때 플랜·궤적·완료판정·물리·튜닝 중 무엇이
틀렸는지 알 수 없다.
"""

from __future__ import annotations

import argparse
import math
import os
import random
from dataclasses import dataclass, field
from typing import Callable, Iterable, Protocol, Sequence

import numpy as np

from pibt_core import (
    DIRS,
    MOVE_TICKS,
    REAR_CELLS,
    REVERSE_FACTOR,
    TURN_TICKS,
    occupied,
    rear_cell,
    run_h,
    swing_cells,
)

# [patch_ticks] 계획 틱이 무엇인지 — 두 경로가 다르다. 헷갈리면 안 된다.
#
#   2026-09-14(-194)에 계획기에 `MOVE_TICKS = 4, TURN_TICKS = 5` 가 생겼다.
#   그런데 **`MOVE_TICKS` 는 `kernel/core.py`(FmsKernel 실행 경로)에만
#   적용된다.**
#
#       FmsKernel     전진 MOVE_TICKS(4) 틱 · 회전 TURN_TICKS(5) 틱
#       step_h/run_h  전진 **1틱** · 회전 TURN_TICKS(5) 틱     <- 우리가 쓰는 쪽
#
#   `run_h` 도 `lifelong` 도 `step_h` 를 직접 부르므로 우리 경로에서 전진은
#   여전히 1틱이다. 바뀐 것은 **회전이 1틱에서 5틱이 된 것**뿐이다.
#
#   그래서 같은 일에 드는 틱이 회전 빈도만큼 늘었다 — 실측 1.3~1.6배
#   (같은 시드·같은 맵에서 계획기만 바꿔 잼). FMS 주석의 "2.07배" 가 그
#   부류의 실측값이다.
#
#   ★ 한때 이 자리에 `TICKS_PER_CELL = MOVE_TICKS` 를 두고 지평·max_steps·
#     tick_s 를 전부 4배로 환산했는데 **틀렸다.** 우리 경로에 MOVE_TICKS 가
#     안 걸리므로 4배는 과하고, `tick_s` 는 원래 맞던 값을 틀리게 만들었다.
#     상수를 그대로 두고, 틱이 무엇인지만 여기 적어 둔다.

Cell = tuple[int, int]
State = tuple[int, int, int]          # (r, c, h)

# 방향 h -> world yaw.  r 증가 = 북(+y), c 증가 = 동(+x).
YAW = (math.pi / 2.0, 0.0, -math.pi / 2.0, math.pi)   # N, E, S, W

MOVE, TURN, REVERSE, WAIT = "move", "turn", "reverse", "wait"

# 겹침 심각도를 가르는 차체 간격 [m]. 이 아래면 "근접" 으로 올려 본다.
#   ★ 칸 공유(= `overlap_events`)는 접촉이 아니다. 1.2 m 칸을 공유 단위로
#     쓰면 **0.5 m 넘게 떨어진 두 대도 걸린다.** 2026-09-14 실측: 대각선
#     이웃이 칸 하나를 각각 5.1 mm · 2.7 mm 씩 스쳤는데 간격은 0.568 m 였다.
#     0.10 은 "이 정도면 눈으로 확인할 값" 이라는 뜻이고 물리 한계가 아니다.
CONTACT_NEAR = 0.10


def wrap(a: float) -> float:
    """각도를 (-pi, pi]로."""
    return (a + math.pi) % (2.0 * math.pi) - math.pi


def clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else (hi if x > hi else x)


# ===========================================================================
# SECTION 1 — 기하: 격자 <-> world, 차체 폴리곤, 스윕 칸
# ===========================================================================


@dataclass(frozen=True)
class RobotGeom:
    """pibt_core의 (r, c, h) 상태를 world pose와 차체 점유 칸으로 옮기는 어댑터.

    ``rear_len``은 구동축에서 차체 뒷면까지 (pibt_core 실측 1.03 m).
    ``front_len``은 구동축에서 차체 앞면까지. 둘의 합이 전장이다.

    ``origin``은 셀 ``(0, 0)`` **중심**의 world 좌표. ``axle_in_prim``은 USD
    prim의 원점에서 구동축까지의 오프셋(prim 로컬 프레임, x=전방). prim 원점이
    구동축과 같으면 (0, 0).  usd_probe.py 로 확인할 값이다.
    """

    pitch: float = 1.20            # 격자 간격 m — 실제 값으로 교체
    rear_len: float = 0.37         # 피벗 -> 차체 뒷면
    front_len: float = 1.03        # 피벗 -> 차체 앞면 (Isaac 실측 1.03 m)
    width: float = 0.80
    v_max: float = 0.90            # m/s (wppl.py의 SPEED_PLAN)
    w_max: float = 2.07            # rad/s ((pi/2) / 0.76 s, Isaac 실측)
    a_lin: float = 0.60            # m/s^2
    a_ang: float = 3.00            # rad/s^2
    origin: tuple[float, float] = (0.0, 0.0)
    axle_in_prim: tuple[float, float] = (0.0, 0.0)

    # [patch_axle] 앞 칸 규칙 스위치. **계획기와 반드시 같아야 한다.**
    #   계획기 쪽은 `pibt.geometry.configure(front_swing=…)` 로 켜고, 이 값은
    #   `build_adg` 진입에서 `geo.front_swing_on()` 과 대조한다. 한쪽만 켜지면
    #   계획에 위험한 배치가 남는데 ADG 가 그걸 못 잡는다 — 주차한 로봇은
    #   간선의 대상이 아니기 때문이다 (설계서 §0-1).
    #
    #   ★ 스위치가 **둘**이다. `pibt_scene` 이 `configure()` 와 이 필드에
    #     각각 넘긴다. 값이 갈릴 수 있는 지점이 이미 있으므로 검사가 필요하다.
    front_swing: bool = False

    # [patch_axle] 섞임 대각 2칸(mA, mB)까지 쓰는가 = 4칸 규칙.
    #   -79 부터 계획기 상태가 **둘**이라 `front_swing` 하나로는 구별이 안 된다.
    #
    #       front_swing=True, front_diag=False   -> 2칸 {f0, f1}
    #       front_swing=True, front_diag=True    -> 4칸 {f0, f1, mA, mB}
    #
    #   ★ 이 값은 **규칙 계산에 안 쓴다.** 칸 집합은 `front_cells()` 가 계획기
    #     함수를 그대로 부르므로 자동으로 따라간다. 여기 두는 이유는 두 가지다 —
    #     `geo.front_diag_on()` 과 대조해 반쪽 설정을 잡고, 지문·셀프테스트의
    #     기대값이 어느 상태에서 나온 것인지 기록으로 남기려는 것이다.
    front_diag: bool = False

    # ★ pibt_core의 h를 물리 헤딩으로 옮길 때 더하는 값 (0 또는 2).
    #
    # pibt_core는 `occupied(s) = {pos, pos - DIRS[h]}` — 차체가 h의 **뒤쪽**
    # 칸을 쓴다고 본다. 이건 피벗이 차체 앞단(= 구동축이 앞)일 때만 맞는다.
    #
    # 뒷바퀴 피벗이면 차체는 앞으로 뻗으므로 실제 점유는 `pos + DIRS[h]`이고,
    # pibt_core의 예약과 반대쪽이 된다. 그대로 두면 플래너가 비어 있다고 본
    # 칸에 차체가 들어가 있다.
    #
    # 해결은 pibt_core를 고치는 게 아니라 **헤딩을 다시 라벨링**하는 것이다.
    # h_phys = (h + 2) % 4 로 읽으면
    #     pibt_core의 `pos - DIRS[h]`  ==  물리적으로 `pos + DIRS[h_phys]`
    # 가 되어 기하가 정확히 일치한다. swing_cells·turn_ok의 대각 칸까지 함께
    # 맞는다 (부호가 같이 뒤집히므로).
    #
    # 남는 대가는 하나뿐이고, 안전이 아니라 효율이다: pibt_core의 '전진'이
    # 물리적으로는 후진이 된다. 그래서 `REVERSE_FACTOR = 3.0`이 물리적 전진에
    # 붙고 물리적 후진이 공짜가 된다 — 로봇이 뒤로 다니는 걸 선호한다.
    # 고치는 곳은 pibt_core의 비용 라벨이지 기하가 아니다 (아래 §PIBT_NOTE).
    heading_offset: int = 2

    def __post_init__(self) -> None:
        object.__setattr__(self, "_stencils", {})
        if self.heading_offset not in (0, 2):
            raise ValueError("heading_offset은 0 또는 2")

    @property
    def pivot_name(self) -> str:
        return "뒷바퀴(구동축이 뒤, 차체가 앞으로)" if self.heading_offset == 2 \
            else "앞축(구동축이 앞, 차체가 뒤로)"

    def phys_heading(self, h: int) -> int:
        """pibt_core의 h -> 물리 헤딩 인덱스."""
        return (h + self.heading_offset) % 4

    # 피벗에서 먼 쪽 / 가까운 쪽. 축이 앞이든 뒤든 모델의 조건은 이 둘로
    # 쓰인다 — 긴 쪽이 이웃 칸을 먹고, 짧은 쪽은 자기 칸에 머물러야 한다.
    @property
    def long_len(self) -> float:
        return max(self.front_len, self.rear_len)

    @property
    def short_len(self) -> float:
        return min(self.front_len, self.rear_len)

    @property
    def pitch_window(self) -> tuple[float, float]:
        """pibt_core의 2칸 점유 + 스윙 3칸 모델이 성립하는 pitch 구간.

        하한 : 짧은 쪽이 자기 칸에 머묾   hypot(short, W/2) < pitch/2
        상한 : 긴 쪽이 이웃 칸에 닿음     long > pitch/2
        """
        return (2.0 * math.hypot(self.short_len, 0.5 * self.width),
                2.0 * self.long_len)

    def heading_vec(self, h: int) -> tuple[float, float]:
        """물리 헤딩의 world 단위벡터 (dx, dy)."""
        yaw = YAW[self.phys_heading(h)]
        return (math.cos(yaw), math.sin(yaw))

    # ---- 격자 <-> world ---------------------------------------------------

    def cell_center(self, cell: Cell) -> tuple[float, float]:
        r, c = cell
        return (self.origin[0] + c * self.pitch, self.origin[1] + r * self.pitch)

    def world_to_cell(self, x: float, y: float) -> Cell:
        return (int(round((y - self.origin[1]) / self.pitch)),
                int(round((x - self.origin[0]) / self.pitch)))

    def state_pose(self, s: State) -> tuple[float, float, float]:
        """상태 -> 피벗의 world pose (x, y, yaw). yaw는 물리 헤딩이다."""
        x, y = self.cell_center((s[0], s[1]))
        return (x, y, YAW[self.phys_heading(s[2])])

    def prim_pose_from_axle(self, x: float, y: float, yaw: float) -> tuple[float, float]:
        """구동축 pose -> prim 원점 world 위치 (Isaac에 쓸 때)."""
        ax, ay = self.axle_in_prim
        return (x - (math.cos(yaw) * ax - math.sin(yaw) * ay),
                y - (math.sin(yaw) * ax + math.cos(yaw) * ay))

    def axle_from_prim_pose(self, x: float, y: float, yaw: float) -> tuple[float, float]:
        """prim 원점 world 위치 -> 구동축 위치 (Isaac에서 읽을 때)."""
        ax, ay = self.axle_in_prim
        return (x + math.cos(yaw) * ax - math.sin(yaw) * ay,
                y + math.sin(yaw) * ax + math.cos(yaw) * ay)

    # ---- 차체 폴리곤 -------------------------------------------------------

    def corners(self, x: float, y: float, yaw: float) -> list[tuple[float, float]]:
        """구동축이 (x, y), 방향 yaw일 때 차체 사각형의 네 꼭짓점."""
        fx, fy = math.cos(yaw), math.sin(yaw)
        lx, ly = -fy, fx                                  # 좌측 단위벡터
        hw = 0.5 * self.width
        f, b = self.front_len, self.rear_len
        return [
            (x + fx * f + lx * hw, y + fy * f + ly * hw),
            (x + fx * f - lx * hw, y + fy * f - ly * hw),
            (x - fx * b - lx * hw, y - fy * b - ly * hw),
            (x - fx * b + lx * hw, y - fy * b + ly * hw),
        ]

    def _cell_square(self, cell: Cell) -> tuple[float, float, float, float]:
        cx, cy = self.cell_center(cell)
        h = 0.5 * self.pitch
        return (cx - h, cy - h, cx + h, cy + h)

    def footprint_corners(self, x: float, y: float,
                          yaw: float) -> tuple[tuple[float, float], ...]:
        """차체 직사각형의 꼭짓점 4개 (전방 좌 · 전방 우 · 후방 우 · 후방 좌).

        `footprint_cells` 와 `body_gap` 이 **같은 수식**을 쓰게 하려고 뺐다.
        두 벌로 두면 치수를 바꿀 때 한쪽만 고쳐 조용히 갈린다.
        """
        cs, sn = math.cos(yaw), math.sin(yaw)
        f, b, hw = self.front_len, self.rear_len, 0.5 * self.width
        return ((x + cs * f - sn * hw, y + sn * f + cs * hw),
                (x + cs * f + sn * hw, y + sn * f - cs * hw),
                (x - cs * b + sn * hw, y - sn * b - cs * hw),
                (x - cs * b - sn * hw, y - sn * b + cs * hw))

    @staticmethod
    def _seg_gap(a, b, c, d) -> float:
        """선분 ab 와 cd 의 최소 거리."""
        def pt_seg(p, q, r):                    # 점 p 와 선분 qr
            vx, vy = r[0] - q[0], r[1] - q[1]
            L2 = vx * vx + vy * vy
            t = 0.0 if L2 <= 1e-18 else ((p[0] - q[0]) * vx + (p[1] - q[1]) * vy) / L2
            t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
            return math.hypot(p[0] - (q[0] + t * vx), p[1] - (q[1] + t * vy))
        return min(pt_seg(a, c, d), pt_seg(b, c, d),
                   pt_seg(c, a, b), pt_seg(d, a, b))

    def body_gap(self, pa, pb) -> float:
        """두 차체 사이 최소 거리 [m]. 겹치면 0.0.

        ★ **겹침이 터졌을 때만** 부른다. 주행 루프에서 부르면 안 된다.

        [왜 필요한가] `_check` 의 칸 공유(경보)와 **실제 접촉은 다르다.**
        pitch 1.2 · 폭 0.8 에서 옆 칸 회전이면, 이상적 자세 기준으로

            경보가 울리는 오차   41.3 mm   (앞 모서리 R=0.5587 vs 반칸 0.600)
            실제로 닿는 오차    241.3 mm   (차체끼리의 간격)

        즉 **5.8배** 차이다. 로그에 칸 개수만 남기면 "감시선이 보수적으로 운
        것" 과 "진짜 접촉" 을 구별할 수 없다 (2026-09-13 실측 쌍 7-8).
        """
        A = self.footprint_corners(*pa)
        B = self.footprint_corners(*pb)

        def sep(P, Q):                          # P 의 변 법선으로 분리되나 (SAT)
            for i in range(4):
                ex = P[(i + 1) % 4][0] - P[i][0]
                ey = P[(i + 1) % 4][1] - P[i][1]
                ux, uy = -ey, ex
                pv = [p[0] * ux + p[1] * uy for p in P]
                qv = [q[0] * ux + q[1] * uy for q in Q]
                if max(pv) < min(qv) - 1e-12 or max(qv) < min(pv) - 1e-12:
                    return True
            return False
        if not (sep(A, B) or sep(B, A)):
            return 0.0                          # 겹친다
        return min(self._seg_gap(A[i], A[(i + 1) % 4], B[j], B[(j + 1) % 4])
                   for i in range(4) for j in range(4))

    def footprint_cells(self, x: float, y: float, yaw: float) -> frozenset[Cell]:
        """차체가 실제로 덮는 칸 집합. 점 샘플링이 아니라 분리축 정리(SAT).

        주행 루프에서 로봇당 매 스텝 불리므로 직사각형 전용으로 펼쳐 두었다.
        직사각형은 고유 분리축이 2개뿐(전방·좌측)이라 world 축까지 4개면 된다.
        """
        cs, sn = math.cos(yaw), math.sin(yaw)
        p0, p1, p2, p3 = self.footprint_corners(x, y, yaw)
        poly = (p0, p1, p2, p3)

        minx = min(p0[0], p1[0], p2[0], p3[0])
        maxx = max(p0[0], p1[0], p2[0], p3[0])
        miny = min(p0[1], p1[1], p2[1], p3[1])
        maxy = max(p0[1], p1[1], p2[1], p3[1])
        ox, oy, p = self.origin[0], self.origin[1], self.pitch
        c0 = int(math.floor((minx - ox) / p + 0.5))
        c1 = int(math.floor((maxx - ox) / p + 0.5))
        r0 = int(math.floor((miny - oy) / p + 0.5))
        r1 = int(math.floor((maxy - oy) / p + 0.5))

        # 차체 고유 분리축 2개에 대한 투영은 셀마다 바뀌지 않는다
        ap = [(cs, sn), (-sn, cs)]
        rng = []
        for ux, uy in ap:
            vs = (p0[0] * ux + p0[1] * uy, p1[0] * ux + p1[1] * uy,
                  p2[0] * ux + p2[1] * uy, p3[0] * ux + p3[1] * uy)
            rng.append((min(vs), max(vs)))

        half = 0.5 * p
        out: set[Cell] = set()
        for r in range(r0, r1 + 1):
            cy = oy + r * p
            sy0, sy1 = cy - half, cy + half
            if maxy < sy0 - 1e-9 or sy1 < miny - 1e-9:
                continue
            for c in range(c0, c1 + 1):
                cx = ox + c * p
                sx0, sx1 = cx - half, cx + half
                if maxx < sx0 - 1e-9 or sx1 < minx - 1e-9:
                    continue
                hit = True
                for (ux, uy), (lo, hi) in zip(ap, rng):
                    q = (sx0 * ux + sy0 * uy, sx1 * ux + sy0 * uy,
                         sx1 * ux + sy1 * uy, sx0 * ux + sy1 * uy)
                    if hi < min(q) - 1e-9 or max(q) < lo - 1e-9:
                        hit = False
                        break
                if hit:
                    out.add((r, c))
        return frozenset(out)

    # ---- 동작 스윕 ---------------------------------------------------------

    # [patch_axle] 앞 칸 (soft) — 규칙은 FMS 가 단일 소스다 ------------------
    def front_cells(self, s0: State, s1: State) -> frozenset[Cell]:
        """회전 중 **코만 스치는** 앞 칸. 몸은 안 들어간다.

        규칙(몇 칸인지, 대각을 넣는지)은 `3_FMS/sim_engine/pibt/geometry.py`
        가 **단일 소스**다. 여기서는 그 함수를 그대로 부른다.

        ★ 여기서 규칙을 다시 구현하지 말 것. 정의가 두 벌이 되는 순간
          "계획기 4칸 / ADG 2칸" 같은 어긋남이 **검사로 안 잡힌다**
          (설계서 §0-1). 2026-09-14 에 실제로 그 버그가 났다 — 교집합을
          간선 조회에도 써서 4칸이 조용히 2칸으로 퇴화했다.

        ★ **교집합을 여기서 하지 말 것.** 돌려주는 것은 규칙이 준 칸 그대로
          (`guard`) 이고, 실제 스윕과의 교집합(`soft`)은 `extract_actions`
          가 따로 만든다. 규칙이 내놓는 칸 중 일부는 스윕 **밖**이다 —
          pitch 1.0 에서 섞임 대각 mA·mB 가 0/8 로 그렇다. 여기서 깎으면
          그 칸들이 간선에서 사라진다.

        ★ pitch 게이팅도 여기서 하지 말 것. `configure(robot_dims, pitch)`
          가 `front_needed()` 로 계획기 안에서 판정한다 (FMS 답신 4 §1).
          우리가 밖에서 한 번 더 걸면 두 층의 기준이 갈라진다.

        ★ `_sweep_stencil` 캐시를 쓰지 말 것. 키가 `(h0, h1, dr, dc, samples)`
          라서 "코만 스윕" 을 같은 캐시로 구하면 **몸통 스윕 결과**를 받는다.

        헤딩은 pibt 규약 그대로 넘긴다 — `geo.front_cells` 도 같은 `DIRS` 를
        쓰므로 `phys_heading` 변환을 끼우면 안 된다.
        """
        if not self.front_swing:
            return frozenset()
        try:
            import pibt.geometry as geo
        except ImportError as e:                       # pragma: no cover
            raise RuntimeError(
                "★ front_swing=True 인데 계획기 기하를 못 불러온다.\n"
                "  pibt_core_v2 가 sys.path 에 sim_engine 을 넣었는지 본다.") from e
        return frozenset(geo.front_cells(s0[0], s0[1], s0[2], s1[2]))

    @property
    def lateral_gap(self) -> float:
        """옆 칸에 나란히 선 두 대의 차체 간격 — `pitch - width`.

        **격자 기하가 정하는 값이라 ADG 규칙과 무관하다.** 대각 케이스를 전부
        막아도 이 배치는 남으므로, 어떤 예약 규칙으로도 이보다 넓힐 수 없다.
        네 pitch(1.0/1.1/1.2/1.4)에서 실측과 소수점까지 일치함을 확인했다.

        `CONTACT_NEAR` 를 읽을 때 같이 보라 — 지금 0.10 은 pitch 1.0 의
        `lateral_gap` 0.200 의 **절반**이다. 채택안(앞 6칸)의 설계 여유가
        200.0 mm 이므로 그대로 맞는 값이고, 41.4 mm 문제는 앞 2칸에만 있었다.
        """
        return self.pitch - self.width

    @property
    def nose_clears_cell_pitch(self) -> float:
        """이 값보다 pitch 가 작으면 회전 중 코가 자기 칸을 벗어난다.

        `2 * hypot(front_len, width/2)` — 앞 모서리 반경의 두 배다.
        치수 0.390 · 0.800 에서 1.1173 m.
        """
        return 2.0 * math.hypot(self.front_len, 0.5 * self.width)

    def swept_cells(self, s0: State, s1: State, samples: int = 48) -> frozenset[Cell]:
        """s0 -> s1 동작 **전체**에서 차체가 지나는 칸.

        ADG가 예약해야 하는 집합이 이것이다. pibt_core의 `cells_hist`(틱 동기
        예약)보다 클 수 있고, 그 차이가 정확히 연속 실행에서 새는 지점이다.
        `audit()`가 그 차이를 센다.

        격자가 균일하니 같은 전이는 어디서 하든 같은 모양이다. 그래서
        `(h0, h1, dr, dc)` 조합마다 pos0 기준 상대 오프셋으로 한 번만 굽고
        (조합이 몇 개뿐이다) 이후엔 평행이동만 한다.
        """
        (r0, c0, h0), (r1, c1, h1) = s0, s1
        st = self._sweep_stencil(h0, h1, r1 - r0, c1 - c0, samples)
        return frozenset((r0 + dr, c0 + dc) for dr, dc in st)

    def _sweep_stencil(self, h0: int, h1: int, dr: int, dc: int,
                       samples: int) -> frozenset[Cell]:
        key = (h0, h1, dr, dc, samples)
        st = self._stencils.get(key)
        if st is not None:
            return st
        x0, y0 = self.cell_center((0, 0))
        x1, y1 = self.cell_center((dr, dc))
        a0 = YAW[self.phys_heading(h0)]
        a1 = a0 + wrap(YAW[self.phys_heading(h1)] - a0)  # 짧은 쪽으로
        out: set[Cell] = set()
        for i in range(samples + 1):
            t = i / samples
            out |= self.footprint_cells(x0 + (x1 - x0) * t,
                                        y0 + (y1 - y0) * t,
                                        a0 + (a1 - a0) * t)
        st = frozenset(out)
        self._stencils[key] = st
        return st

    # ---- 자기 진단 ---------------------------------------------------------

    def audit(self) -> dict:
        """pibt_core의 이산 모델이 이 pitch에서 성립하는지 확인."""
        hw = 0.5 * self.width
        half = 0.5 * self.pitch
        lo, hi = self.pitch_window
        rest = self.footprint_cells(*self.state_pose((5, 5, 1)))
        model_rest = set(occupied((5, 5, 1)))
        turn = self.swept_cells((5, 5, 1), (5, 5, 0))
        model_turn = {(5, 5)} | set(swing_cells(5, 5, 1, 0)) | model_rest
        fwd = self.swept_cells((5, 5, 1), (5, 6, 1))
        model_fwd = {(5, 6), (5, 5)}                     # candidates_h의 전진 예약
        return {
            "pitch": self.pitch,
            "extra_cells_needed": math.ceil(max(0.0, self.long_len - half) / self.pitch),
            "extra_cells_model": REAR_CELLS,
            "short_stays_home": math.hypot(self.short_len, hw) < half,
            "pitch_lo": lo,
            "pitch_hi": hi,
            "in_window": lo < self.pitch < hi,
            "rest_matches": rest == frozenset(model_rest),
            "rest_real": sorted(rest),
            "rest_model": sorted(model_rest),
            "turn_covered": turn <= frozenset(model_turn),
            "turn_extra": sorted(turn - frozenset(model_turn)),
            "fwd_covered": fwd <= frozenset(model_fwd),
            "fwd_extra": sorted(fwd - frozenset(model_fwd)),
        }

    def describe(self) -> str:
        a = self.audit()
        return "\n".join([
            f"피벗             : {self.pivot_name}",
            f"pitch            : {self.pitch:.2f} m   "
            f"(이 모델의 유효 구간 {a['pitch_lo']:.2f} ~ {a['pitch_hi']:.2f} m"
            f"{'' if a['in_window'] else '  ★구간 밖'})",
            f"차체             : 뒤 {self.rear_len:.2f} + 앞 {self.front_len:.2f} "
            f"= {self.rear_len + self.front_len:.2f} m, 폭 {self.width:.2f} m",
            f"속도             : v_max {self.v_max:.2f} m/s, w_max {self.w_max:.2f} rad/s",
            f"옆 칸 간격       : {self.lateral_gap:.3f} m (= pitch - 폭, 규칙과 무관한 바닥)"
            f"   근접 경고선 {CONTACT_NEAR:.2f} m",
            f"정지 점유        : 실제 {a['rest_real']}  모델 {a['rest_model']}"
            f"   {'일치' if a['rest_matches'] else '★불일치'}",
            f"회전 스윙        : {'모델이 덮음' if a['turn_covered'] else '★모델 밖 ' + str(a['turn_extra'])}",
            f"전진 스윕        : {'모델이 덮음' if a['fwd_covered'] else '예약 밖 ' + str(a['fwd_extra']) + ' (알려진 꼬리 칸 누락 — 아래 ★ 참조)'}",
        ])


def _overlaps_rect(poly: Sequence[tuple[float, float]],
                   x0: float, y0: float, x1: float, y1: float) -> bool:
    """분리축 정리 — 볼록 폴리곤 vs 축정렬 사각형."""
    rect = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    axes = [(1.0, 0.0), (0.0, 1.0)]
    n = len(poly)
    for i in range(n):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % n]
        ex, ey = bx - ax, by - ay
        m = math.hypot(ex, ey)
        if m > 1e-12:
            axes.append((-ey / m, ex / m))
    for ux, uy in axes:
        pa = [px * ux + py * uy for px, py in poly]
        pb = [qx * ux + qy * uy for qx, qy in rect]
        if max(pa) < min(pb) - 1e-9 or max(pb) < min(pa) - 1e-9:
            return False
    return True


# ===========================================================================
# SECTION 2 — 액션 추출
# ===========================================================================


@dataclass
class Action:
    agent: int
    idx: int
    kind: str
    tick: int
    frm: State
    to: State
    cells: frozenset[Cell]        # 동작 내내 잡고 있는 칸 (실제 스윕)
    uid: int = -1
    # [patch_axle] 코만 스치고 몸은 안 들어가는 칸 — 회전에만, pitch 의존.
    #   `cells` 는 **건드리지 않는다.** 이 필드는 `build_adg` 의 간선 조건
    #   하나에만 쓰인다. `can_start`(장애물)·`released`(완료 판정)·`_check`
    #   (겹침 감시)는 지금도 `cells` 전체를 본다 — 그게 이 변경의 안전 논거
    #   절반이다. 설계서 `docs/2026-09-14_ADG_축규칙_구조변경_설계.md` §1-3.
    #
    #   스위치가 꺼져 있으면 항상 빈 집합이고, 그러면 `hard == cells` 라
    #   간선이 오늘과 비트 단위로 같다 (§7 항목 1, tools/adg_fingerprint.py).
    soft: frozenset[Cell] = frozenset()
    # [patch_axle] `front_cells()` 가 돌려준 **교집합 이전** 집합.
    #   `soft` 와 갈라 두는 이유: 규칙이 내놓는 칸 중 일부는 **실제 스윕
    #   바깥**이다. pitch 1.0 에서 섞임 대각 mA·mB 가 그렇다 (0/8 — 0.80
    #   에서야 7/8 로 들어온다). `soft = guard & cells` 로만 두면 4칸 규칙이
    #   ADG 안에서 조용히 **2칸으로 퇴화**한다.
    #
    #     guard   규칙 ② 조회용. 계획기가 보는 집합과 **같다.**
    #     soft    `hard = cells - soft` 계산용. 실제 스윕 안쪽만.
    #
    #   교집합을 soft 에 두는 건 맞다 — 스윕 밖 칸은 애초에 hard 가 아니라
    #   빼낼 것이 없다. 잘못된 건 그걸 **간선 조회에도** 썼던 것이다.
    guard: frozenset[Cell] = frozenset()
    # [patch_release] 이 동작이 **태스크의 첫 동작**인가 (-211).
    #
    #   ADG 실행기의 시작 관문 ② 는 `clock >= tick x tick_s` 를 요구한다.
    #   그 줄의 주석이 "아직 주문이 안 왔다" 인데, 주문 도착 제약은 태스크의
    #   **첫 동작에만** 필요하다. 그런데 모든 동작에 걸려 있었다.
    #
    #   실측 (pitch 1.0 · 12대 · 467.65 s · 2026-09-15)
    #       막힘 111,148 프레임 중 **릴리스 바닥 66.2%** · ADG선행 33.8%
    #       = 로봇 시간의 21.8% 가 "계획 시각이 안 됐다" 로 서 있었다
    #       지평(349 s)을 넘기면 막힘이 1,776 프레임으로 62배 줄고 전부 ADG선행
    #
    #   즉 이 시스템의 지배적 제약이 경합도 물리도 아니고 계획 시각표였다.
    #
    #   값이 있는 동작만 바닥을 받고 나머지는 0 이다. 순서 안전은 그대로다 —
    #   관문 ③(ADG 선행)이 손대지 않은 채 남는다. 바닥은 **시각**만 정한다.
    #   lifelong 이 아닌 경로(one-shot)는 태스크 개념이 없어 전부 None 이고,
    #   그때는 `tick_s=None` 이라 바닥 자체가 없다.
    #
    # ★ 2026-09-15 (-211) 불리언 -> **틱**. 전에는 `task_start: bool` 이었고
    #   `release_time` 이 `action.tick`(= 그 동작이 계획에서 몇 번째 틱인가)을
    #   썼다. 그건 **주문 도착 시각이 아니라 계획 시간표**다. 세 틱이 다르다:
    #
    #       주문 도착   task["born"]     ← 바닥이 써야 할 값
    #         <=  배정   assign(t)
    #         <=  첫 동작 action.tick    ← 전에 쓰던 값
    #
    #   계획이 실제보다 느리면(옛 틱 모델이 회전을 3.7배 느리게 봤다) 첫 동작
    #   틱이 뒤로 밀리고, 실행 로봇은 **이미 도착한 주문을 두고** 그 틱을
    #   기다렸다. ADG 는 「시간표가 아니라 순서」인데 바닥만 시간표였던 셈이다.
    release_tick: int | None = None

    @property
    def hard(self) -> frozenset[Cell]:
        """몸이 실제로 차지하는 칸 — 상대 **몸**이 못 들어온다."""
        return self.cells - self.soft

    @property
    def axle(self) -> frozenset[Cell]:
        """구동축이 지나는 칸. 전진은 두 칸, 제자리 회전은 한 칸."""
        return frozenset({self.frm[:2], self.to[:2]})

    @property
    def rest(self) -> frozenset[Cell]:
        """동작이 끝난 뒤 차체가 차지하는 칸."""
        return frozenset(occupied(self.to))

    @property
    def released(self) -> frozenset[Cell]:
        """완료 시 놓아주는 칸 — ★이 칸들이 비었는지가 완료 조건이다."""
        return self.cells - self.rest

    @property
    def acquired(self) -> frozenset[Cell]:
        return self.cells - frozenset(occupied(self.frm))

    def __repr__(self) -> str:
        return f"A{self.agent}#{self.idx} {self.kind}{self.frm}->{self.to}@t{self.tick}"


def classify(s0: State, s1: State) -> str:
    if s0 == s1:
        return WAIT
    if s0[:2] == s1[:2]:
        return TURN
    d = (s1[0] - s0[0], s1[1] - s0[1])
    return MOVE if d == DIRS[s0[2]] else REVERSE


def extract_actions(history: list[dict[int, State]], geom: RobotGeom,
                    task_start: dict[int, list[tuple[int, int]]] | None = None,
                    ) -> tuple[list[list[Action]], list[int], dict]:
    """run_h의 history를 로봇별 액션 체인으로.

    **대기는 액션이 아니다.** ADG 아래에서 대기는 "선행 액션을 기다리는 중"으로
    자동 표현되므로, 대기를 액션으로 만들면 있지도 않은 순서 제약이 생긴다.

    회전이 여러 틱(`TURN_TICKS > 1`)에 걸치면 첫 틱에 방향이 바뀌고 나머지는
    스윙 칸을 물고 대기한다. 그 대기 틱들은 상태가 안 바뀌므로 자연히 건너뛰고,
    회전 액션 하나가 그 시간 전체를 대표한다.

    `task_start` 는 `{agent: [(배정 틱, 주문 도착 틱), ...]}` 다 (lifelong 이
    준다). **배정 틱으로 첫 동작을 찾고, 주문 도착 틱을 그 동작에 단다** —
    ADG 실행기의 릴리스 바닥이 후자만 본다 (`Action.release_tick` 주석).
    안 주면 전부 None 이고 바닥이 아예 안 걸린다.

    ★ 2026-09-15 (-211) 에 평평한 `[틱, ...]` 에서 쌍으로 바꿨다. 전에는
      바닥이 `action.tick`(계획 시간표)을 썼는데 그건 주문 도착 시각이
      아니다. 옛 형식을 주면 여기서 죽는다 — 조용히 다른 뜻이 되느니 낫다.
    """
    agents = sorted(history[0])
    chains: list[list[Action]] = [[] for _ in agents]
    index = {a: i for i, a in enumerate(agents)}
    uid = 0
    stats = {MOVE: 0, TURN: 0, REVERSE: 0, WAIT: 0}
    # 아직 첫 동작을 못 찾은 태스크 시작 틱들 (오름차순으로 소비한다)
    def _pairs(a):
        out = sorted(task_start.get(a, []))
        for p in out:
            if not (isinstance(p, tuple) and len(p) == 2):
                raise TypeError(
                    "task_start 는 {agent: [(배정틱, 주문도착틱), ...]} 다. "
                    f"agent{a} 에서 {p!r} 를 받았다 — 평평한 틱 목록은 "
                    "-211 이전 형식이고 바닥이 계획 시간표를 쓰게 된다.")
        return out

    pending = {a: _pairs(a) for a in agents} if task_start \
        else {a: [] for a in agents}

    for t in range(len(history) - 1):
        for a in agents:
            s0, s1 = history[t][a], history[t + 1][a]
            kind = classify(s0, s1)
            stats[kind] += 1
            if kind == WAIT:
                continue
            i = index[a]
            cells = geom.swept_cells(s0, s1)
            # [patch_axle] 코만 스치는 앞 칸은 회전에만 있다. 전진·후진은 코가
            #   목표 칸을 안 벗어난다 (앞길이 0.390 < 반칸). 스위치가 꺼져 있으면
            #   `front_cells()` 가 빈 집합이라 여기도 빈 집합이다.
            guard = geom.front_cells(s0, s1) if kind == TURN else frozenset()
            # 이 동작이 어느 태스크의 첫 동작인가 — **배정 틱** 이하의 표시를
            # 전부 소비한다 (배정 뒤 여러 틱 대기했다가 움직이는 경우 대비).
            # 바닥에 다는 값은 그 태스크의 **주문 도착 틱**이다. 여러 개를
            # 소비하면 가장 이른 도착 틱을 쓴다 — 더 늦게 걸 이유가 없다.
            rel = None
            while pending[a] and pending[a][0][0] <= t:
                _assign, born = pending[a].pop(0)
                rel = born if rel is None else min(rel, born)
            act = Action(
                agent=a, idx=len(chains[i]), kind=kind, tick=t, frm=s0, to=s1,
                cells=cells, soft=guard & cells, guard=guard, uid=uid,
                release_tick=rel)
            _check_soft(act)
            chains[i].append(act)
            uid += 1
    return chains, agents, stats


def _check_soft(a: Action) -> None:
    """`soft` 분리가 몸 칸을 훔쳐 가지 않았는지 — **실패할 수 있는** 검사.

    ★ `hard | soft == cells` 를 검사하면 안 된다. `hard = cells - soft` 로
      정의했으니 **항진명제**라 절대 실패하지 않는다 (설계서 §2-4).

    무엇을 막는가: `front_cells()` 가 자기 칸을 안 빼면 그 칸이 `soft` 로 가고
    `hard` 에서 빠진다. 그러면 **로봇이 자기 바퀴가 있는 칸을 예약하지 않는다.**
    오류도 경고도 없이 간선이 사라지고 다른 로봇이 들어온다.

    `assert` 가 아니라 실제 검사인 이유: `python -O` 로 조용히 사라지면
    안 되는 종류다. 계획당 한 번, 액션 수천 개라 비용은 무시할 수준이다.

    ★ `SystemExit` 이 아니라 `RuntimeError` 다. 같은 시점/같은 성격의 실패인
      순환 검사가 `RuntimeError` 를 쓰고, 호출자(`plan_and_build*`)가 하나로
      다룬다. `SystemExit` 은 `BaseException` 이라 `except Exception` 을 뚫고
      나가 **Isaac 안에서는 Kit 이 통째로 내려간다.**
    """
    if not a.guard:
        return                                   # 스위치 꺼짐 — 볼 것이 없다

    # (1) 자기 축이 자기 앞 칸에 들어가면 자기 바퀴 칸을 안 잡는다.
    #     `soft` 가 아니라 `guard` 로 본다 — 규칙이 내놓은 것 자체를 봐야 한다.
    if a.axle & a.guard:
        raise RuntimeError(f"★ 축 칸이 앞 칸 규칙에 들어갔다: {a} "
                         f"축 {sorted(a.axle)} guard {sorted(a.guard)}")

    # (2) ★ 몸이 지나가는 칸이 guard 에 있으면 규칙이 틀린 것이다.
    #
    #   `soft` 는 "상대 **몸**은 와도 되고 **축**만 못 오는 칸" 이다. 우리
    #   몸이 쓸고 가는 칸을 거기 넣으면 `hard = cells - soft` 가 그 칸을
    #   몸 금지에서 **빼 버린다.** 2026-09-14 에 우리가 FMS 에 제안한 6칸
    #   (앞2+대각4)의 「뒤 대각」이 정확히 이 경우였다 — 8개 회전 전부에서
    #   모델 스윕 안이고, 그대로 켰으면 pitch 1.0 에서 접촉 96건이 났다.
    #
    #   (1) 은 이걸 못 잡는다. 자기 **축**((5,5))과 뒤 대각((4,4))은 다른
    #   칸이라 `axle & guard` 를 통과한다. 검사가 따로 필요하다.
    body = (set(occupied(a.frm)) | set(occupied(a.to))
            | set(swing_cells(a.frm[0], a.frm[1], a.frm[2], a.to[2])))
    stolen = a.guard & body
    if stolen:
        raise RuntimeError(
            f"""★ 앞 칸 규칙에 **몸 칸**이 들어왔다: {a}
  겹친 칸 {sorted(stolen)}  guard {sorted(a.guard)}
  soft 는 코만 스치는 칸이어야 한다. 몸이 지나는 칸을 넣으면
  hard 에서 빠져 상대 몸이 들어온다 — front_cells() 규칙 확인.""")

    if a.frm[:2] not in a.hard:
        raise RuntimeError(f"★ 출발 칸이 hard 에 없다: {a} "
                         f"출발 {a.frm[:2]} hard {sorted(a.hard)}")


# ===========================================================================
# SECTION 3 — ADG
# ===========================================================================


@dataclass
class ADG:
    chains: list[list[Action]]
    actions: list[Action]
    preds: dict[int, set[int]]
    succs: dict[int, set[int]]
    type1: int = 0
    type2: int = 0

    def topological_order(self) -> list[int] | None:
        """Kahn. None이면 순환 — 데드락 확정이므로 주행 전에 잡힌다."""
        indeg = {a.uid: len(self.preds[a.uid]) for a in self.actions}
        ready = [u for u, d in indeg.items() if d == 0]
        order = []
        while ready:
            u = ready.pop()
            order.append(u)
            for v in self.succs[u]:
                indeg[v] -= 1
                if indeg[v] == 0:
                    ready.append(v)
        return order if len(order) == len(self.actions) else None

    def summary(self) -> str:
        kinds = {k: sum(1 for a in self.actions if a.kind == k)
                 for k in (MOVE, TURN, REVERSE)}
        return "\n".join([
            f"액션             : {len(self.actions)}  "
            f"(전진 {kinds[MOVE]}, 회전 {kinds[TURN]}, 후진 {kinds[REVERSE]})",
            f"type 1 엣지      : {self.type1}  (같은 로봇의 순서)",
            f"type 2 엣지      : {self.type2}  (공유 칸에서의 로봇 간 순서)",
            f"비순환           : {self.topological_order() is not None}",
        ])


def _key(action: Action, cell: Cell) -> tuple[int, int, int]:
    """공유 칸에서 type 2 엣지의 방향을 정하는 전순서.

    가운데 필드가 leave-before-enter다 — 같은 틱이면 그 칸을 **이미 갖고 있던**
    로봇(놓아줄 쪽)이 **얻으려는** 로봇보다 먼저 정렬된다.

    `(tick, sub, agent)`가 전순서이고 같은 로봇의 체인은 tick에 대해 단조라서
    두 종류 엣지의 합집합에 순환이 생길 수 없다. `topological_order()`가 그걸
    말로 믿지 않고 실제로 확인한다.
    """
    return (action.tick, 0 if cell in occupied(action.frm) else 1, action.agent)


def _check_front_swing(actions: list[Action], geom: "RobotGeom") -> None:
    """앞 칸 규칙이 계획기와 ADG **양쪽에서** 같은 상태인지 (설계서 §0-1).

    네 검사를 한다.

      (1) 설정 일치 — 스위치가 양쪽에서 같은가.
          위임 설계라 ADG 쪽에 규칙 정의가 없으므로, 비교할 것은 **스위치
          상태**다. 이게 임시형이 아니라 최종형이다.

      (1b) 대각 스위치 일치 — `front_diag` 까지 본다.
          -79 부터 계획기 상태가 **둘**이다. `front_swing=True` 하나만으로는
          2칸인지 4칸인지 구별되지 않는다.

              front_swing=True, front_diag=False   -> 2칸
              front_swing=True, front_diag=True    -> 4칸

          규칙 집합 자체는 위임이라 자동으로 따라가지만, 지문·셀프테스트의
          기대값이 달라지므로 어느 상태인지는 기록으로 알아야 한다.

      (2) **pitch 게이팅이 실제로 작동하는가.**
          `configure(front_swing=True)` 를 `robot_dims` 없이 부르면 계획기가
          게이팅을 **통째로 건너뛴다** (-79 의 `configure` 본문:
          `if front_swing and robot_dims is not None:`). 그러면 1.2 에서도
          규칙이 켜진다. 여기서 직접 물어 잡는다 — 코가 칸을 안 벗어나는
          pitch 인데 규칙이 칸을 내놓으면 게이팅이 안 걸린 것이다.

      (3) 결과 정합 — 켰고 코가 칸을 벗어나는 pitch 인데 `guard` 가 전부
          비었으면 `front_cells()` 기하나 벤더 폴백이 고장난 것이다.
          **pitch 조건이 있어야** 1.2 에서 안 걸리고 1.0 에서만 걸린다.
    """
    try:
        import pibt.geometry as geo
        planner_on = bool(geo.front_swing_on())
    except (ImportError, AttributeError) as e:
        # 벤더 폴백에는 앞 칸 개념이 없다. 끈 상태로 도는 것은 정상이므로
        # 켜려 할 때만 막는다.
        if geom.front_swing:
            raise RuntimeError(
                f"★ 계획기에서 앞 칸 규칙을 확인할 수 없다 ({e!r}).\n"
                f"  원인 둘 중 하나다 — 증상이 같으니 둘 다 본다:\n"
                f"    (a) 브랜치의 3_FMS 가 -203 이전이다. geometry.py 에\n"
                f"        configure / front_cells / front_swing_on 이 아직 없다\n"
                f"    (b) pibt_core_v2 가 벤더 사본으로 떨어졌다 — 저장소 경로\n"
                f"  그 상태로 front_swing=True 를 켜면 계획기는 앞 칸을 모르는 "
                f"채로 ADG 만 켜진다.") from e
        return

    if planner_on != geom.front_swing:                      # (1)
        raise RuntimeError(
            f"★ 앞 칸 스위치가 어긋났다 — 계획기 {planner_on} / "
            f"ADG {geom.front_swing}.\n"
            f"  한쪽만 켜지면 계획에 위험한 배치가 남고 ADG 는 그걸 못 잡는다 "
            f"(주차한 로봇은 간선의 대상이 아니다).")

    # (1b) 대각 스위치. 계획기에 없으면(-79 이전) ADG 쪽도 꺼져 있어야 한다.
    planner_diag = bool(getattr(geo, "front_diag_on", lambda: False)())
    if planner_diag != geom.front_diag:
        raise RuntimeError(
            f"★ 대각 스위치가 어긋났다 — 계획기 {planner_diag} / "
            f"ADG {geom.front_diag}.\n"
            f"  규칙 집합은 위임이라 따라가지만, 지문과 셀프테스트의 기대값이 "
            f"달라진다. 어느 상태로 돌렸는지 기록에 남아야 한다.")

    # (2) pitch 게이팅이 정말 걸려 있나 — `robot_dims` 를 안 준 경우를 잡는다.
    if geom.front_swing and geom.pitch >= geom.nose_clears_cell_pitch:
        probe = geo.front_cells(5, 5, 1, 0)
        if probe:
            raise RuntimeError(
                f"★ pitch {geom.pitch:.2f} 는 코가 칸을 안 벗어나는 격자인데"
                f"(한계 {geom.nose_clears_cell_pitch:.4f}) 계획기가 앞 칸을 "
                f"{sorted(probe)} 로 내놓는다.\n"
                f"  configure(front_swing=True) 를 **robot_dims 없이** 불렀을 "
                f"때 생긴다 — 그러면 계획기가 게이팅을 통째로 건너뛴다.\n"
                f"  configure(..., robot_dims=(front_len, rear_len, width), "
                f"pitch=...) 로 부를 것.")

    if (geom.front_swing                                     # (3)
            and geom.pitch < geom.nose_clears_cell_pitch
            and not any(a.guard for a in actions)):
        raise RuntimeError(
            f"★ pitch {geom.pitch:.2f} 는 코가 칸을 벗어나는 격자인데"
            f"(한계 {geom.nose_clears_cell_pitch:.4f}) guard 가 전부 비었다 — "
            f"front_cells() 기하 또는 벤더 폴백을 확인하라.")


def build_adg(chains: list[list[Action]], geom: "RobotGeom | None" = None) -> ADG:
    actions = [a for ch in chains for a in ch]

    # [patch_axle] 앞 칸 규칙이 **한쪽만 켜진 상태**로 못 돌게 한다 (설계서 §0-1).
    #
    #   왜 위험한가: 계획기가 앞 칸을 모르면 계획 안에 "A 가 도는 동안 B 가
    #   A 의 앞 칸에 주차해 있는" 배치가 남는다. 그런데 ADG 간선은 **액션 사이의
    #   순서**만 강제하므로, 주차해서 아무 액션도 안 하는 로봇은 간선의 대상이
    #   아니다. 지금 pitch 1.0 의 ADG 순환이 그걸 알려 주는 **유일한 방어선**
    #   인데, 축 규칙을 켜면 그 순환이 풀린다. 안전망이 먼저 사라진다.
    #
    #   ★ 비교 대상은 **스위치 상태 하나**다. 규칙 자체(몇 칸인지)는
    #     `front_cells()` 가 FMS 로 위임하므로 ADG 쪽에 별도 정의가 없다.
    if geom is not None:
        _check_front_swing(actions, geom)

    preds: dict[int, set[int]] = {a.uid: set() for a in actions}
    succs: dict[int, set[int]] = {a.uid: set() for a in actions}
    t1 = t2 = 0

    for ch in chains:                                  # type 1
        for p, n in zip(ch, ch[1:]):
            preds[n.uid].add(p.uid)
            succs[p.uid].add(n.uid)
            t1 += 1

    # [patch_axle] `_key` 가 칸마다 전순서이려면 같은 tick 에 같은 로봇의
    #   액션이 둘 있으면 안 된다. `extract_actions` 구조상 참이지만, 비순환
    #   논거(설계서 §2-3-1)가 여기 걸려 있으므로 못 박아 둔다.
    if len({(a.agent, a.tick) for a in actions}) != len(actions):
        raise RuntimeError("★ 같은 tick 에 같은 로봇의 액션이 둘 이상이다 — "
                         "_key 가 전순서가 아니게 되어 비순환 보장이 깨진다")

    def _link(p: Action, n: Action) -> bool:
        if p.agent == n.agent or n.uid in succs[p.uid]:
            return False
        preds[n.uid].add(p.uid)
        succs[p.uid].add(n.uid)
        return True

    # type 2 ①  몸끼리 — 지금과 같다. 스위치가 꺼져 있으면 hard == cells 라
    #            `by_hard` 가 옛 `by_cell` 과 완전히 같다.
    by_hard: dict[Cell, list[Action]] = {}
    by_axle: dict[Cell, list[Action]] = {}
    for a in actions:
        for c in a.hard:
            by_hard.setdefault(c, []).append(a)
        for c in a.axle:
            by_axle.setdefault(c, []).append(a)
    for cell, users in by_hard.items():
        users.sort(key=lambda a: _key(a, cell))
        for p, n in zip(users, users[1:]):
            t2 += _link(p, n)

    # type 2 ②  상대의 **축**이 내 앞 칸(soft)에 있을 때만.
    #   `soft(p) & hard(q)` 는 간선을 만들지 않는다 — q 의 뒤 칸이 p 의 앞 칸에
    #   걸치는 배치(열 대기 줄)이고, 172 배치 전부 접촉 0 이었다.
    #   스위치가 꺼져 있으면 `guard` 가 전부 비어 이 루프가 **한 번도 안 돈다.**
    #
    #   ★ `soft` 가 아니라 `guard` 를 본다. `soft = guard & cells` 는 실제
    #     스윕 밖 칸을 떨어뜨리는데 pitch 1.0 에서 섞임 대각이 거기 해당해
    #     규칙이 4칸 -> 2칸으로 퇴화한다. 간선은 계획기가 보는 집합 그대로
    #     걸어야 계획기와 ADG 가 같은 규칙을 집행한다.
    # ★ [patch_adg_slim] (-224) `PIBT_ADG_SLIM=1` 이면 **인접 쌍만** 건다.
    #
    #   아래 기본 경로는 `p` 를 `by_axle[s]` 의 **모든** 액션에 잇는다. 6시간
    #   판(77,760틱·24대)에서 한 칸을 수백~수천 번 지나므로 여기서 간선이
    #   제곱으로 는다 — 실측 증가 지수 +2.54, 외삽 5.8억 간선 · 14.8 GB 로
    #   **메모리에 안 들어간다** (`tools/plan_scale.py`).
    #
    #   그런데 그 간선 대부분은 **중복이다.** 축 칸은 `hard` 에도 들어가므로
    #   (`hard = cells - soft`, `soft = guard & cells` 인데 자기 축은 자기
    #   guard 에 없다 — guard 는 회전에만 있고 앞 칸이다) 규칙 ① 이 그 칸의
    #   사용자를 `_key(·, s)` 순 사슬로 이미 묶는다.
    #
    #       q1 -> q2 -> q3      규칙 ①
    #       p  -> q1            규칙 ②, 하나면 충분
    #       p  ~> q2, q3        전이
    #
    #   그래서 `p` 의 자리를 이분 탐색해 **바로 앞·바로 뒤 하나씩만** 건다.
    #   도달 관계는 그대로다. 실측 절감 89.1% -> 96.1% -> 98.1% (호라이즌이
    #   클수록 더 준다), 전제 위반 0 (1,101 칸 전수, `tools/adg_edge_audit.py`).
    #
    #   ★ **기본은 꺼 둔다.** 안전 핵심이라 기본 경로가 비트 단위로 같아야
    #     하고, 켠 판을 `adg_edge_audit --verify` 로 도달 관계까지 확인한 뒤에
    #     기본값을 옮기는 것이 맞다.
    if os.environ.get("PIBT_ADG_SLIM", "0") in ("1", "true", "True"):
        import bisect as _bi
        ax = {}
        for s, qs in by_axle.items():
            qs2 = sorted(qs, key=lambda a: _key(a, s))
            ax[s] = (qs2, [_key(a, s) for a in qs2])
        for p in actions:
            for s in p.guard:
                got = ax.get(s)
                if not got:
                    continue
                qs2, ks = got
                i = _bi.bisect_left(ks, _key(p, s))
                # 동률은 없다 — `_key` 가 (tick, sub, agent) 전순서이고 서로
                # 다른 액션은 (tick, agent) 가 다르다.
                if i > 0:
                    t2 += _link(qs2[i - 1], p)
                if i < len(qs2):
                    t2 += _link(p, qs2[i])
    else:
        for p in actions:
            for s in p.guard:
                for q in by_axle.get(s, ()):
                    lo, hi = sorted((p, q), key=lambda a: _key(a, s))
                    t2 += _link(lo, hi)

    return ADG(chains=chains, actions=actions, preds=preds, succs=succs,
               type1=t1, type2=t2)


class AdgRuntime:
    """실행 중의 ADG 상태. 완료 이벤트 + (선택) 출발 하한.

    ``tick_s`` 를 주면 액션이 `계획틱 x tick_s` **이전에는 시작하지 않는다.**
    선행 조건을 대체하지 않고 **더한다.**

    왜 필요한가: `extract_actions` 는 대기를 버리고 ADG 는 순서만 남긴다.
    one-shot 에서는 그게 장점이지만(절대 시각을 버려야 지연에 강해진다),
    lifelong 에서는 버려지는 시각이 **주문 도착 시각**이다. 그대로 두면
    420 초에 걸쳐 도착할 태스크가 전부 t=0 에 시작하고, 12대가 2.3 초 안에
    한꺼번에 출발한다 (2026-09-07 실측, 버려진 대기 액션 1,329개).

    이르게 시작하는 것만 막으므로 늦은 로봇은 더 늦어지지 않는다 — ADG 의
    지연 복구는 그대로다. 실측 대가: stretch 1.72 에서 makespan +0.0%.
    """

    def __init__(self, adg: ADG, tick_s: float | None = None):
        self.adg = adg
        self.done: set[int] = set()
        self.next_idx = {i: 0 for i in range(len(adg.chains))}
        self.blocked_cells: set[Cell] = set()          # 장애물 보고로 막힌 칸
        self.tick_s = tick_s        # None 이면 예전 동작 (시각 무시)
        self.clock = 0.0

        # [patch_adg_why] 왜 멈췄나 — ①장애물 ②릴리스바닥 ③ADG선행 귀속
        #   `blocking()` 이 이미 셋을 구분한다. 여기서 세기만 한다.
        #   ★ release_time 의 최댓값 = 마지막틱 x tick_s. 그 이후로는 ② 가
        #     원리적으로 안 걸리므로, 전후를 갈라야 ③ 의 크기가 보인다.
        import os as _os
        self._why_on = _os.environ.get("ADG_WHY", "1") not in ("0", "", "false", "False")
        self._why_every = float(_os.environ.get("ADG_WHY_EVERY", "120"))
        self._why_next = self._why_every if self._why_on else float("inf")
        self._why = {}                      # agent -> [obstacle, release, adg]
        self._why_late = {}                 # 같은 것, release 지평 이후만
        # 「이 시각 뒤로는 관문 ②가 아무도 못 막는다」 = 바닥의 최댓값.
        # ★ 2026-09-15 (-211): 예전에는 `max(a.tick)`(= 마지막 **액션** 틱)을
        #   썼다. 바닥이 `action.tick` 이던 시절엔 그게 맞았지만 이제 바닥은
        #   `release_tick`(주문 도착 틱)이라 실제 지평이 더 이르다. 그대로
        #   두면 「지평 이후」 구간에 ②가 이미 안 걸리던 프레임이 섞여
        #   보고가 무뎌진다.
        self._why_horizon = (max((a.release_tick for a in adg.actions
                                  if a.release_tick is not None), default=0)
                             * (tick_s or 0.0))

    def advance(self, dt: float) -> None:
        self.clock += float(dt)
        # [patch_adg_why]
        if self.clock >= self._why_next:
            self._why_next += self._why_every
            self.why_report()

    # [patch_adg_why]
    def why_report(self) -> None:
        """막힌 프레임을 원인별로 찍는다. 비율만 의미가 있다."""
        if not self._why_on or not self._why:
            return
        try:
            import carb
            say = carb.log_warn
        except Exception:
            say = print
        NM = ("장애물", "릴리스", "ADG선행")

        def block(tbl, title):
            tot = [0, 0, 0]
            for v in tbl.values():
                for i in range(3):
                    tot[i] += v[i]
            n = sum(tot)
            if not n:
                say(f"[adg-why] {title}: 막힌 프레임 없음")
                return
            say(f"[adg-why] {title}  막힘 {n:,} 프레임")
            say(f"[adg-why]   {'로봇':>4} {'장애물':>8} {'릴리스':>8} "
                f"{'ADG선행':>8} {'합':>10}")
            for a in sorted(tbl):
                v = tbl[a]
                s = sum(v) or 1
                say(f"[adg-why]   {a:>4} {v[0]/s*100:7.1f}% {v[1]/s*100:7.1f}% "
                    f"{v[2]/s*100:7.1f}% {sum(v):>10,}")
            say(f"[adg-why]   {'전체':>4} {tot[0]/n*100:7.1f}% "
                f"{tot[1]/n*100:7.1f}% {tot[2]/n*100:7.1f}% {n:>10,}")

        say(f"[adg-why] ── t={self.clock:.0f}s  "
            f"릴리스 지평 {self._why_horizon:.0f}s ──")
        block(self._why, "전체 구간")
        if self.clock > self._why_horizon:
            block(self._why_late,
                  f"지평 이후 (t>{self._why_horizon:.0f}s — ② 가 안 걸리는 구간)")

    def release_time(self, action: Action) -> float:
        """이 동작을 **언제부터** 시작해도 되는가.

        주문 도착 제약이라 **태스크의 첫 동작에만** 건다. 중간 동작에 걸면
        로봇이 일찍 끝내도 계획 시각까지 서 있게 되고, 실측에서 그것이
        막힘의 66.2%(로봇 시간의 21.8%)였다 — `Action.release_tick` 주석 참조.

        ★ 2026-09-15 (-211): `action.tick`(계획 시간표) -> `release_tick`
          (주문 도착 틱). 첫 동작에만 걸어도 그 동작이 **계획에서 언제였나**를
          쓰면 여전히 시간표를 따르는 것이다. 계획이 실제보다 느리면 실행
          로봇이 이미 온 주문을 두고 기다린다.

        표시가 없는 동작(태스크 중간 · one-shot · 존 복귀)은 0 이다. 순서는
        관문 ③(ADG 선행)이 그대로 지킨다.
        """
        if self.tick_s is None or action.release_tick is None:
            return 0.0
        return action.release_tick * self.tick_s

    def pending(self, i: int) -> Action | None:
        k = self.next_idx[i]
        ch = self.adg.chains[i]
        return ch[k] if k < len(ch) else None

    # [patch_carry] 이어달리기 — 다음 액션 엿보기 -----------------------------
    def after(self, i: int) -> "Action | None":
        """**지금 돌고 있는** 액션의 다음 액션. `pending` 과 다르다.

        `next_idx` 는 `complete()` 에서만 오른다. 그래서 액션이 도는 동안
        `pending(i)` 은 **그 액션 자신**을 돌려준다. 하나 더 봐야 한다.
        """
        k = self.next_idx[i] + 1
        ch = self.adg.chains[i]
        return ch[k] if k < len(ch) else None

    def can_follow(self, running: "Action", nxt: "Action") -> bool:
        """현재 액션이 끝나는 **즉시** 다음 액션을 시작할 수 있는가.

        ★ `can_start(nxt)` 를 쓰면 안 된다. `nxt` 의 선행에는 지금 돌고 있는
          액션이 type 1 엣지로 들어 있고, 그건 아직 `done` 이 아니다. 그래서
          항상 False 가 나온다 — 이어달리기가 영영 안 걸린다.
          그 하나만 이미 끝난 것으로 보고 나머지를 본다.
        """
        if nxt.cells & self.blocked_cells:
            return False
        if self.clock + 1e-9 < self.release_time(nxt):
            return False
        return all(u in self.done or u == running.uid
                   for u in self.adg.preds[nxt.uid])

    # [patch_adg_why]
    def _why_hit(self, action, k: int) -> None:
        a = getattr(action, "agent", -1)
        self._why.setdefault(a, [0, 0, 0])[k] += 1
        if self.clock > self._why_horizon:
            self._why_late.setdefault(a, [0, 0, 0])[k] += 1

    def can_start(self, action: Action) -> bool:
        if action.cells & self.blocked_cells:
            if self._why_on:
                self._why_hit(action, 0)
            return False                               # 장애물이 경로 위
        if self.clock + 1e-9 < self.release_time(action):
            if self._why_on:
                self._why_hit(action, 1)
            return False                               # 아직 주문이 안 왔다
        ok = all(u in self.done for u in self.adg.preds[action.uid])
        if not ok and self._why_on:
            self._why_hit(action, 2)                   # ADG 선행 대기
        return ok

    def blocking(self, action: Action) -> list[int]:
        """왜 못 시작하는지 — 진단용. 하한 대기 중이면 [-1] 을 앞에 붙인다."""
        out = [u for u in self.adg.preds[action.uid] if u not in self.done]
        if self.clock + 1e-9 < self.release_time(action):
            out = [-1] + out
        return out

    def complete(self, i: int, action: Action) -> None:
        self.done.add(action.uid)
        self.next_idx[i] += 1

    @property
    def finished(self) -> bool:
        return len(self.done) == len(self.adg.actions)


# ===========================================================================
# SECTION 4 — 로봇 드라이버
# ===========================================================================


class RobotDriver(Protocol):
    """주행 계층이 로봇에게 요구하는 전부. 두 개뿐이다."""

    def axle_pose(self) -> tuple[float, float, float]:
        """구동축의 world pose (x, y, yaw). Isaac에서 읽는다."""
        ...

    def command(self, v: float, w: float) -> None:
        """선속도 m/s, 각속도 rad/s. 차동구동 역기구학은 구현체가 담당."""
        ...


class KinematicDriver:
    """물리 없이 (v, w)를 적분하는 드라이버 — 1단계 검증용.

    `slip`과 `lag`으로 실제 컨트롤러의 불완전함을 흉내낸다. ADG의 보장은
    "타이밍이 어긋나도 안전"이므로, 여기서 깨지면 Isaac Sim에서도 깨진다.
    """

    def __init__(self, x: float, y: float, yaw: float, rng: random.Random,
                 slip: float = 0.0, lag: float = 0.0, pose_lag: float = 0.0):
        self.x, self.y, self.yaw = x, y, yaw
        self.rng = rng
        self.slip = slip
        self.lag = lag
        # ★ `lag` 은 **명령** 쪽 1차 지연(구동기 응답)이고, `pose_lag` 은
        #   **관측** 쪽 지연이다 (-224). 둘은 위험이 다르다.
        #
        #   EMQX/ROS2 를 붙이면 실행기가 보는 pose 가 낡는다. 그런데
        #   `complete()` 가 바로 그 pose 로 `body & released` 를 판정한다.
        #   낡은 pose 로 「빠져나왔다」고 하면 아직 그 칸에 있는데 뒷차를
        #   들여보낸다 — 순서 보장이 아니라 **기하 여유**가 깨진다.
        #
        #   여유가 얼마나 얇은지는 산수로 나온다:
        #       4칸 규칙 설계 여유 41.4 mm / v_max 0.9 m/s = 46 ms
        #       도착 허용오차     50.0 mm / 0.9           = 56 ms
        #   설계 여유 전부가 로봇 이동 46 밀리초다. 브로커 왕복과 같은 크기라
        #   붙이기 **전에** 재야 한다.
        self.pose_lag = float(pose_lag)
        self._t = 0.0
        self._hist: list[tuple[float, float, float, float]] = [(0.0, x, y, yaw)]
        self._v = self._w = 0.0
        self._cv = self._cw = 0.0
        self.gain = 1.0 - slip * rng.random() if slip else 1.0

    def axle_pose(self) -> tuple[float, float, float]:
        if self.pose_lag <= 0.0:
            return (self.x, self.y, self.yaw)
        want = self._t - self.pose_lag
        h = self._hist
        # 앞에서부터 버린다 — h[0] 이 `want` 이하인 **가장 최근** 표본이 되게.
        while len(h) > 1 and h[1][0] <= want:
            h.pop(0)
        return (h[0][1], h[0][2], h[0][3])

    def command(self, v: float, w: float) -> None:
        self._cv, self._cw = v, w

    def integrate(self, dt: float) -> None:
        k = 1.0 if self.lag <= 0 else clamp(dt / self.lag, 0.0, 1.0)
        self._v += (self._cv - self._v) * k
        self._w += (self._cw - self._w) * k
        v, w = self._v * self.gain, self._w * self.gain
        self.yaw = wrap(self.yaw + w * dt)
        self.x += v * math.cos(self.yaw) * dt
        self.y += v * math.sin(self.yaw) * dt
        self._t += dt
        if self.pose_lag > 0.0:
            self._hist.append((self._t, self.x, self.y, self.yaw))


class DifferentialDriver:
    """Isaac Sim articulation 래퍼 — 차동구동 역기구학 포함.

    `prim`은 world pose를 주는 무엇이든 된다. Isaac 버전마다 API 이름이
    달라서(`omni.isaac.core` -> `isaacsim.core.api`) 여기서는 **호출자가 이미
    갖고 있는 객체**를 받고, 필요한 두 동작만 콜러블로 주입받는다. wppl.py에서
    쓰던 핸들을 그대로 넘기면 된다.

        DifferentialDriver(
            geom,
            get_pose=lambda: robot.get_world_pose(),        # (pos[3], quat[4])
            set_wheel_vel=lambda l, r: robot.apply_wheel_actions(
                ArticulationAction(joint_velocities=[l, r],
                                   joint_indices=wheel_idx)),
            wheel_radius=0.125, wheel_base=0.50,
        )
    """

    def __init__(self, geom: RobotGeom,
                 get_pose: Callable[[], tuple],
                 set_wheel_vel: Callable[[float, float], None],
                 wheel_radius: float, wheel_base: float,
                 quat_order: str = "wxyz"):
        self.geom = geom
        self._get_pose = get_pose
        self._set = set_wheel_vel
        self.rw = wheel_radius
        self.wb = wheel_base
        self.quat_order = quat_order      # Isaac get_world_pose() = (w, x, y, z)

    def axle_pose(self) -> tuple[float, float, float]:
        pos, quat = self._get_pose()
        yaw = _yaw_from_quat(quat, self.quat_order)
        x, y = self.geom.axle_from_prim_pose(float(pos[0]), float(pos[1]), yaw)
        return (x, y, yaw)

    def command(self, v: float, w: float) -> None:
        vl = (v - w * self.wb * 0.5) / self.rw          # rad/s
        vr = (v + w * self.wb * 0.5) / self.rw
        self._set(vl, vr)


QUAT_ORDERS = ("wxyz", "xyzw")


def _yaw_from_quat(q, order: str = "wxyz") -> float:
    """쿼터니언 -> z축 회전각. ``order`` 는 반드시 명시적으로 준다.

    ★ 2026-09-06 수정. 이전 판은 성분 크기로 순서를 **추측**했다:

        if abs(q[0]) >= abs(q[3]): (w,x,y,z) else: (x,y,z,w)

    이 추측은 |yaw| > 90도에서 항상 틀린다. yaw=180도이면 (w,x,y,z)=(0,0,0,1)
    이라 |w|=0 < |z|=1 이 되어 (x,y,z,w)로 오독하고 **0도를 돌려준다.**

        실측:  91도->0도   135도->0도   180도->0도   -135도->0도

    회전각의 절반이 쿼터니언에 들어가므로 |yaw|>90도면 |w|<|z| 가 되는 것이
    정상이다 — 즉 이 추측은 원리적으로 성립할 수 없었다. 순서는 데이터에서
    알아낼 수 있는 것이 아니라 **API 규약**이므로 인자로 받는다.

    Isaac Sim 의 `get_world_pose()` 는 스칼라 우선 (w, x, y, z) 이다.
    """
    if order not in QUAT_ORDERS:
        raise ValueError(f"order 는 {QUAT_ORDERS} 중 하나여야 한다: {order!r}")
    a, b, c, d = (float(v) for v in q)
    w, x, y, z = (a, b, c, d) if order == "wxyz" else (d, a, b, c)
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


# ===========================================================================
# SECTION 5 — 동작 컨트롤러
# ===========================================================================


def _tol_env(name, default):
    """`PIBT_TOL_POS` 등으로 허용오차를 덮어쓴다. 기본은 아래 값 그대로다.

    ★ 왜 환경변수가 필요한가 (2026-09-16).
      `pos = 0.05` 는 **pitch 1.2 격자에서 정해진 값**인데, 1.0 에서는
      「인접 행에 선 이웃 옆에서 한쪽이 회전할 때」의 기하 여유가

          pitch - 폭/2 - 코반경 = 1.0 - 0.400 - 0.5587 = 41.3 mm

      뿐이다. **허용오차 50 mm 가 그 예산보다 크다.** 도착 판정이
      `hypot(dx,dy) <= pos` 라 로봇은 늘 그 원의 가장자리에 서고(실측 중앙
      -45.7 mm, 다섯 시드 일치), 그래서 옆에서 누가 돌면 닿는다 — 5판 중
      2판이 실제로 차체 접촉으로 중단됐다.

      고치려면 값을 흔들어 봐야 하는데 `FleetController` 가 `tol` 을 안 받는다
      (`live_pibt.py:1078`). 호출부를 고치는 대신 여기서 읽는다 — `_lim` 경고
      계산도 같은 값을 보게 되어 둘이 갈리지 않는다.

      속도는 제약이 아니다. 멈추기 직전 속도가 최대 0.175 m/s 라
      `pos = 0.010` 의 경고선 0.60 m/s 에도 안 닿는다 (`tools/stop_error.py
      --hist`). 감속 때문에 순항 속도 `v_exec` 와 무관하다.
    """
    raw = os.environ.get(name, "").strip()
    return float(raw) if raw else default


# ★ 직선 추종 이득 (-224). 기본값은 예전 하드코딩 그대로라 **비트 동일**이다.
#
#   w = K_CROSS*cross + K_HEAD*head 인데, 직진 중 두 항은 균형을 이룬다.
#   `cross = along*sin(head) - q*cos(head)` 이므로 (q = 차선 이탈) w = 0 에서
#
#       head = K_CROSS*q / (K_HEAD + K_CROSS*along)
#
#   즉 **요잉 오차는 횡이탈을 죽이려고 유지되는 각도**다 (게 걸음). 비율
#   K_CROSS/K_HEAD 가 그 crab 각의 크기를 정한다. 꼬리 이탈이 예산 100 mm 를
#   넘는 것이 이것 때문인지 `tools/gain_balance.py` 로 먼저 확인하고 흔든다.
K_CROSS = _tol_env("PIBT_K_CROSS", 1.8)
K_HEAD = _tol_env("PIBT_K_HEAD", 2.2)


@dataclass
class Tolerance:
    # ★ pitch 1.0 에서는 0.05 가 기하 여유 41.3 mm 보다 크다 — 위 설명 참고.
    #   바꿔 보려면 `PIBT_TOL_POS=0.010` 처럼 준다.
    pos: float = field(default_factory=lambda: _tol_env("PIBT_TOL_POS", 0.05))
    yaw: float = field(default_factory=lambda: _tol_env("PIBT_TOL_YAW", 0.05))
    cross: float = field(default_factory=lambda: _tol_env("PIBT_TOL_CROSS", 0.06))


class MotionController:
    """액션 하나를 (v, w) 명령으로 옮기고 완료를 판정한다.

    회전은 제자리 각도 제어, 전·후진은 직선 구간 추종이다. 격자 경로라서 목표
    방향이 이미 맞으므로, 추종은 횡오차와 방향오차를 죽이는 것으로 충분하다.
    """

    def __init__(self, geom: RobotGeom, tol: Tolerance | None = None,
                 v_exec: float | None = None, a_exec: float | None = None):
        self.g = geom
        self.tol = tol or Tolerance()
        self.action: Action | None = None
        self._v = 0.0
        # [patch_vexec] **실행 속도는 계획 속도와 다른 값이다** (2026-09-14).
        #   `geom.v_max`(= config.SPEED_PLAN 0.9)는 계획의 틱 길이
        #   `pitch / v_max` 와 ADG 릴리스 일정을 정한다. 그걸 올리면 계획이
        #   통째로 바뀐다. 그래서 실행 상한을 따로 둔다.
        #
        #   ★ 실행만 빠르게 하는 것은 **안전한 방향**이다. ADG 는 시간표가
        #     아니라 순서로 돌기 때문에, 일찍 도착하면 선행을 기다릴 뿐이다.
        #     위험한 것은 반대(계획보다 느림)이고, 그래서 SPEED_PLAN 을
        #     1.2 -> 0.9 로 내렸었다 (config.py:49). 그 근거는 시간표 기반
        #     드라이버 것이라 ADG 에는 그대로 적용되지 않는다.
        #
        #   이어달리기가 없을 때는 올려도 거의 소용이 없었다 — 1.2 m 칸
        #   안에서 정지->정지면 램프가 84%라 속도를 쓸 구간이 없다
        #   (0.9 -> 무한대가 칸당 9 ms). 이어달리기가 들어간 지금은 직진
        #   구간(중앙값 7칸 = 8.4 m)을 연속으로 가므로 쓸 구간이 생긴다:
        #     v 0.9 -> 1.2  -18.7%    v 0.9 -> 1.6  -30.7%   (8.4 m 기준)
        self.v_exec = float(v_exec) if v_exec else geom.v_max
        self.a_exec = float(a_exec) if a_exec else geom.a_lin
        # [patch_carry] 이어달리기 종단속도. 0 이면 목표에서 완전히 선다.
        #   FleetController 가 매 스텝 정해 준다 — 다음 액션이 같은 방향
        #   직진이고 곧바로 시작 가능할 때만 0 보다 크다.
        self.exit_v = 0.0

    def begin(self, action: Action, keep_speed: bool = False) -> None:
        """`keep_speed` 면 현재 속도를 물려받는다 (이어달리기).

        회전으로 넘어갈 때는 반드시 False 다 — 제자리 선회에 선속도를 들고
        들어가면 칸을 벗어난다.
        """
        self.action = action
        if not keep_speed:
            self._v = 0.0
        self.exit_v = 0.0
        self.tx, self.ty, self.tyaw = self.g.state_pose(action.to)
        sx, sy, _ = self.g.state_pose(action.frm)
        self.sx, self.sy = sx, sy
        # 전진인지 후진인지는 액션 이름이 아니라 기하로 정한다. pibt_core의
        # '전진'은 헤딩 라벨링에 따라 물리적으로 후진일 수 있다 (heading_offset).
        dr, dc = action.to[0] - action.frm[0], action.to[1] - action.frm[1]
        hx, hy = self.g.heading_vec(action.frm[2])
        self.sign = 1.0 if (dc * hx + dr * hy) >= 0.0 else -1.0

    def update(self, pose: tuple[float, float, float], dt: float) -> tuple[float, float]:
        a = self.action
        assert a is not None
        x, y, yaw = pose
        g = self.g

        if a.kind == TURN:
            err = wrap(self.tyaw - yaw)
            w = clamp(3.0 * err, -g.w_max, g.w_max)
            if abs(err) < 3.0 * self.tol.yaw:            # 마지막엔 부드럽게
                w = clamp(w, -0.4 * g.w_max, 0.4 * g.w_max)
            return (0.0, w)

        # 진행 방향 단위벡터. 후진이면 헤딩의 반대다. (begin()이 기하로 정함)
        sign = self.sign
        fx, fy = math.cos(yaw) * sign, math.sin(yaw) * sign
        dx, dy = self.tx - x, self.ty - y
        along = dx * fx + dy * fy                        # 남은 거리 (진행 방향)
        cross = fx * dy - fy * dx                        # 진행 방향 기준 좌측(+) 오차
        head = wrap(self.tyaw - yaw)

        # 조향 부호에 sign을 곱하지 않는다. (fx, fy)에 이미 방향이 들어 있고,
        # 차체를 +w로 돌리면 진행 방향 벡터도 같이 +w만큼 돈다 — 전진이든 후진이든.
        # 여기에 sign을 한 번 더 곱하면 후진에서 조향이 반대로 걸려 횡오차가
        # 발산하고, 방향 항과 싸우다가 목표 반경에 영영 못 든다.
        w = clamp(K_CROSS * cross + K_HEAD * head, -g.w_max, g.w_max)

        # 속도는 대칭으로: 지나쳤으면(along < 0) 되돌아올 수 있어야 한다.
        # 감속 계수는 **물리적** 후진에 붙인다 (센서가 없는 방향이므로).
        v_cap = self.v_exec * (1.0 if sign > 0 else 1.0 / REVERSE_FACTOR)
        # [patch_carry] 종단속도를 0 이 아니게 둘 수 있다 (이어달리기).
        #   sqrt(2a|d|) 는 "목표에서 정확히 0" 이 되는 곡선이다. 칸마다 이걸
        #   쓰면 칸마다 선다. exit_v 를 실으면 그 속도로 목표를 통과한다.
        brake = (math.sqrt(self.exit_v ** 2 + 2.0 * self.a_exec * abs(along))
                 if along else self.exit_v)
        lim = min(v_cap, max(brake, 0.05))
        want = clamp(1.6 * along, -lim, lim)
        if self.exit_v > 0.0 and along > 0.0:
            want = max(want, min(lim, self.exit_v))   # 목표 근처에서 0 으로 안 죽게
        self._v += clamp(want - self._v, -self.a_exec * dt, self.a_exec * dt)
        return (sign * self._v, w)

    def at_target(self, pose: tuple[float, float, float]) -> bool:
        a = self.action
        assert a is not None
        x, y, yaw = pose
        if abs(wrap(self.tyaw - yaw)) > self.tol.yaw:
            return False
        if a.kind == TURN:
            return True
        return math.hypot(self.tx - x, self.ty - y) <= self.tol.pos

    def complete(self, pose: tuple[float, float, float],
                 body: frozenset[Cell] | None = None) -> bool:
        """★ 완료 판정. 목표 도달 **그리고** 놓아줄 칸에서 차체가 빠져나옴.

        두 번째 조건이 ADG 보장을 지탱한다. 목표 도달만 보면, 컨트롤러가 오버슛
        해서 꼬리가 이전 칸에 걸쳐 있는 채로 완료가 발화하고 후속 로봇이 그
        칸으로 들어온다.

        ``body``는 호출자가 이미 계산한 점유 칸(주행 루프가 스텝당 한 번만
        구한다). 없으면 여기서 구한다.
        """
        if not self.at_target(pose):
            return False
        a = self.action
        assert a is not None
        if not a.released:
            return True
        if body is None:
            body = self.g.footprint_cells(*pose)
        return not (body & a.released)


# ===========================================================================
# SECTION 6 — 플릿 루프
# ===========================================================================


@dataclass
class FleetStats:
    steps: int = 0
    started: int = 0
    completed: int = 0
    overlap_events: int = 0
    carried: int = 0           # [patch_carry] 정지 없이 다음 칸으로 이어간 횟수
    overlap_pairs: set[tuple[int, int]] = field(default_factory=set)
    worst_overlap: int = 0
    # 겹침 중 관측된 **차체 사이 최소 거리** [m]. 겹침이 없으면 inf.
    #   ★ `worst_overlap`(공유 칸 수)만으로는 심각도를 못 잰다. 1.2 m 칸을
    #     공유 단위로 쓰면 **57 cm 떨어진 두 대도 "겹침"** 이 된다 — 2026-09-14
    #     실측: 대각선 이웃이 칸 하나를 각각 5.1 mm · 2.7 mm 씩 스쳤는데
    #     차체 간격은 0.568 m 였다. 심각도를 가르는 것은 이 거리다.
    worst_gap: float = float("inf")
    # **실제로 차체가 닿은** 스텝 수. `overlap_events`(칸 공유)와 구별된다.
    #   판정을 칸에서 거리로 옮긴 이유 (2026-09-14):
    #   ADG 는 **이상적 칸 중심 자세**로 `swept_cells` 를 계산하는데 실행은
    #   그만큼 정확하지 않다. 실측에서 회전 중인 로봇이 칸 중심에서 0.051 m
    #   어긋나 있었고, 그 때문에 차체 모서리가 옆 칸으로 **2.7 mm** 밀려
    #   칸 공유가 떴다. 그때 두 차체 사이는 **0.568 m** 였다.
    #   즉 칸 공유는 "모델과 실행이 어긋났다" 는 신호이지 충돌이 아니다.
    #   구조적으로 계속 나므로, 주행의 합불은 이 값으로 가른다.
    contact_events: int = 0
    stall_steps: int = 0
    sim_time: float = 0.0

    @property
    def clean(self) -> bool:
        """**차체가 닿지 않았는가.** 칸 공유는 합불에 넣지 않는다 (위 주석)."""
        return self.contact_events == 0

    @property
    def cells_clean(self) -> bool:
        """칸 공유조차 없었는가 — 모델과 실행이 완전히 일치했다는 뜻."""
        return self.overlap_events == 0

    @property
    def contact(self) -> bool:
        """차체가 **실제로 닿았는가.** 칸 공유(보수적 감시선)와 구별된다."""
        return self.worst_gap <= 0.0

    def overlap_grade(self) -> str:
        """겹침 심각도 한 줄. 거리로 가른다."""
        if self.overlap_events == 0:
            return "겹침 없음"
        g = self.worst_gap
        if g <= 0.0:
            return f"★★ 실제 접촉 (차체 간격 {g:.3f} m) — 브리지 버그"
        if g < CONTACT_NEAR:
            return f"★ 근접 (차체 간격 {g:.3f} m) — 확인 필요"
        return (f"⚠ 칸 공유만 (차체 간격 {g:.3f} m) — 접촉 아님. "
                f"감시선이 보수적으로 운 것")


class FleetController:
    """매 물리 스텝 `step(dt)`를 부르면 된다. 시간표는 없다.

    Isaac Sim에서:

        fleet = FleetController(geom, adg, drivers, order=order)
        while app.is_running():
            world.step(render=True)
            fleet.step(world.get_physics_dt())
            if fleet.stats.contact_events:
                break             # 차체 접촉 — 브리지 버그. 조용히 넘기지 말 것
                                  # (칸 공유는 stats.overlap_events 로 따로 본다)
    """

    def __init__(self, geom: RobotGeom, adg: ADG, drivers: dict[int, RobotDriver],
                 order: Sequence[int] | None = None, tol: Tolerance | None = None,
                 safety_check: bool = True, action_timeout: float = 60.0,
                 stall_timeout: float = 20.0,
                 starts: dict[int, State] | None = None,
                 release: bool = False, carry: bool = True,
                 v_exec: float | None = None, a_exec: float | None = None):
        self.g = geom
        # release=True 면 계획의 출발 시각을 지킨다 (lifelong 에서 필수).
        # one-shot 은 도착 시각이라는 개념이 없으니 기본값 False 로 둔다.
        # [patch_ticks] 계획 틱 -> 초. 우리 경로(step_h)에서 **전진은 1틱**
        #   이므로 `pitch / v_max` 가 맞다. `MOVE_TICKS` 로 나누면 안 된다 —
        #   그건 FmsKernel 경로의 상수다 (위 주석).
        #
        #   ☹ 다만 회전은 TURN_TICKS(5) 틱을 쓰는데 물리적으로는 ~0.9초다.
        #     그래서 회전이 많은 계획에서는 릴리스 하한이 늦게 잡힌다. 틱이
        #     더는 균일한 시간 단위가 아니라 상수 하나로는 못 맞춘다.
        #     `release` 는 lifelong 에서만 켜므로 지금은 감수한다.
        # ★ 틱 모델 정합 (2026-09-15, -211). 전진 1칸이 MOVE_TICKS 틱이 되어
        #   **틱 != 칸**이다. 릴리스 바닥은 `action.tick x tick_s` 라 틱 단위를
        #   써야 한다. `HORIZON` 도 같이 4배가 되어야 지평(350 s)이 보존된다 —
        #   한쪽만 바꾸면 87.5 s 나 1,400 s 가 되고 **에러는 안 난다**.
        self.rt = AdgRuntime(
            adg,
            tick_s=(geom.pitch / (geom.v_max * MOVE_TICKS)) if release else None)
        self.drivers = drivers
        # chains의 인덱스 = extract_actions가 쓴 agent 순서. 명시적으로 받는다.
        self.order = list(order) if order is not None else sorted(drivers)
        if len(self.order) != len(adg.chains):
            raise ValueError(f"order {len(self.order)}개 != chains {len(adg.chains)}개")
        self.agents = [a for a in self.order if a in drivers]
        self.slot = {a: i for i, a in enumerate(self.order)}
        # [patch_vexec] 실행 속도·가속. 환경변수 > 인자 > 계획값 순.
        #   `geom.v_max` 는 계획이 쓰는 값이라 건드리지 않는다 (tick_s, 릴리스).
        self.v_exec = float(os.environ.get("PIBT_V_EXEC", "") or v_exec or geom.v_max)
        self.a_exec = float(os.environ.get("PIBT_A_EXEC", "") or a_exec or geom.a_lin)
        # ★ 도착 판정이 속도를 못 따라가면 안 된다. 한 스텝에 움직이는 거리가
        #   허용오차 지름(2 * tol.pos)보다 크면 `at_target` 창을 건너뛰어
        #   완료가 영영 안 뜬다 — 오버슈트하고 되돌아오기를 반복한다.
        #   60 Hz · tol.pos 0.05 -> 안전 상한 6.0 m/s. 여유를 보고 절반에서 경고.
        _hz = 60.0
        _lim = 2.0 * (tol or Tolerance()).pos * _hz
        if self.v_exec > 0.5 * _lim:
            print(f"★ 실행 속도 {self.v_exec:.2f} m/s 가 도착 판정 한계 "
                  f"{_lim:.2f} m/s 의 절반을 넘습니다 (tol.pos="
                  f"{(tol or Tolerance()).pos} m @ {_hz:.0f} Hz). "
                  f"완료를 놓칠 수 있으니 tol.pos 를 키우세요.")
        self.ctrl = {a: MotionController(geom, tol, self.v_exec, self.a_exec)
                     for a in self.agents}
        self.running: dict[int, Action | None] = {a: None for a in self.agents}
        self.elapsed: dict[int, float] = {a: 0.0 for a in self.agents}
        self.safety_check = safety_check
        self.action_timeout = action_timeout
        #   회전이 이만큼 **한 번도 안 가까워지면** 교착으로 본다.
        #   `action_timeout`(경고)보다 짧다 — 경고는 정상 대기에도 뜨지만
        #   회전 정체는 그 자체가 이상이라 더 일찍 끊는 것이 맞다.
        self.stall_timeout = float(
            os.environ.get("PIBT_STALL_TIMEOUT", "") or stall_timeout)
        self.timeouts: list[str] = []
        # ★ 회전 교착 워치독 (-224). 액션 단위로 본다.
        #
        #   함대 `completed` 가 안 는 것으로 판정하면 **저부하에서 오발동**한다
        #   — `order_gap 60` 이면 정상 대기가 16.7초를 넘고, 여러 대가 같이
        #   기다리면 더 길어진다. 전진도 「남이 비켜주기」라는 정상 대기가
        #   있어 판정이 어렵다.
        #
        #   **회전은 다르다.** `w` 만 주면 되므로 각도 오차가 안 줄면
        #   확실히 이상이다. 그래서 회전만 본다.
        self.turn_best: dict[int, float] = {}    # 액션별 지금까지 최소 |err|
        self.turn_idle: dict[int, float] = {}    # 그 최소가 안 갱신된 시간
        self.stall: str | None = None            # 채워지면 호출자가 멈춘다
        self.starts = starts
        # 개루프 감지 — 명령은 나가는데 pose 가 안 변하는 상태
        self._last_cmd: dict[int, tuple[float, float]] = {a: (0.0, 0.0) for a in self.agents}
        self._last_pose: dict[int, tuple[float, float, float]] = {}
        self._frozen: dict[int, int] = {a: 0 for a in self.agents}
        self.open_loop: list[str] = []
        self.stats = FleetStats()
        self._reported: set[tuple[int, int]] = set()   # 겹침 상세를 찍은 쌍
        # [patch_carry] 이어달리기 ------------------------------------------
        #   칸마다 정지하면 1.2 m 의 84%가 가감속 램프다. 0.9 m/s 를 쓰는 시간이
        #   한 칸당 0.21 s(8.5%)뿐이다 (2026-09-14 실측 2.367 s/칸).
        #
        #   ★ 안전 근거는 기하다. 구동축이 목표 칸 중심에 있을 때 차체 앞끝은
        #     front_len(0.390 m) 앞이고, 칸 반폭은 0.600 m 다. 즉 축이 중심을
        #     **0.210 m** 지나야 몸이 다음 칸에 들어간다. 그 거리 안에 설 수
        #     있는 속도까지만 싣는다 — 다음 칸을 못 잡아도 칸 밖에서 멈춘다.
        #
        #   `can_start` 의 세 조건 중 선행 완료·릴리스 시각은 **단조**다
        #   (done 은 줄지 않고 clock 은 는다). 단조가 아닌 것은 `blocked_cells`
        #   하나뿐이다 — 장애물이 새로 생길 수 있다.
        #
        #   그래서 상한을 **두 개** 둔다 (2026-09-14 수정).
        #
        #     장애물이 있을 때  sqrt(2 * a_lin * margin) = 0.580 m/s
        #        `can_follow` 가 참이었다가 뒤집힐 수 있으므로, 다음 칸을 못
        #        잡아도 **칸 밖에서** 설 수 있는 속도까지만 싣는다.
        #
        #     장애물이 없을 때  v_max = 0.900 m/s
        #        세 조건이 모두 단조 -> 한 번 참이면 계속 참 -> 감속할 이유가
        #        없다. 목표 칸을 **순항 속도 그대로** 통과한다.
        #
        #   ★ 왜 나누나: 0.580 으로 묶으면 칸 경계마다 0.9 -> 0.58 -> 0.9 로
        #     오르내린다. 멈추지는 않지만 순항이 아니다 — 영상에서 바로 보인다.
        #     그리고 `blocked_cells` 를 채우는 코드가 지금 아무 데도 없다
        #     (`block()` 을 부르는 곳이 없고, [adg-why] 의 장애물 열도 전 판
        #     0.0% 였다). 즉 0.580 상한은 **일어나지 않는 경우**를 막고 있었다.
        #     장애물 보고가 들어오면 자동으로 안전한 쪽으로 내려간다.
        margin = 0.5 * geom.pitch - geom.front_len
        # ★ `margin <= 0` 이면 이어달리기가 **통째로 꺼지는데 로그에 표시가
        #   없었다.** 처리량이 40% 떨어지고 원인을 알 수 없다. pitch 1.0 에서는
        #   0.110 이라 아직 켜지지만 **pitch 0.78 이하에서 0 이 된다**
        #   (0.5 * pitch = front_len 0.390). 조용히 꺼지면 안 된다.
        if carry and margin <= 0.0:
            print(f"★ 이어달리기가 꺼졌다 — 칸 반폭 {0.5 * geom.pitch:.3f} 이 "
                  f"앞길이 {geom.front_len:.3f} 이하다 (여유 {margin:+.3f} m).\n"
                  f"  pitch 를 {2.0 * geom.front_len:.3f} m 보다 크게 하거나 "
                  f"차체 앞길이를 줄여야 한다. 지금은 매 칸 정지로 돈다.")
        self.carry_safe = (min(self.v_exec, math.sqrt(2.0 * self.a_exec * margin))
                           if carry and margin > 0.0 else 0.0)
        self.carry_free = self.v_exec if carry and margin > 0.0 else 0.0
        # 시험용 고정 상한. 비워 두면 위 규칙을 쓴다.
        _cv = os.environ.get("PIBT_CARRY_V", "")
        self.carry_fixed = float(_cv) if _cv else None
        if starts is not None:
            self.verify_start()

    # ---- 시작 pose 정합성 -------------------------------------------------

    def verify_start(self, pos_tol: float = 0.30, yaw_tol: float = 0.20) -> None:
        """★ 주행 전에 '로봇이 계획이 말하는 자리에 있는가'를 확인한다.

        ADG 는 계획된 시작 배치를 전제로 순서를 잡는다. 로봇이 다른 곳에 있으면
        예약과 실제가 처음부터 어긋나고, 컨트롤러는 엉뚱한 방향으로 달린다 —
        셀프테스트는 통과하는데 시뮬에서만 겹치는 전형적인 모습이다.

        원인은 대개 둘 중 하나다.
          * 씬을 만든 seed/pitch/map 과 계획을 돌린 값이 다르다
          * pose 를 읽는 규약이 다르다 (쿼터니언 순서, prim 원점 오프셋)

        yaw 만 크게 어긋나면 쿼터니언 순서를, 위치까지 어긋나면 씬 빌드를
        의심한다. 조용히 달리기 전에 여기서 멈추는 편이 훨씬 싸다.
        """
        if self.starts is None:
            raise ValueError("starts 가 없다 — FleetController(..., starts=history[0])")
        bad = []
        for a in self.agents:
            if a not in self.starts:
                bad.append(f"agent{a}: 계획에 시작 상태가 없다")
                continue
            ex, ey, eyaw = self.g.state_pose(self.starts[a])
            gx, gy, gyaw = self.drivers[a].axle_pose()
            dp = math.hypot(gx - ex, gy - ey)
            dy = abs(wrap(gyaw - eyaw))
            if dp > pos_tol or dy > yaw_tol:
                bad.append(
                    f"agent{a} {self.starts[a]}: 계획 ({ex:.2f}, {ey:.2f}, "
                    f"{math.degrees(eyaw):.0f}deg) vs 실제 ({gx:.2f}, {gy:.2f}, "
                    f"{math.degrees(wrap(gyaw)):.0f}deg)  위치오차 {dp:.2f} m, "
                    f"방향오차 {math.degrees(dy):.0f}deg")
        if not bad:
            return
        yaw_only = all("위치오차 0.0" in b or
                       float(b.split("위치오차 ")[1].split(" m")[0]) <= pos_tol
                       for b in bad if "위치오차" in b)
        hint = ("방향만 어긋난다 -> 쿼터니언 순서를 의심하라 "
                "(DifferentialDriver(quat_order=...), Isaac 은 'wxyz')"
                if yaw_only else
                "위치까지 어긋난다 -> 씬을 계획과 같은 seed/pitch/map 으로 다시 빌드하라")
        raise RuntimeError(
            f"시작 pose 가 계획과 다르다 ({len(bad)}/{len(self.agents)}대). {hint}\n  "
            + "\n  ".join(bad[:6]))

    # ---- 장애물 훅 (3단계) -------------------------------------------------

    def report_obstacle(self, cells: Iterable[Cell]) -> None:
        """라이더가 맵에 없는 장애물을 봤을 때.

        ★ 로봇이 스스로 비켜가면 안 된다 — 예약하지 않은 칸에 들어가는 순간
        ADG 보장이 깨진다. 올바른 반응은 정지 + 보고 + 플릿 재계획이다.
        여기서는 해당 칸을 막고 정지시킨다. 재계획은 호출자가 pibt_core를 다시
        돌려 새 ADG를 만들어 교체한다.
        """
        self.rt.blocked_cells |= set(cells)

    def clear_obstacle(self, cells: Iterable[Cell]) -> None:
        self.rt.blocked_cells -= set(cells)

    # ---- 루프 --------------------------------------------------------------

    # [patch_carry]
    @staticmethod
    def _same_dir(p: Action, q: Action) -> bool:
        """q 가 p 에 이어지는 **같은 방향 직진**인가."""
        if q.kind != MOVE or p.kind != MOVE:
            return False
        if q.frm[2] != p.to[2]:                          # 헤딩이 바뀐다
            return False
        return ((p.to[0] - p.frm[0], p.to[1] - p.frm[1])
                == (q.to[0] - q.frm[0], q.to[1] - q.frm[1]))

    def _why_stuck(self, a, act, pose, c) -> str:
        """왜 안 끝나는지 **한 번에 갈리도록** 찍는다 (-224).

        2026-09-16 에 agent6 이 `turn(46,50,3)->(46,50,0)` 에서 영구 교착했는데
        로그에 `pose` 하나뿐이라 원인을 좁히는 데 주행이 세 판 들었다. 그때
        알고 싶었던 것을 전부 넣는다:

            err       0 에 가까운데 안 끝나면 각도가 아니라 **몸이 안 빠진 것**
            w         0 이면 컨트롤러가 손을 놓은 것. 나오는데 안 돌면 **물리**
            축이탈    칸 중심에서 얼마나 벗어났나 (회전은 위치를 안 본다)
            남은 몸   `complete()` 의 둘째 조건이 무엇에 걸렸나
            선행      ADG 가 막고 있나 (-1 은 릴리스 바닥 대기)
        """
        x, y, yaw = pose
        err = math.degrees(wrap(c.tyaw - yaw))
        w = self._last_cmd.get(a, (float("nan"), float("nan")))[1]
        dx, dy = c.tx - x, c.ty - y
        try:
            mine = frozenset(self.g.footprint_cells(x, y, yaw))
        except Exception:
            mine = frozenset()
        rel = act.released or frozenset()
        left = sorted(mine & rel)
        try:
            pend = self.rt.blocking(act)
        except Exception:
            pend = "?"
        return (
            f"agent{a} {act} 가 {self.elapsed[a]:.0f}s 동안 완료되지 않음\n"
            f"       pose=({x:.3f}, {y:.3f}, {math.degrees(yaw):.1f}deg)"
            f"   목표=({c.tx:.3f}, {c.ty:.3f}, {math.degrees(c.tyaw):.1f}deg)\n"
            f"       err={err:+.1f}deg  w={w:+.3f}rad/s"
            f"  축이탈=({dx * 1000:+.0f}, {dy * 1000:+.0f})mm\n"
            f"       놓아줄 칸에 남은 몸={left or '없음'}"
            f"  (released={sorted(rel) or '없음'})\n"
            f"       선행 미완={pend}  (-1 = 릴리스 바닥 대기)")

    def _straight_run(self, a: int, act: Action) -> int:
        """`act` **다음**으로 이어지는 같은 방향 직진이 몇 칸인가.

        ★ 왜 필요한가 (2026-09-14). 예전에는 **다음 한 칸만** 봤다. 그러면
          회전 직전 칸에서 exit_v 가 0 이 되는데, 그 시점 속도에서 1.2 m 안에
          못 서면 오버슈트한다. 정지 거리 v^2/(2a) 는

              v 0.9 -> 0.51 m    v 1.2 -> 0.90 m    (칸 1.2 m 안, OK)
              v 1.6 -> 1.60 m    v 2.2 -> 3.03 m    (칸의 1.3~2.5배, 불가)

          이라, v_exec 를 1.6 이상으로 올리면 회전 앞에서 못 서고 되돌아오기를
          반복한다. 실측: v=2.2 에서 완주 0/2, 칸공유 400,262건,
          차체 최소거리 0.014 m. 도착 판정 경고로는 이걸 못 잡는다 —
          문제는 판정이 아니라 **제동 거리**다.
        """
        chain = self.rt.adg.chains[self.slot[a]]
        k, n = act.idx + 1, 0
        prev = act
        while k < len(chain) and self._same_dir(prev, chain[k]):
            n += 1
            prev = chain[k]
            k += 1
        return n

    def _carry(self, a: int, act: Action) -> float:
        """이 액션의 종단속도. 0 이면 목표 칸에서 완전히 선다.

        같은 방향 직진이 곧바로 이어질 때만 속도를 싣고, **다음 회전까지
        남은 거리 안에 설 수 있는 속도**로 제한한다. 회전 앞에서는 반드시
        0 이다 — 제자리 선회에 선속도를 들고 들어가면 칸을 벗어난다.
        """
        if self.carry_free <= 0.0 or act.kind != MOVE:
            return 0.0
        nxt = self.rt.after(self.slot[a])
        if nxt is None or not self._same_dir(act, nxt):
            return 0.0
        if not self.rt.can_follow(act, nxt):             # 아직 못 들어간다
            return 0.0
        if self.carry_fixed is not None:
            return self.carry_fixed
        # 장애물 보고가 있으면 `can_follow` 가 뒤집힐 수 있다 -> 안전한 상한.
        # 없으면 세 조건이 모두 단조라 뒤집히지 않는다 -> 순항 속도.
        cap = self.carry_safe if self.rt.blocked_cells else self.carry_free
        # 다음 회전까지 남은 직진 거리 안에 설 수 있어야 한다.
        run = self._straight_run(a, act) * self.g.pitch
        return min(cap, math.sqrt(2.0 * self.a_exec * run)) if run > 0.0 else 0.0

    def step(self, dt: float) -> None:
        self.stats.steps += 1
        self.stats.sim_time += dt
        self.rt.advance(dt)
        moved = False
        occ: dict[int, frozenset[Cell]] = {}
        poses: dict[int, tuple[float, float, float]] = {}

        for a in self.agents:
            drv = self.drivers[a]
            pose = drv.axle_pose()
            self._watch_open_loop(a, pose, dt)
            body = self.g.footprint_cells(*pose)         # 스텝당 로봇당 딱 한 번
            occ[a] = body
            poses[a] = pose
            act = self.running[a]

            if act is not None:
                c = self.ctrl[a]
                self.elapsed[a] += dt
                if c.complete(pose, body):
                    self.rt.complete(self.slot[a], act)
                    self.running[a] = None
                    self.elapsed[a] = 0.0
                    self.turn_best.pop(a, None)
                    self.turn_idle.pop(a, None)
                    self.stats.completed += 1
                    # [patch_carry] 속도를 실은 채 끝났으면 **같은 스텝에**
                    #   다음 액션을 시작한다. 예전에는 여기서 0 을 명령하고
                    #   다음 스텝에 시작해서, 감속과 별개로 한 스텝을 더 버렸다.
                    nxt = self.rt.pending(self.slot[a])
                    if (c.exit_v > 0.0 and nxt is not None
                            and self.rt.can_start(nxt)):
                        c.begin(nxt, keep_speed=True)
                        self.running[a] = nxt
                        self.stats.started += 1
                        self.stats.carried += 1
                        c.exit_v = self._carry(a, nxt)
                        cmd = c.update(pose, dt)
                        drv.command(*cmd)
                        self._last_cmd[a] = cmd
                    else:
                        drv.command(0.0, 0.0)
                        self._last_cmd[a] = (0.0, 0.0)
                else:
                    if act.kind == TURN:
                        # ★ 회전 정체 판정 (-224). |err| 가 줄고 있으면 느려도
                        #   진행 중이다. **안 줄면** 이상이다.
                        err = abs(wrap(c.tyaw - pose[2]))
                        best = self.turn_best.get(a)
                        if best is None or err < best - 1e-3:
                            self.turn_best[a] = err
                            self.turn_idle[a] = 0.0
                        else:
                            self.turn_idle[a] = self.turn_idle.get(a, 0.0) + dt
                    if self.elapsed[a] > self.action_timeout:
                        self.timeouts.append(self._why_stuck(a, act, pose, c))
                        self.elapsed[a] = 0.0
                    c.exit_v = self._carry(a, act)
                    cmd = c.update(pose, dt)
                    drv.command(*cmd)
                    self._last_cmd[a] = cmd
                    # ★ 회전이 `stall_timeout` 동안 한 번도 안 가까워지면 중단한다.
                    #   원인을 몰라도 여기서 끊어야 20분이 아니라 2분에 안다.
                    #   `PIBT_STALL_TIMEOUT=0` 이면 안 끊는다 — 오발동했을 때
                    #   코드를 안 고치고 주행을 살릴 구멍이다.
                    if (act.kind == TURN and self.stall_timeout > 0
                            and self.turn_idle.get(a, 0.0) > self.stall_timeout):
                        self.stall = self._why_stuck(a, act, pose, c)
                moved = True
                continue

            nxt = self.rt.pending(self.slot[a])
            if nxt is None:
                drv.command(0.0, 0.0)
                self._last_cmd[a] = (0.0, 0.0)
                continue
            if self.rt.can_start(nxt):
                self.ctrl[a].begin(nxt)
                self.running[a] = nxt
                self.elapsed[a] = 0.0
                self.stats.started += 1
                self.ctrl[a].exit_v = self._carry(a, nxt)
                cmd = self.ctrl[a].update(pose, dt)
                drv.command(*cmd)
                self._last_cmd[a] = cmd
                moved = True
            else:
                drv.command(0.0, 0.0)                    # 허가 대기 — 정지
                self._last_cmd[a] = (0.0, 0.0)

        if not moved:
            self.stats.stall_steps += 1
        if self.safety_check:
            self._check(occ, poses)

    def _watch_open_loop(self, a: int, pose: tuple[float, float, float],
                         dt: float, hold: float = 1.0) -> None:
        """★ 명령을 보내는데 pose 가 변하지 않으면 제어 루프가 끊긴 것이다.

        이 계층은 매 스텝 pose 를 읽어 오차를 줄이는 되먹임 제어다. pose 가
        갱신되지 않으면 오차가 그대로라 명령이 상한에 걸린 채 유지되고, 로봇은
        **일정한 속도로 영원히 돈다(또는 직진한다).** 수렴하지 않는다.

        영상에서 이렇게 보인다: 여러 대가 부호만 다른 **똑같은 각속도**로
        멈추지 않고 회전. 목표가 제각각인데 속도가 같다는 것이 단서다 — 오차에
        비례한 제어라면 속도가 제각각이어야 한다.

        Isaac 에서 흔한 원인 둘:
          * `SingleArticulation(path)` 의 path 가 실제 articulation root 가 아니라
            그것을 감싼 Xform 이다. 그 Xform 은 스폰 위치에 고정이라 pose 가
            영원히 그대로다.
          * 물리 스텝 콜백 안에서 USD 트랜스폼을 읽었다. USD 쓰기는 렌더 시점에
            일어나므로 물리 콜백에서는 낡거나 멈춘 값이 온다.
        """
        prev = self._last_pose.get(a)
        self._last_pose[a] = pose
        v, w = self._last_cmd.get(a, (0.0, 0.0))
        if prev is None or (abs(v) < 1e-3 and abs(w) < 1e-3):
            self._frozen[a] = 0
            return
        moved = (math.hypot(pose[0] - prev[0], pose[1] - prev[1]) > 1e-6
                 or abs(wrap(pose[2] - prev[2])) > 1e-6)
        if moved:
            self._frozen[a] = 0
            return
        self._frozen[a] += 1
        if self._frozen[a] * dt >= hold and not any(f"agent{a} " in m for m in self.open_loop):
            self.open_loop.append(
                f"agent{a} 에게 {hold:.0f}초 넘게 (v={v:+.2f}, w={w:+.2f}) 를 보냈는데 "
                f"pose 가 그대로다 ({pose[0]:.2f}, {pose[1]:.2f}, "
                f"{math.degrees(pose[2]):.0f}deg). 제어 루프가 끊겼다 — "
                f"articulation root prim 과 물리 콜백에서의 pose 읽기를 확인하라.")

    def _check(self, occ: dict[int, frozenset[Cell]],
               poses: dict[int, tuple[float, float, float]] | None = None) -> None:
        """실제 차체 점유가 겹치는지 매 스텝 검사.

        ADG가 맞다면 절대 발동하지 않는다. 발동하면 브리지 버그이고, 물리
        시뮬에서 눈으로 찾는 것보다 여기서 잡는 게 훨씬 싸다.

        ★ **칸 공유는 접촉이 아니다.** 이 검사는 일부러 보수적인 감시선이라
          차체가 닿기 한참 전에 운다. 그래서 첫 건에 한해 자세와 **차체 사이
          최소 거리**를 같이 남긴다 — 그 숫자가 있어야 "감시선이 보수적으로
          운 것" 과 "진짜 접촉" 을 구별할 수 있다. 없으면 30분짜리 재현을
          다시 돌려야 한다 (2026-09-13, 쌍 7-8 에서 실제로 그랬다).
        """
        ags = self.agents
        for i, a in enumerate(ags):
            oa = occ[a]
            for b in ags[i + 1:]:
                shared = oa & occ[b]
                if shared:
                    self.stats.overlap_events += 1
                    self.stats.overlap_pairs.add((a, b))
                    self.stats.worst_overlap = max(self.stats.worst_overlap, len(shared))
                    if poses:
                        gap = self.g.body_gap(poses[a], poses[b])
                        self.stats.worst_gap = min(self.stats.worst_gap, gap)
                        if gap <= 0.0:                 # 실제 접촉만 합불에 넣는다
                            self.stats.contact_events += 1
                        # **쌍마다 첫 건만** 찍는다. 물리 60 Hz 라 매 스텝 찍으면
                        # 로그가 수천 줄이 되고, 반대로 전체 첫 건만 찍으면
                        # 뒤에 난 다른 쌍의 정보를 통째로 잃는다.
                        if (a, b) not in self._reported:
                            self._reported.add((a, b))
                            self._report_overlap(a, b, shared, poses, gap)

    def _report_overlap(self, a, b, shared, poses, gap) -> None:
        """쌍마다 첫 겹침의 자세·거리·심각도. 이 숫자로 접촉 여부가 판정된다."""
        try:
            pa, pb = poses[a], poses[b]
            say = getattr(self, "_say", print)
            if gap <= 0.0:
                tag = "★★ 실제 접촉 — 물리적으로 닿았다. 브리지 버그"
            elif gap < CONTACT_NEAR:
                tag = f"★ 근접 — {CONTACT_NEAR:.2f} m 안까지 붙었다. 확인 필요"
            else:
                tag = "⚠ 접촉 아님 — 칸만 공유했다 (감시선이 보수적)"
            say(f"겹침 상세  쌍 ({a},{b})  공유칸 {sorted(shared)}  →  {tag}")
            for who, p in ((a, pa), (b, pb)):
                say(f"   agent{who} pose ({p[0]:.3f}, {p[1]:.3f}, "
                    f"{math.degrees(p[2]):.1f}도)")
            say(f"   차체 최소거리 {gap:.3f} m   축 사이 "
                f"{math.hypot(pb[0] - pa[0], pb[1] - pa[1]):.3f} m")
        except Exception as e:                     # 진단이 주행을 죽이면 안 된다
            print(f"[adg] 겹침 상세 실패(주행은 계속): {e!r}")

    def diagnose(self) -> str:
        """정지했을 때 왜 멈췄는지."""
        lines = []
        for a in self.agents:
            nxt = self.rt.pending(self.slot[a])
            if self.running[a] is not None:
                lines.append(f"  agent{a} 실행중 {self.running[a]}")
            elif nxt is None:
                lines.append(f"  agent{a} 완료")
            else:
                blk = self.rt.blocking(nxt)
                owners = {u: ac.agent for ch in self.rt.adg.chains for ac in ch
                          if (u := ac.uid) in blk}
                lines.append(f"  agent{a} 대기 {nxt}  선행 미완 {len(blk)}건 "
                             f"-> agents {sorted(set(owners.values()))}")
        return "\n".join(lines)

    @property
    def finished(self) -> bool:
        return self.rt.finished


def make_kinematic_drivers(geom: RobotGeom, start: dict[int, State], seed: int = 0,
                           slip: float = 0.10, lag: float = 0.15,
                           pose_lag: float = 0.0,
                           ) -> dict[int, KinematicDriver]:
    rng = random.Random(seed)
    out = {}
    for a, s in start.items():
        x, y, yaw = geom.state_pose(s)
        out[a] = KinematicDriver(x, y, yaw, random.Random(rng.random() * 1e9),
                                 slip=slip, lag=lag, pose_lag=pose_lag)
    return out


# ===========================================================================
# SECTION 7 — Isaac Sim 없이 도는 검증
# ===========================================================================


def demo_map(H: int = 25, W: int = 29, rack_h: int = 5, rack_w: int = 2,
             aisle: int = 3, border: int = 4) -> np.ndarray:
    """랙 사이 통로가 있는 창고. free[r, c] = True면 주행 가능.

    통로 폭에 주의. 2칸 차체(`REAR_CELLS = 1`)에서 폭 2 통로는 사실상 단일
    차선이고, 양 끝에 목표를 가진 두 로봇이 영구 진동한다 — pibt_core의
    docstring이 말하는 PIBT one-shot 불완전성이다. 통로 3칸이 최소선이다.
    """
    free = np.ones((H, W), dtype=bool)
    free[0, :] = free[-1, :] = free[:, 0] = free[:, -1] = False
    r = border
    while r + rack_h <= H - border:
        c = border
        while c + rack_w <= W - border:
            free[r:r + rack_h, c:c + rack_w] = False
            c += rack_w + aisle
        r += rack_h + aisle
    return free


def pick_states(free: np.ndarray, n: int, seed: int = 0
                ) -> tuple[dict[int, State], dict[int, Cell]]:
    """valid한 시작 상태와 목표를, 점유가 겹치지 않게 고른다."""
    from pibt_core import valid_state
    rng = random.Random(seed)
    cells = [(r, c) for r in range(free.shape[0]) for c in range(free.shape[1])
             if free[r, c]]
    rng.shuffle(cells)
    starts: dict[int, State] = {}
    used: set[Cell] = set()
    for cell in cells:
        if len(starts) == n:
            break
        for h in rng.sample(range(4), 4):
            s = (cell[0], cell[1], h)
            if not valid_state(free, s):
                continue
            occ = set(occupied(s))
            if occ & used:
                continue
            starts[len(starts)] = s
            used |= occ
            break
    if len(starts) < n:
        raise RuntimeError(f"{n}대를 배치할 수 없음 (배치 {len(starts)}대)")
    free_cells = [c for c in cells if c not in used]
    rng.shuffle(free_cells)
    goals = {a: free_cells[i % len(free_cells)] for i, a in enumerate(starts)}
    return starts, goals


def sweep_audit(geom: RobotGeom, history, cells_hist) -> dict:
    """pibt_core의 예약 칸 vs 실제 스윕 — 어디서 모자라는가.

    `run_h`는 틱 동기다: 틱 t와 t+1의 점유만 겹치지 않으면 이산 모델에서는
    충돌이 없다. 연속 실행에서는 그 사이 시각이 존재하고, 전진 중에는 꼬리가
    아직 이전 칸에 있는 동안 앞단이 다음 칸에 들어간다. 예약이 그 순간을
    포함하지 않으면 후속 로봇이 정당하게(이산 기준) 그 칸을 얻는다.

    이 함수는 그 차이를 셈으로써, ADG를 `cells_hist`가 아니라 실제 스윕으로
    지어야 하는 이유를 수치로 보여 준다.
    """
    short = 0
    total = 0
    missing: dict[str, int] = {}
    examples: list[str] = []
    for t in range(len(cells_hist)):
        for a, reserved in cells_hist[t].items():
            s0, s1 = history[t][a], history[t + 1][a]
            kind = classify(s0, s1)
            real = geom.swept_cells(s0, s1)
            total += 1
            extra = real - frozenset(reserved)
            if extra:
                short += 1
                missing[kind] = missing.get(kind, 0) + 1
                if len(examples) < 4:
                    examples.append(
                        f"t={t} agent{a} {kind} {s0}->{s1}: 예약 "
                        f"{sorted(reserved)} / 실제 {sorted(real)} / 누락 {sorted(extra)}")
    return {"total": total, "short": short, "by_kind": missing, "examples": examples}


def selftest(geom: RobotGeom, n_agents: int = 12, max_steps: int = 960,
             dt: float = 1.0 / 60.0, seeds: int = 4, verbose: bool = True) -> bool:
    say = print if verbose else (lambda *a, **k: None)
    ok = True
    fails: list[str] = []

    def check(cond, label):
        nonlocal ok
        if cond:
            say(f"    OK    {label}")
        else:
            ok = False
            fails.append(label)
            say(f"    FAIL  {label}")

    say("\n[1] 기하 모델 정합성")
    say(f"    피벗: {geom.pivot_name}  (heading_offset={geom.heading_offset})")
    a = geom.audit()
    check(a["rest_matches"],
          "정지 점유가 pibt_core의 occupied(s)와 일치 "
          "(불일치면 heading_offset을 0/2로 바꿀 것 — 플랜이 무효해진다)")
    # [patch_axle] 아래 셋은 **swing 3칸 모델이 성립하는가**를 묻는다. 축 규칙은
    #   그 모델을 의도적으로 확장하므로 켠 상태에서는 전부 실패한다 (pitch 1.0
    #   에서 0.559 > 0.500, 1.1173 > 1.00, turn_extra 비어 있지 않음).
    #   그래서 스위치로 분기한다. 끈 쪽이 **오늘 경로**이고 §7 항목 1 이 이걸
    #   지킨다 — 한 줄도 바꾸지 않는다.
    if not geom.front_swing:
        check(a["short_stays_home"], "짧은 쪽이 자기 칸에 머묾 (swing 3칸 모델의 전제)")
        check(a["in_window"],
              f"pitch가 유효 구간 안 ({a['pitch_lo']:.2f} < {geom.pitch:.2f} < {a['pitch_hi']:.2f})")
        check(a["turn_covered"], "회전 스윕이 pibt_core의 swing 모델 안에 들어감")
    else:
        # ★ **휴면 상태다.** `front_cells()` 본체가 없어 껍데기가 raise 하므로
        #   이 분기는 지금 못 탄다 (켜면 build_adg 진입에서 먼저 죽는다).
        #   본체가 들어오면 여기가 §7 항목 2 의 관문이 된다 — "soft 가 비었나"
        #   가 아니라 **`front_cells()` 와 `swept_cells()` 가 같은 기하를 보는가**
        #   를 직접 묻는 것이라 항목 2 보다 강하다.
        turn = geom.swept_cells((5, 5, 1), (5, 5, 0))
        guard = geom.front_cells((5, 5, 1), (5, 5, 0))
        # ★ 비교 대상은 `guard` 전체가 아니라 `guard & turn` 이다.
        #   규칙이 내놓는 칸 중 일부는 **실제 스윕 밖**이다 — pitch 1.0 에서
        #   섞임 대각 mA/mB 가 0/8 로 스윕 밖이고, 0.80 에서야 7/8 로 들어온다.
        #   `guard == turn_extra` 를 물으면 4칸 규칙에서 반드시 실패한다.
        check(frozenset(a["turn_extra"]) == (guard & turn),
              "모델 초과분이 정확히 front_cells & 실제스윕 과 같음 "
              f"(초과 {sorted(a['turn_extra'])}  guard {sorted(guard)})")
        # 스윕 밖 칸은 hard 에서 뺄 것이 없으니 안전엔 무해하지만, 규칙 ② 는
        # 그 칸도 집행해야 한다. 그래서 `guard - turn` 이 비어도 안 비어도 통과다.
        check(not (guard & (set(occupied((5, 5, 1))) | set(occupied((5, 5, 0)))
                            | set(swing_cells(5, 5, 1, 0)))),
              "front_cells 에 몸 칸이 없음 (뒤 대각이 들어오면 여기서 걸린다)")
        check(a["rest_matches"], "축 규칙에서도 정지 점유는 2칸이어야 한다")

    free = demo_map()
    say("\n[2] 플랜 + ADG")
    all_clean = 0
    runs = 0
    for sd in range(seeds):
        starts, goals = pick_states(free, n_agents, seed=sd)
        try:
            history, cells_hist = run_h(free, starts, goals, max_steps=max_steps)
        except SystemExit as e:
            check(False, f"seed {sd}: run_h 정체 ({e})")
            continue
        chains, order, stats = extract_actions(history, geom)
        adg = build_adg(chains)
        check(adg.topological_order() is not None, f"seed {sd}: ADG 비순환")

        say(f"\n[3] 주행 (seed {sd}, {n_agents}대, slip/lag 주입)")
        for run_seed in range(2):
            drivers = make_kinematic_drivers(geom, starts, seed=run_seed * 7 + sd)
            fleet = FleetController(geom, adg, drivers, order=order)
            limit = 200000
            for _ in range(limit):
                fleet.step(dt)
                for d in drivers.values():
                    d.integrate(dt)
                if fleet.finished:
                    break
            runs += 1
            clean = fleet.stats.clean and fleet.finished
            all_clean += clean
            if not clean:
                say(f"    seed {sd}/{run_seed}: 접촉 {fleet.stats.contact_events}건 "
                    f"(칸 공유 {fleet.stats.overlap_events}건 · 최소 간격 "
                    f"{fleet.stats.worst_gap:.3f} m), "
                    f"완주 {fleet.finished}, 액션 {fleet.stats.completed}/"
                    f"{len(adg.actions)}")
                if not fleet.finished:
                    say(fleet.diagnose())
    check(runs > 0, f"주행이 최소 한 번은 실행됨 ({runs}회)")
    check(all_clean == runs and runs > 0, f"모든 주행이 무충돌 완주 ({all_clean}/{runs})")

    say("\n[4] 예약 칸 감사")
    aud = {"total": 0, "short": 0, "by_kind": {}, "examples": []}
    for sd in range(seeds):
        try:
            starts, goals = pick_states(free, n_agents, seed=sd)
            history, cells_hist = run_h(free, starts, goals, max_steps=max_steps)
        except (SystemExit, RuntimeError):
            continue
        aud = sweep_audit(geom, history, cells_hist)
        break
    say(f"    전이 {aud['total']}건 중 예약이 실제 스윕보다 작은 것: "
        f"{aud['short']}건 {aud['by_kind']}")
    for ex in aud["examples"]:
        say(f"      {ex}")
    check(True, "감사 실행됨 (누락이 있어도 ADG는 실제 스윕으로 지으므로 안전)")

    say("\n[5] 완료 판정이 '목표 도달'보다 엄격한지")
    ctrl = MotionController(geom)
    s0, s1 = (5, 5, 1), (5, 6, 1)
    act = Action(0, 0, MOVE, 0, s0, s1, geom.swept_cells(s0, s1), uid=0)
    ctrl.begin(act)
    target = geom.state_pose(s1)
    say(f"    액션 {act}: 스윕 {sorted(act.cells)} / 유지 {sorted(act.rest)} "
        f"/ 놓아줌 {sorted(act.released)}")
    check(ctrl.complete(target), "정확한 목표 pose에서는 완료")
    check(ctrl.at_target(target), "정확한 목표 pose는 at_target")
    # 판정 로직 자체: 목표에 도달했어도 차체가 놓아줄 칸에 남아 있으면 미완료.
    dirty = frozenset(act.rest | {next(iter(act.released))})
    check(not ctrl.complete(target, dirty),
          "at_target이어도 차체가 놓아줄 칸에 걸쳐 있으면 미완료")
    check(ctrl.complete(target, frozenset(act.rest)),
          "놓아줄 칸에서 빠져나오면 완료")

    # [patch_axle] pitch 별 **표**. 검사가 아니라 기록이다.
    #
    #   축 규칙의 하한은 수식으로 안 닫힌다. "차체가 3×3 을 안 벗어나는" 조건
    #   (2*hypot(rear, W/2) < 3*pitch) 과 "모델이 성립하는" 조건은 다른 양이다 —
    #   `swing_cells` 는 3×3 이 아니라 **3칸**만 예약한다. 그래서 계산하지 말고
    #   **재서** 구간을 얻는다.
    #
    #   ★ `in_window` 가 False 여도 `continue` 하지 않는다. 건너뛰면 pitch 1.0
    #     행이 아예 안 나오는데, 그 행의 `turn_extra` 가 본체 도입 후
    #     `front_cells` 와 대조할 **기준값**이다.
    say("    pitch 별 모델 초과 칸 (turn_extra) — 축 규칙 하한의 측정 기준:")
    for p in (0.80, 0.90, 1.00, 1.10, 1.20, 1.60, 2.00):
        g2 = RobotGeom(pitch=p, rear_len=geom.rear_len, front_len=geom.front_len,
                       width=geom.width, heading_offset=geom.heading_offset)
        a2d = g2.audit()
        say(f"      pitch {p:.2f} m : 구간안 {str(a2d['in_window']):<5} "
            f"초과 {sorted(a2d['turn_extra'])}")

    say("    '꼬리 남음'이 전진에서 실제로 구속력을 갖는가:")
    for p in (0.90, 1.20, 1.60, 2.00):
        g2 = RobotGeom(pitch=p, rear_len=geom.rear_len, front_len=geom.front_len,
                       width=geom.width, heading_offset=geom.heading_offset)
        if not g2.audit()["in_window"]:
            say(f"      pitch {p:.2f} m : 모델 유효 구간 밖")
            continue
        a2 = Action(0, 0, MOVE, 0, (5, 5, 1), (5, 6, 1),
                    g2.swept_cells((5, 5, 1), (5, 6, 1)), uid=0)
        c2 = MotionController(g2)
        c2.begin(a2)
        # 목표 허용 반경 안에서 가장 뒤쪽인 pose
        tx, ty, tyaw = g2.state_pose((5, 6, 1))
        worst = (tx - c2.tol.pos, ty, tyaw)
        binding = bool(g2.footprint_cells(*worst) & a2.released)
        say(f"      pitch {p:.2f} m : 놓아줄 칸 {sorted(a2.released)}  "
            f"허용오차 끝에서 걸침 {binding}")

    say("\n[6] 예약 칸으로 ADG를 지으면 어떻게 되는가")
    say("    같은 플랜, 같은 주행. ADG의 근거만 바꾼다.")
    res: dict[str, list[int]] = {"real": [0, 0], "reserved": [0, 0]}
    for sd in range(seeds):
        try:
            starts, goals = pick_states(free, n_agents, seed=sd)
            history, cells_hist = run_h(free, starts, goals, max_steps=max_steps)
        except (SystemExit, RuntimeError):
            continue
        for mode in ("real", "reserved"):
            chains, order, _ = extract_actions(history, geom)
            if mode == "reserved":
                for i, a in enumerate(order):
                    for act in chains[i]:
                        act.cells = frozenset(cells_hist[act.tick][a])
            adg2 = build_adg(chains)
            drivers = make_kinematic_drivers(geom, starts, seed=sd)
            fl = FleetController(geom, adg2, drivers, order=order)
            # 'reserved'는 완주하지 못하므로(예약이 모순이라 멈춘다) 상한을 둔다.
            # 겹침은 초반에 바로 나오므로 이 예산으로 충분하다.
            for _ in range(20000):
                fl.step(dt)
                for d in drivers.values():
                    d.integrate(dt)
                if fl.finished:
                    break
            res[mode][0] += 1
            res[mode][1] += fl.stats.overlap_events
    say(f"      {'ADG의 근거':<28}{'주행':>5}{'차체 겹침':>12}")
    for m, label in (("real", "실제 스윕 swept_cells"),
                     ("reserved", "예약 칸 cells_hist")):
        say(f"      {label:<28}{res[m][0]:>5}{res[m][1]:>12}")
    check(res["real"][1] == 0, "실제 스윕으로 지은 ADG는 무충돌")
    check(res["reserved"][1] > 0,
          "예약 칸으로 지은 ADG는 실제로 충돌한다 (그래서 swept_cells를 쓴다)")

    if fails:
        say("\n  실패 항목:")
        for f in fails:
            say(f"    - {f}")
    say(f"\n  결과: {'전부 통과' if ok else str(len(fails)) + '건 실패'}")
    return ok


# ===========================================================================
# SECTION 8 — Isaac Sim 진입점
# ===========================================================================


def plan_and_build(free: np.ndarray, starts: dict[int, State], goals: dict[int, Cell],
                   geom: RobotGeom, max_steps: int = 1600, **run_kw
                   ) -> tuple[ADG, list[int], list[dict[int, State]], dict]:
    """pibt_core로 계획하고 ADG까지 만든다. Isaac Sim 쪽에서 부를 함수.

    ADG가 순환이면 여기서 예외가 난다 — 주행을 시작하기 **전에** 데드락이
    잡힌다는 것이 이 계층의 값이다.
    """
    history, cells_hist = run_h(free, starts, goals, max_steps=max_steps, **run_kw)
    chains, order, stats = extract_actions(history, geom)
    adg = build_adg(chains)
    if adg.topological_order() is None:
        raise RuntimeError("ADG에 순환이 있다 — 실행하면 데드락이다")
    return adg, order, history, {"actions": stats,
                                 "sweep": sweep_audit(geom, history, cells_hist)}


ISAAC_TEMPLATE = '''
# ---------------------------------------------------------------------------
# Isaac Sim 안에서 (2단계). 위 --selftest가 통과한 뒤에 붙일 것.
# ---------------------------------------------------------------------------
from isaac_drive import (RobotGeom, DifferentialDriver, FleetController,
                         plan_and_build)

geom = RobotGeom(
    pitch=1.20,                    # ★ 실제 격자 간격
    rear_len=1.03,                 # 구동축 -> 뒷면 (Isaac 실측)
    front_len=0.37,                # ★ 전장 - rear_len
    width=0.80,                    # ★
    v_max=0.90, w_max=2.07,
    origin=(0.0, 0.0),             # ★ 셀 (0,0) 중심의 world 좌표
    axle_in_prim=(0.0, 0.0),       # ★ prim 원점 -> 구동축 (usd_probe.py)
)
print(geom.describe())             # 별표 값이 맞는지 먼저 확인

adg, order, history, info = plan_and_build(free, starts, goals, geom)
print(adg.summary())

drivers = {}
for a, robot in robots.items():    # robots: wppl.py에서 쓰던 핸들
    drivers[a] = DifferentialDriver(
        geom,
        get_pose=lambda rb=robot: rb.get_world_pose(),
        set_wheel_vel=(lambda l, r, rb=robot: rb.apply_wheel_actions(
            ArticulationAction(joint_velocities=[l, r],
                               joint_indices=wheel_idx))),
        wheel_radius=0.125, wheel_base=0.50,   # ★ USD에서
    )

fleet = FleetController(geom, adg, drivers, order=order)
while simulation_app.is_running():
    world.step(render=True)
    fleet.step(world.get_physics_dt())
    if fleet.stats.contact_events:
        print("★ 차체 접촉 — 브리지 버그. 조용히 넘기지 말 것")
        print(fleet.diagnose())
        break
    if fleet.finished:
        break
'''
def plan_and_build_lifelong(free: np.ndarray, starts: dict[int, State],
                            cells_by_cat: dict, geom: RobotGeom,
                            horizon: int = 315, seed: int = 0,
                            order_gap: int = 15,
                            shifts=("in", "out", "out"),
                            battery: bool = False, docks=(),
                            battery_kw: dict | None = None,
                            dispatch: str = "fms", zone_cells=(),
                            order_end=None, **run_kw):
    """`lifelong.run_lifelong` 으로 계획하고 ADG 까지 만든다.

    `plan_and_build` 과 **같은 것**을 돌려준다. one-shot 과 달리 "전원이
    동시에 목표에 있어야 성공" 조건이 없으므로 `GOOD_SEEDS` 가 필요 없다.
    `extract_actions`·`build_adg`·`sweep_audit` 은 한 줄도 안 고친다 —
    lifelong 의 `history` 형식이 `run_h` 와 같기 때문이다.

    `zone_cells` 는 충전존 복귀 후보 칸이다 (`pibt_scene.charge_zone_cells`).
    비우면 FREED 가 시작 칸으로 돌아가는 이전 동작 그대로다.
    """
    from lifelong import run_lifelong

    kw = dict(run_kw)
    base, bkw = None, {}
    if battery:
        from battery import BatteryKernel
        base = BatteryKernel
        bkw = dict(docks=list(docks), pitch=geom.pitch, seed=seed)
        bkw.update(battery_kw or {})
    if dispatch != "fms":
        # 정책 교체는 서브클래스로만 한다 — lifelong.py 는 안 건드린다.
        from dispatch import with_policy
        from lifelong import Kernel
        base = with_policy(base or Kernel, dispatch)
    if base is not None:
        kw.update(kernel_cls=base, kernel_kw=bkw)

    history, cells_hist, li = run_lifelong(
        free, starts, cells_by_cat, horizon=horizon, seed=seed,
        order_gap=order_gap, shifts=shifts, zone_cells=zone_cells,
        order_end=order_end, **kw)

    # ★ 태스크 시작 틱을 넘긴다 (-211). 릴리스 바닥이 태스크 첫 동작에만
    #   걸리게 하려면 여기서 이어 줘야 한다 — 없으면 전부 False 가 되어
    #   바닥이 아예 안 걸린다 (그건 그것대로 틀리다: 주문 전 출발을 허용한다).
    chains, order, stats = extract_actions(history, geom,
                                           task_start=li.get("task_start"))
    adg = build_adg(chains)
    if adg.topological_order() is None:
        raise RuntimeError("ADG에 순환이 있다 — 실행하면 데드락이다")

    import metrics
    cp = metrics.critical_path(adg, geom)
    info = {"actions": stats,
            "sweep": sweep_audit(geom, history, cells_hist),
            "lifelong": li,
            "throughput": metrics.throughput(li["tasks_done"], horizon, geom,
                                             makespan=cp),
            "dispatch": dispatch}
    if battery:
        from battery import watchdog
        info["battery_warn"] = watchdog(li, strict=False)
    return adg, order, history, info



def main() -> int:
    ap = argparse.ArgumentParser(description="pibt_core 플랜의 Isaac Sim 주행 계층")
    ap.add_argument("--pitch", type=float, default=1.20, help="격자 간격 m")
    ap.add_argument("--pivot", choices=("rear_axle", "front_axle"), default="rear_axle",
                    help="회전 중심. rear_axle이면 차체가 앞으로 뻗고 "
                         "heading_offset=2 (pibt_core와 맞추는 라벨링)")
    ap.add_argument("--long", type=float, default=1.03,
                    help="피벗에서 먼 쪽 차체 길이 m (Isaac 실측 1.03)")
    ap.add_argument("--short", type=float, default=0.37,
                    help="피벗에서 가까운 쪽 차체 길이 m")
    ap.add_argument("--width", type=float, default=0.80)
    ap.add_argument("--agents", type=int, default=12)
    ap.add_argument("--seeds", type=int, default=4)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--sweep-audit", action="store_true")
    ap.add_argument("--template", action="store_true", help="Isaac Sim 붙이는 코드 출력")
    args = ap.parse_args()

    rear_pivot = args.pivot == "rear_axle"
    geom = RobotGeom(
        pitch=args.pitch,
        rear_len=args.short if rear_pivot else args.long,
        front_len=args.long if rear_pivot else args.short,
        width=args.width,
        heading_offset=2 if rear_pivot else 0,
    )

    if args.template:
        print(ISAAC_TEMPLATE)
        return 0

    print("=" * 74)
    print("기하")
    print("=" * 74)
    print(geom.describe())

    if args.sweep_audit:
        free = demo_map()
        starts, goals = pick_states(free, args.agents, seed=0)
        history, cells_hist = run_h(free, starts, goals, max_steps=600)
        aud = sweep_audit(geom, history, cells_hist)
        print("\n" + "=" * 74)
        print("예약 칸 감사 — pibt_core의 cells_hist vs 실제 스윕")
        print("=" * 74)
        print(f"전이 {aud['total']}건 중 예약 < 실제: {aud['short']}건  {aud['by_kind']}")
        for ex in aud["examples"]:
            print("  " + ex)
        print("\n틱 동기 모델에서는 문제가 아니지만, 연속 실행에서는 그 순간에")
        print("후속 로봇이 칸을 얻을 수 있다. 그래서 ADG는 cells_hist가 아니라")
        print("swept_cells()로 짓는다.")
        return 0

    print("\n" + "=" * 74)
    print(f"검증 ({args.agents}대, seed {args.seeds}개, Isaac Sim 없음)")
    print("=" * 74)
    return 0 if selftest(geom, n_agents=args.agents, seeds=args.seeds) else 1


if __name__ == "__main__":
    raise SystemExit(main())
