# -*- coding: utf-8 -*-
"""규칙 기반 출발·복귀 차선과 v3 θ 기본값."""
from dataclasses import asdict, replace
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from contracts.guidance_types import GuidanceTheta  # noqa: E402
from from_theta import edge_masks, extract_topology, from_theta, load_theta  # noqa: E402
from map_loader import load_map  # noqa: E402
from sim_v2_tasks import parse_args  # noqa: E402


def test_topology_derives_pocket_departure_and_return_rows():
    free, st, _ = load_map(aisle_block=True)
    topo = extract_topology(free, st)
    rows = sorted({rc[0] for name, rc in st.items() if name.startswith("aisle_buf[")})
    assert rows == [46, 69]
    assert topo.pocket[46].any() and topo.pocket[69].any()
    assert set(np.unique(topo.lane_dir[45])) >= {-1, 3}   # 남쪽 출발 = 서
    assert set(np.unique(topo.lane_dir[43])) >= {-1, 1}   # 남쪽 복귀 = 동
    assert set(np.unique(topo.lane_dir[70])) >= {-1, 1}   # 북쪽 출발 = 동
    assert set(np.unique(topo.lane_dir[72])) >= {-1, 3}   # 북쪽 복귀 = 서


def test_lane_and_pocket_gains_touch_only_their_masks():
    free, st, _ = load_map(aisle_block=True)
    topo = extract_topology(free, st)
    theta = replace(GuidanceTheta.neutral(), lane_gain=3.0, pocket_gain=3.0)
    masks = edge_masks(free, topo, theta)
    cost = from_theta(free, topo, theta).edge_cost
    assert masks["lane_gain"].any() and masks["pocket_gain"].any()
    assert np.all(cost[masks["lane_gain"]] == 3.0)
    assert np.all(cost[masks["pocket_gain"]] == 3.0)
    assert np.all(from_theta(free, topo, GuidanceTheta.neutral()).edge_cost[free] == 1.0)


def test_old_theta_file_loads_neutral_or_runtime_lane_defaults(tmp_path):
    raw = asdict(GuidanceTheta.neutral())
    raw.pop("lane_gain")
    raw.pop("pocket_gain")
    path = tmp_path / "old.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert load_theta(path).lane_gain == 1.0
    assert load_theta(path, (3.0, 3.0)).pocket_gain == 3.0
    assert parse_args([]).lanes
    assert not parse_args(["--no-lanes"]).lanes
