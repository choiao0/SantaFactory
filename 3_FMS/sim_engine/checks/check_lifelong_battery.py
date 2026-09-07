# -*- coding: utf-8 -*-
# ============================================================
# 고정 시간·교대·배터리 불변 검사 — -145 (docs/2026-09-05_SimPy사건층_배터리_교대_설계.md §5)
#
# [1] 유한 모드 도착 시각표가 리팩터링 전 공식(cumsum(exponential).astype(int)+1, 주문 → 입고 순)과 동일 — rng 순서 불변
# [2] 교대 창: 고정 시간 모드에서 in 도착은 in 창 안에만, out 도착은 out 창 안에만. 창 병합 규칙(in,out,out → 2창)
# [3] 배터리 불변 (in-process, 매 틱): 0 ≤ SoC ≤ 1, 동시 CHARGING ≤ 도크 수, 도크당 소유자 1, 충전 중 로봇은 자기 도크 위,
#     TO_CHARGE 로봇의 목표 도크는 자기 소유, soc < low 인 로봇은 새 태스크를 받지 않음. 강제 충전·퇴거가 실제로 일어나는 조건으로 돈다
# [4] CLI 셸 vs SimPy 하네스 SUMMARY 동일 (고정 시간 + 배터리) — simpy 가 없으면 건너뜀(종료 코드 2)
# [5] 0 간격 입력 거부 + 고정 시간 워치독은 경고를 기록하고 T까지 계속
# [6] 유한 모드 워치독은 옛 규칙 그대로 (첫 완료 전 타임스탬프 [0,0], 간격 1500 → [STALL] t=1501)
# [7] --battery 유무가 주문 스트림을 바꾸지 않음 (초기 SoC 별도 rng)
#
# 사용 (3_FMS/sim_engine):  python checks/check_lifelong_battery.py        (~20초)
# 종료 코드 0 = 전부 통과.
# ============================================================
import json
import os
import subprocess
import sys

ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ENGINE_DIR)

import numpy as np

from fms_kernel import CHARGING, TO_CHARGE, TO_PICK
from map_loader import load_map
from order_stream import OrderStream, shift_windows
from sim_v2_tasks import build, parse_args, run_ticks

OUT = ENGINE_DIR
PY = sys.executable
ENV = dict(os.environ, SIM_NO_PLOT="1", PYTHONIOENCODING="utf-8")


def check_finite_times():
    free, st_cell, stations = load_map(aisle_block=True)
    for seed, n, gap in [(42, 40, 50), (7, 120, 15)]:
        s = OrderStream(np.random.default_rng(seed), "main", n, gap, st_cell, stations)
        rng = np.random.default_rng(seed)
        ref_o = np.cumsum(rng.exponential(gap, n)).astype(int) + 1
        ref_i = np.cumsum(rng.exponential(gap, n)).astype(int) + 1
        assert np.array_equal(s.order_times, ref_o) and np.array_equal(s.inbound_times, ref_i), f"유한 모드 시각표 변동 seed={seed}"
        s = OrderStream(np.random.default_rng(seed), "v1compat", n, gap, st_cell, stations)
        assert np.array_equal(s.order_times, ref_o) and len(s.inbound_times) == 0
    print("[1] 유한 모드 도착 시각표: 리팩터링 전 공식과 동일 (main 주문→입고, v1compat 주문만) : OK")


def check_shift_windows():
    assert shift_windows(10800, ("in", "out", "out")) == [("in", 0, 3600), ("out", 3600, 10800)]
    assert shift_windows(100, ("out", "in", "out")) == [("out", 0, 33), ("in", 33, 67), ("out", 67, 100)]
    assert shift_windows(7200, ("in",)) == [("in", 0, 7200)]
    free, st_cell, stations = load_map(aisle_block=True)
    n_checked = 0
    for T, shifts, gap, gin in [(10800, ("in", "out", "out"), 15, None), (5000, ("out", "in", "out", "in"), 7.5, 30),
                                (3600, ("out",), 20, None)]:
        s = OrderStream(np.random.default_rng(1), "main", 0, gap, st_cell, stations, inbound_gap=gin, horizon=T, shifts=shifts)
        _assert_stream_in_windows(s, T, gap, gin)
        n_checked += 1
    print(f"[2] 교대 창: 창 밖 도착 0건, 병합 규칙 3건, 스트림 {n_checked}벌 : OK")


def _assert_stream_in_windows(s, T, gap, gin):
    """스트림 s 의 도착이 전부 자기 종류의 창 안이고, 창별 도착 수가 기대(창 길이/gap)의 ±35 % 안인가."""
    win = {"in": [(a, b) for k, a, b in s.windows if k == "in"], "out": [(a, b) for k, a, b in s.windows if k == "out"]}
    inside = lambda t, ws: any(a <= t < b for a, b in ws)
    assert all(inside(t, win["out"]) for t in s.order_times), "출고 도착이 out 창 밖"
    assert all(inside(t, win["in"]) for t in s.inbound_times), "입고 도착이 in 창 밖"
    assert all(0 < t < T for t in list(s.order_times) + list(s.inbound_times))
    assert s.n_orders == len(s.order_times) and s.n_inbound == len(s.inbound_times) and s.outstanding == s.n_orders + s.n_inbound
    # 창 안 도착 수가 기대(창 길이/gap)와 크게 다르지 않은지 (±35 %, 시드 1개라 느슨하게)
    for kind, times, g in (("out", s.order_times, gap), ("in", s.inbound_times, gap if gin is None else gin)):
        span = sum(b - a for a, b in win[kind])
        if span:
            exp = span / g
            assert 0.65 * exp <= len(times) <= 1.35 * exp, f"{kind} 도착 {len(times)} vs 기대 {exp:.0f}"


def _assert_no_low_soc_dispatch(kernel, prev_task, t):
    """배차 직후: soc < low 인 로봇이 이번 틱에 새 태스크를 받지 않았는가 (배차 제외 규칙). prev_task 를 갱신한다."""
    low = kernel.cfg.soc_low
    for rid in kernel.rids:
        rb = kernel.robots[rid]
        task = rb["task"]
        fresh = task is not None and task is not prev_task[rid] and rb["state"] == TO_PICK and task["assigned"] == t
        assert not fresh or rb["soc"] >= low, f"t={t} robot{rid} soc={rb['soc']:.3f} < low 인데 배차"
        prev_task[rid] = task


def _assert_dock_invariants(kernel, docks, t):
    """이동 직후: 0 ≤ SoC ≤ 1, 동시 CHARGING ≤ 도크 수, 도크당 소유자 1, 충전 중·충전 가는 로봇과 도크 소유 관계 일관."""
    charging = [rid for rid in kernel.rids if kernel.robots[rid]["state"] == CHARGING]
    assert len(charging) <= len(docks), f"t={t} 동시 충전 {len(charging)} > 도크 {len(docks)}"
    owners = [o for o in kernel.dock_owner.values() if o is not None]
    assert len(owners) == len(set(owners)), f"t={t} 도크 소유자 중복"
    for rid in kernel.rids:
        rb = kernel.robots[rid]
        assert 0.0 <= rb["soc"] <= 1.0, f"t={t} robot{rid} soc={rb['soc']}"
        cell = {CHARGING: rb["pos"], TO_CHARGE: rb["goal"]}.get(rb["state"])
        if cell is not None:
            assert cell in docks and kernel.dock_owner[cell] == rid, f"t={t} robot{rid} {rb['state']} 도크 {cell} 소유 불일치"
    for d, o in kernel.dock_owner.items():
        if o is not None:
            assert kernel.robots[o]["state"] in (TO_CHARGE, CHARGING) and kernel.robots[o]["goal"] == d, f"t={t} 도크 {d} 소유자 {o} 상태 불일치"


def check_battery_invariants():
    # 12대·1.5 h·간격 7.5(항상 바쁨 → 기회 충전 거의 없음)·도크 2·강제선 40 % → 강제 충전·퇴거·도크 대기가 실제로 일어난다
    argv = ["chk", "12", "0", "42", "1", "--horizon=5400", "--order-gap=7.5", "--battery", "--chargers=2", "--soc=40,80,95"]
    a = parse_args(argv)
    kernel, stream, ctx = build(a)
    docks = set(kernel.docks)
    initial_min = min(rb["soc"] for rb in kernel.robots.values())
    assert kernel.battery_summary()["soc_min"] == initial_min, "soc_min 에 초기 SoC 최솟값이 포함되지 않음"
    prev_task = {rid: None for rid in kernel.rids}
    for t in range(a.horizon):
        for task in stream.arrivals(t):
            kernel.submit_task(task)
        kernel.dispatch(t)
        _assert_no_low_soc_dispatch(kernel, prev_task, t)
        kernel.move(t)
        _assert_dock_invariants(kernel, docks, t)
    b = kernel.battery_summary()
    assert b["charge_events"] > 0 and b["charge_evictions"] > 0, f"강제 충전·퇴거가 안 일어남: {b}"
    assert b["soc_empty_steps"] == 0, f"0 % 도달 {b['soc_empty_steps']}틱 (12대·도크 2·1.5 h 에선 없어야 함)"
    print(f"[3] 배터리 불변 (12대·1.5 h·도크 2·간격 7.5·SoC 40/80/95, 매 틱): 충전 진입 {b['charge_events']}회·퇴거 {b['charge_evictions']}회·"
          f"도크 대기 {b['dock_wait_steps']}틱, SoC 최저 {b['soc_min']*100:.1f}%, 완료 {len(kernel.tasks_done)} : OK")


def check_harness_parity():
    args = ["hz", "8", "0", "7", "1", "--horizon=3600", "--order-gap=15", "--battery", "--chargers=3"]
    def run(script):
        r = subprocess.run([PY, os.path.join(OUT, script), *args], capture_output=True, text=True, encoding="utf-8", env=ENV, cwd=OUT)
        line = next((ln for ln in r.stdout.splitlines() if ln.startswith("[SUMMARY]")), None)
        return r.returncode, line
    rc, cli = run("sim_v2_tasks.py")
    assert rc == 0 and cli, f"CLI 실패 rc={rc}"
    rc, harness = run("simpy_harness.py")
    if rc == 2:
        print("[4] SimPy 하네스 패리티: simpy 미설치 — 건너뜀")
        return
    assert rc == 0 and harness == cli, f"하네스 SUMMARY 불일치\n CLI {cli}\n SIM {harness}"
    print("[4] SimPy 하네스 패리티 (고정 시간 3600·8대·배터리·도크 3): SUMMARY 동일 : OK")


def check_validation_and_watchdog():
    for flag in ("--order-gap=0", "--inbound-gap=0"):
        try:
            parse_args(["chk", "2", "0", "1", "1", "--horizon=10", flag])
        except AssertionError:
            pass
        else:
            raise AssertionError(f"0 간격을 허용함: {flag}")

    a = parse_args(["chk", "2", "0", "1", "1", "--horizon=10", "--order-gap=0.1"])
    kernel, stream, _ = build(a)
    kernel.cfg.stall_ticks = 1
    run_ticks(kernel, stream, a.horizon)
    assert kernel.stall_warning_ticks, "고정 시간 실행의 무진전 경고가 기록되지 않음"
    print(f"[5] 입력·워치독: 0 간격 거부, 고정 시간 무진전 {len(kernel.stall_warning_ticks)}회 기록 후 완주 : OK")


def check_finite_watchdog_unchanged():
    """유한 모드 워치독은 옛 규칙 그대로여야 한다 (2026-09-06 검토): '할 일 없음 = 진전' 조건은 고정 시간 모드 전용.
    (a) 플래그 없는 커널: 첫 완료 전에는 _progress 타임스탬프가 0 에 머문다. (b) 간격 1500 → v2.1 과 같이 t=1501 에 STALL."""
    a = parse_args(["base", "6", "40", "42", "1"])
    kernel, stream, _ = build(a)
    for t in range(80):                      # 첫 도착(틱 67) 을 지나도록
        for task in stream.arrivals(t):
            kernel.submit_task(task)
        kernel.dispatch(t)
        kernel.move(t)
    assert kernel._progress == [0, 0], f"유한 모드 워치독 타임스탬프가 움직임: {kernel._progress} (옛 규칙은 첫 완료까지 [0, 0])"
    r = subprocess.run([PY, os.path.join(OUT, "sim_v2_tasks.py"), "base", "6", "40", "42", "1", "--order-gap=1500"],
                       capture_output=True, text=True, encoding="utf-8", env=ENV, cwd=OUT)
    assert r.returncode == 1 and "[STALL] t=1501," in r.stdout, f"간격 1500 유한 모드: rc={r.returncode}, v2.1 은 [STALL] t=1501"
    print("[6] 유한 모드 워치독 불변: 첫 완료 전 타임스탬프 [0, 0], 간격 1500 → [STALL] t=1501 (v2.1 동일) : OK")


def check_battery_same_orders():
    """--battery 유무가 주문 스트림(도착 시각·구성)을 바꾸지 않는다 — 초기 SoC 는 별도 rng (2026-09-06 검토)."""
    base = ["hz", "12", "0", "42", "1", "--horizon=3600", "--order-gap=15"]
    tasks = []
    for extra in ([], ["--battery"]):
        a = parse_args(base + extra)
        kernel, stream, _ = build(a)
        seq = [(tk["created"], tk["kind"], tk["frm_name"], tk["to_name"]) for t in range(a.horizon) for tk in stream.arrivals(t)]
        tasks.append(seq)
    assert tasks[0] == tasks[1] and len(tasks[0]) > 50, "배터리 on/off 에서 주문 스트림이 다름"
    print(f"[7] 배터리 on/off 주문 스트림 동일 ({len(tasks[0])} 태스크, 도착·종류·출발·도착지 전부 일치) : OK")


if __name__ == "__main__":
    check_finite_times()
    check_shift_windows()
    check_battery_invariants()
    check_harness_parity()
    check_validation_and_watchdog()
    check_finite_watchdog_unchanged()
    check_battery_same_orders()
    print("[PASS] 고정 시간·교대·배터리 불변 검사 통과")
