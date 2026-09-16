"""MQTT 연결부 + CLI — paho 클라이언트를 Runner 에 잇는다.  `python -m edge` (컨테이너 entrypoint 가 부른다)

세션 규칙(§5.4): 접속(재접속) 전마다 bdSeq+1 로 NDEATH 유언을 새로 걸고, 접속되면 NBIRTH.
paho 의 자동 재접속은 on_disconnect 뒤에 일어나므로 거기서 유언을 갈아 끼운다. 정상 종료는 NDEATH 를 직접 발행한다.
비밀번호는 argv 가 아니라 환경(MQTT_PW_SIM_RUNNER, 또는 --env-file)에서만 받는다. MinIO 키도 환경(MINIO_*)이다.
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

import paho.mqtt.client as mqtt
import psutil

from . import spb, telemetry
from .recorder import DEFAULT_TICK_S, RUN_ENV_MARK, Recorder, RecorderConfig
from .runner import RUNNING, STARTING, STOPPING, Runner, RunnerConfig
from .spb import EdgeSession
from .upload import Uploader

log = logging.getLogger("t3amr_edge")

T3AMR_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # edge/ 의 부모 = t3_amr
DEFAULT_STATE_DIR = os.environ.get("T3AMR_STATE") or os.path.expanduser("~/.local/state/t3amr_edge")
KEEPALIVE_S = 60          # MQTT_CONTRACT §0: sim-runner 60 s
TICK_S = 0.5
SHUTDOWN_GRACE_S = 300.0  # 종료 신호 뒤 런 정리(SIGINT → 조립 → 업로드) 상한
VRAM_PERIOD_S = 5.0
NODE_SUBSCRIPTIONS = (("NCMD", 0),)                       # ACL: NCMD/<node>
EXTRA_SUBSCRIPTIONS = (("spBv1.0/STATE/+", 1),)


def load_env_file(path: str) -> dict:
    """KEY=VALUE 파일(.env). 이미 있는 환경변수는 덮지 않는다."""
    loaded = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value
                loaded[key] = value
    return loaded


def reap_stale(process_iter: Callable = psutil.process_iter, send: Callable[[int, int], None] | None = None,
               me: int | None = None) -> list[tuple[int, str]]:
    """지난 엣지가 남긴 런 프로세스(환경에 SIM_RUN_ID)를 그룹째 SIGKILL — 데몬 재시작 때 한 번. [(pid, run_id)]."""
    def _kill(pid: int, sig: int) -> None:
        for fn in (os.killpg, os.kill):
            try:
                fn(pid, sig)
            except (ProcessLookupError, PermissionError):
                pass
    send = send or _kill
    me = os.getpid() if me is None else me
    found = []
    for p in process_iter():
        try:
            run_id = p.environ().get(RUN_ENV_MARK)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        if run_id and p.pid != me:
            found.append((p.pid, run_id))
    for pid, _ in found:
        send(pid, signal.SIGKILL)
    return found


class Edge:
    def __init__(self, node_id: str, username: str, password: str, session: EdgeSession, alive_path: str,
                 client: Any = None):
        self.session, self.alive_path = session, alive_path
        self._runner: Runner | None = None          # build() 가 붙인다
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.vram_cache: int | None = None
        self._vram_t = -VRAM_PERIOD_S
        self.client = client if client is not None else mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id=node_id, protocol=mqtt.MQTTv311, clean_session=True)
        self.client.suppress_exceptions = True
        self.client.username_pw_set(username, password)
        self.client.reconnect_delay_set(1, 10)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    @property
    def runner(self) -> Runner:
        if self._runner is None:
            raise RuntimeError("runner not attached — call build()")
        return self._runner

    @runner.setter
    def runner(self, value: Runner) -> None:
        self._runner = value

    def subscriptions(self) -> list[tuple[str, int]]:
        """(topic, qos) — acl.conf 의 sim-runner subscribe 허용 목록 안이어야 한다. 벗어나면 EMQX 가 접속을 끊는다."""
        return [(self.runner.topic(kind), qos) for kind, qos in NODE_SUBSCRIPTIONS] + list(EXTRA_SUBSCRIPTIONS)

    def publish(self, topic: str, payload: bytes, qos: int = 0, retain: bool = False) -> None:
        self.client.publish(topic, payload, qos=qos, retain=retain)

    def _arm_will(self) -> None:
        bd = self.session.new_session()
        self.client.will_set(self.runner.topic("NDEATH"), spb.encode_death(bd), qos=1, retain=False)
        log.info("session bdSeq=%d (NDEATH will armed)", bd)

    def cached_vram(self) -> int | None:
        return self.vram_cache

    def sample_vram(self, now: float, sample: Callable = telemetry.vram_mb) -> None:
        if now - self._vram_t < VRAM_PERIOD_S:
            return
        self._vram_t = now
        v = sample()
        if v is not None:
            self.vram_cache = v

    def touch_alive(self, now: float) -> None:
        """k8s livenessProbe 용 — 틱마다 갱신되는 파일."""
        try:
            with open(self.alive_path, "w", encoding="ascii") as f:
                f.write(str(int(now)))
        except OSError:
            pass

    def _on_connect(self, client, _userdata, _flags, reason_code, _props=None) -> None:
        if reason_code != 0:
            log.error("connect refused: %s", reason_code)
            return
        try:
            subs = self.subscriptions()
            client.subscribe(subs)
            with self.lock:
                self.runner.on_connected(time.time())
            log.info("connected → NBIRTH sent, %d subscriptions", len(subs))
        except Exception:  # noqa: BLE001 — 네트워크 스레드는 살아 있어야 한다
            log.exception("on_connect failed")

    def _on_disconnect(self, _client, _userdata, _flags, reason_code, _props=None) -> None:
        if self.stop_event.is_set():
            return
        log.warning("disconnected (%s) — re-arming will for the reconnect", reason_code)
        with self.lock:
            self._arm_will()

    def _on_message(self, _client, _userdata, msg) -> None:
        now = time.time()
        try:
            with self.lock:
                self._dispatch(msg, now)
        except Exception:  # noqa: BLE001 — 깨진 페이로드 하나가 데몬을 벙어리로 만들면 안 된다
            log.exception("message handler failed on %s", msg.topic)

    def _dispatch(self, msg, now: float) -> None:
        if msg.topic == self.runner.topic("NCMD"):
            self.runner.on_ncmd(msg.payload, now)
        elif msg.topic.startswith("spBv1.0/STATE/"):
            self.runner.on_host_state(msg.payload, now)
        else:
            log.info("ignored %s (%d B)", msg.topic, len(msg.payload))

    def run(self, host: str, port: int) -> None:
        self._arm_will()
        self.client.connect_async(host, port, keepalive=KEEPALIVE_S)
        self.client.loop_start()
        log.info("t3amr edge up — broker %s:%d", host, port)
        try:
            while not self.stop_event.is_set():
                now = time.time()
                self.sample_vram(now)
                self.touch_alive(now)
                with self.lock:
                    self.runner.tick(time.time())
                self.stop_event.wait(TICK_S)
        finally:
            self._shutdown()

    def _shutdown(self) -> None:
        with self.lock:
            if self.runner.state in (STARTING, RUNNING):
                log.info("shutdown while %s → stopping the run first", self.runner.state)
                self.runner.handle_stop(time.time())
        deadline = time.time() + SHUTDOWN_GRACE_S
        while time.time() < deadline:
            with self.lock:
                self.runner.tick(time.time())
                if self.runner.state not in (STARTING, RUNNING, STOPPING):
                    break
            time.sleep(TICK_S)
        try:
            info = self.client.publish(self.runner.topic("NDEATH"), spb.encode_death(self.session.bd_seq), qos=1)
            info.wait_for_publish(3)
        except (RuntimeError, ValueError) as e:
            log.warning("NDEATH publish on shutdown failed: %s", e)
        self.client.disconnect()
        self.client.loop_stop()
        log.info("t3amr edge down (bdSeq=%d)", self.session.bd_seq)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="edge", description="t3_amr Sparkplug Edge (MQTT_CONTRACT §5) — Isaac 녹화 러너")
    p.add_argument("--env-file", help=".env (MQTT_HOST · MQTT_PORT · MQTT_PW_SIM_RUNNER · MINIO_*)")
    p.add_argument("--env-from-environ", action="store_true",
                   help="환경변수만 쓴다(컨테이너). --env-file 없이도 기본 동작")
    p.add_argument("--host", help="브로커 (기본 $MQTT_HOST 또는 localhost)")
    p.add_argument("--port", type=int, help="브로커 포트 (기본 $MQTT_PORT 또는 1883)")
    p.add_argument("--group", default="santa")
    p.add_argument("--node-id", default=os.environ.get("NODE_ID") or "sim-runner-gpu01",
                   help="edge_node_id = username = clientId (host-orch --node 와 같아야 한다)")
    p.add_argument("--t3amr-dir", default=T3AMR_DIR, help="run_record.sh 가 있는 폴더")
    p.add_argument("--state-dir", default=DEFAULT_STATE_DIR, help="bdseq · runs/<run_id>/scenario.json · alive")
    p.add_argument("--planner", default="pibt_h")
    p.add_argument("--tick-s", type=float, default=float(os.environ.get("T3AMR_TICK_S") or DEFAULT_TICK_S),
                   help="계획 틱 길이[s] — window_s → PIBT_HORIZON 환산. "
                        "기본 0.333 = 1.2 m ÷ (0.9 m/s × 4틱) (recorder.DEFAULT_TICK_S)")
    p.add_argument("--heartbeat-s", type=float, default=5.0)
    p.add_argument("--ready-timeout-s", type=float, default=420.0, help="Start 뒤 첫 프레임까지 상한")
    p.add_argument("--host-offline-s", type=float, default=15.0, help="host-orch STATE offline 지속 → Stop")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def build(args: argparse.Namespace) -> tuple:
    """인자 + 환경 → (Edge, host, port). 비밀번호가 없으면 SystemExit(2)."""
    if args.env_file:
        load_env_file(args.env_file)
    host = args.host or os.environ.get("MQTT_HOST") or "localhost"
    port = args.port or int(os.environ.get("MQTT_PORT") or 1883)
    password = os.environ.get("MQTT_PW_SIM_RUNNER")
    if not password:
        raise SystemExit("MQTT_PW_SIM_RUNNER must be set (env or --env-file)")
    t3amr = os.path.abspath(args.t3amr_dir)
    rec_cfg = RecorderConfig(t3amr, os.path.join(t3amr, "out"), os.path.join(t3amr, "logs"),
                             os.path.join(args.state_dir, "runs"), args.planner, args.tick_s)
    uploader = Uploader.from_environ()
    if uploader is None:
        log.warning("MINIO_* not set — videos will not be uploaded (VideoUrl = file://…)")
    session = EdgeSession(os.path.join(args.state_dir, "bdseq"))
    cfg = RunnerConfig(args.group, args.node_id, args.heartbeat_s, args.ready_timeout_s, args.host_offline_s)
    os.makedirs(args.state_dir, exist_ok=True)
    edge = Edge(args.node_id, args.node_id, password, session, os.path.join(args.state_dir, "alive"))
    edge.runner = Runner(cfg, session, lambda: Recorder(rec_cfg), edge, uploader, vram_mb=edge.cached_vram)
    return edge, host, port


def main(argv: list | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    edge, host, port = build(args)
    stale = reap_stale()
    if stale:
        log.warning("killed %d stale run process(es) from a previous edge: %s", len(stale),
                    sorted({run_id for _, run_id in stale}))
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: edge.stop_event.set())
    edge.run(host, port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
