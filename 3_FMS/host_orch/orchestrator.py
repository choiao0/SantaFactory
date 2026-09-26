"""검증 잡 수명 — sim.verify.request 1건 = sim-runner 런 1개 (+ fms-core 런 1개) (MQTT_CONTRACT §5.3 · 결정 4/11/14, SIM_VERIFY_CONTRACT).

Job: STARTING(NCMD Start → Runner/State RUNNING · RunId 일치 대기) → RUNNING(창 window_s) → STOPPING(NCMD Stop → IDLE)
→ DONE | FAILED. sim-runner 가 스스로 ERROR 로 접거나 NDEATH 면 FAILED. Start 는 QoS0 이라 반영이 없으면 재전송(멱등).
fms_node_id 를 주면 같은 Start/Stop 을 fms-core 에도 보내고, 창은 두 노드가 모두 RUNNING 일 때 시작한다(결정 11).
kpi 는 fms-core 가 Stop 뒤 `biz/v1/event` kpi_summary 로 내는 것을 그대로 싣는다. 순수 파이썬 — 발행은 콜백.

Coordinator 는 러너 노드를 **여러 개**(sim-runner-gpu01..0N) 들고 있다가 비어 있는 노드에 한 건씩 배정한다
(GPU 1대에서 컨테이너 N개, spec244 §E). fms-core 는 브로커에 하나뿐이라 여러 노드 중 **첫 노드의 잡에만** 묶는다(§3).
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Sequence, Union

from . import spb
from .tracker import HostTracker, Node

log = logging.getLogger("host_orch.orchestrator")

STATE, RUN_ID, HEARTBEAT, RTF = "Runner/State", "Runner/RunId", "Runner/Heartbeat", "Runner/RTF"
RAM, VRAM, LAST_ERROR = "Runner/RamMB", "Runner/VramMB", "Runner/LastError"
ISAAC = "Runner/IsaacInstances"
SCENARIO_SHA = "Runner/ScenarioSha"
VIDEO_URL = "Runner/VideoUrl"          # t3_amr 엣지(-215)가 런 종료 NDATA 에 싣는 mp4 공개 URL → artifacts.video
# ★★ 러너가 지금까지 돈 **시뮬 시각**(초). 창을 이 값으로 끊는다 (2026-09-22).
#
#   예전에는 창이 벽시계였다 — `now - started_at >= window_s`. 그런데 배속(RTF)이
#   판마다 0.33~1.64배로 달라서 **같은 `window_s` 가 판마다 다른 분량**을 돌았다.
#   13대 실측에서 벽시계 600 s 창이 시뮬 219 s, 즉 창의 36 %만 담았다. 그 상태로
#   KPI 를 DES 와 비교하면 분모가 서로 다르다 — 견적은 시뮬 초로 계산한다.
#
#   러너가 이 값을 안 보내면(Kit `--exec` 경로는 시뮬 시각을 로그에 안 찍는다)
#   예전처럼 벽시계로 끊는다. 보내는 판에서는 벽시계가 백스톱이다.
SIM_TIME = "Runner/SimTime"
# ★★ 물리 지표 JSON 문자열(-275 엣지가 씀) — 구간(피크) 재생이 끝나면 접촉·간격·지연률·대기·완료 태스크를
#   담아 한 줄로 싣는다. host-orch 는 파싱만 해서 result() 의 physics 로 옮긴다 (2026-09-26, -244).
PHYSICS = "Runner/Physics"
FMS_STATE, FMS_RUN_ID, FMS_LAST_ERROR, FMS_TICK = "Fms/State", "Fms/RunId", "Fms/LastError", "Fms/Tick"
KPI_EVENT = "kpi_summary"
CMD_START, CMD_STOP, REBIRTH = "Run Control/Start", "Run Control/Stop", "Node Control/Rebirth"
IDLE, STARTING, RUNNING, STOPPING, ERROR = "IDLE", "STARTING", "RUNNING", "STOPPING", "ERROR"

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
MAX_ROBOTS = 64
DEFAULT_WINDOW_S = 600.0
START_MARGIN_S = 300.0          # sim-runner 쪽 timeout_s = window + 여유(기동 + 정지)
# 900 KiB — sim-runner 엣지(t3_amr/edge/spec.py)와 같은 상한. 512 KiB 였는데 DES 피크 구간 궤적을
# 인라인(scenario.trajectory_gz_b64)으로 실으면 10대 ≈ 300 KiB · 15대 ≈ 440 KiB 로 차서 올렸다(-244).
MAX_SCENARIO_BYTES = 900 * 1024
ORDER_WINDOW_MARGIN_S = 60.0      # 창 뒤 여유 — 러너의 계획 여유(t3_amr edge/recorder HORIZON_MARGIN_S)와 같다
WARMUP_DEFAULT_S = 60.0           # scenario.slice.warmup_s 기본값 — verify_slice 워밍업(t3_amr edge/recorder)과 같다
# 궤적 재생 기본 timeout_s 의 배속 하한. 동시 3대 실측 배속 0.8(spec244 §E)보다 낮춰 여유를 둔다.
TRAJ_TIMEOUT_RTF_FLOOR = 0.5


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def canonical_json(obj: Any) -> bytes:
    """sha 정규형 — 이 함수가 기준. fms_core.scenario.canonical_json 과 같은 규칙이어야 sha 가 맞는다 (구 sim_runner.procs 도 같았다, -219 로 삭제)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def scenario_sha256(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj)).hexdigest()


def slice_orders_to_window(scenario: dict, window_s: float) -> dict:
    """`scenario.orders.outbound` 를 창 [t0, t0 + window_s + ORDER_WINDOW_MARGIN_S] 로 자른 **새** scenario (-235).

    러너는 창만 재현하므로 하루치 주문(6,000 건 ≈ 586 KB)을 통째로 NCMD 에 실을 이유가 없다 — 2026-09-16 첫 버튼이
    MAX_SCENARIO_BYTES 에 걸려 거절된 원인. t0 = `window_start_s`(있으면) 아니면 첫 주문 시각(SIM_VERIFY §6 ① 의
    "저장 주문 기준"). 잘라낸 scenario 에는 `window_start_s = t0` 와 `orders.window` {start_s, end_s, kept, total} 를
    적는다. outbound 가 없거나 형식이 다르면 손대지 않는다(러너·fms-core 가 판단). 입력은 바꾸지 않는다.
    """
    orders = scenario.get("orders")
    if not isinstance(orders, dict) or not isinstance(orders.get("outbound"), list):
        return scenario
    outbound = orders["outbound"]
    if not all(isinstance(o, dict) and _is_num(o.get("ordered_at_s")) for o in outbound):
        return scenario
    ws = scenario.get("window_start_s")
    t0 = float(ws) if _is_num(ws) else (float(min(o["ordered_at_s"] for o in outbound)) if outbound else 0.0)
    t1 = t0 + float(window_s) + ORDER_WINDOW_MARGIN_S
    kept = [o for o in outbound if t0 <= o["ordered_at_s"] <= t1]
    window = {"start_s": t0, "end_s": t1, "kept": len(kept), "total": len(outbound)}
    return {**scenario, "window_start_s": t0, "orders": {**orders, "outbound": kept, "window": window}}


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
    is_trajectory: bool = False      # scenario.trajectory_gz_b64 가 있었나 — 있으면 주문 자르기를 생략했다(-244)
    warmup_s: float = WARMUP_DEFAULT_S    # scenario.slice.warmup_s (궤적일 때만 뜻이 있다)
    raw: dict = field(default_factory=dict, compare=False)

    def effective_timeout_s(self) -> float:
        """NCMD Start 에 실을 timeout_s — 명시 값이 있으면 그대로, 없으면 궤적/주문별 기본값 (SIM_VERIFY_CONTRACT §2, -244).

        궤적 재생은 창 앞에 warmup_s 만큼 예열이 붙고, 배속이 느릴 때를 버틸 여유가 필요하다 —
        배속 하한 TRAJ_TIMEOUT_RTF_FLOOR 로 계산한 벽시계 위에 시작/정지 여유(START_MARGIN_S)를 얹는다.
        주문 기반(폴백) 요청은 종전처럼 window_s + START_MARGIN_S."""
        if self.timeout_s is not None:
            return self.timeout_s
        if self.is_trajectory:
            return math.ceil((self.warmup_s + self.window_s) / TRAJ_TIMEOUT_RTF_FLOOR) + START_MARGIN_S
        return self.window_s + START_MARGIN_S

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
        is_trajectory, warmup_s = False, WARMUP_DEFAULT_S
        if scenario is not None:
            if not isinstance(scenario, dict):
                raise ValueError("scenario must be a JSON object")
            is_trajectory, warmup_s = _trajectory_meta(scenario)
            if not is_trajectory:
                # 궤적이 없는 요청(구 견적 등)은 종전처럼 주문을 창으로 자른다(B §1 폴백) — 궤적이 있으면
                # 배정 결과가 이미 담겨 있어 자를 이유가 없다. sha 는 실제로 보내는 scenario 그대로에 낸다.
                scenario = slice_orders_to_window(scenario, float(window))
            size = len(canonical_json(scenario))
            if size > MAX_SCENARIO_BYTES:
                raise ValueError(f"scenario too large: {size} B > {MAX_SCENARIO_BYTES}")
            sha = scenario_sha256(scenario)
        return VerifyRequest(run_id, n, str(d.get("scenario_pkg") or ""), tuple(models), domain, float(window),
                             float(timeout) if timeout is not None else None,
                             _opt_str(d.get("source_run_id")), _opt_int(d.get("estimate_id")),
                             _opt_int(d.get("seed")), _opt_int(d.get("priority")) or 0, scenario, sha,
                             is_trajectory, warmup_s, dict(d))

    def start_command(self) -> dict:
        """NCMD Run Control/Start JSON (MQTT_CONTRACT §5.3). scenario 는 sha 와 함께 실어 sim-runner 가 대조한다."""
        cmd = {"run_id": self.run_id, "scenario_pkg": self.scenario_pkg, "n_robots": self.n_robots,
               "models": [dict(m) for m in self.models], "ros_domain_id": self.ros_domain_id,
               "timeout_s": self.effective_timeout_s()}
        if self.scenario is not None:
            cmd["scenario"], cmd["scenario_sha256"] = self.scenario, self.scenario_sha256
        return cmd


def _trajectory_meta(scenario: dict) -> tuple:
    """scenario.trajectory_gz_b64 가 있으면 (True, warmup_s), 없으면 (False, WARMUP_DEFAULT_S) (B §1, -244).

    값은 존재·비어있지 않은 문자열인지만 본다 — **디코드하지 않는다**(gzip 여부·궤적 형식 검사는 러너 몫,
    host-orch 가 풀면 900 KiB 상한을 우회하는 폭탄까지 떠안는다). warmup_s 는 scenario.slice.warmup_s,
    없으면 기본값(엣지 verify_slice 기본값과 같다)."""
    traj = scenario.get("trajectory_gz_b64")
    if traj is None:
        return False, WARMUP_DEFAULT_S
    if not isinstance(traj, str) or not traj:
        raise ValueError("scenario.trajectory_gz_b64 must be a non-empty string")
    warmup = WARMUP_DEFAULT_S
    sl = scenario.get("slice")
    if isinstance(sl, dict) and _is_num(sl.get("warmup_s")):
        warmup = float(sl["warmup_s"])
    return True, warmup


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
    physics_raw: str = ""       # Runner/Physics 원문(JSON 문자열) — 파싱은 Job.result() 에서 한 번만

    def observe(self, node: Node, accept_run_scoped: bool) -> None:
        """accept_run_scoped 가 False 면 VideoUrl·Physics 는 무시한다 — 노드가 아직 **이전 런**의 값을
        들고 있을 수 있어서다(우리 run_id 를 아직 못 봄). 노드는 런이 끝나야 이 메트릭을 새로 쓰므로,
        먼저 이 잡의 run_id 를 한 번이라도 본 뒤에만 받으면 이전 런 값이 새 결과로 새지 않는다 (-244)."""
        self.robots_online = max(self.robots_online, len(node.alive_devices()))
        if accept_run_scoped:
            url = node.get(VIDEO_URL)
            if isinstance(url, str) and url:
                self.video_url = url
            physics = node.get(PHYSICS)
            if isinstance(physics, str) and physics:
                self.physics_raw = physics
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
            self.stats.observe(node, self._run_scoped(node))
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
        elif self._window_filled(node):
            self._begin_stop(cmd, now, "DONE", "window elapsed")
        elif self.sim_time(node) is None and now - self.started_at >= self.req.window_s:
            # 시뮬 시각을 안 보내는 러너 — 예전처럼 벽시계로 끊는다
            self._begin_stop(cmd, now, "DONE", "window elapsed")
        elif now - self.started_at >= self._wall_backstop():
            # 시뮬 시각이 창을 못 채운 채 벽시계가 다 갔다. 창을 덜 돈 판을
            # 조용히 DONE 으로 적으면 KPI 분모가 DES 와 달라진다 — 그게 이
            # 변경 이전의 동작이었다. 여기서는 실패로 적고 이유를 남긴다.
            self._begin_stop(cmd, now, "FAILED", "wall-clock backstop",
                             f"sim {self.sim_time(node)}s of {self.req.window_s:g}s "
                             f"after {now - self.started_at:.0f}s wall")

    def sim_time(self, node: Optional[Node]) -> Optional[float]:
        """러너가 보고한 시뮬 시각(초). 안 보내면 None — 그러면 벽시계로 후퇴한다.

        0.0 은 **안 보낸 것으로 본다.** NBIRTH 가 모든 메트릭을 기본값으로 한 번
        싣기 때문에, 0 을 「시뮬 0초를 돌았다」로 읽으면 벽시계 후퇴가 막힌다."""
        if node is None:
            return None
        v = node.get(SIM_TIME)
        if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        return float(v) if v > 0 else None

    def _window_filled(self, node: Optional[Node]) -> bool:
        """창을 다 돌았나 — **시뮬 시각 기준**. 보고가 없으면 False(호출부가 벽시계로 간다)."""
        sim = self.sim_time(node)
        return sim is not None and sim >= self.req.window_s

    def _wall_backstop(self) -> float:
        """시뮬 시각으로 끊는 판의 벽시계 한계. 러너 자신의 `timeout_s` **뒤**다 —
        러너가 스스로 접을 기회를 먼저 주고, 그래도 안 끝나면 여기서 잡는다."""
        return self.req.effective_timeout_s() + self.cfg.stop_timeout_s

    def _run_scoped(self, node: Node) -> bool:
        """이 잡의 run_id 를 확인한 뒤에만 True — VideoUrl·Physics 는 이때부터만 받는다.

        노드가 아직 **이전 런**의 값을 들고 있는 채로 STARTING 을 도는 동안 무심코 읽으면, 이번 런이
        실패해서 자기 값을 못 남겨도 지난 런의 값이 결과에 새는 버그가 된다(-244). `seen_ours` 는 한
        번 True 가 되면 계속 True 라 STOPPING 의 마지막 NDATA(run_id 가 이미 비워진)에서도 받는다."""
        return self.seen_ours or (node.get(STATE) == RUNNING and node.get(RUN_ID) == self.req.run_id)

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
        artifacts.video 는 러너가 Runner/VideoUrl 로 준 mp4 URL(-215), 없으면 artifacts 는 null.
        physics 는 Runner/Physics 를 파싱한 객체, 없거나 깨졌으면 null(-244, C)."""
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
                "physics": self._physics(),
                "source_run_id": self.req.source_run_id, "estimate_id": self.req.estimate_id}

    def _fms_block(self) -> Optional[dict]:
        if self.fms is None:
            return None
        sm = self.fms.summary or {}
        return {"node": self.fms.node_id, "ticks": sm.get("ticks", self.fms.ticks), "status": sm.get("status"),
                "error": sm.get("error"), "planner": sm.get("planner"), "counters": sm.get("counters"),
                # 견적과 다른 조건으로 돌았다는 신호 (예: θ 파일 없음 → 중립 θ). null 이 아니면 이 KPI 는 견적과 비교하면 안 된다.
                "warnings": sm.get("warnings")}

    def _physics(self) -> Optional[dict]:
        """Runner/Physics(JSON 문자열) → 객체. 없으면 null, 파싱에 실패하거나 객체가 아니면 경고만 남기고 null (-244)."""
        raw = self.stats.physics_raw
        if not raw:
            return None
        try:
            obj = json.loads(raw)
        except (ValueError, TypeError):
            log.warning("run %s: Runner/Physics is not valid JSON (%d chars) — reporting physics=null",
                       self.req.run_id, len(raw))
            return None
        if not isinstance(obj, dict):
            log.warning("run %s: Runner/Physics is not a JSON object — reporting physics=null", self.req.run_id)
            return None
        return obj


class FailedRequest:
    """파싱 실패한 요청 — 결과 큐에 failed 로 바로 내보낸다(명세 §1-2: 실패도 정상 발행).

    estimate_id · source_run_id 는 본문에서 그대로 옮긴다 — 없으면 BE 가 어느 견적의 실패인지 몰라 결과를 버리고
    화면이 "검증 중" 으로 굳는다 (2026-09-16 verify_2, -235).
    """

    def __init__(self, run_id: Optional[str], error: str, estimate_id: Optional[int] = None,
                 source_run_id: Optional[str] = None):
        self.run_id, self.error, self.phase, self.done = run_id, error, "FAILED", True
        self.estimate_id, self.source_run_id = estimate_id, source_run_id

    def result(self) -> dict:
        return {"run_id": self.run_id, "status": "failed", "error": self.error, "verify": None,
                "kpi": None, "artifacts": None, "physics": None,
                "source_run_id": self.source_run_id, "estimate_id": self.estimate_id}


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


def _raw_fields(body: Any) -> dict:
    """파싱에 실패한 본문에서도 식별자는 건진다 — JSON 객체가 아니면 빈 dict."""
    try:
        d = json.loads(body)
    except Exception:  # noqa: BLE001
        return {}
    return d if isinstance(d, dict) else {}


def run_id_of(body: Any) -> Optional[str]:
    return _opt_str(_raw_fields(body).get("run_id"))


def failed_request(body: Any, error: str) -> "FailedRequest":
    """본문을 못 읽어도 식별자(run_id · estimate_id · source_run_id)는 건져 실패 결과에 싣는다 (-235)."""
    raw = _raw_fields(body)
    return FailedRequest(run_id_of(body), error, _opt_int(raw.get("estimate_id")), _opt_str(raw.get("source_run_id")))


class Coordinator:
    """tracker + 러너 노드마다 잡 한 개(spec244 §E: GPU 1대 · 컨테이너 N개, 노드당 한 건).
    MQTT 스레드와 AMQP 루프가 같은 락으로 부른다.

    노드는 `node_ids` 로 여러 개 줄 수 있다(문자열 하나도 받는다 — 노드 1개인 기존 배치는 그대로 동작).
    비어 있는(온라인 · IDLE/ERROR · 활성 잡 없음 · 대기 중인 Rebirth 없음) 노드를 목록 순서대로 찾아 배정한다.
    fms-core 는 브로커에 하나뿐이라 **첫 노드의 잡에만** 묶는다(-244) — 노드가 여럿이면 나머지 잡은 fms-core
    없이 sim-runner 만으로 돈다(§4 kpi 는 null).

    재전달(채널 단절 뒤 RabbitMQ 가 unacked 를 다시 줌)에 멱등: 진행 중인 같은 run_id 는(어느 노드든) 그 잡을,
    **done 으로 끝난** run_id(최근 50개, 노드 불문 전역)는 끝난 잡을 돌려줘 결과만 다시 발행한다 — GPU 런을
    두 번 돌리지 않는다.

    failed 로 끝난 run_id 는 다시 돌린다(-241). BE 는 run_id 를 견적 id 로 고정하므로, 실패한 견적의 재검증 요청이 여기서
    옛 실패 결과로 되돌아오면 host-orch 를 재시작하는 것 말고는 길이 없었다 (2026-09-17 verify_7 09:08 실측). 재전달로
    실패 런이 한 번 더 도는 경우는 어차피 결과가 필요한 상황이라 받아들인다.
    """
    RECENT_MAX = 50

    def __init__(self, tracker: HostTracker, send_ncmd: Callable[[str, list], None],
                 node_id: Union[str, Sequence[str]], cfg: JobConfig = JobConfig(),
                 clock: Callable[[], float] = time.time, fms_node_id: Optional[str] = None):
        self.tracker, self.send_ncmd, self.cfg, self.clock = tracker, send_ncmd, cfg, clock
        self.node_ids = (node_id,) if isinstance(node_id, str) else tuple(node_id)
        if not self.node_ids:
            raise ValueError("Coordinator needs at least one runner node_id")
        self.cmds = {nid: Commands(send_ncmd, nid) for nid in self.node_ids}
        self.fms_node_id = fms_node_id or None
        if self.fms_node_id and len(self.node_ids) > 1:
            log.info("fms-core(%s) is linked only to %s — the other %d runner node(s) run without it",
                     self.fms_node_id, self.node_ids[0], len(self.node_ids) - 1)
        self.fms_cmd = Commands(send_ncmd, self.fms_node_id) if self.fms_node_id else None
        self.jobs: dict = {}         # node_id -> Job (활성 또는 막 끝난 마지막 잡)
        self.recent: dict = {}       # run_id -> Job, 노드 불문 전역 (멱등·재전달용)

    def _fms_args(self, node_id: str) -> tuple:
        """이 노드의 잡에 fms-core 를 묶을지 — 첫 노드일 때만(-244)."""
        if self.fms_node_id and node_id == self.node_ids[0]:
            return self.fms_node_id, self.tracker.node(self.fms_node_id), self.fms_cmd
        return None, None, None

    def _step_node(self, node_id: str, now: float) -> None:
        job = self.jobs.get(node_id)
        if job is None:
            return
        _, fms_node, fms_cmd = self._fms_args(node_id)
        job.step(self.tracker.node(node_id), now, self.cmds[node_id], fms_node, fms_cmd)

    def _step_all(self, now: float) -> None:
        for node_id in self.node_ids:
            self._step_node(node_id, now)

    def _pick_node(self) -> Optional[str]:
        """비어 있는 노드 하나 — 온라인 · IDLE/ERROR · 활성 잡 없음 · 대기 중인 Rebirth 없음(spec244 §E).
        없으면 None(호출자가 Busy)."""
        for node_id in self.node_ids:
            job = self.jobs.get(node_id)
            if job is not None and not job.done:
                continue
            node = self.tracker.node(node_id)
            if node is None or not node.online or node.needs_rebirth:
                continue
            if node.get(STATE) not in (IDLE, ERROR):
                continue
            return node_id
        return None

    def submit(self, body: Any) -> Any:
        """요청 본문 → Job (또는 FailedRequest). 비어 있는 노드가 없으면 Busy."""
        try:
            req = VerifyRequest.from_json(body)
        except ValueError as e:
            return failed_request(body, f"bad request: {e}")
        for job in self.jobs.values():
            if job is not None and not job.done and job.req.run_id == req.run_id:
                return job                                 # 어느 노드든 같은 run_id 가 진행 중이면 그 잡
        prior = self.recent.get(req.run_id)
        if prior is not None and prior.phase == "DONE":
            return prior                                   # 결과만 재발행. FAILED 는 아래로 — 새 런 (-241)
        node_id = self._pick_node()
        if node_id is None:
            raise Busy(f"no idle runner node among {', '.join(self.node_ids)}")
        fms_node_id, _, _ = self._fms_args(node_id)
        now = self.clock()
        job = Job(req, node_id, self.cfg, now, fms_node_id)
        self.jobs[node_id] = job
        self.recent[req.run_id] = job
        while len(self.recent) > self.RECENT_MAX:
            del self.recent[next(iter(self.recent))]
        self._step_node(node_id, now)
        return job

    def on_mqtt(self, topic: str, payload: bytes, now: Optional[float] = None) -> list:
        now = self.clock() if now is None else now
        if topic.startswith("biz/v1/event"):
            self._on_biz_event(payload)
            return []
        events = self.tracker.handle(topic, payload, now)
        for ev in events:
            if ev.node in self.cmds and self.tracker.rebirth_due(ev.node, now):
                self.cmds[ev.node].rebirth()
            elif self.fms_cmd is not None and ev.node == self.fms_node_id and self.tracker.rebirth_due(self.fms_node_id, now):
                self.fms_cmd.rebirth()
        if events:
            self._step_all(now)
        return events

    def _on_biz_event(self, payload: bytes) -> None:
        try:
            body = json.loads(payload)
        except (ValueError, UnicodeDecodeError):
            return
        for job in self.jobs.values():
            if job is not None and job.on_biz_event(body):
                return
        run_id = body.get("runId") if isinstance(body, dict) else None
        job = self.recent.get(run_id) if isinstance(run_id, str) else None
        if job is not None:                       # 결과를 이미 냈어도 늦게 온 kpi 는 잡에 남긴다 (재전달 시 결과에 실린다)
            job.on_biz_event(body)

    def tick(self, now: Optional[float] = None) -> None:
        now = self.clock() if now is None else now
        for node_id in self.node_ids:
            if self.tracker.rebirth_due(node_id, now):
                self.cmds[node_id].rebirth()
        if self.fms_cmd is not None and self.tracker.rebirth_due(self.fms_node_id, now):
            self.fms_cmd.rebirth()
        self._step_all(now)

    def runner_snapshot(self, node_id: Optional[str] = None) -> dict:
        """노드 하나의 스냅샷 — 생략하면 첫 노드(단일 노드 배치와 호환)."""
        n = self.tracker.node(node_id or self.node_ids[0])
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
