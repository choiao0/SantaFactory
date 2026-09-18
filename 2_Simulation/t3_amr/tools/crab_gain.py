# -*- coding: utf-8 -*-
"""이득비를 바꾸면 **게 걸음 평형이 예산 안으로 들어오나** (S15P21A106-240).

왜 이 도구인가
--------------
2026-09-17 주행에서 a6 의 회전(A6#85)은 대책으로 통과했는데, **바로 다음
액션**(A6#86 `reverse`)이 목표에서 214 mm 떨어진 채 멈췄다.

    pose (50.289, 45.463, 100.0deg)   목표 (50.500, 45.500, 90.0deg)
    along = +0.20 mm    cross = +214.22 mm    head = -10.00 deg
    w = 1.8 x 0.21422 + 2.2 x (-0.17453) = +0.0016 rad/s

`along` 이 0 이라 v 가 없고, 두 항이 상쇄돼 w 도 없다. **움직일 이유가 없는
자리**다. `w = K_CROSS*cross + K_HEAD*head` 의 고정점이고, 평형 예측값
(213.32 mm)과 0.90 mm 차이다.

★ 그런데 「평형식」만 풀면 답이 안 나온다. w=0 을 만족하는 (q, head) 는
  **직선 전체**라서, 어느 q 에 멈추는지는 대수가 아니라 **경로를 다 쓰는 동안
  얼마나 줄였나**로 정해진다. 1 m 밖에 안 남았으면 못 줄인다.

  그래서 이 도구는 평형식을 푸는 게 아니라 **실제 제어식을 적분**한다.
  `MotionController.update()` 의 비회전 분기를 그대로 옮겼다 — 제동 곡선,
  `w_max` 포화, `REVERSE_FACTOR` 감속까지.

무엇을 보나
-----------
    ① 최종 위치오차가 tol.pos(50 mm) 안으로 들어오는 이득비가 있나   ★ 판정
    ② 그 비율에서 게 걸음 각이 얼마나 커지나
    ③ 꼬리 이탈이 예산(로봇당 100 mm)을 넘지 않나

③ 이 관문이다. 꼬리는 지금도 예산 언저리(실측 99.8~109.2 mm)라, 게 걸음을
키우는 방향이면 C 유형을 고치면서 다른 것을 깨뜨린다.

    꼬리 이탈 = |q| + rear_len * |sin(head)|      (`tail_yaw.py` 와 같은 정의)

쓰는 법
-------
    python tools/crab_gain.py                  # 기본 스윕
    Q0=0.378 python tools/crab_gain.py         # 초기 횡이탈 m (기본 0.378 = a6)
    LEN=1.0  python tools/crab_gain.py         # 남은 경로 m (기본 1칸)
    SIGN=-1  python tools/crab_gain.py         # -1 후진 · +1 전진
"""
import math
import os

# ── 실제 상수 (isaac_drive.py · pibt_scene.py) ─────────────────────────────
V_MAX = float(os.environ.get("V_EXEC", "0.9"))       # v_exec 기본 = geom.v_max
A_LIN = float(os.environ.get("A_EXEC", "0.6"))
W_MAX = float(os.environ.get("W_MAX", "1.8"))
REVERSE_FACTOR = 3.0
TOL_POS = float(os.environ.get("TOL_POS", "0.05"))
TOL_YAW = float(os.environ.get("TOL_YAW", "0.05"))
REAR = float(os.environ.get("REAR_LEN", "1.110"))
PITCH = float(os.environ.get("PITCH", "1.0"))
WIDTH = 0.800
DT = 1.0 / 60.0
# 로봇 **한 대**의 꼬리 예산 — 옆 칸 이웃과의 간격 절반.
BUDGET_MM = (PITCH - WIDTH) / 2.0 * 1000.0

Q0 = float(os.environ.get("Q0", "0.378"))            # a6 실측 밀림
LEN = float(os.environ.get("LEN", "1.0"))            # 남은 경로 = 1칸
SIGN = float(os.environ.get("SIGN", "-1"))           # reverse
HEAD0 = math.radians(float(os.environ.get("HEAD0", "0")))


def wrap(a):
    return (a + math.pi) % (2.0 * math.pi) - math.pi


def clamp(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)


def run(kc, kh, q0=Q0, length=LEN, sign=SIGN, head0=HEAD0, trace=False):
    """제어식을 그대로 적분한다. 목표는 원점, 진행축은 +y (후진이면 -y 로 간다).

    좌표를 이렇게 잡는다 — 출발은 목표에서 `length` 만큼 뒤, 옆으로 `q0`.
    목표 yaw 는 +90도(북). `sign=-1` 이면 물리적으로 남쪽으로 간다.
    """
    tx, ty, tyaw = 0.0, 0.0, math.pi / 2.0
    # 진행 방향 단위벡터 = (cos tyaw, sin tyaw) * sign  ->  sign=-1 이면 남쪽
    ux, uy = math.cos(tyaw) * sign, math.sin(tyaw) * sign
    # 출발: 목표에서 진행 방향의 **반대**로 length, 그리고 옆으로 q0
    x = tx - ux * length + (-uy) * q0
    y = ty - uy * length + (ux) * q0
    yaw = wrap(tyaw - head0)

    v = 0.0
    t = 0.0
    v_cap = V_MAX * (1.0 if sign > 0 else 1.0 / REVERSE_FACTOR)
    best = None
    rows = []
    # ★ 상한을 경로에서 뽑는다. 30초로 박아 뒀더니 12 m 판이 **시간에 잘려**
    #   「위치오차 3,073 mm」로 나왔다 — 발산이 아니라 도착을 못 한 것이다.
    #   0.3 m/s 로 12 m 는 40초가 필요하다. 상수 상한은 긴 경로에서 거짓말한다.
    t_max = float(os.environ.get("T_MAX", "0") or 0.0) or (
        10.0 + length / max(v_cap, 1e-3) * 2.0)
    while t < t_max:
        fx, fy = math.cos(yaw) * sign, math.sin(yaw) * sign
        dx, dy = tx - x, ty - y
        along = dx * fx + dy * fy
        cross = fx * dy - fy * dx
        head = wrap(tyaw - yaw)

        w = clamp(kc * cross + kh * head, -W_MAX, W_MAX)
        brake = math.sqrt(2.0 * A_LIN * abs(along)) if along else 0.0
        lim = min(v_cap, max(brake, 0.05))
        want = clamp(1.6 * along, -lim, lim)
        v += clamp(want - v, -A_LIN * DT, A_LIN * DT)

        yaw = wrap(yaw + w * DT)
        x += (sign * v) * math.cos(yaw) * DT
        y += (sign * v) * math.sin(yaw) * DT
        t += DT

        pos = math.hypot(tx - x, ty - y)
        res = max(abs(wrap(tyaw - yaw)) / TOL_YAW, pos / TOL_POS)
        if best is None or res < best[0]:
            best = (res, pos, wrap(tyaw - yaw), cross, along, t)
        if trace and len(rows) < 6:
            rows.append((t, along * 1000, cross * 1000, math.degrees(head), w))
        if res <= 1.0:
            return dict(ok=True, t=t, pos=pos, head=wrap(tyaw - yaw),
                        cross=cross, rows=rows)
        # 멈췄나 — v 와 w 가 둘 다 죽으면 고정점이다
        if abs(v) < 1e-4 and abs(w) < 5e-3 and t > 1.0:
            return dict(ok=False, t=t, pos=pos, head=wrap(tyaw - yaw),
                        cross=cross, stuck=True, rows=rows)
    return dict(ok=False, t=t, pos=math.hypot(tx - x, ty - y),
                head=wrap(tyaw - yaw), cross=cross, stuck=False, rows=rows)


def tail_mm(q, head):
    return (abs(q) + REAR * abs(math.sin(head))) * 1000.0


def main():
    print(f"  초기 횡이탈 {Q0 * 1000:.0f} mm · 남은 경로 {LEN:.2f} m · "
          f"{'후진' if SIGN < 0 else '전진'} · v_cap "
          f"{V_MAX * (1 if SIGN > 0 else 1 / REVERSE_FACTOR):.3f} m/s")
    print(f"  허용 위치 {TOL_POS * 1000:.0f} mm · 허용 각 "
          f"{math.degrees(TOL_YAW):.2f}도 · 꼬리 예산 {BUDGET_MM:.0f} mm")
    print()
    base = run(1.8, 2.2)
    print(f"  ── 지금 이득 (K_CROSS 1.8 / K_HEAD 2.2, 비 0.818) ──")
    print(f"     결과 {'완료' if base['ok'] else '★ 멈춤'} · 위치오차 "
          f"{base['pos'] * 1000:.1f} mm · 게걸음 "
          f"{math.degrees(base['head']):+.2f}도 · 꼬리 "
          f"{tail_mm(base['cross'], base['head']):.1f} mm")
    print()

    print("  ── 이득비 스윕 (K_HEAD 고정 2.2) ──")
    print(f"  {'K_CROSS':>8} {'비':>7} {'위치오차':>9} {'게걸음도':>9} "
          f"{'꼬리mm':>8} {'시간':>6}  판정")
    hit = []
    for kc in (0.4, 0.6, 0.9, 1.2, 1.5, 1.8, 2.2, 2.8, 3.6, 4.8, 6.4, 9.0):
        r = run(kc, 2.2)
        tl = tail_mm(r["cross"], r["head"])
        ok_pos = r["pos"] <= TOL_POS
        ok_tail = tl <= BUDGET_MM
        tag = ("완료" if r["ok"] else "멈춤")
        if ok_pos and ok_tail:
            tag += "  ★ 둘 다 통과"
            hit.append(kc)
        elif ok_pos:
            tag += f"  위치 O · 꼬리 X ({tl:.0f}>{BUDGET_MM:.0f})"
        print(f"  {kc:8.2f} {kc / 2.2:7.3f} {r['pos'] * 1000:8.1f}mm "
              f"{math.degrees(r['head']):+8.2f} {tl:8.1f} {r['t']:6.2f}  {tag}")

    print()
    print("  ── 판정 ──")
    if hit:
        print(f"  ★ 위치·꼬리를 **둘 다** 통과하는 K_CROSS: {hit}")
    else:
        print("  ☠ 둘 다 통과하는 이득비가 **없다.** B 는 이 초기조건에서 닫힌다.")

    print()
    print("  ── 초기 횡이탈이 얼마까지 복구되나 (지금 이득) ──")
    print(f"  {'q0 mm':>7} {'위치오차':>9} {'게걸음도':>9} {'꼬리mm':>8}  판정")
    for q in (0.010, 0.025, 0.050, 0.100, 0.150, 0.200, 0.300, 0.378):
        r = run(1.8, 2.2, q0=q)
        tl = tail_mm(r["cross"], r["head"])
        print(f"  {q * 1000:7.0f} {r['pos'] * 1000:8.1f}mm "
              f"{math.degrees(r['head']):+8.2f} {tl:8.1f}  "
              f"{'완료' if r['ok'] else '★ 멈춤'}")


if __name__ == "__main__":
    main()
