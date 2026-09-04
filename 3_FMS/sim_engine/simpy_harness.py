# -*- coding: utf-8 -*-
# ============================================================
# SimPy 하네스 — 같은 커널(fms_kernel.FmsKernel)·같은 주문 스트림을 SimPy 가상 시계 위에서 돌린다
# (설계: docs/2026-09-04_커널_라이브러리화_SimPy하네스_설계.md §6, 아키텍처 "실행 셸 2종" 중 DES 쪽)
#
# 목적(이번 이슈): "SimPy 시계 위에서 같은 커널이 같은 답" — SUMMARY 가 sim_v2_tasks.py 와 비트 동일해야 한다.
# 다음 이슈에서 배터리(로봇별 SimPy 프로세스), 주문 도착 프로세스 분리, env.run(until=지평) 이 여기에 붙는다.
#
# 사용: 인자는 sim_v2_tasks.py 와 동일.  SIM_NO_PLOT=1 python simpy_harness.py base 6 40 42 1
# 의존: simpy (sim_engine 필수 의존이 아니다 — 없으면 안내 후 종료 코드 2. infra/requirements.txt 에 넣지 않는다)
# ============================================================
import os
import sys

try:
    import simpy
except ImportError:                                   # pragma: no cover
    print("simpy 가 없습니다: pip install simpy  (이 하네스만 필요, CLI 셸 sim_v2_tasks.py 는 simpy 없이 동작)")
    raise SystemExit(2)

from fms_kernel import StallError
from sim_v2_tasks import DT, build, parse_args, plot_heat, report


def ticker(env, kernel, stream):
    """커널 틱 프로세스: 매 DT 마다 arrivals → dispatch → (종료 판단) → move. sim_v2_tasks.run_ticks 와 같은 순서."""
    while stream.outstanding > 0:
        t = int(round(env.now / DT))
        for task in stream.arrivals(t):
            kernel.submit_task(task)
        kernel.dispatch(t)
        if stream.outstanding == 0:
            break
        kernel.move(t)
        yield env.timeout(DT)


def main(argv=None):
    a = parse_args(sys.argv[1:] if argv is None else argv)
    kernel, stream, ctx = build(a)
    for w in a.warnings:
        print(w)
    env = simpy.Environment()
    env.process(ticker(env, kernel, stream))
    try:
        env.run()
    except StallError as e:
        print(str(e))
        raise SystemExit("시뮬 정체 감지")
    print(f"[SIMPY] env.now = {env.now:g} s (틱 {int(round(env.now / DT))})")
    summary, tag, tph = report(a, kernel, stream, ctx)
    if not os.environ.get("SIM_NO_PLOT"):
        plot_heat(a, kernel, ctx, tag, tph)
    return summary


if __name__ == "__main__":
    main()
