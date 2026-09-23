# -*- coding: utf-8 -*-
"""**칸과 차체를 같이 그려서** 왜 부딪히는지 보여주는 씬 (S15P21A106-267).

    cd <t3_amr> && source paths.sh
    python warehouse/scene/build_grid_demo.py                 세 장면 전부
    python warehouse/scene/build_grid_demo.py --case turn     한 장면만
    python warehouse/scene/build_grid_demo.py --pitch 1.2     격자를 바꿔 비교

산출: `$STAGE/grid_demo_<case>.usd`
      `--shoot` 를 주면 `$OUT/grid_demo/<case>.png`
      `--video` 를 주면 `$OUT/grid_demo/<case>.mp4` (움직인다)

    python warehouse/scene/build_grid_demo.py --video          다섯 장면 mp4
    python warehouse/scene/build_grid_demo.py --case rack --video

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

☹ 「회전 첫 스텝의 바퀴 미끄러짐」은 여기 없다. 그것은 기하가 아니라 **제어**다 —
  계단 입력과 바닥 마찰의 문제라 그려서 보여줄 수 없다. `tools/turn_error.py` ·
  `tools/cross_track.py` 가 녹화 NPZ 에서 재는 쪽이 맞다.

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
                choices=["all", "footprint", "side", "follow", "rack", "turn"])
ap.add_argument("--pitch", type=float, default=1.0)
ap.add_argument("--cells", type=int, default=7, help="격자 칸 수 (한 변)")
ap.add_argument("--shoot", action="store_true", help="만들고 PNG 까지 찍는다")
ap.add_argument("--video", action="store_true",
                help="움직이는 mp4 까지 만든다 (회전·접근). --shoot 을 겸한다")
ap.add_argument("--frames", type=int, default=120, help="--video 프레임 수 (30fps)")
ap.add_argument("--exposure", type=float, default=1.0, help="조명 밝기 배수")
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


def footprint(stage, path, cx, cy, yaw, mats, key="body", h=0.62):
    """계획이 쓰는 **발자국** — 축 기준 (-REAR..+FRONT) x (±WIDTH/2).

    ★ 움직일 수 있게 만든다 — 회전·이동 op 을 **값이 0 이어도** 달아 둔다.
      `--video` 가 프레임마다 그 값만 바꾼다 (`animate` 참조).
      op 을 나중에 추가하면 매번 만들어야 하고, 그러다 카메라가 한 자리에
      멈춘 사고를 이미 한 번 겪었다 (`headless_pibt._fpv_track`).
    """
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
MOTION = {
    "rack":   ("/World/A", "rot"),
    "turn":   ("/World/A", "rot"),
    "follow": ("/World/B", "app"),
}


def animate(stage, case, u):
    """0..1 의 u 를 받아 그 순간의 자세로 놓는다. 카메라 궤도면 각도를 돌려준다."""
    mo = MOTION.get(case)
    if mo is None:
        return u * 2 * math.pi * 0.5          # 정적 장면 — 반 바퀴 궤도
    path, kind = mo
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


cases = (["footprint", "side", "follow", "rack", "turn"]
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
    n_ok = 0
    for i in range(A.frames):
        u = i / max(1, A.frames - 1)
        orbit = animate(st, case, u)
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
            print("[grid]   %s  %d/%d" % (name, i, A.frames), flush=True)
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
