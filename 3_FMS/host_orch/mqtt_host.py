"""Primary Host MQTT 연결부 — STATE/host-orch retained + 유언 offline, spBv1.0/{group}/# 구독, NCMD 발행 (MQTT_CONTRACT §5.1 · §5.4).

수신은 paho 스레드에서 coordinator.on_mqtt 로(락 안), 발행은 아무 스레드나. 재접속하면 STATE online 을 다시 쓴다
(timestamp 는 접속마다 새로) — sim-runner 는 이 timestamp 증가를 보고 BIRTH 를 재발행한다.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable, Optional

import paho.mqtt.client as mqtt

from . import spb

log = logging.getLogger("host_orch.mqtt")
KEEPALIVE_S = 30


def now_ms() -> int:
    return int(time.time() * 1000)


class HostClient:
    def __init__(self, host_id: str, password: str, group: str, on_mqtt: Callable[[str, bytes], Any],
                 lock: threading.RLock, extra_subscriptions: tuple = ()):
        self.host_id, self.group, self.on_mqtt, self.lock = host_id, group, on_mqtt, lock
        self.extra_subscriptions = extra_subscriptions
        self.connected = threading.Event()
        self.t_online: Optional[int] = None
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=host_id, protocol=mqtt.MQTTv311,
                                  clean_session=True)
        self.client.suppress_exceptions = True
        self.client.username_pw_set(host_id, password)
        self.client.reconnect_delay_set(1, 10)
        self.client.on_connect, self.client.on_disconnect, self.client.on_message = (
            self._on_connect, self._on_disconnect, self._on_message)

    @property
    def state_topic(self) -> str:
        return f"spBv1.0/STATE/{self.host_id}"

    def state_payload(self, online: bool) -> bytes:
        return json.dumps({"online": online, "timestamp": self.t_online}).encode()

    def subscriptions(self) -> list:
        """acl.conf host-orch subscribe: spBv1.0/# · biz/v1/# · uagv/v2/+/+/#."""
        return [(f"spBv1.0/{self.group}/#", 0)] + list(self.extra_subscriptions)

    def _arm_will(self) -> None:
        self.t_online = now_ms()
        self.client.will_set(self.state_topic, self.state_payload(False), qos=1, retain=True)

    def connect(self, host: str, port: int) -> None:
        self._arm_will()
        self.client.connect_async(host, port, keepalive=KEEPALIVE_S)
        self.client.loop_start()

    def _on_connect(self, client, _u, _f, reason_code, _p=None) -> None:
        if reason_code != 0:
            log.error("connect refused: %s", reason_code)
            return
        try:
            with self.lock:
                client.subscribe(self.subscriptions())
                client.publish(self.state_topic, self.state_payload(True), qos=1, retain=True)
            self.connected.set()
            log.info("connected — STATE online (ts=%s), subscribed %s", self.t_online, self.subscriptions())
        except Exception:  # noqa: BLE001
            log.exception("on_connect failed")

    def _on_disconnect(self, _c, _u, _f, reason_code, _p=None) -> None:
        self.connected.clear()
        if reason_code != 0:
            log.warning("disconnected (%s) — will re-arm STATE for the reconnect", reason_code)
            with self.lock:
                self._arm_will()

    def _on_message(self, _c, _u, msg) -> None:
        try:
            with self.lock:
                self.on_mqtt(msg.topic, msg.payload)
        except Exception:  # noqa: BLE001
            log.exception("message handler failed on %s", msg.topic)

    def send_ncmd(self, node_id: str, metrics: list) -> None:
        self.client.publish(f"spBv1.0/{self.group}/NCMD/{node_id}", spb.encode_cmd(metrics), qos=0)
        log.info("NCMD %s ← %s", node_id, ", ".join(f"{n}={str(v)[:60]}" for n, _t, v in metrics))

    def close(self) -> None:
        try:
            self.client.publish(self.state_topic, self.state_payload(False), qos=1, retain=True).wait_for_publish(3)
        except (RuntimeError, ValueError):
            pass
        self.client.disconnect()
        self.client.loop_stop()
