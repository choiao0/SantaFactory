"""host_orch.amqp — 가짜 pika 로 소비 루프: 선언·prefetch·결과 발행 뒤 ack·중단 시 nack."""
import json
import threading

from host_orch import amqp as A


class FakeExceptions:
    class AMQPError(Exception):
        pass


class FakeChannel:
    def __init__(self, script, on_yield=None):
        self.script, self.on_yield = script, on_yield
        self.declared, self.qos, self.published, self.acks, self.nacks, self.cancelled = [], None, [], [], [], False

    def queue_declare(self, queue, durable):
        self.declared.append((queue, durable))

    def basic_qos(self, prefetch_count):
        self.qos = prefetch_count

    def consume(self, queue, inactivity_timeout):
        for item in self.script:
            if self.on_yield:
                self.on_yield()
            yield item

    def basic_publish(self, exchange, routing_key, body, properties):
        self.published.append((routing_key, json.loads(body), properties))

    def basic_ack(self, delivery_tag):
        self.acks.append(delivery_tag)

    def basic_nack(self, delivery_tag, requeue):
        self.nacks.append((delivery_tag, requeue))

    def cancel(self):
        self.cancelled = True


class FakePika:
    exceptions = FakeExceptions

    def __init__(self, channel):
        self._channel = channel

    def URLParameters(self, url):  # noqa: N802
        return url

    def BlockingConnection(self, params):  # noqa: N802
        pika = self

        class Conn:
            def channel(self):
                return pika._channel

            def close(self):
                pass
        return Conn()

    @staticmethod
    def BasicProperties(**kw):  # noqa: N802
        return kw


class Method:
    def __init__(self, tag):
        self.delivery_tag = tag


class FakeJob:
    def __init__(self, ticks_to_done, result):
        self.left, self._result, self.done = ticks_to_done, result, ticks_to_done == 0

    def result(self):
        return self._result


class FakeCoordinator:
    def __init__(self, jobs):
        self.jobs, self.submitted, self.ticks, self.job = list(jobs), [], 0, None

    def submit(self, body):
        self.submitted.append(body)
        self.job = self.jobs.pop(0)
        return self.job

    def tick(self, now):
        self.ticks += 1
        if self.job and not self.job.done:
            self.job.left -= 1
            self.job.done = self.job.left <= 0


def run(script, jobs, stop_after=None):
    ch = FakeChannel(script)
    coord = FakeCoordinator(jobs)
    consumer = A.Consumer("amqp://x", coord, threading.RLock(), pika_module=FakePika(ch))
    if stop_after is not None:
        ch.on_yield = lambda: consumer.stop_event.set() if len(ch.acks) + len(ch.nacks) >= stop_after else None
    consumer._serve()
    return ch, coord, consumer


def test_declares_both_queues_prefetch_one_and_acks_after_result():
    ok = FakeJob(3, {"run_id": "v1", "status": "done"})
    ch, coord, consumer = run([(Method(1), None, b'{"run_id": "v1"}')] + [(None, None, None)] * 5, [ok])

    assert ch.declared == [("sim.verify.request", True), ("sim.verify.result", True)] and ch.qos == 1
    assert coord.submitted == [b'{"run_id": "v1"}']
    assert ch.published == [("sim.verify.result", {"run_id": "v1", "status": "done"},
                             {"content_type": "application/json", "delivery_mode": 2})]
    assert ch.acks == [1] and consumer.handled == 1
    assert coord.ticks >= 3


def test_rejected_request_is_answered_and_acked_at_once():
    bad = FakeJob(0, {"run_id": None, "status": "failed", "error": "bad request"})
    ch, _, _ = run([(Method(7), None, b"junk")], [bad])

    assert ch.published[0][1]["status"] == "failed" and ch.acks == [7]


def test_stop_while_job_pending_nacks_with_requeue_and_cancels():
    slow = FakeJob(100, {})
    ch = FakeChannel([(Method(3), None, b"{}")] + [(None, None, None)] * 3)
    coord = FakeCoordinator([slow])
    consumer = A.Consumer("amqp://x", coord, threading.RLock(), pika_module=FakePika(ch))
    ch.on_yield = lambda: consumer.stop_event.set() if coord.submitted else None      # 요청을 받은 뒤 중단

    consumer._serve()

    assert ch.nacks == [(3, True)] and ch.acks == [] and ch.cancelled


def test_amqp_url_from_parts(monkeypatch):
    monkeypatch.delenv("RABBITMQ_URL", raising=False)
    monkeypatch.setenv("RABBITMQ_USER", "u")
    monkeypatch.setenv("RABBITMQ_PASSWORD", "p")
    monkeypatch.setenv("RABBITMQ_HOST", "h")
    monkeypatch.delenv("RABBITMQ_PORT", raising=False)

    assert A.amqp_url() == "amqp://u:p@h:5672/"
    monkeypatch.setenv("RABBITMQ_URL", "amqp://direct")
    assert A.amqp_url() == "amqp://direct"


class BusyThenAcceptCoordinator(FakeCoordinator):
    def __init__(self, jobs, busy_polls):
        super().__init__(jobs)
        self.busy_polls = busy_polls

    def submit(self, body):
        from host_orch.orchestrator import Busy
        if self.busy_polls > 0:
            self.busy_polls -= 1
            raise Busy("busy with other")
        return super().submit(body)


def test_busy_request_is_deferred_and_retried_until_accepted():
    ch = FakeChannel([(Method(5), None, b'{"run_id": "v2"}')] + [(None, None, None)] * 6)
    coord = BusyThenAcceptCoordinator([FakeJob(1, {"run_id": "v2", "status": "done"})], busy_polls=3)
    consumer = A.Consumer("amqp://x", coord, threading.RLock(), pika_module=FakePika(ch))

    consumer._serve()

    assert coord.submitted == [b'{"run_id": "v2"}'] and ch.acks == [5] and ch.nacks == []
    assert ch.published[0][1]["status"] == "done"


class ExplodingCoordinator(FakeCoordinator):
    def submit(self, body):
        raise RuntimeError("boom")


def test_unexpected_submit_error_becomes_failed_result_not_a_crash():
    ch = FakeChannel([(Method(9), None, b'{"run_id": "v3", "n_robots": 1}'), (None, None, None)])
    consumer = A.Consumer("amqp://x", ExplodingCoordinator([]), threading.RLock(), pika_module=FakePika(ch))

    consumer._serve()

    assert ch.acks == [9]
    assert ch.published[0][1]["run_id"] == "v3" and ch.published[0][1]["error"] == "internal error: boom"
