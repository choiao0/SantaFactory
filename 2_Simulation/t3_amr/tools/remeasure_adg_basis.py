# -*- coding: utf-8 -*-
"""§4 재측정 — ADG 를 무엇으로 짓느냐에 따라 **접촉**이 몇 건 나는가.

문서 `docs/2026-09-13_격자_1.2m_근거.md` §4 의 표는 `overlap_events`(칸 공유)로
잰 것이다. 칸 공유는 접촉과 다르다 — 칸은 겹치는데 차체는 568 mm 떨어진 쌍이
실제로 있었다 (2026-09-13). `FleetStats` 가 이제 둘을 나눠 세므로 다시 잰다.

Isaac 이 필요 없다. `make_kinematic_drivers` 로 순수 파이썬 주행이다.

    source paths.sh
    python tools/remeasure_adg_basis.py            # 시드 2 · 판 2
    SEEDS=4 RUNS=2 python tools/remeasure_adg_basis.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.environ["W"], "path"))
import pibt_core_v2                      # noqa: F401  sys.modules["pibt_core"] 등록
from pibt_core import run_h              # noqa: E402
import isaac_drive as D                  # noqa: E402
from pibt_scene import setup             # noqa: E402

MAP = os.environ["MAP"]
N = int(os.environ.get("N", "12"))
PITCH = float(os.environ.get("PIBT_PITCH", "1.2"))
SEEDS = int(os.environ.get("SEEDS", "2"))
RUNS = int(os.environ.get("RUNS", "2"))
DT = 1.0 / 60.0


def chains_from(history, cells_hist, geom, basis):
    """`extract_actions` 와 같되 액션이 잡는 칸의 **근거만** 바꾼다."""
    agents = sorted(history[0])
    chains = [[] for _ in agents]
    index = {a: i for i, a in enumerate(agents)}
    uid = 0
    for t in range(len(history) - 1):
        for a in agents:
            s0, s1 = history[t][a], history[t + 1][a]
            kind = D.classify(s0, s1)
            if kind == D.WAIT:
                continue
            i = index[a]
            cells = (geom.swept_cells(s0, s1) if basis == "sweep"
                     else frozenset(cells_hist[t][a]))
            chains[i].append(D.Action(agent=a, idx=len(chains[i]), kind=kind,
                                      tick=t, frm=s0, to=s1, cells=cells, uid=uid))
            uid += 1
    return chains, agents


# 계획기는 **못 푸는 시나리오를 SystemExit 로 알린다.** 시드 하나가 안 풀려도
# 나머지 시드로 표를 낼 수 있으니 그 신호만 잡고 넘어간다.
#
#   [잡는다] 계획기 정체 — 이 시드만 못 푼다. 다음 시드는 의미가 있다
#     _pibt_core_vendor.py:840  "PIBT(헤딩) 정체: N스텝 내 미도달 {...}"
#     `run_h` 가 내는 SystemExit 은 **이것 하나뿐**이다
#
#   [안 잡는다] 그 밖의 SystemExit — 시드와 무관한 사정이다. 그대로 올린다
#
# ★ `setup` 은 여기서 잡지 않는다. 맵·pitch·스테이션 오류라 시드마다 다를 수가
#   없고, 잡으면 같은 메시지가 시드 수만큼 찍힐 뿐이다.
# ★ 옛 코드는 `RuntimeError` 도 함께 잡았다. 그런데 계획기에는 그것을 내는
#   자리가 **없다** — `_pibt_core_vendor.py` 에 `RuntimeError` 0건이고, 시작
#   상태·목표 도달 가능성은 `assert` 라 AssertionError 다. 죽은 절이라 뺐다.
_PLANNER_STALL = ("정체", "미도달")


def plan_one(sd):
    """시드 하나를 계획한다. 계획기가 못 풀면 None."""
    geom, free, starts, goals = setup(MAP, N, PITCH, sd, "cross")
    try:
        history, cells_hist = run_h(free, starts, goals, max_steps=150)
    except SystemExit as e:
        if not any(k in str(e) for k in _PLANNER_STALL):
            raise               # 계획기 정체가 아니다 — 삼키지 않는다
        print(f"  seed {sd}: run_h 실패 — {e}")
        return None
    return (sd, geom, starts, history, cells_hist)


def collect_plans():
    """시드를 전부 계획한다. 하나도 못 내면 거기서 끝낸다."""
    plans = [p for p in (plan_one(sd) for sd in range(SEEDS)) if p]
    if not plans:
        raise SystemExit("★ 계획이 하나도 안 나왔습니다.")
    return plans


def print_audit(plan):
    """첫 계획으로 기하와 예약 감사를 찍는다."""
    _sd, geom, _starts, history, cells_hist = plan
    print(geom.describe())
    aud = D.sweep_audit(geom, history, cells_hist)
    print(f"\n예약 감사: 전이 {aud['total']}건 중 예약 < 실제 스윕 "
          f"{aud['short']}건  {aud['by_kind']}")


def drive_once(geom, adg, starts, order, seed):
    """한 판 주행 — 끝난 `FleetController` 를 돌려준다."""
    drivers = D.make_kinematic_drivers(geom, starts, seed=seed)
    fleet = D.FleetController(geom, adg, drivers, order=order)
    for _ in range(200000):
        fleet.step(DT)
        for d in drivers.values():
            d.integrate(DT)
        if fleet.finished:
            break
    return fleet


def run_basis(basis, plans):
    """근거 하나로 전 시드·전 판을 돌린다 — (주행, 접촉, 칸공유, 최악여유, 완주)."""
    runs = contact = share = done = 0
    worst = float("inf")
    for sd, geom, starts, history, cells_hist in plans:
        chains, order = chains_from(history, cells_hist, geom, basis)
        adg = D.build_adg(chains)
        if adg.topological_order() is None:
            print(f"  [{basis}] seed {sd}: ADG 순환 — 건너뜀")
            continue
        for rs in range(RUNS):
            fleet = drive_once(geom, adg, starts, order, rs * 7 + sd)
            runs += 1
            done += bool(fleet.finished)
            contact += fleet.stats.contact_events
            share += fleet.stats.overlap_events
            worst = min(worst, fleet.stats.worst_gap)
    return runs, contact, share, worst, done


def print_table(plans):
    """두 근거를 같은 계획·같은 시드로 나란히 비교한다."""
    print("\n" + "=" * 74)
    print(f"{'ADG 근거':>12} | {'주행':>4} | {'접촉':>7} | {'칸 공유':>8} | "
          f"{'최소 차체거리':>12} | 완주")
    print("=" * 74)
    for basis in ("sweep", "cells_hist"):
        runs, contact, share, worst, done = run_basis(basis, plans)
        w = "—" if worst == float("inf") else f"{worst * 1000:+.1f} mm"
        print(f"{basis:>12} | {runs:>4} | {contact:>7} | {share:>8} | {w:>12} | "
              f"{done}/{runs}")
    print("=" * 74)
    print("접촉 = 차체가 실제로 닿은 건수 (body_gap <= 0)")
    print("칸 공유 = 발자국 칸이 겹친 건수 — 접촉의 상한이지 접촉이 아니다")


def main():
    plans = collect_plans()
    print_audit(plans[0])
    print_table(plans)


if __name__ == "__main__":
    main()
