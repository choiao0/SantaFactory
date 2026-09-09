"""host_orch.mqtt_host — STATE retained/유언, 재접속 시 timestamp 갱신, 구독이 ACL 안인지, NCMD 인코딩."""
import json
import os
import threading

from host_orch import mqtt_host as H
from host_orch import spb


class FakeClient:
    def __init__(self):
        self.wills, self.subs, self.pubs = [], [], []

    def will_set(self, topic, payload, qos, retain):
        self.wills.append((topic, json.loads(payload), qos, retain))

    def subscribe(self, subs):
        self.subs.append(subs)

    def publish(self, topic, payload, qos=0, retain=False):
        self.pubs.append((topic, payload, qos, retain))


def make():
    h = H.HostClient("host-orch", "pw", "santa", lambda t, p: None, threading.RLock())
    fake = FakeClient()
    h.client = fake
    return h, fake


def test_connect_publishes_retained_online_state_and_subscribes():
    h, fake = make()
    h._arm_will()

    h._on_connect(fake, None, None, 0)

    assert fake.wills == [("spBv1.0/STATE/host-orch", {"online": False, "timestamp": h.t_online}, 1, True)]
    assert fake.subs == [[("spBv1.0/santa/#", 0)]]
    assert fake.pubs == [("spBv1.0/STATE/host-orch", json.dumps({"online": True, "timestamp": h.t_online}).encode(), 1, True)]
    assert h.connected.is_set()


def test_abnormal_disconnect_rearms_will_with_a_newer_timestamp(monkeypatch):
    h, fake = make()
    ticks = iter([1000, 1001, 2000])
    monkeypatch.setattr(H, "now_ms", lambda: next(ticks))
    h._arm_will()
    first = h.t_online

    h._on_disconnect(fake, None, None, 0)          # 정상 종료: 그대로
    assert h.t_online == first and len(fake.wills) == 1
    h._on_disconnect(fake, None, None, 7)          # 비정상: 새 timestamp 로 유언 갱신

    assert h.t_online > first and fake.wills[-1][1] == {"online": False, "timestamp": h.t_online}
    assert not h.connected.is_set()


def _filter_matches(pattern: str, topic: str) -> bool:
    p, t = pattern.split("/"), topic.split("/")
    for i, seg in enumerate(p):
        if seg == "#":
            return True
        if i >= len(t) or (seg != "+" and seg != t[i]):
            return False
    return len(p) == len(t)


def test_subscriptions_are_inside_the_acl_allow_list():
    acl = os.path.join(os.path.dirname(H.__file__), "..", "infra", "emqx", "acl.conf")
    text = open(acl, encoding="utf-8").read()
    block = text[text.index('{allow, {username, "host-orch"}, subscribe'):]
    allowed = [s.strip('"') for s in block[:block.index("]}.")].split("[")[1].split(",")]
    h, _ = make()

    for topic, _qos in h.subscriptions():
        probe = topic.replace("#", "NBIRTH/x")
        assert any(_filter_matches(a.strip(), probe) for a in allowed), topic


def test_send_ncmd_encodes_metrics_on_the_node_topic():
    h, fake = make()

    h.send_ncmd("sim-runner-gpu01", [("Run Control/Stop", spb.BOOLEAN, True)])

    topic, payload, qos, retain = fake.pubs[0]
    assert topic == "spBv1.0/santa/NCMD/sim-runner-gpu01" and qos == 0 and retain is False
    assert spb.metrics_by_name(spb.decode(payload)) == {"Run Control/Stop": True}


def test_message_handler_isolates_exceptions():
    h = H.HostClient("host-orch", "pw", "santa", lambda t, p: 1 / 0, threading.RLock())

    class Msg:
        topic, payload = "spBv1.0/santa/NDATA/x", b""

    h._on_message(None, None, Msg())        # 예외가 새면 paho 스레드가 죽는다
