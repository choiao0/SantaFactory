# -*- coding: utf-8 -*-
"""대기가 **어디서** 일어나는가 — 기록에서 정체 지점을 찾는다.

`motion_profile.py` 는 "얼마나" 기다리는지 알려 주지만 "왜" 를 못 말한다.
로봇이 선 **자리**를 세면 원인이 보인다. 출발 구역이 막히는 것인지, 특정
통로가 병목인지, 목적지 앞에서 줄을 서는 것인지.

    대기 = v < 0.05 m/s 이고 yaw 도 안 도는 프레임 (회전은 제외)

    source paths.sh
    python tools/wait_hotspots.py $OUT/rec_carry2.npz
    TOP=30 python tools/wait_hotspots.py $OUT/rec_full.npz $OUT/rec_carry2.npz
"""
import os
import sys
from collections import defaultdict

import numpy as np

V_STOP, W_TURN = 0.05, 0.10
PITCH = float(os.environ.get("PIBT_PITCH", "1.0"))
TOP = int(os.environ.get("TOP", "15"))


def wrap(a):
    return (a + np.pi) % (2.0 * np.pi) - np.pi


def hotspots(path):
    z = np.load(path, allow_pickle=True)
    t = z["t"].astype(np.float64)
    p = z["pose"].astype(np.float64)
    dt = np.diff(t)
    v = np.hypot(np.diff(p[:, :, 0], axis=0), np.diff(p[:, :, 1], axis=0)) / dt[:, None]
    w = np.abs(wrap(np.diff(p[:, :, 2], axis=0))) / dt[:, None]
    wait = (v < V_STOP) & (w < W_TURN)

    # 대기 프레임의 칸. cell_center = pitch/2 + pitch*k  ->  k = round(x/pitch - 0.5)
    cell = defaultdict(float)                 # (r, c) -> 대기 초
    who = defaultdict(set)
    T, N = wait.shape
    for i in range(T):
        for a in range(N):
            if not wait[i, a]:
                continue
            c = int(round(p[i, a, 0] / PITCH - 0.5))
            r = int(round(p[i, a, 1] / PITCH - 0.5))
            cell[(r, c)] += dt[i]
            who[(r, c)].add(a)
    total = sum(cell.values())
    return cell, who, total, float(t[-1]), N


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args:
        raise SystemExit(__doc__)
    for f in args:
        cell, who, total, dur, n = hotspots(f)
        print("=" * 72)
        print(f"{os.path.basename(f)}   완주 {dur:.1f}s · {n}대 · "
              f"총 대기 {total:.0f} 로봇초 ({total / (dur * n) * 100:.1f}%)")
        print(f"{'칸 (r,c)':>12}{'world (x,y)':>18}{'대기 s':>9}{'전체%':>7}  로봇")
        for k in sorted(cell, key=cell.get, reverse=True)[:TOP]:
            r, c = k
            x, y = PITCH / 2 + c * PITCH, PITCH / 2 + r * PITCH
            ws = sorted(who[k])
            print(f"{str(k):>12}{f'({x:.1f}, {y:.1f})':>18}"
                  f"{cell[k]:9.1f}{cell[k] / total * 100:6.1f}%  "
                  f"{len(ws)}대 {ws if len(ws) <= 6 else str(ws[:6]) + '…'}")
        top = sum(sorted(cell.values(), reverse=True)[:TOP])
        print(f"\n상위 {TOP}칸이 전체 대기의 {top / total * 100:.1f}% · "
              f"대기가 일어난 칸 {len(cell)}개")


if __name__ == "__main__":
    main()
