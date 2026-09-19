# -*- coding: utf-8 -*-
"""Isaac 씬(USD)이 **계획 맵과 같은 창고인가** (S15P21A106-224).

왜 필요한가
-----------
`build_scene.py` 는 씬을 맵에서 굽는다 (`CELL = 0.1`). 그래서 **구조적으로는**
일치한다. 위험은 다른 데 있다 — **구워 둔 USD 가 옛 맵 것일 때**다. 그러면
계획은 새 창고, 화면과 물리는 옛 창고가 된다. 실제로 그런 적이 있다
(2026-09-11, `paths.sh` 주석: "맵은 새 창고인데 화면은 옛 창고").

파일 날짜로는 못 가린다. 빌더가 바뀌어도 USD 는 그대로 남기 때문이다.
그래서 **씬에서 다시 읽어** 격자와 맞댄다.

무엇을 재나
-----------
    1  스테이지 규약     metersPerUnit · upAxis  ★ 1.0/z 가 아니면 아래가 전부 틀리다
    2  건물 치수         /World bbox  vs  격자 (행·열) x 0.1 m
    3  랙 배치           USD 랙 bbox  vs  rack_units.npy (x중심 · y시작 · 길이)
    4  기둥              USD 기둥 xy   vs  columns.npy
    5  ★ 점유 일치       고체 prim 의 bbox 를 0.1 m 로 래스터화해 원본 격자와 비교

읽는 법 — 5번이 핵심이다
------------------------
bbox 래스터는 **과대평가**다 (비스듬한 물체도 사각형을 다 채운다). 그래서

    USD 가 덮는데 격자는 비었다     흔하다. bbox 여유. 큰 덩어리면 볼 것
    ★ 격자는 막혔는데 USD 가 비었다  **이게 문제다.** 계획은 벽이라는데 씬에
                                     아무것도 없다 = 씬이 옛 맵이거나 덜 구워졌다

쓰는 법
-------
    source paths.sh
    python tools/usd_map_parity.py                    # $SCENE 을 본다
    python tools/usd_map_parity.py $STAGE/pibt12.usd  # 빌드된 무대

`pxr` 이 없으면 Isaac 파이썬으로:
    isaacsim isaacsim.exp.full --no-window --exec "<t3_amr>/tools/usd_map_parity.py"
"""
import os
import sys

import numpy as np

try:
    from pxr import Usd, UsdGeom, Gf                    # noqa: F401
except ImportError:
    sys.exit("★ pxr 이 없습니다. Isaac 파이썬으로 돌리십시오 (독스트링 참조).")

CELL = 0.1
# 바닥·조명·카메라·돔은 장애물이 아니다. 여기 빠뜨리면 「격자는 막혔는데 USD 가
# 비었다」가 허위로 뜬다 — 그 경보가 이 도구의 전부라 목록이 곧 정확도다.
SOLID = ("/World/walls", "/World/office_walls", "/World/racks",
         "/World/columns", "/World/steel", "/World/conveyors",
         "/World/worktables", "/World/pallets", "/World/doors",
         "/World/shutters", "/World/shutters_rib", "/World/chargers")
SKIP = ("/World/floor", "/World/ground", "/World/dome", "/World/lights",
        "/World/sun", "/World/cam", "/World/markings", "/World/anchors",
        "/World/Looks", "/World/chargers_led", "/World/chargers_trim")


def bbox_xy(cache, prim):
    """world 좌표 (x0, y0, x1, y1). 비었으면 None."""
    b = cache.ComputeWorldBound(prim)
    r = b.ComputeAlignedRange()
    if r.IsEmpty():
        return None
    mn, mx = r.GetMin(), r.GetMax()
    return (float(mn[0]), float(mn[1]), float(mx[0]), float(mx[1]))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    usd = args[0] if args else os.environ.get("SCENE")
    map_dir = os.environ.get("MAP")
    if not usd or not os.path.isfile(usd):
        sys.exit(f"★ USD 를 못 찾습니다: {usd!r} ($SCENE 또는 인자)")
    if not map_dir:
        sys.exit("★ $MAP 이 없습니다 — source paths.sh")

    g = np.load(os.path.join(map_dir, "occupancy_grid.npy"))
    obs = np.isin(g, (1, 2, 5, 6))
    R0, C0 = g.shape
    # ★ 페이로드를 다 연다. 안 열면 참조 에셋이 통째로 안 보이고, 그걸
    #   「씬에 없다」로 읽게 된다 (2026-09-17 에 실제로 그렇게 읽었다).
    stage = Usd.Stage.Open(usd, Usd.Stage.LoadAll)
    mpu = UsdGeom.GetStageMetersPerUnit(stage)
    up = UsdGeom.GetStageUpAxis(stage)

    print(f"[usd_map_parity] {os.path.basename(usd)}")
    print(f"   맵 {map_dir}")
    print(f"\n── 1. 스테이지 규약 ──")
    ok1 = abs(mpu - 1.0) < 1e-9 and str(up) == "Z"
    print(f"   metersPerUnit {mpu}  ·  upAxis {up}   "
          f"{'★ 기대대로' if ok1 else '☠ 아래 숫자가 전부 이 배율만큼 틀리다'}")

    cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(),
                              [UsdGeom.Tokens.default_, UsdGeom.Tokens.render])

    # ── 1b. ★ 참조 에셋이 풀렸나 ─────────────────────────────────────────
    #   랙·컨베이어·포장대는 **원격 S3 URL 참조**다 (`build_scene.ASSETS`).
    #   망이 없거나 캐시가 비면 조용히 빈 Xform 만 남는다. 그 상태로 점유를
    #   재면 「격자는 막혔는데 씬이 비었다」가 잔뜩 나오는데, 원인은 맵이
    #   아니라 **에셋을 못 받은 것**이다. 둘은 고치는 데가 전혀 다르다.
    print(f"\n── 1b. 참조 에셋 ──")
    refs = []
    for p in stage.Traverse():
        if not p.HasAuthoredReferences():
            continue
        n = sum(1 for q in Usd.PrimRange(p) if q.IsA(UsdGeom.Gprim))
        refs.append((str(p.GetPath()), n))
    if not refs:
        print(f"   참조 prim 이 없다 (전부 직접 만든 씬이다)")
    else:
        empty = [r for r in refs if r[1] == 0]
        print(f"   참조 prim {len(refs):,}개 · 그중 **기하가 하나도 없는 것 "
              f"{len(empty):,}개**")
        if empty:
            print(f"   ☠ 참조가 안 풀렸다 — 아래 숫자는 그만큼 비어 보인다")
            seen = set()
            for path, _ in empty:
                key = path.rsplit("/", 2)[0] if "/" in path else path
                grp = "/".join(key.split("/")[:3])
                if grp in seen:
                    continue
                seen.add(grp)
                print(f"     {grp}  예: {path}")
            print(f"   고치는 법: 그 기계에서 Omniverse 에셋을 받거나 "
                  f"`build_scene.ASSETS` 를 로컬 사본으로 돌린다")

    # ── 2. 건물 치수 ──────────────────────────────────────────────────────
    #   ★ 배열 크기가 아니라 **장애물이 퍼진 범위**와 비교한다. 배열에는
    #     건물 바깥 여백이 들어 있어서, 배열과 대면 늘 «작다»가 나온다
    #     (2026-09-17 에 실제로 «x -3.7 m · y -15.5 m» 로 읽었다 — 허위였다).
    print(f"\n── 2. 건물 치수 ──")
    rs_, cs_ = np.where(obs)
    gx0, gx1 = cs_.min() * CELL, (cs_.max() + 1) * CELL
    gy0, gy1 = rs_.min() * CELL, (rs_.max() + 1) * CELL
    print(f"   격자 배열 {R0} x {C0} x {CELL} m "
          f"(x 0~{C0 * CELL:.1f} · y 0~{R0 * CELL:.1f}) — 여백 포함")
    print(f"   격자 **장애물 범위**  x {gx0:.2f} ~ {gx1:.2f} m · "
          f"y {gy0:.2f} ~ {gy1:.2f} m   <- 건물은 이것")
    solid_prims = []
    for p in Usd.PrimRange.Stage(stage, Usd.TraverseInstanceProxies()):
        path = str(p.GetPath())
        if any(path.startswith(s) for s in SKIP):
            continue
        if not any(path.startswith(s) for s in SOLID):
            continue
        if p.IsA(UsdGeom.Gprim):
            solid_prims.append(p)
    xs = [bbox_xy(cache, p) for p in solid_prims]
    xs = [b for b in xs if b]
    if not xs:
        sys.exit("★ 고체 prim 을 하나도 못 찾았습니다 — SOLID 목록을 보십시오")
    x0 = min(b[0] for b in xs)
    y0 = min(b[1] for b in xs)
    x1 = max(b[2] for b in xs)
    y1 = max(b[3] for b in xs)
    print(f"   USD 고체 {len(xs):,}개 bbox -> "
          f"x {x0:.2f} ~ {x1:.2f} m · y {y0:.2f} ~ {y1:.2f} m")
    print(f"   차이   x0 {x0 - gx0:+.2f} · x1 {x1 - gx1:+.2f} · "
          f"y0 {y0 - gy0:+.2f} · y1 {y1 - gy1:+.2f} m")

    # ── 3. 랙 ────────────────────────────────────────────────────────────
    ru_path = os.path.join(map_dir, "rack_units.npy")
    if os.path.isfile(ru_path):
        ru = np.load(ru_path)
        print(f"\n── 3. 랙 ── (rack_units.npy {ru.shape})")
        # ★ **이름이 아니라 위치로** 맞춘다. 랙은 두 갈래로 지어진다 —
        #   참조 에셋(`b{bi}_l{line}/…`)과 격자 유래 콜라이더 박스
        #   (`solid_{i}`, -224 에서 추가). 이름 접두사로 찾으면 뒤의 것을
        #   못 보고 재빌드 뒤에도 「없다」를 외친다. `/World/racks` 아래
        #   기하를 전부 모아 **중심이 가장 가까운 것**과 댄다.
        rack_boxes = []
        for p in Usd.PrimRange.Stage(stage, Usd.TraverseInstanceProxies()):
            if not str(p.GetPath()).startswith("/World/racks/"):
                continue
            if not p.IsA(UsdGeom.Gprim):
                continue
            b = bbox_xy(cache, p)
            if b:
                rack_boxes.append(b)
        print(f"   `/World/racks` 아래 기하 {len(rack_boxes):,}개 "
              f"(참조 에셋 + 격자 콜라이더 합계)")
        if not rack_boxes:
            print(f"   ☠ 하나도 없다 — 참조가 안 풀렸고 격자 콜라이더도 없다")
            print(f"     씬을 다시 구우면 투명 박스가 선다 (RACK_COLLIDER)")
        else:
            print(f"   {'블록':>5}{'x중심(맵)':>12}{'x중심(USD)':>12}{'차이':>9}"
                  f"{'y범위(맵)':>18}{'y범위(USD)':>18}")
            bad = 0
            for bi in range(len(ru)):
                mx = float(ru[bi][0])
                my0 = float(ru[bi][1])
                my1 = my0 + float(ru[bi][2]) * 3.0    # v6.0 유닛 3.0 m
                myc = (my0 + my1) / 2
                # 중심이 가장 가까운 상자 하나
                b = min(rack_boxes,
                        key=lambda q: (((q[0] + q[2]) / 2 - mx) ** 2
                                       + ((q[1] + q[3]) / 2 - myc) ** 2))
                ux = (b[0] + b[2]) / 2
                d = ux - mx
                if abs(d) > 0.6:
                    bad += 1
                print(f"   b{bi:<4}{mx:>12.2f}{ux:>12.2f}{d:>+9.2f}"
                      f"{f'{my0:.1f}~{my1:.1f}':>18}"
                      f"{f'{b[1]:.1f}~{b[3]:.1f}':>18}"
                      + ("   ☠" if abs(d) > 0.6 else ""))
            print(f"   x중심이 0.6 m 넘게 어긋난 블록 {bad}/{len(ru)}")

    # ── 4. 기둥 ──────────────────────────────────────────────────────────
    cp = os.path.join(map_dir, "columns.npy")
    if os.path.isfile(cp):
        cols = np.load(cp)
        ps = [p for p in stage.Traverse()
              if str(p.GetPath()).startswith("/World/columns/")
              and (p.IsA(UsdGeom.Gprim) or p.IsInstance())]
        cs = []
        for p in ps:
            b = bbox_xy(cache, p)
            if b:
                cs.append(((b[0] + b[2]) / 2, (b[1] + b[3]) / 2))
        print(f"\n── 4. 기둥 ── 맵 {len(cols)}곳 · USD {len(cs)}개")
        far = 0
        for (mx, my) in cols:
            if not cs:
                break
            d = min(((mx - ux) ** 2 + (my - uy) ** 2) ** 0.5 for ux, uy in cs)
            if d > 1.0:
                far += 1
                print(f"   ☠ 맵 기둥 ({mx:.1f}, {my:.1f}) 에서 가장 가까운 "
                      f"USD 기둥이 {d:.2f} m")
        print(f"   1 m 안에 짝이 없는 맵 기둥 {far}/{len(cols)}")

    # ── 5. ★ 점유 일치 ───────────────────────────────────────────────────
    print(f"\n── 5. ★ 점유 일치 (bbox 래스터 0.1 m) ──")
    usd_occ = np.zeros_like(obs)
    for b in xs:
        c0 = max(0, int(np.floor(b[0] / CELL)))
        r0 = max(0, int(np.floor(b[1] / CELL)))
        c1 = min(C0, int(np.ceil(b[2] / CELL)))
        r1 = min(R0, int(np.ceil(b[3] / CELL)))
        if c1 > c0 and r1 > r0:
            usd_occ[r0:r1, c0:c1] = True
    both = int((usd_occ & obs).sum())
    only_usd = int((usd_occ & ~obs).sum())
    only_map = int((~usd_occ & obs).sum())
    print(f"   격자 장애물 {int(obs.sum()):,}칸 · USD 래스터 "
          f"{int(usd_occ.sum()):,}칸")
    print(f"   둘 다 {both:,} · USD만 {only_usd:,} (bbox 여유, 흔하다)")
    print(f"   ★ 격자만 {only_map:,}칸 "
          f"({only_map / max(int(obs.sum()), 1) * 100:.1f} %) "
          f"— **씬에 없는 장애물**")

    # ★ 값별로 가른다. 「랙만 빠졌다」와 「벽이 빠졌다」는 뜻이 전혀 다르다 —
    #   앞은 보통 참조 에셋을 못 받은 것이고, 뒤는 씬이 옛 맵이라는 뜻이다.
    miss = ~usd_occ & obs
    names = {1: "구조물(벽·기둥)", 2: "랙", 5: "컨베이어", 6: "바닥 파렛트"}
    print(f"   값별 —")
    for v, nm in names.items():
        tot_v = int((g == v).sum())
        if not tot_v:
            continue
        m_v = int((miss & (g == v)).sum())
        flag = ""
        if m_v > 0.5 * tot_v:
            flag = ("   ☠ 이 종류가 통째로 빠졌다"
                    if v == 1 else "   ★ 이 종류가 통째로 빠졌다")
        print(f"     값 {v} {nm:14} {m_v:7,} / {tot_v:7,}칸 "
              f"({m_v / tot_v * 100:5.1f} %){flag}")
    if only_map:
        lab = np.argwhere(~usd_occ & obs)
        rs, cs2 = lab[:, 0], lab[:, 1]
        print(f"     퍼진 범위 행 {rs.min()}~{rs.max()} · 열 {cs2.min()}~{cs2.max()}"
              f"  (m: y {rs.min() * CELL:.1f}~{rs.max() * CELL:.1f} · "
              f"x {cs2.min() * CELL:.1f}~{cs2.max() * CELL:.1f})")
        # 1 m 격자로 뭉쳐 큰 덩어리만 — 가장자리 한 줄은 늘 남는다
        k = 10
        r2, c2 = (R0 // k) * k, (C0 // k) * k
        blk = (~usd_occ & obs)[:r2, :c2].reshape(r2 // k, k, c2 // k, k)
        dens = blk.sum(axis=(1, 3))
        big = np.argwhere(dens >= 80)          # 1 m 칸의 80 % 이상이 빈 곳
        print(f"     1 m 칸 중 80 % 이상이 씬에 없는 칸 {len(big)}개")
        for r, c in big[:12]:
            print(f"       칸 (r={r}, c={c})  x {c * 1.0:.0f}~{c + 1:.0f} m · "
                  f"y {r * 1.0:.0f}~{r + 1:.0f} m")

    print(f"\n   읽는 법")
    print(f"    · **1b 를 먼저 본다.** 참조가 안 풀렸으면 3·5 의 «없다» 는")
    print(f"      맵 문제가 아니라 **에셋을 못 받은 것**이다. 맵은 멀쩡하다.")
    print(f"    · 2 는 격자의 **장애물 범위**와 댄다. 배열 크기에는 건물 바깥")
    print(f"      여백이 들어 있어 그것과 대면 늘 «작다» 가 나온다.")
    print(f"    · 5 의 **격자만** 이 0 에 가까우면 씬과 맵이 같은 건물이다.")
    print(f"      가장자리 한두 줄은 bbox 반올림이라 정상이다.")
    print(f"    · 값 1(벽) 이 통째로 빠지면 **씬이 옛 맵**이다 — 벽은 격자에서")
    print(f"      직접 박스를 세우므로 참조와 무관하다. 값 2(랙) 만 빠지는 것은")
    print(f"      보통 참조 에셋 문제다 (랙은 격자 유래 콜라이더가 없다).")
    print(f"    · 3 의 랙 x중심이 어긋나면 **격자와 화면이 다른 창고**다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
