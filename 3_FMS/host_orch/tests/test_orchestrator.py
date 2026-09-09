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
