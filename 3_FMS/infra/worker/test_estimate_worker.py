# -*- coding: utf-8 -*-
"""견적 워커 번역기·변환기 검사 — 브로커·시뮬 없이 돈다. 3_FMS/infra/worker 에서 `python -m pytest -q`."""
import json
import sys
import threading
import time
import os

import pytest

import estimate_worker as w

# 틱 수를 박지 않는다. 초 ÷ dt 로 유도해야 틱 모델이 또 바뀌어도 이 테스트가 산다 (-194).
DT = w.tick_seconds(0.9, w.SIM_ENGINE_DIR)      # 기본 속도 0.9 의 틱 길이[초]


def _ticks(sec, speed=0.9):
    return sec / w.tick_seconds(speed, w.SIM_ENGINE_DIR)


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
    # 무게 입력 없음 → 기본 0.9 m/s. 초 입력이 전부 초÷dt 로 틱이 된다.
    assert set(kw["extra_args"]) == {
        "--horizon=%d" % round(_ticks(21600)), "--speed=0.9", "--shifts=in,in,out,out,out,out",
        "--order-gap=%g" % _ticks(22.5), "--inbound-gap=%g" % _ticks(48.0)}
    # 되돌리면 요청한 초가 나와야 한다 — 이게 깨지면 6 h 요청이 다른 시간으로 돈다
    horizon = next(int(f.split("=")[1]) for f in kw["extra_args"] if f.startswith("--horizon"))
    assert horizon * DT == pytest.approx(21600, rel=1e-4)


def test_defaults_and_tag_sanitizing():
    kw = w.to_sim_args({"run_id": "a/b c", "horizon_s": 3600, "amr": {"count": 1}})
    assert kw["tag"] == "a_b_c"
    assert kw["seed"] == 42
    # 교대 없으면 출고 전용 (-191). 틱 수는 초에서 유도한다 (-194).
    assert kw["extra_args"] == ("--horizon=%d" % round(_ticks(3600)), "--speed=0.9", "--shifts=out")


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
    """평균 무게 + 기종 앵커 → speed_for_load. 50/100 kg, 1.2→1.0 이면 1.1 m/s."""
    amr = {"count": 3, "speed_empty": 1.2, "speed_loaded": 1.0, "max_payload_kg": 100, "avg_payload_kg": 50}
    extra = w.to_sim_args({**REQ, "amr": amr})["extra_args"]
    assert "--speed=1.1" in extra
    assert "--horizon=%d" % round(_ticks(21600, speed=1.1)) in extra
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


def _fake_pika(handle_result_status="failed"):
    """가짜 pika: ch.consume 이 메시지 1건을 주고 나서 (None, None, None) 을 무한히 준다(inactivity_timeout 폴).
    ack 가 나오면 stop_event 를 세워 루프를 끝낸다. 호출 순서는 calls 에 남는다."""
    import types
    calls, stop = [], threading.Event()

    class Ch:
        def basic_qos(self, prefetch_count): calls.append(("qos", prefetch_count))
        def consume(self, queue, inactivity_timeout):
            calls.append(("consume", queue, inactivity_timeout))
            yield types.SimpleNamespace(delivery_tag=7), None, b'{"run_id":"r1","amr":{"count":0}}'
            while True:
                calls.append(("poll",))
                time.sleep(inactivity_timeout)
                yield None, None, None
        def basic_publish(self, exchange, routing_key, body, properties): calls.append(("publish", routing_key, json.loads(body)["status"]))
        def basic_ack(self, delivery_tag): calls.append(("ack", delivery_tag)); stop.set()
        def basic_nack(self, delivery_tag, requeue): calls.append(("nack", delivery_tag, requeue))
        def cancel(self): calls.append(("cancel",))

    fake = types.ModuleType("pika")
    fake.URLParameters = lambda url: url
    fake.BlockingConnection = lambda p: types.SimpleNamespace(channel=lambda: Ch(), close=lambda: None)
    fake.BasicProperties = lambda **kw: kw
    fake.exceptions = types.SimpleNamespace(AMQPError=ConnectionError)
    return fake, calls, stop


def test_consume_publishes_then_acks(monkeypatch):
    """가짜 pika: 메시지 1건 → running 발행 → 작업 스레드가 handle → pika 스레드가 결과 발행 뒤 ack (명세 §1-3 순서 불변)."""
    fake, calls, stop = _fake_pika()
    monkeypatch.setitem(sys.modules, "pika", fake)
    w.consume(stop_event=stop, poll_s=0.01)
    kinds = [c[0] for c in calls]
    assert kinds[:2] == ["qos", "consume"] and calls[0] == ("qos", 1)
    assert [c for c in calls if c[0] in ("publish", "ack")] == [
        ("publish", "sim.result", "running"), ("publish", "sim.result", "failed"), ("ack", 7)]
    assert kinds.index("publish") < kinds.index("ack") < kinds.index("cancel")


def test_consume_keeps_polling_while_handle_runs(monkeypatch):
    """-222 핵심: handle 이 오래 걸리는 동안 pika 스레드는 폴(=heartbeat 처리)을 계속 돈다 — 옛 구조는 콜백 안에서 막혔다."""
    fake, calls, stop = _fake_pika()
    monkeypatch.setitem(sys.modules, "pika", fake)
    slow = w.handle
    def slow_handle(body):
        time.sleep(0.3)                      # 시뮬 서브프로세스 흉내
        return slow(body)
    monkeypatch.setattr(w, "handle", slow_handle)
    w.consume(stop_event=stop, poll_s=0.02)
    kinds = [c[0] for c in calls]
    polls_before_ack = kinds[:kinds.index("ack")].count("poll")
    assert polls_before_ack >= 5, f"handle 0.3 s 동안 폴이 {polls_before_ack}번 — pika 스레드가 막혔다"
    assert kinds.index("publish") < kinds.index("ack")


def test_job_wraps_unexpected_exception():
    """작업 스레드에서 handle 이 예외로 죽어도 failed 결과가 남아 ack 가 나갈 수 있다."""
    import types
    j = w.Job(1, b'{"run_id":"r9"}')
    j.thread = types.SimpleNamespace(start=lambda: None)
    orig = w.handle
    w.handle = lambda body: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        j._run()
    finally:
        w.handle = orig
    assert j.done.is_set() and j.result["status"] == "failed" and j.result["run_id"] == "r9" and "boom" in j.result["error"]


def test_explicit_orders_and_capacity_flags():
    """outbound[] 가 있으면 --orders-file, amr.capacity 가 정수면 --capacity. 비어 있거나 null 이면 둘 다 없음 (-156)."""
    req = {**REQ, "outbound": [{"order_id": 1, "ordered_at_s": 3, "lines": [{"product_id": 7, "rack_id": "A2", "qty": 1}]}]}
    extra = w.to_sim_args(req, orders_path="/tmp/o.json")["extra_args"]
    assert "--orders-file=/tmp/o.json" in extra
    svc = max(1, int(w.SVC_PER_TOTE_S / DT + 0.5))
    assert {"--capacity=6", "--tote-units=10", "--svc-per-tote=%d" % svc} <= set(extra)
    no_cap = w.to_sim_args({**req, "amr": {"count": 3, "capacity": None}}, orders_path="/tmp/o.json")["extra_args"]
    assert "--orders-file=/tmp/o.json" in no_cap
    assert not any(f.startswith("--capacity") for f in no_cap)
    assert "--tote-units=10" in no_cap
    assert "--svc-per-tote=%d" % svc in no_cap
    null_units = w.to_sim_args({**req, "amr": {"count": 3, "capacity": None, "tote_units": None}},
                               orders_path="/tmp/o.json")["extra_args"]     # 백엔드 실제 형식: 키는 있고 값은 null
    assert "--tote-units=10" in null_units
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
# ------------------------------------------------------------
# 리플레이 내보내기 (S15P21A106-205) — 시뮬 없이 산출물만 흉내 낸다
# ------------------------------------------------------------
def _write_export(tag, ticks, dt_s=0.5, robots=2, move_from=None):
    """export_isaac 이 만드는 모양의 디렉터리를 세운다. 경로를 돌려준다.

    move_from 을 주면 그 틱부터만 로봇이 움직인다 — 구간 선택을 시험하는 데 쓴다."""
    import os
    d = w._export_dir(tag)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "scene.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": {"map": "wallA"}, "grid": []}, f)

    def x_at(t):
        if move_from is None:
            return 1.0
        return 1.0 + max(0, t - move_from)

    traj = {"dt_s": dt_s, "model": "heading",
            "robots": {str(i): [[t * dt_s, x_at(t) + i, 2.0] for t in range(ticks)] for i in range(robots)},
            "headings": {str(i): [0.0] * ticks for i in range(robots)},
            # 주문 7 은 토트 2개(틱 4·20)로 나뉘었다 — 마지막이 배달된 20 이 그 주문의 완료다
            "tasks": [{"kind": "out", "order": 7, "completed": 20},
                      {"kind": "in", "order": 1, "completed": 10},
                      {"kind": "out", "order": 7, "completed": 4},
                      {"kind": "out", "order": 9, "completed": 8},
                      {"kind": "out", "order": 3},
                      {"kind": "supply"}]}
    with open(os.path.join(d, "trajectories.json"), "w", encoding="utf-8") as f:
        json.dump(traj, f)
    return d


def test_replay_thins_the_whole_run(monkeypatch):
    """run 전체를 담되 stride 간격으로 솎는다 — 원본은 run 하나가 28대 기준 19 MB 라 큐에 못 싣는다."""
    import os
    monkeypatch.setattr(w, "REPLAY_STRIDE", 4)
    d = _write_export("thin_case", ticks=400, dt_s=0.5)
    try:
        r = w._read_replay("thin_case")
        assert len(r["robots"]["0"]) == 100                  # 400 ÷ 4
        assert len(r["headings"]["0"]) == 100
        assert r["stride"] == 4
        # 샘플 간격이 화면의 dt 다. 원본 dt 를 주면 재생이 4배 느려진다
        assert r["dt_s"] == 2.0
        assert r["seconds"] == 200.0                          # 100 샘플 × 2초 = 원본 400틱 × 0.5초
        assert r["scene"]["meta"]["map"] == "wallA"
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)
    assert not os.path.exists(d)                              # 읽고 나면 지운다 (상주 워커 디스크 보호)


def test_replay_keeps_every_tick_when_stride_is_one(monkeypatch):
    """솎기를 끄면 원본 그대로 — 간격도 원본 dt 다."""
    monkeypatch.setattr(w, "REPLAY_STRIDE", 1)
    _write_export("full_case", ticks=30, dt_s=0.5)
    r = w._read_replay("full_case")
    assert len(r["robots"]["0"]) == 30
    assert r["dt_s"] == 0.5


def test_replay_counts_outbound_orders_not_trips(monkeypatch):
    """주문 단위로 센다.

    주문 하나가 여러 통로에 걸치면 토트가 나뉘어 AMR 왕복이 여러 번이다(실측 500주문 → 630태스크).
    왕복을 세면 사용자가 입력한 출고 건수와 어긋난다. 주문은 마지막 토트가 배달돼야 끝난다.
    입고는 담지 않고, 창 안에 못 끝난 주문(completed 없음)도 완료로 세지 않는다."""
    monkeypatch.setattr(w, "REPLAY_STRIDE", 4)
    _write_export("tasks_case", ticks=40, dt_s=0.5)
    done = w._read_replay("tasks_case")["outbound_done"]
    assert done == [4.0, 10.0]      # 주문 9 = 틱 8, 주문 7 = 틱 20(마지막 토트) → ×0.5초


def test_replay_missing_export_is_not_an_error():
    """내보내기가 꺼졌거나 시뮬이 중간에 죽으면 None. 리플레이 때문에 견적을 실패시키지 않는다."""
    assert w._read_replay("no_such_run") is None
