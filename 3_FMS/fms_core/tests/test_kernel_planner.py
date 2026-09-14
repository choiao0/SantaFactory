"""fms_core.kernel_planner — 실제 맵·커널로 Planner 규약(한 틱 한 칸·90°) · 이벤트 · 카운터 · KPI 가 cli/report 와 같은가."""
import contextlib
import io
import json
import os
from types import SimpleNamespace

import pytest

from fms_core import kpi as K
from fms_core import world as W
from fms_core.kernel_planner import KernelPlanner, des_homes, ensure_sim_engine
from fms_core.planner import PlannerSpec, build_planner

FMS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def racks():
    return sorted(json.load(open(os.path.join(FMS, "map", "rack_buffers.json"), encoding="utf-8"))["racks"])


def scenario(n_orders=3, gap=2):
    rk = racks()
    return {"seed": 42, "orders": {"outbound": [
        {"order_id": i + 1, "ordered_at_s": i * gap, "lines": [{"rack_id": rk[(7 * i) % len(rk)], "qty": 1}]}
        for i in range(n_orders)]}}


def make(n=2, sc=None, **opts):
    homes = tuple(des_homes(n))
    return build_planner("kernel", PlannerSpec("run-1", n, homes, sc if sc is not None else scenario(), opts))


def test_des_homes_match_spawn_contract_example():
    assert des_homes(3) == [(48, 103), (50, 103), (52, 103)]
    assert W.spawn_string(des_homes(2)) == "103.1,48.5;103.1,50.5"


def test_build_and_initial_views():
    p = make()
    views = p.robots()
    assert [v.cell for v in views] == [(48, 103), (50, 103)] and all(v.status == "IDLE" for v in views)
    assert all(v.h in (0, 1, 2, 3) for v in views) and p.counters() == {"open_tasks": 0, "done_tasks": 0, "orders_done": 0, "orders_total": 3}


def test_steps_are_unit_moves_and_track_views():
    p = make()
    kinds = set()
    for t in range(80):
        before = {v.rid: (v.cell, v.h) for v in p.robots()}
        cmds = p.step(t)
        after = {v.rid: (v.cell, v.h) for v in p.robots()}
        for cmd in cmds:
            assert (cmd.cell, cmd.h) == after[cmd.rid]
            assert cmd.kind == W.move_kind(before[cmd.rid][0] + (before[cmd.rid][1],), cmd.cell + (cmd.h,))
            kinds.add(cmd.kind)
        for rid, st in after.items():
            if all(cmd.rid != rid for cmd in cmds):
                assert st == before[rid], "no command ⇒ robot must not move"
    assert kinds and kinds <= {W.FORWARD, W.REVERSE, W.TURN}
    assert p.counters()["open_tasks"] >= 1


def test_events_and_counters_progress():
    p = make(n=2, sc=scenario(4, gap=1))
    seen = []
    for t in range(600):
        p.step(t)
        seen += p.drain_events()
        if p.counters()["orders_done"] >= 1:
            break
    types = [e["type"] for e in seen]
    assert "task_assigned" in types and "task_done" in types and "order_shipped" in types
    done = next(e for e in seen if e["type"] == "task_done")
    assert done["rid"] in (0, 1) and done["task_id"] >= 1
    c = p.counters()
    assert c["done_tasks"] >= 1 and c["orders_done"] >= 1 and c["orders_total"] == 4
    assert p.drain_events() == []


def test_kpi_matches_cli_report():
    """같은 커널 상태에서 cli/report.report() 의 SUMMARY 와 우리 KPI 산식이 일치해야 한다."""
    ensure_sim_engine()
    from cli.report import report
    p = make(n=2, sc=scenario(4, gap=1))
    T = 400
    for t in range(T):
        p.step(t)
    ours = K.summary(p.kernel, p.stream, 2, T, p.dt)
    cfg = p.kernel.cfg
    a = SimpleNamespace(variant="base", n_robots=2, n_orders=p.stream.n_orders, seed=42, aisle_block=False, flow="main",
                        horizon=T, shifts=("out",), order_gap=50, order_gap_arg=None, inbound_gap_arg=None, battery=False,
                        speed=1.0 / p.dt, dt=p.dt, footprint=cfg.footprint, robot_dims=cfg.robot_dims,
                        capacity=cfg.capacity, tote_units=8, lanes=True, yield_rule=cfg.yield_rule,
                        theta_path=None, dirflow=False, export=False)
    ctx = SimpleNamespace(H=p.kernel.H, W=p.kernel.W, turn_masked=0.0)
    with contextlib.redirect_stdout(io.StringIO()):
        theirs, _, _ = report(a, p.kernel, p.stream, ctx)
    for key in ("tasks_per_h", "orders_per_h", "lead_mean_s", "lead_p90_s", "queue_mean_s", "util_incl_service",
                "conflict_wait", "distance_m", "orders_done", "inbound_total", "tasks_in", "tasks_out", "open_tasks", "makespan_steps"):
        assert ours[key] == theirs[key], key
    block = p.kpi(T)
    assert set(block) == {"orders_total", "orders_completed", "inbound_total", "inbound_completed", "makespan_s",
                          "lead_time_mean_s", "lead_time_p90_s", "queue_time_mean_s", "throughput_orders_per_h",
                          "throughput_tasks_per_h", "amr_utilization", "conflict_wait_ratio", "distance_total_m", "charge_downtime_s"}
    assert block["makespan_s"] == round(T * p.dt) and block["throughput_tasks_per_h"] == theirs["tasks_per_h"]   # 초 = 틱 × dt (-116)


def test_defaults_are_the_des_estimate_conditions():
    """견적과 같은 조건으로 선다 — 통로차단 ON · 차선 비용 · 양보 ON · 토트 서비스 (계약 v2.6/v3, -185).
    조건 자체가 워커와 같은지는 test_des_parity.py 가 워커 코드에서 읽어 대조한다."""
    p = make()
    cfg = p.kernel.cfg
    assert cfg.capacity == 1 and cfg.svc_per_tote == 5, "왕복당 토트 수 · 토트당 서비스 틱"
    assert cfg.yield_rule is True and cfg.theta is True, "v3 정면 조우 양보 · θ/차선 비용"
    assert int(p.kernel.free.sum()) == 8640, "통로차단 ON 의 자유 칸 수 (OFF 면 9333)"
    assert p.kernel.lane_dir is not None, "차선 방향이 커널에 들어가야 양보 규칙이 산다"
    assert p.kernel.edge_cost.max() > 1.0, "차선 비용(기본 2.0)이 균일 1.0 이 아니어야 한다"


def test_capacity_is_totes_and_tote_units_group_lines():
    """v2.6 비호환 변경: amr.capacity = 왕복당 토트 수(1~6), amr.tote_units = 토트당 상품 수."""
    rk = racks()
    sc = {"seed": 42, "amr": {"capacity": 3, "tote_units": 8},
          "orders": {"outbound": [{"order_id": 1, "ordered_at_s": 0, "lines": [{"rack_id": rk[0], "qty": 17}]}]}}
    p = make(sc=sc)
    p.step(0)
    assert p.kernel.cfg.capacity == 3
    assert p.stream.totes_total == 3, "ceil(17 / 8)"


def test_oversize_order_is_dropped():
    """한 대에 실을 수 없는 주문(6토트 초과)은 팔레트 흐름으로 보고 시뮬 밖 — 개수만 센다 (-177)."""
    rk = racks()
    sc = {"seed": 42, "amr": {"tote_units": 1},
          "orders": {"outbound": [{"order_id": 1, "ordered_at_s": 0, "lines": [{"rack_id": rk[0], "qty": 7}]},
                                  {"order_id": 2, "ordered_at_s": 1, "lines": [{"rack_id": rk[1], "qty": 6}]}]}}
    p = make(sc=sc)
    assert p.stream.orders_oversize == 1 and p.stream.n_orders == 1


def test_service_steps_match_sim_v2():
    pytest.importorskip("matplotlib")
    ensure_sim_engine()
    os.environ.setdefault("MPLBACKEND", "Agg")
    from sim_v2_tasks import SERVICE_STEPS
    from fms_core.kernel_planner import SERVICE_TIME_S
    assert round(SERVICE_TIME_S / 1.0) == SERVICE_STEPS


def test_horizon_option_drops_late_orders():
    p = make(sc=scenario(3, gap=100), horizon_ticks=150)
    assert p.stream.n_orders == 2 and p.stream.orders_skipped == 1


def test_inbound_passthrough_generates_inbound():
    sc = scenario(2)
    sc.update(inbound_gap_s=30, shifts="in,out")
    p = make(sc=sc, horizon_ticks=600)
    assert p.stream.n_inbound > 0
    assert make(sc=scenario(2)).stream.n_inbound == 0


@pytest.mark.parametrize("homes,msg", [(((48, 103),), "!= n_robots"), (((0, 0), (48, 103)), "blocked"),
                                       (((48, 103), (48, 103)), "shared")])
def test_rejects_bad_homes(homes, msg):
    with pytest.raises(ValueError, match=msg):
        KernelPlanner(PlannerSpec("r", 2, homes, scenario()))


def test_unknown_rack_is_rejected():
    with pytest.raises(KeyError):
        make(sc={"orders": [{"ordered_at_s": 0, "lines": [{"rack_id": "ZZ99"}]}]})


def test_unknown_planner_name():
    with pytest.raises(ValueError, match="unknown planner"):
        build_planner("nope", PlannerSpec("r", 1, ((48, 103),)))
