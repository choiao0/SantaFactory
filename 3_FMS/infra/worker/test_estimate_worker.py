# -*- coding: utf-8 -*-
"""견적 워커 번역기·변환기 검사 — 브로커·시뮬 없이 돈다. 3_FMS/infra/worker 에서 `python -m pytest -q`."""
import json
import os

import pytest

import estimate_worker as w

# 백엔드가 생성해 싣는 출고 주문 1건 (-197 이후 outbound[] 는 항상 채워 온다)
ORDER = {"order_id": 1, "ordered_at_s": 3, "lines": [{"product_id": 7, "rack_id": "A2", "qty": 1}]}

# 명세 §1-1 예시 (5_Docs/Web/시뮬엔진연동API명세서.md v0.3) + 백엔드 생성 주문
REQ = {
    "run_id": "est_77_n3", "seed": 42,
    "horizon_s": 21600, "shifts": "in,in,out,out,out,out", "inbound_gap_s": 48.0, "outbound_gap_s": 22.5,
    "warehouse": {"worker_count": 4, "inbound_avg": 480, "outbound_avg": 500},
    "amr": {"count": 3, "speed_empty": 1.2, "speed_loaded": 1.0, "capacity": 6},
    "inbound": [], "outbound": [ORDER],
}

# 2026-09-08 실측 SUMMARY (base 20 0 42 1 --horizon=3600 …) + 신규 키 2개
SUMMARY = {
    "variant": "est_77_n3", "n_robots": 20, "n_orders": 116, "seed": 42, "makespan_steps": 3600,
    "tasks_per_h": 202.0, "orders_per_h": 104.0, "lead_mean_s": 180.4, "lead_p90_s": 274.0, "queue_mean_s": 9.1,
    "util": 0.598, "util_incl_service": 0.63, "conflict_wait": 0.1, "orders_done": 104, "tasks_in": 30,
    "inbound_total": 33, "distance_m": 41200, "order_lead_mean_s": 190.0, "order_lead_p90_s": 290.0,
}

KPI_KEYS = {"orders_total", "orders_completed", "inbound_total", "inbound_completed", "makespan_s",
            "lead_time_mean_s", "lead_time_p90_s", "queue_time_mean_s", "throughput_orders_per_h",
            "throughput_tasks_per_h", "amr_utilization", "conflict_wait_ratio", "distance_total_m",
            "charge_downtime_s"}


def test_request_to_args():
    kw = w.to_sim_args(REQ)
    assert (kw["tag"], kw["n_robots"], kw["n_orders"], kw["seed"]) == ("est_77_n3", 3, 0, 42)
    # 무게 입력 없음 → 기본 0.9 m/s → 틱 1.111 s: 초 입력이 전부 ×0.9 틱으로
    assert set(kw["extra_args"]) == {"--horizon=19440", "--speed=0.9", "--shifts=in,in,out,out,out,out",
                                     "--order-gap=20.25", "--inbound-gap=43.2"}


def test_defaults_and_tag_sanitizing():
    kw = w.to_sim_args({"run_id": "a/b c", "horizon_s": 3600, "amr": {"count": 1}})
    assert kw["tag"] == "a_b_c"
    assert kw["seed"] == 42
    assert kw["extra_args"] == ("--horizon=3240", "--speed=0.9", "--shifts=out")     # 교대 없으면 출고 전용 (-191)


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
    assert (kpi["lead_time_mean_s"], kpi["lead_time_p90_s"]) == (190.0, 290.0)
    assert kpi["distance_total_m"] == 41200 and kpi["charge_downtime_s"] == 0


def test_kpi_seconds_follow_engine_dt():
    """엔진 SUMMARY 의 dt_s 로 틱을 초로 되돌린다 (v3.3). 3600틱 × 1.111 s = 4000 s."""
    kpi = w.to_kpi({**SUMMARY, "dt_s": 1.0 / 0.9, "speed": 0.9})
    assert kpi["makespan_s"] == 4000


def test_speed_from_payload_and_anchors():
    """평균 무게 + 기종 앵커 → speed_for_load. 50/100 kg, 1.2→1.0 이면 1.1 m/s, horizon 21600 s = 23760 틱."""
    amr = {"count": 3, "speed_empty": 1.2, "speed_loaded": 1.0, "max_payload_kg": 100, "avg_payload_kg": 50}
    extra = w.to_sim_args({**REQ, "amr": amr})["extra_args"]
    assert "--speed=1.1" in extra
    assert "--horizon=23760" in extra
    # 앵커가 하나라도 없으면 계산 불가 → 기본 0.9 (run 은 돈다)
    extra = w.to_sim_args({**REQ, "amr": {"count": 3, "speed_empty": 1.2, "avg_payload_kg": 50}})["extra_args"]
    assert "--speed=0.9" in extra
    with pytest.raises(ValueError, match="avg_payload_kg"):
        w.to_sim_args({**REQ, "amr": {"count": 3, "avg_payload_kg": -1}})


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
    assert {"--capacity=6", "--tote-units=8", "--svc-per-tote=5"} <= set(extra)
    no_cap = w.to_sim_args({**req, "amr": {"count": 3, "capacity": None}}, orders_path="/tmp/o.json")["extra_args"]
    assert "--orders-file=/tmp/o.json" in no_cap
    assert not any(f.startswith("--capacity") for f in no_cap)
    assert "--tote-units=8" in no_cap
    assert "--svc-per-tote=5" in no_cap
    null_units = w.to_sim_args({**req, "amr": {"count": 3, "capacity": None, "tote_units": None}},
                               orders_path="/tmp/o.json")["extra_args"]     # 백엔드 실제 형식: 키는 있고 값은 null
    assert "--tote-units=8" in null_units
    empty = w.to_sim_args(REQ)["extra_args"]           # orders_path 없음 → 간격 플래그만 (handle 은 그 전에 outbound[] 를 요구한다)
    assert not any(f.startswith("--orders-file") for f in empty)
    assert not any(f.startswith("--capacity") for f in empty)
    with pytest.raises(ValueError, match="capacity"):
        w.to_sim_args({**req, "amr": {"count": 3, "capacity": 0}}, orders_path="/tmp/o.json")


# ------------------------------------------------------------
# 주문 원천 = 백엔드 (-197). 워커는 outbound[] 를 그대로 쓰고, 비면 failed (자체 생성 -158 은 2026-09-14 제거)
# ------------------------------------------------------------
@pytest.mark.parametrize("outbound", [[], None, "missing"])
def test_orders_required_from_backend(outbound):
    req = {k: v for k, v in REQ.items() if k != "outbound"} if outbound == "missing" else {**REQ, "outbound": outbound}
    with pytest.raises(ValueError, match="outbound"):
        w._orders_file(req)
    r = w.handle(json.dumps(req))
    assert r["status"] == "failed" and r["kpi"] is None and "outbound" in r["error"] and "197" in r["error"]


def test_backend_orders_written_as_is():
    """outbound[] 는 가공 없이 임시 파일 {"outbound": [...]} 로 — 백엔드 저장본이 곧 시뮬 입력이다."""
    path, n = w._orders_file(REQ)
    try:
        assert n == 1
        assert json.load(open(path, encoding="utf-8")) == {"outbound": [ORDER]}
    finally:
        os.remove(path)
    assert not hasattr(w, "_generate_orders") and not hasattr(w, "GEN_ORDERS")


# ---- -191 워커 기본값 ----
def test_shifts_default_out_but_explicit_kept():
    """요청에 shifts 가 없거나 빈 문자열이면 --shifts=out(출고 전용), 있으면 그대로."""
    without = {k: v for k, v in REQ.items() if k != "shifts"}
    assert "--shifts=out" in w.to_sim_args(without)["extra_args"]
    assert "--shifts=out" in w.to_sim_args({**REQ, "shifts": ""})["extra_args"]
    assert "--shifts=in,in,out,out,out,out" in w.to_sim_args(REQ)["extra_args"]


def test_timeout_default_is_1200():
    assert w.TIMEOUT_S == 1200 or "SIM_TIMEOUT_S" in os.environ
