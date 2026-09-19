# -*- coding: utf-8 -*-
"""맵이 **같은 창고인가** — 원본 · 계획격자 · FMS 격자를 맞댄다 (S15P21A106-224).

왜 필요한가
-----------
같은 주문을 넣고 처리량을 비교하려면 **창고가 같아야** 한다. 그런데 둘은
0.1 m 원본을 각자 다르게 1 m 격자로 접는다.

    우리   `pibt_scene.build_free` · cross 풀링 · 칸 c ↔ x ∈ [c, c+1)
    FMS    `map_loader.load_map`  · max 풀링  · 칸 c ↔ x ∈ [c-0.4, c+0.6)

접는 방식이 다르면 **통로 폭이 칸 단위로 달라진다**. 3 m 통로가 한쪽에서 3칸,
다른 쪽에서 2칸이면 같은 계획기라도 다른 결과가 나온다. 그래도 원본이 같으면
「같은 창고를 다르게 접는 것」이고, 원본이 다르면 아예 다른 건물이다. 둘은
고치는 데가 다르다.

무엇을 찍나
-----------
    1  원본 파일이 같은가 (sha256)
    2  창고 실치수 — 폭 · 깊이 · 통로 · 랙 간격 (m)
    3  스테이션이 두 규약에서 같은 칸으로 가나
    4  두 격자의 통행가능 칸이 얼마나 다른가
    5  교차 통로 폭이 칸 단위로 같은가

쓰는 법
-------
    source paths.sh
    python tools/map_parity.py

    FMS_MAP   FMS 맵 폴더 (기본 $W/../../3_FMS/map)
    PITCH     계획 격자 (기본 1.0)
"""
import hashlib
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.environ["W"], "path"))
os.environ.setdefault("PIBT_FRONT_RULE", "4")

import pibt_scene as PS                                      # noqa: E402

W = os.environ["W"]
OUR_MAP = os.environ["MAP"]
FMS_MAP = os.environ.get(
    "FMS_MAP", os.path.abspath(os.path.join(W, "..", "..", "3_FMS", "map")))
PITCH = float(os.environ.get("PITCH", os.environ.get("PIBT_PITCH", "1.0")))

# FMS `map_loader` 상수. 여기 박아 두면 그쪽이 바꿨을 때 이 표가 조용히
# 틀린다 — 그래서 읽을 수 있으면 읽는다.
CELL_M, OFFSET_M = 1.0, 0.4
OBSTACLE_VALUES = (1, 2, 5, 6)


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def read_fms_consts(d):
    """FMS `map_loader.py` 에서 상수를 직접 읽는다 (import 하지 않는다)."""
    p = os.path.abspath(os.path.join(d, "..", "sim_engine", "map_loader.py"))
    got = {}
    if os.path.isfile(p):
        for line in open(p, encoding="utf-8"):
            if line.startswith("CELL_M, OFFSET_M"):
                try:
                    got["cell"], got["off"] = [
                        float(x) for x in line.split("=")[1].split(",")[:2]]
                except Exception:
                    pass
            if line.startswith("OBSTACLE_VALUES"):
                try:
                    got["obs"] = eval(line.split("=", 1)[1].strip())   # noqa: S307
                except Exception:
                    pass
    return got


def fms_free(map_dir, grid01, cell_m, off_m, obs, aisle_block):
    """FMS 격자. **그쪽 모듈을 직접 부른다.**

    베껴 놓으면 그쪽이 바꿨을 때 이 표가 조용히 틀린다. 실제로 첫 판에서
    `aisle_block`(랙 사이 통로 차단)을 우리 쪽에만 걸어 놓고 「FMS 는 통로가
    열려 있다」고 읽을 뻔했다. 부를 수 있으면 부르는 것이 맞다.

    돌려주는 것 (free, 어떻게 얻었나).
    """
    eng = os.path.abspath(os.path.join(map_dir, "..", "sim_engine"))
    if os.path.isdir(eng):
        keep = list(sys.path)
        try:
            sys.path.insert(0, eng)
            import map_loader as ML                            # noqa: E402
            free, _st, _raw = ML.load_map(map_dir, aisle_block=aisle_block)
            return free, f"map_loader.load_map(aisle_block={aisle_block})"
        except Exception as e:
            print(f"   ※ map_loader 를 못 불렀다 ({e!r}) — 재구현으로 간다")
        finally:
            sys.path[:] = keep
    # 후퇴 분기. 여기 오면 `aisle_block` 이 **빠진다** — 그대로 비교하면
    # 랙 사이 통로가 FMS 쪽만 열린 것처럼 보인다.
    k, ox = round(cell_m / 0.1), round(off_m / 0.1)
    raw = np.isin(grid01, obs).astype(np.uint8)
    m2 = np.pad(raw, ((0, 0), (ox, 0)), constant_values=1)
    h, w = m2.shape
    m2 = np.pad(m2, ((0, (-h) % k), (0, (-w) % k)), constant_values=1)
    coarse = m2.reshape(m2.shape[0] // k, k, m2.shape[1] // k, k).max(axis=(1, 3))
    return coarse == 0, "★ 재구현 (통로 차단 없음 — 비교가 과장된다)"


def runs(vec):
    """불리언 1차원에서 True 구간 [(시작, 길이)...]."""
    out, s = [], None
    for i, v in enumerate(vec):
        if v and s is None:
            s = i
        elif not v and s is not None:
            out.append((s, i - s))
            s = None
    if s is not None:
        out.append((s, len(vec) - s))
    return out


def main():
    print(f"[map_parity] 우리 {OUR_MAP}")
    print(f"             FMS  {FMS_MAP}")
    cf = read_fms_consts(FMS_MAP)
    cell_m = cf.get("cell", CELL_M)
    off_m = cf.get("off", OFFSET_M)
    obs = cf.get("obs", OBSTACLE_VALUES)
    src = "map_loader.py 에서 읽음" if cf else "★ 못 읽어 상수를 박아 씀"
    print(f"             FMS 상수 CELL_M={cell_m} OFFSET_M={off_m} "
          f"장애물값={obs}  ({src})")

    # ── 1. 원본이 같은가 ──────────────────────────────────────────────────
    print(f"\n── 1. 원본 파일 ──")
    same_grid = None
    for name in ("occupancy_grid.npy", "stations.json"):
        a = os.path.join(FMS_MAP, name)
        b = os.path.join(OUR_MAP, name)
        if not (os.path.isfile(a) and os.path.isfile(b)):
            print(f"   {name:20} ★ 한쪽에 없다")
            continue
        ha, hb = sha(a), sha(b)
        ok = ha == hb
        if name == "occupancy_grid.npy":
            same_grid = ok
        print(f"   {name:20} {'★ 같다' if ok else '☠ 다르다'}  {ha[:16]}"
              + ("" if ok else f" vs {hb[:16]}"))

    g = np.load(os.path.join(OUR_MAP, "occupancy_grid.npy"))
    R0, C0 = g.shape
    print(f"   원본 격자 {R0} x {C0} · 0.1 m/칸 -> "
          f"**{R0 * 0.1:.1f} m (y) x {C0 * 0.1:.1f} m (x)**")
    vals, cnt = np.unique(g, return_counts=True)
    print(f"   값 분포 {dict(zip(vals.tolist(), cnt.tolist()))}  "
          f"(장애물로 보는 값 {obs})")

    # ── 2. 두 격자 ────────────────────────────────────────────────────────
    geom = PS.make_geom(PITCH)
    ours, k = PS.build_free(OUR_MAP, PITCH, "cross")
    ab = bool(getattr(PS._CFG, "AISLE_BLOCK", False)) if PS._CFG else False
    theirs, how = fms_free(FMS_MAP, g, cell_m, off_m, obs, ab)
    print(f"\n── 2. 접은 격자 ──")
    print(f"   랙 사이 통로 차단(AISLE_BLOCK) = {ab}  — **양쪽에 같이 건다**")
    print(f"     우리는 0.1 m 마스크에, FMS 는 1 m 격자에 건다 (단계가 다르다)")
    print(f"   우리   {ours.shape} · cross 풀링 · 칸 c ↔ x ∈ [c, c+1) · "
          f"통행 {int(ours.sum()):,}칸")
    print(f"   FMS    {theirs.shape} · max 풀링  · 칸 c ↔ "
          f"x ∈ [c-{off_m}, c+{1 - off_m}) · 통행 {int(theirs.sum()):,}칸")
    print(f"          ({how})")

    # ── 3. 스테이션이 같은 칸으로 가나 ────────────────────────────────────
    st = json.load(open(os.path.join(OUR_MAP, "stations.json"), encoding="utf-8"))
    print(f"\n── 3. 스테이션 칸 (우리 규약 vs FMS 규약) ──")
    diff = []
    tot = 0
    for cat, pts in sorted(st.items()):
        if not isinstance(pts, list):
            continue
        for i, p in enumerate(pts):
            if not (isinstance(p, (list, tuple)) and len(p) == 2):
                continue
            tot += 1
            x, y = float(p[0]), float(p[1])
            mine = PS._cell_of(geom, x, y)
            fms = (int(y / cell_m), int((x + off_m) / cell_m))
            if tuple(mine) != fms:
                diff.append((f"{cat}[{i}]", (x, y), tuple(mine), fms))
    if diff:
        print(f"   ☠ {len(diff)}/{tot} 곳이 **다른 칸**으로 간다")
        for nm, xy, a, b in diff[:12]:
            print(f"     {nm:16} (x={xy[0]}, y={xy[1]})  우리 {a}  FMS {b}")
        if len(diff) > 12:
            print(f"     … 외 {len(diff) - 12}곳")
    else:
        print(f"   ★ {tot}곳 전부 같은 칸이다")

    # ── 4. 통행가능 칸 차이 ───────────────────────────────────────────────
    print(f"\n── 4. 통행가능 차이 ──")
    r = min(ours.shape[0], theirs.shape[0])
    c = min(ours.shape[1], theirs.shape[1])
    a, b = ours[:r, :c], theirs[:r, :c]
    both = int((a & b).sum())
    only_us = int((a & ~b).sum())
    only_fms = int((~a & b).sum())
    print(f"   겹치는 범위 {r} x {c}")
    print(f"   둘 다 통행 {both:,} · **우리만 {only_us:,}** · "
          f"**FMS만 {only_fms:,}**")
    print(f"   불일치 {only_us + only_fms:,} / {r * c:,} "
          f"({(only_us + only_fms) / (r * c) * 100:.1f} %)")

    # ── 5. 교차 통로 폭 ───────────────────────────────────────────────────
    print(f"\n── 5. 가로 통로 폭 (행별 연속 통행 구간, 3칸 이상) ──")
    print(f"   {'행':>5}  {'우리':<34}  {'FMS':<34}")
    for rr in range(min(r, 106)):
        ra = [(s, n) for s, n in runs(a[rr]) if n >= 3]
        rb = [(s, n) for s, n in runs(b[rr]) if n >= 3]
        if ra == rb:
            continue
        sa = " ".join(f"{s}+{n}" for s, n in ra[:4])
        sb = " ".join(f"{s}+{n}" for s, n in rb[:4])
        print(f"   r{rr:<4}  {sa:<34}  {sb:<34}")

    print(f"\n   읽는 법")
    print(f"    · 1 이 같고 3·4 가 다르면 **같은 창고를 다르게 접은 것**이다.")
    print(f"      건물은 하나고, 칸 규약(0.4 m 옵셋)과 풀링이 다르다.")
    print(f"    · 1 이 다르면 애초에 다른 건물이다 — 여기부터 맞춰야 한다.")
    print(f"    · 3 에서 어긋난 스테이션은 **주문 재생에 직접 영향**을 준다.")
    print(f"      `aisle_buf`·`packing` 이 끼어 있으면 출발·도착이 달라진다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
