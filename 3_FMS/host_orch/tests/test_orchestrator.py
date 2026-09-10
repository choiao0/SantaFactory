"""host_orch.orchestrator — 요청 검증 · Job 상태기계 · 결과 · Coordinator."""
import json

import pytest

from host_orch import orchestrator as O
from host_orch import spb
from host_orch.tracker import HostTracker, Node


def req_json(**over):
    d = {"run_id": "verify-1", "n_robots": 2, "scenario_pkg": "wallA", "window_s": 60, "estimate_id": 7,
         "source_run_id": "est_7_n2", "seed": 42}
    d.update(over)
    return json.dumps(d)


class TestVerifyRequest:
    def test_parses_and_builds_start_command_with_margin(self):
        r = O.VerifyRequest.from_json(req_json())

        assert r.run_id == "verify-1" and r.window_s == 60.0 and r.estimate_id == 7 and r.seed == 42
        assert r.start_command() == {"run_id": "verify-1", "scenario_pkg": "wallA", "n_robots": 2, "models": [],
                                     "ros_domain_id": 0, "timeout_s": 60.0 + O.START_MARGIN_S}

    def test_explicit_timeout_and_models_pass_through(self):
        r = O.VerifyRequest.from_json(req_json(timeout_s=900, models=[{"serial": "amr01"}, {"serial": "amr02", "model": "iw_hub"}]))

        assert r.start_command()["timeout_s"] == 900.0
        assert r.start_command()["models"][1] == {"serial": "amr02", "model": "iw_hub"}

    @pytest.mark.parametrize("bad", ["nope", "[]", req_json(run_id="../x"), req_json(n_robots=0), req_json(n_robots=True),
                                     req_json(window_s=0), req_json(timeout_s=-1), req_json(ros_domain_id=999),
                                     req_json(models=[{"serial": "a"}]), req_json(models=[{"serial": "a/b"}, {"serial": "c"}])])
    def test_rejects_bad_requests(self, bad):
        with pytest.raises(ValueError):
            O.VerifyRequest.from_json(bad)


class Cmd:
    def __init__(self):
        self.starts, self.stops, self.rebirths = [], 0, 0

    def start(self, text):
        self.starts.append(json.loads(text))

    def stop(self):
        self.stops += 1

    def rebirth(self):
        self.rebirths += 1


def node(state="IDLE", run_id="", online=True, last_seen=0.0, last_error="", rtf=None, ram=None, devices=()):
    n = Node("sim-runner-gpu01", online=online, bd_seq=1, seq=0, last_seen=last_seen)
    n.metrics = {O.STATE: state, O.RUN_ID: run_id, O.LAST_ERROR: last_error}
    if rtf is not None:
        n.metrics[O.RTF] = rtf
    if ram is not None:
        n.metrics[O.RAM] = ram
    from host_orch.tracker import Device
    n.devices = {d: Device(d) for d in devices}
    return n


def make_job(now=0.0, **cfg):
    return O.Job(O.VerifyRequest.from_json(req_json()), "sim-runner-gpu01", O.JobConfig(**cfg), now), Cmd()


class TestJob:
    def test_happy_path_start_running_window_stop_done(self):
        job, cmd = make_job()

        job.step(node("IDLE"), 0.0, cmd)
        assert job.phase == O.STARTING and cmd.starts[0]["run_id"] == "verify-1" and cmd.starts[0]["n_robots"] == 2
        job.step(node("STARTING", "verify-1"), 1.0, cmd)
        job.step(node("RUNNING", "verify-1", last_seen=2.0, rtf=1.2, ram=300, devices=("amr01", "amr02")), 2.0, cmd)
        assert job.phase == O.RUNNING and job.started_at == 2.0
        job.step(node("RUNNING", "verify-1", last_seen=60.0, rtf=0.8, ram=350, devices=("amr01", "amr02")), 61.0, cmd)
        assert job.phase == O.RUNNING and cmd.stops == 0
        job.step(node("RUNNING", "verify-1", last_seen=62.0, devices=("amr01", "amr02")), 62.0, cmd)
        assert job.phase == O.STOPPING and cmd.stops == 1
        job.step(node("STOPPING", "verify-1", last_seen=62.5), 62.5, cmd)
        job.step(node("IDLE", "", last_seen=63.0), 63.0, cmd)

        assert job.done and job.phase == "DONE"
        r = job.result()
        assert r["status"] == "done" and r["error"] is None and r["kpi"] is None
        assert r["verify"]["robots_online"] == 2 and r["verify"]["rtf_mean"] == 1.0 and r["verify"]["ram_mb_max"] == 350
        assert r["verify"]["elapsed_s"] == 61.0 and r["verify"]["reason"] == "window elapsed"
        assert r["estimate_id"] == 7 and r["source_run_id"] == "est_7_n2" and r["verify"]["started_at"].endswith("Z")

    def test_start_is_resent_until_reflected(self):
        job, cmd = make_job(start_resend_s=10)

        job.step(node("IDLE"), 0.0, cmd)
        job.step(node("IDLE"), 5.0, cmd)
        job.step(node("IDLE"), 10.0, cmd)
        job.step(node("STARTING", "verify-1"), 11.0, cmd)
        job.step(node("STARTING", "verify-1"), 30.0, cmd)

        assert len(cmd.starts) == 2

    def test_runner_error_before_running_fails_with_last_error(self):
        job, cmd = make_job()
        job.step(node("IDLE"), 0.0, cmd)
        job.step(node("STARTING", "verify-1"), 1.0, cmd)

        job.step(node("ERROR", "", last_error="process died during start: amr02"), 5.0, cmd)

        assert job.phase == "FAILED" and job.result()["error"] == "process died during start: amr02"

    def test_busy_runner_times_out(self):
        job, cmd = make_job(start_timeout_s=30)

        job.step(node("RUNNING", "other"), 0.0, cmd)
        job.step(node("RUNNING", "other"), 31.0, cmd)

        assert cmd.starts == [] and job.phase == "FAILED" and "busy with other" in job.result()["error"]

    def test_offline_runner_times_out(self):
        job, cmd = make_job(start_timeout_s=30)

        job.step(None, 0.0, cmd)
        job.step(node(online=False), 31.0, cmd)

        assert job.phase == "FAILED" and "offline" in job.result()["error"] and cmd.starts == []

    def test_runner_error_during_run_fails_without_stop(self):
        job, cmd = make_job()
        job.step(node("IDLE"), 0.0, cmd)
        job.step(node("RUNNING", "verify-1", last_seen=1.0), 1.0, cmd)

        job.step(node("ERROR", "", last_seen=5.0, last_error="host-orch offline > 15s"), 5.0, cmd)

        assert job.phase == "FAILED" and cmd.stops == 0 and job.result()["error"] == "host-orch offline > 15s"

    def test_ndeath_during_run_fails(self):
        job, cmd = make_job()
        job.step(node("IDLE"), 0.0, cmd)
        job.step(node("RUNNING", "verify-1", last_seen=1.0), 1.0, cmd)

        job.step(node(online=False), 2.0, cmd)

        assert job.phase == "FAILED" and job.result()["verify"]["reason"] == "runner NDEATH"

    def test_heartbeat_loss_stops_and_fails(self):
        job, cmd = make_job(heartbeat_s=5, heartbeat_misses=3)
        job.step(node("IDLE"), 0.0, cmd)
        job.step(node("RUNNING", "verify-1", last_seen=1.0), 1.0, cmd)

        job.step(node("RUNNING", "verify-1", last_seen=1.0), 15.0, cmd)
        assert job.phase == O.RUNNING
        job.step(node("RUNNING", "verify-1", last_seen=1.0), 17.0, cmd)
        assert job.phase == O.STOPPING and cmd.stops == 1
        job.step(node("IDLE", "", last_seen=18.0), 18.0, cmd)

        assert job.phase == "FAILED" and "no NDATA" in job.result()["error"]

    def test_stop_is_resent_once_then_fails(self):
        job, cmd = make_job(stop_timeout_s=10)
        job.step(node("IDLE"), 0.0, cmd)
        job.step(node("RUNNING", "verify-1", last_seen=1.0), 1.0, cmd)
        job.step(node("RUNNING", "verify-1", last_seen=61.0), 61.0, cmd)
        assert job.phase == O.STOPPING

        job.step(node("STOPPING", "verify-1", last_seen=72.0), 72.0, cmd)
        assert cmd.stops == 2
        job.step(node("STOPPING", "verify-1", last_seen=83.0), 83.0, cmd)

        assert job.phase == "FAILED" and "stop timeout" in job.result()["verify"]["reason"]

    def test_error_after_our_stop_is_reported_as_failed(self):
        job, cmd = make_job()
        job.step(node("IDLE"), 0.0, cmd)
        job.step(node("RUNNING", "verify-1", last_seen=1.0), 1.0, cmd)
        job.step(node("RUNNING", "verify-1", last_seen=61.0), 61.0, cmd)

        job.step(node("ERROR", "", last_seen=62.0, last_error="process died: amr01"), 62.0, cmd)

        assert job.phase == "FAILED" and job.result()["error"] == "process died: amr01"


BD = spb.MetricDef("bdSeq", spb.INT64, 0)
STATE = spb.MetricDef(O.STATE, spb.STRING, 2)
RUN_ID = spb.MetricDef(O.RUN_ID, spb.STRING, 3)
NB = "spBv1.0/santa/NBIRTH/sim-runner-gpu01"
ND = "spBv1.0/santa/NDATA/sim-runner-gpu01"


class TestCoordinator:
    def make(self):
        sent = []
        clock = {"t": 0.0}
        c = O.Coordinator(HostTracker(), lambda node, m: sent.append((node, m)), "sim-runner-gpu01",
                          O.JobConfig(start_resend_s=10), clock=lambda: clock["t"])
        return c, sent, clock

    def test_submit_sends_start_when_runner_is_idle_and_tracks_to_done(self):
        c, sent, clock = self.make()
        c.on_mqtt(NB, spb.encode_birth(0, [(BD, 1), (STATE, "IDLE"), (RUN_ID, "")]))

        job = c.submit(req_json(window_s=5))
        assert sent[-1][0] == "sim-runner-gpu01" and sent[-1][1][0][0] == O.CMD_START
        clock["t"] = 1.0
        c.on_mqtt(ND, spb.encode_data(1, [(STATE, "RUNNING"), (RUN_ID, "verify-1")]))
        assert job.phase == O.RUNNING
        clock["t"] = 7.0
        c.tick()
        assert job.phase == O.STOPPING and sent[-1][1][0][0] == O.CMD_STOP
        c.on_mqtt(ND, spb.encode_data(2, [(STATE, "IDLE"), (RUN_ID, "")]))

        assert job.done and job.result()["status"] == "done"

    def test_bad_request_becomes_failed_result_immediately(self):
        c, _, _ = self.make()

        job = c.submit(b'{"run_id": "x", "n_robots": "two"}')

        assert job.done and job.result() == {"run_id": "x", "status": "failed", "error": "bad request: n_robots must be an integer in 1..64",
                                             "verify": None, "kpi": None, "artifacts": None}
        assert c.submit(b"garbage").result()["run_id"] is None

    def test_second_submit_while_busy_raises(self):
        c, _, _ = self.make()
        c.submit(req_json())

        with pytest.raises(ValueError):
            c.submit(req_json(run_id="verify-2"))

    def test_seq_gap_triggers_rebirth_ncmd_rate_limited(self):
        c, sent, clock = self.make()
        c.on_mqtt(NB, spb.encode_birth(0, [(BD, 1), (STATE, "IDLE"), (RUN_ID, "")]))

        c.on_mqtt(ND, spb.encode_data(9, [(STATE, "IDLE")]))
        c.on_mqtt(ND, spb.encode_data(20, [(STATE, "IDLE")]))

        assert [m[0][0] for _, m in sent] == [O.REBIRTH]
        clock["t"] = 6.0
        c.tick()
        assert [m[0][0] for _, m in sent] == [O.REBIRTH, O.REBIRTH]

    def test_snapshot(self):
        c, _, _ = self.make()
        assert c.runner_snapshot() == {"online": False}
        c.on_mqtt(NB, spb.encode_birth(0, [(BD, 4), (STATE, "IDLE"), (RUN_ID, "")]))
        assert c.runner_snapshot()["state"] == "IDLE" and c.runner_snapshot()["bd_seq"] == 4


class TestReviewRegressions:
    def test_offline_while_stopping_is_failed_not_done(self):
        job, cmd = make_job()
        job.step(node("IDLE"), 0.0, cmd)
        job.step(node("RUNNING", "verify-1", last_seen=1.0), 1.0, cmd)
        job.step(node("RUNNING", "verify-1", last_seen=61.0), 61.0, cmd)
        assert job.phase == O.STOPPING and job.final == "DONE"

        job.step(node(online=False), 62.0, cmd)

        r = job.result()
        assert r["status"] == "failed" and r["verify"]["reason"] == "runner NDEATH while stopping" and r["error"]

    def test_error_with_run_id_still_set_while_stopping_fails_at_once(self):
        job, cmd = make_job(stop_timeout_s=60)
        job.step(node("IDLE"), 0.0, cmd)
        job.step(node("RUNNING", "verify-1", last_seen=1.0), 1.0, cmd)
        job.step(node("RUNNING", "verify-1", last_seen=61.0), 61.0, cmd)

        job.step(node("ERROR", "verify-1", last_seen=62.0, last_error="process died: amr01"), 62.0, cmd)

        assert job.phase == "FAILED" and job.result()["error"] == "process died: amr01" and cmd.stops == 1

    def test_ndeath_during_starting_fails_immediately(self):
        job, cmd = make_job(start_timeout_s=180)
        job.step(node("IDLE"), 0.0, cmd)
        job.step(node("STARTING", "verify-1"), 1.0, cmd)

        job.step(node(online=False), 2.0, cmd)

        assert job.phase == "FAILED" and job.result()["verify"]["reason"] == "runner NDEATH"

    def test_zero_clock_timestamps_are_still_rendered(self):
        job, cmd = make_job()
        job.step(node("IDLE"), 0.0, cmd)
        job.step(node("RUNNING", "verify-1", last_seen=0.0), 0.0, cmd)

        assert job.result()["verify"]["started_at"] == "1970-01-01T00:00:00.000Z"


class TestCoordinatorRedelivery:
    def make(self):
        sent = []
        c = O.Coordinator(HostTracker(), lambda node, m: sent.append(m[0][0]), "sim-runner-gpu01", clock=lambda: 0.0)
        c.on_mqtt(NB, spb.encode_birth(0, [(BD, 1), (STATE, "IDLE"), (RUN_ID, "")]))
        return c, sent

    def test_same_run_id_in_flight_returns_the_same_job_without_a_second_start(self):
        c, sent = self.make()
        job = c.submit(req_json())

        assert c.submit(req_json()) is job and sent == [O.CMD_START]

    def test_finished_run_id_returns_the_finished_job(self):
        c, sent = self.make()
        job = c.submit(req_json(window_s=1))
        c.on_mqtt(ND, spb.encode_data(1, [(STATE, "RUNNING"), (RUN_ID, "verify-1")]))
        job.step(c.tracker.node("sim-runner-gpu01"), 5.0, c.cmd)          # 창 종료 → Stop
        c.on_mqtt(ND, spb.encode_data(2, [(STATE, "IDLE"), (RUN_ID, "")]))
        assert job.done

        again = c.submit(req_json(window_s=1))

        assert again is job and sent == [O.CMD_START, O.CMD_STOP]

    def test_other_run_id_while_busy_raises_busy(self):
        c, _ = self.make()
        c.submit(req_json())

        with pytest.raises(O.Busy):
            c.submit(req_json(run_id="verify-2"))

    def test_recent_is_bounded(self):
        c, _ = self.make()
        for i in range(O.Coordinator.RECENT_MAX + 5):
            c.job = None
            c.submit(req_json(run_id=f"r{i}"))

        assert len(c.recent) == O.Coordinator.RECENT_MAX and "r0" not in c.recent


class TestScenario:
    SCENARIO = {"seed": 42, "map_version": "v6.0", "orders": {"outbound": [{"order_id": 1, "ordered_at_s": 5,
                                                                             "lines": [{"rack_id": "A3", "qty": 2}]}]}}

    def test_request_carries_scenario_and_sha_into_start(self):
        r = O.VerifyRequest.from_json(req_json(scenario=self.SCENARIO))

        assert r.scenario == self.SCENARIO and r.scenario_sha256 == O.scenario_sha256(self.SCENARIO)
        cmd = r.start_command()
        assert cmd["scenario"] == self.SCENARIO and cmd["scenario_sha256"] == r.scenario_sha256
        assert "scenario" not in O.VerifyRequest.from_json(req_json()).start_command()

    def test_scenario_must_be_object_and_small(self):
        with pytest.raises(ValueError):
            O.VerifyRequest.from_json(req_json(scenario="text"))
        with pytest.raises(ValueError):
            O.VerifyRequest.from_json(req_json(scenario={"blob": "x" * (O.MAX_SCENARIO_BYTES + 1)}))

    def test_result_reports_scenario_ack_only_when_runner_echoes_the_sha(self):
        req = O.VerifyRequest.from_json(req_json(scenario=self.SCENARIO, window_s=10))
        job, cmd = O.Job(req, "sim-runner-gpu01", O.JobConfig(), 0.0), Cmd()
        job.step(node("IDLE"), 0.0, cmd)
        n = node("RUNNING", "verify-1", last_seen=1.0)
        n.metrics[O.SCENARIO_SHA] = req.scenario_sha256
        n.metrics[O.ISAAC] = 1
        job.step(n, 1.0, cmd)
        job.step(node("RUNNING", "verify-1", last_seen=12.0), 12.0, cmd)
        job.step(node("IDLE", "", last_seen=13.0), 13.0, cmd)

        v = job.result()["verify"]
        assert v["scenario_ack"] is True and v["scenario_sha256"] == req.scenario_sha256 and v["isaac_instances"] == 1

    def test_scenario_ack_false_when_runner_did_not_echo(self):
        req = O.VerifyRequest.from_json(req_json(scenario=self.SCENARIO, window_s=10))
        job, cmd = O.Job(req, "sim-runner-gpu01", O.JobConfig(), 0.0), Cmd()
        job.step(node("IDLE"), 0.0, cmd)
        job.step(node("RUNNING", "verify-1", last_seen=1.0), 1.0, cmd)
        job.step(node("RUNNING", "verify-1", last_seen=12.0), 12.0, cmd)
        job.step(node("IDLE", "", last_seen=13.0), 13.0, cmd)

        assert job.result()["verify"]["scenario_ack"] is False

    def test_no_scenario_means_no_ack_claim(self):
        job, cmd = make_job()
        job.step(node("IDLE"), 0.0, cmd)

        assert job.result()["verify"]["scenario_ack"] is False and job.result()["verify"]["scenario_sha256"] is None


# ---- fms-core 연동 (결정 11 · SIM_VERIFY_CONTRACT §3 kpi) ---------------------------------
def fms_node(state="IDLE", run_id="", online=True, last_seen=0.0, last_error="", tick=None):
    n = Node("fms-core", online=online, bd_seq=1, seq=0, last_seen=last_seen)
    n.metrics = {O.FMS_STATE: state, O.FMS_RUN_ID: run_id, O.FMS_LAST_ERROR: last_error}
    if tick is not None:
        n.metrics[O.FMS_TICK] = tick
    return n


def make_fms_job(now=0.0, **cfg):
    return O.Job(O.VerifyRequest.from_json(req_json()), "sim-runner-gpu01", O.JobConfig(**cfg), now, "fms-core"), Cmd(), Cmd()


def kpi_event(run_id="verify-1", kind="kpi_summary", **over):
    body = {"eventId": f"{run_id}-9", "runId": run_id, "at": "2026-09-09T10:00:00.000Z", "type": kind, "tick": 120,
            "status": "done", "error": None, "ticks": 120, "planner": "kernel",
            "kpi": {"orders_total": 4, "orders_completed": 2, "throughput_tasks_per_h": 60.0}, "counters": {"done_tasks": 2}}
    body.update(over)
    return json.dumps(body).encode()


class TestFmsLink:
    def test_window_starts_only_when_both_nodes_run_and_kpi_is_relayed(self):
        job, cmd, fcmd = make_fms_job()

        job.step(node("IDLE"), 0.0, cmd, fms_node("IDLE"), fcmd)
        assert cmd.starts[0]["run_id"] == "verify-1" and fcmd.starts == []          # fms Start 는 러너 RUNNING 뒤
        job.step(node("RUNNING", "verify-1", last_seen=2.0), 2.0, cmd, fms_node("IDLE", last_seen=2.0), fcmd)
        assert job.phase == O.STARTING and fcmd.starts[0] == cmd.starts[0]
        job.step(node("RUNNING", "verify-1", last_seen=3.0), 3.0, cmd, fms_node("STARTING", "verify-1", last_seen=3.0), fcmd)
        assert job.phase == O.STARTING and len(fcmd.starts) == 1
        job.step(node("RUNNING", "verify-1", last_seen=20.0), 20.0, cmd, fms_node("RUNNING", "verify-1", last_seen=20.0), fcmd)
        assert job.phase == O.RUNNING and job.started_at == 20.0
        job.step(node("RUNNING", "verify-1", last_seen=81.0), 81.0, cmd, fms_node("RUNNING", "verify-1", last_seen=81.0, tick=55), fcmd)
        assert job.phase == O.STOPPING and cmd.stops == 1 and fcmd.stops == 1
        assert job.on_biz_event(json.loads(kpi_event()))
        job.step(node("IDLE", "", last_seen=82.0), 82.0, cmd, fms_node("RUNNING", "verify-1", last_seen=82.0), fcmd)
        assert job.phase == O.STOPPING                                                  # fms-core 가 아직 놓지 않음
        job.step(node("IDLE", "", last_seen=83.0), 83.0, cmd, fms_node("IDLE", "", last_seen=83.0), fcmd)

        assert job.done and job.phase == "DONE"
        r = job.result()
        assert r["kpi"] == {"orders_total": 4, "orders_completed": 2, "throughput_tasks_per_h": 60.0}
        assert r["verify"]["fms"] == {"node": "fms-core", "ticks": 120, "status": "done", "error": None, "planner": "kernel",
                                      "counters": {"done_tasks": 2}, "warnings": None}
        assert r["verify"]["elapsed_s"] == 63.0                                       # 창 61 s + fms-core 정리 대기 2 s

    def test_fms_start_is_resent_and_ignores_other_run_ids(self):
        job, cmd, fcmd = make_fms_job(start_resend_s=10)
        job.step(node("RUNNING", "verify-1", last_seen=0.0), 0.0, cmd, fms_node("IDLE"), fcmd)
        job.step(node("RUNNING", "verify-1", last_seen=5.0), 5.0, cmd, fms_node("IDLE"), fcmd)
        job.step(node("RUNNING", "verify-1", last_seen=10.0), 10.0, cmd, fms_node("IDLE"), fcmd)
        assert len(fcmd.starts) == 2
        assert not job.on_biz_event(json.loads(kpi_event(run_id="other")))
        assert not job.on_biz_event(json.loads(kpi_event(kind="task_done")))
        assert job.kpi is None

    def test_fms_error_before_running_fails(self):
        job, cmd, fcmd = make_fms_job()
        job.step(node("RUNNING", "verify-1", last_seen=0.0), 0.0, cmd, fms_node("IDLE"), fcmd)
        job.step(node("RUNNING", "verify-1", last_seen=1.0), 1.0, cmd,
                 fms_node("ERROR", "", last_error="planner build failed: robot 1 home blocked"), fcmd)
        assert job.phase == O.STARTING                                                  # 아직 우리 run_id 를 본 적 없음
        job.step(node("RUNNING", "verify-1", last_seen=2.0), 2.0, cmd, fms_node("STARTING", "verify-1"), fcmd)
        job.step(node("RUNNING", "verify-1", last_seen=3.0), 3.0, cmd,
                 fms_node("ERROR", "", last_error="amr02 primitiveError: timeout"), fcmd)

        assert job.phase == "FAILED" and job.result()["error"] == "amr02 primitiveError: timeout"
        assert job.result()["verify"]["reason"] == "fms-core ended the run"

    def test_fms_bad_start_fails_at_once(self):
        job, cmd, fcmd = make_fms_job()
        job.step(node("RUNNING", "verify-1", last_seen=0.0), 0.0, cmd, fms_node("IDLE", last_error="bad Start: scenario too large"), fcmd)
        assert job.phase == "FAILED" and job.result()["verify"]["reason"] == "fms-core rejected Start"

    def test_fms_offline_at_start_times_out_with_fms_reason(self):
        job, cmd, fcmd = make_fms_job(start_timeout_s=30)
        job.step(node("RUNNING", "verify-1", last_seen=0.0), 0.0, cmd, None, fcmd)
        job.step(node("RUNNING", "verify-1", last_seen=31.0), 31.0, cmd, None, fcmd)
        assert job.phase == "FAILED" and job.result()["error"] == "fms-core offline" and fcmd.starts == []

    @pytest.mark.parametrize("what,reason", [("offline", "fms-core NDEATH"), ("error", "fms-core ended the run"),
                                             ("idle", "fms-core ended the run"), ("silent", "fms-core heartbeat lost")])
    def test_fms_faults_during_run_stop_and_fail(self, what, reason):
        job, cmd, fcmd = make_fms_job()
        job.step(node("RUNNING", "verify-1", last_seen=0.0), 0.0, cmd, fms_node("RUNNING", "verify-1", last_seen=0.0), fcmd)
        assert job.phase == O.RUNNING
        fn = {"offline": fms_node(online=False), "error": fms_node("ERROR", "", last_seen=5.0, last_error="amr01 silent for 31s"),
              "idle": fms_node("IDLE", "", last_seen=5.0), "silent": fms_node("RUNNING", "verify-1", last_seen=0.0)}[what]
        job.step(node("RUNNING", "verify-1", last_seen=20.0), 20.0, cmd, fn, fcmd)

        assert job.phase == O.STOPPING and job.final == "FAILED" and job.reason == reason and cmd.stops == fcmd.stops == 1
        if what == "error":
            assert job.error == "amr01 silent for 31s"

    def test_fms_stop_timeout_fails(self):
        job, cmd, fcmd = make_fms_job(stop_timeout_s=10)
        job.step(node("RUNNING", "verify-1", last_seen=0.0), 0.0, cmd, fms_node("RUNNING", "verify-1", last_seen=0.0), fcmd)
        job.step(node("RUNNING", "verify-1", last_seen=61.0), 61.0, cmd, fms_node("RUNNING", "verify-1", last_seen=61.0), fcmd)
        assert job.phase == O.STOPPING
        job.step(node("IDLE", "", last_seen=62.0), 62.0, cmd, fms_node("RUNNING", "verify-1", last_seen=62.0), fcmd)
        assert job.phase == O.STOPPING
        job.step(node("IDLE", "", last_seen=72.0), 72.0, cmd, fms_node("RUNNING", "verify-1", last_seen=72.0), fcmd)

        assert job.phase == "FAILED" and job.result()["verify"]["reason"] == "fms stop timeout"

    def test_without_fms_the_job_is_unchanged(self):
        job, cmd = make_job()
        job.step(node("RUNNING", "verify-1", last_seen=0.0), 0.0, cmd)
        assert job.phase == O.RUNNING and job.result()["verify"]["fms"] is None and job.result()["kpi"] is None
        assert not job.on_biz_event(json.loads(kpi_event()))


class TestCoordinatorFms:
    FNB, FND = "spBv1.0/santa/NBIRTH/fms-core", "spBv1.0/santa/NDATA/fms-core"
    FST, FRID = spb.MetricDef(O.FMS_STATE, spb.STRING, 20), spb.MetricDef(O.FMS_RUN_ID, spb.STRING, 21)

    def make(self):
        sent, clock = [], {"t": 0.0}
        c = O.Coordinator(HostTracker(), lambda n, m: sent.append((n, m)), "sim-runner-gpu01", O.JobConfig(start_resend_s=10),
                          clock=lambda: clock["t"], fms_node_id="fms-core")
        c.on_mqtt(NB, spb.encode_birth(0, [(BD, 1), (STATE, "IDLE"), (RUN_ID, "")]))
        c.on_mqtt(self.FNB, spb.encode_birth(0, [(BD, 1), (self.FST, "IDLE"), (self.FRID, "")]))
        return c, sent, clock

    def test_starts_both_nodes_relays_kpi_and_stops_both(self):
        c, sent, clock = self.make()
        job = c.submit(req_json(window_s=5))
        assert [n for n, _ in sent] == ["sim-runner-gpu01"]
        c.on_mqtt(ND, spb.encode_data(1, [(STATE, "RUNNING"), (RUN_ID, "verify-1")]))
        assert [n for n, _ in sent] == ["sim-runner-gpu01", "fms-core"] and sent[-1][1][0][0] == O.CMD_START
        clock["t"] = 3.0
        c.on_mqtt(self.FND, spb.encode_data(1, [(self.FST, "RUNNING"), (self.FRID, "verify-1")]))
        assert job.phase == O.RUNNING
        clock["t"] = 9.0
        c.tick()
        assert job.phase == O.STOPPING and [n for n, m in sent if m[0][0] == O.CMD_STOP] == ["sim-runner-gpu01", "fms-core"]
        c.on_mqtt("biz/v1/event", kpi_event())
        c.on_mqtt("biz/v1/event", b"not json")
        c.on_mqtt(self.FND, spb.encode_data(2, [(self.FST, "IDLE"), (self.FRID, "")]))
        c.on_mqtt(ND, spb.encode_data(2, [(STATE, "IDLE"), (RUN_ID, "")]))

        assert job.done and job.result()["status"] == "done" and job.result()["kpi"]["orders_total"] == 4
        assert c.fms_snapshot()["state"] == "IDLE"

    def test_late_kpi_lands_on_the_finished_job(self):
        c, sent, clock = self.make()
        job = c.submit(req_json(window_s=1))
        c.on_mqtt(ND, spb.encode_data(1, [(STATE, "RUNNING"), (RUN_ID, "verify-1")]))
        c.on_mqtt(self.FND, spb.encode_data(1, [(self.FST, "RUNNING"), (self.FRID, "verify-1")]))
        clock["t"] = 2.0
        c.tick()
        c.on_mqtt(self.FND, spb.encode_data(2, [(self.FST, "IDLE"), (self.FRID, "")]))
        c.on_mqtt(ND, spb.encode_data(2, [(STATE, "IDLE"), (RUN_ID, "")]))
        assert job.done and job.result()["kpi"] is None
        c.on_mqtt("biz/v1/event", kpi_event())
        assert job.result()["kpi"]["orders_total"] == 4

    def test_fms_seq_gap_triggers_rebirth_on_fms_node(self):
        c, sent, _ = self.make()
        c.on_mqtt(self.FND, spb.encode_data(7, [(self.FST, "IDLE")]))
        assert sent[-1] == ("fms-core", [(O.REBIRTH, spb.BOOLEAN, True)])
