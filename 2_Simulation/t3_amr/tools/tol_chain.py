# -*- coding: utf-8 -*-
"""관문·허용·이득이 **서로를 보고 있나** (S15P21A106-240).

a6 교착을 파다 나온 물음이다. 액션 하나가 횡오차를 얼마나 지우는지 재면
**진입 상한**이 나온다. 그것이 회전 관문(`PIBT_TOL_TURN_POS`)보다 작으면
관문을 통과한 회전이 **다음 액션에 못 끝낼 일**을 넘긴다.

    python tools/tol_chain.py            # 전부
    GAINS=0 python tools/tol_chain.py    # 이득 스윕 빼고

Isaac 이 필요 없다 — 제어기만 적분한다.

★★ 이 도구가 찾은 것 (2026-09-17)
-----------------------------------
    감쇠가 **크기와 무관하게 55.8 %** 로 일정하다 (선형계다).
        끝 = 0.558 x 진입     ->    끝 <= 50 mm 이려면 진입 <= **89.6 mm**
        회전 관문은 **100 mm** 다.   ☹ 정합하지 않는다

    그리고 그 0.558 을 **이득이 정한다.** `tools/crab_gain.py` 가
    「어떤 양수 이득쌍에도 평형이 있다」로 B 를 닫았는데 **반만 맞았다** —
    평형의 **존재**는 못 없애지만, 평형에 **갇히는 것은 진입 오차가 클 때만**
    이고 그 상한을 이득이 올린다. 거기는 평형 **위치**만 봤고
    **수렴 속도**를 안 봤다.

    또 하나: **후진과 전진이 비트 단위로 같다.** 「후진이라 불안정하다」는
    가설은 틀렸다.
"""
import math
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.environ["W"], "path"))
os.environ.setdefault("PIBT_RECOVER", "0")     # 평상 법칙만 본다
import pibt_core_v2                                    # noqa: F401,E402
import isaac_drive as D                                # noqa: E402

G = D.RobotGeom(pitch=1.0, rear_len=1.11, front_len=0.39, width=0.80,
                heading_offset=0)
DT = 1 / 240.0
S0, S1 = (46, 50, 0), (45, 50, 0)      # a6 가 걸리는 바로 그 전이


def run(kind, cross0, head0=0.0, T=12.0):
    """(끝 cross, 최대 cross, 도착했나)."""
    frm, to = (S0, S1) if kind == D.REVERSE else (S1, S0)
    act = D.Action(agent=6, idx=0, kind=kind, tick=0, frm=frm, to=to,
                   cells=G.swept_cells(frm, to))
    c = D.MotionController(G, D.Tolerance())
    c.begin(act)
    fx, fy = math.cos(c.tyaw) * c.sign, math.sin(c.tyaw) * c.sign
    sx, sy, _ = G.state_pose(frm)
    pose = [sx + cross0 * fy, sy - cross0 * fx, c.tyaw - head0]
    mx = 0.0

    def cross():
        gx, gy = math.cos(pose[2]) * c.sign, math.sin(pose[2]) * c.sign
        return abs(gx * (c.ty - pose[1]) - gy * (c.tx - pose[0]))

    for _ in range(int(T / DT)):
        v, w = c.update(tuple(pose), DT)
        pose[2] += w * DT
        pose[0] += v * math.cos(pose[2]) * DT
        pose[1] += v * math.sin(pose[2]) * DT
        mx = max(mx, cross())
        if c.at_target(tuple(pose)):
            return cross(), mx, True
    return cross(), mx, False


# 하위 프로세스로 이득을 바꿔 재려고 코드를 문자열로 둔다 —
# K_CROSS·K_HEAD 가 **import 시점**에 읽히는 모듈 상수라 재import 로는 안 바뀐다.
GAIN_CODE = r'''
import math, os, sys
sys.path.insert(0, os.path.join(os.environ["W"], "path"))
os.environ["PIBT_RECOVER"] = "0"
import pibt_core_v2, isaac_drive as D
G = D.RobotGeom(pitch=1.0, rear_len=1.11, front_len=0.39, width=0.80, heading_offset=0)
DT = 1/240.0
S0, S1 = (46,50,0), (45,50,0)
act = D.Action(agent=6, idx=0, kind=D.REVERSE, tick=0, frm=S0, to=S1,
               cells=G.swept_cells(S0, S1))
c = D.MotionController(G, D.Tolerance()); c.begin(act)
fx, fy = math.cos(c.tyaw)*c.sign, math.sin(c.tyaw)*c.sign
sx, sy, _ = G.state_pose(S0)
c0 = 0.05
pose = [sx + c0*fy, sy - c0*fx, c.tyaw]
for _ in range(int(12.0/DT)):
    v, w = c.update(tuple(pose), DT)
    pose[2] += w*DT
    pose[0] += v*math.cos(pose[2])*DT
    pose[1] += v*math.sin(pose[2])*DT
    if c.at_target(tuple(pose)):
        break
gx, gy = math.cos(pose[2])*c.sign, math.sin(pose[2])*c.sign
print(abs(gx*(c.ty-pose[1]) - gy*(c.tx-pose[0]))/c0)
'''


def gains():
    py = os.path.join(os.path.expanduser("~"), ".venv/amr/bin/python")
    print("\n  4) ★★ 이득이 **감쇠**를 바꾼다 — 진입 상한이 따라 움직인다")
    print("     {:>8} {:>7} {:>7} {:>10}".format(
        "K_CROSS", "K_HEAD", "감쇠", "진입 상한"))
    for kc, kh in ((1.8, 2.2), (3.0, 2.2), (5.0, 2.2), (8.0, 2.2),
                   (1.8, 1.2), (3.0, 1.2)):
        env = dict(os.environ, PIBT_K_CROSS=str(kc), PIBT_K_HEAD=str(kh))
        r = subprocess.run([py, "-c", GAIN_CODE], capture_output=True,
                           text=True, env=env)
        try:
            a = float(r.stdout.strip().splitlines()[-1])
        except Exception:
            print(f"     {kc:8.1f} {kh:7.1f}   실패")
            continue
        lim = 0.050 / a * 1000
        mark = "  ★ 관문 100 을 넘는다" if lim >= 100 else ""
        print(f"     {kc:8.1f} {kh:7.1f} {a * 100:6.1f}% {lim:9.0f}mm{mark}")
    print("     -> 기본 (1.8, 2.2) 은 90 mm 라 **관문 100 보다 작다.**")
    print("        K_CROSS 8.0 이면 231 mm 로 a6 의 211 mm 를 삼킨다.")
    print("     ☹ 공짜는 아니다 — 조향이 세지면 회전 스윕(밀림)이 커질 수 있고,")
    print("        soft_release_safety 의 「밀림 105 mm 까지 안 닿는다」가")
    print("        **지금 이득 기준**이라 같이 다시 재야 한다.")


def main():
    tol = D.Tolerance()
    print(f"  tol.pos {tol.pos * 1000:.0f} mm · tol.yaw "
          f"{math.degrees(tol.yaw):.2f}도 · turn_pos {tol.turn_pos * 1000:.0f} mm")
    print(f"  K_CROSS {D.K_CROSS} · K_HEAD {D.K_HEAD}\n")

    print("  1) 횡변위만 주고 한 액션을 돌린다 — **얼마나 지워지나**")
    print("     {:>8} {:>9} {:>7}  결과".format("진입", "끝", "감쇠"))
    lo = hi = 0.0
    for c0 in (0.02, 0.05, 0.08, 0.09, 0.10, 0.15):
        end, _mx, ok = run(D.REVERSE, c0)
        print(f"     {c0 * 1000:7.0f}mm {end * 1000:8.1f}mm "
              f"{end / c0 * 100:6.1f}%  {'★ 도착' if ok else '☹ 못 감'}")
        if ok:
            lo = max(lo, c0)
        elif not hi:
            hi = c0
    print(f"\n     -> 감쇠가 **크기와 무관하게 일정**하다 (선형계).")
    print(f"        통과 가능한 **진입 상한**이 {lo * 1000:.0f}~{hi * 1000:.0f} mm 사이다.")

    print("\n  2) 헤딩 오차만 주면 — **해롭지 않다**")
    print("     {:>10} {:>11} {:>9}  결과".format("진입 head", "최대 cross", "끝"))
    for h0 in (2.0, 5.0, 10.0, 12.0):
        end, mx, ok = run(D.REVERSE, 0.0, math.radians(h0))
        print(f"     {h0:9.1f}도 {mx * 1000:10.1f}mm {end * 1000:8.1f}mm  "
              f"{'★ 도착' if ok else '☹ 못 감'}")
    print("     (1 m 앞 목표에 헤딩만 φ 면 cross = 1.0·sin φ — 커 보여도 같이 준다)")

    print("\n  3) 후진 대 전진 — **같다**")
    for kind, nm in ((D.REVERSE, "후진"), (D.MOVE, "전진")):
        end, _m, ok = run(kind, 0.10)
        print(f"     {nm}  100mm -> {end * 1000:.1f}mm  "
              f"{'★' if ok else '☹ 못 감'}")
    print("     -> 「후진이라 불안정하다」는 **아니다**")

    print("\n  ── 판정 ──")
    print(f"  회전 관문 {tol.turn_pos * 1000:.0f} mm  vs  진입 상한 ~{lo * 1000:.0f} mm")
    if tol.turn_pos > lo:
        print("  ☹ **관문이 더 헐겁다.** 관문을 통과한 회전이 다음 액션에")
        print("     **구조적으로 못 끝낼 일**을 넘긴다. 둘이 서로를 안 보고 정해졌다.")
        print(f"     정합하려면  turn_pos <= tol.pos / 감쇠 = "
              f"{tol.pos / 0.558 * 1000:.0f} mm  **또는 이득을 올린다**(4).")
    else:
        print("  ★ 관문이 진입 상한보다 빡빡하다 — 정합한다.")


if __name__ == "__main__":
    main()
    if os.environ.get("GAINS", "1") not in ("0", ""):
        gains()
