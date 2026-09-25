# -*- coding: utf-8 -*-
"""`des_slice` — DES 피크 10분 고르기와 자르기 (S15P21A106-275). 순수 함수라 파일 없이 본다.

    python3 -m pytest tools/test_des_slice.py -q
"""
import base64
import gzip
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import des_slice as DS                                       # noqa: E402


class TestPickPeak:
    def test_the_densest_window_wins(self):
        done = [100, 700, 710, 720, 730, 1500]
        t0, n = DS.pick_peak(done, horizon_s=2000, window_s=100, warmup_s=60, step_s=10)
        assert n == 4 and 640 <= t0 <= 700

    def test_ties_go_to_the_earlier_window(self):
        t0, n = DS.pick_peak([100, 500], horizon_s=1000, window_s=50, warmup_s=60, step_s=10)
        assert n == 1 and t0 == 60

    def test_a_horizon_shorter_than_warmup_plus_window_is_an_error(self):
        with pytest.raises(ValueError):
            DS.pick_peak([10], horizon_s=100, window_s=600, warmup_s=60)


def export(n_ticks=21, dt=1.0):
    """로봇 0 은 매 틱 한 칸 전진, 로봇 1 은 제자리에서 틱 12 에 한 번 돈다."""
    robots, headings, actions = {"0": [], "1": []}, {"0": [], "1": []}, {"0": [], "1": []}
    for k in range(n_ticks):
        t = k * dt
        robots["0"].append([t, 1.0 + k, 2.5])
        headings["0"].append([t, 0.0])
        robots["1"].append([t, 9.1, 9.5])
        headings["1"].append([t, 1.5708 if k >= 12 else 0.0])
        actions["1"].append([t, "wait"])
    tasks = [{"id": 1, "assigned": 5, "completed": 11}, {"id": 2, "assigned": 9, "completed": 30},
             {"id": 3, "assigned": 0, "completed": 3}]
    return {"dt_s": dt, "model": "heading", "robots": robots, "headings": headings,
            "actions": actions, "tasks": tasks}


class TestCut:
    def test_keeps_warmup_window_and_tail_and_writes_the_block(self):
        doc = DS.cut(export(), t0_s=10, warmup_s=2, window_s=5, tail_s=1, speed_mps=0.9, source="est_x")
        s = doc["slice"]
        assert (s["t_start_s"], s["t0_s"], s["t_end_s"]) == (8.0, 10.0, 16.0)
        assert s["warmup_s"] == 2.0 and s["window_s"] == 5.0 and s["speed_mps"] == 0.9
        assert [row[0] for row in doc["robots"]["0"]] == [8.0 + i for i in range(9)]

    def test_counts_what_the_des_did_inside_the_window(self):
        s = DS.cut(export(), t0_s=10, warmup_s=2, window_s=5, tail_s=1)["slice"]["des_window"]
        assert s["moves"] == 5 and s["turns"] == 1 and s["reverses"] == 0   # 틱 10..14
        assert s["tasks_done"] == 1                                         # 완료 틱 11 만

    def test_tasks_overlapping_the_slice_are_kept(self):
        doc = DS.cut(export(), t0_s=10, warmup_s=2, window_s=5, tail_s=1)
        assert {t["id"] for t in doc["tasks"]} == {1, 2}                     # 3 은 틱 3 에 끝났다

    def test_a_t0_earlier_than_the_warmup_is_an_error(self):
        with pytest.raises(ValueError):
            DS.cut(export(), t0_s=1, warmup_s=2, window_s=5)

    def test_a_robot_without_a_row_at_the_slice_start_is_an_error(self):
        raw = export()
        raw["robots"]["1"] = [row for row in raw["robots"]["1"] if row[0] != 8.0]
        with pytest.raises(ValueError, match="첫 틱"):
            DS.cut(raw, t0_s=10, warmup_s=2, window_s=5)

    def test_encoding_round_trips(self):
        doc = DS.cut(export(), t0_s=10, warmup_s=2, window_s=5)
        _, _, b64 = DS.encode(doc)
        assert json.loads(gzip.decompress(base64.b64decode(b64)))["slice"]["t0_s"] == 10.0
