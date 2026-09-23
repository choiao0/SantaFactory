# -*- coding: utf-8 -*-
"""AMR 한 대를 **전면·측면·대각**에서 찍는다 (S15P21A106-264).

    cd <t3_amr> && source paths.sh
    python warehouse/scene/shoot_amr.py                    3장 -> $OUT/amr_shot/
    SHOOT_ROBOT=3 SHOOT_D=5 python warehouse/scene/shoot_amr.py

왜 이 파일이 있나
-----------------
선반에 상자를 올린 뒤(-264) **에셋이 실제로 어떻게 보이는지**를 봐야 하는데,
지금까지 그걸 보려면 주행을 한 판 돌려야 했다. 30분이 걸리고 GPU 를 물고,
영상에서 원하는 각도가 잡히리라는 보장도 없다.

여기서는 물리도 주행도 계획도 안 한다 — 스테이지를 열고, 카메라를 세 자리에
놓고, 세 장을 찍고 닫는다. 1분 안쪽이다.

    ☹ `run_record.sh` 계열과 **다른 물건**이다. 저쪽은 주행을 촬영하고
      이 파일은 **에셋을 촬영한다.** 지표도 mp4 도 안 만든다.

무엇을 재사용하나
-----------------
촬영 경로는 `runners/headless_pibt.py` 에서 검증된 것을 그대로 쓴다 —
리플리케이터 render product + `rgb` annotator, **붙인 직후 워밍업 렌더**,
그리고 `Image.save(..., format=...)`.

    ★ 워밍업이 없으면 첫 장이 `rgb 버퍼가 비었다` 로 죽는다 (2026-09-22 실측).
    ★ 포맷을 명시하지 않으면 확장자 추론이 엉뚱한 곳에서 터진다 (2026-09-23).

환경변수
--------
    SHOOT_ROBOT   찍을 로봇 번호 (기본 0)
    SHOOT_D       거리 [m] (기본 6)
    SHOOT_RES     해상도 (기본 1600x1000 — 정지컷이라 크게 찍는다)
    SHOOT_FOCAL   초점거리 [mm] (기본 45 — 6 m 에서 AMR 이 화면의 54 %)
    SHOOT_RT_SUBFRAMES  레이트레이서 수렴 프레임 (기본 16). 노이즈가 남으면 올린다
    SHOOT_SETTLE  버퍼가 찬 뒤 더 밟을 횟수 (기본 6)
    SHOOT_OUT     저장 폴더 (기본 $OUT/amr_shot)
    PIBT_STAGE    씬 USD (기본 $STAGE/pibt<N>.usd, N=PIBT_N 또는 13)
"""
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
W = os.environ.get("W") or os.path.dirname(os.path.dirname(_HERE))
OUT = os.environ.get("OUT") or os.path.join(W, "out")
STAGE = os.environ.get("STAGE") or os.path.join(W, "stage")

N = int(os.environ.get("PIBT_N", "") or 13)
STAGE_USD = os.environ.get("PIBT_STAGE") or os.path.join(STAGE, "pibt%02d.usd" % N)
ROBOT = int(os.environ.get("SHOOT_ROBOT", "") or 0)
DIST = float(os.environ.get("SHOOT_D", "") or 6.0)
RES = (os.environ.get("SHOOT_RES", "") or "1600x1000").lower()
# 초점거리 [mm]. Isaac 기본 수평 조리개 20.955 mm 기준 —
#   28 mm -> 화각 41.5도, 6 m 에서 프레임 4.5 m (1.5 m AMR 이 3분의 1)
#   45 mm -> 화각 26.3도, 6 m 에서 프레임 2.8 m (절반 넘게 찬다)  <- 기본
FOCAL = float(os.environ.get("SHOOT_FOCAL", "") or 45.0)
RT_SUB = int(os.environ.get("SHOOT_RT_SUBFRAMES", "") or 16)   # 레이트레이서 수렴 프레임
SETTLE = int(os.environ.get("SHOOT_SETTLE", "") or 6)          # 버퍼가 찬 뒤 더 밟을 횟수
SHOT_OUT = os.environ.get("SHOOT_OUT") or os.path.join(OUT, "amr_shot")

if not os.path.isfile(STAGE_USD):
    sys.exit("★ 씬이 없습니다: %s\n  먼저 한 번 돌려 씬을 만드세요:  bash run_record.sh %d"
             % (STAGE_USD, N))

# ── 앱 기동 (headless_pibt 와 같은 규약) ──────────────────────────────
from isaacsim import SimulationApp                       # noqa: E402

_CFG = {"headless": True}
_gpu = (os.environ.get("GPU", "") or "").strip()
if _gpu.isdigit():
    _CFG["active_gpu"], _CFG["multi_gpu"] = int(_gpu), False
print("[shot] SimulationApp 기동 · 씬 %s · 로봇 %d · 거리 %.1fm · 초점 %.0fmm%s"
      % (os.path.basename(STAGE_USD), ROBOT, DIST, FOCAL,
         " · GPU " + _gpu if _gpu.isdigit() else ""))
simulation_app = SimulationApp(_CFG)

import omni.usd                                          # noqa: E402
from pxr import Gf, UsdGeom                              # noqa: E402

ctx = omni.usd.get_context()
ctx.open_stage(STAGE_USD)
for _ in range(60):                                      # 스테이지 로드 대기
    simulation_app.update()
stage = ctx.get_stage()

# ── 대상 로봇의 자리 ─────────────────────────────────────────────────
path = "/World/Robots/amr_%d" % ROBOT
prim = stage.GetPrimAtPath(path)
if not prim or not prim.IsValid():
    simulation_app.close()
    sys.exit("★ 로봇 prim 이 없습니다: %s" % path)
bb = UsdGeom.BBoxCache(0, ["default"]).ComputeWorldBound(prim).ComputeAlignedBox()
lo, hi = bb.GetMin(), bb.GetMax()
cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
cz = (lo[2] + hi[2]) / 2
print("[shot] %s 중심 (%.2f, %.2f, %.2f) · 크기 %.2f x %.2f x %.2f"
      % (path, cx, cy, cz, hi[0]-lo[0], hi[1]-lo[1], hi[2]-lo[2]))

# 로봇의 헤딩 — xform 의 회전에서 뽑는다. 실패하면 +X 로 본다.
try:
    m = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(0)
    yaw = math.atan2(m[0][1], m[0][0])
except Exception:                                        # noqa: BLE001
    yaw = 0.0
fx, fy = math.cos(yaw), math.sin(yaw)
rx, ry = -fy, fx                                         # 왼쪽 방향

# ── 세 시점 — 전부 로봇 헤딩 기준 ───────────────────────────────────
#   전면: 정면에서 살짝 위    측면: 왼쪽 옆    대각: 앞왼쪽 위 (제품컷 각도)
VIEWS = [
    ("전면", ( 1.00,  0.00, 0.28)),
    ("측면", ( 0.00,  1.00, 0.28)),
    ("대각", ( 0.72,  0.72, 0.42)),
]
TARGET_Z = 0.85                                          # 선반 중간 — 상자가 화면에


def place(i, f_, r_, up_):
    """카메라를 로봇 기준 (앞, 왼쪽, 위) 방향에 놓고 겨냥한다."""
    p = "/World/Cameras/Shot_%d" % i
    cam = UsdGeom.Camera.Define(stage, p)
    cam.GetFocalLengthAttr().Set(FOCAL)
    eye = Gf.Vec3d(cx + DIST*(f_*fx + r_*rx), cy + DIST*(f_*fy + r_*ry), DIST*up_)
    tgt = Gf.Vec3d(cx, cy, TARGET_Z)
    fwd = (tgt - eye).GetNormalized()
    right = Gf.Cross(fwd, Gf.Vec3d(0, 0, 1)).GetNormalized()
    up = Gf.Cross(right, fwd)
    x = UsdGeom.Xformable(cam.GetPrim())
    x.ClearXformOpOrder()
    x.AddTransformOp().Set(Gf.Matrix4d(
        right[0], right[1], right[2], 0, up[0], up[1], up[2], 0,
        -fwd[0], -fwd[1], -fwd[2], 0, eye[0], eye[1], eye[2], 1))
    return p


# ── 촬영 ─────────────────────────────────────────────────────────────
import omni.kit.app                                      # noqa: E402

omni.kit.app.get_app().get_extension_manager() \
    .set_extension_enabled_immediate("omni.replicator.core", True)
import omni.replicator.core as rep                       # noqa: E402
from PIL import Image                                    # noqa: E402

# ★★ 리플리케이터 **그래프를 밟아야** 버퍼가 찬다 (2026-09-23).
#
#   `headless_pibt` 에서는 타임라인이 돌고 있어서 `simulation_app.update()` 만으로
#   버퍼가 찼다. 정지컷은 타임라인이 멈춰 있어 그것만으로는 **영영 비어 있다**
#   (첫 판에서 세 장 다 「rgb 버퍼가 비었다」였다).
#
#   `rep.orchestrator.step` 은 Isaac 판마다 시그니처가 다르다. 되는 것을 한 번
#   찾아 두고 그 뒤로는 그것만 쓴다 — 무엇이 먹혔는지 로그에 남긴다.
_STEP = None


def _step_once():
    global _STEP
    if _STEP is not None:
        _STEP()
        return
    for label, fn in (
            # rt_subframes 는 레이트레이서에 수렴할 프레임을 더 준다 — 정지컷이라
            # 노이즈가 남으면 안 된다. 안 받는 판이면 다음 후보로 내려간다.
            ("orchestrator.step(delta_time=0, rt_subframes=%d)" % RT_SUB,
             lambda: rep.orchestrator.step(delta_time=0.0, rt_subframes=RT_SUB)),
            ("orchestrator.step(delta_time=0)", lambda: rep.orchestrator.step(delta_time=0.0)),
            ("orchestrator.step()", lambda: rep.orchestrator.step()),
            ("app.update()", lambda: simulation_app.update())):
        try:
            fn()
        except Exception as e:                           # noqa: BLE001
            print("[shot]   렌더 스텝 %s 안 됨: %r" % (label, e))
            continue
        _STEP = fn
        print("[shot] 렌더 스텝 = %s" % label)
        return
    _STEP = lambda: simulation_app.update()              # noqa: E731
    _STEP()


def _as_array(d):
    """판에 따라 ndarray 를 그대로 주기도 하고 dict 로 싸서 주기도 한다."""
    if isinstance(d, dict):
        d = d.get("data")
    return d


def _grab(annot, tries=20):
    """버퍼가 찰 때까지 밟으며 기다린다. (배열, 몇 번 만에) 또는 (None, tries).

    ★ 버퍼가 찬 **뒤에도 몇 장 더 밟는다.** 첫 프레임은 레이트레이싱이 덜
      수렴해 노이즈가 낀다 — 주행 영상은 흘러가서 티가 안 나지만 정지컷은 남는다.
    """
    for k in range(tries):
        _step_once()
        got = _as_array(annot.get_data())
        if got is not None and getattr(got, "size", 0):
            for _ in range(SETTLE):
                _step_once()
            return _as_array(annot.get_data()), k + 1
    return None, tries


os.makedirs(SHOT_OUT, exist_ok=True)
w, h = (int(v) for v in RES.split("x"))
made = []
for i, (name, (f_, r_, up_)) in enumerate(VIEWS):
    cam_path = place(i, f_, r_, up_)
    annot = rep.AnnotatorRegistry.get_annotator("rgb")
    annot.attach([rep.create.render_product(cam_path, (w, h))])
    data, tries = _grab(annot)
    if data is None:
        raw = annot.get_data()
        print("[shot] ☹ %s — %d번 밟아도 rgb 버퍼가 비었다 (받은 것: %s). 건너뛴다"
              % (name, tries, type(raw).__name__))
        annot.detach()
        continue
    out = os.path.join(SHOT_OUT, "amr_%s.png" % name)
    Image.fromarray(data[:, :, :3]).save(out, format="PNG")   # ★ 포맷 명시
    annot.detach()
    made.append(out)
    print("[shot] %s -> %s (%d x %d · %d번 만에)" % (name, out, w, h, tries))

print("[shot] %d장 · %s" % (len(made), SHOT_OUT))
simulation_app.close()
sys.exit(0 if len(made) == len(VIEWS) else 1)
