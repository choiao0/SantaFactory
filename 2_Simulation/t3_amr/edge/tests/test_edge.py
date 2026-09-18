"""edge.edge — MQTT 연결부: 구독·NBIRTH·유언 재장전·디스패치·종료 사다리·잔재 정리·.env 로딩.
paho 는 가짜 클라이언트로 대신한다."""
import os
import signal

import pytest

from edge import edge as E
from edge import runner as R
from edge import spb
from edge.tests.fakes import FakeRecorder, FakeUploader, ImmediateExecutor, ncmd, start_payload


class FakeInfo:
    def wait_for_publish(self, timeout):
        pass


class FakeMqttClient:
    """Edge 가 만지는 paho 표면만 흉내 낸다."""

    def __init__(self):
        self.published, self.subscribed, self.will, self.auth = [], [], None, None
        self.connected, self.loop, self.disconnected = None, None, False
        self.suppress_exceptions = False
        self.on_connect = self.on_disconnect = self.on_message = None

    def username_pw_set(self, username, password):
        self.auth = (username, password)

    def reconnect_delay_set(self, lo, hi):
        pass

    def will_set(self, topic, payload, qos=0, retain=False):
        self.will = (topic, spb.decode(payload), qos, retain)

    def subscribe(self, subs):
        self.subscribed.append(list(subs))

    def publish(self, topic, payload, qos=0, retain=False):
        self.published.append((topic, spb.decode(payload), qos, retain))
        return FakeInfo()

    def connect_async(self, host, port, keepalive=60):
        self.connected = (host, port, keepalive)

    def loop_start(self):
        self.loop = "started"

    def loop_stop(self):
        self.loop = "stopped"

    def disconnect(self):
        self.disconnected = True

    def kinds(self):
        return [t.split("/")[2] for t, *_ in self.published]


class Msg:
    def __init__(self, topic, payload):
        self.topic, self.payload = topic, payload


@pytest.fixture
def edge(tmp_path):
    session = spb.EdgeSession(str(tmp_path / "bdseq"))
    e = E.Edge("sim-runner-gpu01", "sim-runner-gpu01", "pw", session, str(tmp_path / "alive"), client=FakeMqttClient())
    e.rec = FakeRecorder()
    # 문자열이면 Start 직전 GPU 프로브가 실패한다 (-241).
    # CI 이미지(python:slim)엔 nvidia-smi 가 없으니 기본 프로브를 쓰면 안 된다.
    e.gpu_error = None
    e.runner = R.Runner(R.RunnerConfig(heartbeat_s=5.0), session, lambda: e.rec, e, FakeUploader(),
                        ram_mb=lambda pids: 1, vram_mb=lambda: 1, executor=ImmediateExecutor(),
                        gpu_probe=lambda: e.gpu_error, on_gpu_lost=e.on_gpu_lost)
    return e


class TestConnection:
    def test_constructor_wires_auth_and_callbacks(self, edge):
        c = edge.client
        assert c.auth == ("sim-runner-gpu01", "pw") and c.suppress_exceptions is True
        assert c.on_connect == edge._on_connect and c.on_message == edge._on_message

    def test_will_is_armed_with_the_next_bdseq_before_connect(self, edge):
        bd = edge.session.bd_seq
        edge._arm_will()
        topic, d, qos, retain = edge.client.will
        assert topic == "spBv1.0/santa/NDEATH/sim-runner-gpu01" and qos == 1 and retain is False
        assert spb.metrics_by_name(d)["bdSeq"] == (bd + 1) % spb.SEQ_MOD == edge.session.bd_seq

    def test_on_connect_subscribes_ncmd_and_state_then_sends_nbirth(self, edge):
        edge._on_connect(edge.client, None, None, 0)
        assert edge.client.subscribed == [[("spBv1.0/santa/NCMD/sim-runner-gpu01", 0), ("spBv1.0/STATE/+", 1)]]
        assert edge.client.kinds() == ["NBIRTH"]

    def test_refused_connect_does_nothing(self, edge):
        edge._on_connect(edge.client, None, None, 5)
        assert edge.client.subscribed == [] and edge.client.published == []

    def test_disconnect_rearms_will_unless_shutting_down(self, edge):
        edge._arm_will()
        bd = edge.session.bd_seq
        edge._on_disconnect(edge.client, None, None, 7)
        assert edge.session.bd_seq == (bd + 1) % spb.SEQ_MOD
        edge.stop_event.set()
        edge._on_disconnect(edge.client, None, None, 7)
        assert edge.session.bd_seq == (bd + 1) % spb.SEQ_MOD


class TestDispatch:
    def test_ncmd_start_reaches_the_runner(self, edge):
        edge._on_message(edge.client, None, Msg("spBv1.0/santa/NCMD/sim-runner-gpu01",
                                                ncmd(**{R.CMD_START: start_payload()})))
        assert edge.runner.state == R.STARTING and edge.rec.started

    def test_host_state_and_unknown_topics_do_not_raise(self, edge):
        edge._on_message(edge.client, None, Msg("spBv1.0/STATE/host-orch", b'{"online": true, "timestamp": 1}'))
        edge._on_message(edge.client, None, Msg("uagv/v2/x/y/state", b"{}"))
        edge._on_message(edge.client, None, Msg("spBv1.0/santa/NCMD/sim-runner-gpu01", b"\xff\xfe garbage"))
        assert edge.runner.state == R.IDLE


class TestRunAndShutdown:
    def test_run_connects_and_shutdown_publishes_ndeath_and_disconnects(self, edge):
        edge.stop_event.set()                       # 루프에 들어가기 전에 멈춘 상태 → 바로 종료 사다리
        edge.run("broker", 1883)
        c = edge.client
        assert c.connected == ("broker", 1883, E.KEEPALIVE_S) and c.loop == "stopped" and c.disconnected
        assert c.kinds()[-1] == "NDEATH"
        assert spb.metrics_by_name(c.published[-1][1])["bdSeq"] == edge.session.bd_seq

    def test_gpu_lost_on_start_stops_the_loop_with_exit_code_3(self, edge):
        edge._on_connect(edge.client, None, None, 0)
        edge.gpu_error = "nvidia-smi rc=255: Failed to initialize NVML: Unknown Error"
        edge._on_message(edge.client, None, Msg("spBv1.0/santa/NCMD/sim-runner-gpu01",
                                                ncmd(**{R.CMD_START: start_payload()})))
        assert edge.runner.state == R.ERROR and not edge.rec.started
        assert edge.stop_event.is_set() and edge.exit_code == E.EXIT_GPU_LOST

    def test_shutdown_while_running_stops_the_run_first(self, edge, monkeypatch):
        edge._on_connect(edge.client, None, None, 0)
        edge._on_message(edge.client, None, Msg("spBv1.0/santa/NCMD/sim-runner-gpu01",
                                                ncmd(**{R.CMD_START: start_payload()})))
        edge.rec.is_ready = True
        edge.runner.tick(1.0)
        assert edge.runner.state == R.RUNNING
        monkeypatch.setattr(E.time, "sleep", lambda s: None)

        edge._shutdown()

        assert edge.rec.stop_requested_at is not None
        assert edge.runner.state == R.ERROR            # 영상 없음 → ERROR 로 닫힘
        assert edge.client.kinds()[-1] == "NDEATH"

    def test_touch_alive_writes_epoch_seconds(self, edge):
        edge.touch_alive(1234.9)
        with open(edge.alive_path, encoding="ascii") as f:
            assert f.read() == "1234"


class FakeProc:
    def __init__(self, pid, env=None, raises=None):
        self.pid, self._env, self._raises = pid, env or {}, raises

    def environ(self):
        if self._raises:
            raise self._raises
        return self._env


def test_reap_stale_kills_only_marked_processes_except_me():
    import psutil

    procs = [FakeProc(10, {E.RUN_ENV_MARK: "verify_1"}), FakeProc(11, {}), FakeProc(12, {E.RUN_ENV_MARK: "verify_2"}),
             FakeProc(13, raises=psutil.AccessDenied(13)), FakeProc(99, {E.RUN_ENV_MARK: "me"})]
    sent = []
    found = E.reap_stale(process_iter=lambda: procs, send=lambda pid, sig: sent.append((pid, sig)), me=99)
    assert found == [(10, "verify_1"), (12, "verify_2")]
    assert sent == [(10, signal.SIGKILL), (12, signal.SIGKILL)]


def test_load_env_file_does_not_override_existing_environment(tmp_path, monkeypatch):
    p = tmp_path / "x.env"
    p.write_text("# comment\nMQTT_HOST=broker.local\nMQTT_PORT='1884'\nKEEP=file\nBROKEN LINE\n", encoding="utf-8")
    monkeypatch.setenv("KEEP", "env")
    monkeypatch.delenv("MQTT_HOST", raising=False)
    monkeypatch.delenv("MQTT_PORT", raising=False)
    loaded = E.load_env_file(str(p))
    assert loaded == {"MQTT_HOST": "broker.local", "MQTT_PORT": "1884"}
    assert os.environ["KEEP"] == "env" and os.environ["MQTT_PORT"] == "1884"


def test_build_requires_the_runner_password(tmp_path, monkeypatch):
    monkeypatch.delenv("MQTT_PW_SIM_RUNNER", raising=False)
    args = E.build_parser().parse_args(["--state-dir", str(tmp_path), "--t3amr-dir", str(tmp_path)])
    with pytest.raises(SystemExit):
        E.build(args)
    monkeypatch.setenv("MQTT_PW_SIM_RUNNER", "pw")
    monkeypatch.setenv("MQTT_HOST", "broker.local")
    monkeypatch.setenv("MQTT_PORT", "1883")
    for k in ("MINIO_ENDPOINT", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY"):
        monkeypatch.delenv(k, raising=False)
    e, host, port = E.build(args)
    assert (host, port) == ("broker.local", 1883) and e.runner.cfg.node_id == "sim-runner-gpu01"
    assert e.runner.uploader is None                     # MINIO_* 없음
