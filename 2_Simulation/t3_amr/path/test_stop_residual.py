# -*- coding: utf-8 -*-
"""**왜 칸 중심에 못 서나** — 서는 자리는 두 상수의 비다 (S15P21A106-267).

    python path/test_stop_residual.py

무엇을 밝혔나
-------------
회전 속도 쓸기 9판에서 회전 **시작** 자세의 세로 오차가 판마다 똑같이
**-11.9 mm** 였다 (양수 비율 2~16 %, w 1.2·1.8·2.4 에서 전부 동일).
w 와 무관하니 미끄러짐이 아니다. 계통 오차이고, 뿌리는 제어 상수다.

    목표 근처 속도     v = K_ALONG * along          (isaac_drive:2462)
    도착 판정          |v| <= TOL_STOP_V 도 같이 본다 (at_target)

    둘을 풀면          남는 거리 = TOL_STOP_V / K_ALONG
                                 = 0.02 / 1.6 = 12.5 mm

목표에 **못 미쳐** 선다 — 뒤에서 감속해 오다 느려지면 멈추기 때문이다.
실측 11.9 가 12.5 보다 조금 작은 것은 가속 제한 때문에 v 가 `want` 를
살짝 밑돌아서다.

왜 시험으로 박나
----------------
이야기로 두면 다음 사람이 상수를 만질 때 이 비를 모른 채 만진다. 여기서는
**비를 재고**, 상수를 바꾸면 남는 거리가 그만큼 움직이는지까지 본다.
그러면 「TOL_STOP_V 를 반으로 줄이면 오차도 반이 된다」가 추측이 아니다.

☹ 이 시험은 기구학이다 — 마찰을 안 본다. 그래도 맞는 물음이다. 이 오차는
  **마찰에서 오는 것이 아니라** 제어 종료 조건에서 오기 때문이다. 그게 이
  파일의 주장이고, 9판 실측이 그 주장의 근거다.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pibt_core_v2 as _PC   # noqa: E402,F401  (sim_engine 을 sys.path 에 넣는다)
import isaac_drive as D      # noqa: E402

FAIL = []
DT = 1.0 / 60.0


def check(ok, msg):
    print(("  OK   " if ok else "  ★ 실패 ") + msg)
    if not ok:
        FAIL.append(msg)


def approach(stop_v, k_along, v_exec=0.9, a_exec=0.8):
    """한 칸 전진시키고 **도착이라고 판정한 순간** 남은 거리를 돌려준다 [m]."""
    D.TOL_STOP_V, D.K_ALONG = stop_v, k_along
    geom = D.RobotGeom(pitch=1.0, v_max=0.9, a_lin=a_exec, heading_offset=0)
    ctrl = D.MotionController(geom, v_exec=v_exec, a_exec=a_exec)
    s0, s1 = (5, 5, 1), (5, 6, 1)
    act = D.Action(0, 0, D.MOVE, 0, s0, s1, geom.swept_cells(s0, s1), uid=0)
    ctrl.begin(act)
    x, y, yaw = geom.state_pose(s0)
    tx, ty, _ = geom.state_pose(s1)
    for _ in range(4000):
        if ctrl.at_target((x, y, yaw)):
            return math.hypot(tx - x, ty - y)
        v, w = ctrl.update((x, y, yaw), DT)
        yaw = D.wrap(yaw + w * DT)
        x += v * math.cos(yaw) * DT
        y += v * math.sin(yaw) * DT
    return None


print("\n[1] 서는 자리가 TOL_STOP_V / K_ALONG 인가")
print("    %10s %10s %12s %12s %8s" % ("stop_v", "K_along", "예측 mm", "실제 mm", "비"))
ok_all = True
for sv, k in ((0.02, 1.6), (0.01, 1.6), (0.04, 1.6), (0.02, 3.2), (0.02, 0.8)):
    want = sv / k
    got = approach(sv, k)
    if got is None:
        check(False, "stop_v=%.3f K=%.1f — 도착을 못 했다" % (sv, k))
        ok_all = False
        continue
    ratio = got / want
    print("    %10.3f %10.1f %12.1f %12.1f %8.2f"
          % (sv, k, want * 1000, got * 1000, ratio))
    # 아래로는 가속 제한 때문에 조금 못 미치고, 위로는 이득이 높을수록
    # 이산화가 먼저 걸린다 ([5] 참조). 그래서 양쪽을 다 열어 둔다.
    if not (0.75 <= ratio <= 1.25):
        ok_all = False
check(ok_all, "다섯 조합 모두 예측의 0.75~1.25 배 안")

print("\n[2] 현장 값에서 9판 실측(-11.9 mm)과 맞나")
got = approach(0.02, 1.6) * 1000
check(9.0 <= got <= 15.0,
      "stop_v 0.02 · K 1.6 -> %.1f mm  (실측 11.9 · 식 12.5)" % got)

print("\n[3] 줄이는 두 길이 **같은 비로** 듣나")
half_sv = approach(0.01, 1.6)
dbl_k = approach(0.02, 3.2)
check(abs(half_sv - dbl_k) < 0.002,
      "stop_v 반토막 %.1f mm  ==  K 두 배 %.1f mm  (남는 거리는 비로만 정해진다)"
      % (half_sv * 1000, dbl_k * 1000))

print("\n[4] 이 오차는 **회전 속도와 무관**하다 (9판이 전부 -11.9 였던 이유)")
#   위 경로에 w_exec 이 안 들어간다 — 전진 가지는 w_max 로 조향만 한다.
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "isaac_drive.py"), encoding="utf-8").read()
i = src.index("want = clamp(K_ALONG * along")
seg = src[src.index("sign = self.sign", 0):i]
check("w_exec" not in seg, "전진 감속 경로에 w_exec 이 안 들어간다")

print("\n[5] 이득만 올려서는 **바닥이 있다** — 이산화가 먼저 걸린다")
#   끝에서 한 스텝에 바꿀 수 있는 속도는 a_exec*dt = 0.8/60 = 13.3 mm/s 다.
#   그런데 멈추는 문턱이 20 mm/s 다. 둘이 같은 자릿수라, 문턱을 정밀하게
#   짚을 수가 없다 — K 를 올릴수록 want 가 빨리 변해 이 격차가 더 드러난다.
#   그래서 K 를 두 배 해도 남는 거리가 절반이 안 된다.
step_dv = 0.8 * DT
print("    한 스텝 속도 변화 %.1f mm/s  ·  정지 문턱 %.1f mm/s  ->  같은 자릿수"
      % (step_dv * 1000, 0.02 * 1000))
base = approach(0.02, 1.6)
for k in (1.6, 3.2, 6.4, 12.8):
    g = approach(0.02, k)
    print("    K=%5.1f  예측 %5.1f mm  실제 %5.1f mm" % (k, 0.02 / k * 1000, g * 1000))
floor = approach(0.02, 12.8)
check(floor > 0.004,
      "K 를 8배(12.8) 해도 %.1f mm 아래로 안 내려간다 — 이득만으로는 못 지운다"
      % (floor * 1000))
check(approach(0.005, 1.6) < 0.004,
      "대신 stop_v 를 0.005 로 내리면 %.1f mm 까지 간다 (대신 더 기다린다)"
      % (approach(0.005, 1.6) * 1000))

print()
if FAIL:
    print("★ %d건 실패" % len(FAIL))
    sys.exit(1)
print("모두 통과")
print()
print("서는 자리를 줄이려면 — [5] 가 길을 하나로 좁힌다.")
print("  K_ALONG 을 올린다     7.4 mm 에서 **막힌다.** 8배를 해도 안 내려간다")
print("                        한 스텝 속도 변화 13.3 mm/s 가 문턱 20 과 같은 자릿수라")
print("  TOL_STOP_V 를 내린다  이것만 듣는다. 0.005 면 3.0 mm")
print("                        대가는 시간 — v 가 지수로 줄어 절반마다 ln2/K = 0.43 s")
print("  # 어느 쪽도 재고 바꾼다. 이 시험은 기구학이라 오버슈트·진동은 안 본다.")
