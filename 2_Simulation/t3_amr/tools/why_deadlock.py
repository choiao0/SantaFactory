# -*- coding: utf-8 -*-
"""회전이 **왜 끝날 수 없는지** 를 기하로 확정한다 (S15P21A106-224).

무엇을 재는가
-------------
2026-09-16 시드 7 에서 agent6 이 같은 자리에서 두 판 연속 멈췄다.

    A6#85 turn(46, 50, 3)->(46, 50, 0)@t646
    pose = (50.14, 46.44, 90deg)        목표 칸 중심 = (50.5, 46.5)

`yaw` 는 목표(heading 0 = 90도)에 도달했다. 그러면 `at_target()` 은 참이다
(회전은 각도만 본다). 남는 것은 `complete()` 의 **둘째 조건** 하나다:

    return not (body & action.released)          # isaac_drive.py

`released = cells - rest` 이고 회전의 `cells` 는 **스윕 전체**다. 축이 밀린
채로 회전이 끝나면 몸이 스윕 칸을 아직 물고 있을 수 있고, 회전은 `v = 0`
이라 축을 되돌릴 수단이 없다 -- 그러면 **영원히** 못 끝낸다.

이 도구는 그게 맞는지 실제 `geom` 과 실제 `occupied` 로 확인하고, 이어서
**얼마나 밀리면 못 끝내는지** 를 잰다. 그 여유값이 이 문제의 예산이다.

쓰는 법
-------
    source paths.sh
    PITCH=1.0 python tools/why_deadlock.py

    FRM/TO    "행,열,헤딩" (기본 46,50,3 / 46,50,0)
    POSE      "x,y,yaw도"  (기본 50.14,46.44,90)
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.environ["W"], "path"))

import pibt_scene                                            # noqa: E402
import isaac_drive as idr                                    # noqa: E402
from pibt_core import occupied                               # noqa: E402

PITCH = float(os.environ.get("PITCH", os.environ.get("PIBT_PITCH", "1.0")))


def parse(s, n=3):
    v = [float(x) for x in s.split(",")]
    if len(v) != n:
        raise SystemExit(f"★ 값 {n}개가 필요합니다: {s!r}")
    return v


def main():
    frm = tuple(int(v) for v in parse(os.environ.get("FRM", "46,50,3")))
    to = tuple(int(v) for v in parse(os.environ.get("TO", "46,50,0")))
    px, py, pdeg = parse(os.environ.get("POSE", "50.14,46.44,90"))
    pyaw = math.radians(pdeg)

    geom = pibt_scene.make_geom(PITCH)
    print(f"[why_deadlock] pitch {PITCH} · {geom.pivot_name}")
    print(f"   앞 {geom.front_len} · 뒤 {geom.rear_len} · 폭 {geom.width} · "
          f"heading_offset {geom.heading_offset}")

    tx, ty, tyaw = geom.state_pose(to)
    print(f"\n── 동작 ──")
    print(f"   turn{frm}->{to}")
    print(f"   목표 자세 ({tx:.3f}, {ty:.3f}, {math.degrees(tyaw):.1f}도)")
    print(f"   실측 자세 ({px:.3f}, {py:.3f}, {pdeg:.1f}도)")
    print(f"   축 이탈  ({(tx - px) * 1000:+.0f}, {(ty - py) * 1000:+.0f}) mm"
          f"   각 오차 {math.degrees(idr.wrap(tyaw - pyaw)):+.2f}도")

    cells = geom.swept_cells(frm, to)
    rest = frozenset(occupied(to))
    released = cells - rest
    # 4칸 규칙이 내놓는 앞 칸. `soft = guard & cells` 가 실제 soft 다.
    try:
        guard = geom.front_cells(frm, to)
    except Exception as e:
        guard = frozenset()
        print(f"   (front_cells 실패: {e!r})")
    soft = guard & cells
    print(f"\n── 칸 ──")
    print(f"   스윕 cells   {sorted(cells)}")
    print(f"   끝 자세 rest {sorted(rest)}")
    print(f"   4칸 guard    {sorted(guard)}"
          + (f"   (스윕 밖 {sorted(guard - cells)})" if guard - cells else ""))
    print(f"   soft         {sorted(soft)}   <- 코만 스치는 칸")
    print(f"   ★ released  {sorted(released)}   <- 이 칸들이 비어야 끝난다")

    body = geom.footprint_cells(px, py, pyaw)
    hit = body & released
    print(f"\n── 판정 ──")
    print(f"   실측 몸      {sorted(body)}")
    print(f"   몸 & released = {sorted(hit) or '없음'}")
    ok_yaw = abs(idr.wrap(tyaw - pyaw)) <= idr.Tolerance().yaw
    print(f"   at_target(각도만)  {'통과' if ok_yaw else '실패'}"
          f"   (tol.yaw {idr.Tolerance().yaw})")
    if hit:
        print(f"   ☠ complete() 는 **영원히 거짓**이다 — 회전은 v=0 이라")
        print(f"     축을 {sorted(hit)} 밖으로 되돌릴 수단이 없다.")
    else:
        print(f"   complete() 가 참이어야 한다 — 다른 원인을 봐야 한다.")

    # ── ★ soft 를 빼면 풀리나 (복구 대책 후보) ───────────────────────────
    #   soft 의 정의가 「상대의 **축**만 금지, 몸은 와도 된다」이므로, 몸이
    #   남아 있어도 놓아주는 것이 규칙 자체와 일관된다. `released` 만 지금
    #   `cells` 전체를 보고 있어 soft 칸까지 기다린다.
    slim_rel = released - soft
    slim_hit = body & slim_rel
    print(f"\n── 후보 — `released` 에서 soft 를 빼면 ──")
    print(f"   released - soft = {sorted(slim_rel) or '없음'}")
    print(f"   실측 몸과 교집합 = {sorted(slim_hit) or '없음'}")
    if hit and not slim_hit:
        print(f"   ★ **이 교착은 안 났다.** 막은 칸 {sorted(hit)} 이 전부 soft 다.")
        print(f"     (코만 스치는 칸을 몸이 빠질 때까지 기다린 것이다)")
    elif hit and slim_hit:
        print(f"   여전히 막힌다 — {sorted(slim_hit)} 은 soft 가 아니다.")
        print(f"     이 대책만으로는 안 풀린다.")

    print(f"\n   ※ 안전 논거는 따로 세워야 한다. soft 칸은 규칙상 상대의 **몸**이")
    print(f"     들어올 수 있으므로 일찍 놓아줘도 규칙과 모순은 없다. 다만 4칸의")
    print(f"     여유(41.4 mm)는 **이상적 자세** 기준이고, 여기서는 축이 밀린")
    print(f"     상태다. 그 조합을 재 봐야 한다.")

    # ── 얼마나 밀리면 못 끝내는가 ─────────────────────────────────────────
    print(f"\n── 여유 — 끝 자세에서 축이 얼마나 밀려도 되나 ──")
    print(f"   (끝 헤딩 그대로 두고 축만 옮겨 `body & released` 를 본다)")
    step = 0.005
    for lab, ux, uy in (("동 +x", 1.0, 0.0), ("서 -x", -1.0, 0.0),
                        ("북 +y", 0.0, 1.0), ("남 -y", 0.0, -1.0)):
        d = 0.0
        while d < 1.0:
            b = geom.footprint_cells(tx + ux * d, ty + uy * d, tyaw)
            if b & released:
                break
            d += step
        obs = ((px - tx) * ux + (py - ty) * uy)
        mark = f"   <- 실측 {obs * 1000:+.0f} mm" if obs > 1e-6 else ""
        print(f"     {lab}  {d * 1000:6.0f} mm 까지 안전{mark}")

    print(f"\n   읽는 법")
    print(f"    · 이 여유가 **회전 한 번의 위치 예산**이다. 회전 중 축이 이만큼")
    print(f"      밀리면 그 회전은 끝날 수 없다 (복구 수단이 없어서다).")
    print(f"    · 예산이 컨트롤러의 허용오차 `tol.pos` 보다 작으면 구조적이다 —")
    print(f"      정상 종료한 직진도 그 예산을 넘겨 놓을 수 있다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
