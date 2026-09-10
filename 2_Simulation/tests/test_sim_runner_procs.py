"""sim_runner.procs — Start JSON 검증 · 명령 조립 · 종료 사다리."""
import json
import signal
import subprocess

import pytest

from sim_runner import procs as P


def start_json(**over):
    d = {"run_id": "run-1", "scenario_pkg": "pkg-a", "n_robots": 2,
         "models": [{"serial": "amr01", "manufacturer": "idealworks", "model": "iw_hub"},
                    {"serial": "amr02", "model": "iw_hub"}],
         "ros_domain_id": 7, "timeout_s": 600}
    d.update(over)
    return json.dumps(d)


class TestRunSpec:
    def test_parses_full_start_payload(self):
        s = P.RunSpec.from_json(start_json())

        assert s.run_id == "run-1" and s.n_robots == 2 and s.ros_domain_id == 7 and s.timeout_s == 600.0
        assert s.robots[1] == P.RobotSpec("amr02", "idealworks", "iw_hub")

    def test_defaults_serials_when_models_missing(self):
        s = P.RunSpec.from_json(json.dumps({"run_id": "r", "n_robots": 3}))

        assert [r.serial for r in s.robots] == ["amr01", "amr02", "amr03"]
        assert s.ros_domain_id == 0 and s.timeout_s == P.DEFAULT_TIMEOUT_S

    @pytest.mark.parametrize("bad", ["not json", "[1]", json.dumps({"n_robots": 1}),
                                     start_json(run_id="  "), start_json(n_robots=0), start_json(n_robots=True),
                                     start_json(n_robots=2, models=[{"serial": "a"}]),
                                     start_json(models=[{"serial": "a"}, {"serial": "a"}]),
                                     start_json(models=[{"serial": "a"}, {}]),
                                     start_json(ros_domain_id=999), start_json(timeout_s=0)])
    def test_rejects_invalid_payloads(self, bad):
        with pytest.raises(ValueError):
            P.RunSpec.from_json(bad)


ENV = P.LaunchEnv("100.100.149.68", 1883, "pw", ros_setup=("/opt/ros/humble/setup.bash", "/ws/install/setup.bash"),
                  isaac_cmd="~/isaacsim/python.sh warehouse_sim.py")


def test_agent_cmd_fake_sources_ros_and_spaces_robots():
    argv = P.agent_cmd(P.RobotSpec("amr02"), 1, ENV, fake=True)

    assert argv[:2] == ["bash", "-c"]
    script = argv[2]
    assert script.startswith("source /opt/ros/humble/setup.bash && source /ws/install/setup.bash && exec ros2 launch")
    assert "serial:=amr02" in script and "mqtt_username:=amr02" in script and "mqtt_password:=pw" in script
    assert "fake_robot:=true" in script and "fake_x:=3" in script and "use_sim_time" not in script


def test_agent_cmd_real_uses_sim_time_and_odom():
    script = P.agent_cmd(P.RobotSpec("amr01"), 0, ENV, fake=False)[2]

    assert "pose_source:=odom" in script and "use_sim_time:=true" in script and "fake_robot" not in script


def test_run_env_sets_domain_and_wsim_n():
    spec = P.RunSpec.from_json(start_json())

    env = P.run_env(spec, base={"PATH": "/bin"})

    assert env == {"PATH": "/bin", "ROS_DOMAIN_ID": "7", "WSIM_N": "2", "SIM_RUN_ID": "run-1"}


class FakePopen:
    def __init__(self, argv, **kw):
        self.argv, self.kw, self.pid, self.rc, self.signals = argv, kw, 4242, None, []

    def poll(self):
        return self.rc

    def send_signal(self, sig):
        self.signals.append(("pid", sig))


def make_manager(fake=True, env=ENV):
    spawned = []
    sent = []

    def spawn(argv, **kw):
        p = FakePopen(argv, **kw)
        spawned.append(p)
        return p

    pm = P.ProcessManager(env, fake=fake, spawn=spawn, send=lambda proc, sig: sent.append((proc.pid, sig)))
    return pm, spawned, sent


class TestProcessManager:
    def test_fake_start_spawns_one_agent_per_robot_in_new_session(self):
        pm, spawned, _ = make_manager()

        pm.start(P.RunSpec.from_json(start_json()), now=0.0)

        assert len(spawned) == 2 and pm.agents_started() and pm.isaac_count() == 0
        assert spawned[0].kw["start_new_session"] is True and spawned[0].kw["env"]["ROS_DOMAIN_ID"] == "7"
        assert spawned[0].kw["stdin"] is subprocess.DEVNULL

    def test_real_start_launches_isaac_then_agents_after_warmup(self):
        pm, spawned, _ = make_manager(fake=False, env=P.LaunchEnv("h", 1883, "pw", isaac_cmd="isaac", isaac_warmup_s=10))

        pm.start(P.RunSpec.from_json(start_json()), now=0.0)
        pm.poll_start(now=5.0)
        assert len(spawned) == 1 and pm.isaac_count() == 1 and not pm.agents_started()
        pm.poll_start(now=10.0)
        pm.poll_start(now=11.0)

        assert len(spawned) == 3 and spawned[0].argv == ["bash", "-c", "isaac"]

    def test_real_start_without_isaac_cmd_fails(self):
        pm, _, _ = make_manager(fake=False, env=P.LaunchEnv("h", 1883, "pw"))

        with pytest.raises(RuntimeError):
            pm.start(P.RunSpec.from_json(start_json()), now=0.0)

    def test_dead_lists_unexpected_exits_only(self):
        pm, spawned, _ = make_manager()
        pm.start(P.RunSpec.from_json(start_json()), now=0.0)
        spawned[1].rc = 1

        assert pm.dead() == ["amr02"]
        pm.request_stop(now=1.0)
        assert pm.dead() == []

    def test_stop_ladder_sigint_then_sigterm_group_then_sigkill(self):
        pm, spawned, sent = make_manager()
        pm.start(P.RunSpec.from_json(start_json(n_robots=1, models=None)), now=0.0)
        a = spawned[0]

        pm.request_stop(now=10.0)
        assert pm.poll_stop(now=10.0) is False and a.signals == [("pid", signal.SIGINT)]
        assert pm.poll_stop(now=12.0) is False and sent == []
        assert pm.poll_stop(now=15.0) is False and sent == [(4242, signal.SIGTERM)]
        assert pm.poll_stop(now=17.0) is False
        assert pm.poll_stop(now=18.0) is False and sent[-1] == (4242, signal.SIGKILL)
        a.rc = -9
        assert pm.poll_stop(now=18.5) is True and pm.all_exited()

    def test_stop_waits_for_agents_before_isaac(self):
        pm, spawned, _ = make_manager(fake=False, env=P.LaunchEnv("h", 1883, "pw", isaac_cmd="isaac", isaac_warmup_s=0))
        pm.start(P.RunSpec.from_json(start_json(n_robots=1, models=None)), now=0.0)
        pm.poll_start(now=0.0)
        isaac, agent = spawned

        pm.request_stop(now=1.0)
        pm.poll_stop(now=1.0)
        assert agent.signals == [("pid", signal.SIGINT)] and isaac.signals == []
        agent.rc = 0
        assert pm.poll_stop(now=1.5) is False and isaac.signals == [("pid", signal.SIGINT)]
        isaac.rc = 0
        assert pm.poll_stop(now=2.0) is True


@pytest.mark.parametrize("bad_id", ["../etc", "a/b", ".hidden", "x" * 65, "run id", ""])
def test_run_id_and_serial_charset_blocks_path_tricks(bad_id):
    with pytest.raises(ValueError):
        P.RunSpec.from_json(start_json(run_id=bad_id))
    with pytest.raises(ValueError):
        P.RunSpec.from_json(start_json(models=[{"serial": bad_id}, {"serial": "amr02"}]))


def test_run_id_allows_dots_dashes_and_underscores():
    assert P.RunSpec.from_json(start_json(run_id="run_2026-09-08.v1")).run_id == "run_2026-09-08.v1"


class FakeProcInfo:
    def __init__(self, pid, env=None, denied=False):
        self.pid, self._env, self._denied = pid, env or {}, denied

    def environ(self):
        import psutil
        if self._denied:
            raise psutil.AccessDenied(self.pid)
        return self._env


def test_reap_stale_kills_only_marked_processes_and_not_itself():
    procs = [FakeProcInfo(10, {"SIM_RUN_ID": "r1"}), FakeProcInfo(11, {"PATH": "/bin"}),
             FakeProcInfo(12, denied=True), FakeProcInfo(99, {"SIM_RUN_ID": "r2"})]
    sent = []

    found = P.reap_stale(process_iter=lambda: procs, send=lambda pid, sig: sent.append((pid, sig)), me=99)

    assert found == [(10, "r1")] and sent == [(10, signal.SIGKILL)]


class TestScenario:
    def test_scenario_parsed_and_hashed(self):
        s = P.RunSpec.from_json(start_json(scenario={"seed": 7, "orders": {"outbound": []}}))

        assert s.scenario == {"seed": 7, "orders": {"outbound": []}}
        assert s.scenario_sha256 == P.scenario_sha256({"seed": 7, "orders": {"outbound": []}}) and len(s.scenario_sha256) == 64

    def test_scenario_must_be_object_small_and_match_sha(self):
        with pytest.raises(ValueError):
            P.RunSpec.from_json(start_json(scenario=[1, 2]))
        with pytest.raises(ValueError):
            P.RunSpec.from_json(start_json(scenario={"blob": "x" * (P.MAX_SCENARIO_BYTES + 1)}))
        with pytest.raises(ValueError):
            P.RunSpec.from_json(start_json(scenario={"seed": 1}, scenario_sha256="f" * 64))
        with pytest.raises(ValueError):
            P.RunSpec.from_json(start_json(scenario={"spawn": [1, 2]}))

    def test_canonical_json_is_key_sorted_and_compact(self):
        assert P.canonical_json({"b": 1, "a": [1, 2]}) == b'{"a":[1,2],"b":1}'

    def test_env_without_scenario_has_no_scenario_keys(self):
        env = P.run_env(P.RunSpec.from_json(start_json()), base={})

        assert "SIM_SCENARIO_PATH" not in env and "WSIM_SPAWN" not in env
