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
#       SIM_TIMEOUT_S(기본 1200)  SIM_REQUEST_QUEUE/SIM_RESULT_QUEUE(기본 sim.request/sim.result)
# 주문: 요청의 outbound[] 가 **필수** — 백엔드 OutboundOrderGenerator 가 견적 생성 시 1회 만들어 저장한 목록(-197)이고,
#       같은 목록이 검증 런(scenario.orders)에도 간다. 비어 있으면 failed (워커 자체 생성 -158 은 2026-09-14 제거).
# 속도 (-116, 계약 v3.3): amr.avg_payload_kg(사용자 평균 적재 무게)가 있으면 contracts/speed_model.speed_for_load 로
#       amr.speed_empty·speed_loaded·max_payload_kg 앵커에서 속도를 정하고, 없으면 SPEED_DEFAULT(물리 계획 속도 0.9).
#       run 내내 고정. 초 단위 입력(horizon_s·gap·서비스 5 s)은 dt = CELL_M / speed 로 틱이 되고, KPI 초는 엔진 dt_s 로 되돌린다.
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
if FMS_DIR not in sys.path:                                                # contracts/ (이미지 안 /app/contracts, 로컬 3_FMS/contracts)
    sys.path.insert(0, FMS_DIR)
from contracts.speed_model import speed_for_load  # noqa: E402
TIMEOUT_S = int(os.environ.get("SIM_TIMEOUT_S", "1200"))   # 6,000건·28대: 이 PC 190 s, EC2 2~3배 (-191)
REQUEST_QUEUE = os.environ.get("SIM_REQUEST_QUEUE", "sim.request")
RESULT_QUEUE = os.environ.get("SIM_RESULT_QUEUE", "sim.result")
MAX_ROBOTS = 28            # 충전 존 초기 배치 상한 (SIM_RUN_CONTRACT §1 — 견적 제약)
CELL_M = 1.0               # 계획 격자 1칸 [m] (map_loader.CELL_M 와 같은 값). 틱 길이 = CELL_M / speed
SPEED_DEFAULT = 0.9        # 무게 입력이 없을 때의 고정 속도 [m/s] = 물리 시뮬 계획 속도 (물리 팀 답신 2026-09-13 §2-4). 세 팀 합의 시 여기만
SVC_PER_TOTE_S = 5.0       # 픽업·하역 각각 토트당 서비스 [초] (-177 승인값)


WORKER_ID = os.environ.get("HOSTNAME", "")[:12]     # 컨테이너 id 앞 12자 — 병렬 5개(-182) 로그 구분용. 로컬은 빈 문자열


def log(msg):
    print(f"[worker{(' ' + WORKER_ID) if WORKER_ID else ''}] {msg}", flush=True)


# ------------------------------------------------------------
# 요청 → sim_v2 인자
# ------------------------------------------------------------
def _require_core(req):
    """run_id · amr.count · horizon_s 검증 → (run_id, amr, n, horizon_s). 틱 환산은 속도가 정해진 뒤 호출자가 한다."""
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
    return run_id, amr, n, float(horizon_s)


def _speed(amr, run_id):
    """run 고정 속도 [m/s]. 사용자 평균 적재 무게(amr.avg_payload_kg)가 있으면 기종 앵커로 함수, 없으면 SPEED_DEFAULT.
    앵커(speed_empty·speed_loaded·max_payload_kg) 중 하나라도 없으면 계산할 수 없으니 기본값 + 로그 (run 은 돈다).
    무게가 음수 같은 잘못된 값은 ValueError → 결과 failed (조용히 다른 속도로 돌지 않는다)."""
    w = amr.get("avg_payload_kg")
    if w is None:
        return SPEED_DEFAULT
    if isinstance(w, bool) or not isinstance(w, (int, float)) or w < 0:
        raise ValueError(f"amr.avg_payload_kg 는 0 이상 숫자 (kg): {w!r}")
    anchors = {k: amr.get(k) for k in ("speed_empty", "speed_loaded", "max_payload_kg")}
    if any(v is None for v in anchors.values()):
        log(f"{run_id}: 속도 앵커 없음 {anchors} → 기본 {SPEED_DEFAULT} m/s")
        return SPEED_DEFAULT
    return speed_for_load(w, v_empty=anchors["speed_empty"], v_full=anchors["speed_loaded"],
                          max_load_kg=anchors["max_payload_kg"])


def _gap_flags(req, dt):
    """outbound_gap_s / inbound_gap_s → --order-gap / --inbound-gap (초 ÷ dt = 틱)."""
    flags = []
    for key, flag in (("outbound_gap_s", "order-gap"), ("inbound_gap_s", "inbound-gap")):
        v = req.get(key)
        if v is None:
            continue
        if not isinstance(v, (int, float)) or v <= 0:
            raise ValueError(f"{key} 는 양수: {v!r}")
        flags.append(f"--{flag}={v / dt:g}")
    return flags


def _log_ignored(req, amr, run_id):
    """V1 에서 읽지 않는 필드 — 값이 오면 로그만 (결과에 영향 없음). docs/견적_워커.md"""
    if req.get("inbound"):
        log(f"{run_id}: 명시 inbound 리스트는 V1 에서 무시 (간격 기반 생성, 입고 시나리오 보류)")


def _orders_flags(amr, orders_path, dt):
    """명시 출고 주문(v2.6): capacity=토트 수, tote_units 기본 8, 양 끝 서비스 5초/토트(틱으로 반올림, 최소 1)."""
    if not orders_path:
        return []
    flags = [f"--orders-file={orders_path}", f"--svc-per-tote={max(1, int(SVC_PER_TOTE_S / dt + 0.5))}"]
    cap = amr.get("capacity")
    if cap is not None:
        if isinstance(cap, bool) or not isinstance(cap, int) or not 1 <= cap <= 6:
            raise ValueError(f"amr.capacity 는 1~6 정수 (토트 수): {cap!r}")
        flags.append(f"--capacity={cap}")
    tote_units = amr.get("tote_units")
    if tote_units is None:                      # 백엔드는 amr 필드를 null 로 채워 보낸다 → 기본 8 (신발 상자 기준 가정)
        tote_units = 8
    if isinstance(tote_units, bool) or not isinstance(tote_units, int) or tote_units < 1:
        raise ValueError(f"amr.tote_units 는 1 이상 정수 (상품 개수): {tote_units!r}")
    return flags + [f"--tote-units={tote_units}"]


def to_sim_args(req, orders_path=None):
    """명세 §1-1 요청 dict → run_once 키워드 인자. 잘못된 요청은 ValueError (시뮬을 돌리지 않는다).
    orders_path: 출고 주문을 써 둔 파일 (handle 이 만든다 — 요청 outbound[] 또는 자체 생성) → --orders-file (-156/-158)."""
    run_id, amr, n, horizon_s = _require_core(req)
    speed = _speed(amr, run_id)
    dt = CELL_M / speed
    extra = [f"--horizon={int(round(horizon_s / dt))}", f"--speed={speed:g}"]
    # 교대: 요청이 주면 그대로, 없으면 출고 전용(-191). 팀 결정(2026-09-11) 견적 부하 = 6,000건/6h 출고만.
    # 엔진 기본 in,out,out 은 입고를 켜서 고밀도 교착(입고 × 차선·양보)까지 부른다. 결과 inbound_* 는 0 으로 남는다.
    extra.append(f"--shifts={req.get('shifts') or 'out'}")
    extra += _gap_flags(req, dt)
    _log_ignored(req, amr, run_id)
    extra += _orders_flags(amr, orders_path, dt)
    seed = req.get("seed")
    return dict(tag=re.sub(r"[^A-Za-z0-9_.-]", "_", run_id), n_robots=n, n_orders=0,
                seed=int(seed) if seed is not None else 42,
                theta_path=THETA_PATH or None, extra_args=tuple(extra))


# ------------------------------------------------------------
# SUMMARY → 결과 KPI (명세 §1-2, 14키)
# ------------------------------------------------------------
def to_kpi(s):
    dt = float(s.get("dt_s", 1.0))                        # 엔진 SUMMARY 의 틱 길이 (v3.3). 없으면 1틱 1초
    return dict(
        orders_total=int(s["n_orders"]), orders_completed=int(s["orders_done"]),
        inbound_total=int(s["inbound_total"]), inbound_completed=int(s["tasks_in"]),
        makespan_s=int(round(s["makespan_steps"] * dt)),
        lead_time_mean_s=s.get("order_lead_mean_s", s["lead_mean_s"]),
        lead_time_p90_s=s.get("order_lead_p90_s", s["lead_p90_s"]), queue_time_mean_s=s["queue_mean_s"],
        throughput_orders_per_h=s["orders_per_h"], throughput_tasks_per_h=s["tasks_per_h"],
        amr_utilization=s["util_incl_service"],          # 주행+대기+서비스+회전 ÷ 대수×T (docs/견적_워커.md)
        conflict_wait_ratio=s["conflict_wait"],
        distance_total_m=int(s["distance_m"]),
        charge_downtime_s=int(round(s.get("charging_steps", 0) * dt)),
    )


# ------------------------------------------------------------
# 출고 주문 — 백엔드가 만든 목록만 쓴다 (-197). 주문의 단일 원천은 백엔드 OutboundOrderGenerator 이고
# estimates.outbound_orders_json 에 저장된 그 목록이 DES 스윕(outbound[])과 검증 런(scenario.orders)에 똑같이 간다.
# 워커 자체 생성(-158, order_gen)은 2026-09-14 제거 — 두 생성기가 seed 가 같아도 다른 주문을 내서 원천을 하나로 뒀다.
# ------------------------------------------------------------
def _orders_file(req):
    """(임시 파일 경로, 건수). outbound[] 가 비어 있으면 ValueError → handle 이 failed 로 발행한다."""
    orders = req.get("outbound")
    if not isinstance(orders, list) or not orders:
        raise ValueError("outbound[] 가 비어 있음 — 주문은 백엔드가 생성해 요청에 싣는다 (S15P21A106-197)")
    fd, path = tempfile.mkstemp(prefix="orders_", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"outbound": orders}, f)
    return path, len(orders)


def handle(body):
    """요청 바이트/문자열 → 결과 dict. 어떤 경우에도 예외 대신 failed 결과를 돌려준다 (명세 §1-3: 실패도 발행)."""
    run_id, orders_path, n_orders = "?", None, 0
    try:
        req = json.loads(body)
        run_id = req.get("run_id", "?") if isinstance(req, dict) else "?"
        if isinstance(req, dict):
            orders_path, n_orders = _orders_file(req)
        kw = to_sim_args(req, orders_path)
        t0 = time.perf_counter()
        summary = run_once(SIM_ENGINE_DIR, timeout_s=TIMEOUT_S, **kw)
        log(f"{run_id}: n={kw['n_robots']} 완료 {time.perf_counter() - t0:.1f}s"
            + (f" (명시 주문 {n_orders}건, 제외 {summary.get('orders_skipped', 0)})" if orders_path else ""))
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
