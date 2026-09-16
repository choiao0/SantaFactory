# -*- coding: utf-8 -*-
"""USD 의 **저작된** 바퀴 값을 찍는다 (S15P21A106-224).

왜
--
코드 상수의 출처가 주석 두 줄뿐이다 (`pibt_scene.py:135`).

    WHEEL_RADIUS = 0.08     # iw_hub.usd 조인트 저작값
    WHEEL_BASE = 0.5796     # localPos0 = ±0.28963

이게 맞는지 **원본에서 다시 읽는다.** 틀리면 `swivel_sweep` 의 접지비가 통째로
어긋나고, 그러면 「a6 이 미끄러졌다」는 결론이 흔들린다.

무엇을 찍나
-----------
    metersPerUnit          ★ 이게 1.0 이 아니면 아래 숫자가 전부 그만큼 다르다
    바퀴 조인트            localPos0 / localPos1 · 회전축 · 부모/자식
    바퀴 지오메트리        반지름 (Cylinder) 또는 bbox 로 추정
    prim 스케일            xformOp:scale — 걸려 있으면 저작값 != 실제
    ★ 물리 재질            staticFriction · dynamicFriction · 무엇에 묶였나
    ★ 질량                 physics:mass / density

마지막 둘은 2026-09-16 에 붙였다. Isaac 공식 트러블슈팅이 「바퀴 마찰이 너무
적으면 미끄러짐이 생긴다」고 적고 있고, MIR100 이 90도 명령에 10도만 돈 사례가
**PhysicsMaterial 이 아예 없던** 경우였다. 우리 a6 접지 상실(1/89)을 볼 때
제일 먼저 확인할 자리다.

무대(`$STAGE/pibt12.usd`)를 주면 **스폰된 로봇 12대를 각각** 본다. 로봇 사이에
차이가 있는지가 그때 보인다. 에셋(`$ROBOT`)을 주면 원본 하나만 본다.

쓰는 법
-------
    source paths.sh
    python tools/usd_wheels.py $ROBOT
    python tools/usd_wheels.py $STAGE/pibt12.usd          # 스폰된 12대 비교

`pxr` 이 없으면 Isaac 파이썬으로 돌린다:
    isaacsim isaacsim.exp.full --no-window --exec "<t3_amr>/tools/usd_wheels.py <파일>"
"""
import os
import sys

try:
    from pxr import Usd, UsdGeom, UsdPhysics, Gf         # noqa: F401
except ImportError:
    raise SystemExit(
        "★ pxr(USD) 를 못 불러왔습니다.\n"
        "  이 도구는 USD 라이브러리가 필요합니다. Isaac 파이썬으로 돌리세요:\n"
        "    isaacsim isaacsim.exp.full --no-window \\\n"
        "      --exec \"$W/tools/usd_wheels.py <usd 파일>\"\n"
        "  (venv 에 usd-core 가 있으면 그냥 돌아갑니다: pip install usd-core)")

KEYS = ("wheel", "caster", "swivel")
# 스케일을 물을 계통. 무대/원본에 따라 루트가 달라 **경로 조각**으로 본다.
PART_KEYS = ("wheel", "caster", "swivel", "chassis")


def fmt(v):
    try:
        return "(" + ", ".join(f"{float(c):+.5f}" for c in v) + ")"
    except TypeError:
        return str(v)


def load_split(stage, mpu):
    """★ 하중이 구동축과 캐스터에 어떻게 갈리나 — **도구가 계산한다.**

    손으로 더하다 두 번 틀렸다 (2026-09-16). 그리고 무대에는 원본 에셋에 없는
    것이 붙는다 — **적재 선반**(`chassis/shelf`)이 그렇다. 섀시 밑에 달리므로
    무게중심을 뒤로 끌 수 있고, 캐스터가 무마찰이라 그 하중은 **접지력이 되지
    않는다.** 그래서 선반 유무로 구동축 하중이 달라진다.

    섀시 좌표에서 잰다 — 조인트 `localPos0` 가 섀시 기준이고, 구동축이 섀시
    원점(x=0), 캐스터가 x=-0.65 다. 로봇이 무대에서 돌아가 있어도 상관없다.
    """
    root = None
    for p in stage.Traverse():
        if p.GetName() == "chassis":
            root = p
            break
    if root is None:
        print(f"\n── 하중 배분 ──\n   `chassis` prim 을 못 찾았다")
        return
    print(f"\n── ★ 하중 배분 ({root.GetPath().pathString}) ──")

    inv = UsdGeom.Xformable(root).ComputeLocalToWorldTransform(
        Usd.TimeCode.Default()).GetInverse()
    items = []
    for p in Usd.PrimRange(root):
        a = p.GetAttribute("physics:mass")
        m = float(a.Get()) if a and a.Get() else 0.0
        if m <= 0.0:
            continue
        xf = UsdGeom.Xformable(p).ComputeLocalToWorldTransform(
            Usd.TimeCode.Default()) * inv
        pos = xf.ExtractTranslation()
        ca = p.GetAttribute("physics:centerOfMass")
        if ca and ca.IsAuthored():
            c = ca.Get()
            pos = pos + xf.TransformDir(Gf.Vec3d(*[float(v) for v in c]))
        items.append((p.GetName(), m, float(pos[0]) * mpu))

    if not items:
        print(f"   `physics:mass` 를 가진 강체가 없다")
        return
    tot = sum(m for _n, m, _x in items)
    cx = sum(m * x for _n, m, x in items) / tot
    print(f"   {'강체':<22}{'질량 kg':>9}{'섀시 x (m)':>13}")
    for n, m, x in sorted(items, key=lambda r: -r[1]):
        mark = "   ← 원본 에셋에 없다" if "shelf" in n.lower() or "tab" in n.lower() else ""
        print(f"   {n:<22}{m:>9.2f}{x:>13.3f}{mark}")
    print(f"   {'합':<22}{tot:>9.2f}{cx:>13.3f}   ← 전체 무게중심")

    # 구동축 x=0, 캐스터 x=CASTER_X. 지렛대로 갈린다.
    cx_caster = float(os.environ.get("CASTER_X", "-0.65"))
    if abs(cx_caster) < 1e-9:
        return
    f_caster = max(0.0, min(1.0, cx / cx_caster))
    print(f"\n   구동축 x=0 · 캐스터 x={cx_caster}")
    print(f"   캐스터 하중 {tot * f_caster:6.2f} kg ({f_caster * 100:.1f} %)"
          f"   ← 마찰 0 이라 **접지력이 안 된다**")
    print(f"   구동축 하중 {tot * (1 - f_caster):6.2f} kg "
          f"({(1 - f_caster) * 100:.1f} %)")
    mu = float(os.environ.get("MU", "0.9"))
    print(f"   구동 바퀴 접지력 ~ {mu} x {tot * (1 - f_caster):.1f} x 9.81 = "
          f"{mu * tot * (1 - f_caster) * 9.81:.0f} N   (mu={mu})")
    if f_caster > 0.3:
        print(f"   ★ 무게가 뒤로 쏠려 있다 — 캐스터가 무마찰이면 그만큼")
        print(f"     접지력을 잃는다. 선반·적재물이 원인인지 위 표에서 볼 것.")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args:
        raise SystemExit(__doc__)
    path = args[0]
    # 없는 경로를 그냥 넘기면 pxr 이 역추적을 뱉어 원인이 안 보인다.
    # `$WAREHOUSE` 같은 빈 변수를 쓰면 `/robots/...` 가 되는데, 그때
    # 「셸 변수가 비었다」가 바로 보여야 한다.
    if not path or not os.path.isfile(path):
        raise SystemExit(
            f"★ 파일이 없습니다: {path!r}\n"
            f"  셸 변수가 비지 않았는지 보세요. 에셋은 `$ROBOT` 입니다:\n"
            f"    python tools/usd_wheels.py $ROBOT\n"
            f"    python tools/usd_wheels.py $STAGE/pibt12.usd")
    stage = Usd.Stage.Open(path)
    if stage is None:
        raise SystemExit(f"★ 열 수 없습니다: {path}")

    mpu = UsdGeom.GetStageMetersPerUnit(stage)
    print(f"[usd_wheels] {os.path.basename(path)}")
    print(f"   metersPerUnit {mpu}"
          + ("" if abs(mpu - 1.0) < 1e-9 else
             "   ★ 1.0 이 아니다 — 아래 길이에 이걸 곱해야 미터다"))
    print(f"   upAxis {UsdGeom.GetStageUpAxis(stage)}")

    # ── 스케일이 걸린 prim ────────────────────────────────────────────────
    #   ★ 로봇 아래만 따로 센다. 창고 바닥·조명에 스케일이 걸린 것은 흔하고
    #     우리 계산과 무관하다. 물어야 할 것은 **로봇에 걸렸나** 하나다.
    scaled, robot_scaled = [], []
    for p in stage.Traverse():
        if not p.IsA(UsdGeom.Xformable):
            continue
        for op in UsdGeom.Xformable(p).GetOrderedXformOps():
            if "scale" not in op.GetOpName():
                continue
            s = op.Get()
            if s is None or all(abs(float(c) - 1.0) <= 1e-6 for c in s):
                continue
            row = (p.GetPath().pathString, tuple(float(c) for c in s))
            scaled.append(row)
            # ★ **경로**로 판단한다. 무대냐 원본 에셋이냐에 따라 루트가
            #   `/World/Robots/amr_N` 이기도 `/iw_hub` 이기도 해서, 루트
            #   이름으로 거르면 원본에서 「없다」고 잘못 말한다 (실제로 그랬다).
            #   물어야 할 것은 「바퀴·섀시 계통에 스케일이 걸렸나」 하나다.
            if any(k in row[0].lower() for k in PART_KEYS):
                robot_scaled.append(row)
    print(f"\n── 스케일이 1 이 아닌 prim {len(scaled)}개 "
          f"(그중 바퀴·섀시 계통 {len(robot_scaled)}개) ──")
    if robot_scaled:
        print(f"   ★ 걸려 있다 — 아래 메시의 치수는 저작값 x 스케일이다")
        for pth, s in robot_scaled[:20]:
            print(f"   {s}  {pth}")
        print(f"   ※ 조인트 `localPos` 는 **부모 강체 좌표**라 자식 메시의")
        print(f"     스케일에 영향받지 않는다 — wheel_base 는 그대로 유효하다.")
    else:
        print(f"   바퀴·섀시 계통에는 없다")
        for pth, s in scaled[:4]:
            print(f"   (참고) {s}  {pth}")

    # ── 바퀴·캐스터 조인트 ───────────────────────────────────────────────
    print(f"\n── 조인트 (이름에 {KEYS} 포함) ──")
    n = 0
    for p in stage.Traverse():
        nm = p.GetName().lower()
        if not any(k in nm for k in KEYS):
            continue
        if not p.IsA(UsdPhysics.Joint):
            continue
        n += 1
        j = UsdPhysics.Joint(p)
        p0 = j.GetLocalPos0Attr().Get()
        p1 = j.GetLocalPos1Attr().Get()
        b0 = j.GetBody0Rel().GetTargets()
        b1 = j.GetBody1Rel().GetTargets()
        axis = None
        if p.HasAttribute("physics:axis"):
            axis = p.GetAttribute("physics:axis").Get()
        print(f"   {p.GetName():<22} axis={axis}")
        print(f"      localPos0 {fmt(p0)}   localPos1 {fmt(p1)}")
        print(f"      body0 {[str(x) for x in b0]}")
        print(f"      body1 {[str(x) for x in b1]}")
        if p0 is not None:
            print(f"      localPos0 를 미터로: {fmt([float(c) * mpu for c in p0])}")
    if not n:
        print("   없음 — 이름 규칙이 다르거나 참조가 안 풀렸다")

    # ── 바퀴 지오메트리 반지름 ───────────────────────────────────────────
    print(f"\n── 바퀴 지오메트리 ──")
    cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(),
                              [UsdGeom.Tokens.default_, UsdGeom.Tokens.render])
    # ★ **이름별로 묶는다.** 로봇이 12대면 같은 메시가 12번 나와서, 앞에서
    #   끊으면 이름 두어 개만 보이고 **바깥 타이어 메시가 있는지 안 보인다.**
    #   실제로 그래서 `STR_Inner_*`(안쪽 림) 만 보고 반지름을 잘못 읽을 뻔했다.
    seen = {}
    for p in stage.Traverse():
        nm = p.GetName()
        pth = p.GetPath().pathString
        # ★ **경로**로 거른다. 프림 이름이 `Cylinder` 라서 이름으로 거르면
        #   정작 구동 바퀴(`/iw_hub/left_wheel/Cylinder`)를 놓치고 캐스터의
        #   `STR_Inner_*` 만 잡힌다 — 실제로 그렇게 놓쳤다.
        if "wheel" not in pth.lower() or not p.IsA(UsdGeom.Gprim):
            continue
        key = f"{nm}  <{pth.split('/')[-2] if '/' in pth else ''}>"
        if key in seen:
            seen[key][0] += 1
            continue
        if p.IsA(UsdGeom.Cylinder):
            c = UsdGeom.Cylinder(p)
            r = c.GetRadiusAttr().Get()
            # 부모 스케일이 걸려 있으면 저작 반지름 != 실제 반지름이다.
            xf = UsdGeom.Xformable(p).ComputeLocalToWorldTransform(
                Usd.TimeCode.Default())
            sc = [Gf.Vec3d(xf.GetRow3(i)).GetLength() for i in range(3)]
            desc = (f"Cylinder radius={r}  height={c.GetHeightAttr().Get()}"
                    f"  axis={c.GetAxisAttr().Get()}\n"
                    f"      누적 스케일 ({sc[0]:.4f}, {sc[1]:.4f}, {sc[2]:.4f})"
                    f"  -> ★ 실제 반지름 {float(r) * max(sc[0], sc[1]) * mpu:.5f} m")
            seen[key] = [1, desc, pth]
            continue
        rng = cache.ComputeWorldBound(p).ComputeAlignedRange()
        if rng.IsEmpty():
            continue
        sz = rng.GetSize()
        d = sorted(float(c) for c in sz)
        seen[key] = [1, f"bbox {fmt(sz)}  -> 반지름 추정 {d[-1] / 2.0 * mpu:.5f} m",
                     pth]
    if not seen:
        print("   없음")
    else:
        print(f"   서로 다른 이름 {len(seen)}개 (같은 이름은 로봇 수만큼 반복된다)")
        for nm, (cnt, desc, pth) in sorted(seen.items()):
            print(f"   {nm:<24} x{cnt:<3} {desc}")
            print(f"      {pth}")
        print(f"   ※ 이름에 Inner/Rim 이 들어간 것은 안쪽 부품일 수 있다 —")
        print(f"     가장 **큰** 반지름이 접지면이다.")

    # ── ★ 물리 재질과 질량 ───────────────────────────────────────────────
    #   Isaac 공식 트러블슈팅이 「마찰이 너무 적으면 바퀴 미끄러짐이 생긴다」고
    #   적고 있고, MIR100 이 90도 명령에 10도만 돈 사례는 PhysicsMaterial 이
    #   **아예 없던** 경우였다. 없으면 기본값으로 도는데 그 값이 낮으면
    #   경계에서 미끄러진다. 질량도 같은 갈래다 — 가벼우면 접지가 준다.
    print(f"\n── 물리 재질 (physics:*Friction 을 가진 prim) ──")
    mats = []
    for p in stage.Traverse():
        vals = {}
        for a in p.GetAttributes():
            n = a.GetName()
            if n.startswith("physics:") and (
                    "Friction" in n or "restitution" in n.lower()):
                vals[n.split(":")[-1]] = a.Get()
        if vals:
            mats.append((p.GetPath().pathString, vals))
    if not mats:
        print(f"   ☠ **하나도 없다** — 스테이지에 물리 재질이 안 잡혀 있다.")
        print(f"     Isaac 기본값으로 도는데, 그게 낮으면 회전에서 미끄러진다.")
        print(f"     (MIR100 이 90도 명령에 10도만 돈 사례가 이 상태였다.)")
    else:
        for pth, v in mats[:20]:
            print(f"   {v}")
            print(f"      {pth}")

    print(f"\n── 바퀴·섀시가 어느 재질에 묶였나 ──")
    try:
        from pxr import UsdShade
        bound = {}
        for p in stage.Traverse():
            pth = p.GetPath().pathString
            if not any(k in pth.lower() for k in PART_KEYS):
                continue
            try:
                m, _rel = UsdShade.MaterialBindingAPI(p).ComputeBoundMaterial(
                    materialPurpose="physics")
            except Exception:
                continue
            if m and m.GetPrim().IsValid():
                key = m.GetPrim().GetPath().pathString
                bound.setdefault(key, []).append(pth)
        if bound:
            for mat, users in list(bound.items())[:10]:
                print(f"   {mat}")
                for u in users[:3]:
                    print(f"      <- {u}")
                if len(users) > 3:
                    print(f"      <- … 외 {len(users) - 3}개")
        else:
            print(f"   ☠ **묶인 것이 없다** — 바퀴에 물리 재질이 안 붙어 있다.")
    except ImportError:
        print(f"   (UsdShade 를 못 불러와 확인 못 함)")

    load_split(stage, mpu)

    print(f"\n── 질량 (개별) ──")
    n_mass = 0
    for p in stage.Traverse():
        pth = p.GetPath().pathString
        if not any(k in pth.lower() for k in PART_KEYS):
            continue
        def at(name):
            return p.GetAttribute(name).Get() if p.HasAttribute(name) else None
        m, d = at("physics:mass"), at("physics:density")
        if m is None and d is None:
            continue
        n_mass += 1
        if n_mass > int(os.environ.get("MASS_MAX", "40")):
            continue
        # ★ 무게중심이 하중 배분을 정한다. 이 로봇은 구동축이 **앞**이고 차체가
        #   뒤로 1.11 m 매달린 구조라, 무게가 뒤로 쏠리면 그 하중이 **마찰 0인
        #   캐스터**로 가고 구동 바퀴의 접지력이 그만큼 준다. 기하 중심으로
        #   가정하면 안 되는 값이라 저작값을 그대로 찍는다.
        print(f"   mass={m}  density={d}   {pth}")
        # ★ `(0,0,0)` 은 **저작된 값**일 수도 스키마 기본값일 수도 있다.
        #   둘은 뜻이 정반대다 — 이 로봇은 섀시 원점이 구동축 중점이라
        #   (`localPos0` 가 (0, ±0.28963, 0)), 저작된 (0,0,0) 이면 무게가
        #   **전부 구동축에** 실리고, 미저작이면 PhysX 가 지오메트리에서
        #   계산해 **뒤로 1.11 m 매달린 차체 쪽으로 쏠린다.**
        #   `Get()` 만으로는 못 가른다. `IsAuthored()` 로 본다.
        ca = p.GetAttribute("physics:centerOfMass")
        if ca and ca.IsAuthored():
            print(f"      centerOfMass {fmt(ca.Get())}   ★ **저작됨**")
        elif ca:
            print(f"      centerOfMass {fmt(ca.Get())}   "
                  f"(미저작 — PhysX 가 지오메트리에서 계산한다)")
        else:
            print(f"      centerOfMass 속성 없음 — 지오메트리에서 계산된다")
        ia = p.GetAttribute("physics:diagonalInertia")
        if ia and ia.IsAuthored():
            print(f"      diagonalInertia {fmt(ia.Get())}   ★ 저작됨")
    if not n_mass:
        print(f"   바퀴·섀시 계통에 `physics:mass`/`density` 가 없다 "
              f"— 지오메트리에서 추정된다")

    print(f"\n   읽는 법")
    print(f"    · 재질이 **없으면** 그것부터다. 있으면 `staticFriction` ·")
    print(f"      `dynamicFriction` 값을 본다 — 낮으면 회전에서 미끄러진다.")
    print(f"    · 마찰은 **쌍의 성질**이다. 바퀴만 보지 말고 바닥")
    print(f"      (`/World/Warehouse/ground`) 쪽도 같이 봐야 한다.")
    print(f"    · ★ 캐스터 마찰이 0 이면 **접지력 전부가 구동 바퀴에만** 있다.")
    print(f"      그때는 무게중심 위치가 바로 접지력이다 — 뒤로 쏠릴수록")
    print(f"      구동축 하중이 줄어 회전에서 미끄러지기 쉬워진다.")
    print(f"    · ★ `centerOfMass` 는 **저작 여부가 값보다 중요하다.** 이 로봇은")
    print(f"      섀시 원점이 구동축 중점이라(`localPos0` = (0, ±0.28963, 0)),")
    print(f"      저작된 (0,0,0) = 무게가 전부 구동축 · 미저작 = 뒤로 쏠림이다.")
    print(f"    · `localPos0` 두 바퀴의 **가로 성분 차이**가 wheel_base 다.")
    print(f"      코드는 0.5796 (= 2 x 0.28963) 을 쓴다.")
    print(f"    · 반지름은 코드가 0.08 을 쓴다.")
    print(f"    · 스케일이나 metersPerUnit 이 1 이 아니면 저작값과 실제가")
    print(f"      다르다 — 그때는 `tools/wheel_calib.py` 의 역산값을 믿는다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
