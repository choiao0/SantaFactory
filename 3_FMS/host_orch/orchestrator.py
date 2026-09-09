"""검증 잡 수명 — sim.verify.request 1건 = sim-runner 런 1개 (MQTT_CONTRACT §5.3 · 결정 4/14, SIM_VERIFY_CONTRACT).

Job: STARTING(NCMD Start → Runner/State RUNNING · RunId 일치 대기) → RUNNING(창 window_s) → STOPPING(NCMD Stop → IDLE)
→ DONE | FAILED. sim-runner 가 스스로 ERROR 로 접거나 NDEATH 면 FAILED. Start 는 QoS0 이라 반영이 없으면 재전송(멱등).
Coordinator 가 tracker 이벤트·tick 을 Job.step 으로 넘긴다. 순수 파이썬 — 발행은 콜백.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from . import spb
from .tracker import HostTracker, Node

STATE, RUN_ID, HEARTBEAT, RTF = "Runner/State", "Runner/RunId", "Runner/Heartbeat", "Runner/RTF"
RAM, VRAM, LAST_ERROR = "Runner/RamMB", "Runner/VramMB", "Runner/LastError"
CMD_START, CMD_STOP, REBIRTH = "Run Control/Start", "Run Control/Stop", "Node Control/Rebirth"
IDLE, STARTING, RUNNING, STOPPING, ERROR = "IDLE", "STARTING", "RUNNING", "STOPPING", "ERROR"

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
MAX_ROBOTS = 64
DEFAULT_WINDOW_S = 600.0
START_MARGIN_S = 300.0          # sim-runner 쪽 timeout_s = window + 여유(기동 + 정지)


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class VerifyRequest:
    """sim.verify.request 본문 (SIM_VERIFY_CONTRACT §2). 모르는 필드는 raw 에 남긴다."""
    run_id: str
    n_robots: int
    scenario_pkg: str = ""
    models: tuple = ()
    ros_domain_id: int = 0
    window_s: float = DEFAULT_WINDOW_S
    timeout_s: Optional[float] = None
    source_run_id: Optional[str] = None
    estimate_id: Optional[int] = None
    seed: Optional[int] = None
    priority: int = 0
    raw: dict = field(default_factory=dict, compare=False)

    @staticmethod
    def from_json(text: Any) -> "VerifyRequest":
        try:
            d = json.loads(text)
        except (ValueError, TypeError) as e:
            raise ValueError(f"request is not JSON: {e}") from None
        if not isinstance(d, dict):
            raise ValueError("request must be a JSON object")
        return VerifyRequest.from_dict(d)

    @staticmethod
    def from_dict(d: dict) -> "VerifyRequest":
        run_id = d.get("run_id")
        if not isinstance(run_id, str) or not SAFE_ID.match(run_id):
            raise ValueError("run_id must match [A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
        n = d.get("n_robots")
        if not _is_int(n) or not 1 <= n <= MAX_ROBOTS:
            raise ValueError(f"n_robots must be an integer in 1..{MAX_ROBOTS}")
        window = d.get("window_s", DEFAULT_WINDOW_S)
        if not _is_num(window) or window <= 0:
            raise ValueError("window_s must be a positive number")
        timeout = d.get("timeout_s")
        if timeout is not None and (not _is_num(timeout) or timeout <= 0):
            raise ValueError("timeout_s must be a positive number")
        domain = d.get("ros_domain_id", 0)
        if not _is_int(domain) or not 0 <= domain <= 232:
            raise ValueError("ros_domain_id must be an integer in 0..232")
        models = d.get("models") or []
        if not isinstance(models, list) or (models and len(models) != n):
            raise ValueError("models must be a list with exactly n_robots entries (or empty)")
        for m in models:
            if not isinstance(m, dict) or not isinstance(m.get("serial"), str) or not SAFE_ID.match(m["serial"]):
                raise ValueError("each models[] entry needs a safe serial")
        return VerifyRequest(run_id, n, str(d.get("scenario_pkg") or ""), tuple(models), domain, float(window),
                             float(timeout) if timeout is not None else None,
                             _opt_str(d.get("source_run_id")), _opt_int(d.get("estimate_id")),
                             _opt_int(d.get("seed")), _opt_int(d.get("priority")) or 0, dict(d))

    def start_command(self) -> dict:
        """NCMD Run Control/Start JSON (MQTT_CONTRACT §5.3)."""
        return {"run_id": self.run_id, "scenario_pkg": self.scenario_pkg, "n_robots": self.n_robots,
                "models": [dict(m) for m in self.models], "ros_domain_id": self.ros_domain_id,
                "timeout_s": self.timeout_s if self.timeout_s is not None else self.window_s + START_MARGIN_S}


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _opt_str(v: Any) -> Optional[str]:
    return v if isinstance(v, str) and v else None


def _opt_int(v: Any) -> Optional[int]:
    return v if _is_int(v) else None


@dataclass(frozen=True)
class JobConfig:
    start_timeout_s: float = 180.0      # Start 뒤 RUNNING 까지 (에이전트 기동 + Isaac 예열)
    start_resend_s: float = 15.0        # 반영이 없으면 Start 재전송 (sim-runner 는 같은 run_id 멱등)
    stop_timeout_s: float = 60.0
    heartbeat_s: float = 5.0
    heartbeat_misses: int = 3           # 결정 9: 3회 결측 = 런 실패


@dataclass
class Stats:
    robots_online: int = 0
    rtf_samples: list = field(default_factory=list)
    ram_mb_max: int = 0
    vram_mb_max: int = 0

    def observe(self, node: Node) -> None:
        self.robots_online = max(self.robots_online, len(node.alive_devices()))
        rtf = node.get(RTF)
        if isinstance(rtf, (int, float)) and rtf > 0:
            self.rtf_samples.append(float(rtf))
        for name, attr in ((RAM, "ram_mb_max"), (VRAM, "vram_mb_max")):
            v = node.get(name)
            if isinstance(v, int) and v > getattr(self, attr):
                setattr(self, attr, v)


class Job:
    """런 하나. step(node, now, cmd) 를 이벤트마다·tick 마다 부른다. cmd.start(json_text) / cmd.stop()."""

    def __init__(self, req: VerifyRequest, node_id: str, cfg: JobConfig, now: float):
        self.req, self.node_id, self.cfg = req, node_id, cfg
        self.phase = STARTING
        self.created_at, self.started_at, self.ended_at = now, None, None
        self.last_send, self.stop_sent_at, self.stop_resent = None, None, False
        self.seen_ours = False
        self.seen_online = False
        self.final = None                 # DONE | FAILED (STOPPING 이 끝나면 phase 가 이 값이 된다)
        self.reason, self.error = "", None
        self.stats = Stats()

    # ---- 상태 -------------------------------------------------------------------
    @property
    def done(self) -> bool:
        return self.phase in ("DONE", "FAILED")

    def _finish(self, phase: str, now: float, reason: str, error: Optional[str] = None) -> None:
        self.phase, self.ended_at, self.reason = phase, now, reason
        self.error = error if phase == "FAILED" else None

    def _begin_stop(self, cmd: Any, now: float, final: str, reason: str, error: Optional[str] = None) -> None:
        self.phase, self.final, self.reason, self.error = STOPPING, final, reason, error
        self.stop_sent_at = now
        cmd.stop()

    # ---- 진행 -------------------------------------------------------------------
    def step(self, node: Optional[Node], now: float, cmd: Any) -> None:
        if self.done:
            return
        if node is not None and node.online:
            self.stats.observe(node)
        if self.phase == STARTING:
            self._step_starting(node, now, cmd)
        elif self.phase == RUNNING:
            self._step_running(node, now, cmd)
        elif self.phase == STOPPING:
            self._step_stopping(node, now, cmd)

    def _step_starting(self, node: Optional[Node], now: float, cmd: Any) -> None:
        if node is None or not node.online:
            if self.seen_online:
                self._finish("FAILED", now, "runner NDEATH", "sim-runner went offline while starting")
            elif now - self.created_at > self.cfg.start_timeout_s:
                self._finish("FAILED", now, "start timeout", f"sim-runner {self.node_id} offline")
            return
        self.seen_online = True
        st, rid = node.get(STATE), node.get(RUN_ID)
        if rid == self.req.run_id:
            self.seen_ours = True
            if st == RUNNING:
                self.phase, self.started_at = RUNNING, now
                return
        elif self.seen_ours and st in (IDLE, ERROR):
            self._finish("FAILED", now, "run ended before RUNNING", node.get(LAST_ERROR) or "ended by runner")
            return
        busy = rid and rid != self.req.run_id and st in (STARTING, RUNNING, STOPPING)
        if not busy and not self.seen_ours and (self.last_send is None or now - self.last_send >= self.cfg.start_resend_s):
            self.last_send = now
            cmd.start(json.dumps(self.req.start_command()))
        if now - self.created_at > self.cfg.start_timeout_s:
            why = f"runner busy with {rid}" if busy else f"state={st} run_id={rid!r}"
            self._finish("FAILED", now, "start timeout", why)

    def _step_running(self, node: Optional[Node], now: float, cmd: Any) -> None:
        if node is None or not node.online:
            self._finish("FAILED", now, "runner NDEATH", "sim-runner went offline during the run")
            return
        st, rid = node.get(STATE), node.get(RUN_ID)
        if rid != self.req.run_id or st in (IDLE, ERROR):
            error = node.get(LAST_ERROR) if st == ERROR else "run ended by runner"
            self._finish("FAILED", now, "runner ended the run", error or "runner ERROR")
        elif now - node.last_seen > self.cfg.heartbeat_s * self.cfg.heartbeat_misses:
            self._begin_stop(cmd, now, "FAILED", "heartbeat lost", f"no NDATA for {now - node.last_seen:.0f}s")
        elif now - self.started_at >= self.req.window_s:
            self._begin_stop(cmd, now, "DONE", "window elapsed")

    def _step_stopping(self, node: Optional[Node], now: float, cmd: Any) -> None:
        if node is None or not node.online:
            self._finish("FAILED", now, "runner NDEATH while stopping", "sim-runner went offline before confirming IDLE")
            return
        st, rid = node.get(STATE), node.get(RUN_ID)
        if st == ERROR:
            self._finish("FAILED", now, "runner ERROR while stopping", node.get(LAST_ERROR) or "runner ERROR")
        elif rid != self.req.run_id or st == IDLE:
            self._finish(self.final, now, self.reason, self.error)
        elif now - self.stop_sent_at > self.cfg.stop_timeout_s:
            if not self.stop_resent:
                self.stop_resent, self.stop_sent_at = True, now
                cmd.stop()
            else:
                self._finish("FAILED", now, "stop timeout", f"runner still {st} after 2 Stop commands")

    # ---- 결과 -------------------------------------------------------------------
    def result(self) -> dict:
        """sim.verify.result 본문 (SIM_VERIFY_CONTRACT §3). kpi · artifacts 는 fms-core 연동 전까지 null."""
        s = self.stats
        elapsed = (self.ended_at - self.started_at) if self.started_at is not None and self.ended_at is not None else 0.0
        return {"run_id": self.req.run_id, "status": "done" if self.phase == "DONE" else "failed",
                "error": self.error,
                "verify": {"runner": self.node_id, "n_robots": self.req.n_robots, "robots_online": s.robots_online,
                           "window_s": self.req.window_s, "elapsed_s": round(elapsed, 1),
                           "started_at": iso(self.started_at) if self.started_at is not None else None,
                           "ended_at": iso(self.ended_at) if self.ended_at is not None else None,
                           "rtf_mean": round(sum(s.rtf_samples) / len(s.rtf_samples), 3) if s.rtf_samples else None,
                           "ram_mb_max": s.ram_mb_max or None, "vram_mb_max": s.vram_mb_max or None,
                           "reason": self.reason},
                "kpi": None, "artifacts": None,
                "source_run_id": self.req.source_run_id, "estimate_id": self.req.estimate_id}


class FailedRequest:
    """파싱 실패한 요청 — 결과 큐에 failed 로 바로 내보낸다(명세 §1-2: 실패도 정상 발행)."""

    def __init__(self, run_id: Optional[str], error: str):
        self.run_id, self.error, self.phase, self.done = run_id, error, "FAILED", True

    def result(self) -> dict:
        return {"run_id": self.run_id, "status": "failed", "error": self.error, "verify": None,
                "kpi": None, "artifacts": None}


class Commands:
    def __init__(self, send_ncmd: Callable[[str, list], None], node_id: str):
        self.send_ncmd, self.node_id = send_ncmd, node_id

    def start(self, text: str) -> None:
        self.send_ncmd(self.node_id, [(CMD_START, spb.TEXT, text)])

    def stop(self) -> None:
        self.send_ncmd(self.node_id, [(CMD_STOP, spb.BOOLEAN, True)])

    def rebirth(self) -> None:
        self.send_ncmd(self.node_id, [(REBIRTH, spb.BOOLEAN, True)])


class Busy(ValueError):
    """다른 run_id 의 잡이 진행 중 — 호출자는 요청을 들고 있다가 다시 submit 한다."""


def run_id_of(body: Any) -> Optional[str]:
    try:
        return _opt_str(json.loads(body).get("run_id"))
    except Exception:  # noqa: BLE001
        return None


class Coordinator:
    """tracker + 현재 잡 하나 (prefetch 1). MQTT 스레드와 AMQP 루프가 같은 락으로 부른다.

    재전달(채널 단절 뒤 RabbitMQ 가 unacked 를 다시 줌)에 멱등: 진행 중인 같은 run_id 는 그 잡을, 이미 끝난 run_id(최근 50개)는
    끝난 잡을 돌려줘 결과만 다시 발행한다 — GPU 런을 두 번 돌리지 않는다.
    """
    RECENT_MAX = 50

    def __init__(self, tracker: HostTracker, send_ncmd: Callable[[str, list], None], node_id: str,
                 cfg: JobConfig = JobConfig(), clock: Callable[[], float] = time.time):
        self.tracker, self.send_ncmd, self.node_id, self.cfg, self.clock = tracker, send_ncmd, node_id, cfg, clock
        self.cmd = Commands(send_ncmd, node_id)
        self.job: Optional[Job] = None
        self.recent: dict = {}

    def submit(self, body: Any) -> Any:
        """요청 본문 → Job (또는 FailedRequest). 다른 run_id 가 진행 중이면 Busy."""
        try:
            req = VerifyRequest.from_json(body)
        except ValueError as e:
            return FailedRequest(run_id_of(body), f"bad request: {e}")
        if self.job is not None and not self.job.done:
            if self.job.req.run_id == req.run_id:
                return self.job
            raise Busy(f"busy with {self.job.req.run_id}")
        if req.run_id in self.recent:
            return self.recent[req.run_id]
        self.job = Job(req, self.node_id, self.cfg, self.clock())
        self.recent[req.run_id] = self.job
        while len(self.recent) > self.RECENT_MAX:
            del self.recent[next(iter(self.recent))]
        self.job.step(self.tracker.node(self.node_id), self.clock(), self.cmd)
        return self.job

    def on_mqtt(self, topic: str, payload: bytes, now: Optional[float] = None) -> list:
        now = self.clock() if now is None else now
        events = self.tracker.handle(topic, payload, now)
        for ev in events:
            if ev.node == self.node_id and self.tracker.rebirth_due(self.node_id, now):
                self.cmd.rebirth()
        if events and self.job is not None:
            self.job.step(self.tracker.node(self.node_id), now, self.cmd)
        return events

    def tick(self, now: Optional[float] = None) -> None:
        now = self.clock() if now is None else now
        if self.tracker.rebirth_due(self.node_id, now):
            self.cmd.rebirth()
        if self.job is not None:
            self.job.step(self.tracker.node(self.node_id), now, self.cmd)

    def runner_snapshot(self) -> dict:
        n = self.tracker.node(self.node_id)
        if n is None:
            return {"online": False}
        return {"online": n.online, "state": n.get(STATE), "run_id": n.get(RUN_ID), "bd_seq": n.bd_seq,
                "devices": n.alive_devices(), "last_error": n.get(LAST_ERROR)}
