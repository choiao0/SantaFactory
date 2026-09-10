"""MQTT 연결부 — paho 클라이언트를 Conductor 에 잇는다 (MQTT_CONTRACT §5.4 세션 규칙, 계정 fms-core).

접속(재접속) 전마다 bdSeq+1 로 NDEATH 유언을 새로 걸고, 접속되면 NBIRTH. paho 의 자동 재접속은 on_disconnect 뒤에
일어나므로 거기서 유언을 갈아 끼운다. 구독 목록은 acl.conf 의 fms-core subscribe 허용과 1:1 (벗어나면 EMQX 가 끊는다).
"""
from __future__ import annotations

import logging
import threading
import time

import paho.mqtt.client as mqtt

from . import spb
from .conductor import RUNNING, STARTING, Conductor
from .spb import EdgeSession

log = logging.getLogger("fms_core.mqtt")
KEEPALIVE_S = 30          # MQTT_CONTRACT §0: 기본 30 s (sim-runner 만 60)
TICK_S = 0.2              # 틱 배리어 반응 지연 상한
SHUTDOWN_GRACE_S = 1.0    # cancelOrder · kpi_summary 가 나갈 시간
EXTRA_SUBSCRIPTIONS = (("spBv1.0/STATE/+", 1), ("uagv/v2/+/+/state", 0), ("uagv/v2/+/+/connection", 1))


class Edge:
    def __init__(self, node_id: str, password: str, session: EdgeSession, conductor: Conductor):
        self.session, self.conductor = session, conductor
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.connected = threading.Event()
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=node_id, protocol=mqtt.MQTTv311,
                                  clean_session=True)
        self.client.suppress_exceptions = True      # 콜백 예외로 네트워크 스레드가 죽지 않게
        self.client.username_pw_set(node_id, password)
        self.client.reconnect_delay_set(1, 10)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def subscriptions(self) -> list:
        """(topic, qos) — acl.conf 의 fms-core subscribe 허용 목록 안에서만."""
        return [(self.conductor.topic("NCMD"), 0)] + list(EXTRA_SUBSCRIPTIONS)

    # Conductor 가 쓰는 publisher 인터페이스
    def publish(self, topic: str, payload: bytes, qos: int = 0, retain: bool = False) -> None:
        self.client.publish(topic, payload, qos=qos, retain=retain)

    def _arm_will(self) -> None:
        bd = self.session.new_session()
        self.client.will_set(self.conductor.topic("NDEATH"), spb.encode_death(bd), qos=1, retain=False)
        log.info("session bdSeq=%d (NDEATH will armed)", bd)

    def _on_connect(self, client, _userdata, _flags, reason_code, _props=None) -> None:
        if reason_code != 0:
            log.error("connect refused: %s", reason_code)
            return
        try:
            subs = self.subscriptions()
            client.subscribe(subs)
            with self.lock:
                self.conductor.on_connected(time.time())
            self.connected.set()
            log.info("connected → NBIRTH sent, %d subscriptions", len(subs))
        except Exception:  # noqa: BLE001 — 네트워크 스레드는 살아 있어야 한다
            log.exception("on_connect failed")

    def _on_disconnect(self, _client, _userdata, _flags, reason_code, _props=None) -> None:
        self.connected.clear()
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
        if msg.topic == self.conductor.topic("NCMD"):
            self.conductor.on_ncmd(msg.payload, now)
        elif msg.topic.startswith("spBv1.0/STATE/"):
            self.conductor.on_host_state(msg.payload, now)
        elif msg.topic.startswith("uagv/v2/"):
            self.conductor.on_vda(msg.topic, msg.payload, now)
        else:
            log.info("ignored %s (%d B)", msg.topic, len(msg.payload))

    def connect(self, host: str, port: int) -> None:
        self._arm_will()
        self.client.connect_async(host, port, keepalive=KEEPALIVE_S)
        self.client.loop_start()

    def run(self, host: str, port: int) -> None:
        self.connect(host, port)
        log.info("fms-core up — broker %s:%d, planner %s", host, port, self.conductor.cfg.planner)
        try:
            while not self.stop_event.is_set():
                with self.lock:
                    self.conductor.tick(time.time())
                self.stop_event.wait(TICK_S)
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        with self.lock:
            if self.conductor.state in (STARTING, RUNNING):
                log.info("shutdown while %s → stopping the run first", self.conductor.state)
                self.conductor.handle_stop(time.time())
        time.sleep(SHUTDOWN_GRACE_S)
        try:
            info = self.client.publish(self.conductor.topic("NDEATH"), spb.encode_death(self.session.bd_seq), qos=1)
            info.wait_for_publish(3)
        except (RuntimeError, ValueError) as e:
            log.warning("NDEATH publish on shutdown failed: %s", e)
        self.client.disconnect()
        self.client.loop_stop()
        log.info("fms-core down (bdSeq=%d)", self.session.bd_seq)
