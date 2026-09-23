# -*- coding: utf-8 -*-
"""실행 속도·가속을 쓸어 보며 완주 시간과 **접촉**을 잰다.

이어달리기가 들어가기 전에는 속도를 올려도 소용이 없었다. 1.2 m 칸 안에서
정지->정지면 램프가 84% 라 속도를 쓸 구간이 없다 (0.9 -> 무한대가 칸당 9 ms).
이어달리기가 직진 구간(중앙값 7칸 = 8.4 m)을 연속으로 잇고 나서야 의미가
생겼다. 계산상 8.4 m 기준 0.9 -> 1.2 는 -18.7%, -> 1.6 은 -30.7% 다.

계획은 **안 건드린다.** `geom.v_max`(= SPEED_PLAN 0.9)가 틱 길이와 ADG 릴리스
일정을 정하므로 그대로 두고, 실행 상한만 `PIBT_V_EXEC` 로 올린다. 실행이
계획보다 빠른 것은 안전한 방향이다 — ADG 는 순서로만 돌기 때문에 일찍 도착하면
선행을 기다린다.

★ 속도를 올릴 때 반드시 같이 볼 것
    접촉      0 이 아니면 그 값은 못 쓴다
    최소거리  줄어드는 추세면 다음 값은 위험하다
    완주      안 줄면 병목이 속도가 아니다 (지금은 ADG 대기 45.7%)

    source paths.sh
    python tools/speed_sweep.py
    V=0.9,1.2,1.6 A=0.8,1.1 SEEDS=1,2 python tools/speed_sweep.py
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.environ["W"], "path"))
import pibt_core_v2                      # noqa: F401
from pibt_core import run_h              # noqa: E402
import isaac_drive as D                  # noqa: E402
from pibt_scene import setup             # noqa: E402

MAP = os.environ["MAP"]
N = int(os.environ.get("N", "12"))
PITCH = float(os.environ.get("PIBT_PITCH", "1.0"))
SEEDS = [int(x) for x in os.environ.get("SEEDS", "1,2").split(",")]
VS = [float(x) for x in os.environ.get("V", "0.9,1.2,1.6,2.2").split(",")]
AS_ = [float(x) for x in os.environ.get("A", "0.8").split(",")]
DT = 1.0 / 60.0
LIMIT = 400000


def one(geom, free, starts, goals, seed, v, a):
    history, _ = run_h(free, starts, goals, max_steps=150)
    chains, order, _ = D.extract_actions(history, geom)
    adg = D.build_adg(chains)
    if adg.topological_order() is None:
        return None
    drivers = D.make_kinematic_drivers(geom, starts, seed=seed)
    fleet = D.FleetController(geom, adg, drivers, order=order,
                              v_exec=v, a_exec=a)
    for _ in range(LIMIT):
        fleet.step(DT)
        for d in drivers.values():
            d.integrate(DT)
        if fleet.finished:
            break
    return fleet


def sweep_one(v, a):
    """속도·가속 한 조합 — 전 시드를 돌려 합친다.

    (완주시간들, 접촉, 칸공유, 최악여유, 이어감, 완주수). ADG 가 순환이면
    그 시드는 빠지므로, 완주시간 목록이 비면 그 조합은 잴 것이 없다는 뜻이다.
    """
    ts, ct, ov, gap, cr, fin = [], 0, 0, 9e9, 0, 0
    for s in SEEDS:
        geom, free, starts, goals = setup(MAP, N, PITCH, s, "cross")
        f = one(geom, free, starts, goals, s, v, a)
        if f is None:
            continue
        ts.append(f.stats.sim_time)
        ct += f.stats.contact_events
        ov += f.stats.overlap_events
        gap = min(gap, f.stats.worst_gap)
        cr += f.stats.carried
        fin += bool(f.finished)
    return ts, ct, ov, gap, cr, fin


def print_row(v, a, agg, base):
    """한 줄을 찍고 **기준 완주 시간**을 돌려준다.

    기준은 표에서 처음 성공한 줄이다 — 그 줄부터 아래로 몇 % 줄었는지 읽는다.
    """
    ts, ct, ov, gap, cr, fin = agg
    if not ts:
        print(f"{v:>8.2f}{a:>8.2f}   (ADG 순환)")
        return base
    m = sum(ts) / len(ts)
    if base is None:
        base = m
    g = "—" if gap > 1e8 else f"{gap:.3f}"
    mark = "  ★접촉" if ct else ""
    print(f"{v:>8.2f}{a:>8.2f}{m:>10.1f}{(m-base)/base*100:>9.1f}%"
          f"{ct:>7d}{ov:>8d}{g:>12}{cr // len(ts):>8d}"
          f"{fin:>4d}/{len(ts)}{mark}")
    return base


def print_header():
    print(f"대수 {N}  pitch {PITCH}  시드 {SEEDS}")
    print("계획 속도(geom.v_max) 는 그대로 두고 **실행 상한**만 바꾼다\n")
    print(f"{'v_exec':>8}{'a_exec':>8}{'완주 s':>10}{'기준대비':>10}"
          f"{'접촉':>7}{'칸공유':>8}{'최소거리 m':>12}{'이어감':>8}{'완주':>7}")


def main():
    # 환경변수가 인자를 이기므로, 쓸어보는 동안은 비워 둔다.
    os.environ.pop("PIBT_V_EXEC", None)
    os.environ.pop("PIBT_A_EXEC", None)
    print_header()
    base = None
    for a in AS_:
        for v in VS:
            base = print_row(v, a, sweep_one(v, a), base)
    print("\n접촉이 0 이 아닌 줄은 채택 불가다. 완주가 안 줄면 병목이 속도가")
    print("아니다 — 지금 ADG 대기가 전체의 45.7% 다.")


if __name__ == "__main__":
    main()
