# -*- coding: utf-8 -*-
"""견적 워커 번역기·변환기 검사 — 브로커·시뮬 없이 돈다. 3_FMS/infra/worker 에서 `python -m pytest -q`."""
import json

import pytest

import estimate_worker as w

# 명세 §1-1 예시 (5_Docs/Web/시뮬엔진연동API명세서.md v0.3)
REQ = {
    "run_id": "est_77_n3", "seed": 42,
    "horizon_s": 21600, "shifts": "in,in,out,out,out,out", "inbound_gap_s": 48.0, "outbound_gap_s": 22.5,
    "warehouse": {"worker_count": 4, "inbound_avg": 480, "outbound_avg": 500},
    "amr": {"count": 3, "speed_empty": 1.2, "speed_loaded": 1.0, "capacity": 8},
    "inbound": [], "outbound": [],
}

# 2026-09-08 실측 SUMMARY (base 20 0 42 1 --horizon=3600 …) + 신규 키 2개
SUMMARY = {
    "variant": "est_77_n3", "n_robots": 20, "n_orders": 116, "seed": 42, "makespan_steps": 3600,
    "tasks_per_h": 202.0, "orders_per_h": 104.0, "lead_mean_s": 180.4, "lead_p90_s": 274.0, "queue_mean_s": 9.1,
    "util": 0.598, "util_incl_service": 0.63, "conflict_wait": 0.1, "orders_done": 104, "tasks_in": 30,
    "inbound_total": 33, "distance_m": 41200,
}

KPI_KEYS = {"orders_total", "orders_completed", "inbound_total", "inbound_completed", "makespan_s",
            "lead_time_mean_s", "lead_time_p90_s", "queue_time_mean_s", "throughput_orders_per_h",
            "throughput_tasks_per_h", "amr_utilization", "conflict_wait_ratio", "distance_total_m",
            "charge_downtime_s"}


def test_request_to_args():
    kw = w.to_sim_args(REQ)
    assert (kw["tag"], kw["n_robots"], kw["n_orders"], kw["seed"]) == ("est_77_n3", 3, 0, 42)
    assert set(kw["extra_args"]) == {"--horizon=21600", "--shifts=in,in,out,out,out,out",
                                     "--order-gap=22.5", "--inbound-gap=48"}


def test_defaults_and_tag_sanitizing():
    kw = w.to_sim_args({"run_id": "a/b c", "horizon_s": 3600, "amr": {"count": 1}})
    assert kw["tag"] == "a_b_c" and kw["seed"] == 42 and kw["extra_args"] == ("--horizon=3600",)


@pytest.mark.parametrize("bad", [
    {**REQ, "amr": {"count": 29}},                # 존 용량 초과
    {k: v for k, v in REQ.items() if k != "horizon_s"},   # 유한 모드 금지
    {**REQ, "run_id": ""},
    {**REQ, "outbound_gap_s": 0},
])
def test_invalid_request_rejected(bad):
    with pytest.raises(ValueError):
        w.to_sim_args(bad)


def test_summary_to_kpi():
    kpi = w.to_kpi(SUMMARY)
    assert set(kpi) == KPI_KEYS
    assert (kpi["orders_total"], kpi["orders_completed"]) == (116, 104)
    assert (kpi["inbound_total"], kpi["inbound_completed"]) == (33, 30)
    assert kpi["makespan_s"] == 3600 and kpi["amr_utilization"] == 0.63
    assert kpi["distance_total_m"] == 41200 and kpi["charge_downtime_s"] == 0


def test_handle_never_raises():
    r = json.loads(json.dumps(w.handle(b"not json")))
    assert r["status"] == "failed" and r["kpi"] is None and r["run_id"] == "?"
    r = w.handle(json.dumps({**REQ, "amr": {"count": 0}}))
    assert r["status"] == "failed" and r["run_id"] == "est_77_n3" and "amr.count" in r["error"]


def test_consume_publishes_then_acks(monkeypatch):
    """가짜 pika: 메시지 1건 → 결과가 sim.result 로 발행된 뒤 ack. (실브로커 실사는 docs/견적_워커.md 검증 절)"""
    import sys, types
    calls = []

    class Ch:
        def basic_qos(self, prefetch_count): calls.append(("qos", prefetch_count))
        def basic_consume(self, queue, on_message_callback):
            self.cb, self.q = on_message_callback, queue
        def basic_publish(self, exchange, routing_key, body, properties): calls.append(("publish", routing_key, json.loads(body)["status"]))
        def basic_ack(self, delivery_tag): calls.append(("ack", delivery_tag))
        def start_consuming(self):
            self.cb(self, types.SimpleNamespace(delivery_tag=7), None, b'{"run_id":"r1","amr":{"count":0}}')
            raise StopIteration                      # 루프 탈출용

    fake = types.ModuleType("pika")
    fake.URLParameters = lambda url: url
    fake.BlockingConnection = lambda p: types.SimpleNamespace(channel=lambda: Ch())
    fake.BasicProperties = lambda **kw: kw
    fake.exceptions = types.SimpleNamespace(AMQPError=ConnectionError)
    monkeypatch.setitem(sys.modules, "pika", fake)
    with pytest.raises(StopIteration):
        w.consume()
    assert calls == [("qos", 1), ("publish", "sim.result", "failed"), ("ack", 7)]


def test_explicit_orders_and_capacity_flags():
    """outbound[] 가 있으면 --orders-file, amr.capacity 가 정수면 --capacity. 비어 있거나 null 이면 둘 다 없음 (-156)."""
    req = {**REQ, "outbound": [{"order_id": 1, "ordered_at_s": 3, "lines": [{"product_id": 7, "rack_id": "A2", "qty": 1}]}]}
    extra = w.to_sim_args(req, orders_path="/tmp/o.json")["extra_args"]
    assert "--orders-file=/tmp/o.json" in extra
    assert "--capacity=8" in extra
    no_cap = w.to_sim_args({**req, "amr": {"count": 3, "capacity": None}}, orders_path="/tmp/o.json")["extra_args"]
    assert "--orders-file=/tmp/o.json" in no_cap
    assert not any(f.startswith("--capacity") for f in no_cap)
    empty = w.to_sim_args(REQ, orders_path="/tmp/o.json")["extra_args"]          # outbound: [] → 간격 모드
    assert not any(f.startswith("--orders-file") for f in empty)
    assert not any(f.startswith("--capacity") for f in empty)
    with pytest.raises(ValueError, match="capacity"):
        w.to_sim_args({**req, "amr": {"count": 3, "capacity": 0}}, orders_path="/tmp/o.json")
