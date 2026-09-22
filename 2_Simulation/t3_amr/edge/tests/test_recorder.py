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

    def test_default_tick_follows_the_pitch_the_child_actually_runs(self):
        # path/metrics.tick_seconds = pitch / (v_max × MOVE_TICKS). 215 의 4/3 은 211 이전 값이라
        # 창 300 s 에 270틱만 계획해 시뮬 ≈ 90 s 에 끝났다 (2026-09-16 컨테이너 실측: 400틱 = 시뮬 116 s)
        #
        # ★★ 2026-09-21 — 기본을 1.2 에서 **1.0** 으로 내렸다. run_record.sh:124 가
        #   `export PIBT_PITCH="${PIBT_PITCH:-1.0}"` 라 자식은 늘 1.0 으로 돌고 있었고,
        #   여기만 1.2 로 환산해 **창을 20 % 짧게** 계획했다. 위 215 와 같은 종류의 사고다.
        assert abs(REC.PLAN_PITCH_DEFAULT_M - 1.0) < 1e-9           # run_record.sh:124 와 같아야 한다
        assert abs(REC.tick_seconds({}) - 1.0 / (0.9 * 4)) < 1e-9
        assert REC.horizon_ticks(300.0, REC.tick_seconds({})) == 1296   # (300+60) / 0.2778 = 1296

    def test_tick_follows_PIBT_PITCH_when_given(self):
        """엣지 환경에 pitch 가 있으면 자식도 그 값을 물려받는다 — 둘이 같은 식을 써야 한다."""
        assert abs(REC.tick_seconds({"PIBT_PITCH": "1.2"}) - 1.2 / (0.9 * 4)) < 1e-9
        for bad in ("", "0", "-1", "abc"):
            assert abs(REC.tick_seconds({"PIBT_PITCH": bad}) - 1.0 / (0.9 * 4)) < 1e-9

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

    def test_side_video_path_is_the_top_name_plus_side(self, tmp_path):
        """백엔드가 상단 키에서 `_side` 를 계산한다 — 이름이 어긋나면 버튼만 안 생긴다 (-264)."""
        c, r = self.make(tmp_path)
        r.start(spec(), 0.0)
        assert r.side_video_path() is None                      # 없으면 None
        p = os.path.join(c.out_dir, "demo_verify_77_n3_side.mp4")
        open(p, "wb").close()
        assert r.side_video_path() is None                      # 0바이트는 없는 것
        with open(p, "wb") as f:
            f.write(b"side-mp4-bytes")
        assert r.side_video_path() == p
        # 상단과 **이름만** 다르다
        top = os.path.join(c.out_dir, "demo_verify_77_n3.mp4")
        assert r.side_video_path() == top.replace(".mp4", "_side.mp4")

    def test_remove_frames_deletes_the_shots_dir_and_is_a_noop_afterwards(self, tmp_path):
        r = REC.Recorder(cfg(tmp_path), spawn=FakePopen)
        r.spec = spec()
        os.makedirs(r.shots_dir())
        for name in ("f_000001.png", "f_000002.png"):
            open(os.path.join(r.shots_dir(), name), "wb").close()

        assert r.remove_frames() == 2 and not os.path.exists(r.shots_dir())
        assert r.remove_frames() == 0


class TestHeadlessServicePath:
    """서비스 런은 **헤드리스로 촬영하고, 창을 시뮬 초로 끊고, 접촉으로 안 죽는다** (2026-09-22).

    셋 다 같은 이유에서 나온다 — 검증 한 판이 창의 36 %만 돌고(벽시계 창),
    첫 접촉에 죽고, 12~30분 걸렸다. 그 상태로는 이산·물리 대조를 한 번 할
    때마다 30분을 태운다.
    """

    def env(self, tmp_path, **over):
        return REC.environment(cfg(tmp_path, **over), spec(), base={}, plan_exists=True)

    def test_service_runs_capture_headless(self, tmp_path):
        e = self.env(tmp_path)
        # Kit `--exec` 경로는 매 스텝 렌더하고 그린 것의 95 %를 버린다 (실시간 0.36배).
        assert e["HEADLESS"] == "1"
        # 준비 프레임 상한 — 기본 12,000 은 헤드리스에서 4초라 준비를 못 넘긴다.
        assert int(e["PIBT_HL_SETUP_CAP"]) >= 400000

    def test_the_runner_is_not_given_a_sim_second_cap(self, tmp_path):
        """창을 끊는 주체는 **host-orch 하나**여야 한다.

        host-orch 가 `Runner/SimTime` 으로 시뮬 초 창을 끊는다. 러너에게도
        상한을 걸면 시계가 둘이 되고, 러너가 먼저 멈추면 host-orch 가 그것을
        「런이 스스로 끝났다」= FAILED 로 적는다. 폭주 방지는 벽시계
        `spec.timeout_s` 가 이미 한다."""
        e = self.env(tmp_path)
        assert "PIBT_HL_MAX_SIM" not in e
        # 계획 지평은 창보다 길다 — 창 끝은 host-orch Stop 이 자른다.
        assert int(e["PIBT_HORIZON"]) > spec().window_s / REC.DEFAULT_TICK_S

    def test_sim_time_is_reported_so_the_window_can_be_cut_in_sim_seconds(self, tmp_path):
        """헤드리스 러너가 시뮬 시각을 찍고, 엣지가 그걸 읽어 NDATA 로 싣는다.

        이 사슬이 끊기면 host-orch 가 벽시계로 후퇴한다 — 깨져도 **조용하다.**"""
        from edge import runner as RUN
        assert RUN.SIM_TIME == "Runner/SimTime"
        assert RUN.SIM_TIME in RUN.NODE_METRICS          # NBIRTH 에 선언돼야 읽힌다
        assert hasattr(REC.Recorder, "sim_time")

    def test_contact_counts_instead_of_killing_the_run(self, tmp_path):
        # 검증이 낼 답은 「실패」가 아니라 「몇 번 닿았다」다.
        assert self.env(tmp_path)["PIBT_CONTACT_ABORT"] == "0"


class TestHeadlessLogMarkers:
    """헤드리스 러너는 Kit 과 **다른 말**을 쓴다. 감시하는 쪽이 그 말을 알아야 한다."""

    def make(self, tmp_path):
        c = cfg(tmp_path)
        os.makedirs(c.t3amr_dir)
        os.makedirs(c.out_dir)
        os.makedirs(c.logs_dir, exist_ok=True)
        r = REC.Recorder(c, spawn=FakePopen, send=lambda proc, sig: None)
        r.start(spec(), 0.0)
        return c, r

    def write(self, r, text):
        with open(r.record_log(), "a", encoding="utf-8") as f:
            f.write(text)

    def test_headless_capture_marker_counts_as_ready(self, tmp_path):
        _, r = self.make(tmp_path)
        assert not r.ready()
        self.write(r, "[hl] 촬영 ON (리플리케이터) /out/shots · 20스텝마다 .png\n")
        assert r.ready()

    def test_headless_finish_marker_counts_as_finished(self, tmp_path):
        _, r = self.make(tmp_path)
        assert not r.finished_normally()
        self.write(r, "[hl] 주행 종료 — sim 600.0s · 벽시계 366.0s · 평균 배속 1.64x\n")
        assert r.finished_normally()

    def test_sim_time_reads_the_last_progress_line(self, tmp_path):
        _, r = self.make(tmp_path)
        assert r.sim_time() is None                       # Kit 경로 = 보고 없음
        self.write(r, "[hl] sim     10.0s | 벽시계      6.1s | 배속  1.64x\n")
        self.write(r, "[hl] sim    123.4s | 벽시계     75.2s | 배속  1.64x\n")
        assert r.sim_time() == 123.4

    def test_sim_time_survives_a_long_log(self, tmp_path):
        """뒤에서만 읽는다 — 런이 길어져도 비용이 일정해야 한다."""
        _, r = self.make(tmp_path)
        self.write(r, "채워넣기\n" * 20000)
        self.write(r, "[hl] sim    600.0s | 벽시계    366.0s | 배속  1.64x\n")
        assert r.sim_time() == 600.0
