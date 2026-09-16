# -*- coding: utf-8 -*-
"""팀 T3 창고(v5.9) + 물리 + iw.hub AMR N대 씬을 만든다.

v1의 build_amr_scene.py를 팀 씬에 맞게 다시 쓴 것. 두 가지가 다르다.

[1] 콜리전은 팀 씬에 이미 1,127개가 들어 있다
      walls 652 · columns 416 · office_walls 25 · worktables 16
      conveyors 11 · pallets 6 · ground 1
    v1처럼 내가 붙일 필요가 없다. racks 에는 없는데, 궤적이 렉을 피하도록
    계획돼 있고(장애물 침범 0건) 메시가 많아 PhysX 부하가 크므로 그대로 둔다.

    ★ 2026-09-17 정정. 「부하가 크다」는 **참조 에셋 메시**(프레임 176 +
      데크 264) 기준이었다. 격자 값2 를 사각형으로 접으면 **전부 24개**다.
      그리고 그 참조는 서버에서 **하나도 안 풀린다** — 랙 자리 48,420칸이
      물리적으로 비어 있었다. `build_scene.py` 가 이제 투명 박스를 세운다
      (`RACK_COLLIDER=0` 으로 끈다). 씬을 다시 구워야 반영된다.

[2] **/World/ground 는 v1과 똑같은 함정이다**
      단위 Cube 를 (125.1, 116.1, 0.1) 로 비균일 스케일 → 비율 1251:1.
      v1에서 (99.8, 66, 0.1) = 1000:1 짜리 바닥에 콜리전을 줬다가 중심에서
      30m 떨어진 지점에서 로봇이 23mm 파묻혀 바퀴가 헛돌았다. 여기가 더 심하다.
      → ground 의 콜리전을 끄고 무한 평면(UsdGeom.Plane)을 z=0 에 따로 둔다.
      시각적으로는 /World/floor(Mesh, z≈0)가 그대로 보이므로 차이가 없다.

    (v2/README.md 에 "팀 씬은 이 문제가 구조적으로 없다"고 적었던 것은 틀렸다.)
"""
import argparse, json, math, os

HERE = os.path.dirname(os.path.abspath(__file__))

ap = argparse.ArgumentParser()
ap.add_argument("--warehouse",   # paths.sh 의 $SCENE 과 같은 값 (옛 ../../t3_warehouse 는 -219 로 삭제)
                default=os.environ.get("SCENE") or os.path.join(HERE, "..", "warehouse", "scene", "warehouse_scene.usd"))
ap.add_argument("--robot",
                default=os.path.expanduser("../robots/iwhub/iw_hub.usd"))
ap.add_argument("--traj", default=os.path.expanduser("<t3_amr>/traj_v59/fleet_02/trajectories.json"))
ap.add_argument("--n", type=int, default=2)
ap.add_argument("--starts", default=None,
                help="계획기가 낸 starts.json. 주면 이 좌표에 로봇을 세운다(권장).")
ap.add_argument("--out", default=os.path.expanduser("<t3_amr>/warehouse_v59_amr2.usd"))
ap.add_argument("--shelf", default=None,
                help="적재 선반 USD (warehouse/scene/build_amr_shelf.py 산출). "
                     "주면 로봇마다 얹는다. 없으면 예전과 똑같이 로봇만 세운다.")
ap.add_argument("--shelf-link", default="chassis",
                help="선반을 매달 **강체 링크** 이름. 아티큘레이션 루트에 매달면 "
                     "물리가 안 옮겨 줘서 선반만 제자리에 남는다. 기본 chassis")
args = ap.parse_args()

from isaacsim import SimulationApp
simulation_app = SimulationApp({"headless": True})
import omni.usd
from pxr import Usd, UsdGeom, UsdPhysics, UsdLux, UsdShade, Sdf, Gf

WHEEL_R = 0.081        # 확정값(에셋 저작 0.08). 로봇을 바닥에 앉히는 z 오프셋

ctx = omni.usd.get_context(); ctx.new_stage()
st = ctx.get_stage()
UsdGeom.SetStageUpAxis(st, UsdGeom.Tokens.z)
UsdGeom.SetStageMetersPerUnit(st, 1.0)
st.DefinePrim("/World", "Xform")

# --- 물리 씬 ---
# 팀 씬의 PhysicsScene 은 /physicsScene (=/World 밖)이라 참조로 딸려오지 않는다.
scene = UsdPhysics.Scene.Define(st, "/World/PhysicsScene")
scene.CreateGravityDirectionAttr(Gf.Vec3f(0, 0, -1))
scene.CreateGravityMagnitudeAttr(9.81)
print("[s] PhysicsScene 생성", flush=True)

# --- 창고 참조 ---
wh = st.DefinePrim("/World/Warehouse", "Xform")
wh.GetReferences().AddReference(args.warehouse, Sdf.Path("/World"))
wh.Load(Usd.LoadWithDescendants)
n_col = sum(1 for p in Usd.PrimRange(wh) if p.HasAPI(UsdPhysics.CollisionAPI))
print(f"[s] 창고 참조: {args.warehouse}", flush=True)
print(f"[s]   콜리전 보유 prim {n_col}개 (팀 씬에 이미 들어 있음)", flush=True)

# --- ground 콜리전 해제 + 무한 평면 (위 [2] 참조) ---
gnd = st.GetPrimAtPath("/World/Warehouse/ground")
if gnd and gnd.IsValid():
    UsdPhysics.CollisionAPI(gnd).CreateCollisionEnabledAttr().Set(False)
    print("[s] /World/Warehouse/ground 콜리전 해제 (1251:1 비균일 스케일)", flush=True)
else:
    print("[s] !! ground prim 을 못 찾음 — 씬 구조 확인 필요", flush=True)

# --- 지붕 숨김 ---
# 팀 씬에는 지붕이 있다(roof_steel 492 + roof_skin 14). 위에서 내려다보는
# 관측 카메라로는 **하얀 지붕만 보인다** — 실제로 그 증상이 났다.
# 물리에는 영향이 없다(지붕에 콜리전이 없음). 시각적으로만 감춘다.
n_hidden = 0
for grp in ("roof_skin", "roof_steel"):
    r = st.GetPrimAtPath(f"/World/Warehouse/{grp}")
    if r and r.IsValid():
        UsdGeom.Imageable(r).MakeInvisible()
        n_hidden += 1
print(f"[s] 지붕 숨김: {n_hidden}개 그룹 (roof_skin, roof_steel)", flush=True)

gp = UsdGeom.Plane.Define(st, "/World/GroundPlane")
gp.CreateAxisAttr("Z")
gp.CreateDoubleSidedAttr(False)
UsdGeom.Imageable(gp.GetPrim()).MakeInvisible()
UsdPhysics.CollisionAPI.Apply(gp.GetPrim())
print("[s] GroundPlane 생성 (무한 평면 콜라이더, z=0)", flush=True)

# ★ 바닥 물리 재질 (S15P21A106-224) — 기본은 **끔**
#
#   2026-09-17 실측: 창고 씬 전체에 `physics:*Friction` 을 가진 prim 이
#   **0 개**다 (콜라이더는 3,973개). 로봇이 실제로 달리는 이 평면에도 없다.
#   `/World/floor` 에 묶인 것은 MDL — 렌더 재질이지 물리가 아니다.
#   바퀴 쪽 0.9 는 `iw_hub.usd` 저작값이고, 짝이 되는 바닥은 **PhysX 기본
#   재질**이다. 그 값을 우리는 고른 적도 재 본 적도 없다.
#
#   Isaac 공식 트러블슈팅이 「바퀴 마찰이 너무 적으면 미끄러진다」고 적고,
#   MIR100 이 90도 명령에 10도만 돈 사례가 **PhysicsMaterial 이 없던** 경우다.
#   회전 중 접지 상실 1/89 (2026-09-16 a6) 의 후보로 남는다.
#
#   ★ 그래도 기본을 안 바꾼다. 마찰을 주면 주행 결과가 **바뀐다** — 지금까지
#     잰 기준선(시드 2 = 560.0s · 시드 5 = 541.5s)이 비교 불능이 된다.
#     값을 정하는 것은 측정이지 짐작이 아니다. A/B 로 연다.
#
#       GROUND_FRICTION=0.9          정적·동적 같이 0.9
#       GROUND_FRICTION=0.9,0.7      정적 0.9 · 동적 0.7
_gf = os.environ.get("GROUND_FRICTION", "").strip()
if _gf:
    _v = [float(x) for x in _gf.split(",")]
    _static, _dynamic = _v[0], (_v[1] if len(_v) > 1 else _v[0])
    _m = UsdShade.Material.Define(st, "/World/PhysicsMaterials/Ground")
    _api = UsdPhysics.MaterialAPI.Apply(_m.GetPrim())
    _api.CreateStaticFrictionAttr(_static)
    _api.CreateDynamicFrictionAttr(_dynamic)
    _api.CreateRestitutionAttr(0.0)
    UsdShade.MaterialBindingAPI.Apply(gp.GetPrim())
    UsdShade.MaterialBindingAPI(gp.GetPrim()).Bind(
        _m, UsdShade.Tokens.weakerThanDescendants, "physics")
    print(f"[s] ★ 바닥 물리 재질 정적 {_static} · 동적 {_dynamic} "
          f"(GROUND_FRICTION) — 기준선과 비교 불가", flush=True)
else:
    print("[s] 바닥 물리 재질 없음 (PhysX 기본값). 주려면 "
          "GROUND_FRICTION=0.9 또는 0.9,0.7", flush=True)

# --- 충전존 (stations.json charger 6 + charge_q 6 = 파란 장판 12개, x=107.8/105.5 y=50~65) ---
# 궤적 시작점 대신 여기서 로봇을 스폰한다. PathFollower._closest_forward()는
# ci=0에서 좁은 창(초기 4점=1m)만 보므로, 충전존이 궤적 시작점과 멀면 로봇은
# MAPF 계획이 아닌 단순 직선으로 그 창까지 접근한다 — 이 접근 구간은 충돌 보장이 없다.
# charge_q(대기열, x=105.5)를 먼저 쓴다 — charger(x=107.8)는 벽걸이 캐비닛과
# 바로 붙어 있어 실측 결과 로봇이 스폰 직후 끼어 거의 못 움직였다 (amr_0, 30초간 1.71m).
CHARGE_ZONE = [(105.5, y) for y in (50, 53, 56, 59, 62, 65)] + \
              [(107.8, y) for y in (50, 53, 56, 59, 62, 65)]

# --- 로봇 ---
# **스폰은 계획 시작점과 같아야 한다.** 추종기 PathFollower._closest_forward() 는
# 초기에 탐색 창을 1 m 만 열기 때문에, 스폰이 궤적 시작점에서 멀면 로봇은 자기 경로를
# 영영 잡지 못한다. 실측(2026-09-01): robot 0 이 88.2 m 떨어져 추종오차 76 m 로
# 420초 내내 제자리. --starts 를 주면 그 문제가 구조적으로 사라진다.
with open(args.traj, encoding="utf-8") as f:
    tj = json.load(f)
rids = sorted(tj["robots"].keys(), key=int)[:args.n]
spawn = None
if args.starts:
    with open(args.starts, encoding="utf-8") as f:
        spawn = {r["id"]: (r["x"], r["y"], r["yaw_deg"]) for r in json.load(f)["robots"]}
    print(f"[s] 스폰 좌표: {args.starts} ({len(spawn)}대)", flush=True)
else:
    print("[s] !! --starts 없음 — 충전존에 세운다. 궤적 시작점과 어긋날 수 있다.", flush=True)
st.DefinePrim("/World/Robots", "Xform")
placed = []
for i, rid in enumerate(rids):
    wp = tj["robots"][rid]
    if spawn and i in spawn:
        x0, y0, yaw = spawn[i]
    else:
        x0, y0 = CHARGE_ZONE[i % len(CHARGE_ZONE)]
        _, wx0, wy0 = wp[0]                      # 궤적상 실제 시작점 — yaw만 참고
        dx, dy = wx0 - x0, wy0 - y0
        yaw = math.degrees(math.atan2(dy, dx)) if (abs(dx) > 1e-6 or abs(dy) > 1e-6) else 0.0
    gap = math.hypot(wp[0][1] - x0, wp[0][2] - y0)
    if gap > 1.0:
        print(f"[s] !! amr_{i} 스폰이 궤적 시작점과 {gap:.1f}m 떨어짐", flush=True)
    path = f"/World/Robots/amr_{i}"
    prim = st.DefinePrim(path, "Xform")
    prim.GetReferences().AddReference(args.robot)
    xf = UsdGeom.Xformable(prim)
    xf.AddTranslateOp().Set(Gf.Vec3d(x0, y0, WHEEL_R))
    xf.AddRotateZOp().Set(yaw)

    # --- 적재 선반 (S15P21A106-196) ---
    #   `amr_shelf.usd` 는 구동축 원점 · +X 전진 · 로봇 로컬 z 로 저작돼 있어
    #   추가 변환이 필요 없다.
    #
    #   ★★ **로봇 루트가 아니라 `chassis` 링크 밑에 붙인다** (2026-09-13 실측).
    #     `/World/Robots/amr_i` 는 ArticulationRoot Xform 이고, 물리는 그걸
    #     안 움직인다 — PhysX 는 **각 링크 prim**(chassis·wheel·…)에 자세를
    #     쓴다. 그래서 루트 밑에 두면 로봇만 달리고 **선반은 출발 자리에
    #     그대로 서 있다.** 영상에서 바로 보인다.
    #     `chassis` 의 로컬 변환은 항등(translate 0 · orient 단위 · scale 1)
    #     이라 좌표 보정은 필요 없다 — 부모만 바꾸면 된다.
    #
    #   ★ `XformCommonAPI` 를 쓰지 말 것. 이 저장소는 위처럼 `AddTranslateOp` +
    #     `AddRotateZOp` 조합으로 저작하는데, 그 위에서 `SetTranslate()` 를 부르면
    #     **False 를 돌려주고 아무 일도 하지 않는다 — 예외조차 없다.**
    #     그래서 여기서도 op 를 안 걸고 참조만 얹는다 (원점 일치 저작이라 0 이면 된다).
    if args.shelf:
        link = st.GetPrimAtPath(f"{path}/{args.shelf_link}")
        if not link:
            raise SystemExit(
                f"★ 로봇에 '{args.shelf_link}' 링크가 없습니다: {path}\n"
                f"  선반을 매달 강체 링크 이름을 --shelf-link 로 주세요.\n"
                f"  (iw.hub 은 chassis. 루트에 매달면 물리가 안 옮겨 줍니다)")
        sh = st.DefinePrim(f"{path}/{args.shelf_link}/shelf", "Xform")
        sh.GetReferences().AddReference(args.shelf)

    placed.append((path, rid, x0, y0, yaw))
    print(f"[s] amr_{i} <- robot {rid}  pos=({x0:.1f}, {y0:.1f}) yaw={yaw:.0f}도  "
          f"궤적시작 ({wp[0][1]:.1f},{wp[0][2]:.1f}) 차이 {gap:.2f}m  "
          f"웨이포인트 {len(wp)}개", flush=True)

# --- 조명: 팀 씬에 sun/dome/lights 96개가 이미 있으므로 추가하지 않는다 ---

# --- 카메라 (고정 시점) ---
def look_at(path, eye, tgt, focal=24.0):
    cam = UsdGeom.Camera.Define(st, path)
    cam.CreateFocalLengthAttr(focal)
    cam.CreateClippingRangeAttr(Gf.Vec2f(0.05, 100000.0))
    eye, tgt = Gf.Vec3d(*eye), Gf.Vec3d(*tgt)
    f = (tgt - eye).GetNormalized()
    up0 = Gf.Vec3d(0, 0, 1) if abs(Gf.Dot(f, Gf.Vec3d(0, 0, 1))) < 0.999 else Gf.Vec3d(0, 1, 0)
    r = Gf.Cross(f, up0).GetNormalized(); u = Gf.Cross(r, f).GetNormalized()
    x = UsdGeom.Xformable(cam.GetPrim()); x.ClearXformOpOrder()
    x.AddTransformOp().Set(Gf.Matrix4d(r[0], r[1], r[2], 0, u[0], u[1], u[2], 0,
                                       -f[0], -f[1], -f[2], 0, eye[0], eye[1], eye[2], 1))

st.DefinePrim("/World/Cameras", "Xform")
cx, cy = placed[0][2], placed[0][3]
look_at("/World/Cameras/Cam_Follow", (cx - 8, cy - 10, 5.0), (cx, cy, 0.3), 20.0)
# 창고 범위 x[-5,120] y[-5,111] -> 중심 (57.5, 53). 지붕을 숨겼으므로 내부가 보인다.
look_at("/World/Cameras/Cam_Overview", (57.5, -35.0, 62.0), (57.5, 53.0, 0.0), 20.0)
# 바로 위에서 내려다보는 평면도 시점 — AMR 2대의 경로를 동시에 보기 좋다
look_at("/World/Cameras/Cam_Top", (57.5, 53.0, 120.0), (57.5, 53.01, 0.0), 24.0)
print("[s] 카메라 3개 (Cam_Follow, Cam_Overview, Cam_Top)", flush=True)

st.GetRootLayer().Export(args.out)
print(f"[s] 저장: {args.out}", flush=True)
print("[s] DONE", flush=True)
simulation_app.close()
