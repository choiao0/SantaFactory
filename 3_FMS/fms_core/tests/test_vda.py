"""fms_core.vda — order 스티칭 규약(t4_agent OrderBook 이 오라클) · state 거울 · 도착/재발행 판정 · Fleet 토픽 배분."""
import json
import math

import pytest

from fms_core import vda as V
from fms_core.tests.fakes import vda_connection, vda_state

t4 = pytest.importorskip("amr_agent.vda5050.order", reason="t4_agent not in this checkout")


def link(serial="amr01"):
    return V.RobotLink(serial, "idealworks", f"run-{serial}", map_id="wallA")


class TestOrderBuilding:
    def test_initial_order_is_current_pose_only(self):
        lk = link()
        msg = lk.initial_order(36.0, 40.8, 0.2, now=1.0)
        assert msg["orderId"] == "run-amr01" and msg["orderUpdateId"] == 0 and msg["edges"] == []
        n0 = msg["nodes"][0]
        assert (n0["nodeId"], n0["sequenceId"], n0["released"]) == ("n0", 0, True)
        assert n0["nodePosition"] == {"x": 36.0, "y": 40.8, "theta": 0.0, "mapId": "wallA",
                                      "allowedDeviationXY": V.DEV_XY_M, "allowedDeviationTheta": V.DEV_THETA_RAD}
        assert lk.pending is None and lk.k == 0 and msg["headerId"] == 1 and msg["version"] == "2.0.0"

    def test_next_orders_stitch_from_last_node(self):
        lk = link()
        lk.initial_order(36.1, 40.5, 0.0, 1.0)
        m1 = lk.next_order(37.1, 40.5, 0.0, False, 2.0)            # 전진 1 m
        m2 = lk.next_order(37.1, 40.5, math.pi / 2, False, 3.0)    # 제자리 회전
        m3 = lk.next_order(37.1, 39.5, math.pi / 2, True, 4.0)     # 후진
        for k, m in ((1, m1), (2, m2), (3, m3)):
            assert m["orderUpdateId"] == k
            assert [n["nodeId"] for n in m["nodes"]] == [f"n{k - 1}", f"n{k}"]
            assert [n["sequenceId"] for n in m["nodes"]] == [2 * (k - 1), 2 * k]
            e = m["edges"][0]
            assert (e["edgeId"], e["sequenceId"], e["startNodeId"], e["endNodeId"]) == (f"e{k - 1}", 2 * k - 1, f"n{k - 1}", f"n{k}")
        assert m1["edges"][0]["length"] == 1.0 and "orientation" not in m1["edges"][0]
        assert m2["edges"][0]["length"] == 0.0
        assert m3["edges"][0]["orientation"] == pytest.approx(math.pi)
        assert lk.pending == 3 and lk.k == 3

    def test_t4_orderbook_accepts_the_sequence(self):
        """에이전트 OrderBook: 첫 order 'started', 갱신 'stitched', 재발행 'duplicate', 전부 validate 통과."""
        lk = link()
        book = t4.OrderBook()
        o0 = t4.Order.from_dict(lk.initial_order(36.0, 40.8, 0.1, 1.0))
        assert book.receive(o0, at_xy=(36.0, 40.8)) == "started"
        o1 = t4.Order.from_dict(lk.next_order(36.1, 40.5, 0.0, False, 2.0))
        assert book.receive(o1) == "stitched"
        o2 = t4.Order.from_dict(lk.next_order(37.1, 40.5, 0.0, False, 3.0))
        assert book.receive(o2) == "stitched"
        dup = t4.Order.from_dict(lk.resend(4.0))
        assert book.receive(dup) == "duplicate"
        assert [n.node_id for n in book.order.nodes] == ["n0", "n1", "n2"] and book.order.base_len() == 3
        assert book.order.edges[1].is_reverse() is False
        rev = t4.Order.from_dict(lk.next_order(36.1, 40.5, 0.0, True, 5.0))
        assert book.receive(rev) == "stitched" and book.order.edges[2].is_reverse()

    def test_resend_keeps_update_id_but_new_header(self):
        lk = link()
        lk.initial_order(0, 0, 0, 1.0)
        m = lk.next_order(1.0, 0.0, 0.0, False, 2.0)
        stale = json.loads(vda_state("amr01", 0, 0, 0, node="n0", order_id="run-amr01", update=0)[1])
        lk.on_state(stale, 2.1)
        lk.on_state(stale, 2.2)
        r = lk.resend(3.0)
        assert r["orderUpdateId"] == m["orderUpdateId"] and r["headerId"] == m["headerId"] + 1
        assert r["nodes"] == m["nodes"] and lk.resends == 1
        assert lk.states_since_send == 2 and lk.sent_at == 2.0, "재발행은 카운터·전송 시각을 되돌리지 않는다"

    def test_cancel_order_action(self):
        lk = link()
        a = lk.cancel_order()
        assert a["actions"] == [{"actionType": "cancelOrder", "actionId": "cancel-1", "blockingType": "HARD"}]
        assert a["serialNumber"] == "amr01"


class TestObservation:
    def test_state_mirror_and_arrival(self):
        lk = link()
        lk.initial_order(0, 0, 0, 1.0)
        lk.next_order(1.0, 0.0, 0.0, False, 2.0)
        _, payload = vda_state("amr01", 0.5, 0.0, 0.0, node="n0", order_id="run-amr01", update=1)
        lk.on_state(json.loads(payload), 2.5)
        assert lk.reflected and not lk.arrived and lk.states_since_send == 1 and lk.x == 0.5
        _, payload = vda_state("amr01", 1.0, 0.0, 0.0, node="n1", order_id="run-amr01", update=1)
        lk.on_state(json.loads(payload), 3.0)
        assert lk.arrived
        lk.settle()
        assert lk.pending is None and lk.states_since_send == 0 and lk.reflected

    def test_foreign_order_id_does_not_reflect(self):
        lk = link()
        lk.initial_order(0, 0, 0, 1.0)
        lk.next_order(1.0, 0.0, 0.0, False, 2.0)
        _, payload = vda_state("amr01", 0, 0, 0, node="n1", order_id="other", update=9)
        lk.on_state(json.loads(payload), 2.5)
        assert not lk.reflected and not lk.arrived

    def test_resend_and_error_thresholds(self):
        lk = link()
        lk.initial_order(0, 0, 0, 1.0)
        lk.next_order(1.0, 0.0, 0.0, False, 2.0)
        stale = json.loads(vda_state("amr01", 0, 0, 0, node="n0", order_id="run-amr01", update=0)[1])
        lk.on_state(stale, 2.1)
        assert not lk.resend_due()
        lk.on_state(stale, 2.2)
        assert lk.resend_due() and not lk.unreflected_error()
        lk.resend(2.3)
        assert not lk.resend_due()
        resends = 0
        for i in range(V.ERROR_AFTER_STATES):                     # tick 이 끼어드는 실운영 순서: state → 판정 → (재발행)
            lk.on_state(stale, 3 + i)
            if lk.unreflected_error():
                break
            if lk.resend_due():
                lk.resend(3 + i)
                resends += 1
        assert lk.unreflected_error() and lk.states_since_send == V.ERROR_AFTER_STATES and resends == 3

    @pytest.mark.parametrize("errors,fatal", [
        ([], None), ([{"errorType": "validationError", "errorLevel": "WARNING"}], None),
        ([{"errorType": "primitiveError", "errorLevel": "FATAL", "errorDescription": "timeout"}], "primitiveError: timeout"),
        ([{"errorType": "orderError", "errorLevel": "WARNING", "errorDescription": "still active"}], "orderError: still active"),
        ([{"errorType": "orderUpdateError", "errorLevel": "WARNING"}], "orderUpdateError: ")])
    def test_fatal_error_classification(self, errors, fatal):
        lk = link()
        lk.on_state({"errors": errors}, 1.0)
        assert lk.fatal_error() == fatal

    def test_connection(self):
        lk = link()
        lk.on_connection({"connectionState": "ONLINE"})
        assert lk.online
        lk.on_connection({"connectionState": "weird"})
        assert lk.online
        lk.on_connection({"connectionState": "CONNECTIONBROKEN"})
        assert not lk.online and lk.connection == "CONNECTIONBROKEN"


class TestFleet:
    def test_routes_known_serials_only(self):
        f = V.Fleet([("amr01", "idealworks"), ("amr02", "idealworks")], "run-1")
        assert f.robots["amr02"].order_id == "run-1-amr02"
        assert f.handle(*vda_connection("amr01"))[:2] == ("amr01", "connection")
        assert f.handle(*vda_state("amr02", 1, 2, 0))[:2] == ("amr02", "state")
        assert f.handle(*vda_state("amr09", 1, 2, 0)) is None
        assert f.handle("uagv/v2/idealworks/amr01/factsheet", b"{}") is None
        assert f.handle("uagv/v2/idealworks/amr01/state", b"{nope") is None
        assert f.handle("uagv/v2/idealworks/amr01/state", b"[1]") is None

    def test_all_ready_needs_online_and_pose(self):
        f = V.Fleet([("amr01", "idealworks")], "run-1")
        assert not f.all_ready() and f.online() == 0
        f.robots["amr01"].on_connection({"connectionState": "ONLINE"})
        assert not f.all_ready() and f.online() == 1
        f.robots["amr01"].on_state(json.loads(vda_state("amr01", 1, 2, 0)[1]), 1.0)
        assert f.all_ready()
