"""DES 피크 구간 재생 (S15P21A106-275) — 인라인 궤적 · 구간 모드 환경 · 창 시각 · 물리 지표 전달.

검증은 DES 6시간 중 가장 바쁜 10분만 물리로 본다. 백엔드가 그 구간 궤적을 메시지에
실어 보내면(`scenario.trajectory_gz_b64`) 엣지가 풀어 러너에 넘기고, 러너가 쓴 물리 지표를
영상 URL 과 같은 NDATA 로 host-orch 에 돌려준다.
"""
import base64
import gzip
import json
import os

import pytest

from edge import recorder as REC
from edge import runner as R
from edge import spec as S
from edge.spec import RunSpec
from edge.tests.fakes import Harness
from edge.tests.test_recorder import FakePopen, cfg

SLICE = {"format": 1, "t_start_s": 3540.0, "t0_s": 3600.0, "t_end_s": 4260.0,
         "warmup_s": 60.0, "window_s": 600.0, "speed_mps": 0.9,
         "des_window": {"tasks_done": 174}}
DOC = {"dt_s": 0.2778, "model": "heading",
       "robots": {"0": [[3540.0, 1.1, 2.5]]}, "headings": {"0": [[3540.0, 0.0]]},
       "actions": {"0": []}, "tasks": [], "slice": SLICE}


def b64(doc):
    return base64.b64encode(gzip.compress(json.dumps(doc).encode("utf-8"))).decode("ascii")


def spec_with(scenario=None, **over):
    d = {"run_id": "verify_18_n10", "n_robots": 10, "timeout_s": 1400}
    if scenario is not None:
        d["scenario"] = scenario
    d.update(over)
    return RunSpec.from_dict(d)


class TestInlineTrajectory:
    def test_property_reads_the_inline_field(self):
        assert spec_with({"trajectory_gz_b64": b64(DOC)}).trajectory_b64
        assert spec_with({"seed": 101}).trajectory_b64 is None

    def test_decode_returns_the_json_and_its_slice_block(self):
        body, sl = S.decode_trajectory(b64(DOC))
        assert json.loads(body)["robots"] == DOC["robots"]
        assert sl["t0_s"] == 3600.0 and sl["warmup_s"] == 60.0

    def test_a_trajectory_without_slice_decodes_with_no_block(self):
        doc = {k: v for k, v in DOC.items() if k != "slice"}
        _, sl = S.decode_trajectory(b64(doc))
        assert sl is None

    @pytest.mark.parametrize("bad, why", [
        ("@@@not-base64@@@", "base64"),
        (base64.b64encode(b"plain text, not gzip").decode(), "gzip"),
        (base64.b64encode(gzip.compress(b"[1, 2, 3]")).decode(), "dt_s"),
        (base64.b64encode(gzip.compress(b"{not json")).decode(), "JSON"),
    ])
    def test_broken_payloads_are_rejected_with_a_reason(self, bad, why):
        with pytest.raises(ValueError, match=why):
            S.decode_trajectory(bad)

    def test_unpacked_size_is_capped(self, monkeypatch):
        """gzip 폭탄 — 풀린 크기 상한을 넘으면 멈춘다."""
        monkeypatch.setattr(S, "MAX_TRAJ_BYTES", 100)
        with pytest.raises(ValueError, match="too large"):
            S.decode_trajectory(b64(DOC))

    def test_scenario_limit_fits_a_15_robot_peak_slice(self):
        # 10대 구간 gzip+b64 295 KiB 실측 → 15대 약 440 KiB. 512 KiB 로는 여유가 없다.
        assert S.MAX_SCENARIO_BYTES >= 800 * 1024


class TestRecorderSliceMode:
    def make(self, tmp_path):
        c = cfg(tmp_path)
        os.makedirs(c.t3amr_dir, exist_ok=True)
        os.makedirs(c.out_dir, exist_ok=True)
        os.makedirs(c.logs_dir, exist_ok=True)
        r = REC.Recorder(c, spawn=FakePopen, send=lambda proc, sig: None)
        return c, r

    def test_inline_trajectory_is_unpacked_and_handed_to_the_runner(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PIBT_FRONT_RULE", raising=False)
        monkeypatch.delenv("PIBT_V_EXEC", raising=False)
        c, r = self.make(tmp_path)
        r.start(spec_with({"trajectory_gz_b64": b64(DOC)}), 0.0)
        env = r.proc.kw["env"]
        path = os.path.join(c.runs_dir, "verify_18_n10", "traj.json")
        assert env["PIBT_TRAJ"] == path
        with open(path, encoding="utf-8") as f:
            assert json.load(f)["slice"]["t0_s"] == 3600.0
        # 계획을 안 한다 · FMS 격자 · DES 발자국(앞 2칸) · DES 순항 속도
        assert env["REPLAN"] == "0"
        assert env["PIBT_FMS_GRID"] == "1" and env["PIBT_FRONT_RULE"] == "2"
        assert env["PIBT_V_EXEC"] == "0.9"
        # 계획·씬 폴더는 런마다 따로 — 공용 plan/·stage/ 를 안 건드린다
        run_dir = os.path.join(c.runs_dir, "verify_18_n10")
        assert env["T3AMR_PLAN"] == os.path.join(run_dir, "plan")
        assert env["T3AMR_STAGE"] == os.path.join(run_dir, "stage")

    def test_an_earlier_slice_of_the_same_run_id_is_cleared(self, tmp_path):
        """폴더가 남아 있으면 run_record 가 그 계획(=다른 구간의 스폰 자리)을 재사용한다."""
        c, r = self.make(tmp_path)
        stale = os.path.join(c.runs_dir, "verify_18_n10", "plan", "traj_pibt_h", "fleet_10")
        os.makedirs(stale)
        r.start(spec_with({"trajectory_gz_b64": b64(DOC)}), 0.0)
        assert not os.path.exists(stale)
        assert os.path.isdir(os.path.join(c.runs_dir, "verify_18_n10", "stage"))

    def test_edge_environment_can_still_force_the_4_cell_rule(self, tmp_path):
        """비교 실험용 구멍 — 엣지 환경에 준 값이 이긴다."""
        e = REC.environment(cfg(tmp_path), spec_with(), base={"PIBT_FRONT_RULE": "4"},
                            plan_exists=True, traj_path="/x/traj.json", slice_meta=SLICE)
        assert e["PIBT_FRONT_RULE"] == "4"

    def test_every_run_writes_physics_and_holds_until_stop(self, tmp_path):
        """구간이든 아니든 — 창을 끊는 것은 host-orch 다. 러너가 먼저 내려가면 FAILED 가 된다."""
        c = cfg(tmp_path)
        e = REC.environment(c, spec_with(), base={}, plan_exists=True)
        assert e["PIBT_PHYSICS_OUT"] == os.path.join(c.out_dir, "physics_verify_18_n10.json")
        assert e["PIBT_HOLD_UNTIL_STOP"] == "1"

    def test_broken_trajectory_fails_before_anything_is_launched(self, tmp_path):
        _, r = self.make(tmp_path)
        with pytest.raises(ValueError):
            r.start(spec_with({"trajectory_gz_b64": "@@@"}), 0.0)
        assert r.proc is None

    def test_sim_time_prefers_the_window_clock(self, tmp_path):
        """구간 재생이면 워밍업을 뺀 창 시각을 host-orch 에 준다 — 창은 워밍업 뒤 10분이다."""
        _, r = self.make(tmp_path)
        r.start(spec_with(), 0.0)
        with open(r.record_log(), "a", encoding="utf-8") as f:
            f.write("[hl] sim     70.0s | 벽시계     80.0s | 배속  0.88x (순간  0.90x) |  18.00 ms/step"
                    " | 창    10.0s\n")
        assert r.sim_time() == 10.0

    def test_logs_of_an_earlier_run_with_the_same_id_are_set_aside(self, tmp_path):
        """run_id 는 다시 쓰인다 — 지난 판의 「촬영 ON」·시뮬 시각이 새 판에 섞이면 안 된다."""
        c, r = self.make(tmp_path)
        s = spec_with()
        old = os.path.join(c.logs_dir, "record_verify_18_n10.log")
        with open(old, "w", encoding="utf-8") as f:
            f.write("[hl] 촬영 ON\n[hl] sim    500.0s | 벽시계 300.0s\n")
        with open(REC.physics_path(c, s.run_id), "w", encoding="utf-8") as f:
            f.write('{"robot_contacts": 9}')
        r.start(s, 0.0)
        assert not r.ready() and r.sim_time() is None
        assert os.path.exists(old + ".prev")
        assert r.physics() is None                       # 지난 판 지표는 지웠다

    def test_physics_is_read_from_the_runner_file(self, tmp_path):
        _, r = self.make(tmp_path)
        r.start(spec_with(), 0.0)
        assert r.physics() is None
        doc = {"robot_contacts": 0, "lag": {"p90_s": 1.2}}
        with open(r.physics_path(), "w", encoding="utf-8") as f:
            json.dump(doc, f)
        assert r.physics() == doc


class TestPhysicsInResult:
    @pytest.fixture
    def h(self, tmp_path):
        return Harness(tmp_path, heartbeat_s=5.0, ready_timeout_s=30.0, host_offline_s=15.0)

    def test_nbirth_declares_the_physics_metric(self):
        assert R.PHYSICS == "Runner/Physics" and R.PHYSICS in R.NODE_METRICS

    def test_physics_rides_with_the_video_url_in_the_closing_ndata(self, h):
        h.connect()
        h.run_until_running()
        h.rec.video = "/data/out/demo_verify_77_n3.mp4"
        doc = {"robot_contacts": 0, "rack_contacts": 1, "lag": {"p90_s": 2.4}}
        h.rec.physics_doc = doc
        h.stop(100.0)
        h.runner.tick(101.0)
        named = h.pub.named_with("NDATA", R.VIDEO_URL)
        assert named[R.STATE] == "IDLE"
        assert json.loads(named[R.PHYSICS]) == doc

    def test_physics_is_sent_even_when_the_run_fails(self, h):
        """어디까지 돌다 멈췄는지가 진단 거리다."""
        h.connect()
        h.run_until_running()
        h.rec.physics_doc = {"robot_contacts": 3}
        h.stop(100.0)                                    # 영상 없음 → ERROR
        h.runner.tick(101.0)
        named = h.pub.named_with("NDATA", R.PHYSICS)
        assert named is not None and json.loads(named[R.PHYSICS])["robot_contacts"] == 3

    def test_a_broken_trajectory_is_a_run_error_not_an_edge_crash(self, h):
        h.connect()
        h.rec.launch_error = ValueError("trajectory_gz_b64 is not gzip")
        h.start(1.0)
        assert h.runner.state == R.ERROR
        assert "not gzip" in h.runner.values[R.LAST_ERROR]
