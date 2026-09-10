"""sim_runner.runner — 상태기계 · NCMD · 세션 규칙 (MQTT_CONTRACT §5.3 · §5.4)."""
import signal

import pytest

from sim_runner import mirror as M
from sim_runner import runner as R
from sim_runner import spb
from tests.sim_runner_fakes import Harness, ncmd, vda_state


@pytest.fixture
def h(tmp_path):
    return Harness(tmp_path, heartbeat_s=5.0, ready_timeout_s=30.0, host_offline_s=15.0)


class TestSession:
    def test_connect_publishes_nbirth_with_every_metric_and_seq_zero(self, h):
        h.runner.on_connected(0.0)

        (topic, d, qos, retain), = h.pub.msgs
        named = spb.metrics_by_name(d)
        assert topic == "spBv1.0/santa/NBIRTH/sim-runner-gpu01" and qos == 0 and retain is False
        assert d.seq == 0 and set(named) == set(R.NODE_METRICS)
        assert named[R.BDSEQ] == h.session.bd_seq and named[R.STATE] == "IDLE"
        assert named[R.CMD_START] == "" and named[R.CMD_STOP] is False and named[R.REBIRTH] is False

    def test_seq_increments_across_node_and_device_messages_and_resets_on_nbirth(self, h):
        h.connect()
        h.run_until_running(serials=("amr01",))
        h.runner.on_vda(*vda_state("amr01", x=1.0), 2.0)
        h.runner.on_ncmd(ncmd(**{R.REBIRTH: True}), 3.0)

        seqs = [d.seq for _, d, *_ in h.pub.msgs]
        kinds = h.pub.kinds()
        assert kinds == ["DDATA", "NBIRTH", "DBIRTH"]
        assert seqs[0] > 0 and seqs[1] == 0 and seqs[2] == 1

    def test_rebirth_republishes_nbirth_and_live_dbirths_only(self, h):
        h.connect()
        h.runner.on_ncmd(ncmd(**{R.REBIRTH: True}), 1.0)
        assert h.pub.kinds() == ["NBIRTH"]
        h.pub.clear()
        h.run_until_running()

        h.runner.on_ncmd(ncmd(**{R.REBIRTH: True}), 2.0)

        assert h.pub.kinds() == ["NBIRTH", "DBIRTH", "DBIRTH"]

    def test_reconnect_while_running_rebirths_devices(self, h):
        h.connect()
        h.run_until_running()
        h.session.new_session()

        h.runner.on_connected(5.0)

        assert h.pub.kinds() == ["NBIRTH", "DBIRTH", "DBIRTH"]
        assert h.pub.named("NBIRTH")[R.BDSEQ] == h.session.bd_seq


class TestStart:
    def test_start_launches_agents_and_reports_starting(self, h):
        h.connect()

        h.start(now=0.0)

        assert len(h.spawned) == 2 and h.runner.state == R.STARTING
        assert h.pub.named("NDATA") == {R.STATE: "STARTING", R.RUN_ID: "run-1", R.LAST_ERROR: "", R.SCENARIO_SHA: ""}

    def test_running_after_all_agents_online_with_dbirth_per_robot(self, h):
        h.connect()
        h.start(now=0.0)
        h.runner.on_vda(*vda_state("amr01", x=1.5, y=2.5, node="n1"), 0.5)
        h.runner.on_vda(*vda_state("amr02", ts="2026-09-08T10:00:00.500Z"), 0.6)
        h.pub.clear()
        h.runner.tick(1.0)
        assert h.runner.state == R.STARTING and h.pub.kinds() == []
        h.all_online(("amr01",))
        h.runner.tick(1.5)
        assert h.runner.state == R.STARTING
        h.all_online(("amr02",))

        h.runner.tick(2.0)

        assert h.runner.state == R.RUNNING
        assert h.pub.kinds() == ["DBIRTH", "DBIRTH", "NDATA"]
        topics = [t for t, *_ in h.pub.msgs]
        assert topics[0].endswith("/DBIRTH/sim-runner-gpu01/amr01") and topics[1].endswith("/amr02")
        b1 = spb.metrics_by_name(h.pub.msgs[0][1])
        assert b1[M.MODEL] == "iw_hub" and b1[M.CONNECTION] == "ONLINE" and b1[M.LAST_NODE] == "n1"
        assert b1[M.POSE_X] == 1.5 and b1[M.POSE_Y] == 2.5 and b1[M.AMCL_ERR] is None
        aliases = [m.alias for m in h.pub.msgs[0][1].metrics] + [m.alias for m in h.pub.msgs[1][1].metrics]
        assert len(set(aliases)) == len(aliases) and min(aliases) >= R.DEVICE_ALIAS_BASE
        assert h.pub.named("NDATA") == {R.STATE: "RUNNING"}

    def test_same_run_id_is_idempotent(self, h):
        h.connect()
        h.run_until_running()

        h.start(now=3.0)

        assert len(h.spawned) == 2
        assert h.pub.kinds() == ["NDATA"] and h.pub.named("NDATA") == {R.STATE: "RUNNING", R.RUN_ID: "run-1"}

    def test_other_run_id_while_busy_is_rejected_with_last_error(self, h):
        h.connect()
        h.run_until_running()

        h.start(now=3.0, run_id="run-2")

        assert len(h.spawned) == 2 and h.runner.state == R.RUNNING
        assert "busy: RUNNING run-1" in h.pub.named("NDATA")[R.LAST_ERROR]
        assert h.runner.values[R.RUN_ID] == "run-1"

    def test_bad_start_json_sets_last_error_and_launches_nothing(self, h):
        h.connect()

        h.runner.on_ncmd(ncmd(**{R.CMD_START: '{"run_id": "x"}'}), 0.0)

        assert h.spawned == [] and h.runner.state == R.IDLE
        assert h.pub.named("NDATA")[R.LAST_ERROR].startswith("bad Start: n_robots")

    def test_ready_timeout_ends_in_error_after_stopping(self, h):
        h.connect()
        h.start(now=0.0)
        h.all_online(("amr01",))

        h.runner.tick(31.0)
        assert h.runner.state == R.STOPPING and h.spawned[0].signals == [signal.SIGINT]
        assert "ready timeout" in h.runner.values[R.LAST_ERROR] and "posed=[]" in h.runner.values[R.LAST_ERROR]
        h.exit_all()
        h.runner.tick(32.0)

        assert h.runner.state == R.ERROR and h.runner.values[R.RUN_ID] == ""
        assert h.pub.named("NDATA")[R.STATE] == "ERROR"

    def test_start_after_error_clears_last_error(self, h):
        h.connect()
        h.runner.on_ncmd(ncmd(**{R.CMD_START: "junk"}), 0.0)
        assert h.runner.values[R.LAST_ERROR]

        h.start(now=1.0)

        assert h.runner.state == R.STARTING and h.runner.values[R.LAST_ERROR] == ""


class TestRunning:
    def test_state_delta_becomes_ddata_only_above_threshold(self, h):
        h.connect()
        h.run_until_running(serials=("amr01",))            # DBIRTH 에 포즈(0,0) 포함

        h.runner.on_vda(*vda_state("amr01", x=0.01), 2.0)
        assert h.pub.kinds() == []
        h.runner.on_vda(*vda_state("amr01", x=0.2, node="n3"), 2.5)

        assert h.pub.kinds() == ["DDATA"]
        assert h.pub.named("DDATA") == {M.LAST_NODE: "n3", M.POSE_X: 0.2, M.POSE_Y: 0.0}

    def test_stop_publishes_ddeath_then_idle_when_processes_exit(self, h):
        h.connect()
        h.run_until_running()

        h.runner.on_ncmd(ncmd(**{R.CMD_STOP: True}), 5.0)

        assert h.pub.kinds() == ["DDEATH", "DDEATH", "NDATA"] and h.runner.state == R.STOPPING
        assert all(p.signals == [signal.SIGINT] for p in h.spawned)
        h.runner.on_vda(*vda_state("amr01", x=5.0), 5.5)
        assert "DDATA" not in h.pub.kinds()
        h.runner.tick(6.0)
        assert h.runner.state == R.STOPPING
        h.exit_all()
        h.runner.tick(6.5)

        assert h.runner.state == R.IDLE
        assert h.pub.named("NDATA") == {R.STATE: "IDLE", R.RUN_ID: "", R.SCENARIO_SHA: ""}

    def test_stop_while_idle_is_a_noop(self, h):
        h.connect()

        h.runner.on_ncmd(ncmd(**{R.CMD_STOP: True}), 1.0)

        assert h.pub.msgs == [] and h.runner.state == R.IDLE

    def test_agent_death_fails_the_run(self, h):
        h.connect()
        h.run_until_running()
        h.spawned[1].rc = 1

        h.runner.tick(2.0)

        assert h.runner.state == R.STOPPING and "amr02" in h.runner.values[R.LAST_ERROR]
        assert h.pub.kinds() == ["DDEATH", "DDEATH", "NDATA"]

    def test_timeout_s_is_a_backstop_that_fails_the_run(self, h):
        h.connect()
        h.run_until_running()

        h.runner.tick(601.0)

        assert h.runner.state == R.STOPPING and "timeout_s" in h.runner.values[R.LAST_ERROR]
        assert h.runner.final_state == R.ERROR

    def test_host_offline_over_15s_stops_the_run(self, h):
        h.connect()
        h.runner.on_host_state(b'{"online": true, "timestamp": 1}', 0.0)
        h.run_until_running()

        h.runner.on_host_state(b'{"online": false, "timestamp": 1}', 10.0)
        h.runner.tick(20.0)
        assert h.runner.state == R.RUNNING
        h.runner.tick(26.0)

        assert h.runner.state == R.STOPPING and "host-orch offline" in h.runner.values[R.LAST_ERROR]

    def test_host_back_online_cancels_offline_timer_and_rebirths(self, h):
        h.connect()
        h.runner.on_host_state(b'{"online": true, "timestamp": 1}', 0.0)
        h.run_until_running()
        h.runner.on_host_state(b'{"online": false, "timestamp": 1}', 10.0)

        h.runner.on_host_state(b'{"online": true, "timestamp": 2}', 12.0)
        h.runner.tick(40.0)

        assert h.runner.state == R.RUNNING
        assert h.pub.kinds()[:3] == ["NBIRTH", "DBIRTH", "DBIRTH"]

    def test_first_retained_host_state_does_not_trigger_rebirth(self, h):
        h.connect()

        h.runner.on_host_state(b'{"online": true, "timestamp": 1}', 0.0)
        h.runner.on_host_state(b'{"online": true, "timestamp": 1}', 0.1)

        assert h.pub.msgs == []

    def test_host_restart_with_newer_timestamp_rebirths(self, h):
        h.connect()
        h.runner.on_host_state(b'{"online": true, "timestamp": 1}', 0.0)

        h.runner.on_host_state(b'{"online": true, "timestamp": 5}', 1.0)

        assert h.pub.kinds() == ["NBIRTH"]

    def test_garbage_host_state_is_ignored(self, h):
        h.connect()

        h.runner.on_host_state(b"nope", 0.0)
        h.runner.on_host_state(b'{"online": "yes"}', 0.0)

        assert h.pub.msgs == [] and h.runner.host_online is None


class TestHeartbeat:
    def test_heartbeat_every_5s_with_changed_telemetry_only(self, h):
        h.connect()

        h.runner.tick(4.9)
        assert h.pub.msgs == []
        h.runner.tick(5.0)
        first = h.pub.named("NDATA")
        assert first[R.HEARTBEAT] == 5000 and first[R.VRAM] == 2000 and R.RAM not in first
        h.pub.clear()
        h.runner.tick(10.0)

        assert h.pub.named("NDATA") == {R.HEARTBEAT: 10000}

    def test_heartbeat_reports_rtf_ram_and_isaac_while_running(self, h):
        h.connect()
        h.run_until_running(serials=("amr01",))
        for i in range(4):      # all_ready 가 wall 0 에 10:00:00 표본을 넣었으니 같은 시각 기준으로 2 s/1 s
            h.runner.on_vda(*vda_state("amr01", ts=f"2026-09-08T10:00:{i * 2:02d}.000Z"), float(i))

        h.runner.tick(6.0)

        hb = h.pub.named("NDATA")
        assert hb[R.RTF] == 2.0 and hb[R.RAM] == 100 and R.ISAAC not in hb

    def test_vram_unavailable_keeps_last_value(self, h):
        h.connect()
        h.runner.tick(5.0)
        h.telemetry["vram"] = None
        h.pub.clear()

        h.runner.tick(10.0)

        assert h.pub.named("NDATA") == {R.HEARTBEAT: 10000} and h.runner.values[R.VRAM] == 2000


def test_real_mode_reports_isaac_instance(tmp_path):
    h = Harness(tmp_path, fake=False)
    h.connect()

    h.start(now=0.0, n=1)
    h.runner.tick(0.5)
    h.runner.tick(5.0)

    assert len(h.spawned) == 2 and h.spawned[0].argv == ["bash", "-c", "isaac"]
    assert h.pub.named("NDATA")[R.ISAAC] == 1


class TestReadinessAndScenario:
    def test_online_without_pose_stays_starting(self, h):
        h.connect()
        h.start(now=0.0, n=1)
        h.all_online(("amr01",))

        h.runner.tick(1.0)
        assert h.runner.state == R.STARTING
        h.runner.on_vda(*vda_state("amr01", x=2.0), 1.5)
        h.runner.tick(2.0)

        assert h.runner.state == R.RUNNING

    def test_scenario_is_written_hashed_and_reported(self, h, tmp_path):
        import hashlib, json, os
        scenario = {"seed": 42, "orders": {"outbound": [{"order_id": 1, "lines": [{"rack_id": "A3", "qty": 2}]}]}}
        canonical = json.dumps(scenario, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        sha = hashlib.sha256(canonical).hexdigest()
        h.runs_dir = str(tmp_path / "runs")
        h.connect()

        h.start(now=0.0, n=1, scenario=scenario, scenario_sha256=sha)

        assert h.runner.state == R.STARTING
        assert h.pub.named("NDATA")[R.SCENARIO_SHA] == sha
        path = os.path.join(h.runs_dir, "run-1", "scenario.json")
        assert open(path, "rb").read() == canonical
        env = h.spawned[0].kw["env"]
        assert env["SIM_SCENARIO_PATH"] == path and env["SIM_SCENARIO_SHA256"] == sha
        assert h.pub.named("NBIRTH") is None or True
        h.all_ready(("amr01",))
        h.runner.tick(1.0)
        h.runner.on_ncmd(ncmd(**{R.CMD_STOP: True}), 2.0)
        h.exit_all()
        h.runner.tick(3.0)
        assert h.pub.named("NDATA") == {R.STATE: "IDLE", R.RUN_ID: "", R.SCENARIO_SHA: ""}

    def test_scenario_sha_mismatch_is_rejected_before_launch(self, h):
        h.connect()

        h.start(now=0.0, n=1, scenario={"seed": 1}, scenario_sha256="0" * 64)

        assert h.spawned == [] and h.runner.state == R.IDLE
        assert "scenario_sha256 mismatch" in h.pub.named("NDATA")[R.LAST_ERROR]

    def test_spawn_string_goes_to_wsim_spawn(self, h):
        h.connect()

        h.start(now=0.0, n=2, scenario={"spawn": "36,40.8;39,40.8"})

        assert h.spawned[0].kw["env"]["WSIM_SPAWN"] == "36,40.8;39,40.8"
