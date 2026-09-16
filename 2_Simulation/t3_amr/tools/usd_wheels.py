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
# 스폰된 로봇이 사는 경로. 창고 쪽 스케일과 갈라 보려고 쓴다.
ROBOT_ROOT = os.environ.get("ROBOT_ROOT", "/World/Robots")


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
            if ROBOT_ROOT in row[0]:
                robot_scaled.append(row)
    print(f"\n── 스케일이 1 이 아닌 prim {len(scaled)}개 "
          f"(그중 {ROBOT_ROOT} 아래 {len(robot_scaled)}개) ──")
    if robot_scaled:
        print(f"   ★ 로봇에 스케일이 걸려 있다 — 저작값 != 실제값이다")
        for pth, s in robot_scaled[:20]:
            print(f"   {s}  {pth}")
    else:
        print(f"   ★ **로봇 아래에는 없다** — 저작값이 곧 실제값이다")
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
        if "wheel" not in nm.lower() or not p.IsA(UsdGeom.Gprim):
            continue
        if nm in seen:
            seen[nm][0] += 1
            continue
        if p.IsA(UsdGeom.Cylinder):
            c = UsdGeom.Cylinder(p)
            desc = (f"Cylinder radius={c.GetRadiusAttr().Get()}"
                    f"  height={c.GetHeightAttr().Get()}"
                    f"  axis={c.GetAxisAttr().Get()}")
            seen[nm] = [1, desc, p.GetPath().pathString]
            continue
        rng = cache.ComputeWorldBound(p).ComputeAlignedRange()
        if rng.IsEmpty():
            continue
        sz = rng.GetSize()
        d = sorted(float(c) for c in sz)
        seen[nm] = [1, f"bbox {fmt(sz)}  -> 반지름 추정 {d[-1] / 2.0 * mpu:.5f} m",
                    p.GetPath().pathString]
    if not seen:
        print("   없음")
    else:
        print(f"   서로 다른 이름 {len(seen)}개 (같은 이름은 로봇 수만큼 반복된다)")
        for nm, (cnt, desc, pth) in sorted(seen.items()):
            print(f"   {nm:<24} x{cnt:<3} {desc}")
            print(f"      {pth}")
        print(f"   ※ 이름에 Inner/Rim 이 들어간 것은 안쪽 부품일 수 있다 —")
        print(f"     가장 **큰** 반지름이 접지면이다.")

    print(f"\n   읽는 법")
    print(f"    · `localPos0` 두 바퀴의 **가로 성분 차이**가 wheel_base 다.")
    print(f"      코드는 0.5796 (= 2 x 0.28963) 을 쓴다.")
    print(f"    · 반지름은 코드가 0.08 을 쓴다.")
    print(f"    · 스케일이나 metersPerUnit 이 1 이 아니면 저작값과 실제가")
    print(f"      다르다 — 그때는 `tools/wheel_calib.py` 의 역산값을 믿는다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
