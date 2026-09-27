# -*- coding: utf-8 -*-
"""iw.hub 위에 얹는 3단 적재 선반 USD 를 만든다 (S15P21A106-196).

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

[태블릿] 2026-09-13 추가 (`--no-tablet` 으로 끈다).
상단 앞쪽에 HMI 패널을 단다. **기존 외형을 한 치도 안 넘도록** 넣는다 —
앞면 0.390 에서 5 mm 안쪽, 폭 ±0.125(전폭 ±0.400 안), 높이 1.585(총높이 1.650 안).
그래야 pitch 하한(hypot(front_len, width/2))도 랙 데크 간섭 판정도 그대로다.
빌드가 끝나면 실제 bbox 를 재서 넘으면 죽는다 — 눈으로 못 잡는 종류라서.
"""
import argparse
import math
import os
import sys

from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics, UsdShade

WHEEL_R = 0.081          # build_amr_scene_v2.py 와 같은 값. 로봇 prim 의 z

# --- 설계 치수 (바닥 기준 [m]) --------------------------------------------
BASE_REAR = 1.110        # 구동축 -> 베이스 뒷면 (차체 1.030 + 80 mm)
FRONT = 0.390            # 구동축 -> 앞면. ★ pitch 하한이 여기서 나온다
WIDTH = 0.800            # 전폭
BASE_Z0, BASE_Z1 = 0.220, 0.250      # 베이스 플레이트 (AMR 상면 위 30 mm)
TOP_Z = 1.650                        # 총 높이 ★ 단 수를 바꿔도 이 값은 유지한다
POST = 0.040                         # 포스트 단면 40 x 40
RAIL = 0.040                         # 상단 레일
BACKSTOP = 0.020                     # 후면 낙하방지판 두께

# --- 적재 단 ---------------------------------------------------------------
# ★ 3단이 **시스템이 이미 전제하는 값**이다 (2026-09-13 정정).
#   `3_FMS/sim_engine/kernel/core.py:37`
#       MAX_TOTES_PER_TRIP = 6   # 선반형 AMR 3단 x 2 토트 (-177)
#   토트 적재량 6이 "3단 x 2토트" 에서 나오는데 에셋만 2단이라 어긋나 있었다.
#   단 수를 바꿔도 **총높이 1,650 mm 는 유지**한다 — 랙 데크(밑면 1,005 mm)
#   간섭 판정과 pitch 하한이 전부 그 값을 기준으로 잡혀 있다.
TIERS = 3                            # 적재 단 수 (베이스 포함)
DECK_T = 0.030                       # 데크 두께. 베이스 플레이트와 같다

# --- 적재물 (골판지 상자) --------------------------------------------------
# ★ 단마다 **2개**. FMS `MAX_TOTES_PER_TRIP = 6` 이 「3단 x 2토트」에서 나오는데
#   (core.py:37) 에셋이 그걸 안 보여주고 있었다. 눈으로 보이게 한다.
#
#   ★★ **비주얼 전용이다.** 콜라이더도 질량도 안 붙인다 — `--collide` 는 상부
#     전체를 단일 박스로 덮으므로 상자가 물리에 새로 끼어들 자리가 없다.
#     주행 지문(ms/step·체크포인트)이 유지되어야 한다.
#
#   치수 근거 — 포스트(40 mm, 외형에서 20 mm 안쪽) 사이에 들어가야 한다.
#       쓸 수 있는 폭   0.800 - 2*(0.020+0.040) = 0.680
#       상자 2개        0.30 x 2 + 0.04(틈) = 0.640      양옆 20 mm 남음
#       단 유효높이     446.7 mm  ->  상자 320 mm 면 127 mm 뜬다
CARGO = True                         # `--no-cargo` 로 뺀다
CARGO_D = 0.600                      # 앞뒤 (유로 토트 600 mm)
CARGO_W = 0.300                      # 좌우
CARGO_H = 0.320                      # 높이
CARGO_GAP = 0.040                    # 두 상자 사이
CARGO_CLEAR = 0.060                  # 포스트 안쪽 여유 (inset 0.020 + POST 0.040)
MAT_CARGO = ((0.62, 0.47, 0.31), 0.85, 0.0)    # 골판지 — 거칠고 금속 아님

# --- 태블릿 (HMI 패널) -----------------------------------------------------
# 10인치급을 상단 앞쪽에 눕혀 단다. **외형을 넘지 않는 것이 유일한 제약이다.**
#   앞      FRONT(0.390) 에서 5 mm 안쪽까지만
#   폭      ±0.125  (전폭 ±0.400 안쪽)
#   높이    상단 레일(1.610~1.650) 밑
# 넘으면 pitch 하한이 올라가고 랙 간섭 판정을 다시 해야 한다.
# 치수는 갤럭시 탭 S9 11인치 실물 기준 (254.3 x 165.8 x 5.9 mm).
TAB_W, TAB_H, TAB_T = 0.2543, 0.1658, 0.0059   # 가로 · 세로 · 두께
TAB_BEZEL = 0.008                    # 베젤. 화면은 이만큼 안쪽
TAB_TILT = -15.0                     # Y축 회전 [deg]. 음수 = 윗면이 뒤로 눕는다
TAB_Z = 1.500                        # 화면 중심 높이 (바닥 기준)
TAB_CLEAR = 0.005                    # 앞면에서 띄울 여유
ARM_W, ARM_T = 0.070, 0.010          # 상단 레일에 매다는 브래킷 가로 · 두께

# 재질 — 선반 본체는 기본 회색 그대로 두고 **태블릿에만** 준다.
#   화면이 검게 안 나오면 태블릿으로 안 보인다. 기본 머티리얼은 전부 회색이다.
#   UsdPreviewSurface 는 Isaac RTX 가 그대로 읽는다.
MAT_BODY   = ((0.13, 0.14, 0.16), 0.35, 0.9)   # 그래파이트 알루미늄 (색, rough, metal)
MAT_SCREEN = ((0.02, 0.02, 0.025), 0.04, 0.0)  # 꺼진 화면 — 거의 검고 매우 매끈
MAT_ARM    = ((0.22, 0.23, 0.25), 0.5, 0.6)    # 마운트 브래킷


def deck_levels(tiers, z0=BASE_Z1, z1=TOP_Z, th=DECK_T):
    """베이스 윗면과 상단 사이에 (tiers-1)개의 데크를 **균등**하게 놓는다.

    반환 [(z0, z1), ...] — 바닥 기준. 각 단의 유효 높이가 모두 같아진다.
    3단: 유효 높이 446.7 mm x 3, 데크 2장.
    """
    n = tiers - 1
    if n < 0:
        raise ValueError(f"tiers 는 1 이상: {tiers}")
    clear = (z1 - z0 - n * th) / tiers
    if clear <= 0:
        raise SystemExit(f"★ {tiers}단은 총높이 {z1*1000:.0f} mm 에 안 들어갑니다.")
    out, z = [], z0
    for _ in range(n):
        z += clear
        out.append((z, z + th))
        z += th
    return out


def _box(stage, path, x0, x1, y0, y1, z0, z1):
    """축정렬 박스 하나. Cube 는 한 변 2 이므로 scale 로 만든다."""
    c = UsdGeom.Cube.Define(stage, path)
    c.GetSizeAttr().Set(2.0)
    xf = UsdGeom.Xformable(c)
    xf.AddTranslateOp().Set(Gf.Vec3d((x0 + x1) / 2, (y0 + y1) / 2,
                                     (z0 + z1) / 2 - WHEEL_R))
    xf.AddScaleOp().Set(Gf.Vec3f((x1 - x0) / 2, (y1 - y0) / 2, (z1 - z0) / 2))
    return c


def _panel(stage, path, cx, cy, cz, w, h, t, tilt_deg):
    """Y축으로 눕힌 평판. cx/cy/cz 는 **바닥 기준** 중심.

    Cube 로컬축: x=두께 y=가로 z=세로. 스케일 -> 회전 -> 이동 순으로 적용된다.
    """
    c = UsdGeom.Cube.Define(stage, path)
    c.GetSizeAttr().Set(2.0)
    xf = UsdGeom.Xformable(c)
    xf.AddTranslateOp().Set(Gf.Vec3d(cx, cy, cz - WHEEL_R))
    xf.AddRotateYOp().Set(tilt_deg)
    xf.AddScaleOp().Set(Gf.Vec3f(t / 2, w / 2, h / 2))
    return c


def _material(stage, path, spec):
    """UsdPreviewSurface 하나. spec = (색, roughness, metallic)."""
    color, rough, metal = spec
    mat = UsdShade.Material.Define(stage, path)
    sh = UsdShade.Shader.Define(stage, path + "/PBR")
    sh.CreateIdAttr("UsdPreviewSurface")
    sh.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
    sh.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(float(rough))
    sh.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(float(metal))
    mat.CreateSurfaceOutput().ConnectToSource(sh.ConnectableAPI(), "surface")
    return mat


def _bind(prim, mat):
    UsdShade.MaterialBindingAPI.Apply(prim.GetPrim())
    UsdShade.MaterialBindingAPI(prim.GetPrim()).Bind(mat)


def _tablet_cx(h=TAB_H, t=TAB_T, tilt=TAB_TILT):
    """눕힌 뒤에도 앞면이 FRONT-TAB_CLEAR 를 넘지 않는 중심 x."""
    r = math.radians(abs(tilt))
    hx = (t / 2) * math.cos(r) + (h / 2) * math.sin(r)    # 회전 후 x 반폭
    return FRONT - TAB_CLEAR - hx


def build(out, top_rear, collide, tiers=TIERS, tablet=True, cargo=CARGO):
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

    # 중단 데크 — 상부 풋프린트. tiers-1 장
    decks = deck_levels(tiers)
    for i, (z0, z1) in enumerate(decks):
        _box(stage, f"/AmrShelf/deck_{i}", -top_rear, FRONT, -hw, hw, z0, z1)
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

    # 적재물 — 단마다 상자 2개. **비주얼 전용** (위 CARGO 주석)
    if cargo:
        m_cargo = _material(stage, "/AmrShelf/Looks/Cargo", MAT_CARGO)
        # 적재면 = 베이스 윗면 + 각 데크 윗면. 데크 밑면/상단 레일이 천장이다.
        tops = [BASE_Z1] + [d[1] for d in decks]
        x0 = -top_rear + CARGO_CLEAR
        x1 = FRONT - CARGO_CLEAR
        cx = (x0 + x1) / 2                     # 쓸 수 있는 깊이의 가운데
        for t, z in enumerate(tops):
            for k, sy in enumerate((-1, 1)):
                cy = sy * (CARGO_W + CARGO_GAP) / 2
                b = _box(stage, f"/AmrShelf/cargo_{t}{'lr'[k]}",
                         cx - CARGO_D / 2, cx + CARGO_D / 2,
                         cy - CARGO_W / 2, cy + CARGO_W / 2,
                         z, z + CARGO_H)
                _bind(b.GetPrim(), m_cargo)
                n += 1

    # 태블릿 — 상단 레일에 매달린 HMI 패널 (갤럭시 탭 S9 11인치 치수)
    if tablet:
        m_body = _material(stage, "/AmrShelf/Looks/TabBody", MAT_BODY)
        m_scr = _material(stage, "/AmrShelf/Looks/TabScreen", MAT_SCREEN)
        m_arm = _material(stage, "/AmrShelf/Looks/TabArm", MAT_ARM)

        cx = _tablet_cx()
        r = math.radians(TAB_TILT)
        # 화면 법선 = 눕힌 판의 +x 방향. 화면을 본체보다 이만큼 앞으로 띄운다.
        off = TAB_T / 2 + 0.0004
        nx, nz = math.cos(r) * off, -math.sin(r) * off

        body = _panel(stage, "/AmrShelf/tablet_body", cx, 0.0, TAB_Z,
                      TAB_W, TAB_H, TAB_T, TAB_TILT)
        _bind(body, m_body)
        screen = _panel(stage, "/AmrShelf/tablet_screen", cx + nx, 0.0, TAB_Z + nz,
                        TAB_W - 2 * TAB_BEZEL, TAB_H - 2 * TAB_BEZEL, 0.0008, TAB_TILT)
        _bind(screen, m_scr)
        # 브래킷 — 상단 레일 밑면(TOP_Z-RAIL)에서 패널 윗변까지
        arm = _box(stage, "/AmrShelf/tablet_arm",
                   cx - ARM_T / 2, cx + ARM_T / 2, -ARM_W / 2, ARM_W / 2,
                   TAB_Z + TAB_H / 2 * math.cos(r), TOP_Z - RAIL)
        _bind(arm, m_arm)
        n += 3

    if collide:
        # ★ 부재별로 주지 않는다. 12개면 브로드페이즈 비용이 는다.
        #   상부 전체를 **단일 박스** 하나로 단순화한다.
        box = _box(stage, "/AmrShelf/collider", -top_rear, FRONT, -hw, hw,
                   BASE_Z1, TOP_Z)
        UsdGeom.Imageable(box).MakeInvisible()
        UsdPhysics.CollisionAPI.Apply(box.GetPrim())
        n += 1

    # ★ 외형 초과 검사 — 저작 실수가 조용히 pitch 하한을 올리는 것을 막는다.
    #   `hypot(front_len, width/2)` 가 격자 하한을 정하므로 **앞과 폭**이 특히
    #   중요하다. 눈으로는 절대 못 잡는다 (2026-09-13 태블릿 추가하며 넣음).
    stage.GetRootLayer().Save()
    bb = UsdGeom.BBoxCache(0, ["default"]).ComputeWorldBound(root.GetPrim())
    mn, mx = bb.ComputeAlignedBox().GetMin(), bb.ComputeAlignedBox().GetMax()
    lim = ((-top_rear, FRONT), (-WIDTH / 2, WIDTH / 2),
           (BASE_Z0 - WHEEL_R, TOP_Z - WHEEL_R))
    names = ("x(앞뒤)", "y(폭)", "z(높이)")
    bad = []
    for i, (lo, hi) in enumerate(lim):
        if mn[i] < lo - 1e-6 or mx[i] > hi + 1e-6:
            bad.append(f"{names[i]}  실제 [{mn[i]:+.4f}, {mx[i]:+.4f}]  "
                       f"허용 [{lo:+.4f}, {hi:+.4f}]")
    if bad:
        raise SystemExit("★ 부재가 외형을 넘습니다 — pitch 하한·랙 간섭을 다시 재야 합니다:\n  "
                         + "\n  ".join(bad))
    return n, decks, (mn, mx)


def main():
    ap = argparse.ArgumentParser()
    # ★ 이 파일은 `warehouse/scene/` 에 있다 — t3_amr 까지 **두 단계** 올라간다.
    #   한 단계만 올라가면 `warehouse/robots/shelf/` 에 쓰고, run_webrtc.sh 는
    #   `$W/robots/shelf/` 를 봐서 "가 없습니다" 로 죽는다 (2026-09-13 실측).
    here = os.path.dirname(os.path.abspath(__file__))     # warehouse/scene
    root = os.path.dirname(os.path.dirname(here))         # t3_amr/
    ap.add_argument("--out", default=os.path.join(root, "robots", "shelf",
                                                  "amr_shelf.usd"))
    ap.add_argument("--top-rear", type=float, default=BASE_REAR,
                    help="상부 뒤 돌출 [m] (구동축 기준). 기본 1.110 = 안 깎음. "
                         "랙 데크를 피하려면 줄인다 (문서 제안 0.850)")
    ap.add_argument("--tiers", type=int, default=TIERS,
                    help="적재 단 수 (베이스 포함). 기본 3 — FMS 의 "
                         "MAX_TOTES_PER_TRIP=6 이 '3단 x 2토트' 에서 나온다. "
                         "★ 총높이 1,650 mm 는 단 수와 무관하게 유지된다")
    ap.add_argument("--no-cargo", dest="cargo", action="store_false",
                    help="선반을 비운 채 만든다 (기본은 단마다 상자 2개 — "
                         "FMS MAX_TOTES_PER_TRIP=6 과 같은 모습). 비주얼 전용")
    ap.add_argument("--no-tablet", dest="tablet", action="store_false",
                    help="상단 앞쪽 HMI 태블릿을 빼고 만든다 (기본은 넣는다)")
    ap.add_argument("--collide", action="store_true",
                    help="상부에 단일 박스 콜라이더를 붙인다. 기본은 **비주얼 전용** — "
                         "물리를 그대로 둬야 주행 지문(ms/step·체크포인트)이 유지된다")
    a = ap.parse_args()

    if not (0.0 < a.top_rear <= BASE_REAR):
        raise SystemExit(f"★ --top-rear 는 0 초과 {BASE_REAR} 이하: {a.top_rear}")

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    if os.path.exists(a.out):
        os.remove(a.out)                              # CreateNew 는 덮어쓰지 않는다
    n, decks, (mn, mx) = build(a.out, a.top_rear, a.collide, a.tiers, a.tablet, a.cargo)

    print(f"[shelf] {a.out}")
    print(f"[shelf] 부재 {n}개 · 베이스 {(BASE_REAR + FRONT) * 1000:.0f} x "
          f"{WIDTH * 1000:.0f} mm · 상부 {(a.top_rear + FRONT) * 1000:.0f} mm · "
          f"총높이 {TOP_Z * 1000:.0f} mm")
    # 단 구성을 찍는다 — 눈으로 확인할 유일한 값이다
    tops = [BASE_Z1] + [d[1] for d in decks]
    bots = [d[0] for d in decks] + [TOP_Z]
    print(f"[shelf] {a.tiers}단 · 데크 {len(decks)}장")
    for i, (t, b) in enumerate(zip(tops, bots), 1):
        print(f"[shelf]   {i}단  바닥 {t*1000:7.1f} → 천장 {b*1000:7.1f} mm"
              f"   유효높이 {(b-t)*1000:.1f} mm")
    if a.tablet:
        print(f"[shelf] 태블릿 {TAB_W*1000:.0f} x {TAB_H*1000:.0f} mm · "
              f"중심 높이 {TAB_Z*1000:.0f} mm · 기울기 {abs(TAB_TILT):.0f}도")
    print(f"[shelf] 외형 실측  x [{mn[0]:+.3f}, {mx[0]:+.3f}]  "
          f"y [{mn[1]:+.3f}, {mx[1]:+.3f}]  z(로봇로컬) [{mn[2]:+.3f}, {mx[2]:+.3f}]")
    print(f"[shelf]   -> 앞 여유 {(FRONT - mx[0])*1000:+.1f} mm · "
          f"폭 여유 {(WIDTH/2 - mx[1])*1000:+.1f} mm · "
          f"높이 여유 {((TOP_Z - WHEEL_R) - mx[2])*1000:+.1f} mm")
    print(f"[shelf] 콜라이더 {'있음 (물리 포함)' if a.collide else '없음 (비주얼 전용)'}")
    if a.top_rear >= BASE_REAR:
        print("[shelf] ★ 상부를 안 깎았습니다. 랙 데크(밑면 1,005 mm) 밑을 지나는")
        print("[shelf]   구간에서 겹쳐 보이면 --top-rear 0.850 으로 다시 만드세요.")


if __name__ == "__main__":
    sys.exit(main())
