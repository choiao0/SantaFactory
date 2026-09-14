# -*- coding: utf-8 -*-
"""**회전 종료 자세 오차** 실측 — 녹화 `.npz` 에서.

왜 이 숫자가 필요한가
---------------------
지금까지 쓰던 `51 mm` 는 **한 번의 관측**이다 (2026-09-14 겹침 사건에서
회전 중인 로봇이 칸 중심에서 0.051 m 어긋나 있었다). pitch 1.0 판단 문서가
두 번이나 "이 결론은 51 mm 라는 한 값에 걸려 있다" 고 스스로 적고 있다.

이제 463.8 초 x 12대 x 30 Hz 녹화가 있으므로 **분포로** 뽑을 수 있다.
횡방향 이탈을 잰 것과 같은 파이프라인이다.

무엇을 재는가
-------------
예약 기하는 "구동축이 칸 중심에 **정확히** 있다" 고 가정하고 스윕 칸을
계산한다. 실제 축이 중심에서 벗어난 만큼이 그 가정과의 오차다.

    회전 구간      |각속도| 이 임계 이상인 연속 프레임, 총 회전각 45도 초과
    종료 오차      회전이 끝난 뒤 축과 가장 가까운 칸 중심 사이 거리
    구간 최대      회전하는 **동안**의 최대 이탈 (몸이 쓸고 가는 건 이때다)

    ★ 둘 다 낸다. 접촉은 회전 중에 일어나므로 "구간 최대" 가 더 보수적이고,
      "종료 오차" 는 다음 동작의 출발점이 얼마나 틀어졌는지를 말한다.

예산을 어떻게 쓰는가
--------------------
옆 칸에 선 두 대 사이 간격 `lateral_gap = pitch - width` 를 **두 대가 나눠
먹는다.** 그래서 로봇당 예산은 그 절반이다.

    pitch 1.0  ->  lateral_gap 200 mm  ->  로봇당 100 mm
    앞2 규칙의 설계 여유 41.4 mm       ->  로봇당  20.7 mm

    ★ 회전하는 A 옆에 선 B 는 대개 **자기 회전을 막 끝낸** 상태다.
      그러니 최악 짝은 (회전 오차 + 회전 오차) 이지 (회전 + 직진 이탈) 이
      아니다. 이 도구가 내는 값을 두 번 더해서 여유와 비교하면 된다.

쓰는 법
-------
    source paths.sh
    PITCH=1.2 python tools/turn_error.py $OUT/rec_fast.npz

    PITCH 는 **녹화가 돌던 격자**를 준다 (모르면 cross_track.py --diag).
    BUDGET 으로 로봇당 예산을 덮어쓸 수 있다 (기본 = lateral_gap / 2).
"""
import os
import sys

import numpy as np

PITCH = float(os.environ.get("PITCH", os.environ.get("PIBT_PITCH", "1.2")))
WIDTH = 0.800
W_MIN = float(os.environ.get("W_MIN", "0.15"))     # rad/s — 회전 판정
MIN_DEG = float(os.environ.get("MIN_DEG", "45"))   # 이보다 작게 돌면 회전 아님
SETTLE = float(os.environ.get("SETTLE", "0.20"))   # s — 멈춘 뒤 이만큼 기다려 잰다
# 로봇당 예산 = lateral_gap 의 절반. 여유는 두 대가 나눠 먹는다.
BUDGET = float(os.environ.get("BUDGET", str((PITCH - WIDTH) / 2.0 * 1000.0)))


def off_center(x, y, pitch):
    """축이 가장 가까운 칸 중심에서 벗어난 거리 (m). origin = pitch/2 규약."""
    o = pitch / 2.0
    dx = x - (o + np.round((x - o) / pitch) * pitch)
    dy = y - (o + np.round((y - o) / pitch) * pitch)
    return np.hypot(dx, dy)


def decompose(x, y, yaw, pitch):
    """칸 중심 오차를 **진행축 기준**으로 나눈다 -> (세로, 가로) m.

    왜 나누나: 옆 칸 두 대 사이 여유 `lateral_gap` 을 먹는 것은 **가로**
    성분이다. 세로(앞뒤) 오차는 제동 거리가 틀린 것이고, 나란히 선 두 대의
    옆 간격을 직접 줄이지 않는다.

    2026-09-14 에 회전 중 축 이탈 41.8 mm 를 통째로 예산에서 뺐는데,
    회전 구간 **안**에서 축이 움직인 양은 3.7 mm RMS 뿐이었다. 42 mm 는
    회전이 만든 것이 아니라 **멈춘 자리가 틀린 것**이다. 그렇다면 방향을
    봐야 한다.
    """
    o = pitch / 2.0
    ex = x - (o + np.round((x - o) / pitch) * pitch)
    ey = y - (o + np.round((y - o) / pitch) * pitch)
    c, s = np.cos(yaw), np.sin(yaw)
    lon = ex * c + ey * s          # 진행 방향
    lat = -ex * s + ey * c         # 그 왼쪽
    return lon, lat


def turns_of(t, x, y, yaw):
    """회전 구간을 찾아 (종료오차, 구간최대, 회전각, 지속) 목록을 낸다."""
    yaw = np.unwrap(yaw)
    dt = np.diff(t)
    dt[dt <= 0] = np.nan
    w = np.abs(np.diff(yaw) / dt)
    spin = np.nan_to_num(w) > W_MIN
    err = off_center(x, y, PITCH) * 1000.0

    out = []
    i, n = 0, len(spin)
    while i < n:
        if not spin[i]:
            i += 1
            continue
        j = i
        while j < n and spin[j]:
            j += 1
        # [i, j) 가 회전 구간. 프레임 인덱스로는 i..j
        deg = abs(np.degrees(yaw[j] - yaw[i]))
        if deg >= MIN_DEG:
            # 종료: 각속도가 떨어진 뒤 SETTLE 만큼 지나서 잰다
            k = j
            while k + 1 < len(t) and t[k] - t[j] < SETTLE:
                k += 1
            out.append((err[k], err[i:j + 1].max(), deg, t[j] - t[i]))
        i = j + 1
    return out


def split_report(path):
    """회전 **시작 시점** 오차를 세로/가로로 나눠 찍는다."""
    z = np.load(path, allow_pickle=True)
    t = np.asarray(z["t"], dtype=np.float64)
    pose = np.asarray(z["pose"], dtype=np.float64)
    yaw_all = np.unwrap(pose[:, :, 2], axis=0)
    dt = np.diff(t)
    dt[dt <= 0] = np.nan

    lons, lats, wander = [], [], []
    for a in range(pose.shape[1]):
        x, y, yw = pose[:, a, 0], pose[:, a, 1], yaw_all[:, a]
        spin = np.nan_to_num(np.abs(np.diff(yw) / dt)) > W_MIN
        i, n = 0, len(spin)
        while i < n:
            if not spin[i]:
                i += 1
                continue
            j = i
            while j < n and spin[j]:
                j += 1
            if abs(np.degrees(yw[j] - yw[i])) >= MIN_DEG:
                lo, la = decompose(x[i], y[i], yw[i], PITCH)
                lons.append(lo * 1000.0)
                lats.append(la * 1000.0)
                # 구간 안에서 축이 실제로 움직인 양 (평균 둘레 RMS)
                sx, sy = x[i:j + 1], y[i:j + 1]
                wander.append(float(np.sqrt(np.mean(
                    (sx - sx.mean()) ** 2 + (sy - sy.mean()) ** 2))) * 1000.0)
            i = j + 1
    if not lons:
        return
    lon = np.abs(np.array(lons))
    lat = np.abs(np.array(lats))
    wd = np.array(wander)
    print()
    print("   회전 **시작 시점** 오차를 진행축 기준으로 나눔")
    print(f"   {'':<20}{'중앙':>8}{'p95':>8}{'최대':>8}   mm")
    print(f"   {'세로 (앞뒤)':<20}{np.median(lon):>8.1f}"
          f"{np.percentile(lon, 95):>8.1f}{lon.max():>8.1f}")
    print(f"   {'가로 (옆)':<20}{np.median(lat):>8.1f}"
          f"{np.percentile(lat, 95):>8.1f}{lat.max():>8.1f}")
    print(f"   {'회전 중 축 이동량':<20}{np.median(wd):>8.1f}"
          f"{np.percentile(wd, 95):>8.1f}{wd.max():>8.1f}   <- 구간 안 RMS")
    print()
    print("   ★ 옆 칸 여유(lateral_gap)를 먹는 것은 **가로** 성분이다.")
    print(f"     세로가 크고 가로가 작으면 제동 거리 문제이고, 예산 소모는")
    print(f"     생각보다 작다. 지금 가로 최대 {lat.max():.1f} mm.")


def analyse(path):
    z = np.load(path, allow_pickle=True)
    t = np.asarray(z["t"], dtype=np.float64)
    pose = np.asarray(z["pose"], dtype=np.float64)
    rows = []
    for a in range(pose.shape[1]):
        for rec in turns_of(t, pose[:, a, 0], pose[:, a, 1], pose[:, a, 2]):
            rows.append((a,) + rec)
    return t, rows


def report(path, t, rows):
    name = os.path.basename(path)
    print()
    print(f"-- {name} " + "-" * max(4, 56 - len(name)))
    if not rows:
        print("   회전 구간을 못 찾았다 — W_MIN / MIN_DEG 를 확인하라")
        return
    end = np.array([r[1] for r in rows])
    mx = np.array([r[2] for r in rows])
    deg = np.array([r[3] for r in rows])
    dur = np.array([r[4] for r in rows])
    print(f"   회전 {len(rows):,}회  ·  {t[-1]:.1f} s  ·  pitch {PITCH}")
    print(f"   회전각  중앙 {np.median(deg):.1f}도   지속 중앙 {np.median(dur):.2f} s")
    print()
    print(f"   {'':<12}{'중앙':>8}{'p95':>8}{'p99':>8}{'최대':>8}   mm")
    print(f"   {'종료 오차':<12}{np.median(end):>8.1f}{np.percentile(end, 95):>8.1f}"
          f"{np.percentile(end, 99):>8.1f}{end.max():>8.1f}")
    print(f"   {'구간 최대':<12}{np.median(mx):>8.1f}{np.percentile(mx, 95):>8.1f}"
          f"{np.percentile(mx, 99):>8.1f}{mx.max():>8.1f}")

    print()
    print(f"   로봇당 예산 {BUDGET:.1f} mm  (= lateral_gap "
          f"{(PITCH - WIDTH) * 1000:.0f} mm 의 절반, 두 대가 나눠 먹는다)")
    for nm, arr in (("종료 오차", end), ("구간 최대", mx)):
        p95, worst = np.percentile(arr, 95), arr.max()
        v95 = "초과" if p95 > BUDGET else "이내"
        vmx = "초과" if worst > BUDGET else "이내"
        print(f"     {nm}   p95 {p95:6.1f} {v95}   최대 {worst:6.1f} {vmx}"
              f"   (초과 회전 {(arr > BUDGET).mean() * 100:.1f}%)")

    print()
    print("   두 대가 마주 볼 때 (같은 통계를 두 번 더한다)")
    for nm, arr in (("종료 오차", end), ("구간 최대", mx)):
        print(f"     {nm}   p95x2 {np.percentile(arr, 95) * 2:6.1f} mm"
              f"   최대x2 {arr.max() * 2:6.1f} mm")
    print(f"     -> 앞2 여유  41.4 mm   ·   4칸/5칸 여유 200.0 mm 와 비교")

    print()
    worst_rows = sorted(rows, key=lambda r: -r[2])[:5]
    print("   구간 최대가 큰 회전 5개")
    for a, e, m, d, du in worst_rows:
        print(f"     agent{a:<3} 종료 {e:6.1f}  구간최대 {m:6.1f}  "
              f"{d:5.1f}도  {du:.2f} s")


def main():
    paths = [p for p in sys.argv[1:] if not p.startswith("-")]
    if not paths:
        raise SystemExit(__doc__)
    print(f"회전 종료 자세 오차 — pitch {PITCH}  로봇당 예산 {BUDGET:.1f} mm")
    for p in paths:
        if not os.path.exists(p):
            print(f"\n* 없음: {p}")
            continue
        t, rows = analyse(p)
        report(p, t, rows)
        split_report(p)
    print()
    print("* 지금까지 쓰던 51 mm 는 한 번의 관측이다. 이 표가 그걸 대체한다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
