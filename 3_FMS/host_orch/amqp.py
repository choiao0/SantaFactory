"""RabbitMQ `sim.verify.request` 소비 · `sim.verify.result` 발행 — pika BlockingConnection, prefetch 1, 결과 발행 뒤 ack.

잡은 분 단위로 돌므로 소비 루프 안에서 기다린다: consume(inactivity_timeout) 이 0.5 s 마다 None 을 내면
coordinator.tick() 을 돌리고, 잡이 끝나면 결과를 발행하고 그제야 ack 한다 (명세 §1-3 과 같은 규칙).
prefetch 1 이라 unacked 동안 다음 요청은 오지 않는다. RabbitMQ consumer_timeout(기본 30 분) 안에 창을 끝내야 한다.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Callable, Optional

from .orchestrator import Busy, failed_request

log = logging.getLogger("host_orch.amqp")

REQUEST_QUEUE = "sim.verify.request"
RESULT_QUEUE = "sim.verify.result"
POLL_S = 0.5
RECONNECT_S = 5.0


def amqp_url() -> str:
    """RABBITMQ_URL 또는 RABBITMQ_HOST/PORT/USER/PASSWORD (견적 워커와 같은 규칙)."""
    url = os.environ.get("RABBITMQ_URL")
    if url:
        return url
    user, pw = os.environ.get("RABBITMQ_USER"), os.environ.get("RABBITMQ_PASSWORD")
    if not user or not pw:
        raise SystemExit("RABBITMQ_URL or RABBITMQ_USER/RABBITMQ_PASSWORD must be set")
    host, port = os.environ.get("RABBITMQ_HOST", "localhost"), os.environ.get("RABBITMQ_PORT", "5672")
    return f"amqp://{user}:{pw}@{host}:{port}/"


def result_properties(pika_module: Any) -> Any:
    return pika_module.BasicProperties(content_type="application/json", delivery_mode=2)


class Consumer:
    """coordinator: submit(body) → job(.done, .result()), tick(now). lock 은 MQTT 스레드와 공유."""

    def __init__(self, url: str, coordinator: Any, lock: threading.RLock, request_queue: str = REQUEST_QUEUE,
                 result_queue: str = RESULT_QUEUE, pika_module: Any = None):
        self.url, self.coord, self.lock = url, coordinator, lock
        self.request_queue, self.result_queue = request_queue, result_queue
        self.pika = pika_module
        self.stop_event = threading.Event()
        self.handled = 0

    def run_forever(self) -> None:
        if self.pika is None:
            import pika  # noqa: PLC0415 — 테스트는 가짜 모듈을 주입한다
            self.pika = pika
        while not self.stop_event.is_set():
            try:
                self._serve()
            except self.pika.exceptions.AMQPError as e:
                log.warning("AMQP error: %s — reconnect in %.0fs", e, RECONNECT_S)
                self.stop_event.wait(RECONNECT_S)

    def _serve(self) -> None:
        conn = self.pika.BlockingConnection(self.pika.URLParameters(self.url))
        try:
            ch = conn.channel()
            for q in (self.request_queue, self.result_queue):
                ch.queue_declare(queue=q, durable=True)
            ch.basic_qos(prefetch_count=1)
            log.info("consuming %s (prefetch 1) → %s", self.request_queue, self.result_queue)
            self._loop(ch)
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    def _loop(self, ch: Any) -> None:
        pending = None      # [delivery_tag, body, job|None] — job 이 None 이면 Busy 라 다음 poll 에 다시 submit
        for method, _props, body in ch.consume(self.request_queue, inactivity_timeout=POLL_S):
            if self.stop_event.is_set():
                if pending is not None:
                    ch.basic_nack(delivery_tag=pending[0], requeue=True)
                ch.cancel()
                return
            if method is not None:
                pending = [method.delivery_tag, body, None]
            with self.lock:
                self.coord.tick(time.time())
                if pending is not None and pending[2] is None:
                    pending[2] = self._accept(pending[1])
                job = pending[2] if pending else None
                finished = job is not None and job.done
                result = job.result() if finished else None
            if finished:
                self._publish_result(ch, result)
                ch.basic_ack(delivery_tag=pending[0])
                self.handled += 1
                pending = None

    def _accept(self, body: bytes) -> Any:
        """submit 을 격리한다: Busy → None(보류), 그 밖의 예외 → failed 결과로 바꿔 큐를 막지 않는다. 락 안에서 호출."""
        try:
            job = self.coord.submit(body)
        except Busy as e:
            log.info("request deferred: %s", e)
            return None
        except Exception as e:  # noqa: BLE001 — 버그 하나가 유일 소비자를 죽이면 안 된다
            log.exception("submit failed")
            return failed_request(body, f"internal error: {e}")
        run_id = getattr(getattr(job, "req", None), "run_id", None) or getattr(job, "run_id", "?")
        log.info("request %s → %s", run_id, f"rejected: {getattr(job, 'error', None)}" if job.done else "accepted")
        return job

    def _publish_result(self, ch: Any, result: dict) -> None:
        ch.basic_publish(exchange="", routing_key=self.result_queue, body=json.dumps(result, ensure_ascii=False),
                         properties=result_properties(self.pika))
        log.info("result %s status=%s reason=%s", result.get("run_id"), result.get("status"),
                 (result.get("verify") or {}).get("reason") or result.get("error"))


def publish_request(url: str, queue: str, body: dict, pika_module: Any = None) -> None:
    """테스트·수동 투입용: 요청 1건을 durable 큐에 넣는다."""
    pika = pika_module or __import__("pika")
    conn = pika.BlockingConnection(pika.URLParameters(url))
    try:
        ch = conn.channel()
        ch.queue_declare(queue=queue, durable=True)
        ch.basic_publish(exchange="", routing_key=queue, body=json.dumps(body), properties=result_properties(pika))
    finally:
        conn.close()


def drain(url: str, queue: str, limit: int = 100, pika_module: Any = None, timeout_s: float = 2.0) -> list:
    """테스트용: 큐에서 최대 limit 건을 꺼내(ack) JSON 으로 돌려준다."""
    pika = pika_module or __import__("pika")
    conn = pika.BlockingConnection(pika.URLParameters(url))
    out: list = []
    try:
        ch = conn.channel()
        ch.queue_declare(queue=queue, durable=True)
        for method, _p, body in ch.consume(queue, inactivity_timeout=timeout_s):
            if method is None or len(out) >= limit:
                break
            out.append(json.loads(body))
            ch.basic_ack(delivery_tag=method.delivery_tag)
        ch.cancel()
    finally:
        conn.close()
    return out


Callback = Callable[[dict], Optional[dict]]
