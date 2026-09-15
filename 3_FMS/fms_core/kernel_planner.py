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
EVENT_TYPES = ("task_assigned", "task_done", "order_shipped", "stall")

# ---- DES 견적과 같은 조건 (S15P21A106-185) ------------------------------------------------
# 검증 런의 KPI 는 견적 KPI 와 비교하려고 내는 값이다. 아래 기본값이 견적 워커
# (infra/worker/estimate_worker.py + objective.run_once)와 어긋나면 그 비교가 무의미해진다.
# 값을 바꾸기 전에 fms_core/tests/test_des_parity.py 를 보라 — 워커 코드에서 기준을 읽어 대조한다.
DES_AISLE_BLOCK = True           # run_once(aisle_block=1) — 랙 내부 통로 칸을 막고 돈다
DES_SPEED = 0.9                  # 워커 SPEED_DEFAULT (무게 입력 없을 때 물리 계획 속도, -116). 틱 길이 dt = CELL_M / speed
DEFAULT_THETA = os.path.join(FMS_DIR, "infra", "out", "theta_wallA_r20_c6_v36.json")  # 워커 THETA_PATH 기본값
LANE_GAIN = POCKET_GAIN = 2.0    # 차선·주머니 비용 (sim_v2 --lane-gain/--pocket-gain 기본, v3 헤딩 main 기본 ON)


def des_dt(options: dict | None = None) -> float:
    """틱 길이 [초]. speed 는 `--planner-opt speed=`, 없으면 워커 기본 DES_SPEED (-116).

    커널의 초 환산(서비스·주문 도착·KPI)과 셸의 벽시계 틱(--tick-s 기본)이 같은 값을 보도록
    한 곳에 둔다. 공식은 **시뮬과 같은 상수를 읽어** 구한다 — v3.6(-194) 에서 1칸이
    MOVE_TICKS 틱이 되며 `CELL_M / speed` 가 MOVE_TICKS 배 틀린 값이 됐다. 그 값을 쓰면
    conductor 가 커널을 그만큼 느리게 돌려 런이 timeout_s 에 걸린다.
    """
    ensure_sim_engine()
    from map_loader import CELL_M
    from pibt_core import MOVE_TICKS
    return CELL_M / (float((options or {}).get("speed", DES_SPEED)) * MOVE_TICKS)


def theta_path(options: dict | None = None) -> str | None:
    """쓸 θ 파일 경로. 없으면 None = 중립 θ.

    기본값은 견적 워커와 같다 — 환경변수 `THETA_PATH`, 없으면 `infra/out/theta_wallA_r20_c6_v36.json`("" 이면 중립).
    한 런만 다르게 하려면 `--planner-opt theta_path=<경로>`(빈 문자열이면 중립).
    """
    if options and "theta_path" in options:
        path = options.get("theta_path")
    else:
        path = os.environ.get("THETA_PATH", DEFAULT_THETA)
    return str(path) if path else None


def ensure_sim_engine() -> str:
    if SIM_ENGINE_DIR not in sys.path:
        sys.path.insert(0, SIM_ENGINE_DIR)
    return SIM_ENGINE_DIR


def des_homes(n_robots: int, aisle_block: bool = DES_AISLE_BLOCK) -> list:
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
        from fms_kernel import FmsKernel, KernelConfig
        from map_loader import ROBOT_DIMS, load_charge_zone, load_map, load_rack_map, turn_mask
        from pibt.geometry import FOOTPRINT_MARGIN_M
        from order_stream import OrderStream
        from pibt_core import TURN_TICKS

        opts = spec.options
        # 속도 → 틱 길이 (-116, 계약 v3.3): 커널은 1칸 = 1틱 그대로, 초 단위 값(서비스·토트 서비스·KPI)만 dt 로 환산.
        self.dt = des_dt(opts)
        free, st_cell, stations = load_map(aisle_block=bool(opts.get("aisle_block", DES_AISLE_BLOCK)))
        _validate_homes(free, spec.homes, spec.n_robots)
        zone_mask = load_charge_zone(free)
        zone = zone_mask is not None and not opts.get("fixed_homes", False)
        zone_mask = (zone_mask & free) if zone else None
        lanes = bool(opts.get("lanes", True))
        yield_rule = bool(opts.get("yield_rule", True))
        theta_file, warnings = _theta_file(opts)
        edge_cost, wait_cost, lane_dir = _costs(free, st_cell, theta_file, lanes, yield_rule)
        rack_map = load_rack_map()
        if not rack_map:
            raise RuntimeError("map/rack_buffers.json 없음 — 명시 주문을 픽업 지점으로 바꿀 수 없다")
        so = stream_options(spec.scenario)
        orders = scenario_orders(spec.scenario)
        horizon = int(opts.get("horizon_ticks", MAX_TICKS))
        # 계약 v2.6: tote_units 는 주문 라인 qty 를 토트로 나누는 단위(스트림), capacity 는 왕복당 토트 수(커널).
        self.stream = OrderStream(np.random.default_rng(so["seed"]), "main", 0, float(opts.get("order_gap", so["order_gap"])),
                                  st_cell, stations, inbound_gap=so["inbound_gap"], horizon=horizon, shifts=so["shifts"],
                                  orders=orders, rack_map=rack_map, tote_units=so["tote_units"], dt=self.dt)   # 도착 틱 = ordered_at_s / dt
        # 회전 발자국 (-203, 계약 v3.4): 견적(sim_v2 기본 exact)과 같은 마스크·치수. --planner-opt footprint= / robot_dims=앞,뒤,폭
        footprint = str(opts.get("footprint", "exact"))
        dims = opts.get("robot_dims", ROBOT_DIMS)
        robot_dims = tuple(float(x) for x in (dims.split(",") if isinstance(dims, str) else dims))
        mask = turn_mask(None, robot_dims, FOOTPRINT_MARGIN_M) if footprint != "legacy" else None
        import pibt.heading as _hd
        _hd.NO_PROGRESS_TURN_BIAS = footprint != "legacy"   # 계약 v3.11: 견적(sim_v2 기본)과 같은 값. 모듈 전역이라 호출마다 명시
        _hd.GOAL_WAIT_FREE = True                            # 계약 v3.12: 목표 상태 대기 점수 0 (견적과 같은 값)
        cfg = KernelConfig(heading=True, zone=zone, theta=bool(theta_file or lanes), service_steps=round(SERVICE_TIME_S / self.dt),
                           capacity=so["capacity"], svc_per_tote=max(1, int(so["svc_per_tote_s"] / self.dt + 0.5)),   # 워커 _orders_flags 와 같은 반올림
                           yield_rule=yield_rule, standoff=footprint != "legacy",   # 계약 v3.9: 견적(sim_v2 기본)과 같이 대치 상태기계 V2
                           turn_ticks=TURN_TICKS, stall_warn_only=True, footprint=footprint, robot_dims=robot_dims)
        self.kernel = FmsKernel(free, st_cell, edge_cost, wait_cost, list(spec.homes), spec.n_robots, cfg,
                                zone_mask=zone_mask, on_task_completed=self.stream.on_completed, lane_dir=lane_dir,
                                turn_mask=mask)
        self.n_robots = spec.n_robots
        self.warnings = warnings + list(self.kernel.warnings)
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
        return K.des_block(K.summary(self.kernel, self.stream, self.n_robots, t_end, self.dt), self.dt)

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


def _theta_file(options: dict | None) -> tuple:
    """(θ 경로 또는 None, 경고 목록). 파일이 없으면 실행을 막지 않고 중립 θ 로 간다 — 다만 견적과 경로가 달라진다."""
    path = theta_path(options)
    if path and not os.path.isfile(path):
        return None, [f"[WARN] θ 파일이 없어 중립 θ 로 진행 — 견적과 경로가 달라진다: {path}"]
    return path, []


def _costs(free: np.ndarray, st_cell: dict, theta_file: str | None,
           lanes: bool = True, yield_rule: bool = True) -> tuple:
    """통행 비용·차선 방향 — sim_v2_tasks.build() 와 같은 순서로 조립한다 (θ 조립 뒤 차선 가중을 곱한다, -177).

    차선·양보는 v3 에서 헤딩 main 의 기본값이 됐다. 둘 다 끄면 v2 와 비트 동일하지만 견적과 달라진다.
    합성 창고(--map-dir)는 토폴로지 스펙이 따로 필요하고 명시 주문(rack_buffers.json)도 없어 검증 런 대상이 아니다.
    """
    H, W = free.shape
    topo = None
    if theta_file or lanes or yield_rule:
        from from_theta import extract_topology
        topo = extract_topology(free, st_cell)                  # 공식 맵 = wallA 상수 (sim_v2 의 spec 생략과 같다)
    if theta_file or lanes:
        from from_theta import GuidanceTheta, from_theta, load_theta
        theta = load_theta(theta_file) if theta_file else GuidanceTheta.neutral()
        lane_gain, pocket_gain = (LANE_GAIN, POCKET_GAIN) if lanes else (1.0, 1.0)
        g = from_theta(free, topo, theta, lane_gain=lane_gain, pocket_gain=pocket_gain)
        return g.edge_cost.astype(np.float64), g.wait_cost.astype(np.float64), topo.lane_dir
    return (np.ones((H, W, 4), dtype=np.float64), np.ones((H, W), dtype=np.float64),
            None if topo is None else topo.lane_dir)
