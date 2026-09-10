"""fms_core 테스트 공용 가짜: publisher(토픽별 해석) · 완벽한 로봇(명령 노드에 즉시 도착) · Start 페이로드."""
import json

from fms_core import spb
from fms_core.conductor import CMD_START, CMD_STOP, REBIRTH


class FakePublisher:
    """Sparkplug 는 디코드해서, JSON 토픽은 dict 로 보관."""

    def __init__(self):
        self.msgs = []      # (topic, decoded|dict, qos, retain)

    def publish(self, topic, payload, qos=0, retain=False):
        body = spb.decode(payload) if topic.startswith("spBv1.0/") else json.loads(payload)
        self.msgs.append((topic, body, qos, retain))

    def by_topic(self, prefix):
        return [(t, b) for t, b, *_ in self.msgs if t.startswith(prefix)]

    def kinds(self):
        return [t.split("/")[2] for t, *_ in self.msgs if t.startswith("spBv1.0/")]

    def named(self, kind):
        d = next((b for t, b, *_ in reversed(self.msgs) if t.startswith("spBv1.0/") and t.split("/")[2] == kind), None)
        return spb.metrics_by_name(d) if d else None

    def values(self):
        """NBIRTH 뒤 NDATA 를 순서대로 겹친 노드 메트릭 (마지막 NDATA 가 하트비트뿐이어도 상태를 본다)."""
        out = {}
        for t, b, *_ in self.msgs:
            if t.startswith("spBv1.0/") and t.split("/")[2] in ("NBIRTH", "NDATA"):
                out.update(spb.metrics_by_name(b))
        return out

    def orders(self, serial=None):
        return [b for t, b in self.by_topic("uagv/v2/") if t.endswith("/order") and (serial is None or f"/{serial}/" in t)]

    def actions(self, serial=None):
        return [b for t, b in self.by_topic("uagv/v2/") if t.endswith("/instantActions") and (serial is None or f"/{serial}/" in t)]

    def events(self, kind=None):
        return [b for t, b in self.by_topic("biz/v1/event") if kind is None or b["type"] == kind]

    def clear(self):
        self.msgs.clear()


def start_payload(run_id="run-1", n=2, timeout_s=600, scenario=None, **over):
    d = {"run_id": run_id, "scenario_pkg": "pkg", "n_robots": n, "models": [], "ros_domain_id": 0, "timeout_s": timeout_s}
    if scenario is not None:
        d["scenario"] = scenario
    d.update(over)
    return json.dumps(d)


def ncmd(**metrics):
    types = {CMD_START: spb.TEXT, CMD_STOP: spb.BOOLEAN, REBIRTH: spb.BOOLEAN}
    return spb.encode_cmd([(name, types[name], v) for name, v in metrics.items()])


def vda_connection(serial, state="ONLINE", mfr="idealworks"):
    return f"uagv/v2/{mfr}/{serial}/connection", json.dumps({"connectionState": state}).encode()


def vda_state(serial, x=0.0, y=0.0, theta=0.0, node="", order_id="", update=0, errors=(), mfr="idealworks"):
    msg = {"timestamp": "2026-09-09T10:00:00.000Z", "orderId": order_id, "orderUpdateId": update, "lastNodeId": node,
           "agvPosition": {"x": x, "y": y, "theta": theta, "mapId": "wallA"}, "errors": list(errors)}
    return f"uagv/v2/{mfr}/{serial}/state", json.dumps(msg).encode()


class PerfectRobots:
    """발행된 order 를 받아 다음 deliver() 때 마지막 노드에 도착한 state 를 낸다 (에이전트 stop 허용 안 = 정확히 노드 좌표)."""

    def __init__(self, conductor, pub, serials, poses):
        self.c, self.pub, self.serials = conductor, pub, serials
        self.pose = dict(zip(serials, poses))          # serial → (x, y, theta)
        self.seen = 0
        self.inbox = {}                                # serial → 마지막 order

    def take_orders(self):
        for t, b, *_ in self.pub.msgs[self.seen:]:
            if t.startswith("uagv/v2/") and t.endswith("/order"):
                self.inbox[t.split("/")[3]] = b
        self.seen = len(self.pub.msgs)

    def deliver(self, now, serials=None):
        """받은 order 마다 마지막 노드에 도착한 state 를 conductor 에 넣는다."""
        self.take_orders()
        for serial in serials or list(self.inbox):
            o = self.inbox.pop(serial, None)
            if o is None:
                continue
            n = o["nodes"][-1]["nodePosition"]
            self.pose[serial] = (n["x"], n["y"], n["theta"])
            self.c.on_vda(*vda_state(serial, n["x"], n["y"], n["theta"], o["nodes"][-1]["nodeId"], o["orderId"],
                                     o["orderUpdateId"]), now)

    def idle_state(self, now, serial, update=None, node=""):
        """주문 갱신 없이 현재 포즈 state 만 (재발행 규칙 검사용). update 를 주면 그 로봇의 orderId 로 보고한다."""
        x, y, th = self.pose[serial]
        order_id = self.c.fleet.robots[serial].order_id if update is not None else ""
        self.c.on_vda(*vda_state(serial, x, y, th, node, order_id, -1 if update is None else update), now)
