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
    # 명령 (v, w) — 있으면 실측과 나란히 찍는다. 없는 옛 녹화도 읽힌다.
    cmd = None
    if "cmd" in getattr(z, "files", []):
        c = np.asarray(z["cmd"], dtype=np.float64)
        if c.ndim == 3 and c.shape[0] == len(t) and AGENT < c.shape[1]:
            cmd = c[:, AGENT, :]
    # 관절 속도 — 명령과 pose 사이의 가운데 층.
    jnt, dof = None, []
    if "joint" in getattr(z, "files", []):
        jj = np.asarray(z["joint"], dtype=np.float64)
        if jj.ndim == 3 and jj.shape[0] == len(t) and AGENT < jj.shape[1]:
            jnt = jj[:, AGENT, :]
            dof = [str(s) for s in np.asarray(z["dof_names"]).tolist()] \
                if "dof_names" in z.files else []

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
    if cmd is None:
        print("   ※ 이 녹화에는 명령 (v, w) 이 없다 — 옛 형식이다.")
    print(f"   {'t':>8}{'x':>9}{'y':>9}{'yaw':>9}"
          + (f"{'명령v':>9}{'실측v':>9}{'명령w':>9}{'실측w':>9}" if cmd is not None
             else f"{'속도':>9}{'각속도':>9}")
          + f"{'칸중심까지':>11}")
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
        mid = (f"{cmd[k, 0]:>9.3f}{v:>9.3f}{cmd[k, 1]:>9.3f}{wv:>9.3f}"
               if cmd is not None else f"{v:>9.3f}{wv:>9.3f}")
        print(f"   {t[k]:>8.2f}{x[k]:>9.3f}{y[k]:>9.3f}"
              f"{math.degrees(yaw[k]):>9.1f}{mid}"
              f"{math.hypot(cx - x[k], cy - y[k]) * 1000:>10.0f}mm{mark}")

    # ── 가운데 층 — 바퀴가 명령대로 돌았나, 차체가 바퀴대로 갔나 ─────────
    if jnt is not None and cmd is not None:
        R = float(os.environ.get("WHEEL_RADIUS", "0.08"))
        L = float(os.environ.get("WHEEL_BASE", "0.5796"))
        # 좌·우 구동 바퀴는 **이름으로** 찾는다. 인덱스를 박으면 에셋이
        # 바뀔 때 조용히 부호가 뒤집힌다.
        def find(*keys, default=None):
            for n, nm in enumerate(dof):
                low = nm.lower()
                if all(k in low for k in keys):
                    return n
            return default
        li = find("left", "wheel", default=0)
        ri = find("right", "wheel", default=1)
        print(f"\n── 세 층 대조 (R={R} · L={L}) ──")
        print(f"   DOF {len(dof)}개: {dof or '이름 없음'}")
        print(f"   구동 바퀴 인덱스 L={li} R={ri}"
              f"  ({dof[li] if li < len(dof) else '?'} / "
              f"{dof[ri] if ri < len(dof) else '?'})")
        print(f"   {'t':>8}{'명령v':>8}{'명령w':>8}"
              f"{'좌바퀴':>9}{'우바퀴':>9}{'바퀴v':>8}{'바퀴w':>8}"
              f"{'실측v':>8}{'실측w':>8}")
        for k in range(k0, k1 + 1, span):
            if k + 1 >= len(t):
                break
            d = t[k + 1] - t[k]
            v = math.hypot(x[k + 1] - x[k], y[k + 1] - y[k]) / d if d > 0 else 0.0
            wv = wrap(yaw[k + 1] - yaw[k]) / d if d > 0 else 0.0
            lw, rw = jnt[k, li], jnt[k, ri]
            print(f"   {t[k]:>8.2f}{cmd[k, 0]:>8.3f}{cmd[k, 1]:>8.3f}"
                  f"{lw:>9.3f}{rw:>9.3f}"
                  f"{R * (lw + rw) / 2:>8.3f}{R * (rw - lw) / L:>8.3f}"
                  f"{v:>8.3f}{wv:>8.3f}")
        print(f"\n   ★ 명령 != 바퀴  -> 드라이브가 명령을 못 따라온 것 (토크·마찰)")
        print(f"     바퀴 != 실측  -> 바퀴는 도는데 차체가 다르게 간 것 (미끄러짐)")

        # ── ★ 비구동 관절 — 스위블이 안 돌면 뒤가 끌린다 ──────────────────
        #   제자리 회전에서 스위블은 차체와 **같이** 돌아야 한다. 안 돌면
        #   캐스터가 옛 방향으로만 굴러 차체를 그 선을 따라 끌고 간다.
        #   속도만 기록하므로 각도는 적분해서 본다.
        body = math.degrees(abs(wrap(yaw[j] - yaw[i])))
        print(f"\n── 비구동 관절 — 회전 구간 {t[i]:.2f}~{t[j]:.2f}s "
              f"(차체 {body:.1f}도 회전) ──")
        print(f"   {'관절':<22}{'|속도| 최대':>12}{'적분 각도':>11}{'차체 대비':>10}")
        for n, nm in enumerate(dof):
            if n in (li, ri):
                continue
            seg_v = jnt[i:j + 1, n]
            dtv = np.diff(t[i:j + 1])
            turned = math.degrees(abs(np.sum(seg_v[:-1] * dtv)))
            rel = turned / body if body > 1e-6 else float("nan")
            flag = ""
            if "swivel" in nm.lower():
                flag = ("   <- ★ 거의 안 돌았다" if rel < 0.25 else
                        "   <- 같이 돌았다" if rel > 0.6 else "   <- 부분적")
            print(f"   {nm:<22}{np.abs(seg_v).max():>12.3f}"
                  f"{turned:>10.1f}도{rel:>10.2f}{flag}")
        print(f"\n     ★ 스위블 적분 각도가 차체 회전각의 **1 에 가까워야** 한다 —")
        print(f"       제자리 회전에서 캐스터는 차체와 같이 방향을 틀어야 하기")
        print(f"       때문이다. 0 에 가까우면 옛 방향으로 갇힌 것이고, 그러면")
        print(f"       캐스터가 그 선을 따라서만 굴러 차체를 끌고 간다.")
        print(f"     ※ 좌·우 인덱스는 DOF 이름으로 잡았다. 위 줄에서 확인할 것.")

    print(f"\n   읽는 법")
    print(f"    · (a) 가 크면 **직진이 지나쳐 끝난 것**이다. 회전은 피해자다.")
    print(f"      도착 판정 `at_target` 은 tol.pos 50 mm 안이면 참인데, 그 순간")
    print(f"      속도가 남아 있으면 관성으로 더 간다. 그 거리를 봐야 한다.")
    print(f"    · (b) 가 크면 `v=0` 인데 축이 움직인 것이다. 캐스터 마찰이나")
    print(f"      PhysX 접촉 쪽이고, `tools/axle_frame.py` 로 프레임 오차와")
    print(f"      진짜 밀림을 다시 갈라야 한다.")
    print(f"    · 표의 **속도** 열을 회전 시작 직전에서 본다. 0 이 아니면 (a) 다.")
    if cmd is not None:
        print(f"    · ★ 명령 v 가 0 인데 실측 v 가 0 이 아니면 **물리**다 —")
        print(f"      명령대로 안 따라온 것이다. 명령 v 자체가 0 이 아니면")
        print(f"      **컨트롤러**다 (회전은 v=0 만 낸다).")
        print(f"    · 명령 w 와 실측 w 를 같이 본다. 명령이 포화(2.07)인데 실측이")
        print(f"      한참 작으면 바퀴가 명령 속도를 못 내고 있는 것이다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
