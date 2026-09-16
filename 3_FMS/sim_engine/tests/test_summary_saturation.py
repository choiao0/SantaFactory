# -*- coding: utf-8 -*-
"""포화 구간 완료/h · 대치 묶인 틱 (S15P21A106-230, 계약 §2 조건부 키).

`saturated_tph` — 도착이 웨이브인 6h 런에서 `tasks_per_h` 는 뒤 구간의 수요 제한이 섞여 용량 지표가 아니다.
30~180분(활동 태스크가 함대 상한에 붙어 있는 구간)의 완료/h 로 본다.
`standoff_ticks` — 대치 **건수**는 짧은 대치 100건과 긴 대치 1건을 구분 못 한다. 묶인 로봇·틱을 같이 낸다.

둘 다 조건부 키다: 포화 구간을 다 못 채운 런(고정 주문 수·짧은 horizon)에는 `saturated_tph` 가 안 붙고,
대치 상태기계가 꺼진 런에는 `standoff_ticks` 가 안 붙는다 — 그래야 옛 기준선 CSV 가 그대로 재현된다.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cli.report import SAT_FROM_S, SAT_TO_S, _saturated_tph  # noqa: E402

ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _tasks(*completed_ticks):
    return [{"completed": c} for c in completed_ticks]


def test_window_is_half_open_in_ticks():
    dt = 2.5                                        # 1틱 = 2.5 s → 구간 [720, 4320)틱
    lo, hi = SAT_FROM_S / dt, SAT_TO_S / dt
    got = _saturated_tph(_tasks(lo - 1, lo, hi - 1, hi), T_END=hi, dt=dt, lifelong=True)
    # 경계 두 개만 들어간다(lo 포함·hi 제외) → 2건 / 2.5h
    assert got == {"saturated_tph": round(2 / ((SAT_TO_S - SAT_FROM_S) / 3600), 1)}


def test_no_key_when_run_is_shorter_than_the_window():
    dt = 2.5
    assert _saturated_tph(_tasks(100), T_END=(SAT_TO_S / dt) - 1, dt=dt, lifelong=True) == {}


def test_no_key_for_fixed_order_runs():
    """b0z·load 스윕은 고정 주문 수(lifelong 아님) — 키가 붙으면 기준선 CSV 의 모양이 달라진다."""
    dt = 2.5
    assert _saturated_tph(_tasks(0, 10_000), T_END=10 * SAT_TO_S / dt, dt=dt, lifelong=False) == {}


def test_both_keys_land_in_summary():
    """실제 런 하나. speed 0.1(허용 하한) → dt 2.5 s 라 6h 대신 4,320틱으로 구간을 다 채운다."""
    r = subprocess.run(
        [sys.executable, os.path.join(ENGINE_DIR, "sim_v2_tasks.py"), "hz", "4", "0", "42", "1",
         "--horizon=4320", "--speed=0.1", "--order-gap=15"],
        cwd=ENGINE_DIR, capture_output=True, text=True, encoding="utf-8",
        env=dict(os.environ, SIM_NO_PLOT="1", MPLBACKEND="Agg", PYTHONIOENCODING="utf-8"))
    assert r.returncode == 0, r.stderr[-2000:]
    line = next(ln for ln in r.stdout.splitlines() if ln.startswith("[SUMMARY]"))
    got = json.loads(line[len("[SUMMARY] "):])
    assert got["makespan_steps"] == 4320 and got["dt_s"] == 2.5
    assert got["saturated_tph"] > 0
    # 대치가 걸린 런이면 묶인 틱은 건수 이상이다 (쌍 하나가 최소 두 로봇·한 틱)
    assert got["standoff_ticks"] >= 2 * got["standoffs"]
