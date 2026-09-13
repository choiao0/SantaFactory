import json

from amr_agent.vda5050.order import Edge, Node, NodePosition, Order, OrderBook
from amr_agent.vda5050.state import StateBuilder, make_error


def test_state_shape_and_progress():
    b = OrderBook()
    o = Order("o1", 0, (Node("n0", 0, True, NodePosition(0, 0)), Node("n1", 2, True, NodePosition(1, 0))),
              (Edge("e0", 1, True, "n0", "n1"),))
    b.receive(o)
    sb = StateBuilder("santa", "amr01", "wallA")
    s = sb.state(b, (0.0, 0.0, 0.0), driving=True, errors=[make_error("x", "y")])
    json.dumps(s)
    assert s["headerId"] == 1 and s["serialNumber"] == "amr01" and s["version"] == "2.0.0"
    assert s["lastNodeId"] == "n0" and [n["nodeId"] for n in s["nodeStates"]] == ["n1"]
    assert s["agvPosition"]["mapId"] == "wallA" and s["driving"] and s["errors"][0]["errorType"] == "x"
    b.node_reached()
    s2 = sb.state(b, None)
    assert s2["headerId"] == 2 and s2["lastNodeId"] == "n1" and s2["nodeStates"] == [] and "agvPosition" not in s2
    assert sb.connection("ONLINE")["connectionState"] == "ONLINE"


def test_factsheet_from_model_profile():
    from amr_agent.vda5050.models import load_model_profile
    from amr_agent.vda5050.state import StateBuilder
    p = load_model_profile("iw_hub")
    fs = StateBuilder("idealworks", "amr01").factsheet(p)
    assert fs["manufacturer"] == "idealworks" and fs["serialNumber"] == "amr01" and fs["version"] == "2.0.0"
    ts, pp, geo = fs["typeSpecification"], fs["physicalParameters"], fs["agvGeometry"]
    assert ts["seriesName"] == "iw.hub" and ts["agvKinematic"] == "DIFF" and ts["agvClass"] == "CARRIER"
    assert pp["speedMax"] == 0.8 and pp["length"] == 1.43 and pp["width"] == 0.66 and pp["heightMax"] == 0.41
    assert fs["protocolLimits"]["timing"]["defaultStateInterval"] == 0.5
    drive = [w for w in geo["wheelDefinitions"] if w["type"] == "DRIVE"]
    assert len(drive) == 2 and {w["position"]["y"] for w in drive} == {0.29, -0.29} and drive[0]["diameter"] == 0.16
    sets = {e["set"]: e["polygonPoints"] for e in geo["envelopes2d"]}
    assert sets["footprint"][0] == {"x": 0.4, "y": 0.33} and sets["footprint"][1]["x"] == -1.03
    assert len(sets["swing"]) == 12 and abs(sets["swing"][0]["x"] - 1.09) < 1e-6
    assert [a["actionType"] for a in fs["protocolFeatures"]["agvActions"]] == ["cancelOrder"]


def test_model_profile_missing_key_raises(tmp_path):
    from amr_agent.vda5050.models import ModelProfileError, load_model_profile
    bad = tmp_path / "x.yaml"
    bad.write_text("model: x\n")
    import pytest
    with pytest.raises(ModelProfileError):
        load_model_profile("x", str(bad))
