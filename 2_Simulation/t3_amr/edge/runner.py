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

from . import gpu, spb, telemetry
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
# ★ 지금까지 돈 **시뮬 시각**(초). host-orch 가 창을 벽시계가 아니라 이 값으로
#   끊는다 (`orchestrator._step_running`). 벽시계로 끊으면 배속(0.33~1.64배)에
#   따라 같은 `window_s` 가 판마다 다른 분량을 담는다 — KPI 를 DES 와 비교할 때
#   분모가 달라진다. 못 읽으면 발행하지 않는다(= host-orch 는 벽시계로 후퇴).
SIM_TIME = "Runner/SimTime"
# (-215) 런이 끝나며 올린 mp4 를 가리킨다. 값은 URL 이 아니라 버킷 없는 객체 키 `<run_id>/<파일>` 이다(-233).
# host-orch 가 sim.verify.result.artifacts.video 로 그대로 옮긴다.
VIDEO_URL = "Runner/VideoUrl"
# ★★ 물리 지표 (-275) — 러너가 쓴 `physics_<run_id>.json`(path/physics_report.summarize)을 한 줄
#   JSON 문자열로. 영상 URL 과 **같은 NDATA** 에 실어 host-orch 가 런을 닫을 때 함께 본다
#   → `sim.verify.result.physics`. 모르는 host-orch 는 이름으로만 담아 두고 쓰지 않는다(tracker 가 범용).
PHYSICS = "Runner/Physics"

NODE_METRICS = {d.name: d for d in (
    MetricDef(BDSEQ, spb.INT64, 0, 0), MetricDef(REBIRTH, spb.BOOLEAN, 1, False),
    MetricDef(STATE, spb.STRING, 2, IDLE), MetricDef(RUN_ID, spb.STRING, 3, ""),
    MetricDef(HEARTBEAT, spb.INT64, 4, 0), MetricDef(RTF, spb.DOUBLE, 5, 0.0),
    MetricDef(ISAAC, spb.INT32, 6, 0), MetricDef(RAM, spb.INT32, 7, 0), MetricDef(VRAM, spb.INT32, 8, 0),
    MetricDef(LAST_ERROR, spb.STRING, 9, ""), MetricDef(CMD_START, spb.TEXT, 10, ""),
    MetricDef(CMD_STOP, spb.BOOLEAN, 11, False), MetricDef(SCENARIO_SHA, spb.STRING, 12, ""),
    MetricDef(VIDEO_URL, spb.STRING, 13, ""), MetricDef(SIM_TIME, spb.DOUBLE, 14, 0.0),
    MetricDef(PHYSICS, spb.STRING, 15, ""))}


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
                 executor: Executor | None = None, gpu_probe: Callable[[], str | None] = gpu.probe,
                 on_gpu_lost: Callable[[], None] | None = None):
        self.cfg, self.session, self.recorder_factory, self.pub = cfg, session, recorder_factory, publisher
        self.uploader, self.ram_mb, self.vram_mb = uploader, ram_mb, vram_mb
        # Start 직전 GPU 프로브(-241). 실패면 Kit 을 띄우지 않고 ERROR 보고 → on_gpu_lost (edge 는 프로세스를 내린다)
        self.gpu_probe, self.on_gpu_lost = gpu_probe, on_gpu_lost
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
        gpu_err = self.gpu_probe()
        if gpu_err is not None:
            log.error("run %s: GPU unavailable — %s (처방은 컨테이너 재시작, deploy/README.md)", spec.run_id, gpu_err)
            self._set_state(ERROR, {LAST_ERROR: f"gpu unavailable: {gpu_err}", RUN_ID: ""})
            if self.on_gpu_lost is not None:
                self.on_gpu_lost()
            return
        self.spec, self.rec, self.started_at, self.final_state = spec, self.recorder_factory(), now, IDLE
        try:
            self.rec.start(spec, now)
        except (OSError, RuntimeError, ValueError) as e:
            # ValueError — 인라인 궤적이 깨졌다(`spec.decode_trajectory`, -275). 엣지는 살려 두고 런만 실패
            self._set_state(ERROR, {LAST_ERROR: f"launch failed: {e}", RUN_ID: ""})
            return
        log.info("run %s: recording %d robots, window %.0fs (scenario %s)", spec.run_id, spec.n_robots, spec.window_s,
                 (spec.scenario_sha256 or "none")[:12])
        # ★ 시뮬 시각을 0 으로 되돌려 **같은 NDATA 로** 보낸다 (-279). 새 런은 첫 「[hl] sim」 줄(시뮬 10 s) 전까지
        #   시뮬 시각을 안 보내서, 지난 런의 660 s 가 host-orch 에 남아 이 런이 RUNNING 이 되자마자 「창 다 돌았다」로
        #   Stop 됐다(verify_20_n11·n12). host-orch 는 0 을 「아직 보고 없음」으로 읽는다(orchestrator.sim_time).
        self._set_state(STARTING, {RUN_ID: spec.run_id, LAST_ERROR: "", VIDEO_URL: "", PHYSICS: "",
                                   SCENARIO_SHA: spec.scenario_sha256 or "", SIM_TIME: 0.0})

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

    def _physics_str(self) -> str:
        """러너가 남긴 물리 지표를 한 줄 JSON 으로. 없으면 빈 문자열 (-275)."""
        doc = self.rec.physics() if self.rec else None
        return json.dumps(doc, ensure_ascii=False, separators=(",", ":")) if doc else ""

    def _finish(self) -> None:
        """레코더가 끝났다. 정상 종료면 mp4 를 워커 스레드로 올리기 시작하고(STOPPING 유지), 아니면 바로 최종 상태.

        물리 지표는 실패로 끝나도 싣는다 — 어디까지 돌다 멈췄는지가 진단 거리다.
        """
        extra = {RUN_ID: "", SCENARIO_SHA: "", PHYSICS: self._physics_str()}
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
        # ★ 측면이 있으면 **같이** 넘긴다 (-264). 없으면 None 이라 종전과 같다.
        fpv = self.rec.fpv_video_path()
        log.info("run %s: uploading %s%s", self.spec.run_id, path,
                 " (+ 1인칭)" if fpv else "")
        self._upload = self.executor.submit(
            self._upload_then_tidy, path, self.spec.run_id, self.rec, fpv)
        if self._upload.done():            # 동기 executor(테스트)면 같은 틱에 끝난다
            self._finish_upload()

    def _upload_then_tidy(self, path: str, run_id: str, rec: Recorder,
                          fpv: str | None = None) -> str:
        """워커 스레드: 업로드가 되면 프레임 PNG 를 지운다(런당 1.6~2.6 GB, -241). 실패 런의 것은 진단용으로 남는다.

        ★ 측면이 있으면 **상단 다음에** 올리고, **둘 다 끝난 뒤** 돌아온다
          (-264). 러너가 이 future 를 기다렸다가 상태를 넘기므로, 여기서
          기다리면 백엔드가 두 파일이 다 올라간 뒤에 결과를 본다.
          먼저 보고해도 동작은 하지만 화면을 한 번 더 열어야 버튼이 뜬다.

        ☹ 측면 실패가 런을 실패로 만들면 안 된다 — 백엔드가 기다리는 것은
          상단이고, 측면이 없으면 버튼만 안 생긴다. 경고만 남긴다.
        """
        url = self.uploader.upload(path, run_id)
        if fpv:
            try:
                skey = self.uploader.upload(fpv, run_id)
                log.info("run %s: fpv uploaded → %s", run_id, skey)
            except Exception as e:  # noqa: BLE001
                log.warning("run %s: fpv upload failed (버튼만 안 생긴다): %s", run_id, e)
        n = rec.remove_frames()
        log.info("run %s: uploaded → %s · removed %d frame file(s)", run_id, url, n)
        return url

    def _finish_upload(self) -> None:
        """업로드 결과 → URL 과 함께 IDLE, 실패면 ERROR. 어느 쪽이든 그 NDATA 하나로 host-orch 가 런을 닫는다."""
        fut, self._upload = self._upload, None
        extra = {RUN_ID: "", SCENARIO_SHA: "", PHYSICS: self._physics_str()}
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
        # 시뮬 시각 — 읽히는 판(헤드리스)에서만 싣는다. Kit 경로는 None 이라
        # 아예 안 보내고, host-orch 는 그 경우 벽시계로 창을 끊는다.
        sim_t = self.rec.sim_time() if self.rec else None
        if sim_t is not None:
            sample[SIM_TIME] = float(sim_t)
        return {k: v for k, v in sample.items() if v != self.values[k]}

    def snapshot(self) -> dict:
        return {"state": self.state, "run_id": self.values[RUN_ID], "last_error": self.values[LAST_ERROR],
                "video_url": self.values[VIDEO_URL], "bd_seq": self.session.bd_seq, "seq": self.session.seq}
