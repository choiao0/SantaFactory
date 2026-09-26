"""fms-core 가 DES 견적과 같은 조건으로 도는가 — 두 커널의 설정·비용·KPI 대조 (S15P21A106-185).

검증 런의 KPI 는 견적 워커(infra/worker/estimate_worker.py → objective.run_once → sim_engine/sim_v2_tasks.py)가 낸
KPI 와 비교하려고 만든 값이다. 두 쪽 커널이 한 칸이라도 다르면 그 비교가 무의미해진다. 그래서 기준을 문서가 아니라
**워커 코드 자체**에서 읽어 와 대조한다 — sim_engine 이나 워커가 바뀌면(예: v2.6 토트 비호환 변경 -177) 여기서 깨진다.
fms_core 는 sim_engine 을 수정하지 않고 따라가는 쪽이다.
"""
import inspect
import json
import os
import sys

import numpy as np
import pytest

from fms_core import kpi as K
from fms_core.kernel_planner import DES_AISLE_BLOCK, DES_SPEED, ensure_sim_engine, des_homes, theta_path
from fms_core.planner import PlannerSpec, build_planner
from fms_core.scenario import DEFAULT_TOTE_UNITS, SVC_PER_TOTE_S, scenario_orders, stream_options


FMS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORKER_DIR = os.path.join(FMS, "infra", "worker")
N_ROBOTS = 2
HORIZON = 300


def scenario_shifts(sc: dict) -> tuple:
    """fms-core 가 쓸 교대 — 견적 쪽 요청에도 같은 값을 실어 두 실행을 맞춘다."""
    return stream_options(sc)["shifts"]


def racks():
    return sorted(json.load(open(os.path.join(FMS, "map", "rack_buffers.json"), encoding="utf-8"))["racks"])


def scenario(n_orders=6, gap=2, qty=1, amr=None):
    rk = racks()
    sc = {"seed": 42, "orders": {"outbound": [
        {"order_id": i + 1, "ordered_at_s": i * gap, "lines": [{"rack_id": rk[(7 * i) % len(rk)], "qty": qty}]}
        for i in range(n_orders)]}}
    if amr:
        sc["amr"] = amr
    return sc


@pytest.fixture(scope="module")
def sim_v2():
    """sim_v2_tasks 는 matplotlib 를 끌어온다 — 없으면 이 파일 전체 skip."""
    pytest.importorskip("matplotlib")
    os.environ.setdefault("MPLBACKEND", "Agg")
    ensure_sim_engine()
    import sim_v2_tasks
    return sim_v2_tasks


@pytest.fixture(scope="module")
def worker():
    """견적 워커 모듈 (기준). infra/worker 를 경로에 올린다 — objective 를 형제로 찾는다.

    sys.path 는 되돌리지 않는다(ensure_sim_engine 과 같은 방식): 워커·sim_engine 은 평면 import 라
    세션 내내 경로에 있어야 하고, 이 세션에 같은 이름의 모듈은 없다.
    """
    if WORKER_DIR not in sys.path:
        sys.path.insert(0, WORKER_DIR)
    import estimate_worker
    return estimate_worker


def des_build(sim_v2, worker, tmp_path, sc, n_robots=N_ROBOTS, horizon=HORIZON):
    """이 시나리오를 견적 워커가 받았다면 세웠을 sim_v2 실행(build)을 그대로 만든다.

    인자 조립은 워커 코드(to_sim_args)와 objective.run_once 의 명령줄 순서를 그대로 쓴다 — 여기서 손으로 옮겨 적는 건
    run_once 가 위치 인자로만 받는 aisle_block(기본 1) 하나뿐이고, 그 기본값도 test_worker_defaults 가 대조한다.
    """
    path = tmp_path / "orders.json"
    path.write_text(json.dumps({"outbound": scenario_orders(sc)}), encoding="utf-8")
    # 워커는 초를 받아 틱 = 초 / dt 로 환산한다 (-116). 기본 속도(무게 없음)의 dt 로 같은 틱 수가 되게 초를 준다.
    dt = worker.tick_seconds(worker.SPEED_DEFAULT, worker.SIM_ENGINE_DIR)
    req = {"run_id": "parity", "amr": dict(sc.get("amr") or {}, count=n_robots),
           "horizon_s": horizon * dt, "seed": sc.get("seed", 42),
           # 교대는 명시해서 맞춘다 — 견적의 기본값(in,out,out)과 검증 런의 기본값(out)이 다른 건 의도된 차이다
           # (test_verify_replays_one_outbound_window 참고). 입고 창은 도착 시각을 뽑느라 난수를 소비하므로
           # 교대가 다르면 같은 시드에서도 포장대 배정이 어긋난다.
           "shifts": ",".join(scenario_shifts(sc))}
    kw = worker.to_sim_args(req, str(path))
    argv = [kw["tag"], str(kw["n_robots"]), str(kw["n_orders"]), str(kw["seed"]), "1", "--flow=main"]
    if kw["theta_path"]:
        argv.append(f"--theta={kw['theta_path']}")
    argv += list(kw["extra_args"])
    return sim_v2.build(sim_v2.parse_args(argv))


def fms_build(sc, n_robots=N_ROBOTS, horizon=HORIZON):
    return build_planner("kernel", PlannerSpec("parity", n_robots, tuple(des_homes(n_robots)), sc,
                                               {"horizon_ticks": horizon}))


# ---- 기준값이 워커와 같은가 -------------------------------------------------------------
def test_worker_defaults(worker):
    """토트 상수·통로차단·θ·속도 를 워커에서 읽어 대조한다 (문서가 아니라 코드가 기준)."""
    assert DES_SPEED == worker.SPEED_DEFAULT, "무게 입력 없는 요청의 속도 — 틱 길이(서비스 틱·KPI 초)가 여기서 갈린다 (-116)"
    assert SVC_PER_TOTE_S == worker.SVC_PER_TOTE_S, "픽업·하역 토트당 서비스 [초]"
    dt = worker.tick_seconds(worker.SPEED_DEFAULT, worker.SIM_ENGINE_DIR)
    flags = worker._orders_flags({"capacity": 3}, "/tmp/orders.json", dt)
    assert f"--svc-per-tote={max(1, int(SVC_PER_TOTE_S / dt + 0.5))}" in flags, "픽업·하역 토트당 서비스 틱 = 초 / dt 반올림"
    assert f"--tote-units={DEFAULT_TOTE_UNITS}" in flags, "amr.tote_units 가 null 일 때의 기본 토트당 상품 수"
    assert "--capacity=3" in flags, "amr.capacity = 왕복당 토트 수 (v2.6)"
    from objective import run_once
    assert inspect.signature(run_once).parameters["aisle_block"].default == int(DES_AISLE_BLOCK), \
        "견적은 통로차단 ON 으로 돈다 — fms-core 도 같은 맵이어야 한다"
    assert theta_path() == (worker.THETA_PATH or None), "견적과 다른 θ 로 달리면 경로가 달라진다 (\"\" = 중립 = None)"


# ---- 커널 자체가 같은가 -----------------------------------------------------------------
def test_kernel_config_and_costs_match(sim_v2, worker, tmp_path):
    sc = scenario(amr={"capacity": 3, "tote_units": 8})
    p = fms_build(sc)
    kernel, stream, _ = des_build(sim_v2, worker, tmp_path, sc)
    assert p.kernel.cfg == kernel.cfg
    assert np.array_equal(p.kernel.free, kernel.free), "통로차단(aisle_block)이 다르면 자유 칸이 다르다"
    assert np.array_equal(p.kernel.edge_cost, kernel.edge_cost), "θ·차선 비용"
    assert np.array_equal(p.kernel.wait_cost, kernel.wait_cost)
    assert (p.kernel.lane_dir is None) == (kernel.lane_dir is None)
    if kernel.lane_dir is not None:
        assert np.array_equal(p.kernel.lane_dir, kernel.lane_dir), "차선 방향(v3 양보 규칙 입력)"
    assert [tuple(rb["pos"]) for rb in p.kernel.robots.values()] == [tuple(rb["pos"]) for rb in kernel.robots.values()]
    assert p.stream.n_orders == stream.n_orders and p.stream.orders_oversize == stream.orders_oversize


def test_same_orders_give_the_same_kpi(sim_v2, worker, tmp_path):
    """같은 주문·같은 홈이면 fms-core 의 틱 루프와 견적의 틱 루프가 같은 KPI 를 낸다 (검증 창 비교의 전제)."""
    sc = scenario(amr={"capacity": 3})
    p = fms_build(sc)
    kernel, stream, _ = des_build(sim_v2, worker, tmp_path, sc)
    for t in range(HORIZON):
        p.step(t)
    sim_v2.run_ticks(kernel, stream, HORIZON)
    assert K.summary(p.kernel, p.stream, N_ROBOTS, HORIZON) == K.summary(kernel, stream, N_ROBOTS, HORIZON)
    assert p.kpi(HORIZON) == K.des_block(K.summary(kernel, stream, N_ROBOTS, HORIZON, p.dt), p.dt)
    assert p.dt == worker.tick_seconds(worker.SPEED_DEFAULT, worker.SIM_ENGINE_DIR)
    assert p.kernel.trips == kernel.trips and p.stream.totes_total == stream.totes_total


def test_totes_group_lines_the_same_way(sim_v2, worker, tmp_path):
    """토트 수 = ceil(버퍼별 qty 합 / tote_units) — 한 주문 17개는 3토트(8개들이)."""
    sc = scenario(n_orders=1, qty=17, amr={"capacity": 3, "tote_units": 8})
    p = fms_build(sc)
    kernel, stream, _ = des_build(sim_v2, worker, tmp_path, sc)
    p.step(0)
    stream.arrivals(0)
    assert p.stream.totes_total == stream.totes_total == 3


def test_verify_replays_one_outbound_window():
    """의도된 차이 하나 — 교대 기본값.

    견적은 지평선 전체를 in,out,out 으로 돌린다(sim_v2 기본). 검증 런은 그 지평선 안의 한 창(출고 구간, 보통
    outbound 시작 + 90 분)만 재생하므로 창 길이(예: 600 초)에 in 교대를 다시 잘라 넣으면 그 시각의 견적 모델과
    오히려 달라진다. 그래서 기본은 출고 전용이고, 입고를 섞으려면 scenario.shifts 를 명시해야 한다.
    (SIM_VERIFY_CONTRACT §6 ① 검증 창)
    """
    assert stream_options({})["shifts"] == ("out",)
    assert stream_options({"inbound_gap_s": 30, "shifts": "in,out"})["shifts"] == ("in", "out")


# ---- 적재·서비스 기본값 (2026-09-23) ---------------------------------------------------
#   위 `test_worker_defaults` 는 `amr.capacity` 가 **있을 때** 플래그로 잘 넘어가는지를
#   본다. 안 보는 것이 둘 있다 — **없을 때의 기본값**과 **서비스 틱**이다. 둘 다
#   「같아야 한다」고 주석만 달려 있고 지키는 장치가 없었다.
def sim_v2_const(name):
    """`sim_v2_tasks` 의 모듈 상수를 **소스에서** 읽는다.

    import 하지 않는 이유는 `kernel_planner.py:23` 이 쓴 그대로다 — 그 모듈이
    matplotlib 을 끌어온다. 그래서 fms_core 는 `SERVICE_TIME_S` 를 사본으로 두고
    있고, **사본이 갈리는 것을 막는 장치가 이 함수다.**
    """
    import re
    src = open(os.path.join(FMS, "sim_engine", "sim_v2_tasks.py"), encoding="utf-8").read()
    m = re.search(rf"^{name}\s*=\s*([^\n#]+)", src, re.M)
    assert m, f"sim_v2_tasks 에서 {name} 을 못 찾았다 — 이름이 바뀌었으면 이 테스트도 고친다"
    return eval(m.group(1).strip())                      # noqa: S307 — 우리 저장소의 리터럴


def test_service_time_copy_has_not_drifted():
    """`kernel_planner.SERVICE_TIME_S` 는 `sim_v2_tasks` 의 **사본**이다.

    이 값이 갈리면 검증 커널의 서비스 틱이 견적과 달라지는데 **아무 에러도 안 난다.**
    t3_amr 쪽은 같은 자리에서 2026-09-22 에 두 번 틀렸다 (3 -> 4 -> 13).
    """
    from fms_core.kernel_planner import SERVICE_TIME_S
    assert SERVICE_TIME_S == sim_v2_const("SERVICE_TIME_S"), \
        "서비스 시간 사본이 상류와 갈렸다 — 검증 서비스 틱이 견적과 달라진다"


def test_service_steps_is_the_cli_value_not_the_dataclass_default(worker):
    """서비스 틱은 **CLI 가 넣는 값**이다 — dataclass 기본값(4)을 보면 안 된다.

    견적 워커는 `--service-steps` 를 **안 넘긴다.** 그러면 sim_v2 가
    `round(SERVICE_TIME_S / dt)` 로 정한다. 검증 커널(`kernel_planner.py:122`)도
    같은 식이어야 한다.
    """
    from fms_core.kernel_planner import SERVICE_TIME_S, des_dt
    dt = worker.tick_seconds(worker.SPEED_DEFAULT, worker.SIM_ENGINE_DIR)
    flags = worker._orders_flags({"capacity": 3}, "/tmp/orders.json", dt)
    assert not any(f.startswith("--service-steps") for f in flags), \
        "워커가 --service-steps 를 넘기기 시작했으면 검증도 그 값을 따라가야 한다"
    assert round(SERVICE_TIME_S / des_dt(None)) == round(sim_v2_const("SERVICE_TIME_S") / dt), \
        "검증 커널의 서비스 틱이 견적과 다르다"


def test_capacity_default_matches_the_worker_when_amr_is_absent(worker):
    """`scenario.amr` 가 없을 때 — 워커와 fms-core 가 같은 값으로 가는가.

    워커는 `amr.capacity` 가 없으면 `--capacity` 를 **안 붙인다**. 그러면 sim_v2 의
    기본값이 쓰인다. `DEFAULT_CAPACITY` 는 그 값과 같아야 한다.
    """
    import re
    dt = worker.tick_seconds(worker.SPEED_DEFAULT, worker.SIM_ENGINE_DIR)
    flags = worker._orders_flags({}, "/tmp/orders.json", dt)
    assert not any(f.startswith("--capacity") for f in flags), \
        "워커가 capacity 기본값을 명시하기 시작했다 — DEFAULT_CAPACITY 도 그 값으로"
    # sim_v2 의 `--capacity` 기본값은 `_parse_orders` 의 `_opt(..., int, N)` 에 있다.
    src = open(os.path.join(FMS, "sim_engine", "sim_v2_tasks.py"), encoding="utf-8").read()
    m = re.search(r'_opt\(argv,\s*"capacity",\s*int,\s*(\d+)\)', src)
    assert m, "sim_v2_tasks 에서 --capacity 기본값을 못 찾았다"
    from fms_core.scenario import DEFAULT_CAPACITY
    assert DEFAULT_CAPACITY == int(m.group(1)), \
        "amr 블록이 없을 때 워커와 fms-core 가 다른 capacity 로 간다"
