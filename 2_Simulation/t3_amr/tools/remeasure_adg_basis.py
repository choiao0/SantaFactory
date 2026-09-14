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


def main():
    plans = []
    for sd in range(SEEDS):
        geom, free, starts, goals = setup(MAP, N, PITCH, sd, "cross")
        try:
            history, cells_hist = run_h(free, starts, goals, max_steps=150)
        except (SystemExit, RuntimeError) as e:
            print(f"  seed {sd}: run_h 실패 — {e}")
            continue
        plans.append((sd, geom, starts, history, cells_hist))
    if not plans:
        raise SystemExit("★ 계획이 하나도 안 나왔습니다.")

    print(plans[0][1].describe())
    aud = D.sweep_audit(plans[0][1], plans[0][3], plans[0][4])
    print(f"\n예약 감사: 전이 {aud['total']}건 중 예약 < 실제 스윕 "
          f"{aud['short']}건  {aud['by_kind']}")

    print("\n" + "=" * 74)
    print(f"{'ADG 근거':>12} | {'주행':>4} | {'접촉':>7} | {'칸 공유':>8} | "
          f"{'최소 차체거리':>12} | 완주")
    print("=" * 74)
    for basis in ("sweep", "cells_hist"):
        runs = contact = share = done = 0
        worst = float("inf")
        for sd, geom, starts, history, cells_hist in plans:
            chains, order = chains_from(history, cells_hist, geom, basis)
            adg = D.build_adg(chains)
            if adg.topological_order() is None:
                print(f"  [{basis}] seed {sd}: ADG 순환 — 건너뜀")
                continue
            for rs in range(RUNS):
                drivers = D.make_kinematic_drivers(geom, starts, seed=rs * 7 + sd)
                fleet = D.FleetController(geom, adg, drivers, order=order)
                for _ in range(200000):
                    fleet.step(DT)
                    for d in drivers.values():
                        d.integrate(DT)
                    if fleet.finished:
                        break
                runs += 1
                done += bool(fleet.finished)
                contact += fleet.stats.contact_events
                share += fleet.stats.overlap_events
                worst = min(worst, fleet.stats.worst_gap)
        w = "—" if worst == float("inf") else f"{worst * 1000:+.1f} mm"
        print(f"{basis:>12} | {runs:>4} | {contact:>7} | {share:>8} | {w:>12} | "
              f"{done}/{runs}")
    print("=" * 74)
    print("접촉 = 차체가 실제로 닿은 건수 (body_gap <= 0)")
    print("칸 공유 = 발자국 칸이 겹친 건수 — 접촉의 상한이지 접촉이 아니다")


if __name__ == "__main__":
    main()
