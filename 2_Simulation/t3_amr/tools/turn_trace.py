# -*- coding: utf-8 -*-
"""회전 **하나**의 축 궤적을 뜯어본다 (S15P21A106-224).

무엇을 가리는가
---------------
시드 7 에서 agent6 이 `turn(46,50,3)->(46,50,0)` 를 못 끝냈다. 끝 자세의 축이
목표 칸 중심에서 **서쪽으로 360 mm** 밀려 있었고, 그 때문에 몸이 `released`
칸 (46,49) 를 물어 `complete()` 가 영영 거짓이 됐다 (`tools/why_deadlock.py`).

360 mm 가 어디서 왔는지는 둘 중 하나다.

    (a) 회전 **시작 때 이미** 밀려 있었다
        -> 직전 직진이 목표를 지나쳐 끝난 것. 문제는 MOVE 와 도착 판정에 있다

    (b) 회전 **도중에** 밀렸다
        -> `v = 0` 을 명령했는데 축이 움직인 것. 문제는 회전 물리에 있다

둘은 섞일 수도 있어서 **쪼개서** 낸다.

회전 구간은 각속도 문턱으로 자르지 않는다. 그 방식은 예전에 같은 사건을
318 mm -> 119 mm 로 축소해 보이게 했다 (느린 구간이 잘려 나갔다). 대신
**yaw 가 목표각에 처음 든 시각**을 끝으로 잡고, 거기서 거꾸로 yaw 가
출발각에 마지막으로 머문 시각을 시작으로 잡는다.

쓰는 법
-------
    source paths.sh
    PITCH=1.0 AGENT=6 CELL=46,50 python tools/turn_trace.py $OUT/rec_s7_dev2.npz

    AGENT    볼 로봇 (기본 6)
    CELL     목표 칸 "행,열" (기본 46,50)
    YAW0     출발 헤딩의 각도 (기본 180 = 서)
    YAW1     도착 헤딩의 각도 (기본 90 = 북)
    T0 / T1  볼 시간 창 초 (기본 전체)
"""
import math
import os
import sys

import numpy as np

PITCH = float(os.environ.get("PITCH", os.environ.get("PIBT_PITCH", "1.0")))
AGENT = int(os.environ.get("AGENT", "6"))
YAW0 = math.radians(float(os.environ.get("YAW0", "180")))
YAW1 = math.radians(float(os.environ.get("YAW1", "90")))
NEAR = math.radians(float(os.environ.get("NEAR_DEG", "3")))


def wrap(a):
    return (a + np.pi) % (2.0 * np.pi) - np.pi


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args:
        raise SystemExit(__doc__)
    path = args[0]
    row, col = (int(v) for v in os.environ.get("CELL", "46,50").split(","))
    o = PITCH / 2.0
    cx, cy = o + col * PITCH, o + row * PITCH      # 목표 칸 중심

    z = np.load(path, allow_pickle=True)
    t = np.asarray(z["t"], dtype=np.float64)
    pose = np.asarray(z["pose"], dtype=np.float64)
    if AGENT >= pose.shape[1]:
        raise SystemExit(f"★ agent{AGENT} 이 없습니다 (로봇 {pose.shape[1]}대)")
    x, y, yaw = pose[:, AGENT, 0], pose[:, AGENT, 1], pose[:, AGENT, 2]

    lo = float(os.environ.get("T0", t[0]))
    hi = float(os.environ.get("T1", t[-1]))
    win = (t >= lo) & (t <= hi)
    if not win.any():
        raise SystemExit(f"★ 창 {lo}~{hi}s 에 프레임이 없습니다")

    print(f"[turn_trace] {os.path.basename(path)} · agent{AGENT} · "
          f"목표 칸 ({row},{col}) 중심 ({cx:.3f}, {cy:.3f})")
    print(f"   {len(t):,} 프레임 · {t[0]:.1f}~{t[-1]:.1f}s · "
          f"창 {lo:.1f}~{hi:.1f}s")

    # ── 회전 구간 — 각도로 자른다 (각속도 문턱을 쓰지 않는다) ─────────────
    at1 = np.abs(wrap(YAW1 - yaw)) < NEAR
    at0 = np.abs(wrap(YAW0 - yaw)) < NEAR
    idx = np.nonzero(win & at1)[0]
    if len(idx) == 0:
        raise SystemExit(f"★ 창 안에서 yaw 가 {math.degrees(YAW1):.0f}도 에 "
                         f"든 적이 없습니다")
    j = int(idx[0])                       # 목표각에 **처음** 든 시각
    pre = np.nonzero(at0[:j])[0]
    if len(pre) == 0:
        raise SystemExit(f"★ 그 앞에 yaw 가 {math.degrees(YAW0):.0f}도 였던 "
                         f"적이 없습니다")
    i = int(pre[-1])                      # 출발각에 **마지막으로** 있던 시각

    def off(k):
        return (cx - x[k]) * 1000.0, (cy - y[k]) * 1000.0

    ox0, oy0 = off(i)
    ox1, oy1 = off(j)
    print(f"\n── 회전 구간 ──")
    print(f"   시작 t={t[i]:7.2f}s  축 ({x[i]:.3f}, {y[i]:.3f})  "
          f"yaw {math.degrees(yaw[i]):+7.1f}도   칸중심 이탈 ({ox0:+.0f}, {oy0:+.0f}) mm")
    print(f"   끝   t={t[j]:7.2f}s  축 ({x[j]:.3f}, {y[j]:.3f})  "
          f"yaw {math.degrees(yaw[j]):+7.1f}도   칸중심 이탈 ({ox1:+.0f}, {oy1:+.0f}) mm")
    print(f"   지속 {t[j] - t[i]:.2f}s · {j - i} 프레임")

    # ── ★ 쪼개기 ────────────────────────────────────────────────────────
    seg = np.hypot(np.diff(x[i:j + 1]), np.diff(y[i:j + 1])).sum() * 1000.0
    net = math.hypot(x[j] - x[i], y[j] - y[i]) * 1000.0
    start = math.hypot(ox0, oy0)
    end = math.hypot(ox1, oy1)
    print(f"\n── ★ 360 mm 는 어디서 왔나 ──")
    print(f"   (a) 회전 시작 때 이미 있던 이탈   {start:7.1f} mm")
    print(f"   (b) 회전 중 축 이동 (알짜)        {net:7.1f} mm")
    print(f"       회전 중 축 이동 (경로 길이)   {seg:7.1f} mm")
    print(f"   ---------------------------------------------")
    print(f"   회전 끝 이탈                      {end:7.1f} mm")
    verdict = ("(a) 직진이 목표를 지나쳐 끝났다 — MOVE·도착 판정 쪽"
               if start > end * 0.6 else
               "(b) 회전 중에 밀렸다 — v=0 인데 축이 움직였다")
    print(f"   ★ {verdict}")

    # ── 궤적 표 ─────────────────────────────────────────────────────────
    print(f"\n── 궤적 (회전 앞뒤 포함) ──")
    print(f"   {'t':>8}{'x':>9}{'y':>9}{'yaw':>9}"
          f"{'속도':>9}{'각속도':>9}{'칸중심까지':>11}")
    span = max(1, (j - i) // 14)
    k0 = max(0, i - span * 6)
    k1 = min(len(t) - 1, j + span * 4)
    for k in range(k0, k1 + 1, span):
        if k + 1 >= len(t):
            break
        d = t[k + 1] - t[k]
        v = math.hypot(x[k + 1] - x[k], y[k + 1] - y[k]) / d if d > 0 else 0.0
        wv = wrap(yaw[k + 1] - yaw[k]) / d if d > 0 else 0.0
        mark = "  <- 회전 시작" if i <= k < i + span else (
               "  <- 회전 끝" if j <= k < j + span else "")
        print(f"   {t[k]:>8.2f}{x[k]:>9.3f}{y[k]:>9.3f}"
              f"{math.degrees(yaw[k]):>9.1f}{v:>9.3f}{wv:>9.3f}"
              f"{math.hypot(cx - x[k], cy - y[k]) * 1000:>10.0f}mm{mark}")

    print(f"\n   읽는 법")
    print(f"    · (a) 가 크면 **직진이 지나쳐 끝난 것**이다. 회전은 피해자다.")
    print(f"      도착 판정 `at_target` 은 tol.pos 50 mm 안이면 참인데, 그 순간")
    print(f"      속도가 남아 있으면 관성으로 더 간다. 그 거리를 봐야 한다.")
    print(f"    · (b) 가 크면 `v=0` 인데 축이 움직인 것이다. 캐스터 마찰이나")
    print(f"      PhysX 접촉 쪽이고, `tools/axle_frame.py` 로 프레임 오차와")
    print(f"      진짜 밀림을 다시 갈라야 한다.")
    print(f"    · 표의 **속도** 열을 회전 시작 직전에서 본다. 0 이 아니면 (a) 다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
