# -*- coding: utf-8 -*-
"""주행 중 **횡방향 이탈** 실측 — 녹화 `.npz` 에서.

왜 이 숫자가 필요한가
---------------------
pitch 1.0 의 여유 상한은 `lateral_gap = pitch - width = 200.0 mm` 다. 미리
정해 둔 기각선은 그 절반인 **100 mm**. 실행 속도를 2.2 m/s 로 올려 채택한
이상, 2.2 에서 잰 이탈이 100 mm 를 넘으면 **1.0 과 2.2 중 하나를 버려야
한다.**

    ★ 참고값: 제동 프로파일 수정 **전** 2.2 에서 175.9 mm 였다.
      그 값은 정지거리 계산이 한 동작만 보던 시절의 것이라 무효다.
      이 도구로 **수정 후** 녹화를 다시 재는 것이 목적이다.

무엇을 재는가
-------------
격자의 차선(=칸 중심을 잇는 직선)에서 구동축이 얼마나 벗어났는지.

    가로로 달리는 중   차선은 y = origin_y + r*pitch     이탈 = |y - 가장 가까운 차선|
    세로로 달리는 중   차선은 x = origin_x + c*pitch     이탈 = |x - 가장 가까운 차선|

    ★ **직진 중인 프레임만** 센다. 회전 중에는 축이 칸 중심에 붙박여 있어
      이탈이 0 이고, 그걸 섞으면 분포가 통째로 낙관적으로 나온다.
    ★ 헤딩이 축 정렬에서 벗어난 프레임(회전 과도구간)도 뺀다.

쓰는 법
-------
    source paths.sh
    python tools/cross_track.py $OUT/rec_fast.npz
    PITCH=1.0 VMIN=0.3 python tools/cross_track.py $OUT/rec_carry2.npz

    여러 개를 한 번에 주면 나란히 비교한다.
"""
import math
import os
import sys

import numpy as np

PITCH = float(os.environ.get("PITCH", os.environ.get("PIBT_PITCH", "1.2")))
VMIN = float(os.environ.get("VMIN", "0.30"))      # m/s — 이보다 느리면 "직진 중" 아님
YAW_TOL = float(os.environ.get("YAW_TOL", "10"))  # 도 — 축 정렬 허용 오차
WIDTH = 0.800                                     # m — 차체 폭
# 기각선 = lateral_gap 의 절반. pitch 에서 파생시킨다 —
# 1.0 이면 100 mm, 1.2 면 200 mm. 상수로 박으면 pitch 를 바꿀 때 조용히 틀린다.
REJECT = float(os.environ.get("REJECT", str((PITCH - WIDTH) / 2.0 * 1000.0)))


def lanes(v, origin, pitch):
    """v 에서 가장 가까운 차선까지의 거리 (부호 없음)."""
    k = np.round((v - origin) / pitch)
    return np.abs(v - (origin + k * pitch))


def analyse(path):
    z = np.load(path, allow_pickle=True)
    t = np.asarray(z["t"], dtype=np.float64)          # (N,)
    pose = np.asarray(z["pose"], dtype=np.float64)    # (N, R, 3) = x, y, yaw
    if pose.ndim != 3 or pose.shape[2] < 3:
        raise SystemExit(f"★ pose 모양이 예상과 다릅니다: {pose.shape}")
    n, R, _ = pose.shape
    ox = oy = PITCH / 2.0                             # make_geom 과 같은 규약

    dt = np.diff(t)
    dt[dt <= 0] = np.nan

    rows = []
    for a in range(R):
        x, y, yaw = pose[:, a, 0], pose[:, a, 1], pose[:, a, 2]
        vx, vy = np.diff(x) / dt, np.diff(y) / dt
        spd = np.hypot(vx, vy)

        # 헤딩을 90° 격자에 맞춘 뒤 벗어난 각을 잰다
        deg = np.degrees(yaw[:-1]) % 90.0
        off = np.minimum(deg, 90.0 - deg)

        moving = (spd > VMIN) & np.isfinite(spd) & (off < YAW_TOL)
        if not moving.any():
            continue

        # 가로 주행인지 세로 주행인지 — 속도 성분이 큰 쪽
        horiz = np.abs(vx) >= np.abs(vy)
        err = np.where(horiz,
                       lanes(y[:-1], oy, PITCH),       # 가로 주행 -> y 이탈
                       lanes(x[:-1], ox, PITCH))       # 세로 주행 -> x 이탈
        e = err[moving] * 1000.0                       # mm
        v = spd[moving]
        rows.append((a, e, v))

    if not rows:
        raise SystemExit("★ 직진 중인 프레임이 없습니다 — VMIN/YAW_TOL 을 확인하세요.")

    all_e = np.concatenate([r[1] for r in rows])
    allv = np.concatenate([r[2] for r in rows])
    return rows, all_e, allv


def report(path, rows, e, v):
    name = os.path.basename(path)
    print(f"\n── {name} " + "─" * max(4, 56 - len(name)))
    print(f"   직진 프레임 {len(e):,}  ·  pitch {PITCH}  ·  VMIN {VMIN} m/s")
    print(f"   속도  중앙 {np.median(v):.2f}  p95 {np.percentile(v, 95):.2f}  "
          f"최대 {v.max():.2f} m/s")
    print(f"   이탈  중앙 {np.median(e):6.1f}   p95 {np.percentile(e, 95):6.1f}   "
          f"p99 {np.percentile(e, 99):6.1f}   최대 {e.max():6.1f}  mm")

    over = (e > REJECT).mean() * 100.0
    worst = np.percentile(e, 95)
    verdict = "기각선 초과" if worst > REJECT else "기각선 이내"
    print(f"   기각선 {REJECT:.0f} mm 대비 p95 {worst:6.1f} mm  ->  ★ {verdict}"
          f"   (초과 프레임 {over:.2f}%)")

    # 속도 구간별 — 빠를수록 나빠지는지 본다
    print(f"\n   {'속도 구간':<14}{'프레임':>9}{'중앙':>8}{'p95':>8}{'최대':>8}")
    edges = [0.0, 0.5, 1.0, 1.5, 2.0, 9.9]
    for lo, hi in zip(edges, edges[1:]):
        m = (v >= lo) & (v < hi)
        if m.sum() < 20:
            continue
        print(f"   {lo:.1f}-{hi:.1f} m/s{'':<4}{m.sum():>9,}"
              f"{np.median(e[m]):>8.1f}{np.percentile(e[m], 95):>8.1f}"
              f"{e[m].max():>8.1f}")

    # 로봇별 최악 셋
    print(f"\n   로봇별 p95 상위: ", end="")
    top = sorted(rows, key=lambda r: -np.percentile(r[1], 95))[:3]
    print("  ".join(f"agent{a} {np.percentile(ee, 95):.1f}" for a, ee, _ in top))


# ===========================================================================
# 진단 — 차선 격자를 **데이터에서 찾는다**
# ===========================================================================
def diagnose(path):
    """pitch·origin·어느 pose 인지를 추측하지 않고 **고른다.**

    로봇이 차선을 따라 달렸다면 올바른 `(pitch, origin)` 에서는 주행 방향에
    수직인 좌표의 `mod pitch` 가 **한 점에 몰린다.** 틀린 격자에서는 균일하게
    퍼지고, 그때 "가장 가까운 차선까지" 는 항상 `pitch/2` 근처가 된다.

    ★ 2026-09-14 첫 측정이 정확히 그 함정이었다. 모든 녹화에서 최대가
      500.0 mm = pitch/2 로 딱 떨어졌는데, 그건 이탈이 큰 것이 아니라
      **격자를 못 찾은 것**이다. 그래서 추측을 그만두고 이 함수를 넣었다.
    """
    z = np.load(path, allow_pickle=True)
    keys = list(z.keys())
    t = np.asarray(z["t"], dtype=np.float64)
    print()
    print("=" * 66)
    print(os.path.basename(path))
    print("=" * 66)
    print(f"  키 {keys}   프레임 {len(t):,}   {t[0]:.1f} ~ {t[-1]:.1f} s")
    if "stage" in keys:
        print(f"  stage: {z['stage']}")

    dt = np.diff(t)
    dt[dt <= 0] = np.nan

    for nm in ("pose", "pose_alt"):
        if nm not in keys:
            continue
        p3 = np.asarray(z[nm], dtype=np.float64)
        print()
        print(f"  -- {nm}  shape {p3.shape}")
        if p3.ndim != 3 or p3.shape[2] < 3:
            print("     모양이 (프레임, 로봇, 3) 이 아니다 — 건너뛴다")
            continue
        x, y = p3[:, :, 0], p3[:, :, 1]
        print(f"     x {x.min():8.3f} ~ {x.max():8.3f}     "
              f"y {y.min():8.3f} ~ {y.max():8.3f}")

        vx = np.diff(x, axis=0) / dt[:, None]
        vy = np.diff(y, axis=0) / dt[:, None]
        spd = np.hypot(vx, vy)
        deg = np.degrees(p3[:-1, :, 2]) % 90.0
        off = np.minimum(deg, 90.0 - deg)
        mv = (spd > VMIN) & np.isfinite(spd) & (off < YAW_TOL)
        if not mv.any():
            print("     직진 프레임 없음 — VMIN/YAW_TOL 확인")
            continue
        horiz = np.abs(vx) >= np.abs(vy)
        # 주행 방향에 **수직**인 좌표 = 차선 이탈의 원천
        perp = np.where(horiz, y[:-1], x[:-1])[mv]
        print(f"     직진 프레임 {mv.sum():,}"
              f"   (가로 {horiz[mv].mean() * 100:.0f}% / 세로 "
              f"{(~horiz[mv]).mean() * 100:.0f}%)")

        print(f"     {'pitch':>7}{'origin':>9}{'중앙mm':>9}{'p95mm':>9}"
              f"{'50mm내':>9}{'20mm내':>9}")
        scores = []
        for pit in (0.80, 0.90, 1.00, 1.10, 1.20, 1.40, 1.60):
            for oname, org in (("0", 0.0), ("pitch/2", pit / 2.0)):
                e = np.abs(perp - (org + np.round((perp - org) / pit) * pit))
                e = e * 1000.0
                c50 = float((e < 50).mean()) * 100.0
                c20 = float((e < 20).mean()) * 100.0
                print(f"     {pit:>7.2f}{oname:>9}{np.median(e):>9.1f}"
                      f"{np.percentile(e, 95):>9.1f}{c50:>8.1f}%{c20:>8.1f}%")
                scores.append((c20, c50, pit, oname))
        scores.sort(reverse=True)
        best, second = scores[0], scores[1]
        print(f"     -> 1등 pitch {best[2]:.2f} origin {best[3]}"
              f"  (20mm 내 {best[0]:.1f}% · 50mm 내 {best[1]:.1f}%)")
        print(f"        2등 pitch {second[2]:.2f} origin {second[3]}"
              f"  (20mm 내 {second[0]:.1f}%)")

        # ★ 판정 기준은 **절대 집중도가 아니라 2등과의 격차**다.
        #   이탈이 커도(합성 검증에서 최대 110mm) 격자만 맞으면 1등이 확연히
        #   앞선다. 반대로 좌표계가 틀리면 전부 비슷하게 낮다.
        if best[0] < 2.0 * max(second[0], 1.0):
            print("     ★ 1등과 2등이 비슷하다 — 격자를 못 고른 것이다.")
            print("        이 pose 가 구동축이 아닐 수 있다 (prim 원점일 가능성),")
            print("        또는 후보 pitch 목록 밖이거나 origin 이 둘 다 아니다.")
        elif best[1] < 50.0:
            print("     ※ 격자는 골랐지만 50mm 안이 절반 미만이다 — "
                  "이탈 자체가 크다는 뜻이다. 본 측정에서 확인할 것.")


def main():
    paths = [p for p in sys.argv[1:] if not p.startswith("-")]
    if not paths:
        raise SystemExit(__doc__)

    # --diag 는 격자를 **고르기 위한** 모드다. 본 측정 전에 한 번 돌린다.
    if "--diag" in sys.argv:
        for p in paths:
            if os.path.exists(p):
                diagnose(p)
            else:
                print(f"\n★ 없음: {p}")
        print("\n★ 어느 (pitch, origin) 이 맞는지 정한 뒤에 본 측정을 한다.")
        return 0

    print(f"횡방향 이탈 — pitch {PITCH}  lateral_gap "
          f"{(PITCH - WIDTH) * 1000:.0f} mm  기각선 {REJECT:.0f} mm (그 절반)")
    for p in paths:
        if not os.path.exists(p):
            print(f"\n★ 없음: {p}")
            continue
        rows, e, v = analyse(p)
        report(p, rows, e, v)
    print("\n★ 2.2 m/s 로 녹화한 판에서 p95 가 기각선을 넘으면 "
          "pitch 1.0 과 2.2 m/s 를 동시에 못 쓴다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
