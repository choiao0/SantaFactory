# -*- coding: utf-8 -*-
# ============================================================
# 견적 워커 (S15P21A106-155) — RabbitMQ sim.request 1건 → sim_v2_tasks.py 1회 → sim.result
#
# 계약: 5_Docs/Web/시뮬엔진연동API명세서.md v0.3 (§1-1 요청, §1-2 결과, §1-3 워커 규칙)
# 설계: 3_FMS/docs/견적_워커.md (필드 매핑·실패 처리·미룬 것)
#
#   python estimate_worker.py                      큐 소비 (상주). RABBITMQ_URL 또는 RABBITMQ_HOST/USER/PASSWORD
#   python estimate_worker.py --once <요청.json>   큐 없이 1건 실행, 결과 JSON 을 stdout 에
#
# 환경: SIM_ENGINE_DIR(기본 /work/sim_engine, 없으면 이 파일 기준 ../../sim_engine)
#       THETA_PATH(기본 <3_FMS>/infra/out/theta_wallA_r24_g15.json, "" 이면 중립)
#       SIM_TIMEOUT_S(기본 600)  SIM_REQUEST_QUEUE/SIM_RESULT_QUEUE(기본 sim.request/sim.result)
# ============================================================
import json
import os
import re
import sys
import tempfile
import time

from objective import SimFailed, run_once

HERE = os.path.dirname(os.path.abspath(__file__))
_LOCAL_FMS = os.path.dirname(os.path.dirname(HERE))                       # infra/worker → 3_FMS
SIM_ENGINE_DIR = os.environ.get("SIM_ENGINE_DIR") or (
    "/work/sim_engine" if os.path.isdir("/work/sim_engine") else os.path.join(_LOCAL_FMS, "sim_engine"))
FMS_DIR = os.path.dirname(SIM_ENGINE_DIR)
THETA_PATH = os.environ.get("THETA_PATH", os.path.join(FMS_DIR, "infra", "out", "theta_wallA_r24_g15.json"))
TIMEOUT_S = int(os.environ.get("SIM_TIMEOUT_S", "600"))
REQUEST_QUEUE = os.environ.get("SIM_REQUEST_QUEUE", "sim.request")
RESULT_QUEUE = os.environ.get("SIM_RESULT_QUEUE", "sim.result")
MAX_ROBOTS = 28            # 충전 존 초기 배치 상한 (SIM_RUN_CONTRACT §1 — 견적 제약)
DT = 1.0                   # 1틱 = 1초 (CELL_M 1.0 m / SPEED 1.0 m/s). 속도 반영은 docs/견적_워커.md "미룬 것"


def log(msg):
    print(f"[worker] {msg}", flush=True)


# ------------------------------------------------------------
# 요청 → sim_v2 인자
# ------------------------------------------------------------
def _require_core(req):
    """run_id · amr.count · horizon_s 검증 → (run_id, amr, n, horizon_ticks)."""
    if not isinstance(req, dict):
        raise ValueError("요청 본문이 JSON 객체가 아님")
    run_id = req.get("run_id")
    if not run_id or not isinstance(run_id, str):
        raise ValueError("run_id 없음")
    amr = req.get("amr") or {}
    n = amr.get("count")
    if not isinstance(n, int) or not 1 <= n <= MAX_ROBOTS:
        raise ValueError(f"amr.count 는 1~{MAX_ROBOTS} 정수: {n!r}")
    horizon_s = req.get("horizon_s")
    if not isinstance(horizon_s, (int, float)) or horizon_s <= 0:
        raise ValueError(f"horizon_s 는 양수 (고정 시간 실행 필수, 명세 §1-1): {horizon_s!r}")
    return run_id, amr, n, int(round(horizon_s / DT))


def _gap_flags(req):
    """outbound_gap_s / inbound_gap_s → --order-gap / --inbound-gap (초 = 틱)."""
    flags = []
    for key, flag in (("outbound_gap_s", "order-gap"), ("inbound_gap_s", "inbound-gap")):
        v = req.get(key)
        if v is None:
            continue
        if not isinstance(v, (int, float)) or v <= 0:
            raise ValueError(f"{key} 는 양수: {v!r}")
        flags.append(f"--{flag}={v / DT:g}")
    return flags


def _log_ignored(req, amr, run_id):
    """V1 에서 읽지 않는 필드 — 값이 오면 로그만 (결과에 영향 없음). docs/견적_워커.md"""
    for k in ("speed_empty", "speed_loaded"):
        if amr.get(k) not in (None, 1.0):
            log(f"{run_id}: amr.{k}={amr[k]} 는 V1 에서 무시 (커널 속도 1.0 m/s 고정)")
    if req.get("inbound"):
        log(f"{run_id}: 명시 inbound 리스트는 V1 에서 무시 (간격 기반 생성, 입고 시나리오 보류)")


def _orders_flags(req, amr, orders_path):
    """명시 출고 주문 (-156): outbound[] 가 있으면 --orders-file, amr.capacity 가 정수면 --capacity (상품 개수)."""
    if not (req.get("outbound") and orders_path):
        return []
    flags = [f"--orders-file={orders_path}"]
    cap = amr.get("capacity")
    if cap is None:
        return flags
    if isinstance(cap, bool) or not isinstance(cap, int) or cap < 1:
        raise ValueError(f"amr.capacity 는 1 이상 정수 (상품 개수): {cap!r}")
    return flags + [f"--capacity={cap}"]


def to_sim_args(req, orders_path=None):
    """명세 §1-1 요청 dict → run_once 키워드 인자. 잘못된 요청은 ValueError (시뮬을 돌리지 않는다).
    orders_path: 요청 outbound[] 를 써 둔 파일 (handle 이 만든다) → --orders-file (-156)."""
    run_id, amr, n, horizon = _require_core(req)
    extra = [f"--horizon={horizon}"]
    if req.get("shifts"):
        extra.append(f"--shifts={req['shifts']}")
    extra += _gap_flags(req)
    _log_ignored(req, amr, run_id)
    extra += _orders_flags(req, amr, orders_path)
    seed = req.get("seed")
    return dict(tag=re.sub(r"[^A-Za-z0-9_.-]", "_", run_id), n_robots=n, n_orders=0,
                seed=int(seed) if seed is not None else 42,
                theta_path=THETA_PATH or None, extra_args=tuple(extra))


# ------------------------------------------------------------
# SUMMARY → 결과 KPI (명세 §1-2, 14키)
# ------------------------------------------------------------
def to_kpi(s):
    return dict(
        orders_total=int(s["n_orders"]), orders_completed=int(s["orders_done"]),
        inbound_total=int(s["inbound_total"]), inbound_completed=int(s["tasks_in"]),
        makespan_s=int(round(s["makespan_steps"] * DT)),
        lead_time_mean_s=s["lead_mean_s"], lead_time_p90_s=s["lead_p90_s"], queue_time_mean_s=s["queue_mean_s"],
        throughput_orders_per_h=s["orders_per_h"], throughput_tasks_per_h=s["tasks_per_h"],
        amr_utilization=s["util_incl_service"],          # 주행+대기+서비스+회전 ÷ 대수×T (docs/견적_워커.md)
        conflict_wait_ratio=s["conflict_wait"],
        distance_total_m=int(s["distance_m"]),
        charge_downtime_s=int(round(s.get("charging_steps", 0) * DT)),
    )


def handle(body):
    """요청 바이트/문자열 → 결과 dict. 어떤 경우에도 예외 대신 failed 결과를 돌려준다 (명세 §1-3: 실패도 발행)."""
    run_id, orders_path = "?", None
    try:
        req = json.loads(body)
        run_id = req.get("run_id", "?") if isinstance(req, dict) else "?"
        if isinstance(req, dict) and req.get("outbound"):
            fd, orders_path = tempfile.mkstemp(prefix="orders_", suffix=".json")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"outbound": req["outbound"]}, f)
        kw = to_sim_args(req, orders_path)
        t0 = time.perf_counter()
        summary = run_once(SIM_ENGINE_DIR, timeout_s=TIMEOUT_S, **kw)
        log(f"{run_id}: n={kw['n_robots']} 완료 {time.perf_counter() - t0:.1f}s"
            + (f" (명시 주문 {len(req['outbound'])}건, 제외 {summary.get('orders_skipped', 0)})" if orders_path else ""))
        return dict(run_id=run_id, status="done", error=None, kpi=to_kpi(summary))
    except (ValueError, KeyError, SimFailed, json.JSONDecodeError) as e:
        log(f"{run_id}: 실패 — {e}")
        return dict(run_id=run_id, status="failed", error=str(e)[:2000], kpi=None)
    finally:
        if orders_path and os.path.exists(orders_path):
            os.remove(orders_path)


# ------------------------------------------------------------
# 큐 소비 (pika 는 여기서만 import — --once 와 테스트는 브로커 없이 돈다)
# ------------------------------------------------------------
def amqp_url():
    url = os.environ.get("RABBITMQ_URL")
    if url:
        return url
    host = os.environ.get("RABBITMQ_HOST", "localhost")
    user = os.environ.get("RABBITMQ_USER", "guest")
    pw = os.environ.get("RABBITMQ_PASSWORD", "guest")
    return f"amqp://{user}:{pw}@{host}:5672/"


def consume():
    import pika

    def on_message(ch, method, props, body):
        result = handle(body)
        ch.basic_publish(exchange="", routing_key=RESULT_QUEUE, body=json.dumps(result),
                         properties=pika.BasicProperties(content_type="application/json", delivery_mode=2))
        ch.basic_ack(delivery_tag=method.delivery_tag)          # 결과 발행 뒤에 ack (명세 §1-3)

    while True:
        try:
            conn = pika.BlockingConnection(pika.URLParameters(amqp_url()))
            ch = conn.channel()
            ch.basic_qos(prefetch_count=1)
            ch.basic_consume(queue=REQUEST_QUEUE, on_message_callback=on_message)
            log(f"소비 시작 {REQUEST_QUEUE} → {RESULT_QUEUE} (sim_engine={SIM_ENGINE_DIR}, theta={THETA_PATH or '중립'})")
            ch.start_consuming()
        except pika.exceptions.AMQPError as e:
            log(f"브로커 연결 실패/끊김: {e} — 5초 후 재시도")
            time.sleep(5)


def main(argv):
    if len(argv) >= 2 and argv[0] == "--once":
        with open(argv[1], encoding="utf-8") as f:
            print(json.dumps(handle(f.read()), ensure_ascii=False, indent=2))
        return
    consume()


if __name__ == "__main__":
    main(sys.argv[1:])
