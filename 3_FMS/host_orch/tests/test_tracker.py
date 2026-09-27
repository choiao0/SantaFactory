"""host_orch.tracker — NBIRTH/NDATA/DBIRTH/DDATA/DDEATH/NDEATH · seq/bdSeq · Rebirth 요청 조건."""
from host_orch import spb
from host_orch import tracker as T

BD = spb.MetricDef("bdSeq", spb.INT64, 0)
STATE = spb.MetricDef("Runner/State", spb.STRING, 2)
RUN_ID = spb.MetricDef("Runner/RunId", spb.STRING, 3)
HB = spb.MetricDef("Runner/Heartbeat", spb.INT64, 4)
MODEL = spb.MetricDef("Robot/Model", spb.STRING, 100)
POSE_X = spb.MetricDef("Robot/PoseX", spb.DOUBLE, 103)
N = "spBv1.0/santa/NBIRTH/sim-runner-gpu01"
ND = "spBv1.0/santa/NDATA/sim-runner-gpu01"
DEATH = "spBv1.0/santa/NDEATH/sim-runner-gpu01"


def birth(tr, bd=3, now=0.0):
    return tr.handle(N, spb.encode_birth(0, [(BD, bd), (STATE, "IDLE"), (RUN_ID, ""), (HB, 0)]), now)


def test_parse_topic_needs_group_and_kind_node():
    assert T.parse_topic("spBv1.0/santa/DBIRTH/sim-runner-gpu01/amr01", "santa") == ("DBIRTH", "sim-runner-gpu01", "amr01")
    assert T.parse_topic("spBv1.0/other/NBIRTH/x", "santa") is None
    assert T.parse_topic("spBv1.0/STATE/host-orch", "santa") is None


def test_nbirth_resets_node_and_records_bdseq_and_aliases():
    tr = T.HostTracker()

    events = birth(tr, bd=7, now=1.0)

    n = tr.node("sim-runner-gpu01")
    assert events == [T.Event("nbirth", "sim-runner-gpu01")]
    assert n.online and n.bd_seq == 7 and n.seq == 0 and n.last_seen == 1.0
    assert n.get("Runner/State") == "IDLE" and n.aliases[2] == "Runner/State"


def test_ndata_resolves_alias_only_metrics_and_tracks_seq():
    tr = T.HostTracker()
    birth(tr)
    p = spb.Payload(timestamp=1, seq=1)
    m = p.metrics.add()
    m.alias, m.string_value = 2, "RUNNING"

    events = tr.handle(ND, p.SerializeToString(), 2.0)

    assert events == [T.Event("ndata", "sim-runner-gpu01", changed=("Runner/State",))]
    assert tr.node("sim-runner-gpu01").get("Runner/State") == "RUNNING" and tr.node("sim-runner-gpu01").seq == 1


def test_seq_gap_flags_rebirth_but_still_applies_data():
    tr = T.HostTracker()
    birth(tr)

    events = tr.handle(ND, spb.encode_data(5, [(STATE, "STARTING")]), 2.0)

    assert [e.kind for e in events] == ["seq_gap", "ndata"]
    n = tr.node("sim-runner-gpu01")
    assert n.needs_rebirth and n.get("Runner/State") == "STARTING" and n.seq == 5


def test_seq_wraps_255_to_0_without_gap():
    tr = T.HostTracker()
    birth(tr)
    tr.node("sim-runner-gpu01").seq = 255

    events = tr.handle(ND, spb.encode_data(0, [(HB, 1)]), 2.0)

    assert [e.kind for e in events] == ["ndata"]


def test_ndeath_with_matching_bdseq_marks_offline_and_devices_stale():
    tr = T.HostTracker()
    birth(tr, bd=3)
    tr.handle("spBv1.0/santa/DBIRTH/sim-runner-gpu01/amr01", spb.encode_birth(1, [(MODEL, "iw_hub")]), 1.0)

    assert tr.handle(DEATH, spb.encode_death(2), 2.0) == [T.Event("stale_death", "sim-runner-gpu01")]
    assert tr.node("sim-runner-gpu01").online
    assert tr.handle(DEATH, spb.encode_death(3), 3.0) == [T.Event("ndeath", "sim-runner-gpu01")]
    n = tr.node("sim-runner-gpu01")
    assert not n.online and n.alive_devices() == [] and n.devices["amr01"].alive is False


def test_device_birth_data_death():
    tr = T.HostTracker()
    birth(tr)

    e1 = tr.handle("spBv1.0/santa/DBIRTH/sim-runner-gpu01/amr01", spb.encode_birth(1, [(MODEL, "iw_hub"), (POSE_X, None)]), 1.0)
    e2 = tr.handle("spBv1.0/santa/DDATA/sim-runner-gpu01/amr01", spb.encode_data(2, [(POSE_X, 1.5)]), 2.0)
    e3 = tr.handle("spBv1.0/santa/DDEATH/sim-runner-gpu01/amr01", spb.encode_ddeath(3), 3.0)

    n = tr.node("sim-runner-gpu01")
    assert e1[0].kind == "dbirth" and e2[0].kind == "ddata" and e3[0].kind == "ddeath"
    assert n.devices["amr01"].metrics == {"Robot/Model": "iw_hub", "Robot/PoseX": 1.5}
    assert n.alive_devices() == []


def test_data_before_birth_asks_for_rebirth_once_per_interval():
    tr = T.HostTracker()

    events = tr.handle(ND, spb.encode_data(4, [(STATE, "IDLE")]), 10.0)

    assert events == [T.Event("unknown_node", "sim-runner-gpu01")]
    assert tr.rebirth_due("sim-runner-gpu01", 10.0) is True
    assert tr.rebirth_due("sim-runner-gpu01", 12.0) is False
    assert tr.rebirth_due("sim-runner-gpu01", 16.0) is True
    birth(tr, now=17.0)
    assert tr.rebirth_due("sim-runner-gpu01", 30.0) is False


def test_commands_and_garbage_are_ignored():
    tr = T.HostTracker()
    birth(tr)

    assert tr.handle("spBv1.0/santa/NCMD/sim-runner-gpu01", spb.encode_cmd([("Run Control/Stop", spb.BOOLEAN, True)]), 1.0) == []
    assert tr.handle(ND, b"\xff\xff\xff", 1.0) == []
