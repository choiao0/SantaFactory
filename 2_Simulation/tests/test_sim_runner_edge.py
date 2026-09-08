"""sim_runner.edge — 구독 목록(acl.conf 와 1:1) · .env 로딩 · build() 의 비밀번호 검사."""
import os

import pytest

from sim_runner import edge as E
from sim_runner import runner as R
from sim_runner import spb


def make_edge(tmp_path):
    session = spb.EdgeSession(str(tmp_path / "bdseq"))
    e = E.Edge("sim-runner-gpu01", "sim-runner-gpu01", "pw", session)
    e.runner = R.Runner(R.RunnerConfig(), session, lambda: None, e)
    return e


def test_subscriptions_match_acl_allow_list(tmp_path):
    e = make_edge(tmp_path)

    assert e.subscriptions() == [("spBv1.0/santa/NCMD/sim-runner-gpu01", 0),
                                 ("spBv1.0/santa/DCMD/sim-runner-gpu01/+", 0),
                                 ("spBv1.0/STATE/+", 1),
                                 ("uagv/v2/+/+/state", 0),
                                 ("uagv/v2/+/+/connection", 1)]


def test_subscriptions_are_covered_by_acl_conf(tmp_path):
    """acl.conf 의 sim-runner subscribe 목록에 없는 토픽을 구독하면 EMQX 가 끊는다 — 목록을 파일에서 직접 대조."""
    acl = os.path.join(os.path.dirname(E.SIM_DIR), "3_FMS", "infra", "emqx", "acl.conf")
    if not os.path.exists(acl):
        pytest.skip("acl.conf not in this checkout")
    text = open(acl, encoding="utf-8").read()
    block = text[text.index('{allow, {username, "sim-runner-gpu01"}, subscribe'):]
    block = block[:block.index("]}.")]

    for topic, _ in make_edge(tmp_path).subscriptions():
        assert f'"{topic}"' in block, topic


def test_load_env_file_sets_missing_keys_only(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# comment\nMQTT_HOST=1.2.3.4\nMQTT_PW_AMR='secret'\nBAD LINE\nEXISTING=file\n")
    monkeypatch.setenv("EXISTING", "shell")
    monkeypatch.delenv("MQTT_HOST", raising=False)
    monkeypatch.delenv("MQTT_PW_AMR", raising=False)

    loaded = E.load_env_file(str(env))

    assert loaded == {"MQTT_HOST": "1.2.3.4", "MQTT_PW_AMR": "secret"}
    assert os.environ["EXISTING"] == "shell" and os.environ["MQTT_PW_AMR"] == "secret"


def test_build_requires_passwords_from_env(tmp_path, monkeypatch):
    monkeypatch.delenv("MQTT_PW_SIM_RUNNER", raising=False)
    monkeypatch.setenv("MQTT_PW_AMR", "x")
    args = E.build_parser().parse_args(["--state-dir", str(tmp_path)])

    with pytest.raises(SystemExit):
        E.build(args)


def test_build_wires_runner_publisher_and_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MQTT_PW_SIM_RUNNER", "s")
    monkeypatch.setenv("MQTT_PW_AMR", "a")
    monkeypatch.setenv("MQTT_HOST", "9.9.9.9")
    args = E.build_parser().parse_args(["--state-dir", str(tmp_path), "--port", "31883"])

    edge, host, port = E.build(args)

    assert (host, port) == ("9.9.9.9", 31883)
    assert edge.runner.pub is edge and edge.runner.cfg.node_id == "sim-runner-gpu01"
    pm = edge.runner.procs_factory()
    assert pm.fake is True and pm.env.amr_password == "a" and pm.env.mqtt_host == "9.9.9.9"


def test_sample_vram_runs_every_period_and_keeps_last_value_on_failure(tmp_path):
    e = make_edge(tmp_path)
    calls = []

    def sample():
        calls.append(1)
        return 1500 if len(calls) == 1 else None

    e.sample_vram(0.0, sample)
    e.sample_vram(1.0, sample)
    e.sample_vram(5.0, sample)

    assert len(calls) == 2 and e.cached_vram() == 1500


def test_message_handler_survives_a_handler_exception(tmp_path):
    e = make_edge(tmp_path)

    class Msg:
        topic, payload = "uagv/v2/idealworks/amr01/state", b"{}"

    def boom(*_):
        raise RuntimeError("boom")

    e.runner.on_vda = boom

    e._on_message(None, None, Msg())      # 예외가 새어 나오면 paho 네트워크 스레드가 죽는다


def test_disconnect_rearms_will_under_the_lock_with_next_bdseq(tmp_path):
    e = make_edge(tmp_path)
    e.session.new_session()
    armed = []
    e.client.will_set = lambda topic, payload, qos, retain: armed.append((topic, spb.metrics_by_name(spb.decode(payload))))

    e._on_disconnect(None, None, None, 7)

    assert armed == [("spBv1.0/santa/NDEATH/sim-runner-gpu01", {"bdSeq": 1})] and e.session.seq == 0
