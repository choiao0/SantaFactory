"""edge.spec — Start JSON 파싱 · window_s 유도 · scenario sha 검증."""
import json

import pytest

from edge import spec as S


def test_parses_host_orch_start_and_derives_window_from_timeout():
    scenario = {"seed": 101, "orders": [{"order_id": 1, "ordered_at_s": 0,
                                         "lines": [{"product_id": 7, "rack_id": "A2", "qty": 1}]}]}
    text = json.dumps({"run_id": "verify_77_n3", "scenario_pkg": "wallA_v6", "n_robots": 3, "models": [],
                       "ros_domain_id": 0, "timeout_s": 900, "scenario": scenario,
                       "scenario_sha256": S.scenario_sha256(scenario)})

    spec = S.RunSpec.from_json(text)

    assert spec.run_id == "verify_77_n3" and spec.n_robots == 3 and spec.timeout_s == 900.0
    assert spec.seed == 101
    assert spec.window_s == 600.0                         # timeout_s − START_MARGIN_S(300)
    assert spec.scenario_sha256 == S.scenario_sha256(scenario)


def test_window_floor_and_scenario_override():
    assert S.RunSpec.from_dict({"run_id": "r", "n_robots": 1, "timeout_s": 100}).window_s == S.MIN_WINDOW_S
    spec = S.RunSpec.from_dict({"run_id": "r", "n_robots": 1, "timeout_s": 900, "scenario": {"window_s": 120}})
    assert spec.window_s == 120.0 and spec.seed is None


@pytest.mark.parametrize("bad", [
    {"run_id": "bad id!", "n_robots": 1},
    {"run_id": "r", "n_robots": 0},
    {"run_id": "r", "n_robots": 65},
    {"run_id": "r", "n_robots": True},
    {"run_id": "r", "n_robots": 1, "timeout_s": 0},
    {"run_id": "r", "n_robots": 1, "scenario": "text"},
    {"run_id": "r", "n_robots": 1, "scenario": {"seed": 1}, "scenario_sha256": "0" * 64},
])
def test_rejects_bad_start(bad):
    with pytest.raises(ValueError):
        S.RunSpec.from_dict(bad)


def test_not_json_or_not_object():
    with pytest.raises(ValueError):
        S.RunSpec.from_json("{nope")
    with pytest.raises(ValueError):
        S.RunSpec.from_json("[1]")
