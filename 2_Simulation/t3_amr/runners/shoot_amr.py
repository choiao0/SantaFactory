# -*- coding: utf-8 -*-
"""AMR 한 대의 구조 사진 3장 — 정면 · 측면 · 대각선 (S15P21A106-196).

    python runners/shoot_amr.py --stage $STAGE/pibt12.usd --out $OUT/amr_shots

선반이 로봇에 제대로 얹혀 있는지, 랙 데크를 뚫는지를 **눈으로** 확인하기 위한
것이다. 랙은 `instance=True` 참조라 콜라이더가 없어 물리로는 안 잡힌다
(`run_webrtc.sh` 머리말 참조). 영상보다 정지 사진이 치수를 보기에 낫다.

[왜 주행과 따로 도는가]
`live_pibt.py` 의 캡처는 **활성 뷰포트 스크린샷**이라 스트리밍 익스피리언스가
떠 있어야 하고, 카메라도 씬에 박힌 3개(Cam_Follow·Overview·Top)뿐이다. 여기는
로봇 기준으로 카메라를 새로 놓아야 해서 replicator 로 직접 렌더한다.
**물리를 안 돌린다** — 씬을 열고 첫 프레임만 찍는다. 그래서 빠르고, 주행
지문(ms/step·체크포인트)에 영향이 없다.

[카메라 배치]  로봇 로컬 기준. +X 가 전진 (heading_offset=0)
    정면    전진 방향 **앞**에서 뒤를 본다      — 폭·앞면
    측면    좌현에서 본다                       — 전장·높이·단 구성
    대각선  앞-좌 45도, 높은 곳에서 내려다본다  — 3단 구조 전체

★ 다른 로봇은 숨긴다 (`--keep-others` 로 끔). 충전존 출발 간격이 2.4 m 라
  5 m 거리 · 35 mm 화각이면 옆 로봇이 프레임에 들어와 구조를 가린다.
"""
import argparse
import math
import os
import sys

ap = argparse.ArgumentParser()
ap.add_argument("--stage", required=True, help="촬영할 씬 USD (선반이 붙은 것)")
ap.add_argument("--out", required=True, help="PNG 를 쓸 폴더")
ap.add_argument("--robot", default="/World/Robots/amr_0")
ap.add_argument("--dist", type=float, default=5.0, help="정면·측면 카메라 거리 [m]")
ap.add_argument("--focal", type=float, default=35.0, help="초점거리 [mm]. 작을수록 넓다")
ap.add_argument("--res", default="1600x1200", help="해상도 WxH. 4:3 이 세로 여유가 있다")
ap.add_argument("--warmup", type=int, default=24,
                help="첫 프레임은 셰이더·텍스처가 덜 올라온다. 버릴 프레임 수")
ap.add_argument("--keep-others", action="store_true", help="다른 로봇을 숨기지 않는다")
args = ap.parse_args()

W, H = (int(v) for v in args.res.lower().split("x"))

from isaacsim import SimulationApp                                  # noqa: E402
simulation_app = SimulationApp({"headless": True})

import numpy as np                                                  # noqa: E402
import omni.replicator.core as rep                                  # noqa: E402
import omni.usd                                                     # noqa: E402
from PIL import Image                                               # noqa: E402
from pxr import Gf, UsdGeom                                         # noqa: E402

ctx = omni.usd.get_context()
ctx.open_stage(args.stage)
st = ctx.get_stage()

prim = st.GetPrimAtPath(args.robot)
if not prim:
    raise SystemExit(f"★ 로봇 prim 이 없습니다: {args.robot}")

# --- 로봇 pose — 씬 빌더가 AddTranslateOp + AddRotateZOp 으로 저작한다 ---
x0 = y0 = 0.0
yaw = 0.0
for op in UsdGeom.Xformable(prim).GetOrderedXformOps():
    n = op.GetOpName()
    if n.endswith("translate"):
        t = op.Get()
        x0, y0 = float(t[0]), float(t[1])
    elif "rotateZ" in n:
        yaw = float(op.Get())

th = math.radians(yaw)
fwd = (math.cos(th), math.sin(th))          # 로봇 +X = 전진
lft = (-math.sin(th), math.cos(th))         # 좌현

# 선반 포함 z 0.220~1.650. 중심을 0.85 로 잡으면 바퀴부터 상단 레일까지 들어온다.
TGT = (x0, y0, 0.85)

print(f"[shot] {args.robot}  pos=({x0:.2f}, {y0:.2f})  yaw={yaw:.0f}도", flush=True)


def look_at(path, eye, tgt, focal):
    """build_amr_scene_v2.py:look_at 과 같은 수식 — 그쪽과 어긋나면 안 된다."""
    cam = UsdGeom.Camera.Define(st, path)
    cam.CreateFocalLengthAttr(focal)
    cam.CreateClippingRangeAttr(Gf.Vec2f(0.05, 100000.0))
    eye, tgt = Gf.Vec3d(*eye), Gf.Vec3d(*tgt)
    f = (tgt - eye).GetNormalized()
    up0 = Gf.Vec3d(0, 0, 1) if abs(Gf.Dot(f, Gf.Vec3d(0, 0, 1))) < 0.999 else Gf.Vec3d(0, 1, 0)
    r = Gf.Cross(f, up0).GetNormalized()
    u = Gf.Cross(r, f).GetNormalized()
    x = UsdGeom.Xformable(cam.GetPrim())
    x.ClearXformOpOrder()
    x.AddTransformOp().Set(Gf.Matrix4d(r[0], r[1], r[2], 0, u[0], u[1], u[2], 0,
                                       -f[0], -f[1], -f[2], 0, eye[0], eye[1], eye[2], 1))
    return str(cam.GetPath())


d = args.dist
diag = (fwd[0] + lft[0], fwd[1] + lft[1])
dn = math.hypot(*diag) or 1.0
diag = (diag[0] / dn, diag[1] / dn)

SHOTS = [
    ("1_정면",   (x0 + fwd[0] * d,        y0 + fwd[1] * d,        1.10)),
    ("2_측면",   (x0 + lft[0] * d,        y0 + lft[1] * d,        1.10)),
    ("3_대각선", (x0 + diag[0] * d * 1.1, y0 + diag[1] * d * 1.1, 2.60)),
]

# --- 다른 로봇 숨기기 ---
if not args.keep_others:
    n = 0
    robots = st.GetPrimAtPath("/World/Robots")
    if robots:
        for r in robots.GetChildren():
            if str(r.GetPath()) != args.robot:
                UsdGeom.Imageable(r).MakeInvisible()
                n += 1
    print(f"[shot] 다른 로봇 {n}대 숨김", flush=True)

os.makedirs(args.out, exist_ok=True)

# --- 렌더 ---
#   ★ 카메라마다 render_product 를 따로 만들고 **한 번에 하나만** 어노테이터에
#     붙인다. 한꺼번에 붙이면 GPU 메모리가 해상도 x 개수만큼 잡힌다.
written = []
for name, eye in SHOTS:
    path = look_at(f"/World/Cameras/Shot_{name.split('_')[0]}", eye, TGT, args.focal)
    rp = rep.create.render_product(path, (W, H))
    ann = rep.AnnotatorRegistry.get_annotator("rgb")
    ann.attach([rp])

    # 첫 프레임은 셰이더가 덜 올라와 까맣거나 얼룩진다. 몇 장 버린다.
    for _ in range(args.warmup):
        rep.orchestrator.step(rt_subframes=1)

    data = ann.get_data()
    arr = np.asarray(data)
    if arr.size == 0:
        print(f"[shot] ★ {name} 렌더 실패 (빈 버퍼)", flush=True)
    else:
        img = Image.fromarray(arr[..., :3].astype(np.uint8))
        f = os.path.join(args.out, f"amr_{name}.png")
        img.save(f)
        written.append(f)
        print(f"[shot] {f}  {img.size[0]}x{img.size[1]}  "
              f"eye=({eye[0]:.2f}, {eye[1]:.2f}, {eye[2]:.2f})", flush=True)

    ann.detach([rp])
    rp.destroy()

print(f"[shot] DONE {len(written)}장", flush=True)
simulation_app.close()
sys.exit(0 if len(written) == len(SHOTS) else 1)
