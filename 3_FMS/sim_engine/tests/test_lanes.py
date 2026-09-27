# -*- coding: utf-8 -*-
"""규칙 기반 출발·복귀 차선 — 차선 비용은 θ 밖(--lane-gain/--pocket-gain), θ 스키마는 11개 그대로."""
from dataclasses import asdict
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from contracts.guidance_types import GuidanceTheta  # noqa: E402
from from_theta import edge_masks, extract_topology, from_theta  # noqa: E402
from map_loader import load_map  # noqa: E402
from sim_v2_tasks import parse_args  # noqa: E402


def test_topology_derives_pocket_departure_and_return_rows():
    free, st, _ = load_map(aisle_block=True)
    topo = extract_topology(free, st)
    rows = sorted({rc[0] for name, rc in st.items() if name.startswith("aisle_buf[")})
    assert rows == [46, 69]
    assert topo.pocket[46].any() and topo.pocket[69].any()
    assert set(np.unique(topo.lane_dir[45])) >= {-1, 1}   # 남쪽 출발 = 동
    assert set(np.unique(topo.lane_dir[43])) >= {-1, 3}   # 남쪽 복귀 = 서
    assert set(np.unique(topo.lane_dir[70])) >= {-1, 3}   # 북쪽 출발 = 서
    assert set(np.unique(topo.lane_dir[72])) >= {-1, 1}   # 북쪽 복귀 = 동


def test_lane_and_pocket_gains_touch_only_their_masks():
    free, st, _ = load_map(aisle_block=True)
    topo = extract_topology(free, st)
    theta = GuidanceTheta.neutral()
    masks = edge_masks(free, topo, theta)
    cost = from_theta(free, topo, theta, lane_gain=3.0, pocket_gain=3.0).edge_cost
    assert masks["lane_gain"].any() and masks["pocket_gain"].any()
    assert np.all(cost[masks["lane_gain"]] == 3.0)
    assert np.all(cost[masks["pocket_gain"]] == 3.0)
    assert np.all(from_theta(free, topo, theta).edge_cost[free] == 1.0)      # 기본 1.0 = 차선 없음, v2 비트 동일


def test_theta_schema_unchanged_and_lane_cli_defaults():
    assert len(asdict(GuidanceTheta.neutral())) == 11                        # θ 는 A트랙 계약 — 차선 비용은 θ 밖
    a = parse_args([])
    assert a.lanes and a.lane_gain == 2.0 and a.pocket_gain == 2.0
    assert not parse_args(["--no-lanes"]).lanes
    assert parse_args(["--lane-gain=3", "--pocket-gain=1"]).lane_gain == 3.0
    assert not parse_args(["--cell"]).lanes                                  # 칸 모델은 A/B 기준 축
