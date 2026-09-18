# -*- coding: utf-8 -*-
"""soft 칸을 **일찍 놓아주면** 얼마나 위험한가 (S15P21A106-240).

무엇을 재는가
-------------
a6 교착의 대책 후보는 한 줄이다 (문서 §8-1).

    released = cells - rest              # 지금
    released = cells - soft - rest       # 후보

soft 의 정의가 「상대의 **축**만 금지, 몸은 와도 된다」이므로 몸이 남아 있어도
놓아주는 것이 규칙과 일관된다. 그런데 공짜가 아니다 — 코드 주석이 이렇게
적고 있다.

    `released`(완료 판정)는 지금도 `cells` 전체를 본다
    — **그게 이 변경의 안전 논거 절반이다**

즉 4칸 규칙을 들일 때 「`released` 는 전체를 본다」가 안전 근거로 쓰였다.
빼려면 그 논거를 다시 세워야 한다.

★ 재야 할 것이 정확히 무엇인가
------------------------------
4칸의 여유 **41.4 mm** 는 두 로봇이 **이상적 자세**로 섰을 때 값이다. 그런데
이 대책이 쓰이는 상황은 정의상 **축이 밀린** 상태다 (안 밀렸으면 교착이 안
난다). 그 조합은 아무도 안 재봤다.

그래서 이렇게 잰다.

    앞차 A   회전을 끝낸 자세에서 축을 **d 만큼 밀어** 둔다 (전 방향)
    뒤차 B   soft 칸에 축을 두지 않는 합법 자세 전부
    값       `geom.body_gap` 의 최소 — 두 차체 사각형 사이 실제 간격

밀림 d 는 실측 분포에서 가져온다. 마찰 4점 실측(2026-09-17):

    밀림 중앙 5.3 ~ 13.0 mm · p95 11.7 ~ 27.1 mm · 예산 105 mm

쓰는 법
-------
    source paths.sh
    PITCH=1.0 python tools/soft_release_safety.py

    FRM/TO   볼 회전 (기본 46,50,3 -> 46,50,0 — a6 의 그것)
    DMAX     밀림 최대 mm (기본 105 = 회전 한 번의 위치 예산)
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.environ["W"], "path"))
os.environ.setdefault("PIBT_FRONT_RULE", "4")

import pibt_scene                                            # noqa: E402
import isaac_drive as idr                                    # noqa: E402
from pibt_core import occupied                               # noqa: E402

PITCH = float(os.environ.get("PITCH", os.environ.get("PIBT_PITCH", "1.0")))
DMAX = float(os.environ.get("DMAX", "105")) / 1000.0
STEP = float(os.environ.get("DSTEP", "5")) / 1000.0
NDIR = int(os.environ.get("NDIR", "16"))


def parse(s):
    return tuple(int(v) for v in s.split(","))


def worst_for(geom, frm, to):
    """이 회전에서 (일찍 놓아줄 칸, 밀림 0 간격, 닿는 밀림) — 요약용."""
    cells = geom.swept_cells(frm, to)
    rest = frozenset(occupied(to))
    soft = geom.front_cells(frm, to) & cells
    early = sorted(soft & (cells - rest))
    if not early:
        return (0, None, None)
    ax, ay, ayaw = geom.state_pose(to)
    cand = []
    for cell in early:
        r, c = cell
        for dr in (-2, -1, 0, 1, 2):
            for dc in (-2, -1, 0, 1, 2):
                pr, pc = r + dr, c + dc
                if (pr, pc) in soft:
                    continue
                for h in range(4):
                    s = (pr, pc, h)
                    if cell in frozenset(occupied(s)) and not (
                            frozenset(occupied(s)) & rest):
                        cand.append((s, None))
                    for h2 in ((h + 1) % 4, (h - 1) % 4, (h + 2) % 4):
                        try:
                            sw = geom.swept_cells(s, (pr, pc, h2))
                        except Exception:
                            continue
                        if cell in sw and not (sw & rest):
                            cand.append((s, (pr, pc, h2)))
    if not cand:
        return (len(early), float("inf"), None)

    def gap_at(d):
        w = float("inf")
        for k in range(NDIR):
            th = 2.0 * math.pi * k / NDIR
            pa = (ax + d * math.cos(th), ay + d * math.sin(th), ayaw)
            for s0, s1 in cand:
                bx, by, b0 = geom.state_pose(s0)
                if s1 is None:
                    w = min(w, geom.body_gap(pa, (bx, by, b0)))
                    continue
                b1 = geom.state_pose(s1)[2]
                dth = (b1 - b0 + math.pi) % (2.0 * math.pi) - math.pi
                for m in range(13):
                    w = min(w, geom.body_gap(pa, (bx, by, b0 + dth * m / 12.0)))
            if d == 0.0:
                break
        return w

    base = gap_at(0.0)
    touch, d = None, 0.0
    while d <= DMAX + 1e-9:
        if gap_at(d) <= 0.0:
            touch = d
            break
        d += STEP * 4
    return (len(early), base, touch)


def sweep_all(geom):
    """**모든 회전 종류**에서 최악을 낸다 — 기하는 평행이동 불변이라 12가지다."""
    print(f"\n── ★ 모든 회전 종류 (12가지) ──")
    print(f"   {'회전':>12}{'일찍 놓는 칸':>14}{'밀림0 간격':>12}{'닿는 밀림':>12}")
    r0, c0 = 46, 50
    worst_base, worst_touch = float("inf"), None
    for h in range(4):
        for h2 in range(4):
            if h == h2:
                continue
            n, base, touch = worst_for(geom, (r0, c0, h), (r0, c0, h2))
            if n == 0:
                print(f"   h{h}->h{h2:<9}{'—':>14}{'(일찍 놓을 칸 없음)':>24}")
                continue
            worst_base = min(worst_base, base)
            if touch is not None:
                worst_touch = touch if worst_touch is None else min(
                    worst_touch, touch)
            print(f"   h{h}->h{h2:<9}{n:>14}{base * 1000:>12.1f}"
                  f"{('%.0f' % (touch * 1000)) if touch is not None else '안 닿음':>12}")
    print(f"\n   ★ 전 종류 최악  밀림0 간격 {worst_base * 1000:.1f} mm"
          + (f" · 닿는 밀림 {worst_touch * 1000:.0f} mm" if worst_touch
             is not None else f" · 예산 {DMAX * 1000:.0f} mm 까지 안 닿음"))
    return worst_base, worst_touch


def main():
    frm = parse(os.environ.get("FRM", "46,50,3"))
    to = parse(os.environ.get("TO", "46,50,0"))
    geom = pibt_scene.make_geom(PITCH)
    print(f"[soft_release_safety] pitch {PITCH} · turn{frm}->{to}")
    print(f"   앞 {geom.front_len} · 뒤 {geom.rear_len} · 폭 {geom.width}")

    cells = geom.swept_cells(frm, to)
    rest = frozenset(occupied(to))
    guard = geom.front_cells(frm, to)
    soft = guard & cells
    released_now = cells - rest
    released_new = released_now - soft
    print(f"\n── 칸 ──")
    print(f"   soft            {sorted(soft)}")
    print(f"   released 지금   {sorted(released_now)}")
    print(f"   released 후보   {sorted(released_new)}"
          f"   (일찍 놓아주는 칸 {sorted(soft & released_now)})")

    early = sorted(soft & released_now)
    if not early:
        print(f"\n   일찍 놓아줄 칸이 없다 — 이 회전에는 대책이 안 걸린다")
        return 0

    # ── 뒤차가 설 수 있는 자세 ────────────────────────────────────────────
    #   soft 는 「상대의 **축**만 금지」다. 그러므로 뒤차의 축 칸은 soft 가
    #   아닌 칸이어야 하고, 몸(앞칸+뒤칸)은 soft 에 들어와도 된다.
    ax, ay, ayaw = geom.state_pose(to)
    peers = []
    for cell in early:
        r, c = cell
        for dr in (-2, -1, 0, 1, 2):
            for dc in (-2, -1, 0, 1, 2):
                pr, pc = r + dr, c + dc
                if (pr, pc) in soft:
                    continue                    # 축은 soft 에 못 둔다
                for h in range(4):
                    s = (pr, pc, h)
                    body = frozenset(occupied(s))
                    if cell not in body:
                        continue                # 그 칸에 몸이 와야 의미가 있다
                    if body & rest:
                        continue                # 앞차 끝 자세와 겹치면 불법
                    peers.append(s)
    peers = sorted(set(peers))

    # ★ 정지 자세만 보면 안 된다 (2026-09-17). 41.4 mm 라는 값 자체가 **두 대가
    #   동시에 회전**할 때 나온 것이다 (답신 11 §1, 로그의 「동시 회전 두 대의
    #   soft 가 겹쳤다」). 뒤차가 그 칸을 **스치고 지나가는** 경우를 넣는다.
    #
    #   뒤차의 축이 soft 밖이고, 회전 스윕이 일찍 놓아준 칸에 들어오면 대상이다.
    sweeps = []
    for cell in early:
        r, c = cell
        for dr in (-2, -1, 0, 1, 2):
            for dc in (-2, -1, 0, 1, 2):
                pr, pc = r + dr, c + dc
                if (pr, pc) in soft:
                    continue
                for h in range(4):
                    for h2 in ((h + 1) % 4, (h - 1) % 4, (h + 2) % 4):
                        s0, s1 = (pr, pc, h), (pr, pc, h2)
                        try:
                            sw = geom.swept_cells(s0, s1)
                        except Exception:
                            continue
                        if cell not in sw or (sw & rest):
                            continue
                        sweeps.append((s0, s1))
    sweeps = sorted(set(sweeps))

    print(f"\n── 뒤차 후보 ──")
    print(f"   정지 자세 {len(peers)}개 · **회전 스윕 {len(sweeps)}개**")
    print(f"   (축은 soft 밖 · 몸/스윕이 일찍 놓아준 칸에 들어옴 · rest 와 안 겹침)")
    if not peers and not sweeps:
        print(f"   없다 — 이 칸은 뒤차가 몸으로도 못 들어온다. **위험이 없다**")
        return 0

    # ── 앞차를 밀면서 최소 간격 ──────────────────────────────────────────
    print(f"\n── 앞차 축을 밀면서 두 차체 최소 간격 ──")
    print(f"   {'밀림 mm':>9}{'최소 간격 mm':>14}   최악 조합")
    base = None
    rows = []
    d = 0.0
    while d <= DMAX + 1e-9:
        worst, worst_at = float("inf"), None
        for k in range(NDIR):
            th = 2.0 * math.pi * k / NDIR
            pa = (ax + d * math.cos(th), ay + d * math.sin(th), ayaw)
            for s in peers:
                pb = geom.state_pose(s)
                g = geom.body_gap(pa, pb)
                if g < worst:
                    worst, worst_at = g, (math.degrees(th), f"정지 {s}")
            # ★ 회전 중인 뒤차 — 스윕을 각도로 훑는다
            for s0, s1 in sweeps:
                bx, by, b0 = geom.state_pose(s0)
                _bx, _by, b1 = geom.state_pose(s1)
                dth = (b1 - b0 + math.pi) % (2.0 * math.pi) - math.pi
                for m in range(13):
                    pb = (bx, by, b0 + dth * m / 12.0)
                    g = geom.body_gap(pa, pb)
                    if g < worst:
                        worst, worst_at = g, (math.degrees(th),
                                              f"회전 {s0}->{s1}")
            if d == 0.0:
                break                           # 0 이면 방향이 무의미
        rows.append((d, worst))
        if base is None:
            base = worst
        mark = ""
        if worst <= 0.0:
            mark = "   ☠ 닿는다"
        elif worst < 0.0414:
            mark = "   ★ 4칸 설계 여유(41.4mm) 아래"
        print(f"   {d * 1000:>9.0f}{worst * 1000:>14.1f}   "
              f"{worst_at[0]:>5.0f}도 · 뒤차 {worst_at[1]}{mark}")
        d += STEP if d < 0.02 else STEP * 4

    print(f"\n── 판정 ──")
    print(f"   이상적 자세 (밀림 0)          {base * 1000:.1f} mm")
    touch = next((d for d, g in rows if g <= 0.0), None)
    below = next((d for d, g in rows if g < 0.0414), None)
    if touch is not None:
        print(f"   ☠ **닿기 시작하는 밀림      {touch * 1000:.0f} mm**")
    else:
        print(f"   밀림 {DMAX * 1000:.0f} mm 까지 안 닿는다")
    if below is not None:
        print(f"   41.4 mm 아래로 내려가는 밀림 {below * 1000:.0f} mm")

    sweep_all(geom)

    print(f"\n   읽는 법")
    print(f"    · 닿는 밀림이 **실측 p95(11.7~27.1 mm)보다 크면** 이 대책은")
    print(f"      안전하다. 평상 주행이 거기까지 안 간다.")
    print(f"    · 예산 105 mm 안에서 닿으면, 교착을 푸는 대신 **접촉을 여는**")
    print(f"      셈이다. 그러면 밀림에 상한을 걸어야 한다.")
    print(f"    · 41.4 mm 는 4칸 규칙을 들일 때 쓴 설계 여유다. 그 아래로")
    print(f"      내려가는 것 자체는 위반이 아니지만, **논거가 약해진다.**")
    return 0


if __name__ == "__main__":
    sys.exit(main())
