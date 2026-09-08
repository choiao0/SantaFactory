"""기종 프로파일(config/models/<model>.yaml) 로드 → VDA 5050 factsheet 입력. 순수 파이썬 (ROS 불필요)."""
from __future__ import annotations

import math
import os
from typing import Optional

import yaml

REQUIRED = ("model", "manufacturer", "kinematic", "agv_class", "max_load_kg", "v_min", "v_max", "a_max",
            "length", "width", "height", "front_overhang", "rear_overhang", "swing_radius", "wheels",
            "state_interval", "order_interval")


class ModelProfileError(ValueError):
    """프로파일 파일이 없거나 필수 키가 빠졌다."""


def models_dir() -> str:
    """설치본(share/amr_agent/config/models)이 있으면 그것, 아니면 소스 트리의 config/models."""
    try:
        from ament_index_python.packages import get_package_share_directory
        d = os.path.join(get_package_share_directory("amr_agent"), "config", "models")
        if os.path.isdir(d):
            return d
    except Exception:  # noqa: BLE001 — ROS 밖(단위 테스트)에서는 소스 트리로
        pass
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "config", "models")


def load_model_profile(model: str = "iw_hub", path: Optional[str] = None) -> dict:
    p = path or os.path.join(models_dir(), f"{model}.yaml")
    if not os.path.isfile(p):
        raise ModelProfileError(f"model profile not found: {p}")
    with open(p, encoding="utf-8") as f:
        d = yaml.safe_load(f) or {}
    missing = [k for k in REQUIRED if k not in d]
    if missing:
        raise ModelProfileError(f"model profile {p} missing keys: {missing}")
    if not d["wheels"]:
        raise ModelProfileError(f"model profile {p}: wheels is empty")
    return d


def footprint_polygon(p: dict) -> list:
    """차량 좌표계 외곽 사각형 — 앞 front_overhang, 뒤 rear_overhang, 폭 width."""
    hx_f, hx_r, hy = float(p["front_overhang"]), float(p["rear_overhang"]), float(p["width"]) / 2
    return [{"x": hx_f, "y": hy}, {"x": -hx_r, "y": hy}, {"x": -hx_r, "y": -hy}, {"x": hx_f, "y": -hy}]


def swing_polygon(p: dict, n: int = 12) -> list:
    """스팟턴 스윙 원(반경 swing_radius)의 n각형 근사 — 원점은 회전 중심."""
    r = float(p["swing_radius"])
    return [{"x": round(r * math.cos(2 * math.pi * i / n), 4), "y": round(r * math.sin(2 * math.pi * i / n), 4)}
            for i in range(n)]
