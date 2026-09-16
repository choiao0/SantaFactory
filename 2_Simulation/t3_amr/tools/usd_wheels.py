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

무대(`$STAGE/pibt12.usd`)를 주면 **스폰된 로봇 12대를 각각** 본다. 로봇 사이에
차이가 있는지가 그때 보인다. 에셋(`$ROBOT`)을 주면 원본 하나만 본다.

쓰는 법
-------
    source paths.sh
    python tools/usd_wheels.py $WAREHOUSE/robots/iwhub/iw_hub.usd
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


def fmt(v):
    try:
        return "(" + ", ".join(f"{float(c):+.5f}" for c in v) + ")"
    except TypeError:
        return str(v)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args:
        raise SystemExit(__doc__)
    path = args[0]
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
    scaled = []
    for p in stage.Traverse():
        if not p.IsA(UsdGeom.Xformable):
            continue
        for op in UsdGeom.Xformable(p).GetOrderedXformOps():
            if "scale" in op.GetOpName():
                s = op.Get()
                if s is not None and any(abs(float(c) - 1.0) > 1e-6 for c in s):
                    scaled.append((p.GetPath().pathString, tuple(float(c) for c in s)))
    print(f"\n── 스케일이 1 이 아닌 prim {len(scaled)}개 ──")
    for pth, s in scaled[:12]:
        print(f"   {s}  {pth}")
    if not scaled:
        print("   없음 — 저작값이 곧 실제값이다")

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
    m = 0
    for p in stage.Traverse():
        nm = p.GetName().lower()
        if "wheel" not in nm or not p.IsA(UsdGeom.Gprim):
            continue
        m += 1
        if p.IsA(UsdGeom.Cylinder):
            c = UsdGeom.Cylinder(p)
            print(f"   {p.GetName():<22} Cylinder radius={c.GetRadiusAttr().Get()}"
                  f"  height={c.GetHeightAttr().Get()}  axis={c.GetAxisAttr().Get()}")
            continue
        rng = cache.ComputeWorldBound(p).ComputeAlignedRange()
        if rng.IsEmpty():
            continue
        sz = rng.GetSize()
        d = sorted(float(c) for c in sz)
        print(f"   {p.GetName():<22} bbox {fmt(sz)}"
              f"  -> 반지름 추정 {d[-1] / 2.0 * mpu:.5f} m")
        if m >= 12:
            print("   ... (12개에서 끊는다)")
            break
    if not m:
        print("   없음")

    print(f"\n   읽는 법")
    print(f"    · `localPos0` 두 바퀴의 **가로 성분 차이**가 wheel_base 다.")
    print(f"      코드는 0.5796 (= 2 x 0.28963) 을 쓴다.")
    print(f"    · 반지름은 코드가 0.08 을 쓴다.")
    print(f"    · 스케일이나 metersPerUnit 이 1 이 아니면 저작값과 실제가")
    print(f"      다르다 — 그때는 `tools/wheel_calib.py` 의 역산값을 믿는다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
