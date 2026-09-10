"""fms_core.edge · app — 구독 목록(acl.conf 의 fms-core 와 1:1) · .env 로딩 · 옵션 파싱 · 비밀번호 검사."""
import os

import pytest

from fms_core import app as A
from fms_core import edge as E
from fms_core import spb
from fms_core.conductor import Conductor, ConductorConfig

FMS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def make_edge(tmp_path):
    session = spb.EdgeSession(str(tmp_path / "bdseq"))
    c = Conductor(ConductorConfig(), session, None)
    e = E.Edge("fms-core", "pw", session, c)
    c.pub = e
    return e


def test_subscriptions_match_acl_allow_list(tmp_path):
    assert make_edge(tmp_path).subscriptions() == [("spBv1.0/santa/NCMD/fms-core", 0), ("spBv1.0/STATE/+", 1),
                                                   ("uagv/v2/+/+/state", 0), ("uagv/v2/+/+/connection", 1)]


def test_subscriptions_are_covered_by_acl_conf(tmp_path):
    """acl.conf 의 fms-core subscribe 목록에 없는 토픽을 구독하면 EMQX 가 끊는다 — 파일에서 직접 대조."""
    text = open(os.path.join(FMS, "infra", "emqx", "acl.conf"), encoding="utf-8").read()
    block = text[text.index('{allow, {username, "fms-core"}, subscribe'):]
    block = block[:block.index("]}.")]
    for topic, _ in make_edge(tmp_path).subscriptions():
        assert f'"{topic}"' in block, topic


def test_publish_topics_are_covered_by_acl_conf():
    """conductor 가 발행하는 토픽 종류가 acl.conf 의 fms-core publish 허용 안인가."""
    text = open(os.path.join(FMS, "infra", "emqx", "acl.conf"), encoding="utf-8").read()
    block = text[text.index('{allow, {username, "fms-core"}, {publish'):]
    block = block[:block.index("]}.")]
    for topic in ("uagv/v2/+/+/order", "uagv/v2/+/+/instantActions", "biz/v1/event",
                  "spBv1.0/santa/NBIRTH/fms-core", "spBv1.0/santa/NDEATH/fms-core", "spBv1.0/santa/NDATA/fms-core"):
        assert f'"{topic}"' in block, topic


def test_load_env_file_sets_missing_keys_only(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# c\nMQTT_HOST=1.2.3.4\nMQTT_PW_FMS_CORE='secret'\nBAD LINE\nEXISTING=file\n")
    monkeypatch.setenv("EXISTING", "shell")
    monkeypatch.delenv("MQTT_HOST", raising=False)
    monkeypatch.delenv("MQTT_PW_FMS_CORE", raising=False)
    assert A.load_env_file(str(env)) == {"MQTT_HOST": "1.2.3.4", "MQTT_PW_FMS_CORE": "secret"}
    assert os.environ["EXISTING"] == "shell"


def test_parse_options_coerces():
    assert A.parse_options(["aisle_block=true", "horizon_ticks=600", "order_gap=2.5", "theta_path=/x.json"]) == {
        "aisle_block": True, "horizon_ticks": 600, "order_gap": 2.5, "theta_path": "/x.json"}
    with pytest.raises(SystemExit):
        A.parse_options(["nokey"])


def test_build_requires_password(tmp_path, monkeypatch):
    monkeypatch.delenv("MQTT_PW_FMS_CORE", raising=False)
    args = A.build_parser().parse_args(["--state-dir", str(tmp_path)])
    with pytest.raises(SystemExit, match="MQTT_PW_FMS_CORE"):
        A.build(args)


def test_build_wires_conductor(tmp_path, monkeypatch):
    monkeypatch.setenv("MQTT_PW_FMS_CORE", "pw")
    args = A.build_parser().parse_args(["--state-dir", str(tmp_path), "--host", "b", "--port", "1999",
                                        "--planner-opt", "aisle_block=true", "--tick-s", "2"])
    edge, host, port = A.build(args)
    assert (host, port) == ("b", 1999)
    assert edge.conductor.pub is edge and edge.conductor.cfg.tick_s == 2.0
    assert edge.conductor.cfg.planner_options == {"aisle_block": True}
