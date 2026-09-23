# -*- coding: utf-8 -*-
"""**칸과 차체를 같이 그려서** 왜 부딪히는지 보여주는 씬 (S15P21A106-267).

    cd <t3_amr> && source paths.sh
    python warehouse/scene/build_grid_demo.py                 세 장면 전부
    python warehouse/scene/build_grid_demo.py --case turn     한 장면만
    python warehouse/scene/build_grid_demo.py --pitch 1.2     격자를 바꿔 비교

산출: `$STAGE/grid_demo_<case>.usd`  (`--shoot` 를 주면 PNG 까지)

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
    side        옆 칸 두 대. 간격 200 mm — **안 닿는다**
    turn        가운데가 제자리 회전. 스윕 원이 옆 차체를 파고든다

색
--
    칸 선    진회색     발자국   반투명 청회색
    스윕 원  주황       침투 구간 빨강
"""
import argparse
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
ap.add_argument("--case", default="all", choices=["all", "footprint", "side", "turn"])
ap.add_argument("--pitch", type=float, default=1.0)
ap.add_argument("--cells", type=int, default=7, help="격자 칸 수 (한 변)")
ap.add_argument("--shoot", action="store_true", help="만들고 PNG 까지 찍는다")
ap.add_argument("--res", default="1600x1000")
A = ap.parse_args()
P = A.pitch

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

from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade        # noqa: E402

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


def grid(stage, mats, n):
    """1.0 m 격자 — **진한 선**. 칸 경계가 보여야 이 설명이 성립한다."""
    half, t, z = n * P / 2, 0.022, 0.004
    for i in range(n + 1):
        v = -half + i * P
        box(stage, f"/World/Grid/x_{i}", v - t/2, v + t/2, -half, half, 0, z, mats["line"])
        box(stage, f"/World/Grid/y_{i}", -half, half, v - t/2, v + t/2, 0, z, mats["line"])
    box(stage, "/World/Floor", -half, half, -half, half, -0.01, 0.0, mats["floor"])


def footprint(stage, path, cx, cy, yaw, mats, key="body", h=0.62):
    """계획이 쓰는 **발자국** — 축 기준 (-REAR..+FRONT) x (±WIDTH/2)."""
    return box(stage, path, cx - REAR, cx + FRONT, cy - WIDTH/2, cy + WIDTH/2,
               0.02, h, mats[key], yaw=yaw, cx=cx, cy=cy)


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


cases = ["footprint", "side", "turn"] if A.case == "all" else [A.case]
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

for usd in made:
    name = os.path.splitext(os.path.basename(usd))[0]
    ctx = omni.usd.get_context()
    ctx.open_stage(usd)
    for _ in range(60):
        app.update()
    st = ctx.get_stage()
    d = A.cells * P * 0.62
    cam = UsdGeom.Camera.Define(st, "/World/Cam")
    cam.GetFocalLengthAttr().Set(35.0)
    eye, tgt = Gf.Vec3d(-d, -d, d * 1.15), Gf.Vec3d(0, 0, 0)
    f = (tgt - eye).GetNormalized()
    r = Gf.Cross(f, Gf.Vec3d(0, 0, 1)).GetNormalized()
    u = Gf.Cross(r, f)
    xf = UsdGeom.Xformable(cam.GetPrim())
    xf.ClearXformOpOrder()
    xf.AddTransformOp().Set(Gf.Matrix4d(r[0], r[1], r[2], 0, u[0], u[1], u[2], 0,
                                        -f[0], -f[1], -f[2], 0, eye[0], eye[1], eye[2], 1))
    annot = rep.AnnotatorRegistry.get_annotator("rgb")
    annot.attach([rep.create.render_product("/World/Cam", (w, h))])
    data = None
    for _ in range(20):                                # ★ 그래프를 밟아야 버퍼가 찬다
        try:
            rep.orchestrator.step(delta_time=0.0, rt_subframes=16)
        except TypeError:
            rep.orchestrator.step()
        got = annot.get_data()
        got = got.get("data") if isinstance(got, dict) else got
        if got is not None and getattr(got, "size", 0):
            data = got
            break
    if data is None:
        print("[grid] ☹ %s — rgb 버퍼가 비었다" % name)
    else:
        p = os.path.join(shot_dir, "%s.png" % name)
        Image.fromarray(data[:, :, :3]).save(p, format="PNG")   # ★ 포맷 명시
        print("[grid] %s -> %s" % (name, p))
    annot.detach()

app.close()
