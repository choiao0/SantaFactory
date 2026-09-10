"""주행 로직 교체 지점 — Planner 프로토콜과 관측·명령 타입 (fms-core 의 유일한 알고리즘 경계).

셸(conductor)은 이 인터페이스만 본다: 틱마다 step(t) 를 부르고 돌아온 Command 를 VDA 5050 order 로 바꿔 보낸 뒤,
전 로봇이 도착하면 다음 틱을 부른다(틱 배리어). 로봇 위치의 진실은 플래너 쪽 모델이다 — 실 로봇은 명령한 칸 중심에
allowedDeviation(5 cm · 0.03 rad) 안으로 멈추므로 다음 틱의 시작 상태가 플래너 모델과 일치한다.
새 알고리즘 = 이 프로토콜을 만족하는 클래스 하나 + PLANNERS 등록 한 줄. sim_engine 커널은 kernel_planner 가 감싼다(무수정).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol

from .world import FORWARD, REVERSE, TURN, WAIT  # noqa: F401 — 명령 종류 재수출


@dataclass(frozen=True)
class PlannerSpec:
    """플래너 생성 입력. homes = 로봇 rid 순서의 시작 칸 (실 로봇의 첫 포즈에서 셸이 구한다)."""
    run_id: str
    n_robots: int
    homes: tuple                      # ((r, c), …) 길이 n_robots
    scenario: dict = field(default_factory=dict)      # SIM_VERIFY_CONTRACT §2 scenario (orders · seed · …)
    options: dict = field(default_factory=dict)       # 플래너별 옵션 (--planner-opt key=value)


@dataclass(frozen=True)
class RobotView:
    rid: int
    cell: tuple
    h: int
    status: str                       # 플래너 고유 상태 문자열 (커널: IDLE · TO_PICK · …)
    task_id: Optional[int] = None


@dataclass(frozen=True)
class Command:
    """틱 t 의 로봇 하나 명령: 이 틱이 끝났을 때 있어야 할 (cell, h). kind 는 world.move_kind 의 값."""
    rid: int
    kind: str
    cell: tuple
    h: int


class Planner(Protocol):
    n_robots: int

    def robots(self) -> tuple:
        """현재 로봇 관측 (RobotView 튜플, rid 순)."""

    def step(self, t: int) -> tuple:
        """틱 t 를 진행하고 이동·회전이 있는 로봇의 Command 튜플을 돌려준다 (대기·서비스 로봇은 생략)."""

    def drain_events(self) -> list:
        """마지막 호출 뒤 생긴 biz 이벤트 [{type, order_id, task_id, rid}] (MQTT_CONTRACT §4.4 type 집합)."""

    def counters(self) -> dict:
        """open_tasks · done_tasks · orders_done · orders_total (Sparkplug Fms/* 메트릭)."""

    def kpi(self, t_end: int) -> dict:
        """틱 t_end 까지의 KPI — DES 견적 워커 to_kpi 와 같은 14개 키 (SIM_VERIFY_CONTRACT §3 kpi)."""


def _kernel_factory(spec: PlannerSpec):
    from .kernel_planner import KernelPlanner       # sim_engine 은 여기서만 (numpy · 맵 로드)
    return KernelPlanner(spec)


PLANNERS: dict = {"kernel": _kernel_factory}       # 이름 → Callable[[PlannerSpec], Planner]


def build_planner(name: str, spec: PlannerSpec) -> Planner:
    try:
        factory: Callable[[PlannerSpec], Planner] = PLANNERS[name]
    except KeyError:
        raise ValueError(f"unknown planner {name!r} (known: {', '.join(sorted(PLANNERS))})") from None
    return factory(spec)
