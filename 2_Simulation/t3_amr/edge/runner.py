"""엣지 상태기계 — MQTT_CONTRACT §5.2 메트릭 사전 · §5.3 NCMD · §5.4 세션 규칙. 브로커 없이 테스트한다.

상태: IDLE → STARTING(촬영 켜지기 대기) → RUNNING → STOPPING(SIGINT → mp4 조립 → 업로드) → IDLE | ERROR.
ERROR 는 IDLE 처럼 다음 Start 를 받는다. 로봇 디바이스 메트릭은 없다(에이전트 없음) — host-orch 의 robots_online 은 0.
영상 URL 은 STOPPING 을 벗어나는 그 NDATA 에 `Runner/VideoUrl` 로 같이 실린다 — host-orch 가 IDLE 과 URL 을 함께 본다.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from . import spb, telemetry
from .recorder import Recorder
from .spb import EdgeSession, MetricDef
from .spec import RunSpec
from .upload import Uploader

log = logging.getLogger("t3amr_edge")

IDLE, STARTING, RUNNING, STOPPING, ERROR = "IDLE", "STARTING", "RUNNING", "STOPPING", "ERROR"

BDSEQ, REBIRTH = "bdSeq", "Node Control/Rebirth"
STATE, RUN_ID, HEARTBEAT, RTF = "Runner/State", "Runner/RunId", "Runner/Heartbeat", "Runner/RTF"
ISAAC, RAM, VRAM, LAST_ERROR = "Runner/IsaacInstances", "Runner/RamMB", "Runner/VramMB", "Runner/LastError"
CMD_START, CMD_STOP = "Run Control/Start", "Run Control/Stop"
SCENARIO_SHA = "Runner/ScenarioSha"
VIDEO_URL = "Runner/VideoUrl"                # 신규(-215): 런이 끝나며 올린 mp4 의 공개 URL. host-orch → artifacts.video

NODE_METRICS = {d.name: d for d in (
    MetricDef(BDSEQ, spb.INT64, 0, 0), MetricDef(REBIRTH, spb.BOOLEAN, 1, False),
    MetricDef(STATE, spb.STRING, 2, IDLE), MetricDef(RUN_ID, spb.STRING, 3, ""),
    MetricDef(HEARTBEAT, spb.INT64, 4, 0), MetricDef(RTF, spb.DOUBLE, 5, 0.0),
    MetricDef(ISAAC, spb.INT32, 6, 0), MetricDef(RAM, spb.INT32, 7, 0), MetricDef(VRAM, spb.INT32, 8, 0),
    MetricDef(LAST_ERROR, spb.STRING, 9, ""), MetricDef(CMD_START, spb.TEXT, 10, ""),
    MetricDef(CMD_STOP, spb.BOOLEAN, 11, False), MetricDef(SCENARIO_SHA, spb.STRING, 12, ""),
    MetricDef(VIDEO_URL, spb.STRING, 13, ""))}


@dataclass(frozen=True)
class RunnerConfig:
    group: str = "santa"
    node_id: str = "sim-runner-gpu01"
    heartbeat_s: float = 5.0
    ready_timeout_s: float = 420.0           # Isaac 부팅(60~120 s) + 씬 로드 + 계획(REPLAN) + 첫 프레임
    host_offline_s: float = 15.0


class Runner:
    def __init__(self, cfg: RunnerConfig, session: EdgeSession, recorder_factory: Callable[[], Recorder],
                 publisher: Any, uploader: Uploader | None = None,
                 ram_mb: Callable = telemetry.ram_mb, vram_mb: Callable = telemetry.vram_mb,
                 executor: Executor | None = None):
        self.cfg, self.session, self.recorder_factory, self.pub = cfg, session, recorder_factory, publisher
        self.uploader, self.ram_mb, self.vram_mb = uploader, ram_mb, vram_mb
        # 업로드는 워커 스레드에서 — tick() 은 Edge 의 락을 쥐고 도니 여기서 기다리면
        # paho 스레드(Stop 재전송·keepalive)가 막힌다
        self.executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="t3amr-upload")
        self._upload: Future | None = None
        self.values = {name: d.initial for name, d in NODE_METRICS.items()}
        self.state = IDLE
        self.spec: RunSpec | None = None
        self.rec: Recorder | None = None
        self.started_at = 0.0
        self.last_heartbeat = 0.0
        self.final_state = IDLE
        self.host_online: bool | None = None
        self.host_ts = 0
        self.host_offline_since: float | None = None

    # ---- 토픽 · 발행 ------------------------------------------------------------
    def topic(self, kind: str) -> str:
        return f"spBv1.0/{self.cfg.group}/{kind}/{self.cfg.node_id}"

    def _pairs(self, names) -> list[tuple[MetricDef, Any]]:
        return [(NODE_METRICS[n], self.values[n]) for n in names]

    def publish_nbirth(self) -> None:
        self.session.seq = 0
        self.values[BDSEQ] = self.session.bd_seq
        payload = spb.encode_birth(self.session.next_seq(), self._pairs(NODE_METRICS))
        self.pub.publish(self.topic("NBIRTH"), payload, 0, False)

    def publish_ndata(self, changes: dict) -> None:
        self.values.update(changes)
        self.pub.publish(self.topic("NDATA"), spb.encode_data(self.session.next_seq(), self._pairs(changes)), 0, False)

    # ---- 인바운드 ----------------------------------------------------------------
    def on_connected(self, now: float) -> None:
        self.publish_nbirth()
        self.last_heartbeat = now

    def on_ncmd(self, payload: bytes, now: float) -> None:
        try:
            cmd = spb.metrics_by_name(spb.decode(payload))
        except Exception as e:  # noqa: BLE001 — 깨진 protobuf 는 무시하고 기록만
            log.warning("NCMD undecodable: %s", e)
            return
        if cmd.get(REBIRTH) is True:
            log.info("NCMD Rebirth")
            self.publish_nbirth()
        if cmd.get(CMD_STOP) is True:
            self.handle_stop(now)
        start = cmd.get(CMD_START)
        if isinstance(start, str) and start.strip():
            self.handle_start(start, now)

    def on_host_state(self, payload: bytes, now: float) -> None:
        try:
            d = json.loads(payload)
        except (ValueError, UnicodeDecodeError):
            log.debug("host STATE payload undecodable: %r", payload[:80])
            return
        if not isinstance(d, dict) or not isinstance(d.get("online"), bool):
            log.debug("host STATE payload ignored (not {online: bool}): %r", payload[:80])
            return
        online, ts = d["online"], d.get("timestamp", 0)
        came_back = online and (self.host_online is False or (self.host_online and ts > self.host_ts))
        self.host_online, self.host_ts = online, ts if isinstance(ts, int) else self.host_ts
        self.host_offline_since = None if online else (self.host_offline_since or now)
        if came_back:
            log.info("host-orch back online → rebirth")
            self.publish_nbirth()

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
        self.spec, self.rec, self.started_at, self.final_state = spec, self.recorder_factory(), now, IDLE
        try:
            self.rec.start(spec, now)
        except (OSError, RuntimeError) as e:
            self._set_state(ERROR, {LAST_ERROR: f"launch failed: {e}", RUN_ID: ""})
            return
        log.info("run %s: recording %d robots, window %.0fs (scenario %s)", spec.run_id, spec.n_robots, spec.window_s,
                 (spec.scenario_sha256 or "none")[:12])
        self._set_state(STARTING, {RUN_ID: spec.run_id, LAST_ERROR: "", VIDEO_URL: "",
                                   SCENARIO_SHA: spec.scenario_sha256 or ""})

    def handle_stop(self, now: float) -> None:
        if self.state in (STARTING, RUNNING):
            self._stop(now, IDLE, "")
        else:
            log.info("Stop while %s — nothing to do", self.state)

    def _stop(self, now: float, final_state: str, reason: str) -> None:
        log.info("run %s stopping → %s %s", self.spec.run_id if self.spec else "?", final_state, reason)
        self.final_state = final_state
        self.rec.request_stop(now)
        self._set_state(STOPPING, {LAST_ERROR: reason} if reason else {})

    def _fail(self, now: float, reason: str) -> None:
        log.error("run %s failed: %s", self.spec.run_id if self.spec else "?", reason)
        self._stop(now, ERROR, reason)

    def _set_state(self, state: str, extra: dict | None = None) -> None:
        self.state = state
        self.publish_ndata({STATE: state, **(extra or {})})

    # ---- 주기 --------------------------------------------------------------------
    def tick(self, now: float) -> None:
        if self.state == STARTING:
            self._tick_starting(now)
        elif self.state == RUNNING:
            self._tick_running(now)
        elif self.state == STOPPING:
            if self._upload is not None:
                if self._upload.done():
                    self._finish_upload()
            elif self.rec.poll_stop(now):
                self._finish()
        if now - self.last_heartbeat >= self.cfg.heartbeat_s:
            self.last_heartbeat = now
            self.publish_ndata({HEARTBEAT: int(now * 1000), **self._telemetry_changes()})

    def _tick_starting(self, now: float) -> None:
        if self.rec.dead():
            self._fail(now, "recorder exited during start (계획 없음·촬영 불가·Kit 기동 실패 — record 로그 확인)")
        elif self.rec.ready():
            log.info("run %s: capture on → RUNNING", self.spec.run_id)
            self._set_state(RUNNING)
        elif now - self.started_at > self.cfg.ready_timeout_s:
            self._fail(now, f"ready timeout {self.cfg.ready_timeout_s:g}s: no frames yet")

    def _tick_running(self, now: float) -> None:
        if self.rec.dead():
            if self.rec.finished_normally():
                log.info("run %s: recorder finished on its own → collecting", self.spec.run_id)
                self._stop(now, IDLE, "")
            else:
                self._fail(now, "recorder died")
        elif now - self.started_at > self.spec.timeout_s:
            self._fail(now, f"timeout_s {self.spec.timeout_s:g} elapsed")
        elif self.host_offline_since is not None and now - self.host_offline_since > self.cfg.host_offline_s:
            self._fail(now, f"host-orch offline > {self.cfg.host_offline_s:g}s")

    def _finish(self) -> None:
        """레코더가 끝났다. 정상 종료면 mp4 를 워커 스레드로 올리기 시작하고(STOPPING 유지), 아니면 바로 최종 상태."""
        extra = {RUN_ID: "", SCENARIO_SHA: ""}
        if self.final_state != IDLE:
            self._set_state(self.final_state, extra)
            return
        path = self.rec.video_path()
        if not path:
            err = "no video produced (프레임 0장 — record 로그의 '캡처' 줄 확인)"
            self._set_state(ERROR, {**extra, LAST_ERROR: err})
            return
        if self.uploader is None:
            log.warning("no uploader configured — video left at %s", path)
            self._set_state(IDLE, {**extra, VIDEO_URL: f"file://{path}"})
            return
        log.info("run %s: uploading %s", self.spec.run_id, path)
        self._upload = self.executor.submit(self.uploader.upload, path, self.spec.run_id)
        if self._upload.done():            # 동기 executor(테스트)면 같은 틱에 끝난다
            self._finish_upload()

    def _finish_upload(self) -> None:
        """업로드 결과 → URL 과 함께 IDLE, 실패면 ERROR. 어느 쪽이든 그 NDATA 하나로 host-orch 가 런을 닫는다."""
        fut, self._upload = self._upload, None
        extra = {RUN_ID: "", SCENARIO_SHA: ""}
        try:
            url = fut.result()
        except Exception as e:  # noqa: BLE001 — 업로드 실패는 런 실패로 보고한다
            log.error("run %s: upload failed: %s", self.spec.run_id if self.spec else "?", e)
            self._set_state(ERROR, {**extra, LAST_ERROR: f"upload failed: {e}"})
            return
        self._set_state(IDLE, {**extra, VIDEO_URL: url})

    def _telemetry_changes(self) -> dict:
        pids = self.rec.pids() if self.rec else []
        vram = self.vram_mb()
        sample = {ISAAC: self.rec.isaac_count() if self.rec else 0,
                  RAM: self.ram_mb(pids) if pids else 0, VRAM: vram if vram is not None else self.values[VRAM]}
        return {k: v for k, v in sample.items() if v != self.values[k]}

    def snapshot(self) -> dict:
        return {"state": self.state, "run_id": self.values[RUN_ID], "last_error": self.values[LAST_ERROR],
                "video_url": self.values[VIDEO_URL], "bd_seq": self.session.bd_seq, "seq": self.session.seq}
