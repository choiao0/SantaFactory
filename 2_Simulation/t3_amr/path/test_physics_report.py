# -*- coding: utf-8 -*-
"""`physics_report` — 물리 검증 숫자 한 벌 (S15P21A106-275). 순수 함수라 Isaac 없이 본다.

    python3 -m pytest path/test_physics_report.py -q
"""
import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import physics_report as PR                                 # noqa: E402


def stats(**over):
    d = {k: 0 for k in PR.COUNTERS}
    d.update(worst_gap=float("inf"), static_worst_pen=0.0, zone_worst_pen=0.0, start_lag=[])
    d.update(over)
    return SimpleNamespace(**d)


class TestLag:
    def test_only_actions_planned_inside_the_window_count(self):
        lag = [(0.0, 0.5), (10.0, 10.0), (70.0, 75.0), (80.0, 80.2)]   # (계획, 실제)
        s = PR.lag_summary(lag, 60.0, 660.0)
        assert s["n"] == 2
        assert s["p50_s"] == 0.2 and s["p90_s"] == 5.0 and s["max_s"] == 5.0
        assert s["late_ratio"] == 0.5                                  # 1 초 넘게 늦은 것 1/2

    def test_an_empty_window_has_no_numbers(self):
        assert PR.lag_summary([], 60.0, 660.0)["n"] == 0
        assert PR.lag_summary([], 60.0, 660.0)["p90_s"] is None


class TestProgress:
    def test_ratio_and_the_age_of_the_oldest_overdue_action(self):
        planned = [60.0, 61.0, 61.0, 62.0, 700.0]      # 같은 시각 동작이 둘일 수 있다
        started = [60.0, 61.0]
        p = PR.progress(planned, started, 60.0, 660.0, now_s=100.0)
        assert p["planned"] == 4 and p["started"] == 2 and p["ratio"] == 0.5
        assert p["overdue_s"] == 39.0                   # 61 초 계획 두 번째 것이 아직

    def test_nothing_overdue_when_everything_due_has_started(self):
        p = PR.progress([60.0, 61.0], [60.0, 61.0], 60.0, 660.0, now_s=100.0)
        assert p["ratio"] == 1.0 and p["overdue_s"] == 0.0

    def test_actions_planned_after_now_are_not_due_yet(self):
        p = PR.progress([60.0, 200.0], [60.0], 60.0, 660.0, now_s=100.0)
        assert p["planned"] == 1 and p["overdue_s"] == 0.0


class TestSummarize:
    def test_counters_are_counted_after_warmup_only(self):
        rt = SimpleNamespace(_why={0: [1, 2, 3, 4], 1: [0, 0, 0, 0]}, _why_steps=100)
        s0 = stats(contact_events=3, static_contact_events=1)
        base = PR.snapshot(s0, SimpleNamespace(_why={0: [0, 1, 1, 1]}, _why_steps=40))
        s1 = stats(contact_events=5, static_contact_events=1, worst_gap=0.32, static_worst_pen=0.0123,
                   start_lag=[(70.0, 71.5)])
        doc = PR.summarize(s1, base, sim_s=660.0, wall_s=733.0, warmup_s=60.0, window_s=600.0,
                           n_robots=2, planned_s=[70.0], rt=rt, des_window={"tasks_done": 174})
        assert doc["robot_contacts"] == 2 and doc["rack_contacts"] == 0
        assert doc["robot_min_gap_m"] == 0.32 and doc["rack_worst_pen_mm"] == 12.3
        assert doc["window_sim_s"] == 600.0 and doc["rtf"] == 0.9
        assert doc["blocked"]["robot_frames"] == 120                   # (100 − 40) 스텝 × 2대
        assert doc["blocked"]["release"] == 1 and doc["blocked"]["adg_other"] == 3
        assert doc["lag"]["n"] == 1 and doc["window_actions"]["ratio"] == 1.0
        assert doc["des_window"]["tasks_done"] == 174

    def test_before_warmup_ends_the_whole_run_is_counted(self):
        doc = PR.summarize(stats(contact_events=1), None, sim_s=30.0, wall_s=30.0,
                           warmup_s=60.0, window_s=600.0, n_robots=1)
        assert doc["robot_contacts"] == 1 and doc["window_sim_s"] == 0.0
        assert doc["robot_min_gap_m"] is None                          # 한 번도 안 가까워졌다

    def test_self_planned_runs_have_no_plan_comparison(self):
        """DES 계획이 없는 런 — 태스크 첫 동작의 주문 도착 시각만 남아 있어도 견주지 않는다."""
        s = stats(started=1462, start_lag=[(3.0, 3.01), (5.0, 5.02)])
        doc = PR.summarize(s, None, sim_s=600.0, wall_s=701.0, warmup_s=0.0, window_s=600.0,
                           n_robots=12, planned_s=None)
        assert doc["lag"] is None and doc["window_actions"] is None
        assert doc["actions_started"] == 1462                          # 나머지는 그대로 센다

    def test_file_is_written_whole(self, tmp_path):
        p = str(tmp_path / "physics_x.json")
        PR.write_atomic(p, {"robot_contacts": 0})
        with open(p, encoding="utf-8") as f:
            assert json.load(f) == {"robot_contacts": 0}
        assert not os.path.exists(p + ".part")
