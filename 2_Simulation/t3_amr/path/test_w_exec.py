# -*- coding: utf-8 -*-
"""`PIBT_W_EXEC` 가 **제자리 회전에만** 걸리나 (S15P21A106-267).

    python path/test_w_exec.py

왜 이 시험이 있나
-----------------
회전 밀림의 원인을 쓸어 보려고 회전 속도 손잡이를 새로 냈다. 그 실험이
성립하려면 두 가지가 **동시에** 참이라야 한다.

    (가) 회전 명령이 실제로 `w_exec` 에서 잘린다
    (나) 직진 중 **조향**은 안 바뀐다

(나)가 깨지면 「회전이 빨라서 밀렸나」와 「조향이 세서 밀렸나」가 섞여 쓸어도
답이 안 나온다. 눈으로는 못 본다 — 둘 다 같은 `w` 로 나가기 때문이다.
그래서 시험으로 박아 둔다.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pibt_core_v2 as _PC   # noqa: E402,F401  (sim_engine 을 sys.path 에 넣는다)
import isaac_drive as D      # noqa: E402

FAIL = []


def check(ok, msg):
    print(("  OK   " if ok else "  ★ 실패 ") + msg)
    if not ok:
        FAIL.append(msg)


def turn_w(w_exec, steps=1):
    """제자리 90도 회전을 시작하고 첫 스텝의 각속도를 돌려준다.

    ★ 자세는 `state_pose(s0)` 에서 받는다. 헤딩 인덱스 0 이 yaw 0 이 아니다 —
      0 -> 90도, 1 -> 0도 다. 0.0 을 손으로 넣었다가 오차가 0 이 돼 회전이
      아예 안 걸렸다.
    """
    geom = D.RobotGeom(pitch=1.0, w_max=1.8, heading_offset=0)
    ctrl = D.MotionController(geom, w_exec=w_exec)
    s0, s1 = (5, 5, 0), (5, 5, 1)
    act = D.Action(0, 0, D.TURN, 0, s0, s1, geom.swept_cells(s0, s1), uid=0)
    ctrl.begin(act)
    x, y, yaw = geom.state_pose(s0)
    w = 0.0
    for _ in range(steps):
        _, w = ctrl.update((x, y, yaw), 1.0 / 60.0)
    return w


print("\n[1] 회전이 w_exec 에서 잘리나")
# 90도 오차면 3*err = 4.71 이라 어떤 상한이든 포화한다.
for wx in (0.9, 1.8, 3.0):
    # 각가속 제한이 켜져 있으면 첫 스텝은 램프에 걸린다 — 여기선 끄고 본다.
    D.W_ACCEL = 0.0
    got = turn_w(wx)
    check(abs(abs(got) - wx) < 1e-9,
          f"w_exec={wx:.1f} -> 명령 {abs(got):.3f} rad/s")

print("\n[2] 안 주면 계획값(geom.w_max=1.8) 그대로인가")
D.W_ACCEL = 0.0
check(abs(abs(turn_w(None)) - 1.8) < 1e-9, "기본이 1.8")

print("\n[3] 직진 중 조향은 **안 바뀐다**")
#   횡오차를 크게 줘서 조향이 포화하게 만든 뒤, w_exec 를 낮춰도 그대로인지 본다.
geom = D.RobotGeom(pitch=1.0, w_max=1.8, heading_offset=0)
s0, s1 = (5, 5, 1), (5, 6, 1)
act = D.Action(0, 0, D.MOVE, 0, s0, s1, geom.swept_cells(s0, s1), uid=0)
ws = []
for wx in (1.8, 0.3):
    D.W_ACCEL = 0.0
    c = D.MotionController(geom, w_exec=wx)
    c.begin(act)
    x, y, yaw = geom.state_pose(s0)
    _, w = c.update((x, y + 0.6, yaw + 1.2), 1.0 / 60.0)   # 크게 틀어 놓는다
    ws.append(w)
check(abs(ws[0]) > 1e-6, f"조향이 실제로 걸렸다 ({abs(ws[0]):.3f} rad/s)")
check(abs(ws[0] - ws[1]) < 1e-12,
      f"w_exec 1.8 -> 0.3 인데 조향은 그대로 ({abs(ws[1]):.3f} rad/s)")

print("\n[4] 환경변수가 FleetController 까지 닿나")
os.environ["PIBT_W_EXEC"] = "2.4"
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "isaac_drive.py"), encoding="utf-8").read()
check('os.environ.get("PIBT_W_EXEC"' in src, "FleetController 가 PIBT_W_EXEC 를 읽는다")
check(src.count("self.w_exec") >= 3, "w_exec 가 컨트롤러까지 전달된다")

print()
if FAIL:
    print("★ %d건 실패" % len(FAIL))
    sys.exit(1)
print("모두 통과")
