"""sim_engine 커널 어댑터 — FmsKernel + OrderStream 을 Planner 프로토콜로 감싼다 (sim_engine 은 한 줄도 바꾸지 않는다).

sim_v2_tasks.build() 와 같은 순서로 맵·비용·주문 스트림·커널을 만들고, 틱마다 CLI 셸과 같은 순서
(arrivals → submit → dispatch → move, docs/커널_시뮬_구조.md)로 부른 뒤 로봇 (pos, h) 의 전후 차이를 Command 로 낸다.
홈은 DES 의 충전 존 배치(make_homes_zone)가 아니라 실 로봇의 첫 포즈 칸 — DES 와 같은 배치를 원하면 Isaac spawn 을
des_homes() 로 만든다(`python3 -m fms_core --spawn N`). sim_engine 은 평면 import(map_loader …)라 sys.path 에 올린다.
"""
from __future__ import annotations

import os
import sys

import numpy as np

from . import kpi as K
from .planner import Command, PlannerSpec, RobotView
from .scenario import scenario_orders, stream_options
from .world import JUMP, WAIT, move_kind

FMS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))          # 3_FMS (map · contracts 의 형제)
SIM_ENGINE_DIR = os.environ.get("SIM_ENGINE_DIR") or os.path.join(FMS_DIR, "sim_engine")
MAX_TICKS = 199_000              # 커널 move() 의 틱 상한(200,000) 아래 — 한 런은 그보다 훨씬 짧다
SERVICE_TIME_S = 40 / 11         # sim_v2_tasks.SERVICE_TIME_S 와 같은 값 (그 모듈은 matplotlib 을 끌어와 import 하지 않는다)
DEFAULT_ORDER_GAP = 50           # 명시 주문 모드에서는 입고 간격 기본값으로만 쓰인다 (sim_v2 기본 50)
EVENT_TYPES = ("task_assigned", "task_done", "order_shipped", "stall")


def ensure_sim_engine() -> str:
    if SIM_ENGINE_DIR not in sys.path:
        sys.path.insert(0, SIM_ENGINE_DIR)
    return SIM_ENGINE_DIR


def des_homes(n_robots: int, aisle_block: bool = False) -> list:
    """DES 견적과 같은 초기 배치(충전 존, 간격 2) — Isaac spawn 문자열을 만들 때 쓴다."""
    ensure_sim_engine()
    from map_loader import load_charge_zone, load_map, make_homes, make_homes_zone
    free, st_cell, _ = load_map(aisle_block=aisle_block)
    zone = load_charge_zone(free)
    if zone is None:
        return make_homes(free, st_cell, n_robots)
    return make_homes_zone(free, zone & free, n_robots)


class KernelPlanner:
    """Planner 구현: 커널 상태가 진실이고 셸이 실 로봇을 거기에 맞춘다."""

    def __init__(self, spec: PlannerSpec):
        ensure_sim_engine()
        from cli.common import DT
        from fms_kernel import FmsKernel, KernelConfig
        from map_loader import load_charge_zone, load_map, load_rack_map
        from order_stream import OrderStream
        from pibt_core import TURN_TICKS

        opts = spec.options
        free, st_cell, stations = load_map(aisle_block=bool(opts.get("aisle_block", False)))
        _validate_homes(free, spec.homes, spec.n_robots)
        zone_mask = load_charge_zone(free)
        zone = zone_mask is not None and not opts.get("fixed_homes", False)
        zone_mask = (zone_mask & free) if zone else None
        edge_cost, wait_cost = _costs(free, st_cell, opts.get("theta_path"))
        rack_map = load_rack_map()
        if not rack_map:
            raise RuntimeError("map/rack_buffers.json 없음 — 명시 주문을 픽업 지점으로 바꿀 수 없다")
        so = stream_options(spec.scenario)
        orders = scenario_orders(spec.scenario)
        horizon = int(opts.get("horizon_ticks", MAX_TICKS))
        self.stream = OrderStream(np.random.default_rng(so["seed"]), "main", 0, float(opts.get("order_gap", DEFAULT_ORDER_GAP)),
                                  st_cell, stations, inbound_gap=so["inbound_gap"], horizon=horizon, shifts=so["shifts"],
                                  orders=orders, rack_map=rack_map, capacity=so["capacity"])
        cfg = KernelConfig(heading=True, zone=zone, theta=bool(opts.get("theta_path")), service_steps=round(SERVICE_TIME_S / DT),
                           turn_ticks=TURN_TICKS, stall_warn_only=True)
        self.kernel = FmsKernel(free, st_cell, edge_cost, wait_cost, list(spec.homes), spec.n_robots, cfg,
                                zone_mask=zone_mask, on_task_completed=self.stream.on_completed)
        self.n_robots = spec.n_robots
        self.warnings = list(self.kernel.warnings)
        self._events: list = []
        self._done_seen = 0
        self._stall_seen = 0
        self._assigned: dict = {}          # task id → rid (task_done 이벤트의 로봇)
        self._shipped: set = set()

    # ---- Planner 프로토콜 ---------------------------------------------------------
    def robots(self) -> tuple:
        return tuple(RobotView(rid, tuple(rb["pos"]), int(rb["h"]), rb["state"], rb["task"]["id"] if rb["task"] else None)
                     for rid, rb in self.kernel.robots.items())

    def step(self, t: int) -> tuple:
        k, s = self.kernel, self.stream
        for task in s.arrivals(t):
            k.submit_task(task)
        k.dispatch(t)
        before = {rid: (rb["pos"][0], rb["pos"][1], rb["h"]) for rid, rb in k.robots.items()}
        k.move(t)
        cmds = []
        for rid in k.rids:
            rb = k.robots[rid]
            after = (rb["pos"][0], rb["pos"][1], rb["h"])
            kind = move_kind(before[rid], after)
            if kind == WAIT:
                continue
            if kind == JUMP:                    # 헤딩 모델은 한 틱에 한 칸·90° 뿐 — 그 밖은 실 로봇이 못 따라간다
                raise RuntimeError(f"robot {rid}: non-unit move {before[rid]} → {after}")
            cmds.append(Command(rid, kind, (after[0], after[1]), int(after[2])))
        self._collect_events(t)
        return tuple(cmds)

    def drain_events(self) -> list:
        out, self._events = self._events, []
        return out

    def counters(self) -> dict:
        k, s = self.kernel, self.stream
        done = len(k.tasks_done)
        return {"open_tasks": k.n_submitted - done, "done_tasks": done,
                "orders_done": sum(1 for od in s.orders.values() if od["completed"] is not None),
                "orders_total": int(s.n_orders)}

    def kpi(self, t_end: int) -> dict:
        return K.des_block(K.summary(self.kernel, self.stream, self.n_robots, t_end))

    # ---- 이벤트 ------------------------------------------------------------------
    def _collect_events(self, t: int) -> None:
        k, s = self.kernel, self.stream
        for rid, rb in k.robots.items():
            tk = rb["task"]
            if tk is not None and tk["assigned"] is not None and tk["id"] not in self._assigned:
                self._assigned[tk["id"]] = rid
                self._events.append(dict(type="task_assigned", order_id=tk["order"], task_id=tk["id"], rid=rid, tick=t))
        for tk in k.tasks_done[self._done_seen:]:
            self._events.append(dict(type="task_done", order_id=tk["order"], task_id=tk["id"],
                                     rid=self._assigned.get(tk["id"]), tick=t))
            oid = tk["order"]
            if oid is not None and oid not in self._shipped and s.orders[oid]["completed"] is not None:
                self._shipped.add(oid)
                self._events.append(dict(type="order_shipped", order_id=oid, task_id=None, rid=None, tick=t))
        self._done_seen = len(k.tasks_done)
        for st in k.stall_warning_ticks[self._stall_seen:]:
            self._events.append(dict(type="stall", order_id=None, task_id=None, rid=None, tick=int(st)))
        self._stall_seen = len(k.stall_warning_ticks)


def _validate_homes(free, homes: tuple, n_robots: int) -> None:
    if len(homes) != n_robots:
        raise ValueError(f"homes {len(homes)} != n_robots {n_robots}")
    H, W = free.shape
    seen: set = set()
    for rid, (r, c) in enumerate(homes):
        if not (0 <= r < H and 0 <= c < W) or not free[r, c]:
            raise ValueError(f"robot {rid}: home cell {(r, c)} is outside the map or blocked")
        if (r, c) in seen:
            raise ValueError(f"robot {rid}: home cell {(r, c)} shared with another robot")
        seen.add((r, c))


def _costs(free, st_cell, theta_path):
    H, W = free.shape
    if not theta_path:
        return np.ones((H, W, 4), dtype=np.float64), np.ones((H, W), dtype=np.float64)
    from from_theta import extract_topology, from_theta, load_theta
    g = from_theta(free, extract_topology(free, st_cell), load_theta(theta_path))
    return g.edge_cost.astype(np.float64), g.wait_cost.astype(np.float64)
