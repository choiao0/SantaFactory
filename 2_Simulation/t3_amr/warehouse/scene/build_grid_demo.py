# -*- coding: utf-8 -*-
"""**칸과 차체를 같이 그려서** 왜 부딪히는지 보여주는 씬 (S15P21A106-267).

    cd <t3_amr> && source paths.sh
    python warehouse/scene/build_grid_demo.py                 일곱 장면 전부
    python warehouse/scene/build_grid_demo.py --case turn     한 장면만
    python warehouse/scene/build_grid_demo.py --pitch 1.2     격자를 바꿔 비교

★ **Isaac 런처가 따로 없다.** `paths.sh` 를 source 한 셸의 `python` 이 곧
  Isaac 의 venv 다 (`./isaac_python.sh` 같은 파일은 없다 — 찾지 말 것).
  씬만 만들 때(`--shoot` 없이)는 venv 의 pxr 만으로 되고 GPU 도 안 문다.

산출: `$STAGE/grid_demo_<case>.usd`
      `--shoot` 를 주면 `$OUT/grid_demo/<case>.png`
      `--video` 를 주면 `$OUT/grid_demo/<case>.mp4` (움직인다)

    python warehouse/scene/build_grid_demo.py --video          일곱 장면 mp4
    python warehouse/scene/build_grid_demo.py --case rack --video

☹ `$STAGE` 는 `paths.sh` 에서 **주행 씬이 사는 폴더**다. 데모 USD 를 거기
  섞지 않으려면 앞에 붙여 한 판만 딴 데로 돌린다: `STAGE=/tmp/grid python …`

왜 이 파일이 있나
-----------------
「칸은 안 겹쳤는데 몸이 닿는다」를 13대 주행에서 **사냥하면** 언제 날지 모르고,
나도 30분을 태운 뒤에야 안다. 그런데 이건 **기하다** — 주행이 필요 없다.
칸과 차체를 같이 그려 놓으면 그 자리에서 보인다.

    차체 1.500 m 가 칸 1.000 m 안에 들어갈 수 없다.

숫자 (`PITCH=1.0`, 차체 축->앞 0.390 · 축->뒤 1.110 · 폭 0.800)
---------------------------------------------------------------
    정지    길이가 칸을 **앞뒤로 500 mm** 넘는다 · 옆 칸과는 200 mm 뜬다
    회전    앞 모서리 r=0.559  -> 칸을 **59 mm** 넘는다
            뒤 모서리 r=1.180  -> 칸을 **680 mm** 넘는다
    옆 칸에 남이 있으면 회전이 그 차체를 **580 mm** 파고든다

★ 뒤 모서리가 크게 도는 것은 **구동축이 앞**이기 때문이다(heading_offset=0).
  차체가 헤딩의 뒤로 뻗으므로 제자리 회전이 꼬리로 큰 원을 그린다. 회전 마스크
  2,976건과 `PIBT_TURN_PAIR` 20조합이 막고 있는 것이 이 원이다.

장면
----
    footprint   한 대. 발자국이 칸을 넘는다
    side        옆으로 나란히 두 대. 간격 200 mm — **안 닿는다** (이것도 결과다)
    follow      앞뒤로 한 칸 간격. 칸은 안 겹치는데 **차체가 500 mm 겹친다**
    rack        옆 칸이 랙. 정중앙에서 돌려도 앞 모서리가 **59 mm** 들어간다
    turn        옆 칸에 남이 있는데 회전. 뒤 모서리가 **580 mm** 파고든다
    accel       계획(등속)과 실제(칸마다 정지)를 나란히. 3칸에 3.33 s 대 8.35 s
    decel       v_max 에서 제동. 표시한 자리를 **675 mm** 지나쳐 선다

    ★ accel·decel 은 기하가 아니라 **운동**이라 `--video` 라야 뜻이 있다.
      정지컷은 「두 대가 서 있다」로만 보인다.

☹ 「회전 첫 스텝의 바퀴 미끄러짐」은 여기 없다. 그것은 기하가 아니라 **제어**다 —
  계단 입력과 바닥 마찰의 문제라 그려서 보여줄 수 없다. `tools/turn_error.py` ·
  `tools/cross_track.py` 가 녹화 NPZ 에서 재는 쪽이 맞다.
  (가속·감속은 달랐다 — 저건 상수에서 식이 나와 그릴 수 있다. 그래서 넣었다.)

색
--
    칸 선    진회색     발자국   반투명 청회색
    스윕 원  주황       침투 구간 빨강
"""
import argparse
import glob
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
W_DIR = os.environ.get("W") or os.path.dirname(os.path.dirname(_HERE))
STAGE = os.environ.get("STAGE") or os.path.join(W_DIR, "stage")
OUT = os.environ.get("OUT") or os.path.join(W_DIR, "out")

# 차체 — `build_amr_shelf.py` · `isaac_drive.RobotGeom` 과 같은 값
FRONT, REAR, WIDTH = 0.390, 1.110, 0.800

ap = argparse.ArgumentParser()
ap.add_argument("--case", default="all",
                choices=["all", "footprint", "side", "follow", "rack", "turn",
                         "accel", "decel"])
ap.add_argument("--pitch", type=float, default=1.0)
ap.add_argument("--cells", type=int, default=7, help="격자 칸 수 (한 변)")
ap.add_argument("--shoot", action="store_true", help="만들고 PNG 까지 찍는다")
ap.add_argument("--video", action="store_true",
                help="움직이는 mp4 까지 만든다 (회전·접근). --shoot 을 겸한다")
ap.add_argument("--frames", type=int, default=120, help="--video 프레임 수 (30fps)")
ap.add_argument("--exposure", type=float, default=1.0, help="조명 밝기 배수")
ap.add_argument("--robot", default=os.environ.get("ROBOT") or
                os.path.join(W_DIR, "robots", "iwhub", "iw_hub.usd"),
                help="AMR 에셋 (기본 $ROBOT)")
ap.add_argument("--shelf", default=os.path.join(W_DIR, "robots", "shelf", "amr_shelf.usd"),
                help="적재 선반 에셋")
ap.add_argument("--boxes", action="store_true",
                help="실제 에셋 대신 **발자국 상자**로 그린다 (에셋이 없을 때)")
ap.add_argument("--rt-subframes", type=int, default=12, dest="rt_subframes",
                help="레이트레이서 수렴 프레임. 노이즈가 남으면 올린다")
ap.add_argument("--res", default="1600x1000")
A = ap.parse_args()
P = A.pitch
# ★ `--video` 는 `--shoot` 을 겸한다. **여기서** 접어야 한다 — 아래 SimulationApp
#   블록이 `A.shoot` 을 보고 Isaac 을 띄울지 정하기 때문이다. 뒤에서 켜면 앱이
#   안 뜬 채로 `import omni` 에 닿아 죽는다 (2026-09-23 실측).
if A.video:
    A.shoot = True

# ── 기하 계산 — 그리기 전에 숫자부터 낸다 ────────────────────────────
R_FRONT = math.hypot(FRONT, WIDTH / 2)
R_REAR = math.hypot(REAR, WIDTH / 2)
OVER_LEN = (FRONT + REAR) - P
SIDE_GAP = P - WIDTH
PEN_NEIGHBOR = R_REAR - (P - WIDTH / 2)

print("═" * 66)
print("칸 %.2f m · 차체 %.3f x %.3f m (축->앞 %.3f)" % (P, FRONT + REAR, WIDTH, FRONT))
print("  정지  길이가 칸을 앞뒤로 %+.0f mm · 옆 칸과 %.0f mm" % (OVER_LEN * 1000, SIDE_GAP * 1000))
print("  회전  앞 모서리 r=%.4f -> 칸을 %+.0f mm" % (R_FRONT, (R_FRONT - P / 2) * 1000))
print("        뒤 모서리 r=%.4f -> 칸을 %+.0f mm" % (R_REAR, (R_REAR - P / 2) * 1000))
print("  옆 칸 로봇을 %+.0f mm %s" % (abs(PEN_NEIGHBOR) * 1000,
                                     "파고든다" if PEN_NEIGHBOR > 0 else "여유"))
print("═" * 66)

# ★★ `--shoot` 이면 **Isaac 을 먼저 띄운다** (2026-09-23).
#
#   `from pxr import …` 를 SimulationApp 보다 먼저 하면 venv 의 standalone USD 가
#   먼저 로드되고, 뒤이어 Isaac 이 자기 USD(`omni.usd.libs`)를 또 올린다. 한
#   프로세스에 USD 가 두 벌이면 이렇게 죽는다 —
#
#       TypeError: No to_python converter found for C++ type: …SdfPath…
#       free(): corrupted unsorted chunks
#
#   `shoot_amr.py` 는 SimulationApp 뒤에 pxr 을 들여서 안 걸린다. 같은 순서로 둔다.
#   USD 만 만들 때는 Isaac 이 필요 없으므로 안 띄운다 — 그쪽이 훨씬 빠르다.
simulation_app = None
if A.shoot:
    from isaacsim import SimulationApp                 # noqa: E402
    _cfg = {"headless": True}
    _g = (os.environ.get("GPU", "") or "").strip()
    if _g.isdigit():
        _cfg["active_gpu"], _cfg["multi_gpu"] = int(_g), False
    print("[grid] SimulationApp 기동 (--shoot)%s"
          % (" · GPU " + _g if _g.isdigit() else ""))
    simulation_app = SimulationApp(_cfg)

from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdShade   # noqa: E402

MAT = {                                    # (색, rough, metal, 불투명도)
    "line":  ((0.16, 0.17, 0.20), 0.8, 0.0, 1.0),
    "floor": ((0.82, 0.83, 0.85), 0.9, 0.0, 1.0),
    "body":  ((0.29, 0.42, 0.54), 0.6, 0.0, 0.55),
    "sweep": ((0.85, 0.52, 0.16), 0.7, 0.0, 0.9),
    "hit":   ((0.78, 0.18, 0.16), 0.6, 0.0, 0.95),
}


def material(stage, path, key):
    col, rough, metal, op = MAT[key]
    m = UsdShade.Material.Define(stage, path)
    s = UsdShade.Shader.Define(stage, path + "/S")
    s.CreateIdAttr("UsdPreviewSurface")
    s.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*col))
    s.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(rough)
    s.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(metal)
    if op < 1.0:
        s.CreateInput("opacity", Sdf.ValueTypeNames.Float).Set(op)
    m.CreateSurfaceOutput().ConnectToSource(s.ConnectableAPI(), "surface")
    return m


def box(stage, path, x0, x1, y0, y1, z0, z1, mat=None, yaw=0.0, cx=0.0, cy=0.0):
    """축정렬 박스. yaw 를 주면 (cx, cy) 를 중심으로 돌린다."""
    c = UsdGeom.Cube.Define(stage, path)
    c.GetSizeAttr().Set(2.0)
    xf = UsdGeom.Xformable(c)
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    if yaw:
        dx, dy = mx - cx, my - cy
        ca, sa = math.cos(yaw), math.sin(yaw)
        mx, my = cx + dx * ca - dy * sa, cy + dx * sa + dy * ca
    xf.AddTranslateOp().Set(Gf.Vec3d(mx, my, (z0 + z1) / 2))
    if yaw:
        xf.AddRotateZOp().Set(math.degrees(yaw))
    xf.AddScaleOp().Set(Gf.Vec3f((x1 - x0) / 2, (y1 - y0) / 2, (z1 - z0) / 2))
    if mat is not None:
        UsdShade.MaterialBindingAPI(c.GetPrim()).Bind(mat)
    return c


def lights(stage):
    """★ 조명을 **씬에 넣는다** (2026-09-23).

    안 넣으면 렌더가 거의 새까맣게 나온다 — 첫 판에서 그랬다. 창고 씬
    (`build_amr_scene_v2.py`)은 자기 조명이 있지만 이 데모는 처음부터 짓는
    씬이라 아무것도 없다.

    돔(하늘빛) + 해(방향광) 둘. `--exposure` 로 밝기를 조절한다.
    """
    d = UsdLux.DomeLight.Define(stage, "/World/Lights/Dome")
    d.CreateIntensityAttr(900.0 * A.exposure)
    d.CreateColorAttr(Gf.Vec3f(0.86, 0.90, 0.96))
    s = UsdLux.DistantLight.Define(stage, "/World/Lights/Sun")
    s.CreateIntensityAttr(2600.0 * A.exposure)
    s.CreateAngleAttr(1.2)
    s.CreateColorAttr(Gf.Vec3f(1.0, 0.97, 0.92))
    UsdGeom.Xformable(s.GetPrim()).AddRotateXYZOp().Set(Gf.Vec3f(-48.0, 0.0, 38.0))


def grid(stage, mats, n):
    """1.0 m 격자 — **진한 선**. 칸 경계가 보여야 이 설명이 성립한다."""
    half, t, z = n * P / 2, 0.022, 0.004
    for i in range(n + 1):
        v = -half + i * P
        box(stage, f"/World/Grid/x_{i}", v - t/2, v + t/2, -half, half, 0, z, mats["line"])
        box(stage, f"/World/Grid/y_{i}", -half, half, v - t/2, v + t/2, 0, z, mats["line"])
    box(stage, "/World/Floor", -half, half, -half, half, -0.01, 0.0, mats["floor"])


WHEEL_R = 0.081          # `build_amr_scene_v2.py` 와 같은 값 — 로봇 prim 의 z

_asset_warned = False


def have_assets():
    """실제 에셋이 있나. git 제외라 없는 기계가 있다 — 그러면 상자로 떨어진다."""
    global _asset_warned
    if A.boxes:
        return False
    ok = os.path.isfile(A.robot)
    if not ok and not _asset_warned:
        _asset_warned = True
        print("[grid] ☹ AMR 에셋이 없어 **발자국 상자**로 그린다: %s" % A.robot)
        print("[grid]   받으려면:  python tools/fetch_iwhub.py")
    return ok


def footprint(stage, path, cx, cy, yaw, mats, key="body", h=0.62):
    """그 자리에 **AMR 을 놓는다.** 에셋이 없으면 발자국 상자로 떨어진다.

    ★ 격자를 넘는 것을 보여주는 것이 목적이라 **실제 에셋**이라야 한다. 상자는
      「계획이 쓰는 발자국」이지 눈에 보이는 로봇이 아니다.

    ★ 움직일 수 있게 만든다 — 회전·이동 op 을 **값이 0 이어도** 달아 둔다.
      `--video` 가 프레임마다 그 값만 바꾼다 (`animate` 참조). op 을 나중에
      추가하면 매번 만들게 되고, 그러다 카메라가 한 자리에 멈춘 사고를 이미
      한 번 겪었다 (`headless_pibt._fpv_track`, 5257b1f).

    ★ 로봇 에셋은 **구동축 원점 · +X 전진**으로 저작돼 있다. 그래서 축 자리에
      그대로 놓으면 되고, 선반도 추가 변환 없이 얹힌다
      (`build_amr_scene_v2.py:239` 의 주석이 그 규약을 적어 뒀다).
    """
    if have_assets():
        prim = stage.DefinePrim(path, "Xform")
        prim.GetReferences().AddReference(A.robot)
        xf = UsdGeom.Xformable(prim)
        xf.AddTranslateOp().Set(Gf.Vec3d(cx, cy, WHEEL_R))
        xf.AddRotateZOp().Set(math.degrees(yaw))
        xf.AddScaleOp().Set(Gf.Vec3f(1.0, 1.0, 1.0))
        if os.path.isfile(A.shelf):
            # 물리를 안 돌리므로 링크에 매달 필요가 없다 — 루트 밑이면 된다.
            stage.DefinePrim(path + "/shelf", "Xform") \
                 .GetReferences().AddReference(A.shelf)
        # 바닥에 **발자국 자국**을 같이 깐다 — 칸을 얼마나 넘는지 눈금이 된다.
        #   ★ 로봇 prim 의 **자식**으로 넣는다. 형제로 두면 로봇만 돌고 자국은
        #     제자리에 남아, 회전 장면에서 무엇이 발자국인지 알 수 없게 된다.
        #     자식이면 부모의 translate·rotateZ 를 그대로 물려받는다.
        box(stage, path + "/pad", -REAR, FRONT, -WIDTH/2, WIDTH/2,
            0.005 - WHEEL_R, 0.010 - WHEEL_R, mats[key])
        return prim
    c = UsdGeom.Cube.Define(stage, path)
    c.GetSizeAttr().Set(2.0)
    xf = UsdGeom.Xformable(c)
    t = xf.AddTranslateOp()
    r = xf.AddRotateZOp()
    s = xf.AddScaleOp()
    t.Set(Gf.Vec3d(cx + (FRONT - REAR) / 2, cy, (0.02 + h) / 2))
    r.Set(math.degrees(yaw))
    s.Set(Gf.Vec3f((FRONT + REAR) / 2, WIDTH / 2, (h - 0.02) / 2))
    UsdShade.MaterialBindingAPI(c.GetPrim()).Bind(mats[key])
    return c


def sweep_ring(stage, path, cx, cy, r, mats, key="sweep", seg=96, t=0.03):
    """제자리 회전이 쓸고 가는 원 — 짧은 막대를 이어 그린다."""
    for i in range(seg):
        a0, a1 = 2*math.pi*i/seg, 2*math.pi*(i+1)/seg
        x0, y0 = cx + r*math.cos(a0), cy + r*math.sin(a0)
        x1, y1 = cx + r*math.cos(a1), cy + r*math.sin(a1)
        mid = ((x0+x1)/2, (y0+y1)/2)
        ln = math.hypot(x1-x0, y1-y0)
        ang = math.atan2(y1-y0, x1-x0)
        box(stage, f"{path}/s{i}", mid[0]-ln/2, mid[0]+ln/2, mid[1]-t/2, mid[1]+t/2,
            0.005, 0.05, mats[key], yaw=ang, cx=mid[0], cy=mid[1])


def build(case):
    out = os.path.join(STAGE, "grid_demo_%s.usd" % case)
    os.makedirs(STAGE, exist_ok=True)
    stage = Usd.Stage.CreateNew(out)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(stage.GetPrimAtPath("/World"))
    mats = {k: material(stage, "/World/Looks/%s" % k, k) for k in MAT}
    lights(stage)
    grid(stage, mats, A.cells)

    note = []
    if case == "footprint":
        footprint(stage, "/World/A", 0, 0, 0.0, mats)
        note.append("발자국 %.3f m 가 칸 %.2f m 를 앞뒤로 %.0f mm 넘는다"
                    % (FRONT + REAR, P, OVER_LEN * 1000))
    elif case == "side":
        footprint(stage, "/World/A", 0, 0, 0.0, mats)
        footprint(stage, "/World/B", 0, P, 0.0, mats)
        note.append("옆 칸 두 대 — 간격 %.0f mm. **안 닿는다**" % (SIDE_GAP * 1000))
    elif case == "follow":
        # ★ 가장 단순한 「칸은 안 겹쳤는데 몸이 닿는다」 — 회전도 오차도 필요 없다.
        #   앞차 축 x=0, 뒤차 축 x=-P. 두 칸은 안 겹치는데 차체가 겹친다.
        footprint(stage, "/World/A", 0, 0, 0.0, mats)
        footprint(stage, "/World/B", -P, 0, 0.0, mats, key="hit", h=0.50)
        ov = (FRONT + REAR) - P
        note.append("앞뒤로 한 칸 간격 — **칸은 안 겹친다**")
        note.append("그런데 차체가 %.0f mm 겹친다 (길이 %.3f > 칸 %.2f)"
                    % (ov * 1000, FRONT + REAR, P))
    elif case == "rack":
        # ★ t3-38 이 실측으로 적은 58.7 mm 가 이것이다 — 칸 정중앙에서 돌려도
        #   앞 모서리가 옆 칸(랙)으로 들어간다.
        footprint(stage, "/World/A", 0, 0, 0.0, mats)
        box(stage, "/World/Rack", -P/2, P/2, P/2, P*1.5, 0.0, 1.35, mats["hit"])
        sweep_ring(stage, "/World/SweepFront", 0, 0, R_FRONT, mats, seg=72, t=0.025)
        pen = R_FRONT - P/2
        note.append("옆 칸이 랙(빨강). 칸 **정중앙**에서 제자리 회전")
        note.append("앞 모서리 r=%.4f -> 랙 칸으로 %.1f mm 들어간다" % (R_FRONT, pen * 1000))
        note.append("t3-38 실측 58.7 mm 와 같다 — 기하가 그렇게 돼 있다")
    elif case == "accel":
        # 위: 계획(등속) · 아래: 실제(칸마다 정지). 같은 자리에서 같이 출발한다.
        footprint(stage, "/World/Plan", X0, P, 0.0, mats, key="sweep")
        footprint(stage, "/World/A", X0, 0, 0.0, mats)
        for k in range(N_CELL + 1):
            box(stage, "/World/Mark/m%d" % k, X0 + k*P - 0.03, X0 + k*P + 0.03,
                -P*1.6, P*1.6, 0.006, 0.014, mats["hit"])
        pk = math.sqrt(A_LIN * P)
        note.append("위 주황 = 계획(등속 %.2f m/s) · 아래 = 실제(칸마다 정지)" % V_MAX)
        note.append("한 칸 계획 %.3f s vs 실제 %.3f s  ->  **%.2f배**"
                    % (P / V_MAX, T_CELL, T_CELL / (P / V_MAX)))
        note.append("실제 최고속도 %.3f m/s = v_max 의 %.0f %% (가속이 칸 안에서 안 끝난다)"
                    % (pk, 100 * pk / V_MAX))
    elif case == "decel":
        footprint(stage, "/World/A", 0, 0, 0.0, mats)
        d = D_STOP
        box(stage, "/World/Mark/target", -0.03, 0.03, -P*1.2, P*1.2, 0.006, 0.02, mats["hit"])
        box(stage, "/World/Mark/stop", d - 0.03, d + 0.03, -P*1.2, P*1.2, 0.006, 0.02, mats["sweep"])
        note.append("빨강 = 멈추라고 한 자리 · 주황 = 실제로 서는 자리")
        note.append("v_max %.2f m/s 에서 정지거리 **%.3f m** = 칸 %.2f 의 %.0f %%"
                    % (V_MAX, d, P, 100 * d / P))
    elif case == "turn":
        footprint(stage, "/World/A", 0, 0, 0.0, mats)
        footprint(stage, "/World/B", 0, P, 0.0, mats, key="hit")
        sweep_ring(stage, "/World/Sweep", 0, 0, R_REAR, mats)
        sweep_ring(stage, "/World/SweepFront", 0, 0, R_FRONT, mats, key="sweep", seg=72, t=0.02)
        note.append("가운데가 제자리 회전 -> 뒤 모서리 반경 %.3f m" % R_REAR)
        note.append("옆 칸 로봇(빨강)을 %.0f mm 파고든다" % (PEN_NEIGHBOR * 1000))

    stage.GetRootLayer().Save()
    print("[grid] %-10s -> %s" % (case, out))
    for n in note:
        print("[grid]   %s" % n)
    return out


# ── 장면마다 무엇이 움직이나 (`--video`) ─────────────────────────────
#   기하만으로 부딪힌다는 것이 요점이라 **물리를 안 돌린다.** 발자국의 xform 을
#   프레임마다 직접 옮긴다 — 그래서 결정적이고 1분이면 끝난다.
#
#       prim        움직일 대상        kind  rot=제자리 회전 · app=뒤에서 접근
#       (없으면)    카메라가 궤도를 돈다 (정적 장면)
# ── 가감속 — 계획과 실제를 **나란히 달리게** 한다 ────────────────────
#   표로는 「2.32배」가 와닿지 않는다. 두 대를 같이 출발시키면 간격이 벌어지는
#   것이 그대로 보인다. 물리를 안 돌린다 — 두 프로파일 다 **상수에서 나온 식**이다.
#
#       계획  등속 v_max (MOVE_TICKS 가 가정하는 것)
#       실제  칸마다 정지·재출발, 가속도 a_lin 의 삼각 프로파일
V_MAX, A_LIN = 0.90, 0.60          # isaac_drive.RobotGeom 과 같은 값
N_CELL = 3                         # 몇 칸을 달리나
X0 = -1.0                          # 출발 x — 궤적을 격자 가운데에 놓는다
T_CELL = 2.0 * math.sqrt(P / A_LIN)          # 칸마다 정지할 때 한 칸에 드는 시간
D_STOP = V_MAX ** 2 / (2 * A_LIN)            # v_max 에서의 정지거리
DUR = {"accel": N_CELL * T_CELL + 0.6, "decel": 3.2}


def x_plan(t):
    """계획 — 등속. `MOVE_TICKS x tick_s` 가 가정하는 그 움직임이다."""
    return X0 + min(V_MAX * t, N_CELL * P)


def x_real(t):
    """실제 — 칸마다 서고 다시 붙는다. 한 칸 안에서 가속·감속만 하므로
    최고속도가 `sqrt(a*P)` 에서 잘린다 (v_max 에 못 닿는다)."""
    k, rem = divmod(t, T_CELL)
    if k >= N_CELL:
        return X0 + N_CELL * P
    half = T_CELL / 2
    d = (0.5 * A_LIN * rem ** 2 if rem <= half
         else P - 0.5 * A_LIN * (T_CELL - rem) ** 2)
    return X0 + k * P + d


def x_brake(t):
    """감속 — v_max 로 오다 목표(원점)에서 제동을 **시작**한다.
    정지거리 v^2/(2a) 만큼 지나쳐 선다."""
    if t <= 1.2:
        return -V_MAX * (1.2 - t)
    dt_ = min(t - 1.2, V_MAX / A_LIN)
    return V_MAX * dt_ - 0.5 * A_LIN * dt_ ** 2


# 가감속 장면은 **옆에서** 본다 — 궤도를 돌면 얼마나 갔는지 눈이 못 따라간다.
#   (바라보는 점, 카메라 자리)
CAM_FIX = {
    # 거리는 **차체가 꽉 차게** 잡았다 — 35 mm · 가로 화각 54.4도 에서
    #   가속 차체 x -2.11..2.39 (4.5 m) < 화면 5.9 m
    #   감속 차체 x -2.19..1.07 (3.3 m) < 화면 4.7 m
    "accel": ((X0 + N_CELL * P / 2, P / 2, 0.35),
              (X0 + N_CELL * P / 2, -5.2, 2.8)),
    "decel": ((D_STOP / 2 - 0.2, 0.0, 0.35),
              (D_STOP / 2 - 0.2, -4.2, 2.2)),
}


MOTION = {
    "rack":   ("/World/A", "rot"),
    "turn":   ("/World/A", "rot"),
    "follow": ("/World/B", "app"),
    "accel":  (None, "race"),
    "decel":  (None, "brake"),
}


def animate(stage, case, u):
    """0..1 의 u 를 받아 그 순간의 자세로 놓는다. 카메라 궤도면 각도를 돌려준다."""
    mo = MOTION.get(case)
    if mo is None:
        return u * 2 * math.pi * 0.5          # 정적 장면 — 반 바퀴 궤도
    path, kind = mo
    if kind in ("race", "brake"):
        t = u * DUR[case]
        def put(p, x):
            o = UsdGeom.Xformable(stage.GetPrimAtPath(p)).GetOrderedXformOps()
            z = o[0].Get()[2]
            o[0].Set(Gf.Vec3d(x, o[0].Get()[1], z))
        if kind == "race":
            put("/World/Plan", x_plan(t))
            put("/World/A", x_real(t))
        else:
            put("/World/A", x_brake(t))
        return 0.0
    ops = UsdGeom.Xformable(stage.GetPrimAtPath(path)).GetOrderedXformOps()
    if kind == "rot":
        # 0 -> 90도. 앞 모서리가 옆 칸으로 들어가는 그 구간이 한가운데 온다.
        ops[1].Set(u * 90.0)
    else:
        # 뒤에서 한 칸 간격까지 다가온다. 마지막 30 % 는 멈춰 겹침을 보여준다.
        v = min(1.0, u / 0.7)
        x0, x1 = -2.8 * P, -P
        cx = x0 + (x1 - x0) * v
        ops[0].Set(Gf.Vec3d(cx + (FRONT - REAR) / 2, 0.0, ops[0].Get()[2]))
    return 0.0


cases = (["footprint", "side", "follow", "rack", "turn", "accel", "decel"]
         if A.case == "all" else [A.case])
made = [build(c) for c in cases]

if not A.shoot:
    print("\n열어 보려면:  usdview <파일>")
    print("PNG 까지 원하면 --shoot")
    sys.exit(0)

# ── 촬영 — `shoot_amr.py` 에서 검증된 경로를 그대로 ──────────────────
#   앱은 위에서 이미 떠 있다 (pxr 보다 먼저 띄워야 해서).
app = simulation_app

import omni.kit.app                                    # noqa: E402
import omni.usd                                        # noqa: E402
from PIL import Image                                  # noqa: E402

omni.kit.app.get_app().get_extension_manager() \
    .set_extension_enabled_immediate("omni.replicator.core", True)
import omni.replicator.core as rep                     # noqa: E402

w, h = (int(v) for v in A.res.split("x"))
shot_dir = os.path.join(OUT, "grid_demo")
os.makedirs(shot_dir, exist_ok=True)

def look_at(xop, eye, tgt):
    f = (tgt - eye).GetNormalized()
    r = Gf.Cross(f, Gf.Vec3d(0, 0, 1)).GetNormalized()
    u = Gf.Cross(r, f)
    xop.Set(Gf.Matrix4d(r[0], r[1], r[2], 0, u[0], u[1], u[2], 0,
                        -f[0], -f[1], -f[2], 0, eye[0], eye[1], eye[2], 1))


def grab(annot, tries=24):
    """★ 리플리케이터 **그래프를 밟아야** 버퍼가 찬다 (`shoot_amr.py` 와 같다)."""
    for _ in range(tries):
        try:
            rep.orchestrator.step(delta_time=0.0, rt_subframes=A.rt_subframes)
        except TypeError:
            rep.orchestrator.step()
        got = annot.get_data()
        got = got.get("data") if isinstance(got, dict) else got
        if got is not None and getattr(got, "size", 0):
            return got
    return None


for usd in made:
    name = os.path.splitext(os.path.basename(usd))[0]
    case = name.replace("grid_demo_", "")
    ctx = omni.usd.get_context()
    ctx.open_stage(usd)
    for _ in range(60):
        app.update()
    st = ctx.get_stage()
    d = A.cells * P * 0.62
    cam = UsdGeom.Camera.Define(st, "/World/Cam")
    cam.GetFocalLengthAttr().Set(35.0)
    cxf = UsdGeom.Xformable(cam.GetPrim())
    cxf.ClearXformOpOrder()
    cop = cxf.AddTransformOp()
    annot = rep.AnnotatorRegistry.get_annotator("rgb")
    annot.attach([rep.create.render_product("/World/Cam", (w, h))])

    if not A.video:
        if case in CAM_FIX:
            tgt, eye = CAM_FIX[case]
            look_at(cop, Gf.Vec3d(*eye), Gf.Vec3d(*tgt))
        else:
            look_at(cop, Gf.Vec3d(-d, -d, d * 1.15), Gf.Vec3d(0, 0, 0))
        data = grab(annot)
        if data is None:
            print("[grid] ☹ %s — rgb 버퍼가 비었다" % name)
        else:
            p = os.path.join(shot_dir, "%s.png" % name)
            Image.fromarray(data[:, :, :3]).save(p, format="PNG")
            print("[grid] %s -> %s" % (name, p))
        annot.detach()
        continue

    # ── 영상 — 움직이는 것이 요점이다 ────────────────────────────────
    #   물리를 안 돌린다. 발자국 xform 을 프레임마다 직접 옮긴다 (`animate`).
    #   그래서 결정적이고, 프레임 수만큼만 걸린다.
    fdir = os.path.join(shot_dir, name)
    os.makedirs(fdir, exist_ok=True)
    for old in glob.glob(os.path.join(fdir, "f_*.png")):
        os.remove(old)
    # 가감속 장면은 **실시간**으로 본다 — 빨리 감으면 「느리다」가 안 보인다.
    nfr = int(DUR[case] * 30) if case in DUR else A.frames
    n_ok = 0
    for i in range(nfr):
        u = i / max(1, nfr - 1)
        orbit = animate(st, case, u)
        if case in CAM_FIX:
            tgt, eye = CAM_FIX[case]
            look_at(cop, Gf.Vec3d(*eye), Gf.Vec3d(*tgt))
        else:
            ang = math.radians(215.0) + orbit
            look_at(cop, Gf.Vec3d(d * math.cos(ang), d * math.sin(ang), d * 1.05),
                    Gf.Vec3d(0, 0, 0.3))
        data = grab(annot)
        if data is None:
            continue
        Image.fromarray(data[:, :, :3]).save(
            os.path.join(fdir, "f_%04d.png" % i), format="PNG")
        n_ok += 1
        if i % 30 == 0:
            print("[grid]   %s  %d/%d" % (name, i, nfr), flush=True)
    annot.detach()
    if not n_ok:
        print("[grid] ☹ %s — 한 장도 못 받았다" % name)
        continue
    mp4 = os.path.join(shot_dir, "%s.mp4" % name)
    rc = os.system('ffmpeg -y -loglevel warning -framerate 30 -i "%s/f_%%04d.png" '
                   '-c:v libx264 -pix_fmt yuv420p -crf 20 "%s"' % (fdir, mp4))
    if rc == 0:
        print("[grid] %s -> %s  (%d프레임 · %.1f초)" % (name, mp4, n_ok, n_ok / 30.0))
    else:
        print("[grid] ☹ %s — ffmpeg 실패. 프레임은 %s 에 있다" % (name, fdir))

app.close()
