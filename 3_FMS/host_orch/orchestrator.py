"""검증 잡 수명 — sim.verify.request 1건 = sim-runner 런 1개 (+ fms-core 런 1개) (MQTT_CONTRACT §5.3 · 결정 4/11/14, SIM_VERIFY_CONTRACT).

Job: STARTING(NCMD Start → Runner/State RUNNING · RunId 일치 대기) → RUNNING(창 window_s) → STOPPING(NCMD Stop → IDLE)
→ DONE | FAILED. sim-runner 가 스스로 ERROR 로 접거나 NDEATH 면 FAILED. Start 는 QoS0 이라 반영이 없으면 재전송(멱등).
fms_node_id 를 주면 같은 Start/Stop 을 fms-core 에도 보내고, 창은 두 노드가 모두 RUNNING 일 때 시작한다(결정 11).
kpi 는 fms-core 가 Stop 뒤 `biz/v1/event` kpi_summary 로 내는 것을 그대로 싣는다. 순수 파이썬 — 발행은 콜백.
"""
from __future__ import annotations

import hashlib
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
ISAAC = "Runner/IsaacInstances"
SCENARIO_SHA = "Runner/ScenarioSha"
VIDEO_URL = "Runner/VideoUrl"          # t3_amr 엣지(-215)가 런 종료 NDATA 에 싣는 mp4 공개 URL → artifacts.video
FMS_STATE, FMS_RUN_ID, FMS_LAST_ERROR, FMS_TICK = "Fms/State", "Fms/RunId", "Fms/LastError", "Fms/Tick"
KPI_EVENT = "kpi_summary"
CMD_START, CMD_STOP, REBIRTH = "Run Control/Start", "Run Control/Stop", "Node Control/Rebirth"
IDLE, STARTING, RUNNING, STOPPING, ERROR = "IDLE", "STARTING", "RUNNING", "STOPPING", "ERROR"

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
MAX_ROBOTS = 64
DEFAULT_WINDOW_S = 600.0
START_MARGIN_S = 300.0          # sim-runner 쪽 timeout_s = window + 여유(기동 + 정지)
MAX_SCENARIO_BYTES = 512 * 1024   # sim-runner 와 같은 상한 (MQTT 패킷 1 MB 아래)


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def canonical_json(obj: Any) -> bytes:
    """sha 정규형 — 이 함수가 기준. fms_core.scenario.canonical_json 과 같은 규칙이어야 sha 가 맞는다 (구 sim_runner.procs 도 같았다, -219 로 삭제)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def scenario_sha256(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj)).hexdigest()


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
    scenario: Optional[dict] = None
    scenario_sha256: Optional[str] = None
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
        scenario = d.get("scenario")
        sha = None
        if scenario is not None:
            if not isinstance(scenario, dict):
                raise ValueError("scenario must be a JSON object")
            size = len(canonical_json(scenario))
            if size > MAX_SCENARIO_BYTES:
                raise ValueError(f"scenario too large: {size} B > {MAX_SCENARIO_BYTES}")
            sha = scenario_sha256(scenario)
        return VerifyRequest(run_id, n, str(d.get("scenario_pkg") or ""), tuple(models), domain, float(window),
                             float(timeout) if timeout is not None else None,
                             _opt_str(d.get("source_run_id")), _opt_int(d.get("estimate_id")),
                             _opt_int(d.get("seed")), _opt_int(d.get("priority")) or 0, scenario, sha, dict(d))

    def start_command(self) -> dict:
        """NCMD Run Control/Start JSON (MQTT_CONTRACT §5.3). scenario 는 sha 와 함께 실어 sim-runner 가 대조한다."""
        cmd = {"run_id": self.run_id, "scenario_pkg": self.scenario_pkg, "n_robots": self.n_robots,
               "models": [dict(m) for m in self.models], "ros_domain_id": self.ros_domain_id,
               "timeout_s": self.timeout_s if self.timeout_s is not None else self.window_s + START_MARGIN_S}
        if self.scenario is not None:
            cmd["scenario"], cmd["scenario_sha256"] = self.scenario, self.scenario_sha256
        return cmd


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
    isaac_max: int = 0
    runner_scenario_sha: str = ""
    video_url: str = ""

    def observe(self, node: Node) -> None:
        self.robots_online = max(self.robots_online, len(node.alive_devices()))
        url = node.get(VIDEO_URL)
        if isinstance(url, str) and url:
            self.video_url = url
        sha = node.get(SCENARIO_SHA)
        if isinstance(sha, str) and sha:
            self.runner_scenario_sha = sha
        isaac = node.get(ISAAC)
        if isinstance(isaac, int) and isaac > self.isaac_max:
            self.isaac_max = isaac
        rtf = node.get(RTF)
        if isinstance(rtf, (int, float)) and rtf > 0:
            self.rtf_samples.append(float(rtf))
        for name, attr in ((RAM, "ram_mb_max"), (VRAM, "vram_mb_max")):
            v = node.get(name)
            if isinstance(v, int) and v > getattr(self, attr):
                setattr(self, attr, v)


class FmsLink:
    """fms-core 쪽 런 추적 (결정 11). Start 를 반영할 때까지 재전송, 우리 run_id 로 RUNNING 이면 ready."""

    def __init__(self, node_id: str):
        self.node_id = node_id
        self.last_send: Optional[float] = None
        self.seen_ours = False
        self.ticks = 0
        self.summary: Optional[dict] = None       # kpi_summary 이벤트 본문

    def observe(self, node: Optional[Node]) -> tuple:
        """(online, state, run_id, last_error)."""
        if node is None or not node.online:
            return False, None, "", ""
        return True, node.get(FMS_STATE), node.get(FMS_RUN_ID), node.get(FMS_LAST_ERROR) or ""

    def note(self, node: Optional[Node]) -> None:
        tick = node.get(FMS_TICK) if node is not None else None
        if isinstance(tick, int) and tick > self.ticks:
            self.ticks = tick


class Job:
    """런 하나. step(node, now, cmd[, fms_node, fms_cmd]) 를 이벤트마다·tick 마다 부른다. cmd.start(json_text) / cmd.stop()."""

    def __init__(self, req: VerifyRequest, node_id: str, cfg: JobConfig, now: float, fms_node_id: Optional[str] = None):
        self.req, self.node_id, self.cfg = req, node_id, cfg
        self.phase = STARTING
        self.created_at, self.started_at, self.ended_at = now, None, None
        self.last_send, self.stop_sent_at, self.stop_resent = None, None, False
        self.seen_ours = False
        self.seen_online = False
        self.final = None                 # DONE | FAILED (STOPPING 이 끝나면 phase 가 이 값이 된다)
        self.reason, self.error = "", None
        self.stats = Stats()
        self.fms = FmsLink(fms_node_id) if fms_node_id else None
        self.kpi: Optional[dict] = None
        self._fms_node: Optional[Node] = None
        self._fms_cmd: Any = None

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
        if self._fms_cmd is not None:
            self._fms_cmd.stop()

    # ---- 진행 -------------------------------------------------------------------
    def step(self, node: Optional[Node], now: float, cmd: Any, fms_node: Optional[Node] = None, fms_cmd: Any = None) -> None:
        if self.done:
            return
        if node is not None and node.online:
            self.stats.observe(node)
        if self.fms is not None:
            self._fms_node, self._fms_cmd = fms_node, fms_cmd
            self.fms.note(fms_node)
        if self.phase == STARTING:
            self._step_starting(node, now, cmd)
        elif self.phase == RUNNING:
            self._step_running(node, now, cmd)
        elif self.phase == STOPPING:
            self._step_stopping(node, now, cmd)

    def on_biz_event(self, body: Any) -> bool:
        """fms-core 의 biz/v1/event. 우리 run_id 의 kpi_summary 면 kpi 를 받는다. 받았으면 True."""
        if self.fms is None or not isinstance(body, dict) or body.get("runId") != self.req.run_id:
            return False
        if body.get("type") != KPI_EVENT:
            return False
        self.fms.summary = body
        kpi = body.get("kpi")
        self.kpi = kpi if isinstance(kpi, dict) else None
        return True

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
            if st == RUNNING and self._fms_ready(now):
                self.phase, self.started_at = RUNNING, now
                return
        elif self.seen_ours and st in (IDLE, ERROR):
            self._finish("FAILED", now, "run ended before RUNNING", node.get(LAST_ERROR) or "ended by runner")
            return
        if self.done:                     # fms-core 쪽이 이미 접었다
            return
        busy = rid and rid != self.req.run_id and st in (STARTING, RUNNING, STOPPING)
        if not busy and not self.seen_ours and (self.last_send is None or now - self.last_send >= self.cfg.start_resend_s):
            self.last_send = now
            cmd.start(json.dumps(self.req.start_command()))
        if now - self.created_at > self.cfg.start_timeout_s:
            why = f"runner busy with {rid}" if busy else f"state={st} run_id={rid!r}"
            if self.seen_ours and st == RUNNING and self.fms is not None:
                online, fst, frid, ferr = self.fms.observe(self._fms_node)
                why = f"fms-core {'offline' if not online else f'state={fst} run_id={frid!r}'}"
            self._finish("FAILED", now, "start timeout", why)

    def _fms_ready(self, now: float) -> bool:
        """fms-core 가 없으면 True. 있으면 Start 를 (재)전송하고 우리 run_id 로 RUNNING 인지. ERROR 면 잡을 접고 False."""
        if self.fms is None:
            return True
        online, st, rid, err = self.fms.observe(self._fms_node)
        if not online:
            return False
        if rid == self.req.run_id:
            self.fms.seen_ours = True
            if st == RUNNING:
                return True
            if st == ERROR:
                self._finish("FAILED", now, "fms-core ended the run", err or "fms-core ERROR")
                return False
        elif self.fms.seen_ours and st in (IDLE, ERROR):
            self._finish("FAILED", now, "fms-core ended the run", err or "ended by fms-core")
            return False
        elif err.startswith("bad Start"):
            self._finish("FAILED", now, "fms-core rejected Start", err)
            return False
        busy = rid and rid != self.req.run_id and st in (STARTING, RUNNING)
        if not busy and not self.fms.seen_ours and self._fms_cmd is not None and (
                self.fms.last_send is None or now - self.fms.last_send >= self.cfg.start_resend_s):
            self.fms.last_send = now
            self._fms_cmd.start(json.dumps(self.req.start_command()))
        return False

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
        elif self.fms is not None and self._fms_running_fault(now, cmd):
            return
        elif now - self.started_at >= self.req.window_s:
            self._begin_stop(cmd, now, "DONE", "window elapsed")

    def _fms_running_fault(self, now: float, cmd: Any) -> bool:
        """RUNNING 중 fms-core 가 접었거나(ERROR·IDLE·NDEATH) 조용하면 잡을 접는다. 접었으면 True."""
        online, st, rid, err = self.fms.observe(self._fms_node)
        if not online:
            self._begin_stop(cmd, now, "FAILED", "fms-core NDEATH", "fms-core went offline during the run")
        elif rid != self.req.run_id or st in (IDLE, ERROR):
            self._begin_stop(cmd, now, "FAILED", "fms-core ended the run", (err if st == ERROR else "") or "fms-core ended the run")
        elif now - self._fms_node.last_seen > self.cfg.heartbeat_s * self.cfg.heartbeat_misses:
            self._begin_stop(cmd, now, "FAILED", "fms-core heartbeat lost", f"no NDATA from fms-core for {now - self._fms_node.last_seen:.0f}s")
        else:
            return False
        return True

    def _step_stopping(self, node: Optional[Node], now: float, cmd: Any) -> None:
        if node is None or not node.online:
            self._finish("FAILED", now, "runner NDEATH while stopping", "sim-runner went offline before confirming IDLE")
            return
        st, rid = node.get(STATE), node.get(RUN_ID)
        if st == ERROR:
            self._finish("FAILED", now, "runner ERROR while stopping", node.get(LAST_ERROR) or "runner ERROR")
        elif rid != self.req.run_id or st == IDLE:
            if self._fms_stopped(now):
                self._finish(self.final, now, self.reason, self.error)
        elif now - self.stop_sent_at > self.cfg.stop_timeout_s:
            if not self.stop_resent:
                self.stop_resent, self.stop_sent_at = True, now
                cmd.stop()
            else:
                self._finish("FAILED", now, "stop timeout", f"runner still {st} after 2 Stop commands")

    def _fms_stopped(self, now: float) -> bool:
        """fms-core 가 우리 run 을 놓았는가(IDLE/ERROR/다른 run_id/offline). Stop 뒤 stop_timeout 이 지나면 접고 True."""
        if self.fms is None:
            return True
        online, st, rid, _ = self.fms.observe(self._fms_node)
        if not online or rid != self.req.run_id or st in (IDLE, ERROR):
            return True
        if now - self.stop_sent_at > self.cfg.stop_timeout_s:
            self.final, self.reason, self.error = "FAILED", "fms stop timeout", f"fms-core still {st} after Stop"
            return True
        return False

    # ---- 결과 -------------------------------------------------------------------
    def result(self) -> dict:
        """sim.verify.result 본문 (SIM_VERIFY_CONTRACT §3). kpi 는 fms-core 의 kpi_summary, 없으면 null.
        artifacts.video 는 러너가 Runner/VideoUrl 로 준 mp4 URL(-215), 없으면 artifacts 는 null."""
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
                           "isaac_instances": s.isaac_max,
                           "scenario_sha256": self.req.scenario_sha256,
                           "scenario_ack": (self.req.scenario_sha256 is not None
                                            and s.runner_scenario_sha == self.req.scenario_sha256),
                           "reason": self.reason, "fms": self._fms_block()},
                "kpi": self.kpi, "artifacts": {"video": s.video_url} if s.video_url else None,
                "source_run_id": self.req.source_run_id, "estimate_id": self.req.estimate_id}

    def _fms_block(self) -> Optional[dict]:
        if self.fms is None:
            return None
        sm = self.fms.summary or {}
        return {"node": self.fms.node_id, "ticks": sm.get("ticks", self.fms.ticks), "status": sm.get("status"),
                "error": sm.get("error"), "planner": sm.get("planner"), "counters": sm.get("counters"),
                # 견적과 다른 조건으로 돌았다는 신호 (예: θ 파일 없음 → 중립 θ). null 이 아니면 이 KPI 는 견적과 비교하면 안 된다.
                "warnings": sm.get("warnings")}


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
                 cfg: JobConfig = JobConfig(), clock: Callable[[], float] = time.time, fms_node_id: Optional[str] = None):
        self.tracker, self.send_ncmd, self.node_id, self.cfg, self.clock = tracker, send_ncmd, node_id, cfg, clock
        self.cmd = Commands(send_ncmd, node_id)
        self.fms_node_id = fms_node_id or None
        self.fms_cmd = Commands(send_ncmd, self.fms_node_id) if self.fms_node_id else None
        self.job: Optional[Job] = None
        self.recent: dict = {}

    def _step_job(self, now: float) -> None:
        if self.job is not None:
            self.job.step(self.tracker.node(self.node_id), now, self.cmd,
                          self.tracker.node(self.fms_node_id) if self.fms_node_id else None, self.fms_cmd)

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
        self.job = Job(req, self.node_id, self.cfg, self.clock(), self.fms_node_id)
        self.recent[req.run_id] = self.job
        while len(self.recent) > self.RECENT_MAX:
            del self.recent[next(iter(self.recent))]
        self._step_job(self.clock())
        return self.job

    def on_mqtt(self, topic: str, payload: bytes, now: Optional[float] = None) -> list:
        now = self.clock() if now is None else now
        if topic.startswith("biz/v1/event"):
            self._on_biz_event(payload)
            return []
        events = self.tracker.handle(topic, payload, now)
        for ev in events:
            if ev.node == self.node_id and self.tracker.rebirth_due(self.node_id, now):
                self.cmd.rebirth()
            elif self.fms_cmd is not None and ev.node == self.fms_node_id and self.tracker.rebirth_due(self.fms_node_id, now):
                self.fms_cmd.rebirth()
        if events:
            self._step_job(now)
        return events

    def _on_biz_event(self, payload: bytes) -> None:
        try:
            body = json.loads(payload)
        except (ValueError, UnicodeDecodeError):
            return
        if self.job is not None and self.job.on_biz_event(body):
            return
        run_id = body.get("runId") if isinstance(body, dict) else None
        job = self.recent.get(run_id) if isinstance(run_id, str) else None
        if job is not None:                       # 결과를 이미 냈어도 늦게 온 kpi 는 잡에 남긴다 (재전달 시 결과에 실린다)
            job.on_biz_event(body)

    def tick(self, now: Optional[float] = None) -> None:
        now = self.clock() if now is None else now
        if self.tracker.rebirth_due(self.node_id, now):
            self.cmd.rebirth()
        if self.fms_cmd is not None and self.tracker.rebirth_due(self.fms_node_id, now):
            self.fms_cmd.rebirth()
        self._step_job(now)

    def runner_snapshot(self) -> dict:
        n = self.tracker.node(self.node_id)
        if n is None:
            return {"online": False}
        return {"online": n.online, "state": n.get(STATE), "run_id": n.get(RUN_ID), "bd_seq": n.bd_seq,
                "devices": n.alive_devices(), "last_error": n.get(LAST_ERROR)}

    def fms_snapshot(self) -> Optional[dict]:
        if not self.fms_node_id:
            return None
        n = self.tracker.node(self.fms_node_id)
        if n is None:
            return {"online": False}
        return {"online": n.online, "state": n.get(FMS_STATE), "run_id": n.get(FMS_RUN_ID), "tick": n.get(FMS_TICK),
                "last_error": n.get(FMS_LAST_ERROR)}
