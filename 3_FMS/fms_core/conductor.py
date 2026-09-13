"""fms-core 상태기계 — Sparkplug Edge(fms-core) · VDA 5050 마스터 · 플래너 틱 배리어 (MQTT_CONTRACT §4 · §5, SIM_VERIFY_CONTRACT §3).

MQTT 소켓은 edge.py 가 붙인다. 여기는 publisher · 시각을 주입받는 순수 로직이라 브로커 없이 테스트한다.
상태: IDLE → STARTING(전 로봇 ONLINE+포즈 → 플래너 생성 → 정렬 order(칸 중심·커널 헤딩) 도착 대기) → RUNNING → IDLE | ERROR.
RUNNING 의 한 틱: planner.step(t) → 로봇별 order 갱신(노드 1개) → 전원 lastNodeId 도착(틱 배리어, 최소 tick_s) → 다음 틱.
Stop(또는 timeout_s·오류)이면 cancelOrder 를 보내고 `biz/v1/event` kpi_summary 를 낸 뒤 IDLE/ERROR. ERROR 는 IDLE 처럼 다음 Start 를 받는다.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from . import spb
from .planner import PlannerSpec, build_planner
from .scenario import RunSpec
from .spb import EdgeSession, MetricDef
from .vda import CONNECTION_STATES, Fleet, RobotLink, now_iso, parse_vda_topic, vda_topic
from .world import REVERSE, cell_center, heading_yaw, world_to_cell

log = logging.getLogger("fms_core")

IDLE, STARTING, RUNNING, ERROR = "IDLE", "STARTING", "RUNNING", "ERROR"

BDSEQ, REBIRTH = "bdSeq", "Node Control/Rebirth"
STATE, RUN_ID, LAST_ERROR, SCENARIO_SHA = "Fms/State", "Fms/RunId", "Fms/LastError", "Fms/ScenarioSha"
TICK, ROBOTS_ONLINE, OPEN_TASKS, DONE_TASKS = "Fms/Tick", "Fms/RobotsOnline", "Fms/OpenTasks", "Fms/DoneTasks"
ORDERS_DONE, HEARTBEAT, PLANNER = "Fms/OrdersDone", "Fms/Heartbeat", "Fms/Planner"
CMD_START, CMD_STOP = "Run Control/Start", "Run Control/Stop"
BIZ_EVENT_TOPIC = "biz/v1/event"
KPI_EVENT = "kpi_summary"

NODE_METRICS = {d.name: d for d in (
    MetricDef(BDSEQ, spb.INT64, 0, 0), MetricDef(REBIRTH, spb.BOOLEAN, 1, False),
    MetricDef(STATE, spb.STRING, 2, IDLE), MetricDef(RUN_ID, spb.STRING, 3, ""),
    MetricDef(LAST_ERROR, spb.STRING, 4, ""), MetricDef(SCENARIO_SHA, spb.STRING, 5, ""),
    MetricDef(TICK, spb.INT64, 6, 0), MetricDef(ROBOTS_ONLINE, spb.INT32, 7, 0),
    MetricDef(OPEN_TASKS, spb.INT32, 8, 0), MetricDef(DONE_TASKS, spb.INT32, 9, 0),
    MetricDef(ORDERS_DONE, spb.INT32, 10, 0), MetricDef(HEARTBEAT, spb.INT64, 11, 0),
    MetricDef(PLANNER, spb.STRING, 12, ""), MetricDef(CMD_START, spb.TEXT, 13, ""),
    MetricDef(CMD_STOP, spb.BOOLEAN, 14, False))}


@dataclass(frozen=True)
class ConductorConfig:
    group: str = "santa"
    node_id: str = "fms-core"
    planner: str = "kernel"
    planner_options: dict = field(default_factory=dict)
    tick_s: float = 1.0                 # 틱 최소 길이(벽시계) = DES 틱 길이 CELL_M/speed (app 이 des_dt 로 채움). 이동 틱은 로봇 도착이 늦으면 그만큼 늘어난다
    ack_timeout_s: float = 30.0         # 노드 하나(1 m · 90°)에 이 이상 걸리면 로봇 정체 → 런 실패
    ready_timeout_s: float = 420.0      # Start 뒤 전원 ONLINE+포즈 (실모드 Isaac 부팅 포함, sim-runner 와 같은 값)
    heartbeat_s: float = 5.0
    host_offline_s: float = 15.0        # host-orch STATE offline 지속 → 런 실패 (§5.4)
    robot_silence_s: float = 30.0       # state 무소식 → 로봇 단절로 본다 (§4.3 결정 10)


class Conductor:
    def __init__(self, cfg: ConductorConfig, session: EdgeSession, publisher: Any,
                 planner_factory: Callable = build_planner):
        self.cfg, self.session, self.pub, self.planner_factory = cfg, session, publisher, planner_factory
        self.values = {name: d.initial for name, d in NODE_METRICS.items()}
        self.values[PLANNER] = cfg.planner
        self.state = IDLE
        self.spec: Optional[RunSpec] = None
        self.fleet: Optional[Fleet] = None
        self.planner: Any = None
        self.t = 0
        self.started_at = 0.0
        self.running_since: Optional[float] = None
        self.tick_started_at = 0.0
        self.last_heartbeat = 0.0
        self.event_seq = 0
        self.last_kpi: Optional[dict] = None
        self.planner_warnings: list = []          # 이 런이 견적과 다른 조건에서 돌았다는 신호 (kpi_summary·snapshot 에 실린다)
        self.host_online: Optional[bool] = None
        self.host_ts = 0
        self.host_offline_since: Optional[float] = None
        self.connections: dict = {}        # serial → 마지막 connectionState. retained 라 구독 직후 한 번만 오므로 런 밖에서도 기억한다

    # ---- 토픽 · 발행 ------------------------------------------------------------
    def topic(self, kind: str) -> str:
        return f"spBv1.0/{self.cfg.group}/{kind}/{self.cfg.node_id}"

    def _pairs(self, names) -> list:
        return [(NODE_METRICS[n], self.values[n]) for n in names]

    def publish_nbirth(self) -> None:
        self.session.seq = 0
        self.values[BDSEQ] = self.session.bd_seq
        self.pub.publish(self.topic("NBIRTH"), spb.encode_birth(self.session.next_seq(), self._pairs(NODE_METRICS)), 0, False)

    def publish_ndata(self, changes: dict) -> None:
        if not changes:
            return
        self.values.update(changes)
        self.pub.publish(self.topic("NDATA"), spb.encode_data(self.session.next_seq(), self._pairs(changes)), 0, False)

    def births(self) -> None:
        self.publish_nbirth()

    def _changed(self, sample: dict) -> dict:
        return {k: v for k, v in sample.items() if v != self.values[k]}

    def _publish_json(self, topic: str, body: dict, qos: int) -> None:
        self.pub.publish(topic, json.dumps(body, ensure_ascii=False).encode("utf-8"), qos, False)

    def _publish_order(self, link: RobotLink, msg: dict) -> None:
        self._publish_json(vda_topic(link.manufacturer, link.serial, "order"), msg, 0)

    def _publish_event(self, kind: str, **fields: Any) -> None:
        self.event_seq += 1
        run_id = self.spec.run_id if self.spec else ""
        body = {"eventId": f"{run_id}-{self.event_seq}", "runId": run_id, "at": now_iso(), "type": kind, "tick": self.t}
        body.update(fields)
        self._publish_json(BIZ_EVENT_TOPIC, body, 1)

    # ---- 인바운드 ----------------------------------------------------------------
    def on_connected(self, now: float) -> None:
        self.births()
        self.last_heartbeat = now

    def on_ncmd(self, payload: bytes, now: float) -> None:
        try:
            cmd = spb.metrics_by_name(spb.decode(payload))
        except Exception as e:  # noqa: BLE001 — 깨진 protobuf 는 무시하고 기록만
            log.warning("NCMD undecodable: %s", e)
            return
        if cmd.get(REBIRTH) is True:
            log.info("NCMD Rebirth")
            self.births()
        if cmd.get(CMD_STOP) is True:
            self.handle_stop(now)
        start = cmd.get(CMD_START)
        if isinstance(start, str) and start.strip():
            self.handle_start(start, now)

    def on_host_state(self, payload: bytes, now: float) -> None:
        try:
            d = json.loads(payload)
        except (ValueError, UnicodeDecodeError):
            return
        if not isinstance(d, dict) or not isinstance(d.get("online"), bool):
            return
        online, ts = d["online"], d.get("timestamp", 0)
        came_back = online and (self.host_online is False or (self.host_online and ts > self.host_ts))
        self.host_online, self.host_ts = online, ts if isinstance(ts, int) else self.host_ts
        self.host_offline_since = None if online else (self.host_offline_since or now)
        if came_back:
            log.info("host-orch back online → rebirth")
            self.births()

    def on_vda(self, topic: str, payload: bytes, now: float) -> None:
        parsed = parse_vda_topic(topic)
        if parsed is not None and parsed[2] == "connection":
            self._remember_connection(parsed[1], payload)
        if self.fleet is None or self.state not in (STARTING, RUNNING):
            return
        hit = self.fleet.handle(topic, payload)
        if hit is None:
            return
        serial, kind, msg = hit
        link = self.fleet.robots[serial]
        if kind == "connection":
            link.on_connection(msg)
        else:
            link.on_state(msg, now)

    def _remember_connection(self, serial: str, payload: bytes) -> None:
        try:
            msg = json.loads(payload)
        except (ValueError, UnicodeDecodeError):
            return
        state = msg.get("connectionState") if isinstance(msg, dict) else None
        if state in CONNECTION_STATES:
            self.connections[serial] = state

    # ---- 명령 -------------------------------------------------------------------
    def handle_start(self, text: str, now: float) -> None:
        try:
            spec = RunSpec.from_json(text)
        except ValueError as e:
            self.publish_ndata({LAST_ERROR: f"bad Start: {e}"})
            return
        if self.state in (STARTING, RUNNING):
            current = self.spec.run_id if self.spec else ""
            if spec.run_id == current:
                log.info("Start %s repeated while %s → state re-reported", spec.run_id, self.state)
                self.publish_ndata({STATE: self.state, RUN_ID: current})
            else:
                self.publish_ndata({LAST_ERROR: f"busy: {self.state} {current}; Start {spec.run_id} ignored"})
            return
        self._begin(spec, now)

    def _begin(self, spec: RunSpec, now: float) -> None:
        self.spec = spec
        self.fleet = Fleet([(r.serial, r.manufacturer) for r in spec.robots], spec.run_id)
        for serial, link in self.fleet.robots.items():        # retained connection 은 Start 전에 이미 왔을 수 있다. 포즈는 새 state 로만
            link.connection = self.connections.get(serial, "")
        self.planner, self.t, self.started_at, self.running_since, self.last_kpi = None, 0, now, None, None
        self.planner_warnings = []                            # 앞 런의 경고가 다음 런 결과에 묻어가면 안 된다
        log.info("run %s: waiting for %d robots (scenario %s)", spec.run_id, spec.n_robots, (spec.scenario_sha256 or "none")[:12])
        self._set_state(STARTING, {RUN_ID: spec.run_id, LAST_ERROR: "", SCENARIO_SHA: spec.scenario_sha256 or "",
                                   TICK: 0, ROBOTS_ONLINE: 0, OPEN_TASKS: 0, DONE_TASKS: 0, ORDERS_DONE: 0})

    def handle_stop(self, now: float) -> None:
        if self.state in (STARTING, RUNNING):
            self._end(now, IDLE, "")
        else:
            log.info("Stop while %s — nothing to do", self.state)

    def _fail(self, now: float, reason: str) -> None:
        log.error("run %s failed: %s", self.spec.run_id if self.spec else "?", reason)
        self._end(now, ERROR, reason)

    def _end(self, now: float, final: str, reason: str) -> None:
        run_id = self.spec.run_id if self.spec else "?"
        log.info("run %s ending → %s %s (tick %d)", run_id, final, reason, self.t)
        if self.fleet is not None:
            for link in self.fleet.robots.values():
                if link.k >= 0:
                    self._publish_json(vda_topic(link.manufacturer, link.serial, "instantActions"), link.cancel_order(), 0)
        kpi = None
        if self.planner is not None and self.t > 0:
            try:
                kpi = self.planner.kpi(self.t)
            except Exception as e:  # noqa: BLE001 — KPI 실패가 종료를 막으면 안 된다
                log.exception("kpi failed: %s", e)
        self.last_kpi = kpi
        counters = self.planner.counters() if self.planner is not None else {}
        self._publish_event(KPI_EVENT, status="done" if final == IDLE else "failed", error=reason or None,
                            kpi=kpi, ticks=self.t, elapsed_s=round(now - self.running_since, 1) if self.running_since else 0.0,
                            counters=counters, planner=self.cfg.planner, warnings=self.planner_warnings or None)
        self.fleet, self.planner = None, None
        self._set_state(final, {RUN_ID: "", SCENARIO_SHA: "", LAST_ERROR: reason})

    def _set_state(self, state: str, extra: Optional[dict] = None) -> None:
        self.state = state
        self.publish_ndata({STATE: state, **(extra or {})})

    # ---- 주기 --------------------------------------------------------------------
    def tick(self, now: float) -> None:
        if self.state == STARTING:
            self._tick_starting(now)
        elif self.state == RUNNING:
            self._tick_running(now)
        if now - self.last_heartbeat >= self.cfg.heartbeat_s:
            self.last_heartbeat = now
            online = self.fleet.online() if self.fleet is not None else 0
            self.publish_ndata({HEARTBEAT: int(now * 1000), **self._changed({ROBOTS_ONLINE: online})})

    def _tick_starting(self, now: float) -> None:
        if self.planner is None:
            if self.fleet.all_ready():
                self._build_planner(now)
            elif now - self.started_at > self.cfg.ready_timeout_s:
                self._fail(now, f"ready timeout {self.cfg.ready_timeout_s:g}s: online={self.fleet.online()}/{self.spec.n_robots}")
            return
        fault = self._robot_fault(now)
        if fault:
            self._fail(now, fault)
        elif self._service_pending(now) and not self.fleet.pending():
            self.running_since, self.tick_started_at = now, now - self.cfg.tick_s
            log.info("run %s: %d robots aligned → RUNNING", self.spec.run_id, self.spec.n_robots)
            self._set_state(RUNNING, {ROBOTS_ONLINE: self.fleet.online()})

    def _build_planner(self, now: float) -> None:
        links = [self.fleet.robots[r.serial] for r in self.spec.robots]
        homes = tuple(world_to_cell(link.x, link.y) for link in links)
        spec = PlannerSpec(self.spec.run_id, self.spec.n_robots, homes, self.spec.scenario, dict(self.cfg.planner_options))
        try:
            self.planner = self.planner_factory(self.cfg.planner, spec)
        except (ValueError, RuntimeError, AssertionError, KeyError, OSError) as e:   # OSError: θ·맵 파일 읽기 실패
            self._fail(now, f"planner build failed: {e}")
            return
        # 플래너 경고 = "이 런은 견적과 다른 조건에서 돌았다" 는 신호. 로그로만 두면 결과를 견적과 비교하는 쪽이
        # 알 수 없다 → kpi_summary·snapshot 에도 싣는다 (예: θ 파일 없음 → 중립 θ).
        self.planner_warnings = [str(w) for w in getattr(self.planner, "warnings", ())]
        for warning in self.planner_warnings:
            log.warning("run %s: planner %s", self.spec.run_id, warning)
        views = self.planner.robots()
        for link, view in zip(links, views):
            self._publish_order(link, link.initial_order(link.x, link.y, link.yaw, now))
            x, y = cell_center(view.cell)
            self._publish_order(link, link.next_order(x, y, heading_yaw(view.h), False, now))
        log.info("run %s: planner %s built, aligning %d robots to cell centres", self.spec.run_id, self.cfg.planner, len(links))

    def _robot_fault(self, now: float) -> Optional[str]:
        for link in self.fleet.robots.values():
            fatal = link.fatal_error()
            if fatal:
                return f"{link.serial} {fatal}"
            if link.connection in ("OFFLINE", "CONNECTIONBROKEN"):
                return f"{link.serial} {link.connection}"
            if link.last_state_at and now - link.last_state_at > self.cfg.robot_silence_s:
                return f"{link.serial} silent for {now - link.last_state_at:.0f}s"
        return None

    def _service_pending(self, now: float) -> bool:
        """도착 확인 · 재발행 · 정체 판정. 런을 접었으면 False."""
        for link in self.fleet.pending():
            if link.arrived:
                link.settle()
            elif link.unreflected_error():
                self._fail(now, f"{link.serial} ignores orderUpdateId {link.pending} after {link.states_since_send} states")
                return False
            elif link.resend_due():
                log.warning("%s: orderUpdateId %d unreflected after %d states → resend", link.serial, link.pending,
                            link.states_since_send)
                self._publish_order(link, link.resend(now))
            elif now - link.sent_at > self.cfg.ack_timeout_s:
                self._fail(now, f"{link.serial} did not reach n{link.pending} within {self.cfg.ack_timeout_s:g}s")
                return False
        return True

    def _tick_running(self, now: float) -> None:
        if now - self.started_at > self.spec.timeout_s:
            self._fail(now, f"timeout_s {self.spec.timeout_s:g} elapsed")
            return
        if self.host_offline_since is not None and now - self.host_offline_since > self.cfg.host_offline_s:
            self._fail(now, f"host-orch offline > {self.cfg.host_offline_s:g}s")
            return
        fault = self._robot_fault(now)
        if fault:
            self._fail(now, fault)
            return
        if not self._service_pending(now) or self.fleet.pending() or now - self.tick_started_at < self.cfg.tick_s:
            return
        self._advance(now)

    def _advance(self, now: float) -> None:
        try:
            cmds = self.planner.step(self.t)
        except Exception as e:  # noqa: BLE001 — 플래너 예외는 런 실패 사유가 된다 (데몬은 살아야 한다)
            log.exception("planner step failed")
            self._fail(now, f"planner step {self.t} failed: {e}")
            return
        serials = [r.serial for r in self.spec.robots]
        for cmd in cmds:
            link = self.fleet.robots[serials[cmd.rid]]
            x, y = cell_center(cmd.cell)
            self._publish_order(link, link.next_order(x, y, heading_yaw(cmd.h), cmd.kind == REVERSE, now))
        self.t += 1
        self.tick_started_at = now
        for ev in self.planner.drain_events():
            self._emit_planner_event(ev, serials)
        c = self.planner.counters()
        self.publish_ndata(self._changed({TICK: self.t, OPEN_TASKS: c["open_tasks"], DONE_TASKS: c["done_tasks"],
                                          ORDERS_DONE: c["orders_done"], ROBOTS_ONLINE: self.fleet.online()}))

    def _emit_planner_event(self, ev: dict, serials: list) -> None:
        rid = ev.get("rid")
        robot = None
        if rid is not None and 0 <= rid < len(serials):
            link = self.fleet.robots[serials[rid]]
            robot = {"manufacturer": link.manufacturer, "serial": link.serial}
        self._publish_event(ev["type"], orderId=ev.get("order_id"), taskId=ev.get("task_id"), robot=robot,
                            tick=ev.get("tick", self.t))

    def snapshot(self) -> dict:
        return {"state": self.state, "run_id": self.values[RUN_ID], "last_error": self.values[LAST_ERROR],
                "tick": self.t, "bd_seq": self.session.bd_seq, "seq": self.session.seq, "kpi": self.last_kpi,
                "warnings": self.planner_warnings or None}
