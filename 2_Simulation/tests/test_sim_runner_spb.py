"""sim_runner.spb — Sparkplug B 코덱 · EdgeSession (MQTT_CONTRACT §5.4)."""
import os

import pytest

from sim_runner import spb

BD = spb.MetricDef("bdSeq", spb.INT64, 0)
REBIRTH = spb.MetricDef("Node Control/Rebirth", spb.BOOLEAN, 1)
STATE = spb.MetricDef("Runner/State", spb.STRING, 2)
RTF = spb.MetricDef("Runner/RTF", spb.DOUBLE, 3)
RAM = spb.MetricDef("Runner/RamMB", spb.INT32, 4)
START = spb.MetricDef("Run Control/Start", spb.TEXT, 5)
AMCL = spb.MetricDef("Robot/AmclErr", spb.DOUBLE, 6)


def test_birth_roundtrip_keeps_name_alias_type_and_value():
    raw = spb.encode_birth(0, [(BD, 7), (REBIRTH, False), (STATE, "IDLE"), (RTF, 1.25), (RAM, 512), (START, "")], ts=1000)

    d = spb.decode(raw)

    assert d.seq == 0 and d.timestamp == 1000
    assert [m.name for m in d.metrics] == ["bdSeq", "Node Control/Rebirth", "Runner/State", "Runner/RTF",
                                            "Runner/RamMB", "Run Control/Start"]
    assert [m.alias for m in d.metrics] == [0, 1, 2, 3, 4, 5]
    assert [m.value for m in d.metrics] == [7, False, "IDLE", 1.25, 512, ""]
    assert [m.datatype for m in spb.Payload.FromString(raw).metrics] == [spb.INT64, spb.BOOLEAN, spb.STRING,
                                                                          spb.DOUBLE, spb.INT32, spb.TEXT]


def test_birth_declares_optional_metric_as_null():
    d = spb.decode(spb.encode_birth(3, [(AMCL, None)]))

    assert d.metrics[0].name == "Robot/AmclErr"
    assert d.metrics[0].value is None
    assert spb.Payload.FromString(spb.encode_birth(3, [(AMCL, None)])).metrics[0].is_null is True


def test_data_carries_alias_and_name_without_type():
    raw = spb.encode_data(9, [(RTF, 0.5)])

    p = spb.Payload.FromString(raw)
    d = spb.decode(raw)

    assert p.seq == 9
    assert p.metrics[0].HasField("datatype") is False
    assert d.metrics[0].alias == 3 and d.metrics[0].name == "Runner/RTF" and d.metrics[0].value == 0.5


def test_death_has_only_bdseq_and_no_seq():
    d = spb.decode(spb.encode_death(300))

    assert d.seq is None
    assert spb.metrics_by_name(d) == {"bdSeq": 300 % 256}


def test_ddeath_has_seq_and_no_metrics():
    d = spb.decode(spb.encode_ddeath(17))

    assert d.seq == 17 and d.metrics == ()


def test_cmd_roundtrip_json_text_and_boolean():
    d = spb.decode(spb.encode_cmd([("Run Control/Start", spb.TEXT, '{"run_id": "r1"}'),
                                   ("Run Control/Stop", spb.BOOLEAN, True)]))

    assert d.seq is None
    assert spb.metrics_by_name(d) == {"Run Control/Start": '{"run_id": "r1"}', "Run Control/Stop": True}


def test_negative_int_is_two_s_complement_on_the_wire():
    p = spb.Payload.FromString(spb.encode_data(0, [(RAM, -1)]))

    assert p.metrics[0].int_value == 0xFFFF_FFFF


class TestEdgeSession:
    def test_first_session_is_bdseq_zero_and_persists(self, tmp_path):
        path = str(tmp_path / "state" / "bdseq")

        s = spb.EdgeSession(path)
        bd = s.new_session()

        assert bd == 0
        assert open(path).read() == "0"

    def test_restart_continues_bdseq_from_file(self, tmp_path):
        path = str(tmp_path / "bdseq")
        spb.EdgeSession(path).new_session()

        s = spb.EdgeSession(path)

        assert s.new_session() == 1
        assert s.new_session() == 2

    def test_bdseq_wraps_at_256(self, tmp_path):
        path = str(tmp_path / "bdseq")
        with open(path, "w") as f:
            f.write("255")

        assert spb.EdgeSession(path).new_session() == 0

    def test_seq_starts_at_zero_after_new_session_and_wraps(self, tmp_path):
        s = spb.EdgeSession(str(tmp_path / "bdseq"))
        s.new_session()
        s.seq = 255

        assert s.next_seq() == 255
        assert s.next_seq() == 0
        s.new_session()
        assert s.next_seq() == 0

    def test_corrupt_file_starts_over_at_zero(self, tmp_path):
        path = str(tmp_path / "bdseq")
        with open(path, "w") as f:
            f.write("junk")

        assert spb.EdgeSession(path).new_session() == 0
        assert os.path.exists(path + ".tmp") is False


@pytest.mark.parametrize("dtype,value,expected", [(spb.INT32, 5.9, 5), (spb.DOUBLE, 3, 3.0),
                                                  (spb.BOOLEAN, 1, True), (spb.STRING, 12, "12")])
def test_values_are_cast_to_declared_type(dtype, value, expected):
    d = spb.decode(spb.encode_birth(0, [(spb.MetricDef("m", dtype, 1), value)]))

    assert d.metrics[0].value == expected and type(d.metrics[0].value) is type(expected)
