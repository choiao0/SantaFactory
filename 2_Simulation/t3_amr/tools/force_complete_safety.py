# -*- coding: utf-8 -*-
"""막힌 액션을 **강제 완료**하면 얼마나 위험한가 — E안 (S15P21A106-240).

무엇을 재는가
-------------
A6#86 `reverse` 가 추종기 고정점에 갇혔다 (§8-5).

    along = +0.20 mm    cross = +214.22 mm    head = -10.00 deg

`along` 이 0 이라 **경로 끝에는 이미 와 있다.** 남은 214 mm 가 전부 횡방향일
뿐이다. 그래서 「그냥 완료 처리하고 다음 액션을 시작한다」가 후보로 나온다(E).

그런데 그 순간 이 로봇은 **놓아준 칸을 몸으로 물고 있다.** ADG 가 뒷차에게
「그 칸은 네 것」이라고 말하는데 앞차 몸이 아직 거기 있다. `soft` 해제
(-240) 와 같은 종류의 거래이고, **같은 방법으로 재야 한다.**

    앞차 P   액션을 끝낸 자세에서 축을 **d 만큼 밀고** yaw 를 **θ 만큼** 틀어 둔다
    뒤차 Q   P 가 놓아준 칸에 들어올 수 있는 합법 자세 전부
    값       `geom.body_gap` 의 최소 — 두 차체 사각형 사이 실제 간격

★ `soft_release_safety.py` 와 재는 방식을 일부러 같게 두었다. 두 안의 여유를
  **같은 자로** 재야 저울이 성립한다.

판정선 셋
---------
    41.4 mm   4칸 규칙의 설계 여유. 이걸 깨면 E 는 그 자리에서 닫힌다
   100.0 mm   `CONTACT_NEAR` — 이 아래는 「근접」으로 로그에 뜬다
     0.0 mm   접촉. 말할 것도 없다

쓰는 법
-------
    source paths.sh
    PITCH=1.0 python tools/force_complete_safety.py

    DMAX   밀림 최대 mm (기본 250 — a6 의 214 를 넘겨 본다)
    YAWMAX 요잉 오차 최대 도 (기본 12 — a6 는 10.0)
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
DMAX = float(os.environ.get("DMAX", "250")) / 1000.0
YAWMAX = math.radians(float(os.environ.get("YAWMAX", "12")))
NDIR = int(os.environ.get("NDIR", "16"))
NYAW = int(os.environ.get("NYAW", "5"))

DESIGN = 0.0414          # 4칸 규칙 설계 여유
NEAR = idr.CONTACT_NEAR  # 0.10


def peers(geom, frm, to):
    """P 가 놓아준 칸에 들어올 수 있는 뒤차 Q 의 자세 목록.

    `soft_release_safety.worst_for` 와 같은 얼개다 — 정지 자세와 회전 중
    자세를 모두 넣는다. P 가 **계속 쥐고 있는** 칸(`rest`)을 건드리는 Q 는
    ADG 가 애초에 안 들여보내므로 뺀다.
    """
    cells = geom.swept_cells(frm, to)
    rest = frozenset(occupied(to))
    released = cells - rest
    cand = []
    for cell in sorted(released):
        r, c = cell
        for dr in (-2, -1, 0, 1, 2):
            for dc in (-2, -1, 0, 1, 2):
                pr, pc = r + dr, c + dc
                for h in range(4):
                    s = (pr, pc, h)
                    occ = frozenset(occupied(s))
                    if cell in occ and not (occ & rest):
                        cand.append((s, None))
                    for h2 in ((h + 1) % 4, (h - 1) % 4):
                        try:
                            sw = geom.swept_cells(s, (pr, pc, h2))
                        except Exception:
                            continue
                        if cell in sw and not (sw & rest):
                            cand.append((s, (pr, pc, h2)))
    return released, cand


def min_gap(geom, frm, to, d, dyaw):
    """축을 d 만큼(모든 방향) 밀고 yaw 를 dyaw 틀었을 때의 최소 차체 간격."""
    _rel, cand = peers(geom, frm, to)
    if not cand:
        return float("inf")
    ax, ay, ayaw = geom.state_pose(to)
    worst = float("inf")
    dirs = range(NDIR) if d > 0 else range(1)
    for k in dirs:
        th = 2.0 * math.pi * k / NDIR
        pa = (ax + d * math.cos(th), ay + d * math.sin(th), ayaw + dyaw)
        for s0, s1 in cand:
            bx, by, b0 = geom.state_pose(s0)
            if s1 is None:
                worst = min(worst, geom.body_gap(pa, (bx, by, b0)))
                continue
            b1 = geom.state_pose(s1)[2]
            dth = (b1 - b0 + math.pi) % (2.0 * math.pi) - math.pi
            for m in range(9):
                worst = min(worst, geom.body_gap(pa, (bx, by, b0 + dth * m / 8.0)))
    return worst


def main():
    geom = pibt_scene.make_geom(PITCH)
    print(f"  pitch {PITCH} · 밀림 0~{DMAX * 1000:.0f} mm · "
          f"요잉 0~{math.degrees(YAWMAX):.0f}도 · 방향 {NDIR} · 요잉 {NYAW}단계")
    print(f"  판정선  설계 여유 {DESIGN * 1000:.1f} mm · "
          f"근접선 {NEAR * 1000:.0f} mm · 접촉 0")

    # a6 이 갇힌 액션: reverse (46,50,0) -> (45,50,0)
    acts = [("reverse h0", (46, 50, 0), (45, 50, 0)),
            ("reverse h1", (46, 50, 1), (46, 49, 1)),
            ("move h0", (46, 50, 0), (47, 50, 0)),
            ("move h1", (46, 50, 1), (46, 51, 1))]

    print(f"\n  {'액션':<12}{'놓아준 칸':>22}{'뒤차 후보':>10}")
    for lab, frm, to in acts:
        rel, cand = peers(geom, frm, to)
        print(f"  {lab:<12}{str(sorted(rel)):>22}{len(cand):>10}")

    print(f"\n  ── 밀림별 최소 차체 간격 [mm] ──")
    hdr = "".join(f"{math.degrees(YAWMAX * j / max(NYAW - 1, 1)):>8.0f}도"
                  for j in range(NYAW))
    print(f"  {'밀림mm':>8}{hdr}   판정")
    rows = []
    for dmm in (0, 25, 50, 100, 150, 214, int(DMAX * 1000)):
        d = dmm / 1000.0
        if d > DMAX + 1e-9:
            continue
        vals = []
        for j in range(NYAW):
            dyaw = YAWMAX * j / max(NYAW - 1, 1)
            g = min(min_gap(geom, frm, to, d, dyaw)
                    for lab, frm, to in acts)
            vals.append(g)
        w = min(vals)
        if w <= 0.0:
            tag = "☠ 접촉"
        elif w < DESIGN:
            tag = f"☠ 설계 여유 {DESIGN * 1000:.1f} 를 깬다"
        elif w < NEAR:
            tag = "~ 근접 (로그에 뜬다)"
        else:
            tag = "★ 여유"
        print(f"  {dmm:>8}" + "".join(f"{v * 1000:>10.1f}" for v in vals)
              + f"   {tag}")
        rows.append((dmm, w))

    # ★ 왜 닫히는지 — 두 손잡이의 크기를 나란히 둔다.
    #   꼬리가 1.11 m 라 **요잉이 밀림보다 훨씬 세다.** 이걸 안 적으면
    #   「214 mm 때문에 닫혔다」로 잘못 읽는다.
    lat = geom.lateral_gap * 1000.0
    print(f"\n  ── 왜 닫히나 — 손잡이 둘의 크기 ──")
    print(f"  옆 칸 간격 (pitch - 폭)            {lat:.0f} mm  <- 이걸 다 쓰면 닿는다")
    print(f"  밀림 d 가 먹는 양                  d mm  (1:1)")
    print(f"  요잉 θ 가 먹는 양   rear_len x sinθ = "
          f"{geom.rear_len * 1000:.0f} x sinθ mm")
    print()
    print(f"  {'요잉':>6}{'꼬리가 먹는 양':>16}{'남는 간격(밀림 0)':>20}")
    for deg in (0, 2.86, 5, 10, 12):
        eat = geom.rear_len * math.sin(math.radians(deg)) * 1000.0
        note = "  <- tol.yaw" if abs(deg - 2.86) < 0.01 else (
            "  <- a6" if deg == 10 else "")
        print(f"  {deg:>5.2f}도{eat:>14.0f} mm{max(0.0, lat - eat):>17.0f} mm{note}")
    print(f"\n  ★ 꼬리 1.11 m 라 **요잉이 밀림보다 훨씬 세다.** "
          f"{math.degrees(math.asin(min(1.0, geom.lateral_gap / geom.rear_len))):.1f}도면")
    print(f"    밀림이 0 이어도 옆 칸 간격을 통째로 먹는다.")

    print(f"\n  ── 판정 ──")
    a6 = [w for d, w in rows if d == 214]
    if a6:
        w = a6[0]
        print(f"  a6 자세(밀림 214 mm · 요잉 10도)에서 최소 간격 "
              f"**{w * 1000:.1f} mm**")
        if w <= 0.0:
            print("  ☠ 닿는다. E 는 닫힌다")
        elif w < DESIGN:
            print(f"  ☠ 4칸 설계 여유 {DESIGN * 1000:.1f} mm 를 깬다. E 는 닫힌다")
        else:
            print(f"  ★ 설계 여유({DESIGN * 1000:.1f})를 안 깬다 — "
                  f"E 가 1.0 유지 시나리오의 후보로 남는다")
            print("    다만 이건 **기하만** 본 값이다. 강제 완료한 액션의 "
                  "다음 액션이")
            print("    어디로 가는지는 계획이 정하므로, 채택하려면 주행으로 "
                  "확인해야 한다")


if __name__ == "__main__":
    main()
