"""edge.recorder — 명령·환경 조립(순수), 촬영 시작·완주 감지(로그 파일), 정지 사다리."""
import os
import signal

from edge import recorder as REC
from edge.spec import RunSpec


class FakePopen:
    _next_pid = 7000

    def __init__(self, argv, **kw):
        FakePopen._next_pid += 1
        self.argv, self.kw, self.pid, self.rc, self.signals = argv, kw, FakePopen._next_pid, None, []

    def poll(self):
        return self.rc

    def send_signal(self, sig):
        self.signals.append(sig)


def cfg(tmp_path, **over):
    d = dict(t3amr_dir=str(tmp_path / "t3"), out_dir=str(tmp_path / "out"), logs_dir=str(tmp_path / "logs"),
             runs_dir=str(tmp_path / "runs"))
    d.update(over)
    return REC.RecorderConfig(**d)


def spec(n=3, **over):
    d = {"run_id": "verify_77_n3", "n_robots": n, "timeout_s": 900}
    d.update(over)
    return RunSpec.from_dict(d)


class TestPureAssembly:
    def test_command_targets_run_record_with_planner(self, tmp_path):
        c = cfg(tmp_path, planner="pibt_h")
        assert REC.command(c) == ["bash", os.path.join(c.t3amr_dir, "run_record.sh"), "--planner", "pibt_h"]

    def test_environment_maps_spec_to_run_record_variables(self, tmp_path):
        s = spec(n=5, scenario={"seed": 101})
        e = REC.environment(cfg(tmp_path, tick_s=1.0), s, base={"PATH": "/bin"}, scenario_path="/x/scenario.json",
                            plan_exists=False)
        assert e["PATH"] == "/bin"
        assert e["RUN_TAG"] == "verify_77_n3" and e[REC.RUN_ENV_MARK] == "verify_77_n3"
        assert e["PIBT_N"] == "5" and e["PIBT_SEED"] == "101" and e["PIBT_MODE"] == "lifelong"
        assert e["PIBT_HORIZON"] == str(600 + 60)                  # window 600 s + 여유 60 s, tick 1 s
        assert e["REPLAN"] == "1"                                   # 계획 폴더 없음 → run_record 가 먼저 계획
        assert e["SIM_SCENARIO_PATH"] == "/x/scenario.json" and e["SIM_SCENARIO_SHA256"] == s.scenario_sha256

    def test_environment_keeps_existing_plan_and_omits_seed_when_absent(self, tmp_path):
        c = cfg(tmp_path)
        os.makedirs(REC.plan_dir(c.t3amr_dir, 3))
        e = REC.environment(c, spec(n=3), base={})
        assert e["REPLAN"] == "0" and "PIBT_SEED" not in e and "SIM_SCENARIO_PATH" not in e

    def test_default_tick_matches_the_211_tick_model(self):
        # path/metrics.tick_seconds = pitch / (v_max × MOVE_TICKS). 215 의 4/3 은 211 이전 값이라
        # 창 300 s 에 270틱만 계획해 시뮬 ≈ 90 s 에 끝났다 (2026-09-16 컨테이너 실측: 400틱 = 시뮬 116 s)
        assert abs(REC.DEFAULT_TICK_S - 1.2 / (0.9 * 4)) < 1e-9
        assert REC.horizon_ticks(300.0) == 1080                     # (300+60) / 0.3333 = 1080

    def test_horizon_ticks_rounds_up(self):
        assert REC.horizon_ticks(600.0, 0.7) == 943                 # (600+60)/0.7 = 942.86 → 943


class TestLifecycle:
    def make(self, tmp_path):
        c = cfg(tmp_path)
        os.makedirs(c.t3amr_dir)
        os.makedirs(c.out_dir)
        r = REC.Recorder(c, spawn=FakePopen, send=lambda proc, sig: proc.signals.append(("group", sig)))
        return c, r

    def test_start_spawns_in_t3amr_dir_with_session_and_scenario_file(self, tmp_path):
        c, r = self.make(tmp_path)
        s = spec(scenario={"seed": 7, "orders": []})
        r.start(s, 0.0)
        assert r.proc.argv[:2] == ["bash", os.path.join(c.t3amr_dir, "run_record.sh")]
        assert r.proc.kw["cwd"] == c.t3amr_dir and r.proc.kw["start_new_session"] is True
        assert r.proc.kw["env"]["PIBT_N"] == "3"
        with open(os.path.join(c.runs_dir, "verify_77_n3", "scenario.json"), "rb") as f:
            assert f.read() == b'{"orders":[],"seed":7}'
        assert r.alive() and not r.dead() and r.pids() == [r.proc.pid] and r.isaac_count() == 1

    def test_ready_when_frames_exist_or_log_says_capture_on(self, tmp_path):
        c, r = self.make(tmp_path)
        r.start(spec(), 0.0)
        assert not r.ready()
        os.makedirs(c.logs_dir, exist_ok=True)
        with open(r.record_log(), "w", encoding="utf-8") as f:
            f.write("[shots] 캡처 ON 12대\n")
        assert r.ready() and not r.finished_normally()
        with open(r.record_log(), "a", encoding="utf-8") as f:
            f.write("전원 완주\n")
        assert r.finished_normally()

    def test_ready_by_frame_files(self, tmp_path):
        c, r = self.make(tmp_path)
        r.start(spec(), 0.0)
        os.makedirs(r.shots_dir())
        open(os.path.join(r.shots_dir(), "f_000001.png"), "wb").close()
        assert r.frames() == 1 and r.ready()

    def test_stop_ladder_int_then_term_then_kill(self, tmp_path):
        c, r = self.make(tmp_path)
        r.start(spec(), 0.0)
        r.request_stop(10.0)
        assert r.proc.signals == [signal.SIGINT] and r.dead() is False
        assert r.poll_stop(10.0 + REC.INT_GRACE_S - 1) is False and r.proc.signals == [signal.SIGINT]
        assert r.poll_stop(10.0 + REC.INT_GRACE_S) is False
        assert r.proc.signals[-1] == ("group", signal.SIGTERM)
        assert r.poll_stop(10.0 + REC.INT_GRACE_S + REC.TERM_GRACE_S) is False
        assert r.proc.signals[-1] == ("group", signal.SIGKILL)
        r.proc.rc = -9
        assert r.poll_stop(999.0) is True

    def test_video_path_only_when_mp4_is_nonempty(self, tmp_path):
        c, r = self.make(tmp_path)
        r.start(spec(), 0.0)
        assert r.video_path() is None
        p = os.path.join(c.out_dir, "demo_verify_77_n3.mp4")
        open(p, "wb").close()
        assert r.video_path() is None
        with open(p, "wb") as f:
            f.write(b"\x00" * 16)
        assert r.video_path() == p

    def test_remove_frames_deletes_the_shots_dir_and_is_a_noop_afterwards(self, tmp_path):
        r = REC.Recorder(cfg(tmp_path), spawn=FakePopen)
        r.spec = spec()
        os.makedirs(r.shots_dir())
        for name in ("f_000001.png", "f_000002.png"):
            open(os.path.join(r.shots_dir(), name), "wb").close()

        assert r.remove_frames() == 2 and not os.path.exists(r.shots_dir())
        assert r.remove_frames() == 0
