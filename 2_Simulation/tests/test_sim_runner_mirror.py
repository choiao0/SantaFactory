"""sim_runner.mirror — VDA state/connection → Robot/* 델타 · RTF."""
import json
import math

from sim_runner import mirror as M


def state(x=0.0, y=0.0, theta=0.0, battery=100.0, node="", ts="2026-09-08T10:00:00.000Z"):
    return {"timestamp": ts, "lastNodeId": node, "agvPosition": {"x": x, "y": y, "theta": theta},
            "batteryState": {"batteryCharge": battery}}


def test_parse_vda_topic_accepts_only_v2_five_part_topics():
    assert M.parse_vda_topic("uagv/v2/idealworks/amr01/state") == ("idealworks", "amr01", "state")
    assert M.parse_vda_topic("uagv/v1/idealworks/amr01/state") is None
    assert M.parse_vda_topic("spBv1.0/santa/NCMD/sim-runner-gpu01") is None


def test_parse_iso_s_handles_z_suffix_and_garbage():
    assert M.parse_iso_s("1970-01-01T00:00:01.500Z") == 1.5
    assert M.parse_iso_s("not a time") is None
    assert M.parse_iso_s(None) is None


class TestRobotMirror:
    def test_first_state_reports_every_known_metric(self):
        r = M.RobotMirror("amr01", "iw_hub")

        changed = r.update_state(state(1.0, 2.0, 0.5, 90.0, "n1"), wall_s=0.0)

        assert set(changed) == {M.LAST_NODE, M.POSE_X, M.POSE_Y, M.YAW, M.BATTERY}
        assert r.values()[M.POSE_X] == 1.0 and r.values()[M.BATTERY] == 90.0

    def test_small_drift_is_not_reported_until_it_accumulates(self):
        r = M.RobotMirror("amr01")
        r.update_state(state(), 0.0)

        assert r.update_state(state(x=0.03), 0.5) == []
        assert r.update_state(state(x=0.049), 1.0) == []
        assert set(r.update_state(state(x=0.06), 1.5)) == {M.POSE_X, M.POSE_Y}

    def test_pose_delta_reports_x_and_y_together(self):
        r = M.RobotMirror("amr01")
        r.update_state(state(), 0.0)

        assert r.update_state(state(y=0.2), 0.5)[-2:] == [M.POSE_X, M.POSE_Y]

    def test_yaw_threshold_wraps_around_pi(self):
        r = M.RobotMirror("amr01")
        r.update_state(state(theta=math.pi - 0.01), 0.0)

        assert r.update_state(state(theta=-math.pi + 0.01), 0.5) == []
        assert r.update_state(state(theta=-math.pi + 0.06), 1.0) == [M.YAW]

    def test_battery_threshold_is_one_percent(self):
        r = M.RobotMirror("amr01")
        r.update_state(state(battery=80.0), 0.0)

        assert r.update_state(state(battery=79.5), 0.5) == []
        assert r.update_state(state(battery=79.0), 1.0) == [M.BATTERY]

    def test_last_node_id_reports_on_any_change(self):
        r = M.RobotMirror("amr01")
        r.update_state(state(node="a"), 0.0)

        assert r.update_state(state(node="a"), 0.5) == []
        assert r.update_state(state(node="b"), 1.0) == [M.LAST_NODE]

    def test_connection_reports_only_valid_states(self):
        r = M.RobotMirror("amr01")

        assert r.update_connection({"connectionState": "ONLINE"}) == [M.CONNECTION]
        assert r.update_connection({"connectionState": "ONLINE"}) == []
        assert r.update_connection({"connectionState": "BOGUS"}) == []
        assert r.connection == "ONLINE"

    def test_birth_values_include_null_amcl_and_reset_reporting(self):
        r = M.RobotMirror("amr01", "iw_hub")
        r.update_state(state(x=1.0), 0.0)

        v = r.birth_values()

        assert v[M.MODEL] == "iw_hub" and v[M.POSE_X] == 1.0 and v[M.AMCL_ERR] is None
        assert r.update_state(state(x=1.0), 0.5) == []

    def test_rtf_is_sim_time_over_wall_time(self):
        r = M.RobotMirror("amr01")
        for i in range(6):
            sim = f"1970-01-01T00:00:{i * 2:02d}.000Z"
            r.update_state(state(ts=sim), wall_s=float(i))

        assert r.rtf() == 2.0

    def test_rtf_needs_one_second_of_wall_time(self):
        r = M.RobotMirror("amr01")
        r.update_state(state(ts="1970-01-01T00:00:00.000Z"), 0.0)
        r.update_state(state(ts="1970-01-01T00:00:00.500Z"), 0.5)

        assert r.rtf() is None

    def test_missing_fields_keep_previous_values(self):
        r = M.RobotMirror("amr01")
        r.update_state(state(x=1.0, battery=50.0), 0.0)

        r.update_state({"timestamp": "x"}, 0.5)

        assert r.x == 1.0 and r.battery == 50.0


class TestFleet:
    def test_handles_only_known_serials_and_valid_json(self):
        f = M.Fleet([("amr01", "iw_hub")])

        assert f.handle("uagv/v2/idealworks/amr02/state", b"{}", 0.0) is None
        assert f.handle("uagv/v2/idealworks/amr01/state", b"not json", 0.0) is None
        assert f.handle("uagv/v2/idealworks/amr01/state", b"[1]", 0.0) is None
        assert f.handle("uagv/v2/idealworks/amr01/factsheet", b"{}", 0.0) is None
        assert f.handle("uagv/v2/idealworks/amr01/connection",
                        json.dumps({"connectionState": "ONLINE"}).encode(), 0.0) == ("amr01", [M.CONNECTION])

    def test_all_online_and_median_rtf(self):
        f = M.Fleet([("amr01", "iw_hub"), ("amr02", "iw_hub")])
        f.handle("uagv/v2/idealworks/amr01/connection", b'{"connectionState": "ONLINE"}', 0.0)

        assert f.online() == ["amr01"] and f.all_online() is False
        f.handle("uagv/v2/idealworks/amr02/connection", b'{"connectionState": "ONLINE"}', 0.0)
        assert f.all_online() is True
        assert f.rtf() is None
        for i in range(3):
            f.handle("uagv/v2/idealworks/amr01/state", json.dumps(state(ts=f"1970-01-01T00:00:0{i}.000Z")).encode(), i)
        assert f.rtf() == 1.0


def test_non_dict_nested_fields_do_not_crash_and_keep_values():
    r = M.RobotMirror("amr01")
    r.update_state(state(x=1.0, battery=50.0), 0.0)

    changed = r.update_state({"agvPosition": 1, "batteryState": "x", "lastNodeId": 5, "timestamp": 3}, 0.5)

    assert changed == [] and r.x == 1.0 and r.battery == 50.0 and r.last_node_id == ""
