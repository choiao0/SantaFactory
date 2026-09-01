"""A안(AI)-B안(PIBT 엔진) 공유 계약.

출처: 5_Docs/AI/AI입출력명세서.md §13. 이 파일을 바꾸려면 양쪽 합의가 먼저다.
"""

from dataclasses import dataclass

import numpy as np


@dataclass
class GuidanceInput:
    """AI가 받는 것."""

    static_map: np.ndarray       # (18, H, W) float32 — 창고 생김새
    task_profile: np.ndarray     # ( 6, H, W) float32 — 짐 흐름
    topology_tensor: np.ndarray  # (15, H, W) float32 — 통로 구조
    scenario: np.ndarray         # ( 9,)      float32 — 운영 조건


@dataclass
class GuidanceTheta:
    """AI가 내놓는 것 — 통행 규칙 파라미터 θ 11개."""

    # 연속 파라미터 8개
    aisle_alt_gain: float    # 1.0 ~ 3.5 — 통로 역주행 벌금
    aisle_alt_boost: float   # 0.4 ~ 1.0 — 통로 순방향 할인
    loop_gain: float         # 1.0 ~ 3.0 — 외곽 순환 강제 세기
    main_aisle_gain: float   # 0.5 ~ 1.2 — 큰 통로 할인
    junction_penalty: float  # 1.0 ~ 3.0 — 교차로 진입 벌금
    station_in: float        # 0.4 ~ 1.0 — 작업자리 접근 할인
    station_out: float       # 1.0 ~ 3.0 — 작업자리 역방향 벌금
    wait_cost: float         # 0.5 ~ 3.0 — 기다리는 비용

    # 범주형 파라미터 3개
    aisle_period: int  # 1, 2, 3 중 하나 — 몇 통로마다 방향을 뒤집을지
    aisle_phase: int   # 0 또는 1 — 첫 통로를 북쪽으로 할지 남쪽으로 할지
    loop_dir: int      # 0=시계, 1=반시계


@dataclass
class Guidance:
    """from_theta()가 내놓는 것 — 칸별 통행 비용."""

    edge_cost: np.ndarray  # (H, W, 4) float32 — 방향별 비용 (북·동·남·서), 범위 0.5~5.0
    wait_cost: np.ndarray  # (H, W)    float32 — 제자리 대기 비용, 범위 0.5~5.0
