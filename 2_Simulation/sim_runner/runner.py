"""sim-runner 상태기계 — MQTT_CONTRACT §5.2 메트릭 사전 · §5.3 NCMD · §5.4 세션 규칙.

MQTT 소켓은 edge.py 가 붙인다. 여기는 publisher · clock · ProcessManager 를 주입받는 순수 로직이라 브로커 없이 테스트한다.
상태: IDLE → STARTING(에이전트 ONLINE ×N 대기) → RUNNING → STOPPING → IDLE | ERROR. ERROR 는 IDLE 처럼 다음 Start 를 받는다.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from . import mirror as M
from . import spb, telemetry
from .procs import ProcessManager, RunSpec
from .spb import EdgeSession, MetricDef

log = logging.getLogger("sim_runner")

IDLE, STARTING, RUNNING, STOPPING, ERROR = "IDLE", "STARTING", "RUNNING", "STOPPING", "ERROR"

BDSEQ, REBIRTH = "bdSeq", "Node Control/Rebirth"
STATE, RUN_ID, HEARTBEAT, RTF = "Runner/State", "Runner/RunId", "Runner/Heartbeat", "Runner/RTF"
ISAAC, RAM, VRAM, LAST_ERROR = "Runner/IsaacInstances", "Runner/RamMB", "Runner/VramMB", "Runner/LastError"
CMD_START, CMD_STOP = "Run Control/Start", "Run Control/Stop"

NODE_METRICS = {d.name: d for d in (
    MetricDef(BDSEQ, spb.INT64, 0, 0), MetricDef(REBIRTH, spb.BOOLEAN, 1, False),
    MetricDef(STATE, spb.STRING, 2, IDLE), MetricDef(RUN_ID, spb.STRING, 3, ""),
    MetricDef(HEARTBEAT, spb.INT64, 4, 0), MetricDef(RTF, spb.DOUBLE, 5, 0.0),
    MetricDef(ISAAC, spb.INT32, 6, 0), MetricDef(RAM, spb.INT32, 7, 0), MetricDef(VRAM, spb.INT32, 8, 0),
    MetricDef(LAST_ERROR, spb.STRING, 9, ""), MetricDef(CMD_START, spb.TEXT, 10, ""),
    MetricDef(CMD_STOP, spb.BOOLEAN, 11, False))}

DEVICE_ALIAS_BASE, DEVICE_ALIAS_STRIDE = 100, 16      # 별칭은 노드+디바이스 전체에서 유일해야 한다
_DEVICE_TYPES = ((M.MODEL, spb.STRING), (M.CONNECTION, spb.STRING), (M.LAST_NODE, spb.STRING),
                 (M.POSE_X, spb.DOUBLE), (M.POSE_Y, spb.DOUBLE), (M.YAW, spb.DOUBLE), (M.BATTERY, spb.DOUBLE),
                 (M.AMCL_ERR, spb.DOUBLE))
RTF_EPS = 0.01


def device_metrics(index: int) -> dict:
    base = DEVICE_ALIAS_BASE + index * DEVICE_ALIAS_STRIDE
    return {name: MetricDef(name, dtype, base + k) for k, (name, dtype) in enumerate(_DEVICE_TYPES)}


@dataclass(frozen=True)
class RunnerConfig:
    group: str = "santa"
    node_id: str = "sim-runner-gpu01"
    heartbeat_s: float = 5.0
    ready_timeout_s: float = 120.0
    host_offline_s: float = 15.0


class Runner:
    def __init__(self, cfg: RunnerConfig, session: EdgeSession, procs_factory: Callable[[], ProcessManager],
                 publisher: Any, ram_mb: Callable = telemetry.ram_mb,
                 vram_mb: Callable = telemetry.vram_mb):
        self.cfg, self.session, self.procs_factory, self.pub = cfg, session, procs_factory, publisher
        self.ram_mb, self.vram_mb = ram_mb, vram_mb
        self.values = {name: d.initial for name, d in NODE_METRICS.items()}
        self.state = IDLE
        self.spec: Optional[RunSpec] = None
        self.procs: Optional[ProcessManager] = None
        self.fleet: Optional[M.Fleet] = None
        self.devices_born: list = []
        self.started_at = 0.0
        self.last_heartbeat = 0.0
        self.final_state = IDLE
        self.host_online: Optional[bool] = None
        self.host_ts = 0
        self.host_offline_since: Optional[float] = None

    # ---- 토픽 · 발행 ------------------------------------------------------------
    def topic(self, kind: str, device: Optional[str] = None) -> str:
        t = f"spBv1.0/{self.cfg.group}/{kind}/{self.cfg.node_id}"
        return f"{t}/{device}" if device else t

    def _node_pairs(self, names) -> list:
        return [(NODE_METRICS[n], self.values[n]) for n in names]

    def publish_nbirth(self) -> None:
        self.session.seq = 0
        self.values[BDSEQ] = self.session.bd_seq
        self.pub.publish(self.topic("NBIRTH"), spb.encode_birth(self.session.next_seq(),
                                                                 self._node_pairs(NODE_METRICS)), 0, False)

    def publish_ndata(self, changes: dict) -> None:
        self.values.update(changes)
        self.pub.publish(self.topic("NDATA"), spb.encode_data(self.session.next_seq(),
                                                              self._node_pairs(changes)), 0, False)

    def _device_defs(self, serial: str) -> dict:
        return device_metrics(list(self.fleet.robots).index(serial))

    def publish_dbirth(self, serial: str) -> None:
        defs, values = self._device_defs(serial), self.fleet.robots[serial].birth_values()
        pairs = [(defs[n], values[n]) for n in M.DEVICE_METRIC_NAMES]
        self.pub.publish(self.topic("DBIRTH", serial), spb.encode_birth(self.session.next_seq(), pairs), 0, False)

    def publish_ddata(self, serial: str, names: list) -> None:
        defs, values = self._device_defs(serial), self.fleet.robots[serial].values()
        pairs = [(defs[n], values[n]) for n in names]
        self.pub.publish(self.topic("DDATA", serial), spb.encode_data(self.session.next_seq(), pairs), 0, False)

    def publish_ddeath(self, serial: str) -> None:
        self.pub.publish(self.topic("DDEATH", serial), spb.encode_ddeath(self.session.next_seq()), 0, False)

    def births(self) -> None:
        """NBIRTH + 살아 있는 DBIRTH 재발행 (접속 · Rebirth · Host 복귀)."""
        self.publish_nbirth()
        for serial in list(self.devices_born):
            self.publish_dbirth(serial)

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
        if self.fleet is None or self.state not in (STARTING, RUNNING):
            return
        hit = self.fleet.handle(topic, payload, now)
        if hit and self.state == RUNNING and hit[1] and hit[0] in self.devices_born:
            self.publish_ddata(hit[0], hit[1])

    # ---- 명령 -------------------------------------------------------------------
    def handle_start(self, text: str, now: float) -> None:
        try:
            spec = RunSpec.from_json(text)
        except ValueError as e:
            self.publish_ndata({LAST_ERROR: f"bad Start: {e}"})
            return
        if self.state in (STARTING, RUNNING, STOPPING):
            current = self.spec.run_id if self.spec else ""
            if spec.run_id == current and self.state != STOPPING:
                log.info("Start %s repeated while %s → state re-reported", spec.run_id, self.state)
                self.publish_ndata({STATE: self.state, RUN_ID: current})
            else:
                self.publish_ndata({LAST_ERROR: f"busy: {self.state} {current}; Start {spec.run_id} ignored"})
            return
        self._begin(spec, now)

    def _begin(self, spec: RunSpec, now: float) -> None:
        self.spec, self.fleet, self.devices_born = spec, M.Fleet([(r.serial, r.model) for r in spec.robots]), []
        self.procs, self.started_at, self.final_state = self.procs_factory(), now, IDLE
        try:
            self.procs.start(spec, now)
        except (OSError, RuntimeError) as e:
            self._set_state(ERROR, {LAST_ERROR: f"launch failed: {e}", RUN_ID: ""})
            return
        log.info("run %s: launching %d agents", spec.run_id, spec.n_robots)
        self._set_state(STARTING, {RUN_ID: spec.run_id, LAST_ERROR: ""})

    def handle_stop(self, now: float) -> None:
        if self.state in (STARTING, RUNNING):
            self._stop(now, IDLE, "")
        else:
            log.info("Stop while %s — nothing to do", self.state)

    def _stop(self, now: float, final_state: str, reason: str) -> None:
        log.info("run %s stopping → %s %s", self.spec.run_id if self.spec else "?", final_state, reason)
        for serial in self.devices_born:
            self.publish_ddeath(serial)
        self.devices_born = []
        self.final_state = final_state
        self.procs.request_stop(now)
        self._set_state(STOPPING, {LAST_ERROR: reason} if reason else {})

    def _fail(self, now: float, reason: str) -> None:
        log.error("run %s failed: %s", self.spec.run_id if self.spec else "?", reason)
        self._stop(now, ERROR, reason)

    def _set_state(self, state: str, extra: Optional[dict] = None) -> None:
        self.state = state
        self.publish_ndata({STATE: state, **(extra or {})})

    # ---- 주기 --------------------------------------------------------------------
    def tick(self, now: float) -> None:
        if self.state == STARTING:
            self._tick_starting(now)
        elif self.state == RUNNING:
            self._tick_running(now)
        elif self.state == STOPPING and self.procs.poll_stop(now):
            self._set_state(self.final_state, {RUN_ID: ""})
        if now - self.last_heartbeat >= self.cfg.heartbeat_s:
            self.last_heartbeat = now
            self.publish_ndata({HEARTBEAT: int(now * 1000), **self._telemetry_changes()})

    def _tick_starting(self, now: float) -> None:
        self.procs.poll_start(now)
        dead = self.procs.dead()
        if dead:
            self._fail(now, f"process died during start: {','.join(dead)}")
        elif self.fleet.all_online():
            for serial in self.fleet.robots:
                self.publish_dbirth(serial)
                self.devices_born.append(serial)
            log.info("run %s: %d agents ONLINE → RUNNING", self.spec.run_id, len(self.devices_born))
            self._set_state(RUNNING)
        elif now - self.started_at > self.cfg.ready_timeout_s:
            self._fail(now, f"ready timeout {self.cfg.ready_timeout_s:g}s: online={self.fleet.online()}")

    def _tick_running(self, now: float) -> None:
        dead = self.procs.dead()
        if dead:
            self._fail(now, f"process died: {','.join(dead)}")
        elif now - self.started_at > self.spec.timeout_s:
            self._fail(now, f"timeout_s {self.spec.timeout_s:g} elapsed")
        elif self.host_offline_since is not None and now - self.host_offline_since > self.cfg.host_offline_s:
            self._fail(now, f"host-orch offline > {self.cfg.host_offline_s:g}s")

    def _telemetry_changes(self) -> dict:
        pids = self.procs.pids() if self.procs else []
        rtf = (self.fleet.rtf() if self.fleet and self.state == RUNNING else None) or 0.0
        vram = self.vram_mb()
        sample = {RTF: rtf, ISAAC: self.procs.isaac_count() if self.procs else 0,
                  RAM: self.ram_mb(pids) if pids else 0, VRAM: vram if vram is not None else self.values[VRAM]}
        return {k: v for k, v in sample.items()
                if (abs(v - self.values[k]) >= RTF_EPS if k == RTF else v != self.values[k])}

    def snapshot(self) -> dict:
        return {"state": self.state, "run_id": self.values[RUN_ID], "last_error": self.values[LAST_ERROR],
                "devices": list(self.devices_born), "bd_seq": self.session.bd_seq, "seq": self.session.seq}


def now_s() -> float:
    return time.time()
