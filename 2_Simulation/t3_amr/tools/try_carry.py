# -*- coding: utf-8 -*-
"""이어달리기(연속 주행) A/B — 매 칸 정지를 없애면 얼마나 빨라지나.

`FleetController(carry=False/True)` 만 바꿔 같은 계획·같은 시드로 돌린다.
Isaac 이 필요 없다 — `make_kinematic_drivers` 로 순수 파이썬 주행이다.

무엇을 보는가
-------------
  완주        carry 가 데드락을 만들지 않는지. 이게 깨지면 나머지는 볼 필요 없다
  접촉        `contact_events` 가 0 이어야 한다. 하나라도 나면 되돌린다
  이어간 횟수 `carried` — 실제로 몇 번 정지를 건너뛰었나 (0 이면 안 걸린 것)
  막힘        ADG 대기. **빨라지면 나빠질 수도 있다** — 충돌 지점에 더 빨리 모인다

    source paths.sh
    python tools/try_carry.py
    SEEDS=1,2,4 N=12 python tools/try_carry.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.environ["W"], "path"))
import pibt_core_v2                      # noqa: F401
from pibt_core import run_h              # noqa: E402
import isaac_drive as D                  # noqa: E402
from pibt_scene import setup             # noqa: E402

MAP = os.environ["MAP"]
N = int(os.environ.get("N", "12"))
PITCH = float(os.environ.get("PIBT_PITCH", "1.2"))
SEEDS = [int(x) for x in os.environ.get("SEEDS", "1,2").split(",")]
DT = 1.0 / 60.0
LIMIT = 400000


def one(geom, free, starts, goals, seed, carry):
    history, cells_hist = run_h(free, starts, goals, max_steps=150)
    chains, order, _ = D.extract_actions(history, geom)
    adg = D.build_adg(chains)
    if adg.topological_order() is None:
        return None
    drivers = D.make_kinematic_drivers(geom, starts, seed=seed)
    fleet = D.FleetController(geom, adg, drivers, order=order, carry=carry)
    for _ in range(LIMIT):
        fleet.step(DT)
        for d in drivers.values():
            d.integrate(DT)
        if fleet.finished:
            break
    return fleet


def main():
    print(f"대수 {N}  pitch {PITCH}  시드 {SEEDS}\n")
    rows = {}
    for seed in SEEDS:
        geom, free, starts, goals = setup(MAP, N, PITCH, seed, "cross")
        if seed == SEEDS[0]:
            margin = 0.5 * geom.pitch - geom.front_len
            print(f"기하: 칸 반폭 {0.5*geom.pitch:.3f} − 앞길이 {geom.front_len:.3f} "
                  f"= 여유 {margin:.3f} m")
            print(f"      이어달리기 종단속도 상한 "
                  f"min({geom.v_max:.2f}, sqrt(2·{geom.a_lin}·{margin:.3f})) = "
                  f"{min(geom.v_max, (2*geom.a_lin*margin) ** 0.5):.3f} m/s\n")
        for carry in (False, True):
            f = one(geom, free, starts, goals, seed, carry)
            if f is None:
                print(f"  seed {seed}: ADG 순환 — 건너뜀")
                continue
            rows.setdefault(carry, []).append(f.stats.sim_time)
            print(f"  seed {seed}  carry={str(carry):<5} "
                  f"완주 {str(f.finished):<5} "
                  f"시간 {f.stats.sim_time:7.1f}s  "
                  f"접촉 {f.stats.contact_events:5d}  "
                  f"칸공유 {f.stats.overlap_events:5d}  "
                  f"이어감 {f.stats.carried:5d}  "
                  f"액션 {f.stats.completed}")
        print()
    if len(rows.get(False, [])) == len(rows.get(True, [])) and rows.get(False):
        b = sum(rows[False]) / len(rows[False])
        c = sum(rows[True]) / len(rows[True])
        print(f"평균 완주 시간  carry=False {b:.1f}s -> carry=True {c:.1f}s  "
              f"{(c-b)/b*100:+.1f}%")


if __name__ == "__main__":
    main()
