"""edge.runner — 상태기계 · NCMD · 세션 규칙 · 영상 URL 보고 (MQTT_CONTRACT §5.3 · §5.4)."""
import json

import pytest

from edge import runner as R
from edge import spb
from edge.tests.fakes import FakeUploader, Harness, ManualExecutor, ncmd


@pytest.fixture
def h(tmp_path):
    return Harness(tmp_path, heartbeat_s=5.0, ready_timeout_s=30.0, host_offline_s=15.0)


class TestSession:
    def test_connect_publishes_nbirth_with_every_metric_including_video_url(self, h):
        h.runner.on_connected(0.0)

        (topic, d, qos, retain), = h.pub.msgs
        named = spb.metrics_by_name(d)
        assert topic == "spBv1.0/santa/NBIRTH/sim-runner-gpu01" and qos == 0 and retain is False
        assert d.seq == 0 and set(named) == set(R.NODE_METRICS)
        assert named[R.STATE] == "IDLE" and named[R.VIDEO_URL] == "" and named[R.BDSEQ] == h.session.bd_seq

    def test_rebirth_republishes_nbirth(self, h):
        h.connect()
        h.runner.on_ncmd(ncmd(**{R.REBIRTH: True}), 1.0)
        assert h.pub.kinds() == ["NBIRTH"]

    def test_host_back_online_triggers_rebirth(self, h):
        h.connect()
        h.runner.on_host_state(json.dumps({"online": False, "timestamp": 1}).encode(), 1.0)
        h.runner.on_host_state(json.dumps({"online": True, "timestamp": 2}).encode(), 2.0)
        assert h.pub.kinds() == ["NBIRTH"]


class TestStartToRunning:
    def test_start_launches_recorder_and_reports_starting(self, h):
        h.connect()
        h.start(1.0, scenario={"seed": 101})

        assert h.runner.state == R.STARTING and h.rec.started and h.rec.spec.n_robots == 3
        named = h.pub.named("NDATA")
        assert named[R.STATE] == "STARTING" and named[R.RUN_ID] == "verify_77_n3"
        assert named[R.SCENARIO_SHA] == h.rec.spec.scenario_sha256 and named[R.VIDEO_URL] == ""

    def test_capture_on_moves_to_running(self, h):
        h.connect()
        h.start(1.0)
        h.runner.tick(2.0)
        assert h.runner.state == R.STARTING
        h.rec.is_ready = True
        h.runner.tick(3.0)
        assert h.runner.state == R.RUNNING and h.pub.named("NDATA")[R.STATE] == "RUNNING"

    def test_ready_timeout_fails_the_run(self, h):
        h.connect()
        h.start(1.0)
        h.runner.tick(1.0 + 31.0)
        assert h.runner.state == R.STOPPING and h.rec.stop_requested_at is not None
        h.runner.tick(40.0)
        assert h.runner.state == R.ERROR
        assert "ready timeout" in h.pub.named_with("NDATA", R.LAST_ERROR)[R.LAST_ERROR]
        assert h.pub.named_with("NDATA", R.STATE)[R.RUN_ID] == ""

    def test_recorder_dying_during_start_fails(self, h):
        h.connect()
        h.start(1.0)
        h.rec.die()
        h.runner.tick(2.0)
        assert h.runner.state == R.STOPPING
        h.runner.tick(3.0)
        assert h.runner.state == R.ERROR
        assert "exited during start" in h.pub.named_with("NDATA", R.LAST_ERROR)[R.LAST_ERROR]

    def test_bad_start_reports_error_without_state_change(self, h):
        h.connect()
        h.runner.on_ncmd(ncmd(**{R.CMD_START: "{not json"}), 1.0)
        assert h.runner.state == R.IDLE and h.pub.named("NDATA")[R.LAST_ERROR].startswith("bad Start")

    def test_busy_runner_ignores_other_start_but_re_reports_same(self, h):
        h.connect()
        h.run_until_running()
        h.start(5.0, run_id="other")
        assert "busy" in h.pub.named("NDATA")[R.LAST_ERROR]
        h.pub.clear()
        h.start(6.0)
        assert h.pub.named("NDATA")[R.STATE] == "RUNNING" and h.runner.state == R.RUNNING


class TestSideVideo:
    """두 번째 시점 (-264) — 둘 다 올라간 **뒤에** 보고한다."""

    def _stop(self, h):
        h.connect()
        h.run_until_running()
        h.rec.video = "/data/out/demo_verify_77_n3.mp4"
        h.rec.fpv_video = "/data/out/demo_verify_77_n3_fpv.mp4"
        h.stop(100.0)
        h.runner.tick(101.0)

    def test_both_uploaded_in_order_and_reported_once(self, h):
        self._stop(h)
        assert h.uploader.calls == [
            ("/data/out/demo_verify_77_n3.mp4", "verify_77_n3"),
            ("/data/out/demo_verify_77_n3_fpv.mp4", "verify_77_n3")]
        assert h.runner.state == R.IDLE
        # 보고는 **상단 키** 하나다 — 백엔드가 여기서 `_fpv` 를 계산한다
        named = h.pub.named_with("NDATA", R.VIDEO_URL)
        assert named[R.VIDEO_URL] == "verify_77_n3/demo_verify_77_n3.mp4"

    def test_no_fpv_is_bit_identical(self, h):
        h.connect()
        h.run_until_running()
        h.rec.video = "/data/out/demo_verify_77_n3.mp4"
        h.stop(100.0)
        h.runner.tick(101.0)
        assert h.uploader.calls == [("/data/out/demo_verify_77_n3.mp4", "verify_77_n3")]
        assert h.runner.state == R.IDLE


class TestStopAndVideo:
    def test_stop_uploads_video_and_reports_url_with_idle_in_one_ndata(self, h):
        h.connect()
        h.run_until_running()
        h.rec.video = "/data/out/demo_verify_77_n3.mp4"

        h.stop(100.0)
        assert h.runner.state == R.STOPPING and h.rec.stop_requested_at == 100.0
        h.runner.tick(101.0)

        assert h.runner.state == R.IDLE
        assert h.uploader.calls == [("/data/out/demo_verify_77_n3.mp4", "verify_77_n3")]
        named = h.pub.named_with("NDATA", R.VIDEO_URL)       # URL 과 IDLE 이 한 메시지에
        assert named[R.STATE] == "IDLE" and named[R.RUN_ID] == ""
        assert named[R.VIDEO_URL] == "verify_77_n3/demo_verify_77_n3.mp4"      # 객체 키(버킷 없음), URL 아님(-233)

    def test_recorder_finishing_on_its_own_collects_video(self, h):
        h.connect()
        h.run_until_running()
        h.rec.video, h.rec.finished = "/data/out/demo_verify_77_n3.mp4", True
        h.rec.die()
        h.runner.tick(50.0)
        assert h.runner.state == R.STOPPING
        h.runner.tick(51.0)
        assert h.runner.state == R.IDLE
        assert h.pub.named_with("NDATA", R.VIDEO_URL)[R.VIDEO_URL].endswith("demo_verify_77_n3.mp4")

    def test_no_video_after_stop_is_an_error(self, h):
        h.connect()
        h.run_until_running()
        h.stop(100.0)
        h.runner.tick(101.0)
        assert h.runner.state == R.ERROR
        assert "no video" in h.pub.named_with("NDATA", R.LAST_ERROR)[R.LAST_ERROR] and h.uploader.calls == []

    def test_upload_failure_is_an_error_and_keeps_the_frames(self, tmp_path):
        h = Harness(tmp_path, uploader=FakeUploader(fail=OSError("connection refused")), heartbeat_s=5.0)
        h.connect()
        h.run_until_running()
        h.rec.video = "/data/out/demo_verify_77_n3.mp4"
        h.stop(100.0)
        h.runner.tick(101.0)
        assert h.runner.state == R.ERROR and "upload failed" in h.pub.named_with("NDATA", R.LAST_ERROR)[R.LAST_ERROR]
        assert not h.rec.frames_removed                      # 실패 런의 프레임은 진단용으로 남긴다 (-241)

    def test_successful_upload_removes_the_frames(self, h):
        h.connect()
        h.run_until_running()
        h.rec.video = "/data/out/demo_verify_77_n3.mp4"
        h.stop(100.0)
        h.runner.tick(101.0)
        assert h.runner.state == R.IDLE and h.uploader.calls and h.rec.frames_removed

    def test_without_uploader_reports_local_path(self, tmp_path):
        h = Harness(tmp_path, heartbeat_s=5.0)
        h.runner.uploader = None
        h.connect()
        h.run_until_running()
        h.rec.video = "/data/out/demo_verify_77_n3.mp4"
        h.stop(100.0)
        h.runner.tick(101.0)
        assert h.runner.state == R.IDLE and h.pub.named_with("NDATA", R.VIDEO_URL)[R.VIDEO_URL] == "file:///data/out/demo_verify_77_n3.mp4"

    def test_recorder_dying_while_running_without_finish_marker_fails(self, h):
        h.connect()
        h.run_until_running()
        h.rec.die()
        h.runner.tick(50.0)
        h.runner.tick(51.0)
        assert h.runner.state == R.ERROR and "recorder died" in h.pub.named_with("NDATA", R.LAST_ERROR)[R.LAST_ERROR]

    def test_timeout_and_host_offline_fail_the_run(self, tmp_path):
        h = Harness(tmp_path, heartbeat_s=5.0, host_offline_s=15.0)
        h.connect()
        h.run_until_running(timeout_s=100)
        h.runner.tick(1.0 + 101.0)
        assert h.runner.state == R.STOPPING and "timeout_s" in h.pub.named_with("NDATA", R.LAST_ERROR)[R.LAST_ERROR]
        h2 = Harness(tmp_path / "b", heartbeat_s=5.0, host_offline_s=15.0)
        h2.connect()
        h2.run_until_running()
        h2.runner.on_host_state(json.dumps({"online": False, "timestamp": 3}).encode(), 10.0)
        h2.runner.tick(26.0)
        assert h2.runner.state == R.STOPPING
        assert "host-orch offline" in h2.pub.named_with("NDATA", R.LAST_ERROR)[R.LAST_ERROR]

    def test_upload_runs_off_the_tick_and_run_stays_stopping_until_it_finishes(self, tmp_path):
        ex = ManualExecutor()
        h = Harness(tmp_path, executor=ex, heartbeat_s=5.0)
        h.connect()
        h.run_until_running()
        h.rec.video = "/data/out/demo_verify_77_n3.mp4"
        h.stop(100.0)
        h.runner.tick(101.0)                       # 레코더 종료 → 업로드 제출, 아직 STOPPING

        assert h.runner.state == R.STOPPING and len(ex.pending) == 1
        h.start(102.0, run_id="other")             # 업로드 중 새 Start 는 busy
        assert "busy" in h.pub.named_with("NDATA", R.LAST_ERROR)[R.LAST_ERROR]
        h.runner.tick(103.0)                       # 아직 안 끝남 → 그대로
        assert h.runner.state == R.STOPPING

        ex.complete("verify_77_n3/demo_verify_77_n3.mp4")
        h.runner.tick(104.0)
        named = h.pub.named_with("NDATA", R.VIDEO_URL)
        assert h.runner.state == R.IDLE and named[R.STATE] == "IDLE" and named[R.VIDEO_URL].endswith(".mp4")

    def test_upload_failure_on_the_worker_becomes_error(self, tmp_path):
        ex = ManualExecutor()
        h = Harness(tmp_path, executor=ex, heartbeat_s=5.0)
        h.connect()
        h.run_until_running()
        h.rec.video = "/data/out/demo_verify_77_n3.mp4"
        h.stop(100.0)
        h.runner.tick(101.0)
        ex.fail(TimeoutError("read timed out"))
        h.runner.tick(102.0)
        assert h.runner.state == R.ERROR
        assert "upload failed: read timed out" in h.pub.named_with("NDATA", R.LAST_ERROR)[R.LAST_ERROR]

    def test_error_state_accepts_the_next_start(self, h):
        h.connect()
        h.run_until_running()
        h.stop(100.0)
        h.runner.tick(101.0)                       # no video → ERROR
        assert h.runner.state == R.ERROR
        h.start(200.0, run_id="verify_78_n2", n=2)
        assert h.runner.state == R.STARTING and h.rec.spec.run_id == "verify_78_n2"


class TestGpuProbe:
    def test_gpu_loss_reports_error_without_launching_and_asks_for_shutdown(self, h):
        h.connect()
        h.gpu_error = "nvidia-smi rc=255: Failed to initialize NVML: Unknown Error"
        h.start(1.0)
        assert h.runner.state == R.ERROR and not h.rec.started and h.gpu_lost == 1
        m = h.pub.named_with("NDATA", R.LAST_ERROR)
        assert m[R.LAST_ERROR] == "gpu unavailable: " + h.gpu_error and m[R.RUN_ID] == ""

    def test_gpu_ok_launches_as_before(self, h):
        h.connect()
        h.start(1.0)
        assert h.runner.state == R.STARTING and h.rec.started and h.gpu_lost == 0


class TestHeartbeat:
    def test_heartbeat_carries_telemetry_changes_only(self, h):
        h.connect()
        h.runner.tick(5.0)
        named = h.pub.named("NDATA")
        assert named[R.HEARTBEAT] == 5000 and named[R.VRAM] == 2000
        assert R.RAM not in named                  # pids 없음 → RAM 0 = 초기값
        h.pub.clear()
        h.runner.tick(7.0)
        assert h.pub.msgs == []
        h.run_until_running(now=9.0)
        h.runner.tick(12.0)
        named = h.pub.named("NDATA")
        assert named[R.ISAAC] == 1 and named[R.RAM] == 100
