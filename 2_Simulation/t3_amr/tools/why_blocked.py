# -*- coding: utf-8 -*-
"""ADG 대기가 **진짜 경합**인가 **얼어붙은 순서** 때문인가.

[문제] 대기가 완주 시간의 23.8% 이고 `[adg-why]` 는 100% 가 `ADG선행` 이라고만
말한다. 그런데 그것만으로는 ADG 구조를 고쳐야 하는지 알 수 없다.

    진짜 경합       막는 로봇이 바로 앞에 있다. 순서를 바꿔도 누군가는 기다린다
    얼어붙은 순서   막는 로봇이 멀리 있다. 계획 시점 순서 때문에 기다리는 것이고,
                    실행 중 순서를 바꿀 수 있다면 안 기다려도 된다

`_key()` 가 `(tick, sub, agent)` 전순서로 type 2 엣지 방향을 정하므로, 계획에서
A 가 먼저였으면 실행에서 B 가 먼저 도착해도 A 를 기다린다. 그 대가가 얼마인지
재는 것이 이 도구다.

[방법] 막힌 프레임마다 `AdgRuntime.blocking()` 으로 막는 액션을 얻고, 그 액션의
주인 로봇까지의 **실제 거리**를 잰다. 가장 가까운 막는 로봇의 거리로 분류한다.

Isaac 이 필요 없다. 순서 문제라 물리 잡음은 무관하고, 운동학으로 충분하다.

    source paths.sh
    python tools/why_blocked.py
    SEEDS=1,2,4 STRIDE=6 python tools/why_blocked.py
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
STRIDE = int(os.environ.get("STRIDE", "6"))      # 몇 스텝마다 표본을 뜰까 (60Hz -> 10Hz)
DT = 1.0 / 60.0
LIMIT = 400000

# 분류 경계 [m]. 차체가 1.5 m 이므로 3.0 m = 두 대 길이.
NEAR, MID = 3.0, 7 * PITCH               # 3.0 / 8.4


def plan_and_fleet(seed):
    """계획해서 (fleet, drivers, uid2act) 를 만든다. ADG 가 순환이면 None."""
    geom, free, starts, goals = setup(MAP, N, PITCH, seed, "cross")
    history, _ = run_h(free, starts, goals, max_steps=150)
    chains, order, _ = D.extract_actions(history, geom)
    adg = D.build_adg(chains)
    if adg.topological_order() is None:
        return None
    drivers = D.make_kinematic_drivers(geom, starts, seed=seed)
    fleet = D.FleetController(geom, adg, drivers, order=order)
    return fleet, drivers, {a.uid: a for a in adg.actions}


def blockers_of(fleet, a):
    """로봇 a 가 **지금 기다리는 원인 액션**들. 없으면 빈 목록.

    돌지 않는 경우가 셋이다 — 이미 실행 중이거나, 다음 액션이 없거나 바로
    시작할 수 있거나, 막는 것이 로봇이 아니라 릴리스 지평인 경우다.
    마지막 것은 **로봇 탓이 아니라서** 표본에서 뺀다.
    """
    if fleet.running[a] is not None:
        return []
    nxt = fleet.rt.pending(fleet.slot[a])
    if nxt is None or fleet.rt.can_start(nxt):
        return []
    return [u for u in fleet.rt.blocking(nxt) if u >= 0]


def nearest_blocker(drivers, uid2act, a, blk):
    """막는 로봇들 중 **가장 가까운** 거리 [m]. 잴 것이 없으면 None."""
    x, y, _ = drivers[a].axle_pose()
    best = None
    for u in blk:
        b = uid2act.get(u)
        if b is None or b.agent not in drivers:
            continue
        bx, by, _ = drivers[b.agent].axle_pose()
        dd = math.hypot(bx - x, by - y)
        best = dd if best is None else min(best, dd)
    return best


def sample_frame(fleet, drivers, uid2act, dists, nblk):
    """이 프레임에서 막힌 로봇마다 가장 가까운 막는 로봇 거리를 모은다."""
    for a in fleet.agents:
        blk = blockers_of(fleet, a)
        if not blk:
            continue
        best = nearest_blocker(drivers, uid2act, a, blk)
        if best is None:
            continue
        dists.append(best)
        nblk.append(len(blk))


def drive_and_sample(fleet, drivers, uid2act):
    """주행하면서 STRIDE 스텝마다 표본을 뜬다 — (거리들, 막는 수들)."""
    dists, nblk = [], []
    step = 0
    while step < LIMIT:
        fleet.step(DT)
        for d in drivers.values():
            d.integrate(DT)
        step += 1
        if fleet.finished:
            break
        if step % STRIDE:
            continue
        sample_frame(fleet, drivers, uid2act, dists, nblk)
    return dists, nblk


def summarise(seed, fleet, dists, nblk):
    """거리 표본을 근접/중간/원거리로 나눈다. 표본이 없으면 None."""
    tot = len(dists)
    if not tot:
        return None
    near = sum(1 for d in dists if d < NEAR)
    mid = sum(1 for d in dists if NEAR <= d < MID)
    far = tot - near - mid
    s = sorted(dists)
    return dict(seed=seed, t=fleet.stats.sim_time, samples=tot,
                near=near / tot, mid=mid / tot, far=far / tot,
                med=s[len(s) // 2], p90=s[int(len(s) * 0.9)],
                blk=sum(nblk) / len(nblk))


def run_one(seed):
    got = plan_and_fleet(seed)
    if got is None:
        return None
    fleet, drivers, uid2act = got
    return summarise(seed, fleet, *drive_and_sample(fleet, drivers, uid2act))


def main():
    print(f"대수 {N}  pitch {PITCH}  시드 {SEEDS}  표본 간격 {STRIDE}스텝")
    print(f"분류: 근접 < {NEAR:.1f} m  ·  중간 < {MID:.1f} m  ·  원거리 그 이상\n")
    print(f"{'시드':>5}{'완주 s':>9}{'표본':>9}{'근접':>8}{'중간':>8}{'원거리':>8}"
          f"{'중앙 m':>9}{'p90 m':>9}{'막는수':>8}")
    agg = []
    for s in SEEDS:
        r = run_one(s)
        if r is None:
            print(f"{s:>5}  (ADG 순환 또는 표본 없음)")
            continue
        agg.append(r)
        print(f"{r['seed']:>5}{r['t']:9.1f}{r['samples']:9d}"
              f"{r['near']*100:7.1f}%{r['mid']*100:7.1f}%{r['far']*100:7.1f}%"
              f"{r['med']:9.2f}{r['p90']:9.2f}{r['blk']:8.2f}")
    if agg:
        n = len(agg)
        print(f"\n{'평균':>5}{'':>9}{'':>9}"
              f"{sum(r['near'] for r in agg)/n*100:7.1f}%"
              f"{sum(r['mid'] for r in agg)/n*100:7.1f}%"
              f"{sum(r['far'] for r in agg)/n*100:7.1f}%")
    print("\n원거리가 크면 **계획 시점에 얼어붙은 순서** 때문에 기다리는 것이다.")
    print("근접이 대부분이면 진짜 경합이고, ADG 순서를 바꿔도 나아지지 않는다.")


if __name__ == "__main__":
    main()
