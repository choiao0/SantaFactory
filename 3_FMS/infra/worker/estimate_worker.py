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
#       THETA_PATH(기본 <3_FMS>/infra/out/theta_wallA_r20_c6_v36.json, "" 이면 중립)
#       THETA_MODEL(비면 꺼짐. 채우면 ai_theta 모델로 **대수별** θ 를 뽑고, 실패하면 THETA_PATH 로)
#       THETA_MAP_DIR(예측할 맵 폴더. 비면 공식 맵)  THETA_AI_DIR(기본 <3_FMS>/ai_theta)
#       SIM_TIMEOUT_S(기본 1200)  SIM_REQUEST_QUEUE/SIM_RESULT_QUEUE(기본 sim.request/sim.result)
# 주문: 요청의 outbound[] 가 **필수** — 백엔드 OutboundOrderGenerator 가 견적 생성 시 1회 만들어 저장한 목록(-197)이고,
#       같은 목록이 검증 런(scenario.orders)에도 간다. 비어 있으면 failed (워커 자체 생성 -158 은 2026-09-14 제거).
# 속도 (-116, 계약 v3.3): amr.avg_payload_kg(사용자 평균 적재 무게)가 있으면 contracts/speed_model.speed_for_load 로
#       amr.speed_empty·speed_loaded·max_payload_kg 앵커에서 속도를 정하고, 없으면 SPEED_DEFAULT(물리 계획 속도 0.9).
#       run 내내 고정. 초 단위 입력(horizon_s·gap·서비스 5 s)은 objective.tick_seconds 로 틱이 되고,
#       KPI 초는 엔진 SUMMARY 의 dt_s 로 되돌린다. **틱 길이 공식을 여기 적지 않는다** — v3.6(-194)에서
#       1칸이 4틱이 되며 CELL_M / speed 가 4배 틀린 값이 됐다(6h 요청이 1.5h 로 돌았다).
# ============================================================
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time

from objective import SimFailed, run_once, tick_seconds

HERE = os.path.dirname(os.path.abspath(__file__))
_LOCAL_FMS = os.path.dirname(os.path.dirname(HERE))                       # infra/worker → 3_FMS
SIM_ENGINE_DIR = os.environ.get("SIM_ENGINE_DIR") or (
    "/work/sim_engine" if os.path.isdir("/work/sim_engine") else os.path.join(_LOCAL_FMS, "sim_engine"))
FMS_DIR = os.path.dirname(SIM_ENGINE_DIR)
# 계약 v3.6(-194) 조건에서 뽑은 θ — 회전 마스크(v3.4) 위에서 재탐색한 값이다.
# 이전 기본값 theta_wallA_r24_g15.json 은 구 조건(24대 · gap 15 · 1토트 · 속도 1.0 ·
# 1칸=1틱 · 마스크 없음)이라 지금 시뮬과 다른 세계의 값이다.
THETA_PATH = os.environ.get("THETA_PATH",
                            os.path.join(FMS_DIR, "infra", "out", "theta_wallA_r20_c6_v36.json"))
if FMS_DIR not in sys.path:                                                # contracts/ (이미지 안 /app/contracts, 로컬 3_FMS/contracts)
    sys.path.insert(0, FMS_DIR)
from contracts.speed_model import speed_for_load  # noqa: E402
TIMEOUT_S = int(os.environ.get("SIM_TIMEOUT_S", "1200"))   # 6,000건·28대: 이 PC 190 s, EC2 2~3배 (-191)
REQUEST_QUEUE = os.environ.get("SIM_REQUEST_QUEUE", "sim.request")
RESULT_QUEUE = os.environ.get("SIM_RESULT_QUEUE", "sim.result")
MAX_ROBOTS = 28            # 충전 존 초기 배치 상한 (SIM_RUN_CONTRACT §1 — 견적 제약)
SPEED_DEFAULT = 0.9        # 무게 입력이 없을 때의 고정 속도 [m/s] = 물리 시뮬 계획 속도 (물리 팀 답신 2026-09-13 §2-4). 세 팀 합의 시 여기만
SVC_PER_TOTE_S = 5.0       # 픽업·하역 각각 토트당 서비스 [초] (-177 승인값)
# 리플레이 궤적을 몇 틱마다 하나씩 남길지 (S15P21A106-205). run 전체를 담되 솎아낸다 —
# 원본 그대로면 run 하나가 2.7 MB(4대)·19 MB(28대)라 큐와 DB 에 담을 것이 못 된다.
# 4 로 두면 run 당 0.67 MB(4대) 이고 샘플 간격이 4.4 초인데, 화면이 ×32 로 재생하므로
# 한 프레임이 시뮬 0.5 초다 — 원본(1.1 초)도 이미 프레임보다 성기고, 사이는 보간이 메운다.
REPLAY_STRIDE = max(1, int(os.environ.get("REPLAY_STRIDE", "4")))


WORKER_ID = os.environ.get("HOSTNAME", "")[:12]     # 컨테이너 id 앞 12자 — 병렬 5개(-182) 로그 구분용. 로컬은 빈 문자열


def log(msg):
    print(f"[worker{(' ' + WORKER_ID) if WORKER_ID else ''}] {msg}", flush=True)


# ------------------------------------------------------------
# θ 예측 (S15P21A106-206) — 기본은 꺼져 있다
#
# THETA_MODEL 이 비어 있으면 이 부분은 **한 줄도 안 돌고**, 견적은 지금까지와 비트 단위로
# 같은 고정 θ(THETA_PATH)로 돈다. 켜도 실패하면 조용히 고정 θ 로 떨어진다 — 모델 때문에
# 견적이 멈추면 안 된다.
#
# **대수마다 다른 θ 를 뽑는다.** 견적 1건은 1~28대 run 을 한꺼번에 발행하는데, 모델 입력의
# `fleet` 이 바로 그 대수다. 파일 하나를 THETA_PATH 로 묶으면 20대에서 뽑은 값이 1대에도
# 28대에도 똑같이 들어간다.
#
# 대수별로 한 번만 예측해 캐시한다(최대 28항). 예측 1회가 무작위 후보 10만 개라 1초대이고
# run 은 분 단위라 무시할 만하다. 모델은 seed 가 고정이라 같은 입력이면 같은 θ 가 나온다.
# ------------------------------------------------------------
THETA_MODEL = os.environ.get("THETA_MODEL", "")            # joblib 경로. 비면 꺼짐
THETA_MAP_DIR = os.environ.get("THETA_MAP_DIR") or None    # 비면 공식 맵
_THETA_CACHE = {}
_THETA_LOCK = threading.Lock()


def _theta_for(n_robots):
    """대수 → θ 파일 경로. 꺼져 있거나 예측이 실패하면 고정 θ 그대로."""
    if not THETA_MODEL:
        return THETA_PATH or None
    fixed = THETA_PATH or None
    with _THETA_LOCK:
        if n_robots in _THETA_CACHE:
            return _THETA_CACHE[n_robots]
        path = None
        try:
            ai_dir = os.environ.get("THETA_AI_DIR") or os.path.join(FMS_DIR, "ai_theta")
            if ai_dir not in sys.path:
                sys.path.insert(0, ai_dir)
            import predict as theta_predict     # 늦게 부른다 — 꺼져 있으면 sklearn 이 없어도 된다
            path = theta_predict.theta_file_for(fleet=float(n_robots), model_path=THETA_MODEL,
                                                map_dir=THETA_MAP_DIR)
        except Exception as e:
            log(f"θ 예측 실패({n_robots}대): {type(e).__name__}: {e}")
        if path is None:
            log(f"θ 를 못 뽑았다({n_robots}대) — 고정 θ 로 돌린다: {fixed or '중립'}")
            path = fixed
        else:
            log(f"θ 예측 {n_robots}대 → {path}")
        _THETA_CACHE[n_robots] = path
        return path


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
    """명시 출고 주문(v2.6): capacity=토트 수, tote_units 기본 10(v3.9; 개인 주문 상한 10개 = 토트 1개), 양 끝 서비스 5초/토트(틱으로 반올림, 최소 1)."""
    if not orders_path:
        return []
    flags = [f"--orders-file={orders_path}", f"--svc-per-tote={max(1, int(SVC_PER_TOTE_S / dt + 0.5))}"]
    cap = amr.get("capacity")
    if cap is not None:
        if isinstance(cap, bool) or not isinstance(cap, int) or not 1 <= cap <= 6:
            raise ValueError(f"amr.capacity 는 1~6 정수 (토트 수): {cap!r}")
        flags.append(f"--capacity={cap}")
    tote_units = amr.get("tote_units")
    if tote_units is None:                      # 백엔드는 amr 필드를 null 로 채워 보낸다 → 기본 10 (2026-09-15 결정: 상한 10개·토트 10개들이. fms_core DEFAULT_TOTE_UNITS 와 같아야)
        tote_units = 10
    if isinstance(tote_units, bool) or not isinstance(tote_units, int) or tote_units < 1:
        raise ValueError(f"amr.tote_units 는 1 이상 정수 (상품 개수): {tote_units!r}")
    return flags + [f"--tote-units={tote_units}"]


def to_sim_args(req, orders_path=None):
    """명세 §1-1 요청 dict → run_once 키워드 인자. 잘못된 요청은 ValueError (시뮬을 돌리지 않는다).
    orders_path: 출고 주문을 써 둔 파일 (handle 이 만든다 — 요청 outbound[] 또는 자체 생성) → --orders-file (-156/-158)."""
    run_id, amr, n, horizon_s = _require_core(req)
    speed = _speed(amr, run_id)
    dt = tick_seconds(speed, SIM_ENGINE_DIR)      # 시뮬과 같은 상수로 (-194)
    extra = [f"--horizon={int(round(horizon_s / dt))}", f"--speed={speed:g}"]
    # 교대: 요청이 주면 그대로, 없으면 출고 전용(-191). 팀 결정(2026-09-11) 견적 부하 = 6,000건/6h 출고만.
    # 엔진 기본도 v3.16 부터 out 이지만 여기서도 명시한다 — 요청 로그에 교대가 보이게. 결과 inbound_* 는 0 으로 남는다.
    extra.append(f"--shifts={req.get('shifts') or 'out'}")
    extra += _gap_flags(req, dt)
    _log_ignored(req, amr, run_id)
    extra += _orders_flags(amr, orders_path, dt)
    seed = req.get("seed")
    return dict(tag=re.sub(r"[^A-Za-z0-9_.-]", "_", run_id), n_robots=n, n_orders=0,
                seed=int(seed) if seed is not None else 42,
                theta_path=_theta_for(n), extra_args=tuple(extra))


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


# ------------------------------------------------------------
# 리플레이 내보내기 (S15P21A106-205)
# ------------------------------------------------------------
def _export_dir(tag):
    return os.path.join(SIM_ENGINE_DIR, f"isaac_export_{tag}")


def _thin(series, stride):
    """틱 배열을 stride 간격으로 솎는다. 로봇별 dict 도 그대로 받는다."""
    if isinstance(series, dict):
        return {k: v[::stride] for k, v in series.items() if isinstance(v, list)}
    return series[::stride] if isinstance(series, list) else series


def _outbound_done_seconds(traj, dt_s):
    """출고 <b>주문</b>이 완료된 시각(초) 목록. 화면이 "지금까지 몇 건 나갔나"를 세는 데 쓴다.

    태스크가 아니라 주문을 센다. 주문 하나가 여러 통로에 걸치면 토트가 나뉘어 AMR 왕복이
    여러 번이라(실측 500주문 → 630태스크), 태스크를 세면 사용자가 입력한 출고 건수와 어긋난다.
    주문은 <b>마지막 토트가 배달돼야</b> 끝나므로 order 별 최대 완료 시각을 쓴다.

    입고는 빼고 출고(kind == "out")만 담는다 — 견적 판정도 출고 처리율만 본다.
    좌표와 달리 솎지 않는다. 숫자 하나씩이라 수천 건이어도 수십 KB 다.
    """
    last = {}
    for i, task in enumerate(traj.get("tasks") or []):
        if not isinstance(task, dict) or task.get("kind") != "out":
            continue
        at = task.get("completed")
        if not isinstance(at, (int, float)):
            continue                       # 창 안에 못 끝난 주문 — 완료로 세지 않는다
        # order 가 없는 옛 내보내기면 태스크마다 따로 센다(주문 단위를 알 수 없으므로)
        key = task.get("order", f"task:{i}")
        last[key] = max(last.get(key, at), at)
    return sorted(round(at * dt_s, 1) for at in last.values())


def _read_replay(tag):
    """export_isaac 산출물 → 앞 REPLAY_SECONDS 구간만 남긴 재생 데이터. 읽고 나면 디렉터리를 지운다.

    상주 프로세스라 run 마다 20 MB 를 남기면 디스크가 찬다. 파일이 없거나 깨졌으면 None 을 준다 —
    리플레이는 곁다리라 이것 때문에 견적을 실패로 만들지 않는다.
    """
    exp_dir = _export_dir(tag)
    scene_path, traj_path = os.path.join(exp_dir, "scene.json"), os.path.join(exp_dir, "trajectories.json")
    try:
        if not (os.path.exists(scene_path) and os.path.exists(traj_path)):
            log(f"{tag}: 리플레이 산출물이 없습니다 (내보내기가 꺼졌거나 시뮬이 중간에 끝남)")
            return None
        with open(scene_path, encoding="utf-8") as f:
            scene = json.load(f)
        with open(traj_path, encoding="utf-8") as f:
            traj = json.load(f)
        dt_s = float(traj.get("dt_s") or 0) or 1.0
        robots = _thin(traj.get("robots") or {}, REPLAY_STRIDE)
        # 솎은 뒤의 샘플 간격이 화면이 쓸 dt 다. 원본 dt 를 그대로 주면 재생이 stride 배 느려진다
        sample_dt = dt_s * REPLAY_STRIDE
        covered = max((len(v) for v in robots.values()), default=0) * sample_dt
        return {"dt_s": sample_dt, "model": traj.get("model"), "seconds": round(covered, 1),
                "stride": REPLAY_STRIDE,
                "robots": robots, "headings": _thin(traj.get("headings") or {}, REPLAY_STRIDE),
                "outbound_done": _outbound_done_seconds(traj, dt_s),
                "scene": scene}
    except (OSError, ValueError) as e:
        log(f"{tag}: 리플레이 산출물을 읽지 못했습니다 — {e}")
        return None
    finally:
        shutil.rmtree(exp_dir, ignore_errors=True)


def handle(body):
    """요청 바이트/문자열 → 결과 dict. 어떤 경우에도 예외 대신 failed 결과를 돌려준다 (명세 §1-3: 실패도 발행)."""
    run_id, orders_path, n_orders, tag = "?", None, 0, None
    try:
        req = json.loads(body)
        run_id = req.get("run_id", "?") if isinstance(req, dict) else "?"
        if isinstance(req, dict):
            orders_path, n_orders = _orders_file(req)
        kw = to_sim_args(req, orders_path)
        tag = kw["tag"]
        # 요청에 없으면 안 만든다 (계약 §1-3 "모르는 필드 무시" 와 짝 — 옛 백엔드는 이 키를 안 보낸다).
        # run_once 가 os.environ 을 그대로 자식에게 넘기므로 여기서 켜고 끝나면 되돌린다. prefetch 1 이라 겹치지 않는다
        want_replay = bool(req.get("export_replay")) if isinstance(req, dict) else False
        if want_replay:
            os.environ["SIM_EXPORT_ISAAC"] = "1"
        t0 = time.perf_counter()
        try:
            summary = run_once(SIM_ENGINE_DIR, timeout_s=TIMEOUT_S, **kw)
        finally:
            os.environ.pop("SIM_EXPORT_ISAAC", None)
        result = dict(run_id=run_id, status="done", error=None, kpi=to_kpi(summary))
        if want_replay:
            result["replay"] = _read_replay(tag)
        log(f"{run_id}: n={kw['n_robots']} 완료 {time.perf_counter() - t0:.1f}s"
            + (f" (명시 주문 {n_orders}건, 제외 {summary.get('orders_skipped', 0)})" if orders_path else "")
            + (f", 리플레이 {result['replay']['seconds']:.0f}s" if want_replay and result.get("replay") else ""))
        return result
    except (ValueError, KeyError, SimFailed, json.JSONDecodeError) as e:
        log(f"{run_id}: 실패 — {e}")
        return dict(run_id=run_id, status="failed", error=str(e)[:2000], kpi=None)
    finally:
        if orders_path and os.path.exists(orders_path):
            os.remove(orders_path)
        if tag:                       # 실패로 빠져나온 경우에도 내보내기 찌꺼기를 남기지 않는다
            shutil.rmtree(_export_dir(tag), ignore_errors=True)


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


# AMQP 소비(pika 스레드)와 시뮬 실행(작업 스레드)의 분리 (S15P21A106-222, 2026-09-16).
#   옛 구조는 basic_consume 콜백 안에서 handle()(시뮬 서브프로세스, 최대 SIM_TIMEOUT_S) 을 막고 기다렸다. 그동안 pika 가
#   프레임을 못 처리해 heartbeat(브로커 기본 60 s)가 2회 결측되면 연결이 끊기고, 끝난 뒤 publish/ack 가 닫힌 채널에 떨어져
#   메시지가 재큐 → 같은 run 을 다시 2분 → 무한 반복, 백엔드는 run-timeout. 6h 28대 run 이 EC2·리플레이·워커 2개 경합에서 2분을 넘긴다.
#   새 구조는 host_orch/amqp.py Consumer 와 같은 꼴: pika 스레드가 ch.consume(inactivity_timeout=POLL_S) 제너레이터로 폴링하고
#   (그 사이 heartbeat 처리), 일은 작업 스레드 하나가 하고, 완료를 보면 **같은 pika 스레드에서** publish → ack 한다.
#   채널은 pika 스레드만 만지므로 add_callback_threadsafe 도 락도 없다. prefetch 1 이라 진행 중 job 은 항상 하나.
POLL_S = float(os.environ.get("SIM_POLL_S", "1.0"))     # 폴 간격 [s] — heartbeat(60 s) 보다 충분히 짧으면 된다
RECONNECT_S = 5.0


def _run_id(body):
    try:
        return json.loads(body).get("run_id", "?")
    except Exception:  # noqa: BLE001
        return "?"


def _publish(pika, ch, payload):
    ch.basic_publish(exchange="", routing_key=RESULT_QUEUE, body=json.dumps(payload),
                     properties=pika.BasicProperties(content_type="application/json", delivery_mode=2))


class Job:
    """요청 1건의 작업 스레드. handle() 은 예외를 안 내지만(failed 결과), 스레드에서 새면 안 되니 한 번 더 감싼다."""

    def __init__(self, delivery_tag, body):
        self.delivery_tag, self.body = delivery_tag, body
        self.run_id = _run_id(body)
        self.result = None
        self.done = threading.Event()
        self.thread = threading.Thread(target=self._run, name="sim-job", daemon=True)

    def start(self):
        self.thread.start()
        return self

    def _run(self):
        try:
            self.result = handle(self.body)
        except Exception as e:  # noqa: BLE001 — 작업 스레드가 죽으면 ack 도 결과도 없이 큐가 막힌다
            self.result = dict(run_id=self.run_id, status="failed", error=f"worker internal error: {e}"[:2000], kpi=None)
        finally:
            self.done.set()


def _serve(pika, conn, stop_event, poll_s):
    """연결 하나의 수명: 폴링 루프. 진행 중 job 은 연결이 끊겨도 계속 돌고(§2), 재연결 뒤 결과를 발행한다."""
    ch = conn.channel()
    ch.basic_qos(prefetch_count=1)
    log(f"소비 시작 {REQUEST_QUEUE} → {RESULT_QUEUE} (sim_engine={SIM_ENGINE_DIR}, "
        f"theta={('예측 ' + THETA_MODEL) if THETA_MODEL else (THETA_PATH or '중립')}, poll={poll_s:g}s)")
    job = None
    for method, _props, body in ch.consume(REQUEST_QUEUE, inactivity_timeout=poll_s):
        if stop_event.is_set():
            if job is not None and not job.done.is_set():
                ch.basic_nack(delivery_tag=job.delivery_tag, requeue=True)     # 재배포: 진행 중 건은 다른 워커에게
            ch.cancel()
            return
        if method is not None:                              # 새 요청 (prefetch 1 → job 이 없을 때만 온다)
            job = Job(method.delivery_tag, body)
            _publish(pika, ch, dict(run_id=job.run_id, status="running"))   # 집었다고 먼저 알린다 (명세 §1-2)
            job.start()
        if job is not None and job.done.is_set():
            _publish(pika, ch, job.result)
            ch.basic_ack(delivery_tag=job.delivery_tag)     # 결과 발행 뒤 ack (명세 §1-3) — pika 스레드에서
            job = None


def consume(stop_event=None, poll_s=POLL_S):
    import pika
    stop_event = stop_event or threading.Event()
    while not stop_event.is_set():
        try:
            conn = pika.BlockingConnection(pika.URLParameters(amqp_url()))
            try:
                _serve(pika, conn, stop_event, poll_s)
            finally:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass
        except pika.exceptions.AMQPError as e:
            log(f"브로커 연결 실패/끊김: {e} — {RECONNECT_S:.0f}초 후 재시도")
            stop_event.wait(RECONNECT_S)


def main(argv):
    if len(argv) >= 2 and argv[0] == "--once":
        with open(argv[1], encoding="utf-8") as f:
            print(json.dumps(handle(f.read()), ensure_ascii=False, indent=2))
        return
    consume()


if __name__ == "__main__":
    main(sys.argv[1:])
