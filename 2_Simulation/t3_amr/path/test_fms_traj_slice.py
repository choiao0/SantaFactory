# -*- coding: utf-8 -*-
"""`fms_traj` 의 구간 파일 읽기 (S15P21A106-275) — 틱을 구간 시작 기준 0 으로 다시 센다.

`fms_traj` 는 계획기 원본(`pibt_core`, numba 필요)과 FMS `map_loader` 를 부른다. 여기서는
그 둘을 **가짜 모듈로 끼워** 재기준 로직만 본다 — 칸·헤딩 변환 규칙은 같은 DIRS 로 맞춘다.

    python3 -m pytest path/test_fms_traj_slice.py -q
"""
import importlib
import json
import math
import os
import sys
import types

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
DIRS = [(-1, 0), (0, 1), (1, 0), (0, -1)]
CELL_M, OFF_M = 1.0, 0.4
DT = 0.2777777777777778


@pytest.fixture
def ft(monkeypatch):
    monkeypatch.syspath_prepend(HERE)
    for name, attrs in (("pibt_core_v2", {}), ("pibt_core", {"DIRS": DIRS}),
                        ("map_loader", {"CELL_M": CELL_M, "OFFSET_M": OFF_M})):
        m = types.ModuleType(name)
        m.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, m)
    monkeypatch.delitem(sys.modules, "fms_traj", raising=False)
    mod = importlib.import_module("fms_traj")
    yield mod
    sys.modules.pop("fms_traj", None)


def xy(r, c):
    return round((c + 0.5) * CELL_M - OFF_M, 2), round((r + 0.5) * CELL_M, 2)


def yaw(h):
    dr, dc = DIRS[h]
    return round(math.atan2(dr, dc), 4)


def write(tmp_path, ticks, slice_block=None, drop_first_of=None):
    """로봇 두 대가 `ticks` 동안 한 칸씩 가는 궤적. 시각은 DES 원래 초(틱 × DT)."""
    robots, headings = {}, {}
    for rid in (0, 1):
        rows, hs = [], []
        for i, k in enumerate(ticks):
            if drop_first_of == rid and i == 0:
                continue
            t = round(k * DT, 3)
            rows.append([t, *xy(5 + rid, 3 + i)])
            hs.append([t, yaw(1)])
        robots[str(rid)], headings[str(rid)] = rows, hs
    doc = {"dt_s": DT, "model": "heading", "robots": robots, "headings": headings,
           "actions": {}, "tasks": []}
    if slice_block is not None:
        doc["slice"] = slice_block
    p = tmp_path / "traj.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return str(p)


def block(k_start, warm_ticks=216):
    return {"t_start_s": k_start * DT, "t0_s": (k_start + warm_ticks) * DT,
            "warmup_s": warm_ticks * DT, "window_s": 600.0}


class TestSliceRebase:
    def test_slice_start_becomes_tick_zero(self, ft, tmp_path):
        k0 = 56916                                   # DES 15,810 s 근처
        p = write(tmp_path, [k0, k0 + 1, k0 + 2], block(k0))
        history, meta = ft.load_history(p, verbose=False)
        assert len(history) == 3
        assert history[0][0] == (5, 3, 1) and history[2][1] == (6, 5, 1)
        assert meta["slice"]["t0_s"] == pytest.approx((k0 + 216) * DT)
        assert meta["dt"] == DT

    def test_a_robot_missing_at_the_slice_start_is_an_error(self, ft, tmp_path):
        """스폰 자리를 모르면 돌 수 없다 — 조용히 빼면 그 로봇이 사라진다."""
        k0 = 100
        p = write(tmp_path, [k0, k0 + 1], block(k0, warm_ticks=10), drop_first_of=1)
        with pytest.raises(ValueError, match="구간 시작"):
            ft.load_history(p, verbose=False)

    def test_inconsistent_warmup_is_rejected(self, ft, tmp_path):
        bad = block(100, warm_ticks=10)
        bad["warmup_s"] = 99.0
        p = write(tmp_path, [100, 101], bad)
        with pytest.raises(ValueError, match="warmup"):
            ft.load_history(p, verbose=False)

    def test_missing_slice_keys_are_named(self, ft, tmp_path):
        p = write(tmp_path, [0, 1], {"t_start_s": 0.0})
        with pytest.raises(ValueError, match="t0_s"):
            ft.load_history(p, verbose=False)

    def test_a_whole_run_export_reads_as_before(self, ft, tmp_path):
        p = write(tmp_path, [0, 1, 2])
        history, meta = ft.load_history(p, verbose=False)
        assert len(history) == 3 and meta["slice"] is None
        assert history[0][0] == (5, 3, 1)
