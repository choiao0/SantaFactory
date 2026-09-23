# -*- coding: utf-8 -*-
"""**가속·감속·회전 시작**을 곡선으로 낸다 — 녹화 `.npz` 에서 (S15P21A106-267).

    python tools/motion_profile.py out/rec_r13.npz
    python tools/motion_profile.py out/rec_r13.npz --robot 3 --svg out/profile.svg

녹화 만들기:  주행에 `PIBT_RECORD=out/rec_r13.npz` 를 준다 (30 Hz, `PIBT_RECORD_HZ`)

왜 이 파일이 있나
-----------------
「한 칸에 최고속도로 못 달린다」와 「최고속도에서 제자리에 못 멈춘다」는 **영상으로
못 보여준다.** 눈으로 「느리다」를 구별할 수 없다. 그 둘은 **곡선**이다.

기존 도구는 각각 한 질문에 숫자로 답한다 —

    tools/measure_seq.py   전환 비용 · 칸마다 멈추나       (틱 수)
    tools/stop_error.py    멈춘 자리가 칸 중심에서 얼마나  (mm)
    tools/turn_error.py    회전 종료 자세 오차             (mm)

이 파일은 그 **앞단**을 낸다: 시간에 대한 속도 v(t) 와 각속도 w(t). 「왜 그
숫자가 나오는지」가 여기 보인다.

무엇을 답하나
-------------
    [1] 가속   한 칸(pitch)을 가는 동안 v 가 v_max 에 닿나
               -> 닿은 적이 없으면 **칸이 짧아서 가속이 안 끝난다**
    [2] 감속   멈추기까지 몇 m 를 더 가나 (곡선의 꼬리)
    [3] 회전   시작 직후 w 가 목표까지 오르는 데 몇 프레임인가
               ★ 바퀴 슬립 **자체**는 이 녹화로 못 잰다 — 자세만 있고 바퀴
                 명령·회전수가 없다. 여기서 보이는 것은 그 결과인 **w 의 지연**
                 이다. 슬립을 직접 재려면 바퀴 조인트 기록이 있어야 한다.

☹ 자세만 있는 녹화라 v·w 는 **차분**이다. 30 Hz 차분은 잡음이 있어 3프레임
  이동평균을 건다 (`--smooth`).

내는 것
-------
숫자는 표준출력, 곡선은 SVG (matplotlib 을 안 쓴다 — 이 저장소의 계측 도구는
어디서나 돌아야 한다).
"""
import argparse
import math
import os
import sys

import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("npz")
ap.add_argument("--robot", type=int, default=-1, help="한 대만 (기본: 전부)")
ap.add_argument("--pitch", type=float, default=float(os.environ.get("PIBT_PITCH", "") or 1.0))
ap.add_argument("--vmax", type=float, default=float(os.environ.get("PIBT_V_PLAN", "") or 0.9))
ap.add_argument("--wmax", type=float, default=2.07, help="계획 각속도 [rad/s]")
ap.add_argument("--smooth", type=int, default=3, help="이동평균 창 (프레임)")
ap.add_argument("--vmin", type=float, default=0.05, help="이 아래는 정지로 본다 [m/s]")
ap.add_argument("--wmin", type=float, default=0.15, help="이 아래는 직진으로 본다 [rad/s]")
ap.add_argument("--svg", default="", help="곡선 SVG 경로 (기본 <npz>_profile.svg)")
A = ap.parse_args()


def smooth(a, n):
    if n <= 1 or len(a) < n:
        return a
    k = np.ones(n) / n
    return np.convolve(a, k, mode="same")


def wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


z = np.load(A.npz, allow_pickle=False)
t, P = z["t"], z["pose"]                       # t[F], P[F, N, 3]
F, N = P.shape[0], P.shape[1]
dt = float(np.median(np.diff(t))) if F > 1 else 1 / 30.0
print("═" * 72)
print("%s · 프레임 %d · 로봇 %d대 · %.1f Hz · %.1f 초"
      % (os.path.basename(A.npz), F, N, 1 / dt, t[-1] - t[0]))
print("계획 v_max %.2f m/s · w_max %.2f rad/s · 칸 %.2f m" % (A.vmax, A.wmax, A.pitch))
print("═" * 72)

robots = range(N) if A.robot < 0 else [A.robot]
runs, stops, turns = [], [], []
best = None                                    # 그림으로 낼 한 구간

for r in robots:
    x, y, th = P[:, r, 0], P[:, r, 1], P[:, r, 2]
    v = smooth(np.hypot(np.diff(x), np.diff(y)) / dt, A.smooth)
    w = smooth(np.abs(wrap(np.diff(th))) / dt, A.smooth)
    moving = (v > A.vmin) & (w < A.wmin)       # 전진 구간
    spin = w >= A.wmin                         # 회전 구간

    # ── [1][2] 전진 구간 — 칸 하나를 가는 동안의 v 곡선 ────────────
    i = 0
    while i < len(moving):
        if not moving[i]:
            i += 1
            continue
        j = i
        while j < len(moving) and moving[j]:
            j += 1
        seg = v[i:j]
        dist = float(np.sum(seg) * dt)
        if len(seg) >= 4 and dist > A.pitch * 0.5:
            peak = float(seg.max())
            runs.append((peak, dist, (j - i) * dt))
            # 감속 꼬리 — 최고점 뒤 v 가 vmin 아래로 내려가기까지 간 거리
            k = int(np.argmax(seg))
            tail = float(np.sum(seg[k:]) * dt)
            stops.append(tail)
            if best is None or dist > best[3]:
                best = (r, i, j, dist)
        i = j

    # ── [3] 회전 시작 — w 가 목표까지 오르는 데 걸리는 프레임 ──────
    i = 0
    while i < len(spin):
        if not spin[i]:
            i += 1
            continue
        j = i
        while j < len(spin) and spin[j]:
            j += 1
        seg = w[i:j]
        if len(seg) >= 4:
            pk = float(seg.max())
            rise = int(np.argmax(seg >= pk * 0.9)) + 1      # 90 % 도달 프레임
            turns.append((pk, rise * dt, (j - i) * dt))
        i = j

if not runs:
    print("전진 구간을 못 찾았다 — --vmin/--wmin 을 조절하거나 녹화가 짧다.")
    sys.exit(1)

pk = np.array([r[0] for r in runs])
ds = np.array([r[1] for r in runs])
print("\n[1] 가속 — 한 칸을 가는 동안 v 가 어디까지 오르나   (전진 구간 %d개)" % len(runs))
print("    최고 v   중앙 %.3f · p90 %.3f · 최대 %.3f m/s" % (np.median(pk), np.percentile(pk, 90), pk.max()))
print("    v_max %.2f 대비  중앙 **%.0f %%** · 최대 %.0f %%" % (A.vmax, 100*np.median(pk)/A.vmax, 100*pk.max()/A.vmax))
print("    구간 거리 중앙 %.2f m (칸 %.2f)" % (np.median(ds), A.pitch))
if np.median(pk) < A.vmax * 0.95:
    print("    ☹ 칸 하나로는 **가속이 안 끝난다** — 계획이 쓰는 %.2f m/s 에 못 닿는다" % A.vmax)

ta = np.array(stops)
print("\n[2] 감속 — 최고점을 지나 멈추기까지 더 가는 거리")
print("    중앙 %.3f m · p90 %.3f m · 최대 %.3f m" % (np.median(ta), np.percentile(ta, 90), ta.max()))
print("    칸 %.2f m 대비 중앙 **%.0f %%**" % (A.pitch, 100*np.median(ta)/A.pitch))

if turns:
    tp = np.array([x[0] for x in turns])
    tr = np.array([x[1] for x in turns])
    print("\n[3] 회전 — 시작 뒤 w 가 최고의 90 %% 에 닿기까지   (회전 구간 %d개)" % len(turns))
    print("    올라가는 시간 중앙 %.3f s (%.1f 프레임) · p90 %.3f s"
          % (np.median(tr), np.median(tr)/dt, np.percentile(tr, 90)))
    print("    최고 w 중앙 %.2f rad/s (계획 %.2f 의 %.0f %%)" % (np.median(tp), A.wmax, 100*np.median(tp)/A.wmax))
    print("    ☹ 바퀴 슬립 **자체**는 이 녹화로 못 잰다 — 자세만 있고 바퀴 명령이 없다.")
    print("      여기 보이는 것은 그 결과인 **w 의 지연**이다.")

# ── 곡선 SVG ─────────────────────────────────────────────────────────
r, i0, i1, _ = best
x, y, th = P[:, r, 0], P[:, r, 1], P[:, r, 2]
vv = smooth(np.hypot(np.diff(x), np.diff(y)) / dt, A.smooth)[max(0, i0-6):i1+6]
tt = np.arange(len(vv)) * dt
Wpx, Hpx, ml, mb = 760, 300, 62, 42
sx = (Wpx - ml - 18) / max(1e-9, tt[-1])
sy = (Hpx - mb - 22) / max(A.vmax * 1.15, vv.max() * 1.05)
pts = " ".join("%.1f,%.1f" % (ml + tt[k]*sx, Hpx - mb - vv[k]*sy) for k in range(len(vv)))
ymax = Hpx - mb - A.vmax * sy
svg = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">
<style>
 text{font-family:monospace;font-size:12px;fill:#2a2f38}
 .ax{stroke:#8b939f;stroke-width:1;fill:none}
 .vm{stroke:#c0392b;stroke-width:1.4;stroke-dasharray:6 4;fill:none}
 .v {stroke:#1f6f8b;stroke-width:2;fill:none}
 .lb{fill:#5a6472;font-size:11px}
</style>
<rect width="100%%" height="100%%" fill="#ffffff"/>
<polyline class="ax" points="%d,%d %d,%d %d,%d"/>
<line class="vm" x1="%d" y1="%.1f" x2="%d" y2="%.1f"/>
<text class="lb" x="%d" y="%.1f">v_max %.2f</text>
<polyline class="v" points="%s"/>
<text x="%d" y="18">전진 한 구간의 속도 — 로봇 %d · %.2f m · 최고 %.3f m/s (v_max 의 %.0f%%)</text>
<text class="lb" x="%d" y="%d">시간 [s] 0 … %.2f</text>
</svg>
""" % (Wpx, Hpx, Wpx, Hpx,
       ml, 22, ml, Hpx-mb, Wpx-18, Hpx-mb,
       ml, ymax, Wpx-18, ymax,
       ml+4, ymax-4, A.vmax,
       pts,
       ml, r, float(np.sum(vv)*dt), float(vv.max()), 100*float(vv.max())/A.vmax,
       ml, Hpx-14, tt[-1])
out = A.svg or (os.path.splitext(A.npz)[0] + "_profile.svg")
open(out, "w", encoding="utf-8").write(svg)
print("\n곡선 -> %s" % out)
print("  (이 그림 하나가 「한 칸에 최고속도로 못 달린다」를 말한다 —")
print("   빨간 점선이 계획이 쓰는 v_max, 파란 곡선이 실제다)")
