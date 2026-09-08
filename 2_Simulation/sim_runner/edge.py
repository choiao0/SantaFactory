"""MQTT 연결부 + CLI — paho 클라이언트를 Runner 에 잇는다.  `python3 -m sim_runner --mode fake --env-file …`

세션 규칙(§5.4): 접속(재접속) 전마다 bdSeq+1 로 NDEATH 유언을 새로 걸고, 접속되면 NBIRTH(+살아 있는 DBIRTH).
paho 의 자동 재접속은 on_disconnect 뒤에 일어나므로 거기서 유언을 갈아 끼운다. 정상 종료는 NDEATH 를 직접 발행한다.
비밀번호는 argv 가 아니라 환경(MQTT_PW_SIM_RUNNER · MQTT_PW_AMR, 또는 --env-file)에서만 받는다.
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
import time
from typing import Callable, Optional

import paho.mqtt.client as mqtt

from . import spb, telemetry
from .procs import LaunchEnv, ProcessManager, reap_stale
from .runner import RUNNING, STARTING, STOPPING, Runner, RunnerConfig
from .spb import EdgeSession

log = logging.getLogger("sim_runner")

SIM_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ROS_SETUP = ("/opt/ros/humble/setup.bash", os.path.join(SIM_DIR, "t4_agent", "install", "setup.bash"))
DEFAULT_STATE_DIR = os.path.expanduser("~/.local/state/sim_runner")
DEFAULT_ISAAC_CMD = os.path.expanduser("~/isaacsim/python.sh") + " " + os.path.join(SIM_DIR, "t3_warehouse",
                                                                                     "warehouse_sim.py")
KEEPALIVE_S = 60          # MQTT_CONTRACT §0: sim-runner 60 s
TICK_S = 0.5
SHUTDOWN_GRACE_S = 40.0   # 종료 신호 뒤 런 정리(에이전트 5 s + Isaac 20 s 사다리) 상한
VRAM_PERIOD_S = 5.0       # nvidia-smi 는 느릴 수 있어 락 밖에서, 하트비트 주기로만
NODE_SUBSCRIPTIONS = (("NCMD", None, 0), ("DCMD", "+", 0))   # ACL: NCMD/<node> · DCMD/<node>/+
EXTRA_SUBSCRIPTIONS = (("spBv1.0/STATE/+", 1), ("uagv/v2/+/+/state", 0), ("uagv/v2/+/+/connection", 1))


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


class Edge:
    def __init__(self, node_id: str, username: str, password: str, session: EdgeSession):
        self.session = session
        self.runner: Runner = None  # type: ignore[assignment]  — build() 가 바로 붙인다
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.vram_cache: Optional[int] = None
        self._vram_t = -VRAM_PERIOD_S
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=node_id,
                                  protocol=mqtt.MQTTv311, clean_session=True)
        self.client.suppress_exceptions = True      # 콜백 예외로 네트워크 스레드가 죽지 않게(아래서 직접 로깅)
        self.client.username_pw_set(username, password)
        self.client.reconnect_delay_set(1, 10)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def subscriptions(self) -> list:
        """(topic, qos) — acl.conf 의 sim-runner subscribe 허용 목록과 1:1. 벗어나면 EMQX 가 접속을 끊는다."""
        return [(self.runner.topic(kind, device), qos) for kind, device, qos in NODE_SUBSCRIPTIONS] + list(EXTRA_SUBSCRIPTIONS)

    # Runner 가 쓰는 publisher 인터페이스
    def publish(self, topic: str, payload: bytes, qos: int = 0, retain: bool = False) -> None:
        self.client.publish(topic, payload, qos=qos, retain=retain)

    def _arm_will(self) -> None:
        bd = self.session.new_session()
        self.client.will_set(self.runner.topic("NDEATH"), spb.encode_death(bd), qos=1, retain=False)
        log.info("session bdSeq=%d (NDEATH will armed)", bd)

    def cached_vram(self) -> Optional[int]:
        return self.vram_cache

    def sample_vram(self, now: float, sample: Callable = telemetry.vram_mb) -> None:
        """락 밖에서 부른다. VRAM_PERIOD_S 마다 한 번, 실패(None)면 이전 값 유지."""
        if now - self._vram_t < VRAM_PERIOD_S:
            return
        self._vram_t = now
        v = sample()
        if v is not None:
            self.vram_cache = v

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
        with self.lock:                      # session.seq 를 tick 의 next_seq() 와 같이 만진다
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
        elif msg.topic.startswith("uagv/v2/"):
            self.runner.on_vda(msg.topic, msg.payload, now)
        else:
            log.info("ignored %s (%d B)", msg.topic, len(msg.payload))

    def run(self, host: str, port: int) -> None:
        self._arm_will()
        self.client.connect_async(host, port, keepalive=KEEPALIVE_S)
        self.client.loop_start()
        log.info("sim-runner up — broker %s:%d", host, port)
        try:
            while not self.stop_event.is_set():
                self.sample_vram(time.time())
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
        log.info("sim-runner down (bdSeq=%d)", self.session.bd_seq)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sim_runner", description="Sparkplug Edge sim-runner (MQTT_CONTRACT §5)")
    p.add_argument("--env-file", help=".env (MQTT_HOST · MQTT_PORT · MQTT_PW_SIM_RUNNER · MQTT_PW_AMR)")
    p.add_argument("--host", help="브로커 (기본 $MQTT_HOST 또는 localhost)")
    p.add_argument("--port", type=int, help="브로커 포트 (기본 $MQTT_PORT 또는 1883)")
    p.add_argument("--mode", choices=("fake", "real"), default="fake", help="fake = fake_robot 에이전트만")
    p.add_argument("--group", default="santa")
    p.add_argument("--node-id", default="sim-runner-gpu01", help="edge_node_id = username = clientId")
    p.add_argument("--ros-setup", action="append", help="source 할 setup.bash (반복). 기본 humble + t4_agent/install")
    p.add_argument("--isaac-cmd", help="실모드 Isaac 셸 명령 (기본 $SIM_RUNNER_ISAAC_CMD 또는 warehouse_sim.py)")
    p.add_argument("--isaac-warmup-s", type=float, default=90.0, help="Isaac 기동 뒤 에이전트를 띄우기까지")
    p.add_argument("--state-dir", default=DEFAULT_STATE_DIR, help="bdseq 파일 · 런 로그")
    p.add_argument("--heartbeat-s", type=float, default=5.0)
    p.add_argument("--ready-timeout-s", type=float, default=120.0, help="Start 뒤 에이전트 전원 ONLINE 상한")
    p.add_argument("--host-offline-s", type=float, default=15.0, help="host-orch STATE offline 지속 → Stop")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def build(args: argparse.Namespace) -> tuple:
    """인자 + 환경 → (Edge, host, port). 비밀번호가 없으면 SystemExit(2)."""
    if args.env_file:
        load_env_file(args.env_file)
    host = args.host or os.environ.get("MQTT_HOST") or "localhost"
    port = args.port or int(os.environ.get("MQTT_PORT") or 1883)
    password, amr_password = os.environ.get("MQTT_PW_SIM_RUNNER"), os.environ.get("MQTT_PW_AMR")
    if not password or not amr_password:
        raise SystemExit("MQTT_PW_SIM_RUNNER and MQTT_PW_AMR must be set (env or --env-file)")
    env = LaunchEnv(host, port, amr_password, tuple(args.ros_setup or DEFAULT_ROS_SETUP),
                    args.isaac_cmd or os.environ.get("SIM_RUNNER_ISAAC_CMD") or DEFAULT_ISAAC_CMD,
                    args.isaac_warmup_s)
    session = EdgeSession(os.path.join(args.state_dir, "bdseq"))
    log_dir = os.path.join(args.state_dir, "logs")
    cfg = RunnerConfig(args.group, args.node_id, args.heartbeat_s, args.ready_timeout_s, args.host_offline_s)
    edge = Edge(args.node_id, args.node_id, password, session)
    edge.runner = Runner(cfg, session, lambda: ProcessManager(env, fake=args.mode == "fake", log_dir=log_dir), edge,
                         vram_mb=edge.cached_vram)
    return edge, host, port


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    edge, host, port = build(args)
    stale = reap_stale()
    if stale:
        log.warning("killed %d stale run process(es) from a previous sim-runner: %s", len(stale),
                    sorted({run_id for _, run_id in stale}))
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: edge.stop_event.set())
    edge.run(host, port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
