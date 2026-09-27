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


# ── 다중 노드: prefetch = 노드 수, pending 여러 건 (spec244 §E, -244) ────────────────────────────
class FakeMultiCoordinator:
    """submit 마다 새 FakeJob 을 내주고 tick 은 아직 안 끝난 잡을 전부 진행시킨다 — 노드별 독립 pending 재현용.

    (기존 FakeCoordinator 는 `self.job` 하나만 진행시켜 여러 pending 을 동시에 못 돌린다.)"""

    def __init__(self, jobs):
        self.to_hand_out, self.submitted, self.active = list(jobs), [], []

    def submit(self, body):
        self.submitted.append(body)
        job = self.to_hand_out.pop(0)
        self.active.append(job)
        return job

    def tick(self, now):
        for job in self.active:
            if not job.done:
                job.left -= 1
                job.done = job.left <= 0


def test_prefetch_count_matches_the_given_node_count():
    ch = FakeChannel([])
    consumer = A.Consumer("amqp://x", FakeCoordinator([]), threading.RLock(), pika_module=FakePika(ch), prefetch_count=3)

    consumer._serve()

    assert ch.qos == 3


def test_multiple_pending_requests_are_held_and_acked_independently():
    j1, j2 = FakeJob(1, {"run_id": "v1", "status": "done"}), FakeJob(3, {"run_id": "v2", "status": "done"})
    script = [(Method(1), None, b'{"run_id": "v1"}'), (Method(2), None, b'{"run_id": "v2"}')] + [(None, None, None)] * 5
    ch = FakeChannel(script)
    coord = FakeMultiCoordinator([j1, j2])
    consumer = A.Consumer("amqp://x", coord, threading.RLock(), pika_module=FakePika(ch), prefetch_count=2)

    consumer._serve()

    assert ch.qos == 2
    assert coord.submitted == [b'{"run_id": "v1"}', b'{"run_id": "v2"}']    # 둘 다 prefetch 안에서 동시에 받는다
    assert ch.acks == [1, 2]                                                # v1 이 먼저 끝나 먼저 ack, v2 는 나중
    assert [r["run_id"] for _q, r, _p in ch.published] == ["v1", "v2"]


def test_stop_while_multiple_pending_nacks_all_with_requeue_and_cancels():
    ch = FakeChannel([(Method(1), None, b'{"run_id": "a"}'), (Method(2), None, b'{"run_id": "b"}')]
                     + [(None, None, None)] * 3)
    coord = FakeMultiCoordinator([FakeJob(100, {}), FakeJob(100, {})])
    consumer = A.Consumer("amqp://x", coord, threading.RLock(), pika_module=FakePika(ch), prefetch_count=2)
    ch.on_yield = lambda: consumer.stop_event.set() if len(coord.submitted) >= 2 else None

    consumer._serve()

    assert sorted(ch.nacks) == [(1, True), (2, True)] and ch.acks == [] and ch.cancelled


def test_busy_pending_is_requeued_after_a_short_hold_not_held_forever(monkeypatch):
    """Busy(빈 노드 없음)로 계속 보류되던 메시지를 BUSY_REQUEUE_S 뒤에 requeue 한다 — 그러지 않으면 계속
    unacked 로 남아 RabbitMQ consumer_timeout(기본 30 분, amqp.py 모듈 docstring)에 걸린다(-244, §3)."""
    ch = FakeChannel([(Method(11), None, b'{"run_id": "v9"}')] + [(None, None, None)] * 4)
    coord = BusyThenAcceptCoordinator([], busy_polls=10 ** 9)      # 영원히 Busy
    consumer = A.Consumer("amqp://x", coord, threading.RLock(), pika_module=FakePika(ch))

    clock = [1000.0]

    def fake_time():
        clock[0] += 3.0          # poll(0.5 s) 마다 3 s 씩 흐르는 걸로 쳐서 BUSY_REQUEUE_S(10 s)를 몇 번이면 넘는다
        return clock[0]

    monkeypatch.setattr(A.time, "time", fake_time)

    consumer._serve()

    assert ch.acks == [] and ch.nacks == [(11, True)]
