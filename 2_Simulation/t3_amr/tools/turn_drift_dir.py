# -*- coding: utf-8 -*-
"""**회전 중 미끄러짐이 어느 쪽으로 가나** — 원인을 가르는 한 가지 (S15P21A106-267).

    source paths.sh
    python tools/turn_drift_dir.py out/rec_wsw1p80_s104.npz
    python tools/turn_drift_dir.py out/rec_wsw*_s104.npz

Isaac 이 필요 없다 — 이미 있는 NPZ 만 읽는다.

무엇을 가르나
-------------
회전 명령의 병진 속도는 **정확히 0** 이다 (`isaac_drive`, TURN 가지가
`return (0.0, w)`). 기구학으로 돌리면 축이 0.0000 mm 움직인다. 그런데 물리
판에서는 움직인다 — w 1.2·1.8·2.4 에서 RMS 0.60 · 1.27 · 2.83 mm, 로그-로그
기울기 2.24 다. 명령이 0 인데 움직였으니 움직인 것은 전부 물리다.

그럼 **무엇이** 미나. 후보가 셋이고, 추세가 이미 둘을 거른다.

    (가) 관성 — 무게중심이 축에 없다   ✘ **닫혔다** (2026-09-24)
         ① 방향이 안 맞았다. 차체 좌표 적분의 해석해는
              중심이 세로로 d 어긋남 -> 세로 0      · 가로 d*theta
              중심이 가로로 e 어긋남 -> 세로 -e*theta · 가로 0
            무게중심이 축 뒤인 것은 **세로** 어긋남이라 신호가 가로로 나와야
            하는데, 실측은 세로가 거의 전부다 (6.97 대 0.12).
         ② 크기가 안 된다. 무게중심이 구동축에서 **41 mm** 뒤일 뿐이다
            (`2026-09-16_회전중_바퀴헛돎_a6교착.md` §4-6: 합 49.00 kg ·
            무게중심 -0.041 · 구동축 93.6 %). w=1.8 에서 구심가속도가
            1.8^2 x 0.041 = 0.13 m/s^2 — 유효 마찰 0.9 의 한도 8.8 에
            견주면 무시할 크기다.
    (나) 캐스터 끌림 — 뒤 스위블이 옛 방향에 갇혀 끈다
         힘이 거의 일정하니 변위는 지속시간의 제곱, 즉 **1/w^2** 로 준다.
             예측: w 가 크면 **줄어든다**                                  ✘ 추세 반대
         ★★ 그리고 **에셋이 이미 닫는다** (2026-09-24 확인). 캐스터 재질이
            staticFriction 0.0 · dynamicFriction 0.0 — **무마찰로 저작돼**
            있다 (`tools/ground_material.py` 출력, 13대 전부). 마찰이 0 이면
            끌 수가 없다. 추세로 기각했는데 구조로도 기각된다.
    (다) 계단 입력 — 첫 스텝에 바퀴가 헛돈다
         각가속 램프 A/B 에서 363.4 -> 375.5 로 안 변했다 (isaac_drive:2346)  ✘ 닫힘

(나)·(다)는 닫혔다. 남은 (가)를 **방향으로** 시험한다.

무엇을 재나
-----------
축 변위를 **그 순간의 차체 좌표로 돌려** 더한다. 제자리 회전이라 세계 좌표
변위는 호를 그려 방향이 계속 바뀌지만, 구심 방향은 차체 좌표에서 **고정**
(앞쪽)이다. 그래서 차체 좌표로 적분해야 신호가 안 지워진다.

    세로 합이 크고 **양수(앞쪽)**      ->  (가) 맞다
    가로가 크거나 부호가 제각각        ->  (가) 아니다. 다시 생각해야 한다
"""
import glob
import os
import re
import sys

import numpy as np

W_MIN = float(os.environ.get("W_MIN", "0.15"))     # 회전으로 볼 각속도 [rad/s]
MIN_DEG = float(os.environ.get("MIN_DEG", "45"))   # 이만큼은 돌아야 한 회전


def segments(spin):
    i, n = 0, len(spin)
    while i < n:
        if not spin[i]:
            i += 1
            continue
        j = i
        while j < n and spin[j]:
            j += 1
        yield i, j
        i = j + 1


def drift(path):
    """(세로합, 가로합, 회전각) 목록. mm."""
    d = np.load(path)
    t, pose = d["t"], d["pose"]
    dt = np.diff(t)
    dt[dt <= 0] = np.nan
    out = []
    for a in range(pose.shape[1]):
        x, y = pose[:, a, 0], pose[:, a, 1]
        yw = np.unwrap(pose[:, a, 2])
        spin = np.nan_to_num(np.abs(np.diff(yw) / dt)) > W_MIN
        for i, j in segments(spin):
            deg = abs(np.degrees(yw[j] - yw[i]))
            if deg < MIN_DEG:
                continue
            dx, dy = np.diff(x[i:j + 1]), np.diff(y[i:j + 1])
            h = yw[i:j]                       # 각 증분 순간의 헤딩
            lon = float(np.sum(dx * np.cos(h) + dy * np.sin(h)))
            lat = float(np.sum(-dx * np.sin(h) + dy * np.cos(h)))
            turn = float(yw[j] - yw[i])       # 부호 있는 회전각 (+ = 좌회전)
            out.append((lon * 1000.0, lat * 1000.0, deg, turn))
    return out


def w_of(path):
    m = re.search(r"wsw(\d)p(\d\d)", os.path.basename(path))
    return float("%s.%s" % (m.group(1), m.group(2))) if m else float("nan")


def main():
    args = [p for g in sys.argv[1:] for p in (sorted(glob.glob(g)) or [g])]
    if not args:
        raise SystemExit(__doc__)
    print("회전 중 축 밀림의 **방향** — 차체 좌표로 적분한 순변위")
    print("  세로 + = 앞쪽(구심 방향) · 가로 + = 왼쪽")
    print()
    print("%-26s %5s %6s %9s %9s %9s %9s"
          % ("파일", "w", "회전", "세로중앙", "세로평균", "가로중앙", "앞쪽비율"))
    rows_all = []
    for p in args:
        if not os.path.isfile(p):
            print("%-26s  없음" % os.path.basename(p))
            continue
        rows = drift(p)
        if not rows:
            print("%-26s  회전 없음" % os.path.basename(p))
            continue
        lon = np.array([r[0] for r in rows])
        lat = np.array([r[1] for r in rows])
        print("%-26s %5.2f %6d %9.2f %9.2f %9.2f %8.0f%%"
              % (os.path.basename(p), w_of(p), len(rows),
                 np.median(lon), lon.mean(), np.median(lat),
                 100.0 * float(np.mean(lon > 0))))
        rows_all.append((os.path.basename(p), w_of(p), rows))

    # ── 갈림 — 회전 **방향**으로 나눠 본다 ────────────────────────────
    #   차체 좌표 적분의 해석해는 이렇다 (제자리 회전 theta):
    #       중심이 **세로**로 d 어긋남  ->  세로 0      · 가로 d*theta
    #       중심이 **가로**로 e 어긋남  ->  세로 -e*theta · 가로 0
    #   실측은 세로가 거의 전부이므로 어긋난 것은 **가로**다. 그러면 부호가
    #   theta 를 따라가므로, 좌/우 회전에서 **뒤집혀야** 한다.
    #
    #       뒤집힌다      차체에 **고정된** 가로 치우침이다 (바퀴 반지름 차,
    #                     휠베이스 비대칭, 한쪽 접지 — 기계적 비대칭)
    #       안 뒤집힌다   방향과 무관하게 **뒤로 밀린다.** 그러면 위 해석해가
    #                     아니라 다른 기전이다 (캐스터 끌림 같은)
    print()
    print("회전 방향으로 나눔 — **부호가 뒤집히나**")
    print("%-26s %5s %8s %8s %8s %8s"
          % ("파일", "w", "좌n", "좌 세로", "우n", "우 세로"))
    for name, w, rows in rows_all:
        L = np.array([r[0] for r in rows if r[3] > 0])
        R = np.array([r[0] for r in rows if r[3] < 0])
        print("%-26s %5.2f %8d %8s %8d %8s"
              % (name, w, len(L), "—" if not len(L) else "%.2f" % np.median(L),
                 len(R), "—" if not len(R) else "%.2f" % np.median(R)))
    print("   부호가 뒤집히면 차체에 **고정된 가로 치우침**이다 (기계적 비대칭)")
    print("   둘 다 음수면 방향과 무관하게 **뒤로 밀린다** — 다른 기전이다")

    # ── 둘이 겹쳐 있으면 **갈라 낸다** ──────────────────────────────
    #   좌/우가 부호는 같은데 크기가 다르면 성분이 둘이다. 하나는 방향을
    #   안 타고(공통), 하나는 탄다(차동). 더하고 빼면 갈라진다.
    #
    #       좌 = 공통 - 차동      공통 = (좌 + 우) / 2
    #       우 = 공통 + 차동      차동 = (우 - 좌) / 2
    #
    #   ★ 둘은 **고칠 자리가 다르다.**
    #       공통  방향과 무관하게 뒤로 — 캐스터·접지처럼 회전 자체에 딸린 것
    #       차동  좌우 어느 쪽으로 도느냐를 타는 것 — 바퀴 반지름 차,
    #             휠베이스 비대칭 같은 **기계적 비대칭** (tools/wheel_calib.py)
    print()
    print("겹친 둘을 갈라 냄 — 공통(방향 무관) · 차동(방향 탐)")
    print("%-26s %5s %10s %10s %10s"
          % ("파일", "w", "공통 mm", "차동 mm", "공통 비중"))
    for name, w, rows in rows_all:
        L = [r[0] for r in rows if r[3] > 0]
        R = [r[0] for r in rows if r[3] < 0]
        if not L or not R:
            print("%-26s %5.2f   한쪽 방향밖에 없다" % (name, w))
            continue
        ml, mr = float(np.median(L)), float(np.median(R))
        com, dif = (ml + mr) / 2.0, (mr - ml) / 2.0
        tot = abs(com) + abs(dif)
        print("%-26s %5.2f %10.2f %10.2f %9.0f%%"
              % (name, w, com, dif, 100.0 * abs(com) / tot if tot else 0.0))
    print("   공통이 크면 회전 자체에 딸린 것 — 캐스터·접지를 본다")
    print("     (tools/swivel_sweep.py 가 같은 NPZ 의 `joint` 로 캐스터 각을 잰다)")
    print("   차동이 크면 기계적 비대칭 — tools/wheel_calib.py 로 상수를 역산한다")

    print()
    print("읽는 법")
    print("  세로가 크고 **양수 비율이 높다**   -> 관성(무게중심이 축 뒤)이 맞다.")
    print("     그러면 고칠 자리는 마찰이 아니라 **기하**다 — 축을 무게중심 쪽으로")
    print("     옮기거나, 회전 속도를 낮추거나(w^2 로 준다), 회전 중 그 힘을")
    print("     **명령으로 넣어** 주는 것(피드포워드)이다.")
    print("  가로가 더 크거나 부호가 반반  -> 관성이 아니다. 캐스터·접지를 다시 본다.")
    print()
    print("☹ 이 도구는 **방향만** 가른다. 크기를 무게중심 거리로 환산하려면")
    print("  질량·관성이 필요하고, 그건 USD 에서 읽어야 한다 (tools/usd_wheels.py).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
