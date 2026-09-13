"""profile.resolve_profile — 세 층(기종 yaml < profile_file < profile_overrides), BE 키 번역, 거절 규칙, 파생값."""
import json
import pathlib

import pytest

from amr_agent import profile as P
from amr_agent.control.primitives import Gains, Limits
from amr_agent.vda5050.state import StateBuilder

BE_BLOCK = {"speed_empty": 1.2, "speed_loaded": 1.0, "consumption": 0.02, "battery": 100.0,
            "charge_time": 3600, "charge_threshold": 0.2, "capacity": 6, "tote_units": 8}


def test_defaults_come_from_model_yaml_and_section_defaults():
    p = P.resolve_profile("iw_hub")

    assert p["v_max"] == 0.8 and p["v_max_loaded"] == 0.8 and p["a_max"] == 1.0
    assert p["control"]["rate_hz"] == 20.0 and p["control"]["tol_xy"] == 0.05
    assert p["battery"]["consumption_pct_per_s"] == 0.0 and p["battery"]["soc_init_pct"] == 100.0
    assert p["load"] == {"capacity_totes": 6, "tote_units": 8}
    assert p["plant"]["a_max"] == 6.0 and p["plant"]["v_max"] == 0.835


def test_be_keys_translate_to_profile_paths():
    p = P.resolve_profile("iw_hub", profile_overrides=json.dumps(BE_BLOCK))

    assert p["v_max"] == 1.2 and p["v_max_loaded"] == 1.0
    assert p["battery"]["consumption_pct_per_s"] == 0.02 and p["battery"]["soc_init_pct"] == 100.0
    assert p["battery"]["charge_time_s"] == 3600.0 and p["battery"]["charge_threshold_pct"] == 20.0
    assert p["load"] == {"capacity_totes": 6, "tote_units": 8}


def test_ratio_and_percent_both_accepted_for_battery_fields():
    a = P.resolve_profile("iw_hub", profile_overrides='{"battery": 0.75, "charge_threshold": 30}')

    assert a["battery"]["soc_init_pct"] == 75.0 and a["battery"]["charge_threshold_pct"] == 30.0


def test_pct_boundary_one_is_percent_not_ratio():
    a = P.resolve_profile("iw_hub", profile_overrides='{"charge_threshold": 1, "battery": 1.0}')

    assert a["battery"]["charge_threshold_pct"] == 1.0 and a["battery"]["soc_init_pct"] == 1.0


def test_battery_section_override_is_a_section_when_given_as_mapping():
    a = P.resolve_profile("iw_hub", profile_overrides='{"battery": {"idle_ratio": 0.5}, "consumption": 0.01}')

    assert a["battery"]["idle_ratio"] == 0.5 and a["battery"]["consumption_pct_per_s"] == 0.01
    assert a["battery"]["soc_init_pct"] == 100.0
    with pytest.raises(P.ProfileError, match="both given"):
        P.resolve_profile("iw_hub", profile_overrides='{"consumption": 0.01, "battery": {"consumption_pct_per_s": 0.02}}')


def test_wheels_override_is_validated_before_factsheet():
    for bad in ('{"wheels": "oops"}', '{"wheels": []}', '{"wheels": [{"type": "DRIVE"}]}',
                '{"wheels": [{"type": "DRIVE", "is_active_driven": true, "is_active_steered": false, '
                '"position": {"x": 0}, "diameter": 0.16, "width": 0.05}]}'):
        with pytest.raises(P.ProfileError, match="wheels"):
            P.resolve_profile("iw_hub", profile_overrides=bad)


def test_integer_be_keys_reject_fractions():
    with pytest.raises(P.ProfileError, match="bad value"):
        P.resolve_profile("iw_hub", profile_overrides='{"capacity": 5.9}')
    assert P.resolve_profile("iw_hub", profile_overrides='{"tote_units": 4.0}')["load"]["tote_units"] == 4


def _model_yaml(tmp_path, patch: str):
    src = pathlib.Path(P.load_model_profile.__globals__["models_dir"]()) / "iw_hub.yaml"
    f = tmp_path / "custom.yaml"
    f.write_text(src.read_text(encoding="utf-8") + "\n" + patch, encoding="utf-8")
    return str(f)


def test_model_yaml_section_must_be_a_mapping(tmp_path):
    with pytest.raises(P.ProfileError, match="model yaml section battery must be a mapping"):
        P.resolve_profile("custom", model_path=_model_yaml(tmp_path, "battery: oops\n"))


def test_model_yaml_extra_section_key_is_overridable(tmp_path):
    path = _model_yaml(tmp_path, "control:\n  rate_hz: 20.0\n  extra_gain: 1.0\n")

    p = P.resolve_profile("custom", model_path=path, profile_overrides='{"control": {"extra_gain": 2.0}}')

    assert p["control"]["extra_gain"] == 2.0 and p["control"]["tol_xy"] == 0.05


def test_file_then_inline_precedence(tmp_path):
    f = tmp_path / "amr.yaml"
    f.write_text("speed_empty: 0.9\ncontrol:\n  tol_xy: 0.08\n", encoding="utf-8")

    p = P.resolve_profile("iw_hub", profile_file=str(f), profile_overrides='{"speed_empty": 1.1}')

    assert p["v_max"] == 1.1                      # inline beats file
    assert p["control"]["tol_xy"] == 0.08         # file beats model yaml
    assert p["control"]["tol_theta"] == 0.03      # untouched section keys survive


def test_json_profile_file_accepted(tmp_path):
    f = tmp_path / "amr.json"
    f.write_text(json.dumps({"capacity": 3, "plant": {"a_max": 3.0}}), encoding="utf-8")

    p = P.resolve_profile("iw_hub", profile_file=str(f))

    assert p["load"]["capacity_totes"] == 3 and p["plant"]["a_max"] == 3.0


def test_unknown_key_is_rejected():
    with pytest.raises(P.ProfileError, match="unknown profile keys"):
        P.resolve_profile("iw_hub", profile_overrides='{"speed_max": 1.0}')
    with pytest.raises(P.ProfileError, match="unknown keys in control"):
        P.resolve_profile("iw_hub", profile_overrides='{"control": {"tol_z": 1.0}}')


def test_be_key_and_its_target_together_are_rejected():
    with pytest.raises(P.ProfileError, match="both given"):
        P.resolve_profile("iw_hub", profile_overrides='{"speed_empty": 1.0, "v_max": 1.0}')
    with pytest.raises(P.ProfileError, match="both given"):
        P.resolve_profile("iw_hub", profile_overrides='{"capacity": 2, "load": {"capacity_totes": 2}}')


@pytest.mark.parametrize("bad", ['{"speed_empty": 0}', '{"capacity": 7}', '{"charge_threshold": 150}',
                                 '{"v_min": 2.0}', '{"control": {"rate_hz": 0}}', '{"consumption": -1}'])
def test_out_of_range_values_are_rejected(bad):
    with pytest.raises(P.ProfileError, match="out of range"):
        P.resolve_profile("iw_hub", profile_overrides=bad)


def test_missing_model_and_bad_inputs_raise_profile_error(tmp_path):
    with pytest.raises(P.ProfileError, match="model profile not found"):
        P.resolve_profile("no_such_model")
    with pytest.raises(P.ProfileError, match="not found"):
        P.resolve_profile("iw_hub", profile_file=str(tmp_path / "missing.yaml"))
    with pytest.raises(P.ProfileError, match="not JSON"):
        P.resolve_profile("iw_hub", profile_overrides="{speed_empty: 1}")
    with pytest.raises(P.ProfileError, match="must be a mapping"):
        P.resolve_profile("iw_hub", profile_overrides="[1, 2]")


def test_factsheet_reflects_override():
    p = P.resolve_profile("iw_hub", profile_overrides='{"speed_empty": 1.2}')

    fs = StateBuilder("idealworks", "amr01").factsheet(p)

    assert fs["physicalParameters"]["speedMax"] == 1.2
    assert fs["protocolLimits"]["timing"]["minStateInterval"] == 0.5


def test_derived_values_feed_controller_and_executor():
    p = P.resolve_profile("iw_hub", profile_overrides='{"speed_empty": 1.2, "w_max": 1.5}')

    lim, g = Limits(**P.limits(p)), Gains(**P.gains(p))

    assert lim.v_max == 1.2 and lim.w_max == 1.5 and lim.a_max == 1.0 and lim.v_min == 0.05
    assert g.k_turn == 2.5
    assert P.state_rate_hz(p) == 2.0
    assert "v_max=1.2" in P.summary(p) and "soc=100.0%" in P.summary(p)


def test_inputs_are_not_mutated():
    base = P.with_defaults(P.load_model_profile("iw_hub"))
    snapshot = json.dumps(base, sort_keys=True)
    overrides = {"speed_empty": 1.2, "control": {"tol_xy": 0.1}}

    P.validate(P.apply_overrides(base, overrides))

    assert json.dumps(base, sort_keys=True) == snapshot
    assert overrides == {"speed_empty": 1.2, "control": {"tol_xy": 0.1}}


def test_resolve_from_node_values_treats_empty_strings_as_absent():
    p = P.resolve_from_values({"model": "iw_hub", "profile_file": "", "profile_overrides": ""})

    assert p["v_max"] == 0.8
