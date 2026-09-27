# -*- coding: utf-8 -*-
"""회전이 쓸고 가는 칸이 **실제로 비어 있나** (S15P21A106-240).

왜 이것을 묻나
--------------
`A3#253 turn(46,68,3)->(46,68,0)` 이 **시작 48.4 mm -> 끝 363.4 mm** 로 밀렸다.
가설을 셋 세우고 셋 다 닫았다.

    계단 입력          각가속 램프(W_ACCEL=20)로 A/B -> 363.4 vs 375.5. **안 변했다**
    이어달리기 관성     `_carry` 가 `_same_dir` 로 막는다 — 회전엔 속도를 못 싣는다
    한쪽 바퀴 정지      회전 중심 역산 결과 차체 **(+187, -133) mm · |r| 229**.
                        구동바퀴 (0, ±250) 도, 캐스터 (-1110, 0) 도 아니다

**어느 부품도 아닌 점**이 중심이면 순수 회전이 아니다 — 회전에 **떠밀림**이
섞였다는 뜻이다. 그래서 다음 물음은 「무엇이 밀었나」이고, 제일 싼 후보가
**정적 장애물**이다. 꼬리가 길기 때문이다.

    rear_len 1.11 · width 0.80  ->  뒤 모서리 반지름 hypot(1.11, 0.40) = **1.18 m**

1 m 격자에서 1.18 m 짜리 팔을 90도 돌린다. `swept_cells` 는 이걸 48 샘플로
굽어 **예약은 제대로 한다.** 그러나 예약은 「남의 로봇」을 막을 뿐이고,
**랙은 예약으로 안 비켜난다.** 스윕 안에 막힌 칸이 있으면 부딪친다.

이 도구는 그것만 본다. Isaac 이 필요 없다 — 맵과 기하만 읽는다.

    python tools/turn_sweep_check.py                 # a6 의 그 회전
    python tools/turn_sweep_check.py 46 68 3 0       # 임의의 제자리 회전
    ALL=1 python tools/turn_sweep_check.py           # 맵 전체 회전 가능 칸 훑기

☹ 한계 — 「막힌 칸을 스치나」는 답하지만 **실제로 닿았나**는 아니다.
  칸이 막혔어도 랙이 칸 한가운데 얇게 서 있으면 안 닿을 수 있다.
  다만 **막힌 칸을 안 스치면 이 가설은 닫힌다.** 부정 쪽이 강한 검사다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.environ["W"], "path"))
os.environ.setdefault("PIBT_RECOVER", "0")
import pibt_scene as PS                                # noqa: E402
import pibt_core_v2 as PC                              # noqa: E402
import isaac_drive as D                                # noqa: E402
from turn_sweep_mask import penetrate                  # noqa: E402
from turn_sweep_mask import load_obstacle_mask as load_mask   # noqa: E402

PITCH = float(os.environ.get("PIBT_PITCH", "1.0"))
MAP = os.environ.get("PIBT_MAP",
                     os.path.join(os.environ["W"], "warehouse/map"))
DEFAULT = (46, 68, 3, 0)          # a6 가 밀린 바로 그 회전


def check(free, geom, r, c, h0, h1, quiet=False):
    """(막힌 칸 목록, 스윕 칸 수, 예약 칸 수)."""
    s0, s1 = (r, c, h0), (r, c, h1)
    sweep = geom.swept_cells(s0, s1)
    resv = frozenset(D.occupied(s0)) | frozenset(D.occupied(s1))
    R, C = free.shape
    bad = []
    for (rr, cc) in sorted(sweep):
        if not (0 <= rr < R and 0 <= cc < C):
            bad.append(((rr, cc), "맵 밖"))
        elif not free[rr, cc]:
            bad.append(((rr, cc), "막힌 칸"))
    if not quiet:
        print(f"  {s0} -> {s1}")
        print(f"    스윕 {len(sweep)}칸 {sorted(sweep)}")
        print(f"    예약(점유 합집합) {len(resv)}칸 {sorted(resv)}")
        print(f"    스윕 - 예약 = {len(sweep - resv)}칸 "
              f"{sorted(sweep - resv)}   <- 회전이 **더** 쓰는 칸")
    return bad, len(sweep), len(resv)


def main():
    geom = PS.make_geom(PITCH)
    free, _k = PS.build_free(MAP, PITCH)      # (free, k) 를 돌려준다
    print(f"  맵 {MAP}  격자 {free.shape}  통행가능 {100.0 * free.mean():.1f}%")
    print(f"  {geom.pivot_name}  pitch {PITCH}  rear {geom.rear_len} "
          f"front {geom.front_len} width {geom.width}")
    import math
    print(f"  뒤 모서리 반지름 = hypot({geom.rear_len}, {geom.width / 2}) = "
          f"{math.hypot(geom.rear_len, geom.width / 2):.3f} m\n")

    if os.environ.get("ALL", "0") not in ("0", ""):
        return sweep_all(free, geom)

    a = sys.argv[1:]
    r, c, h0, h1 = (tuple(int(x) for x in a[:4]) if len(a) >= 4 else DEFAULT)
    bad, ns, nr = check(free, geom, r, c, h0, h1)
    print()
    if bad:
        print("  · 칸 판정: 스윕이 막힌 칸을 지난다")
        for cell, why in bad:
            print(f"      {cell}  {why}")
    else:
        print("  · 칸 판정: 막힌 칸 없음")

    mask, src = load_mask(MAP)
    pen, ang, gap = penetrate(mask, geom, r, c, h0, h1)
    print(f"\n  ── 0.1 m 마스크 실측 ({src}) ──")
    if pen > 0.0:
        print(f"  ☹ **차체가 장애물을 {pen * 1000:.0f} mm 파고든다** "
              f"(회전 {ang:+.0f}도 지점)")
        print("     Isaac 에는 랙 콜라이더가 있으므로 여기서 **밀린다.**")
        print("     고칠 자리는 제어기가 아니라 **계획(`turn_ok`)** 이다 —")
        print("     못 도는 회전을 계획이 내면 제어기는 무엇을 해도 진다.")
    else:
        print("  ★ 파고들지 않는다 (겹침 0).")
        print("     정적 장애물 가설은 닫힌다 — 남는 후보는 다른 로봇과의 접촉,")
        print("     바닥·바퀴 물성, 리프트 하중이다.")


def sweep_all(free, geom):
    """맵 전체에서 **막힌 칸을 스치는 회전**이 얼마나 되나."""
    R, C = free.shape
    tot = hit = 0
    hits = []
    for r in range(R):
        for c in range(C):
            if not free[r, c]:
                continue
            for h0 in range(4):
                h1 = (h0 + 1) % 4
                if not PC.valid_state(free, (r, c, h0)):
                    continue
                if not PC.valid_state(free, (r, c, h1)):
                    continue
                tot += 1
                bad, _ns, _nr = check(free, geom, r, c, h0, h1, quiet=True)
                if bad:
                    hit += 1
                    hits.append((r, c, h0, h1))
    print(f"  회전 가능 전이 {tot:,}건 중 막힌 칸을 스치는 것 {hit:,}건 "
          f"({100.0 * hit / max(tot, 1):.1f}%)  <- 칸 판정, 거칠다")

    # ★ 칸 판정은 **선별**일 뿐이다. 진짜 수는 0.1 m 마스크로 다시 센다.
    mask, src = load_mask(MAP)
    pens = []
    for st in hits:
        pen, ang, _g = penetrate(mask, geom, *st)
        if pen > 0.0:
            pens.append((pen, st, ang))
    pens.sort(reverse=True)
    print(f"  그중 **실제로 파고드는 것 {len(pens):,}건** "
          f"({100.0 * len(pens) / max(tot, 1):.1f}% of 전체)   [{src}]")
    for pen, st, ang in pens[:10]:
        print(f"     {st}  침투 {pen * 1000:5.0f} mm  ({ang:+.0f}도)")
    print()
    if pens:
        print("  ☹ **계획이 못 도는 회전을 낸다.** 제어기가 아니라 계획 문제다.")
        print("     `turn_ok` 가 스윕을 안 본다 — FMS-31 §5 의 `turn_ok` 앞칸과 같은 자리.")
    else:
        print("  ★ 파고드는 회전이 없다 — 정적 장애물은 원인이 아니다.")


if __name__ == "__main__":
    main()
