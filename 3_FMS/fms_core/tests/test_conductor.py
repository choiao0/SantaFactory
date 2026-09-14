"""fms_core.conductor — NBIRTH 사전 · Start/Stop · 정렬 · 틱 배리어 · 재발행/정체/오류 → ERROR · kpi_summary · 실제 커널 통합."""
import logging

import pytest

from fms_core import conductor as C
from fms_core import spb
from fms_core import world as W
from fms_core.kernel_planner import des_homes
from fms_core.planner import Command, RobotView
from fms_core.tests.fakes import FakePublisher, PerfectRobots, ncmd, start_payload, vda_connection, vda_state
from fms_core.kernel_planner import des_dt
from fms_core.tests.test_kernel_planner import MOVE_TICKS, scenario

SERIALS = ["amr01", "amr02"]
POSES = [(36.0, 40.8, 0.0), (39.0, 40.8, 0.0)]          # Isaac 기본 spawn → 칸 (40,36) · (40,39)


class FakePlanner:
    def __init__(self, spec, script):
        self.spec, self.n_robots, self.script = spec, spec.n_robots, script
        self.cells, self.hs = list(spec.homes), [1] * spec.n_robots
        self.steps, self._events, self.kpi_calls = [], [], []

    def robots(self):
        return tuple(RobotView(i, self.cells[i], self.hs[i], "IDLE") for i in range(self.n_robots))

    def step(self, t):
        self.steps.append(t)
        cmds = self.script.get(t, ())
        for cmd in cmds:
            self.cells[cmd.rid], self.hs[cmd.rid] = cmd.cell, cmd.h
        self._events.append(dict(type="task_assigned", order_id=1, task_id=t + 1, rid=0, tick=t))
        return tuple(cmds)

    def drain_events(self):
        out, self._events = self._events, []
        return out

    def counters(self):
        return {"open_tasks": 1, "done_tasks": len(self.steps), "orders_done": 0, "orders_total": 1}

    def kpi(self, t_end):
        self.kpi_calls.append(t_end)
        return {"orders_total": 1, "makespan_s": t_end}


class Harness:
    def __init__(self, tmp_path, script=None, factory=None, **cfg):
        self.pub = FakePublisher()
        self.session = spb.EdgeSession(str(tmp_path / "bdseq"))
        self.session.new_session()
        self.planners = []

        def fake_factory(name, spec):
            p = FakePlanner(spec, script or {})
            self.planners.append(p)
            return p
        self.c = C.Conductor(C.ConductorConfig(**cfg), self.session, self.pub, factory or fake_factory)
        self.robots = PerfectRobots(self.c, self.pub, SERIALS, POSES)

    @property
    def planner(self):
        return self.planners[-1]

    def start(self, now=1.0, n=2, **over):
        self.c.on_ncmd(ncmd(**{C.CMD_START: start_payload(n=n, **over)}), now)

    def robots_ready(self, now=2.0, n=2):
        for serial, (x, y, th) in list(zip(SERIALS, POSES))[:n]:
            self.c.on_vda(*vda_connection(serial), now)
            self.c.on_vda(*vda_state(serial, x, y, th), now)

    def to_running(self, now=3.0):
        """Start → 로봇 준비 → 정렬 order 도착 → RUNNING. 반환: 마지막 now."""
        self.start(now - 2.0)
        self.robots_ready(now - 1.0)
        self.c.tick(now - 0.5)          # 플래너 생성 + 정렬 order
        self.robots.deliver(now)        # 정렬 도착
        self.c.tick(now)
        assert self.c.state == C.RUNNING
        return now


def fwd(rid, cell, h=1):
    return Command(rid, W.FORWARD, cell, h)


# ---- 세션 · 명령 -------------------------------------------------------------------
def test_nbirth_declares_the_contract_metrics(tmp_path):
    h = Harness(tmp_path)
    h.c.on_connected(0.0)
    m = h.pub.named("NBIRTH")
    assert set(m) == set(C.NODE_METRICS) >= {"bdSeq", "Node Control/Rebirth", "Fms/RunId", "Fms/Tick", "Fms/RobotsOnline",
                                             "Fms/OpenTasks", "Fms/DoneTasks", "Run Control/Start", "Run Control/Stop"}
    assert m["Fms/State"] == "IDLE" and m["Fms/Planner"] == "kernel" and m["bdSeq"] == h.session.bd_seq
    assert h.pub.msgs[0][1].seq == 0


def test_rebirth_and_host_state_republish_nbirth(tmp_path):
    h = Harness(tmp_path)
    h.c.on_connected(0.0)
    h.c.on_ncmd(ncmd(**{C.REBIRTH: True}), 1.0)
    h.c.on_host_state(b'{"online": true, "timestamp": 5}', 2.0)
    h.c.on_host_state(b'{"online": true, "timestamp": 9}', 3.0)
    h.c.on_host_state(b'{"online": true, "timestamp": 9}', 4.0)
    assert h.pub.kinds().count("NBIRTH") == 3       # connect · Rebirth · timestamp 증가 (같은 ts 는 무시)


def test_start_waits_for_robots_then_aligns(tmp_path):
    h = Harness(tmp_path)
    h.start(1.0, scenario={"seed": 1})
    assert h.c.state == C.STARTING
    nd = h.pub.values()
    assert nd["Fms/State"] == "STARTING" and nd["Fms/RunId"] == "run-1" and len(nd["Fms/ScenarioSha"]) == 64
    h.c.tick(1.5)
    assert h.pub.orders() == [] and not h.planners
    h.robots_ready(2.0)
    h.c.tick(2.5)
    assert h.planner.spec.homes == ((40, 36), (40, 39)) and h.planner.spec.scenario == {"seed": 1}
    for serial, (x, y, _), cell in zip(SERIALS, POSES, h.planner.spec.homes):
        o0, o1 = h.pub.orders(serial)
        assert o0["orderUpdateId"] == 0 and o0["nodes"][0]["nodePosition"]["x"] == x
        assert o1["orderUpdateId"] == 1 and o1["nodes"][1]["nodePosition"] ["x"] == pytest.approx(W.cell_center(cell)[0])
        assert o1["nodes"][1]["nodePosition"]["theta"] == pytest.approx(W.heading_yaw(1))
        assert o1["nodes"][1]["nodePosition"]["mapId"] == "wallA"
    assert h.c.state == C.STARTING


def test_retained_connection_before_start_counts(tmp_path):
    """connection ONLINE 은 retained 라 구독 직후(런 없음)에만 온다 — Start 뒤 state 만 와도 ready 가 돼야 한다 (E2E 2026-09-09 실패 원인)."""
    h = Harness(tmp_path)
    for serial in SERIALS:
        h.c.on_vda(*vda_connection(serial), 0.5)
    h.start(1.0)
    for serial, (x, y, th) in zip(SERIALS, POSES):
        h.c.on_vda(*vda_state(serial, x, y, th), 2.0)
    h.c.tick(2.5)
    assert h.planners and h.c.state == C.STARTING and len(h.pub.orders()) == 4
    h.c.on_vda(*vda_connection("amr02", "CONNECTIONBROKEN"), 3.0)        # 런 중 단절은 여전히 즉시 반영
    h.c.tick(3.1)
    assert h.c.state == C.ERROR


def test_stale_pose_is_not_reused_across_runs(tmp_path):
    """이전 런의 포즈는 새 런에 쓰지 않는다 — Start 뒤 새 state 가 와야 플래너를 만든다."""
    h = Harness(tmp_path)
    h.to_running(3.0)
    h.c.on_ncmd(ncmd(**{C.CMD_STOP: True}), 4.0)
    n_before = len(h.planners)
    h.start(5.0, run_id="run-2")
    h.c.tick(5.5)
    assert len(h.planners) == n_before and h.c.state == C.STARTING
    for serial, (x, y, th) in zip(SERIALS, POSES):
        h.c.on_vda(*vda_state(serial, x, y, th), 6.0)
    h.c.tick(6.5)
    assert len(h.planners) == n_before + 1


def test_alignment_ack_makes_running_and_first_tick_runs(tmp_path):
    h = Harness(tmp_path, script={0: [fwd(0, (40, 37))]})
    h.to_running(3.0)
    assert h.pub.values()["Fms/State"] == "RUNNING"
    h.c.tick(3.1)                                    # tick_started_at = now - tick_s → 첫 틱 즉시
    assert h.planner.steps == [0]
    o = h.pub.orders("amr01")[-1]
    assert o["orderUpdateId"] == 2 and o["nodes"][1]["nodePosition"]["x"] == pytest.approx(37.1)
    assert len(h.pub.orders("amr02")) == 2           # 명령 없는 로봇은 갱신 없음
    nd = h.pub.values()
    assert nd["Fms/Tick"] == 1 and nd["Fms/DoneTasks"] == 1
    assert h.pub.events("task_assigned")[0]["robot"]["serial"] == "amr01"


def test_tick_barrier_waits_for_arrival_and_min_tick(tmp_path):
    h = Harness(tmp_path, script={0: [fwd(0, (40, 37))], 1: [fwd(1, (40, 40))]}, tick_s=1.0)
    now = h.to_running(3.0)
    h.c.tick(now + 0.1)                              # step 0
    h.c.tick(now + 5.0)                              # amr01 미도착 → 배리어
    assert h.planner.steps == [0]
    h.robots.deliver(now + 5.1)
    h.c.tick(now + 5.2)                              # 도착 + 1 s 넘음 → step 1
    assert h.planner.steps == [0, 1]
    h.robots.deliver(now + 5.3)                      # amr02 즉시 도착
    h.c.tick(now + 5.4)                              # 아직 tick_s 안 → 대기
    assert h.planner.steps == [0, 1]
    h.c.tick(now + 6.3)
    assert h.planner.steps == [0, 1, 2]


def test_unreflected_states_trigger_resend_then_error(tmp_path):
    h = Harness(tmp_path, script={0: [fwd(0, (40, 37))]})
    now = h.to_running(3.0)
    h.c.tick(now + 0.1)
    n_orders = len(h.pub.orders("amr01"))
    h.robots.idle_state(now + 0.5, "amr01", update=1)
    h.c.tick(now + 0.6)
    assert len(h.pub.orders("amr01")) == n_orders
    h.robots.idle_state(now + 1.0, "amr01", update=1)
    h.c.tick(now + 1.1)
    assert len(h.pub.orders("amr01")) == n_orders + 1 and h.pub.orders("amr01")[-1]["orderUpdateId"] == 2
    for i in range(10):                              # tick 을 끼워 넣어도(실운영) 10건에서 오류가 난다 (리뷰 2026-09-09)
        h.robots.idle_state(now + 2 + i * 0.5, "amr01", update=1)
        h.c.tick(now + 2.1 + i * 0.5)
        if h.c.state == C.ERROR:
            break
    assert i == 7, "3+…+10 = 8번째 state(누적 10건)에서 오류"
    assert h.c.state == C.ERROR and "ignores orderUpdateId 2 after 10 states" in h.pub.values()["Fms/LastError"]
    assert len(h.pub.orders("amr01")) == n_orders + 4     # 2·4·6·8건째에서 재발행, 10건째에서 오류


def test_ack_timeout_is_not_deferred_by_resends(tmp_path):
    h = Harness(tmp_path, script={0: [fwd(0, (40, 37))]}, ack_timeout_s=30.0)
    now = h.to_running(3.0)
    h.c.tick(now + 0.1)
    for i in range(1, 8):                            # 4 s 마다 미반영 state 1건 → 8건째까지 재발행만, 30 s 에 도착 상한
        h.robots.idle_state(now + 4 * i, "amr01", update=1)
        h.robots.idle_state(now + 4 * i, "amr02")
        h.c.tick(now + 4 * i + 0.1)
    assert h.c.state == C.RUNNING and len(h.pub.orders("amr01")) == 3 + 3      # 2·4·6건째 재발행
    h.c.tick(now + 31.0)
    assert h.c.state == C.ERROR and "did not reach n2 within 30s" in h.pub.values()["Fms/LastError"]


def test_ack_timeout_fails_the_run(tmp_path):
    h = Harness(tmp_path, script={0: [fwd(0, (40, 37))]}, ack_timeout_s=30.0)
    now = h.to_running(3.0)
    h.c.tick(now + 0.1)
    for i in range(1, 7):                            # 반영은 됐지만(orderUpdateId 2) 도착(n2)이 없는 state 가 계속 온다
        h.robots.idle_state(now + 5 * i, "amr01", update=2, node="n1")
        h.robots.idle_state(now + 5 * i, "amr02")
        h.c.tick(now + 5 * i + 0.1)
    assert h.c.state == C.RUNNING and len(h.pub.orders("amr01")) == 3
    h.c.tick(now + 31.0)
    assert h.c.state == C.ERROR and "did not reach n2" in h.pub.values()["Fms/LastError"]


@pytest.mark.parametrize("what,expect", [("fatal", "primitiveError"), ("broken", "CONNECTIONBROKEN"), ("silent", "silent")])
def test_robot_faults_fail_the_run(tmp_path, what, expect):
    h = Harness(tmp_path, robot_silence_s=30.0)
    now = h.to_running(3.0)
    if what == "fatal":
        h.c.on_vda(*vda_state("amr02", 39.0, 40.8, 0.0, errors=[{"errorType": "primitiveError", "errorLevel": "FATAL"}]), now + 1)
        h.c.tick(now + 1.1)
    elif what == "broken":
        h.c.on_vda(*vda_connection("amr02", "CONNECTIONBROKEN"), now + 1)
        h.c.tick(now + 1.1)
    else:
        h.c.tick(now + 40.0)
    assert h.c.state == C.ERROR and expect in h.pub.values()["Fms/LastError"]
    assert len(h.pub.actions("amr01")) == 1 and h.pub.events("kpi_summary")[-1]["status"] == "failed"


def test_stop_cancels_orders_and_publishes_kpi(tmp_path):
    h = Harness(tmp_path, script={0: [fwd(0, (40, 37))]})
    now = h.to_running(3.0)
    h.c.tick(now + 0.1)
    h.robots.deliver(now + 1.0)
    h.c.tick(now + 1.2)
    h.c.on_ncmd(ncmd(**{C.CMD_STOP: True}), now + 2.0)
    assert h.c.state == C.IDLE
    for serial in SERIALS:
        assert h.pub.actions(serial)[-1]["actions"][0]["actionType"] == "cancelOrder"
    ev = h.pub.events("kpi_summary")[-1]
    assert ev["runId"] == "run-1" and ev["status"] == "done" and ev["kpi"] == {"orders_total": 1, "makespan_s": 2}
    assert ev["ticks"] == 2 and ev["counters"]["done_tasks"] == 2 and ev["planner"] == "kernel"
    assert h.pub.msgs[-1][2] == 0 or any(q == 1 for t, _, q, _ in h.pub.msgs if t == "biz/v1/event")
    nd = h.pub.values()
    assert nd["Fms/State"] == "IDLE" and nd["Fms/RunId"] == "" and h.planner.kpi_calls == [2]
    assert h.c.snapshot()["kpi"] == ev["kpi"]


def test_stop_before_running_has_no_kpi(tmp_path):
    h = Harness(tmp_path)
    h.start(1.0)
    h.c.on_ncmd(ncmd(**{C.CMD_STOP: True}), 2.0)
    assert h.c.state == C.IDLE and h.pub.events("kpi_summary")[-1]["kpi"] is None and h.pub.actions() == []


def test_start_idempotent_and_busy(tmp_path):
    h = Harness(tmp_path)
    h.start(1.0)
    h.pub.clear()
    h.start(2.0)
    assert h.pub.named("NDATA") == {"Fms/State": "STARTING", "Fms/RunId": "run-1"}
    h.start(3.0, run_id="run-2")
    assert h.pub.values()["Fms/LastError"].startswith("busy: STARTING run-1")
    assert h.c.state == C.STARTING and h.c.spec.run_id == "run-1"


def test_bad_start_reports_error_only(tmp_path):
    h = Harness(tmp_path)
    h.c.on_ncmd(ncmd(**{C.CMD_START: "{\"run_id\": \"x y\"}"}), 1.0)
    assert h.c.state == C.IDLE and h.pub.values()["Fms/LastError"].startswith("bad Start")
    h.c.on_ncmd(b"\x00garbage", 1.0)                 # 깨진 protobuf 는 무시


def test_ready_timeout(tmp_path):
    h = Harness(tmp_path, ready_timeout_s=10.0)
    h.start(1.0)
    h.c.on_vda(*vda_connection("amr01"), 2.0)
    h.c.tick(12.0)
    assert h.c.state == C.ERROR and "ready timeout" in h.pub.values()["Fms/LastError"]


def test_timeout_s_and_host_offline_fail_the_run(tmp_path):
    h = Harness(tmp_path, host_offline_s=15.0)
    now = h.to_running(3.0)
    h.c.on_host_state(b'{"online": false, "timestamp": 1}', now + 1)
    h.c.tick(now + 10)
    assert h.c.state == C.RUNNING
    h.c.tick(now + 17)
    assert h.c.state == C.ERROR and "host-orch offline" in h.pub.values()["Fms/LastError"]
    h2 = Harness(tmp_path)
    now = h2.to_running(3.0)
    h2.start(now, timeout_s=5)                       # 같은 run_id 반복 → 상태만
    h2.c.tick(now + 700)
    assert h2.c.state == C.ERROR and "timeout_s" in h2.pub.values()["Fms/LastError"]


@pytest.mark.parametrize("exc", [ValueError("no map"), OSError("theta.json: permission denied")])
def test_planner_build_failure_is_run_error(tmp_path, exc):
    """플래너 생성 실패는 런 오류 — 데몬 틱 루프를 뚫고 나가면 안 된다 (θ·맵 파일 I/O 포함)."""
    def bad(name, spec):
        raise exc
    h = Harness(tmp_path, factory=bad)
    h.start(1.0)
    h.robots_ready(2.0)
    h.c.tick(2.5)
    assert h.c.state == C.ERROR and h.pub.values()["Fms/LastError"] == f"planner build failed: {exc}"


def test_heartbeat_reports_robots_online(tmp_path):
    h = Harness(tmp_path, heartbeat_s=5.0)
    h.c.on_connected(0.0)
    h.start(1.0)
    h.robots_ready(2.0)
    h.c.tick(6.0)
    nd = h.pub.values()
    assert nd["Fms/Heartbeat"] == 6000 and nd["Fms/RobotsOnline"] == 2


def test_planner_warnings_are_logged(tmp_path):
    """플래너 경고(예: θ 파일 없음 → 중립 θ)는 런 로그에 남아야 한다 — 조용히 견적과 다른 조건으로 도는 게 최악이다."""
    def warn_factory(name, spec):
        p = FakePlanner(spec, {})
        p.warnings = ["[WARN] θ 파일이 없어 중립 θ 로 진행"]
        return p
    seen = []

    class Collect(logging.Handler):
        def emit(self, record):
            seen.append(record.getMessage())

    handler = Collect(level=logging.WARNING)
    logger = logging.getLogger("fms_core")
    logger.addHandler(handler)
    try:
        h = Harness(tmp_path, factory=warn_factory)
        now = h.to_running(1.0)
        h.c.on_ncmd(ncmd(**{C.CMD_STOP: True}), now + 1.0)
    finally:
        logger.removeHandler(handler)
    assert any("중립 θ" in m for m in seen)
    # 로그만으로는 부족하다 — 결과를 견적과 비교하는 쪽(host-orch → sim.verify.result.verify.fms)이
    # "이 KPI 는 견적과 다른 조건에서 나왔다"를 알 수 있어야 한다.
    ev = h.pub.events("kpi_summary")[-1]
    assert ev["warnings"] == ["[WARN] θ 파일이 없어 중립 θ 로 진행"]
    assert h.c.snapshot()["warnings"] == ev["warnings"]


def test_kpi_summary_has_no_warnings_key_noise(tmp_path):
    """경고가 없으면 null — 있는 런만 눈에 띄어야 한다."""
    h = Harness(tmp_path)
    now = h.to_running(1.0)
    h.c.on_ncmd(ncmd(**{C.CMD_STOP: True}), now + 1.0)
    assert h.pub.events("kpi_summary")[-1]["warnings"] is None


# ---- 실제 커널 통합 ------------------------------------------------------------------
def test_kernel_planner_end_to_end_with_perfect_robots(tmp_path):
    """DES 홈에서 출발한 2대가 완벽한 로봇이면 커널 배차·이동이 order 로 나가고 KPI 가 나온다."""
    homes = des_homes(2)
    poses = [W.cell_center(c) + (0.0,) for c in homes]
    # 벽시계 틱을 DES 틱에 맞춘다 — 운영(app.py)이 tick_s = des_dt() 로 채우는 그 값이다.
    # 1.0 을 박아 두면 1칸이 여러 틱인 모델(-194)에서 커널이 MOVE_TICKS 배 느리게 돌아
    # 런이 timeout_s 에 걸린다.
    h = Harness(tmp_path, factory=None, tick_s=des_dt())
    h.c.planner_factory = __import__("fms_core.planner", fromlist=["build_planner"]).build_planner
    h.robots = PerfectRobots(h.c, h.pub, SERIALS, poses)
    h.start(1.0, scenario=scenario(4, gap=1))
    for serial, (x, y, th) in zip(SERIALS, poses):
        h.c.on_vda(*vda_connection(serial), 2.0)
        h.c.on_vda(*vda_state(serial, x, y, th), 2.0)
    now = 3.0
    h.c.tick(now)
    h.robots.deliver(now + 0.5)
    h.c.tick(now + 0.6)
    assert h.c.state == C.RUNNING
    # 벽시계 한 걸음 = 틱 길이. 1.1 을 박아 두면 틱이 잘아졌을 때(v3.6) 시계만 빨리 흘러
    # 로봇 침묵 워치독(30 s)에 걸린다 — 실제로 걸렸다 (-194).
    step_s = des_dt() * 0.99
    for i in range(500 * MOVE_TICKS):
        now += step_s
        h.c.tick(now)
        h.robots.deliver(now + 0.5, idle=True)      # 명령 없는 틱에도 실 로봇은 state 를 낸다
        if h.c.values[C.DONE_TASKS] >= 1:
            break
    assert h.c.values[C.DONE_TASKS] >= 1 and h.c.t > 50
    h.c.on_ncmd(ncmd(**{C.CMD_STOP: True}), now + 1)
    ev = h.pub.events("kpi_summary")[-1]
    assert ev["status"] == "done" and ev["kpi"]["orders_total"] == 4 and ev["kpi"]["throughput_tasks_per_h"] > 0
    assert ev["kpi"]["distance_total_m"] > 0 and h.pub.events("task_done")
    kinds = {o["edges"][0].get("orientation") is not None for o in h.pub.orders() if o["edges"]}
    assert kinds                                     # 전진/회전(그리고 있으면 후진)이 order 로 나갔다
