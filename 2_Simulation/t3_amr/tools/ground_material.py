# -*- coding: utf-8 -*-
"""바닥 마찰이 **실제로 접촉에 들어가나** (S15P21A106-240).

왜 필요한가
-----------
`GROUND_FRICTION` 을 0.9 · 0.3 · 0.01 로 바꿔 네 판을 돌렸는데 결과가 거의
안 움직였다. 그러면 갈래가 셋인데 **로그가 「붙였다」고만 말해서** 어느 것인지
못 갈랐다.

    (가) 재질을 안 묶었다 / 엉뚱한 prim 에 묶었다
    (나) 묶은 prim 이 접촉면이 아니다 (콜리전이 꺼져 있다든가)
    (다) 묶였고 접촉면도 맞는데 **결합 규칙**이 무시한다
         frictionCombineMode = max 이면 상대(바퀴 0.9)가 이겨서 바닥 값이
         무슨 값이든 결과가 같다 — 90배를 바꿔도 비트 동일이 된다

셋은 고치는 데가 전혀 다르다. 이 도구가 셋을 가른다.

읽는 법
-------
    바닥 콜라이더가 하나도 없다        -> (나). 로봇이 딴 것을 밟는다
    콜라이더는 있는데 바인딩이 없다     -> (가). 만들기만 하고 안 묶었다
    바인딩도 있는데 combineMode=max    -> (다). ★ 바닥 값은 영영 안 쓰인다

쓰는 법
-------
    source paths.sh
    python tools/ground_material.py $STAGE/pibt12.usd
"""
import os
import sys

try:
    from pxr import Usd, UsdGeom, UsdPhysics, UsdShade      # noqa: F401
except ImportError:
    sys.exit("★ pxr 이 없습니다. Isaac 파이썬으로 돌리십시오.")

# 바닥일 법한 prim. 이름이 아니라 **z 높이와 넓이**로도 거른다 (아래 참조).
NAME_HINT = ("ground", "floor", "plane")


def frictions(prim):
    """이 prim 이 물리 재질이면 (static, dynamic, combineMode)."""
    if not prim or not prim.IsValid():
        return None
    api = UsdPhysics.MaterialAPI(prim)
    s = api.GetStaticFrictionAttr().Get() if api else None
    d = api.GetDynamicFrictionAttr().Get() if api else None
    if s is None and d is None:
        return None
    cm = None
    for n in ("physxMaterial:frictionCombineMode", "physics:frictionCombineMode"):
        a = prim.GetAttribute(n)
        if a and a.Get() is not None:
            cm = a.Get()
            break
    return (s, d, cm)


def bound_physics(prim):
    try:
        m = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial("physics")[0]
        return m.GetPrim() if m else None
    except Exception:
        return None


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    usd = args[0] if args else os.path.join(os.environ.get("STAGE", ""),
                                            "pibt12.usd")
    if not os.path.isfile(usd):
        sys.exit(f"★ 무대를 못 찾습니다: {usd!r}  ($STAGE/pibt12.usd)")
    stage = Usd.Stage.Open(usd, Usd.Stage.LoadAll)
    print(f"[ground_material] {os.path.basename(usd)}")

    # ── 1. 물리 재질이 어디에 있나 ───────────────────────────────────────
    print(f"\n── 1. 물리 재질 prim ──")
    mats = {}
    for p in stage.Traverse():
        f = frictions(p)
        if f:
            mats[str(p.GetPath())] = f
            print(f"   {p.GetPath()}   정적 {f[0]} · 동적 {f[1]}"
                  f" · combineMode {f[2] if f[2] is not None else '(기본)'}")
    if not mats:
        print(f"   없다 — 어느 prim 에도 physics:*Friction 이 없다")

    # ── 2. ★ 콜라이더가 **켜져** 있고 무엇에 묶였나 ──────────────────────
    #    `HasAPI` 만 보면 안 된다. `collisionEnabled=False` 인 prim 도 목록에
    #    남는다 — `build_amr_scene_v2.py` 가 `/World/Warehouse/ground` 를
    #    일부러 끈다 (1251:1 비균일 스케일에 로봇이 파묻혔다).
    print(f"\n── 2. 바닥 후보 콜라이더 ──")
    print(f"   {'prim':<44}{'콜리전':>8}  묶인 물리 재질")
    rows, any_on = [], False
    for p in stage.Traverse():
        path = str(p.GetPath())
        if not p.HasAPI(UsdPhysics.CollisionAPI):
            continue
        if not any(h in path.lower() for h in NAME_HINT):
            continue
        en = UsdPhysics.CollisionAPI(p).GetCollisionEnabledAttr().Get()
        en = True if en is None else bool(en)     # 없으면 기본 켬
        any_on |= en
        m = bound_physics(p)
        rows.append((path, en, str(m.GetPath()) if m else None))
    for path, en, m in rows:
        print(f"   {path:<44}{'켜짐' if en else '**꺼짐**':>8}  {m or '(없음)'}")
    if not rows:
        print(f"   이름에 {NAME_HINT} 가 든 콜라이더가 없다")

    # ── 3. 판정 ──────────────────────────────────────────────────────────
    print(f"\n── 3. 판정 ──")
    live = [(p, m) for p, en, m in rows if en]
    if not live:
        print(f"   ☠ (나) 켜진 바닥 콜라이더가 없다 — 로봇은 **딴 것**을 밟는다")
        print(f"     무대에서 바퀴 아래 z~0 에 무엇이 있는지 찾아야 한다")
    elif not any(m for _p, m in live):
        print(f"   ☠ (가) 켜진 바닥에 물리 재질이 **안 묶였다**")
        print(f"     재질을 만들기만 하고 바인딩을 빠뜨린 것이다")
    else:
        for p, m in live:
            if not m:
                continue
            f = mats.get(m)
            cm = (f[2] if f else None)
            print(f"   ★ {p}\n     -> {m}  정적 {f[0] if f else '?'}"
                  f" · combineMode {cm if cm is not None else '(기본)'}")
            if cm and str(cm).lower() == "max":
                print(f"     ☠ (다) **max** 다 — 상대(바퀴 0.9)가 이긴다.")
                print(f"        바닥을 0.01 로 낮춰도 결과가 안 바뀐다")
            else:
                print(f"     바인딩·콜리전 모두 정상. 바닥 값이 실제로 쓰인다")

    # ── 4. 바퀴 쪽 (짝을 알아야 결합 결과를 안다) ────────────────────────
    print(f"\n── 4. 바퀴 재질 (짝) ──")
    n = 0
    for p in stage.Traverse():
        path = str(p.GetPath())
        if "wheel" not in path.lower():
            continue
        m = bound_physics(p)
        if not m:
            continue
        f = mats.get(str(m.GetPath()))
        print(f"   {path:<52} -> {m.GetPath()}  정적 {f[0] if f else '?'}"
              f" · combineMode {f[2] if f and f[2] is not None else '(기본)'}")
        n += 1
        if n >= 4:
            print(f"   … (앞 4개만)")
            break
    if not n:
        print(f"   바퀴 prim 에 묶인 물리 재질이 없다 (로봇 에셋 안쪽일 수 있다)")

    print(f"\n   ※ PhysX 기본 결합은 **average** 다. 한쪽이 max 로 저작돼 있으면")
    print(f"     그쪽이 이긴다 — 바닥을 아무리 바꿔도 안 움직이는 전형이다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
