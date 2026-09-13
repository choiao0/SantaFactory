# -*- coding: utf-8 -*-
"""iw.hub 위에 얹는 2단 적재 선반 USD 를 만든다 (S15P21A106-196).

    cd ~/isaacsim && ./python.sh $W/warehouse/scene/build_amr_shelf.py
    ./python.sh .../build_amr_shelf.py --top-rear 0.850     상부를 깎을 때

산출: `$W/robots/shelf/amr_shelf.usd`

[좌표 규약 — 이게 틀리면 선반이 공중에 뜨거나 로봇을 뚫는다]
루트 prim 원점은 **구동축**, +X 가 전진, z 는 **로봇 로컬**이다.
로봇 prim 은 `build_amr_scene_v2.py:132` 가 `z = WHEEL_R = 0.081` 에 앉히므로

    로봇 로컬 z = 바닥 기준 z - 0.081

설계 문서의 표는 전부 **바닥 기준**이라 여기서 0.081 을 뺀다. 그래야 붙일 때
translate 가 (0, 0, 0) 이 된다.

[왜 상부만 짧은가]
랙 1단 데크 밑면이 **1,005 mm** 다. 지금 로봇은 220 mm 라 그 밑으로 지나가지만
1,650 mm 선반은 못 지나간다. 구동축이 앞이라(heading_offset=0) 차체는 헤딩의
**뒤쪽**으로 뻗고, 로봇이 랙에 등을 돌리면 꼬리가 랙 풋프린트로 들어간다.
그래서 베이스는 1,500 mm 를 유지하되 **상부만** 뒤를 깎는다.

    --top-rear 1.110   상부 1,500 mm  (베이스와 같음 = 안 깎음, 기본)
    --top-rear 0.850   상부 1,240 mm  (설계 문서 제안값)

★ 기본을 **안 깎은 1.110** 으로 둔 이유: `tools/check_shelf_clearance.py --sweep`
  을 도달 가능한 전 상태(4,660개)에 돌렸을 때 어느 길이에서도 랙 침범이 2건으로
  같았고, 그 2건은 **현재 차체(폭 0.65)로도 똑같이 난다** (원인이 꼬리가 아니라
  앞쪽이고 cross 풀링 탓). 즉 이 브랜치에서는 깎을 근거가 재현되지 않았다.
  설계 문서의 41건은 배터리 ON · robot_first 시절 표본이다.
  **서버에서 눈으로 확인한 뒤 정할 것** — 랙 콜라이더가 없어(인스턴스 참조)
  물리로는 안 잡히고 영상에서만 보인다.

[태블릿 제외] 요청대로 넣지 않는다.
"""
import argparse
import os
import sys

from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics

WHEEL_R = 0.081          # build_amr_scene_v2.py 와 같은 값. 로봇 prim 의 z

# --- 설계 치수 (바닥 기준 [m]) --------------------------------------------
BASE_REAR = 1.110        # 구동축 -> 베이스 뒷면 (차체 1.030 + 80 mm)
FRONT = 0.390            # 구동축 -> 앞면. ★ pitch 하한이 여기서 나온다
WIDTH = 0.800            # 전폭
BASE_Z0, BASE_Z1 = 0.220, 0.250      # 베이스 플레이트 (AMR 상면 위 30 mm)
DECK_Z0, DECK_Z1 = 0.920, 0.950      # 중단 데크
TOP_Z = 1.650                        # 총 높이
POST = 0.040                         # 포스트 단면 40 x 40
RAIL = 0.040                         # 상단 레일
BACKSTOP = 0.020                     # 후면 낙하방지판 두께


def _box(stage, path, x0, x1, y0, y1, z0, z1):
    """축정렬 박스 하나. Cube 는 한 변 2 이므로 scale 로 만든다."""
    c = UsdGeom.Cube.Define(stage, path)
    c.GetSizeAttr().Set(2.0)
    xf = UsdGeom.Xformable(c)
    xf.AddTranslateOp().Set(Gf.Vec3d((x0 + x1) / 2, (y0 + y1) / 2,
                                     (z0 + z1) / 2 - WHEEL_R))
    xf.AddScaleOp().Set(Gf.Vec3f((x1 - x0) / 2, (y1 - y0) / 2, (z1 - z0) / 2))
    return c


def build(out, top_rear, collide):
    stage = Usd.Stage.CreateNew(out)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    root = UsdGeom.Xform.Define(stage, "/AmrShelf")
    stage.SetDefaultPrim(root.GetPrim())

    hw = WIDTH / 2
    n = 0

    # 베이스 플레이트 — 1,500 mm 전체
    _box(stage, "/AmrShelf/base", -BASE_REAR, FRONT, -hw, hw, BASE_Z0, BASE_Z1)
    n += 1

    # 중단 데크 — 상부 풋프린트
    _box(stage, "/AmrShelf/deck", -top_rear, FRONT, -hw, hw, DECK_Z0, DECK_Z1)
    n += 1

    # 포스트 4개 — 상부 외형에서 20 mm 안쪽
    inset = 0.020
    for i, (px, py) in enumerate([(-top_rear + inset, -hw + inset),
                                  (-top_rear + inset, hw - inset - POST),
                                  (FRONT - inset - POST, -hw + inset),
                                  (FRONT - inset - POST, hw - inset - POST)]):
        _box(stage, f"/AmrShelf/post_{i}", px, px + POST, py, py + POST,
             BASE_Z1, TOP_Z)
        n += 1

    # 상단 레일 4개 — 둘레
    _box(stage, "/AmrShelf/rail_f", FRONT - RAIL, FRONT, -hw, hw, TOP_Z - RAIL, TOP_Z)
    _box(stage, "/AmrShelf/rail_b", -top_rear, -top_rear + RAIL, -hw, hw, TOP_Z - RAIL, TOP_Z)
    _box(stage, "/AmrShelf/rail_l", -top_rear, FRONT, -hw, -hw + RAIL, TOP_Z - RAIL, TOP_Z)
    _box(stage, "/AmrShelf/rail_r", -top_rear, FRONT, hw - RAIL, hw, TOP_Z - RAIL, TOP_Z)
    n += 4

    # 후면 낙하방지판
    _box(stage, "/AmrShelf/backstop", -top_rear, -top_rear + BACKSTOP,
         -hw, hw, BASE_Z1, TOP_Z)
    n += 1

    if collide:
        # ★ 부재별로 주지 않는다. 12개면 브로드페이즈 비용이 는다.
        #   상부 전체를 **단일 박스** 하나로 단순화한다.
        box = _box(stage, "/AmrShelf/collider", -top_rear, FRONT, -hw, hw,
                   BASE_Z1, TOP_Z)
        UsdGeom.Imageable(box).MakeInvisible()
        UsdPhysics.CollisionAPI.Apply(box.GetPrim())
        n += 1

    stage.GetRootLayer().Save()
    return n


def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)                      # t3_amr/
    ap.add_argument("--out", default=os.path.join(root, "robots", "shelf",
                                                  "amr_shelf.usd"))
    ap.add_argument("--top-rear", type=float, default=BASE_REAR,
                    help="상부 뒤 돌출 [m] (구동축 기준). 기본 1.110 = 안 깎음. "
                         "랙 데크를 피하려면 줄인다 (문서 제안 0.850)")
    ap.add_argument("--collide", action="store_true",
                    help="상부에 단일 박스 콜라이더를 붙인다. 기본은 **비주얼 전용** — "
                         "물리를 그대로 둬야 주행 지문(ms/step·체크포인트)이 유지된다")
    a = ap.parse_args()

    if not (0.0 < a.top_rear <= BASE_REAR):
        raise SystemExit(f"★ --top-rear 는 0 초과 {BASE_REAR} 이하: {a.top_rear}")

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    if os.path.exists(a.out):
        os.remove(a.out)                              # CreateNew 는 덮어쓰지 않는다
    n = build(a.out, a.top_rear, a.collide)

    print(f"[shelf] {a.out}")
    print(f"[shelf] 부재 {n}개 · 베이스 {(BASE_REAR + FRONT) * 1000:.0f} x "
          f"{WIDTH * 1000:.0f} mm · 상부 {(a.top_rear + FRONT) * 1000:.0f} mm · "
          f"총높이 {TOP_Z * 1000:.0f} mm")
    print(f"[shelf] 콜라이더 {'있음 (물리 포함)' if a.collide else '없음 (비주얼 전용)'}")
    if a.top_rear >= BASE_REAR:
        print("[shelf] ★ 상부를 안 깎았습니다. 랙 데크(밑면 1,005 mm) 밑을 지나는")
        print("[shelf]   구간에서 겹쳐 보이면 --top-rear 0.850 으로 다시 만드세요.")


if __name__ == "__main__":
    sys.exit(main())
