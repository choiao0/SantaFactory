# -*- coding: utf-8 -*-
"""A 복구 기동 — **차체가 예약 칸 밖으로 더 나가나**를 먼저 묻는다 (S15P21A106-240).

왜 이것이 먼저인가
------------------
지배식에서 4구간 기동의 모양이 나왔다.

    Δcross = -∫ w·along dt = **-∫ along dθ**   = (along, θ) 평면의 부호 있는 넓이

    ㄱ 제자리에서 튼다   along~0 이라 **공짜**
    ㄴ 곧게 물러난다     along 을 키운다
    ㄷ 먼 쪽에서 튼다    along 이 크니 **여기서 번다**
    ㄹ 곧게 돌아온다     되돌릴 각을 최소로

그런데 ㄷ 에서 **1.5 m 짜리 차체를 1 m 격자 안에서 튼다.** 그 스윕이 예약
칸(`action.cells`) 밖으로 나가면 복구 기동이 **새 충돌 경로**가 된다.
이 물음이 A 를 닫을 수도 있어서 만들기 전에 묻는다.

★ 판정 기준 — 「벗어나나」가 아니라 **「새 칸이 느나」**다
--------------------------------------------------------
멈춘 자세가 **이미** 예약 밖이다. `cross 211 mm` 가 측면 여유
`pitch - width = 200 mm` 보다 크기 때문이고, 기동과 무관하다.

    목표 자세 (오차 0)   몸 [(45,50),(46,50)]                 벗어남 **없음**
    a6 멈춘 자세         몸 [(44,50),(44,51),(45,50),(45,51)] 벗어남 2칸

그래서 「벗어남 0」을 기준으로 쓰면 **모든 조합이 탈락**한다 — 실제로 처음에
그렇게 재고 「A 는 성립하지 않는다」로 결론 낼 뻔했다. 옳은 기준은 **기동이
칸을 더 늘리지 않는가**다.

★★ 결론 — **A 는 예약을 벗어나지 않고는 못 한다. 기하가 그렇다** (2026-09-17)
-------------------------------------------------------------------------
    칸 1,000 mm · 폭 800 mm   ->  한쪽 여유 **100 mm**
    꼬리 1,110 mm 가 θ 만큼 틀면 측면으로 1.11·sin(θ)
    -> **가운데에 있어도 θ > 5.2도 면 반드시 칸을 벗어난다**

그런데 `Δcross ~ d·θ` 라 회전 없이는 `cross` 가 안 준다. 즉 **고칠 수단이
칸을 벗어나는 것뿐**이다. θ 를 5도 아래로 낮춰도 벗어남은 줄 뿐 안 없어지고,
회수만 는다 (θ=3도·d=0.3 m 면 14회).

실제로 반복해 보면 **어떤 (d, θ) 조합도 반대편 칸 `(44,51)` 을 건드린다.**
`ㄱ`(제자리 -θ)을 빼면 오히려 **둘**로 는다 — `ㄱ` 은 도움이 되고 있었다.

    d 0.3 · θ 5도   6회   같은열 [(46,49)] / 반대편 [(44,51)]
    d 0.5 · θ 10도  2회   같은열 [(46,49)] / 반대편 [(44,51)]
    ㄱ 없이         더 나쁨 — 반대편 [(44,51), (45,51)]

-> 그래서 남은 물음이 「A 가 칸을 벗어나나」(답: **예, 반드시**)가 아니라
   **「벗어나는 그 칸이 비어 있나」**로 바뀐다. 셋을 확인해야 한다:

       (46,49)   물러날 때. 이미 넘친 열의 연장
       (44,51)   기동 중. **반대편** — 없던 자리다
       (44,49) (45,49)   멈춘 자세가 이미 쓰고 있다 (A 와 무관)

   교착이면 A6#86 의 `released` 를 기다리는 후행은 **정의상 대기 중**이라
   ADG 가 보장한다. 위험은 **무관한 제3자 예약**이다. 그 시점 12대 예약을
   훑어 위 칸들과 겹치는지 봐야 한다 (`why_deadlock` 계열).

★ heading_offset 주의
---------------------
`2` 로 두면 기하가 통째로 한 칸 밀린다 — `swept` 가
`[(45,50),(46,50),(47,50)]` 로 나오는데 실측 로그는 `[(44,50),(45,50),(46,50)]`
이다. 판정은 이 한 줄이다:

    footprint_cells(state_pose(S1)) == occupied(S1)

재는 법
-------
Isaac 이 필요 없다. 기동을 **개루프로 적분**하고 매 스텝 SAT 발자국을 본다.

    python tools/recover_design.py
    D=0.2,0.3 TH=15,20,25 python tools/recover_design.py
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.environ["W"], "path"))
import pibt_core_v2                                    # noqa: F401,E402
import isaac_drive as D                                # noqa: E402

DT = 1.0 / 240.0                # 기동만 보므로 곱게 적분한다
GEOM = D.RobotGeom(pitch=1.0, rear_len=1.11, front_len=0.39, width=0.80,
                   heading_offset=0)          # ★ 위 주석 참고. 2 면 한 칸 밀린다
# a6 실측 (시드 7 · A6#86) — along 37 mm · cross 211 mm · head -10.0도
S0, S1 = (46, 50, 0), (45, 50, 0)
ALONG0, CROSS0, HEAD0 = 0.037, 0.211, math.radians(-10.0)
W_MAX = GEOM.w_max
V_MAX = 0.30                    # 복구는 천천히
SPILL_COLS: set = set()         # main() 이 채운다 — 멈춘 자세가 이미 넘친 열
# ★ 남은 cross 에 θ 를 맞출까 (ADAPT=0 이면 고정 θ — 대조용)
ADAPT = os.environ.get("ADAPT", "1") not in ("0", "", "no")
# ★ ㄱ(제자리 -θ) 을 뺄까 — cross 로는 공짜인데 발자국으로는 꼬리를 밀어낸다
NO_G = os.environ.get("NO_G", "0") not in ("0", "", "no")


def controller():
    act = D.Action(agent=6, idx=0, kind=D.REVERSE, tick=651, frm=S0, to=S1,
                   cells=GEOM.swept_cells(S0, S1))
    c = D.MotionController(GEOM, D.Tolerance())
    c.begin(act)
    return c


def start_pose(c):
    """목표에서 (along, cross, head) 만큼 어긋난 자세."""
    fx, fy = math.cos(c.tyaw) * c.sign, math.sin(c.tyaw) * c.sign
    return [c.tx - ALONG0 * fx + CROSS0 * fy,
            c.ty - ALONG0 * fy - CROSS0 * fx,
            c.tyaw - HEAD0]


def err(c, pose):
    """(along, cross, head) — isaac_drive 와 같은 정의."""
    x, y, yaw = pose
    fx, fy = math.cos(yaw) * c.sign, math.sin(yaw) * c.sign
    dx, dy = c.tx - x, c.ty - y
    return (dx * fx + dy * fy, fx * dy - fy * dx, D.wrap(c.tyaw - yaw))


def maneuver(d, dtheta, cells, pose0=None):
    """4구간 개루프 기동 -> (Δcross, 벗어난 칸 집합, 최대 |along|, 끝 자세).

    부호는 지배식에서 나온다. `cross > 0` 을 줄이려면 ∫along dθ > 0 이어야
    하므로 **along 이 클 때 +dθ**, 작을 때 -dθ 다.

    ★ `pose0` 를 주면 거기서 시작한다 — **반복 모드**가 쓴다. 표의 1회분
      Δcross 를 그냥 나눠서 횟수를 세면 틀린다. `cross` 가 줄면 기하가
      달라지므로 회마다 다시 재야 한다.
    """
    c = controller()
    pose = list(pose0) if pose0 is not None else start_pose(c)
    _, c0, _ = err(c, pose)
    out, far = set(), 0.0

    def step(v, w):
        nonlocal far
        pose[2] += w * DT
        pose[0] += v * math.cos(pose[2]) * DT
        pose[1] += v * math.sin(pose[2]) * DT
        out.update(GEOM.footprint_cells(pose[0], pose[1], pose[2]) - cells)
        far = max(far, abs(err(c, pose)[0]))

    def rotate(dth):
        for _ in range(int(abs(dth) / (W_MAX * DT))):
            step(0.0, math.copysign(W_MAX, dth))

    def straight(dist):
        for _ in range(int(abs(dist) / (V_MAX * DT))):
            step(math.copysign(V_MAX, dist) * c.sign, 0.0)

    # ★ ㄱ 은 **cross 로는 공짜지만 발자국으로는 아니다** (2026-09-17).
    #   제자리 -θ 도 꼬리를 1.11*sin(θ) 만큼 옆으로 밀어낸다. NO_G=1 로 뺀다.
    if not NO_G:
        rotate(-dtheta)  # ㄱ  along~0 에서 튼다
    straight(-d)         # ㄴ  곧게 물러난다
    rotate(+dtheta)      # ㄷ  먼 쪽에서 튼다 (여기서 번다)
    straight(+d)         # ㄹ  곧게 돌아온다
    _, c1, _ = err(c, pose)
    return c1 - c0, out, far, pose


def main():
    cells = GEOM.swept_cells(S0, S1)
    c = controller()
    base = GEOM.footprint_cells(*start_pose(c)) - cells      # ★ 기준선
    global SPILL_COLS
    SPILL_COLS = {cl for (_, cl) in base}                    # 이미 넘친 열

    print(f"  예약 칸 cells   {sorted(cells)}")
    print(f"  목표 자세 발자국 {sorted(GEOM.footprint_cells(*GEOM.state_pose(S1)))}"
          f"   (occupied {sorted(D.occupied(S1))} — 일치해야 한다)")
    print(f"  ★ 멈춘 자세가 **이미** 벗어나 있다: {sorted(base) or '없음'}")
    print(f"    cross {CROSS0 * 1000:.0f} mm > 측면 여유 "
          f"{(GEOM.pitch - GEOM.width) * 1000:.0f} mm 이므로 당연하다.")
    print(f"    -> 판정은 「벗어나나」가 아니라 **「새 칸이 느나」**다.")
    print(f"       그리고 새 칸도 **이미 넘친 열 {sorted(SPILL_COLS)} 인가 "
          f"반대편인가**로 가른다.\n")
    hdr = ("  {:>5} {:>6} {:>10} {:>10} {:>5} {:>6}  {}"
           .format("d[m]", "θ[도]", "Δcross", "최대along", "같은열", "반대편",
                   "늘어난 칸 (같은열 / 반대편)"))
    print(hdr)

    ok = []
    for d in [float(v) for v in os.environ.get("D", "0.1,0.2,0.3,0.4,0.5").split(",")]:
        for th in [float(v) for v in os.environ.get("TH", "10,20,30,40").split(",")]:
            dc, out, far, _ = maneuver(d, math.radians(th), cells)
            new = out - base                              # ★ 기준선을 뺀다
            # ★★ 새 칸을 **두 종류로 가른다** (2026-09-17).
            #   이미 흘러넘친 열(49)로 한 칸 더 가는 것과, **반대편**(51)을
            #   새로 침범하는 것은 위험이 다르다. 앞은 있던 문제의 연장이고
            #   뒤는 A 가 **없던 자리에 새로 들어가는** 것이다.
            far_side = {cl for (_, cl) in new} - SPILL_COLS
            same = sorted(x for x in new if x[1] in SPILL_COLS)
            other = sorted(x for x in new if x[1] not in SPILL_COLS)
            mark = "  ★" if not other and dc < 0 else ""
            print(f"  {d:5.2f} {th:6.0f} {dc * 1000:+9.1f}mm {far * 1000:9.0f}mm "
                  f"{len(same):4d} {len(other):5d}  "
                  f"{sorted(same) if same else '-'} / "
                  f"{sorted(other) if other else '없음'}{mark}")
            if not other and dc < 0:
                ok.append((dc, d, th))
    print()
    if ok:
        dc, d, th = min(ok)
        n = math.ceil(CROSS0 / abs(dc))
        print(f"  ★★ **반대편을 안 건드리는 조합이 {len(ok)}개** 있다 — A 가 산다.")
        print(f"     최선  d={d} m · θ={th:.0f}도  ->  Δcross {dc * 1000:+.1f} mm/회")
        print(f"     cross {CROSS0 * 1000:.0f} mm 를 지우려면 **{n}회** "
              f"(누적 왕복 {2 * d * n:.1f} m · 회전 {4 * th * n:.0f}도)")
        print()
        print(f"  ☹ 다만 공짜가 아니다 — 이미 흘러넘친 열로 **한 칸 더** 간다.")
        print(f"     멈춘 자세   {sorted(base)}")
        print(f"     그 열이 뒷차 예약이면 A 는 **거기서 막힌다.** 실측 로그에서는")
        print(f"     후행이 선행 완료를 기다리고 있었지만(agent3 대기), 그건")
        print(f"     **이 판의 사정**이지 일반 보장이 아니다 — 다음에 확인할 것.")
    else:
        print("  ☒ **반대편을 안 건드리는 조합이 없다.** 이 모양의 A 는 성립하지 않는다.")


def iterate(d, dtheta, cells, base, cap=20):
    """cross 가 허용 안에 들 때까지 **실제로 반복**한다 -> 회별 기록.

    ★ 표의 1회분 Δcross 를 나눠서 횟수를 세면 **틀린다.** cross 가 줄면
      기하가 달라져 회마다 Δcross 도, 벗어나는 칸도 바뀐다. 특히 cross 가
      측면 여유(200 mm) 아래로 내려가면 **벗어남이 저절로 사라진다.**
    """
    c = controller()
    tol = c.tol.pos
    pose = start_pose(c)
    rows, seen = [], set()
    for i in range(1, cap + 1):
        _, cr0, _ = err(c, pose)
        # ★★ θ 를 **남은 cross 에 맞춘다** (2026-09-17).
        #   고정 θ 로 돌리면 마지막 회에서 **반대편을 넘는다** — 갚을 것이
        #   50 mm 인데 150 mm 짜리 기동을 하기 때문이다. 실측:
        #       cross 201 -> 150 -> 98 -> 47   3회째에만 (44,51) 이 났다
        #   지배식이 Δcross ~ -d*θ 이므로 θ = |cross| / d 로 잡으면 딱 갚는다.
        #   상한은 인자로 받은 θ (안전 쪽), 하한은 수치 잡음 방지용이다.
        th = min(dtheta, abs(cr0) / max(d, 1e-6)) if ADAPT else dtheta
        th = max(th, math.radians(1.0))
        dc, out, _far, pose = maneuver(d, th, cells, pose)
        _, cr1, _ = err(c, pose)
        seen |= out
        rows.append((i, cr0, cr1, sorted(out - base)))
        if abs(cr1) <= tol:
            return rows, seen, True
        if abs(cr1) >= abs(cr0):          # 안 줄면 그만 — 발산 방지
            return rows, seen, False
    return rows, seen, False


def main_iter():
    cells = GEOM.swept_cells(S0, S1)
    c = controller()
    base = GEOM.footprint_cells(*start_pose(c)) - cells
    global SPILL_COLS
    SPILL_COLS = {cl for (_, cl) in base}
    tol = c.tol.pos
    print(f"  반복 모드 — cross 가 tol.pos {tol*1000:.0f} mm 안에 들 때까지")
    print(f"  기준선(멈춘 자세가 이미 벗어난 칸) {sorted(base)}\n")
    print("  {:>5} {:>6} {:>6}  {}".format("d[m]", "θ[도]", "회", "판정"))
    for d in [float(v) for v in os.environ.get("D", "0.2,0.3,0.4,0.5").split(",")]:
        for th in [float(v) for v in os.environ.get("TH", "10,20").split(",")]:
            rows, seen, done = iterate(d, math.radians(th), cells, base)
            new = seen - base
            other = sorted(x for x in new if x[1] not in SPILL_COLS)
            same = sorted(x for x in new if x[1] in SPILL_COLS)
            v = ("★ 든다" if done else "☒ 못 든다")
            print(f"  {d:5.2f} {th:6.0f} {len(rows):6d}  {v}"
                  f"   같은열 {same or '-'} / 반대편 {other or '없음'}")
            if os.environ.get("VERBOSE"):
                for i, a, b, o in rows:
                    print(f"        {i:2d}회  cross {a*1000:7.1f} -> {b*1000:7.1f} mm"
                          f"   벗어남 {o or '-'}")


if __name__ == "__main__":
    (main_iter if os.environ.get("ITER") else main)()
