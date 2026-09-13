"""로봇 프로파일 — 노드 전부가 보는 **하나의** 병합 dict. 순수 파이썬(ROS 불필요).

여기서 factsheet(bridge) · 컨트롤러 한계(primitive_controller) · 상태 주기·배터리(order_executor) · 가짜 로봇 물리(fake_robot)가
전부 나온다. 값의 출처는 세 층이고 위가 이긴다:

  1. profile_overrides  — JSON 문자열 (sim-runner 가 scenario.amr 을 그대로 넘긴다)
  2. profile_file       — yaml | json 파일 경로
  3. config/models/<model>.yaml — 기종 팩토리 기본값 (+ 아래 SECTION_DEFAULTS)

오버라이드는 **BE 키**(시뮬엔진연동API명세서 §1-1 `amr`: speed_empty · speed_loaded · consumption · battery · charge_time ·
charge_threshold · capacity · tote_units)와 프로파일 키(v_max · control.tol_xy …) 둘 다 받는다. 모르는 키는 거절한다(오타 방지).
"""
from __future__ import annotations

import copy
import json
import os
from typing import Any, Mapping, Optional

import yaml

from .vda5050.models import REQUIRED, ModelProfileError, load_model_profile


class ProfileError(ValueError):
    """프로파일을 만들 수 없다 — 파일 없음 · 모르는 키 · 범위 밖 값."""


# 기종 yaml 에 없어도 되는 절과 기본값. 기종 yaml 이 같은 키를 주면 그것이 이긴다.
SECTION_DEFAULTS: dict = {
    "w_max": 1.2, "alpha_max": 2.5, "w_min": 0.12,
    "v_max_loaded": None,                      # None → v_max
    "control": {"rate_hz": 20.0, "tol_xy": 0.05, "tol_theta": 0.03, "timeout_s": 30.0,
                "turn_threshold": 0.12, "zero_edge_eps": 0.05, "first_node_tol": 0.5,
                "k_turn": 2.5, "k_heading": 2.5, "k_lateral": 1.5},
    "battery": {"soc_init_pct": 100.0, "consumption_pct_per_s": 0.0, "idle_ratio": 0.25,
                "charge_time_s": 3600.0, "charge_threshold_pct": 20.0},
    "load": {"capacity_totes": 6, "tote_units": 8},
    "plant": {"v_max": 0.835, "w_max": 2.0, "a_max": 6.0, "alpha_max": 12.0},   # fake_robot 응답 (T1 실측)
}
SECTIONS = ("control", "battery", "load", "plant")
SCALAR_KEYS = tuple(k for k in REQUIRED if k != "wheels") + ("w_max", "alpha_max", "w_min", "v_max_loaded",
                                                             "description", "d_max")


def _pct(v: float) -> float:
    """0 < v < 1 은 비율(charge_threshold 0.2 → 20). 1 이상은 이미 % (1 → 1 %, 100.0 → 100 %) — 경계 1 은 % 다."""
    return v * 100.0 if 0.0 < v < 1.0 else v


def _int(v: Any) -> int:
    """정수만. 5.0 은 5, 5.9 는 거절 — 토트 수를 조용히 자르지 않는다."""
    if isinstance(v, bool) or (isinstance(v, float) and not v.is_integer()):
        raise ValueError(f"not an integer: {v!r}")
    return int(v)


WHEEL_KEYS = ("type", "is_active_driven", "is_active_steered", "position", "diameter", "width")


# BE 키 → (프로파일 경로, 변환). 단위: m/s · %/s(주행 중) · % · s · 토트 · 상품
BE_KEYS: dict = {
    "speed_empty": (("v_max",), float),
    "speed_loaded": (("v_max_loaded",), float),
    "consumption": (("battery", "consumption_pct_per_s"), float),
    "battery": (("battery", "soc_init_pct"), lambda v: _pct(float(v))),
    "charge_time": (("battery", "charge_time_s"), float),
    "charge_threshold": (("battery", "charge_threshold_pct"), lambda v: _pct(float(v))),
    "capacity": (("load", "capacity_totes"), _int),
    "tote_units": (("load", "tote_units"), _int),
}


def _is_be_key(k: str, v: Any) -> bool:
    """BE 키는 스칼라다. 같은 이름의 절(battery)을 dict 로 주면 섹션 오버라이드로 본다."""
    return k in BE_KEYS and not isinstance(v, Mapping)


# ---- 층 쌓기 --------------------------------------------------------------------
def with_defaults(model_profile: Mapping[str, Any]) -> dict:
    """기종 yaml + SECTION_DEFAULTS → 새 dict. 절은 키 단위로 합친다."""
    out = copy.deepcopy(SECTION_DEFAULTS)
    for k, v in model_profile.items():
        if k in SECTIONS:
            out[k] = {**out[k], **copy.deepcopy(_as_mapping(v, f"model yaml section {k}"))}
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_overrides(path: Optional[str] = None, inline: Optional[str] = None) -> dict:
    """profile_file(yaml|json) 과 profile_overrides(JSON 문자열)를 하나로. inline 이 file 을 덮는다."""
    merged: dict = {}
    if path:
        if not os.path.isfile(path):
            raise ProfileError(f"profile_file not found: {path}")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        try:
            data = json.loads(text) if path.endswith(".json") else yaml.safe_load(text)
        except (ValueError, yaml.YAMLError) as e:
            raise ProfileError(f"profile_file {path} unparsable: {e}") from e
        merged = _merge(merged, _as_mapping(data, f"profile_file {path}"))
    if inline and inline.strip():
        try:
            data = json.loads(inline)
        except ValueError as e:
            raise ProfileError(f"profile_overrides is not JSON: {e}") from e
        merged = _merge(merged, _as_mapping(data, "profile_overrides"))
    return merged


def apply_overrides(profile: Mapping[str, Any], overrides: Mapping[str, Any]) -> dict:
    """BE 키를 프로파일 경로로 옮기고 덮어쓴 **새** dict. 모르는 키 · BE 키와 그 대상 키를 동시에 주면 ProfileError."""
    out = copy.deepcopy(dict(profile))
    plain = {k: v for k, v in overrides.items() if not _is_be_key(k, v)}
    unknown = [k for k in plain if k not in SCALAR_KEYS and k not in SECTIONS and k != "wheels"]
    if unknown:
        raise ProfileError(f"unknown profile keys {unknown}; allowed: BE keys {sorted(BE_KEYS)} · "
                           f"profile keys {sorted(SCALAR_KEYS)} · sections {list(SECTIONS)}")
    for k, v in plain.items():
        if k in SECTIONS:
            sec = _as_mapping(v, f"section {k}")
            allowed = set(SECTION_DEFAULTS[k]) | set(out[k])        # 기종 yaml 이 절에 더한 키도 허용
            bad = [s for s in sec if s not in allowed]
            if bad:
                raise ProfileError(f"unknown keys in {k}: {bad}; allowed {sorted(allowed)}")
            out[k] = {**out[k], **copy.deepcopy(dict(sec))}
        else:
            out[k] = copy.deepcopy(v)
    for k, v in overrides.items():
        if not _is_be_key(k, v):
            continue
        path, conv = BE_KEYS[k]
        if (len(path) == 1 and path[0] in plain) or (len(path) == 2 and path[1] in _as_mapping(plain.get(path[0], {}), path[0])):
            raise ProfileError(f"{k} and {'.'.join(path)} both given — use one")
        try:
            val = conv(v)
        except (TypeError, ValueError) as e:
            raise ProfileError(f"{k}: bad value {v!r}") from e
        if len(path) == 1:
            out[path[0]] = val
        else:
            out[path[0]] = {**out[path[0]], path[1]: val}
    return out


def validate(profile: Mapping[str, Any]) -> dict:
    """범위 검사 + 파생 기본값(v_max_loaded · v_min ≤ v_max …). 통과하면 새 dict."""
    p = copy.deepcopy(dict(profile))
    if p.get("v_max_loaded") is None:
        p["v_max_loaded"] = p["v_max"]
    _check_wheels(p.get("wheels"))
    checks = [
        ("v_max", p["v_max"] > 0), ("v_max_loaded", p["v_max_loaded"] > 0), ("a_max", p["a_max"] > 0),
        ("w_max", p["w_max"] > 0), ("alpha_max", p["alpha_max"] > 0),
        ("v_min", 0 < p["v_min"] < p["v_max"]), ("w_min", 0 < p["w_min"] < p["w_max"]),
        ("state_interval", p["state_interval"] > 0), ("order_interval", p["order_interval"] > 0),
        ("control.rate_hz", p["control"]["rate_hz"] > 0), ("control.tol_xy", p["control"]["tol_xy"] > 0),
        ("control.tol_theta", p["control"]["tol_theta"] > 0), ("control.timeout_s", p["control"]["timeout_s"] > 0),
        ("battery.soc_init_pct", 0 <= p["battery"]["soc_init_pct"] <= 100),
        ("battery.consumption_pct_per_s", p["battery"]["consumption_pct_per_s"] >= 0),
        ("battery.idle_ratio", 0 <= p["battery"]["idle_ratio"] <= 1),
        ("battery.charge_time_s", p["battery"]["charge_time_s"] > 0),
        ("battery.charge_threshold_pct", 0 <= p["battery"]["charge_threshold_pct"] <= 100),
        ("load.capacity_totes", 1 <= int(p["load"]["capacity_totes"]) <= 6),
        ("load.tote_units", int(p["load"]["tote_units"]) >= 1),
        ("plant.v_max", p["plant"]["v_max"] > 0), ("plant.a_max", p["plant"]["a_max"] > 0),
    ]
    bad = [name for name, ok in checks if not ok]
    if bad:
        raise ProfileError(f"profile out of range: {bad}")
    return p


def resolve_profile(model: str = "iw_hub", model_path: Optional[str] = None,
                    profile_file: Optional[str] = None, profile_overrides: Optional[str] = None) -> dict:
    """세 층을 쌓아 검증된 프로파일 하나를 돌려준다. 실패는 전부 ProfileError."""
    try:
        base = load_model_profile(model, model_path)
    except ModelProfileError as e:
        raise ProfileError(str(e)) from e
    return validate(apply_overrides(with_defaults(base), load_overrides(profile_file, profile_overrides)))


# ---- 노드별 파생값 ------------------------------------------------------------------
def limits(p: Mapping[str, Any]) -> dict:
    """control.primitives.Limits(**limits(p))."""
    return {"v_max": float(p["v_max"]), "w_max": float(p["w_max"]), "a_max": float(p["a_max"]),
            "alpha_max": float(p["alpha_max"]), "v_min": float(p["v_min"]), "w_min": float(p["w_min"])}


def gains(p: Mapping[str, Any]) -> dict:
    """control.primitives.Gains(**gains(p))."""
    c = p["control"]
    return {"k_turn": float(c["k_turn"]), "k_heading": float(c["k_heading"]), "k_lateral": float(c["k_lateral"])}


def state_rate_hz(p: Mapping[str, Any]) -> float:
    return 1.0 / float(p["state_interval"])


def summary(p: Mapping[str, Any]) -> str:
    """로그 한 줄 — 어떤 값으로 도는지 런 로그에 남긴다."""
    b, ld = p["battery"], p["load"]
    return (f"model={p['model']} v_max={p['v_max']}/{p['v_max_loaded']} a_max={p['a_max']} w_max={p['w_max']} "
            f"state_interval={p['state_interval']} soc={b['soc_init_pct']}% drain={b['consumption_pct_per_s']}%/s "
            f"threshold={b['charge_threshold_pct']}% totes={ld['capacity_totes']}x{ld['tote_units']}")


# ---- ROS 파라미터 ------------------------------------------------------------------
PROFILE_PARAMS = [("model", "iw_hub"), ("profile_file", ""), ("profile_overrides", "")]


def resolve_from_values(g: Mapping[str, Any]) -> dict:
    """declare_parameters(PROFILE_PARAMS) 로 받은 값 dict → 프로파일. 빈 문자열은 '없음'."""
    return resolve_profile(str(g.get("model") or "iw_hub"), None,
                           str(g.get("profile_file") or "") or None, str(g.get("profile_overrides") or "") or None)


# ---- 내부 ---------------------------------------------------------------------------
def _check_wheels(wheels: Any) -> None:
    """factsheet 가 MQTT 스레드에서 죽지 않도록 여기서 미리 검사한다 (오버라이드로 들어온 wheels 포함)."""
    if not isinstance(wheels, list) or not wheels:
        raise ProfileError("wheels must be a non-empty list")
    for i, w in enumerate(wheels):
        if not isinstance(w, Mapping):
            raise ProfileError(f"wheels[{i}] must be a mapping")
        missing = [k for k in WHEEL_KEYS if k not in w]
        if missing:
            raise ProfileError(f"wheels[{i}] missing {missing}")
        pos = w["position"]
        if not isinstance(pos, Mapping) or "x" not in pos or "y" not in pos:
            raise ProfileError(f"wheels[{i}].position needs x and y")
        try:
            float(pos["x"]), float(pos["y"]), float(w["diameter"]), float(w["width"])
        except (TypeError, ValueError) as e:
            raise ProfileError(f"wheels[{i}]: non-numeric geometry") from e


def _as_mapping(v: Any, what: str) -> dict:
    if v is None:
        return {}
    if not isinstance(v, Mapping):
        raise ProfileError(f"{what} must be a mapping, got {type(v).__name__}")
    return dict(v)


def _merge(a: Mapping[str, Any], b: Mapping[str, Any]) -> dict:
    out = copy.deepcopy(dict(a))
    for k, v in b.items():
        if k in SECTIONS and isinstance(v, Mapping) and isinstance(out.get(k), Mapping):
            out[k] = {**out[k], **copy.deepcopy(dict(v))}
        else:
            out[k] = copy.deepcopy(v)
    return out
