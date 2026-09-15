"""Run Control/Start 본문 → RunSpec, scenario → 커널 주문 (MQTT_CONTRACT §5.3 · SIM_VERIFY_CONTRACT §2).

sim-runner 와 같은 Start JSON 을 받는다(host-orch 가 두 노드에 같은 명령을 보낸다). scenario 의 sha 는 host-orch 와 같은
정규형(키 정렬 · 공백 없음)으로 다시 계산해 다르면 거절한다. scenario.window_start_s 가 있으면 주문 시각을 그만큼 앞당기고
음수가 된 주문은 버린다(검증 창 오프셋, SIM_VERIFY_CONTRACT §6 ①).
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
MAX_ROBOTS = 64
MAX_SCENARIO_BYTES = 512 * 1024
# 적재 기본값은 견적 워커(infra/worker/estimate_worker.py::_orders_flags)와 같은 값이어야 한다 — 검증 KPI 는 견적 KPI 와
# 비교하려고 내는 값이다. 워커와 대조하는 테스트: fms_core/tests/test_des_parity.py::test_worker_defaults.
DEFAULT_CAPACITY = 1          # 왕복당 토트 수 (요청에 amr.capacity 가 없으면 sim_v2 기본 1)
DEFAULT_TOTE_UNITS = 10       # 토트당 상품 수 (백엔드가 amr.tote_units 를 null 로 보낼 때). 2026-09-15 결정: 개인 주문 상한 10개·토트 10개들이 → 주문 1건 = 토트 1개 (계약 v3.9; v2.6~v3.8 은 8)
SVC_PER_TOTE_S = 5.0          # 픽업·하역 각각 토트당 서비스 [초] (워커 SVC_PER_TOTE_S, -177) — 틱은 kernel_planner 가 dt 로 환산
DEFAULT_ORDER_GAP = 50.0      # 주문 도착 간격 [틱] (sim_v2 --order-gap 기본) — 명시 주문 모드에선 입고 간격 기본값
MAX_TOTES_PER_TRIP = 6        # 선반형 AMR 3단 × 2 (sim_engine kernel.core.MAX_TOTES_PER_TRIP, -177)
DEFAULT_MANUFACTURER, DEFAULT_MODEL = "idealworks", "iw_hub"


def canonical_json(obj: Any) -> bytes:
    """sha 정규형 — host_orch.orchestrator.canonical_json(기준)과 같은 규칙."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def scenario_sha256(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj)).hexdigest()


@dataclass(frozen=True)
class Robot:
    serial: str
    manufacturer: str = DEFAULT_MANUFACTURER
    model: str = DEFAULT_MODEL


@dataclass(frozen=True)
class RunSpec:
    """Start 명령 (§5.3). 모르는 필드는 raw 에 남긴다."""
    run_id: str
    n_robots: int
    robots: tuple
    timeout_s: float = 900.0
    scenario: dict = field(default_factory=dict)
    scenario_sha256: Optional[str] = None
    raw: dict = field(default_factory=dict, compare=False)

    @staticmethod
    def from_json(text: str) -> "RunSpec":
        try:
            d = json.loads(text)
        except (ValueError, TypeError) as e:
            raise ValueError(f"Start is not JSON: {e}") from None
        if not isinstance(d, dict):
            raise ValueError("Start must be a JSON object")
        return RunSpec.from_dict(d)

    @staticmethod
    def from_dict(d: dict) -> "RunSpec":
        run_id = d.get("run_id")
        if not isinstance(run_id, str) or not SAFE_ID.match(run_id):
            raise ValueError("run_id must match [A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
        n = d.get("n_robots")
        if not _is_int(n) or not 1 <= n <= MAX_ROBOTS:
            raise ValueError(f"n_robots must be an integer in 1..{MAX_ROBOTS}")
        timeout = d.get("timeout_s", 900.0)
        if not _is_num(timeout) or timeout <= 0:
            raise ValueError("timeout_s must be a positive number")
        robots = _robots(d.get("models") or [], n)
        scenario = d.get("scenario")
        sha = None
        if scenario is not None:
            if not isinstance(scenario, dict):
                raise ValueError("scenario must be a JSON object")
            if len(canonical_json(scenario)) > MAX_SCENARIO_BYTES:
                raise ValueError("scenario too large")
            sha = scenario_sha256(scenario)
            claimed = d.get("scenario_sha256")
            if claimed is not None and claimed != sha:
                raise ValueError(f"scenario_sha256 mismatch: claimed {str(claimed)[:12]}… computed {sha[:12]}…")
        return RunSpec(run_id, n, robots, float(timeout), scenario or {}, sha, dict(d))


def _robots(models: Any, n: int) -> tuple:
    if not isinstance(models, list) or (models and len(models) != n):
        raise ValueError("models must be a list with exactly n_robots entries (or empty)")
    if not models:
        return tuple(Robot(f"amr{i + 1:02d}") for i in range(n))
    out = []
    for m in models:
        serial = m.get("serial") if isinstance(m, dict) else None
        if not isinstance(serial, str) or not SAFE_ID.match(serial):
            raise ValueError("each models[] entry needs a safe serial")
        out.append(Robot(serial, str(m.get("manufacturer") or DEFAULT_MANUFACTURER), str(m.get("model") or DEFAULT_MODEL)))
    if len({r.serial for r in out}) != len(out):
        raise ValueError("models[] serials must be unique")
    return tuple(out)


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


# ---- scenario → 커널 입력 ----------------------------------------------------------
def scenario_orders(scenario: dict) -> list:
    """scenario.orders(생성기 산출물 {meta, outbound} 또는 outbound 리스트) → [{ordered_at_s, lines[{rack_id, qty}]}].

    window_start_s 만큼 앞당기고 0 보다 이른 주문은 버린다. 형식이 틀리면 ValueError (Start 거절 사유가 된다).
    """
    orders = scenario.get("orders")
    if isinstance(orders, dict):
        orders = orders.get("outbound")
    if orders is None:
        return []
    if not isinstance(orders, list):
        raise ValueError("scenario.orders must be a list or {outbound: [...]}")
    offset = scenario.get("window_start_s", 0)
    if not _is_num(offset) or offset < 0:
        raise ValueError("scenario.window_start_s must be a non-negative number")
    out = []
    for i, od in enumerate(orders):
        if not isinstance(od, dict) or not _is_num(od.get("ordered_at_s")) or not isinstance(od.get("lines"), list):
            raise ValueError(f"scenario.orders[{i}] needs ordered_at_s and lines[]")
        t = int(od["ordered_at_s"]) - int(offset)
        if t < 0:
            continue
        lines = []
        for ln in od["lines"]:
            if not isinstance(ln, dict) or not isinstance(ln.get("rack_id"), str):
                raise ValueError(f"scenario.orders[{i}].lines needs rack_id")
            qty = ln.get("qty", 1)
            if not _is_int(qty) or qty < 1:
                raise ValueError(f"scenario.orders[{i}] qty must be a positive integer")
            lines.append({"rack_id": ln["rack_id"], "qty": qty})
        out.append({"ordered_at_s": t, "lines": lines, "order_id": od.get("order_id", i)})
    return out


def _amr_field(scenario: dict, name: str) -> Any:
    """scenario.<name> 우선, 없으면 scenario.amr.<name>. 백엔드는 채우지 않은 amr 필드를 null 로 보낸다."""
    v = scenario.get(name)
    if v is None and isinstance(scenario.get("amr"), dict):
        v = scenario["amr"].get(name)
    return v


def stream_options(scenario: dict) -> dict:
    """DES 요청 pass-through 필드 → OrderStream·KernelConfig 인자. 없으면 출고 전용(입고 없음).

    적재는 계약 v2.6(-177) 이후 두 값이다 — `capacity` = 왕복당 토트 수(1~6, 커널이 동승을 묶는 단위),
    `tote_units` = 토트당 상품 수(주문 스트림이 라인 qty 를 토트로 나누는 단위). 옛 계약의 capacity(상품 수)를
    그대로 보내면 범위에서 걸린다 — 조용히 다른 뜻으로 도는 것보다 낫다.
    기본값은 견적 워커와 같아야 한다(위 상수) — 다르면 같은 요청이 견적과 검증에서 다른 KPI 를 낸다.
    """
    opts: dict = {"seed": 42, "capacity": DEFAULT_CAPACITY, "tote_units": DEFAULT_TOTE_UNITS,
                  "svc_per_tote_s": SVC_PER_TOTE_S, "order_gap": DEFAULT_ORDER_GAP, "inbound_gap": None,
                  "shifts": ("out",)}
    seed = scenario.get("seed")
    if seed is not None:
        if not _is_int(seed):
            raise ValueError("scenario.seed must be an integer")
        opts["seed"] = seed
    cap = _amr_field(scenario, "capacity")
    if cap is not None:
        if not _is_int(cap) or not 1 <= cap <= MAX_TOTES_PER_TRIP:
            raise ValueError(f"scenario.capacity must be an integer 1..{MAX_TOTES_PER_TRIP} "
                             "(totes per trip since contract v2.6, not units)")
        opts["capacity"] = cap
    units = _amr_field(scenario, "tote_units")
    if units is not None:
        if not _is_int(units) or units < 1:
            raise ValueError("scenario.tote_units must be a positive integer (units per tote)")
        opts["tote_units"] = units
    out_gap = scenario.get("outbound_gap_s")
    if out_gap is not None:                      # 명시 주문 모드에선 입고 간격의 기본값으로만 쓰인다 (sim_v2 --order-gap)
        if not _is_num(out_gap) or out_gap <= 0:
            raise ValueError("scenario.outbound_gap_s must be positive")
        opts["order_gap"] = float(out_gap)
    gap = scenario.get("inbound_gap_s")
    if gap is not None:
        if not _is_num(gap) or gap <= 0:
            raise ValueError("scenario.inbound_gap_s must be positive")
        opts["inbound_gap"] = float(gap)
        shifts = scenario.get("shifts", "in,out,out")
        if not isinstance(shifts, str):
            raise ValueError("scenario.shifts must be a string like 'in,in,out'")
        toks = tuple(s.strip() for s in shifts.split(",") if s.strip())
        if not toks or any(s not in ("in", "out") for s in toks):
            raise ValueError("scenario.shifts tokens must be in|out")
        opts["shifts"] = toks
    return opts
