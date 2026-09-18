# -*- coding: utf-8 -*-
"""정체 재계획이 **스스로를 먹여 살리는가** (S15P21A106-224).

무엇을 재는가
-------------
`stall_kind` 가 시드 14 의 8대 정체를 「위상 잠금 아님」으로 갈랐다. 그러면
「그럼 뭔가」가 남는다. 들여다보니 a8 은 막힌 게 아니라 **텅 빈 통로를 두고
반대쪽으로 53칸을 갔다** (목표까지 34 -> 89, 그동안 동쪽 교차통로 193칸에
로봇이 최대 1대).

원인은 거리장이 **둘**이라는 데 있다.

    lifelong.py:584   stag.update(a, goal, self.dm(goal)[s1])       <- 평소 거리장
    lifelong.py:477   d_now[a] = replan.dist_for(..., stag)         <- 우회 거리장

`liveness.py` 의 `dist_for` 는 `stag > REPLAN_AFTER` 면 주변 로봇을 벽으로
막은 우회 거리장을 만들어 `REPLAN_HOLD` 틱 유지한다. 그런데 —

    1  우회로 가면 **평소 거리장 기준** 거리가 늘어난다
    2  `stag` 는 그 평소 거리장으로 잰다. 리셋 조건은 `d < b` (**역대 최소**)
    3  우회 중에는 그 조건이 원리적으로 성립할 수 없다 -> stag 가 안 준다
    4  -> `stag > REPLAN_AFTER` 가 계속 참 -> hold 만료마다 새 우회 거리장,
         **매번 더 먼 곳에서**

끄는 장치가 없다. 목표에 닿거나 목표가 바뀌어야 풀린다.

이 도구는 그 고리를 **숫자로** 확정한다 — 로봇이 어느 거리장을 골랐는지
틱마다 세고, 그동안 평소 거리장 기준 거리가 어떻게 움직였는지 같이 본다.

읽는 법
-------
    우회 비율이 낮고 stag 가 오르내린다        장치가 의도대로 작동
    ★ 우회 비율이 1 에 가깝고 stag 가 단조 증가  **래치**다. 스스로 못 끈다

쓰는 법
-------
    source paths.sh
    python tools/replan_latch.py                 # 기본 3시드
    SEEDS=14 WATCH=8 python tools/replan_latch.py

    SEEDS      쉼표로 (기본 14,2,7)
    HORIZON    기본 1260
    N · GAP    기본 12 · 60
    RULE       앞 칸 규칙 (기본 4 — 주행과 같게)
    TOP        자세히 볼 로봇 수 (기본 3)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.environ["W"], "path"))
# 주행과 같은 환경을 스스로 맞춘다. 안 맞추면 **다른 계획**을 재게 된다
# (`lag_budget` · `stall_kind` 가 같은 덫에 걸렸었다).
os.environ.setdefault("PIBT_FRONT_RULE", os.environ.get("RULE", "4"))

import pibt_scene as PS                                      # noqa: E402

SEEDS = [int(s) for s in os.environ.get("SEEDS", "14,2,7").split(",") if s]
N = int(os.environ.get("N", "12"))
PITCH = float(os.environ.get("PIBT_PITCH", "1.0"))
HORIZON = int(os.environ.get("HORIZON", "1260"))
GAP = int(os.environ.get("GAP", "60"))
TOP = int(os.environ.get("TOP", "3"))


def run(seed):
    from lifelong import Kernel, run_lifelong

    geom, free, starts, goals = PS.setup_lifelong(
        os.environ["MAP"], N, PITCH, seed, "cross", verbose=False)
    zone = PS.charge_zone_cells(free, geom)
    hold = {}

    class Rec(Kernel):
        """`dist_for` 를 감싸 **어느 거리장을 줬는지** 기록한다.

        반환값이 `base` 와 같은 객체면 평소 거리장, 아니면 우회다. 값을
        비교하면 안 된다 — 같은 값이 나올 수도 있다. 객체 동일성이 답이다.
        """

        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            hold["k"] = self
            self.log = []            # (t, agent, 우회인가, stag, 평소거리)
            rp = self.replan
            orig = rp.dist_for
            kern = self

            def spy(a, t, states, extra, goal, base, stag):
                out = orig(a, t, states, extra, goal, base, stag)
                try:
                    d = int(base[states[a]])
                except Exception:
                    d = -1
                kern.log.append((t, a, out is not base, stag, d))
                return out
            rp.dist_for = spy

    _h, _c, li = run_lifelong(
        free, starts, goals, horizon=HORIZON, seed=seed, order_gap=GAP,
        shifts=("in", "out", "out"), zone_cells=zone, kernel_cls=Rec)
    return hold["k"].log, li


def main():
    print(f"[replan_latch] PIBT_FRONT_RULE="
          f"{os.environ.get('PIBT_FRONT_RULE')} · pitch {PITCH} · {N}대 · "
          f"horizon {HORIZON} · order_gap {GAP}")
    try:
        from liveness import REPLAN_AFTER, REPLAN_HOLD, REPLAN_RADIUS
    except Exception:
        REPLAN_AFTER = REPLAN_HOLD = REPLAN_RADIUS = None
        sys.path.insert(0, os.path.abspath(os.path.join(
            os.environ["W"], "..", "..", "3_FMS", "sim_engine")))
        try:
            from pibt.liveness import (REPLAN_AFTER, REPLAN_HOLD,   # noqa: F811
                                       REPLAN_RADIUS)
        except Exception:
            pass
    print(f"   REPLAN_AFTER={REPLAN_AFTER} · HOLD={REPLAN_HOLD} · "
          f"RADIUS={REPLAN_RADIUS}   (3_FMS/sim_engine/pibt/liveness.py)")

    grand = [0, 0]
    for seed in SEEDS:
        log, li = run(seed)
        tot = len(log)
        det = sum(1 for r in log if r[2])
        grand[0] += tot
        grand[1] += det
        print(f"\n══ 시드 {seed} ══  태스크 {li.get('tasks_done')}/"
              f"{li.get('tasks_spawned')} · stag_max {li.get('stag_max')} · "
              f"100틱+ {li.get('stag_stuck')}대")
        print(f"   거리장 선택 {tot:,}회 중 **우회 {det:,}회 "
              f"({det / max(tot, 1) * 100:.1f} %)**")

        # ★ 창을 로봇마다 따로 잡는다. 런 전체로 비율을 내면 래치가 **안
        #   보인다** — a8 은 정체 구간 안에서 96 %인데 런 전체로는 38 %다.
        #   래치는 구간 현상이라 구간에서 재야 한다.
        by_a = {}
        for row in log:
            by_a.setdefault(row[1], []).append(row)
        peak = {}
        for a, rows in by_a.items():
            t, sg = max(((r[0], r[3]) for r in rows), key=lambda x: x[1])
            peak[a] = (sg, t)

        rank = sorted(peak.items(), key=lambda kv: -kv[1][0])[:TOP]
        print(f"   ── 로봇별 **최대 정체 구간 안에서** ──")
        print(f"   {'로봇':>5}{'구간':>14}{'길이':>6}{'선택':>6}{'우회':>6}"
              f"{'비율':>8}{'시작거리':>9}{'최대이탈':>9}")
        for a, (sgm, tp) in rank:
            # 창은 「stag 0 -> 최대」다. 그래서 **끝 거리는 시작과 같기 마련**
            # 이다 (그 틱에 기록을 깨서 리셋된다). 신호는 «끝» 이 아니라
            # **얼마나 멀리 나갔다 왔나**다.
            lo, hi = max(0, tp - sgm), tp
            win = [r for r in by_a[a] if lo <= r[0] <= hi]
            if not win:
                continue
            n = len(win)
            d = sum(1 for r in win if r[2])
            db = [r[4] for r in win if r[4] >= 0]
            if not db:
                continue
            away = max(db) - db[0]
            ratio = d / max(n, 1)
            mark = ""
            if ratio > 0.8 and sgm >= 100:
                # 목표가 가까울수록 같은 이탈이 더 나쁘다 — 둘 다 본다.
                mark = ("   ★ 래치" if (away >= 10 or away >= db[0])
                        else "   우회고착")
            print(f"   a{a:<4}{f'{lo}~{hi}':>14}{sgm:>6}{n:>6}{d:>6}"
                  f"{ratio * 100:>7.1f}%{db[0]:>9}{away:>+9}{mark}")

    print(f"\n══ 합계 ══  거리장 선택 {grand[0]:,}회 중 우회 {grand[1]:,}회 "
          f"({grand[1] / max(grand[0], 1) * 100:.1f} %)")
    print(f"\n   읽는 법")
    print(f"    · `ReplanCache` 주석은 「정체 상황은 드물어 크기가 작다」고")
    print(f"      적혀 있다. 위 비율이 그 전제를 확인하거나 깬다.")
    print(f"    · 비율은 **런 전체가 아니라 그 로봇의 최대 정체 구간**에서 낸다.")
    print(f"      전체로 내면 래치가 안 보인다 (구간 96 % 가 전체로는 38 %).")
    print(f"    · 창이 「stag 0 -> 최대」라 **끝 거리는 시작과 같기 마련**이다")
    print(f"      (그 틱에 기록을 깨서 리셋된다). 그래서 «끝» 은 신호가 아니다.")
    print(f"      보는 것은 **최대이탈** — 목표에서 얼마나 멀어졌다 왔나다.")
    print(f"    · **★ 래치** = 우회 80 %+ · stag 100틱+ · 최대이탈이 10칸 이상")
    print(f"      이거나 시작거리보다 크다. 목표가 8칸인데 55칸까지 나갔다면")
    print(f"      그 왕복은 통째로 낭비다.")
    print(f"    · 고치는 방향은 상류(FMS) 몫이다. 정체를 **로봇이 실제로")
    print(f"      따라가는 거리장**으로 재거나, 우회를 채택할 때 `best` 를 그")
    print(f"      거리장 기준으로 다시 잡으면 고리가 끊긴다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
