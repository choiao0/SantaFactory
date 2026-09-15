# -*- coding: utf-8 -*-
"""차체 **꼬리**가 옆 칸을 얼마나 먹는가 — 축 지표가 빠뜨린 성분.

왜
--
`cross_track` · `turn_error` 는 전부 **축 위치**의 오차를 잰다. 그런데 차체는
축 뒤로 `rear_len` = 1.110 m 매달려 있다. 헤딩이 δ 만큼 틀어져 있으면 축이
차선 한가운데 있어도 꼬리 끝은 옆으로 나간다.

    꼬리 끝의 옆 이탈  =  축 가로 이탈  +  rear_len x sin(δ)
    δ = 0.05 rad (Tolerance.yaw) 이면 뒤 항만 55.5 mm · 두 대면 111 mm

축 가로 이탈 최대가 54.7 mm 였으니 **같은 크기의 성분을 통째로 빼먹고 있었을
수 있다.** 그게 `worst_gap 26.7 mm` 와 축 기준 여유 90.6 mm 의 64 mm 차이를
설명하는지 보는 것이 이 도구의 목적이다.

무엇을 재나
-----------
1. 전 구간에서 **꼬리 끝의 차선 이탈** 분포. 축 이탈과 나란히 찍어 어느 쪽이
   예산을 먹는지 가른다.
2. `--pair a,b` 를 주면 그 두 대가 **가장 가까웠던 프레임**을 찾아, 그 순간의
   요잉·축 이탈·꼬리 이탈·차체 간격을 한 줄로 낸다. `worst_gap` 이 왜 그
   값인지는 이 줄에서 읽는다.

쓰는 법
-------
    source paths.sh
    PITCH=1.0 python tools/tail_yaw.py $OUT/rec_v22.npz
    PITCH=1.0 python tools/tail_yaw.py $OUT/rec_v22.npz --pair 0,1

    쌍은 로그의 `overlap_pairs` 에서 가져온다. 안 주면 **모든 쌍**을 훑어
    가장 가까웠던 쌍을 스스로 찾는다 (12대면 66쌍 x 프레임이라 조금 걸린다).

한계
----
· 요잉은 녹화의 `pose[:, :, 2]` 를 그대로 쓴다. `axle_frame` 이 판정한
  프레임 오차(delta)는 **보정하지 않는다** — 그건 축 위치의 문제고 여기서
  보는 것은 헤딩이다.
· 차체 간격은 사각형 근사다 (`isaac_drive.RobotGeom.body_gap` 과 같은 규약이
  아니라 독립 구현이다). 두 값이 크게 다르면 그것 자체가 단서다.
"""
import argparse
import os
import sys

import numpy as np

PITCH = float(os.environ.get("PITCH", os.environ.get("PIBT_PITCH", "1.2")))
WIDTH = float(os.environ.get("WIDTH", "0.800"))
REAR = float(os.environ.get("REAR_LEN", "1.110"))    # 축 -> 차체 뒷면
FRONT = float(os.environ.get("FRONT_LEN", "0.390"))  # 축 -> 차체 앞면
YAW_TOL = float(os.environ.get("YAW_TOL", "0.05"))   # rad — Tolerance.yaw
VMIN = float(os.environ.get("VMIN", "0.30"))         # m/s — 직진 판정
BUDGET = (PITCH - WIDTH) / 2.0 * 1000.0              # 로봇당 예산 mm
W_TURN = float(os.environ.get("W_TURN", "0.15"))     # rad/s — 회전 중 판정
AXIS_TOL = float(os.environ.get("AXIS_TOL", "0.25"))  # rad — 축에서 14도
# 근접 경고선. `isaac_drive.CONTACT_NEAR` 와 같은 값을 쓴다.
NEAR = float(os.environ.get("NEAR", "0.10"))         # m


def lane_off(v, pitch):
    """가장 가까운 차선 중심에서의 거리 (m). origin = pitch/2 규약이라
    칸 안 위치 `v % pitch` 의 중심이 `pitch/2` 다."""
    return np.abs(v % pitch - pitch / 2.0)


def axis_offset(th):
    """헤딩이 가장 가까운 90도 배수에서 벗어난 각 (rad, 부호 있음)."""
    return (th + np.pi / 4) % (np.pi / 2) - np.pi / 4


def within(mm, mark=""):
    return f"{mark}초과" if mm > BUDGET else "이내"


def corners(x, y, th):
    """차체 사각형 네 꼭짓점 [..., 4, 2]."""
    c, s = np.cos(th), np.sin(th)
    hw = WIDTH / 2.0
    # body 프레임 (x=전방) 의 네 점
    pts = np.array([[FRONT, hw], [FRONT, -hw], [-REAR, -hw], [-REAR, hw]])
    out = np.empty(np.shape(x) + (4, 2))
    for i, (bx, by) in enumerate(pts):
        out[..., i, 0] = x + bx * c - by * s
        out[..., i, 1] = y + bx * s + by * c
    return out


def sat_gap(pa, pb):
    """두 볼록 사각형 사이 간격 (m). 분리축 정리 — 겹치면 음수 근사 0."""
    best = -np.inf
    for P, Q in ((pa, pb), (pb, pa)):
        for i in range(4):
            e = P[(i + 1) % 4] - P[i]
            n = np.array([-e[1], e[0]])
            n = n / (np.hypot(*n) + 1e-12)
            p, q = P @ n, Q @ n
            d = max(q.min() - p.max(), p.min() - q.max())
            best = max(best, d)
    return max(best, 0.0)          # 겹치면 음수가 나오므로 0 으로 눌러 둔다


def straight_deviations(P, dt):
    """직진 중(v > VMIN) 프레임의 (축 이탈, 꼬리 이탈, |요잉|). 단위 m·rad.

    꼬리 이탈 = 축 이탈 + rear_len x |sin δ| — 차체가 축 뒤로 매달려 있어
    헤딩이 δ 틀어지면 뒤끝이 그만큼 더 옆으로 나간다.
    """
    ax_all, tl_all, yw_all = [], [], []
    for k in range(P.shape[1]):
        x, y, th = P[:, k, 0], P[:, k, 1], P[:, k, 2]
        mv = (np.hypot(np.diff(x), np.diff(y)) / dt) > VMIN
        if not mv.any():
            continue
        xs, ys, ts = x[:-1][mv], y[:-1][mv], th[:-1][mv]
        horiz = np.abs(np.cos(ts)) > np.abs(np.sin(ts))   # 가로 주행 -> y 이탈
        ax = np.where(horiz, lane_off(ys, PITCH), lane_off(xs, PITCH))
        d = axis_offset(ts)
        ax_all.append(ax)
        tl_all.append(ax + REAR * np.abs(np.sin(d)))
        yw_all.append(np.abs(d))
    return (np.concatenate(ax_all) * 1000.0,
            np.concatenate(tl_all) * 1000.0,
            np.concatenate(yw_all))


def print_deviations(ax, tl, yw):
    print("\n══ 직진 중 이탈 — 축이 먹는 것 vs 꼬리가 먹는 것 ══")
    print(f"   {'':<16}{'중앙':>8}{'p95':>8}{'p99':>8}{'최대':>8}   mm")
    for nm, arr in (("축 가로 이탈", ax), ("**꼬리 이탈**", tl)):
        print(f"   {nm:<16}{np.median(arr):>8.1f}{np.percentile(arr, 95):>8.1f}"
              f"{np.percentile(arr, 99):>8.1f}{arr.max():>8.1f}")
    print(f"   {'요잉 |δ| rad':<16}{np.median(yw):>8.3f}"
          f"{np.percentile(yw, 95):>8.3f}{np.percentile(yw, 99):>8.3f}"
          f"{yw.max():>8.3f}")
    print(f"\n   예산 {BUDGET:.0f} mm 대비 — 축 최대 {ax.max():.1f} "
          f"({within(ax.max())})  ·  꼬리 최대 {tl.max():.1f} "
          f"({within(tl.max(), '★ ')})")
    print(f"   꼬리가 예산을 넘은 프레임 {(tl > BUDGET).mean() * 100:.2f}%")
    print(f"   -> 꼬리가 축보다 {tl.max() - ax.max():+.1f} mm 더 먹는다")


def closest_frames(P, pairs):
    """쌍마다 차체 간격을 재서 [(간격 m, 프레임, a, b)] 를 돌려준다.

    ★ 후보를 **거리 문턱**으로 고른다. 예전에는 축 거리 상위 200 프레임만
    봤는데, 축이 멀어도 헤딩이 직각이면 꼬리가 더 가까울 수 있어 진짜 최소를
    놓쳤다 (FleetStats worst_gap 26.7 mm 를 40.5 로 읽었다). 차체 반대각의
    두 배 + 여유 안쪽이면 전부 정밀 계산한다.
    """
    reach = 2.0 * np.hypot(max(FRONT, REAR), WIDTH / 2.0) + 0.05
    rows = []
    for (i, j) in pairs:
        ci = corners(P[:, i, 0], P[:, i, 1], P[:, i, 2])
        cj = corners(P[:, j, 0], P[:, j, 1], P[:, j, 2])
        d0 = np.hypot(P[:, i, 0] - P[:, j, 0], P[:, i, 1] - P[:, j, 1])
        rows += [(sat_gap(ci[f], cj[f]), f, i, j)
                 for f in np.flatnonzero(d0 < reach)]
    rows.sort()
    return rows


def frame_cells(P, W, f, k):
    """최근접 표의 한 로봇 칸 — (요잉, 축 이탈, 꼬리 이탈) 문자열.

    ★ 회전 중이면 차선 기준 분해가 **성립하지 않는다.** 헤딩이 축에서 45도
    벗어나 있으면 axis_offset 이 0.77 rad 이 되고 「꼬리 이탈」이 830 mm 로
    찍힌다 — 그건 이탈이 아니라 그냥 비스듬히 선 것이다 (2026-09-15 v1.6
    판에서 실제로 그렇게 나왔다). 간격(SAT)은 헤딩과 무관하게 유효하므로 그
    열만 믿고 나머지는 '회전' 으로 표시한다.
    """
    th = P[f, k, 2]
    d = axis_offset(th)
    turning = (f < len(W) and W[f, k] > W_TURN) or abs(d) > AXIS_TOL
    if turning:
        return f"{d:>7.3f}", "  회전", "   회전"
    horiz = abs(np.cos(th)) > abs(np.sin(th))
    axk = lane_off(P[f, k, 1] if horiz else P[f, k, 0], PITCH)
    return (f"{d:>7.3f}", f"{axk * 1000:>6.1f}",
            f"{(axk + REAR * abs(np.sin(d))) * 1000:>7.1f}")


def print_closest(rows, P, t, dt, top):
    W = np.abs(np.diff(np.unwrap(P[:, :, 2], axis=0), axis=0)) / dt   # [F-1, N]
    print(f"   {'간격mm':>8}{'t':>8}  쌍      "
          f"{'요잉a':>7}{'요잉b':>7}   {'축a':>6}{'축b':>6}"
          f"  {'꼬리a':>7}{'꼬리b':>7}  mm")
    for g, f, i, j in rows[:top]:
        (ya, aa, ta) = frame_cells(P, W, f, i)
        (yb, ab, tb) = frame_cells(P, W, f, j)
        print(f"   {g * 1000:>8.1f}{t[f]:>8.1f}  {i:>2}-{j:<2}   "
              f"{ya}{yb}   {aa}{ab}  {ta}{tb}")


def print_near(rows, sim_s):
    """근접(gap < NEAR) 프레임이 몇 번인가 — **노출**의 척도.

    `overlap_events` 는 칸 공유 횟수라 4칸 규칙이 일부러 허용하는 안전한
    나란히-서기까지 센다. 위험을 세려면 실제로 가까웠던 횟수를 봐야 한다
    (`isaac_drive.CONTACT_NEAR` 와 같은 0.10 m). FleetStats 에는 이 카운터가
    없고 로그는 쌍마다 첫 건만 찍으므로 여기서 센다.
    """
    near = [r for r in rows if r[0] < NEAR]
    pairs = {(r[2], r[3]) for r in near}
    print(f"\n══ 근접 — 차체 간격 {NEAR * 1000:.0f} mm 안 ══")
    print(f"   프레임 {len(near):,}  ·  쌍 {len(pairs)}  "
          f"·  주행 {sim_s:.1f} s 당 {len(near) / max(sim_s, 1e-9):.2f} 회/s")
    if near:
        print(f"   가장 붙은 값 {near[0][0] * 1000:.1f} mm")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("npz")
    ap.add_argument("--pair", default=None, help="'a,b' — 그 쌍의 최근접 프레임")
    ap.add_argument("--top", type=int, default=5, help="최근접 프레임 N개")
    a = ap.parse_args()

    z = np.load(a.npz, allow_pickle=False)
    t, P = z["t"], z["pose"]
    F, N, _ = P.shape
    dt = float(np.median(np.diff(t)))
    print(f"[in] {a.npz}  {F} 표본 · {N}대 · {t[-1] - t[0]:.1f} s")
    print(f"     pitch {PITCH} · 차체 뒤 {REAR} + 앞 {FRONT} · 폭 {WIDTH}")
    print(f"     로봇당 예산 {BUDGET:.1f} mm · 요잉 허용치 {YAW_TOL} rad "
          f"(꼬리 {REAR * np.sin(YAW_TOL) * 1000:.1f} mm)")

    print_deviations(*straight_deviations(P, dt))

    if a.pair:
        pairs = [tuple(int(v) for v in a.pair.split(","))]
    else:
        pairs = [(i, j) for i in range(N) for j in range(i + 1, N)]
    rows = closest_frames(P, pairs)
    print(f"\n══ 차체가 가장 가까웠던 순간 ({len(pairs)}쌍) ══")
    print_closest(rows, P, t, dt, a.top)
    print_near(rows, float(t[-1] - t[0]))

    print("\n  읽는 법")
    print("   · '꼬리 최대'가 '축 최대'보다 크게 높으면 예산표가 축만 보고")
    print("     있었다는 뜻이다. 그 차이만큼 §8 판정을 다시 해야 한다.")
    print("   · 최근접 프레임의 요잉이 허용치 0.05 rad 근처면 원인이 확정된다.")
    print("     대책은 회전 종료 요잉 허용치를 줄이는 것 (회전 시간이 조금 는다).")
    print("   · 요잉이 작은데도 간격이 좁으면 원인은 다른 데 있다 — 그때는")
    print("     축 이탈 열을 보라. 둘 다 작으면 차체 사각형 근사를 의심한다.")
    print("   · '근접' 은 속도를 비교할 때 overlap_events 대신 쓸 척도다.")
    print("     겹침은 안전한 나란히-서기까지 세지만 이건 실제로 가까웠던 횟수다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
