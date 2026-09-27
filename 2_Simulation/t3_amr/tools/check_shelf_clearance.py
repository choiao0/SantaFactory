# -*- coding: utf-8 -*-
"""적재 선반 상부가 랙 데크 밑으로 파고드는 상태를 센다 (S15P21A106-196).

    python tools/check_shelf_clearance.py                       기본 (상부 뒤 0.850)
    python tools/check_shelf_clearance.py --sweep                한계값 찾기
    python tools/check_shelf_clearance.py --rear 0.820           다른 값으로
    python tools/check_shelf_clearance.py --show 8               침범 상태를 찍는다

[왜 필요한가]
지금 로봇은 높이 220 mm 라 랙 1단 데크(밑면 **1,005 mm**) 밑으로 그냥 지나간다.
선반을 1,650 mm 로 올리면 못 지나간다. 그런데 계획기는 이걸 **모른다** —
`occupancy_grid` 는 2차원이고 랙 칸(코드 2)은 "목표로 삼지 않는 칸" 일 뿐,
차체가 그 위를 스치는 것은 막지 않는다.

구동축이 **앞**이라(`heading_offset=0`) 차체는 헤딩의 **뒤쪽**으로 뻗는다.
그래서 로봇이 랙에 등을 돌리고 서면 꼬리가 랙 풋프린트 안으로 들어간다.
선반 상부를 그만큼 짧게 깎아야 데크를 피한다 — 이 스크립트가 그 길이를 잰다.

[무엇을 세나]
실제 계획이 방문한 모든 상태 (r, c, h) 에 대해 **상부 직사각형**을 world 로
펴고, 0.1 m 원본 격자의 **랙 셀(코드 2)** 과 겹치는지 본다. 겹치면 1건.

  상부 직사각형 (구동축 기준, 로봇 로컬)
      x ∈ [-rear, +front]      rear = 상부 뒤 돌출 (이 스크립트의 인자)
      y ∈ [-width/2, +width/2]

[한계]
여기서 나온 값은 **이 맵 · 이 계획** 의 것이다. 맵·시드·대수가 바뀌면 방문
상태가 달라지므로 다시 돌려야 한다. 통로 기하(랙 남단 y=47.05, 마지막 랙열
서단 x=98.05)는 격자에서 나오므로 격자가 그대로면 값도 그대로다.
"""
import argparse
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "path"))

import pibt_scene as PS                                      # noqa: E402
from pibt_core_v2 import DIRS                                # noqa: E402

RACK_CODE = 2          # 0.1 m 원본 셀값: 1=구조물 2=랙 5=컨베이어 6=바닥 파렛트
FINE = 0.1             # 원본 격자 해상도 [m]


def visited_states(map_dir, n, pitch, seed, horizon, dispatch):
    """계획을 한 번 돌려 **방문한 상태**만 모은다 (중복 제거).

    ★ 이건 *그 시드 · 그 설정* 의 표본이다. 선반 치수를 여기에만 맞추면
      시드·배차·대수를 바꾸는 순간 무효가 된다. 실제로 그랬다 —
      설계 문서(배터리 ON · robot_first)는 41건을 봤는데, 배터리를 끄고
      배차를 fms 로 바꾼 계획에서는 **0건**이 나온다. 상태가 안 겹쳤을 뿐
      기하가 안전해진 게 아니다. 치수 결정은 `--all` 로 하라.
    """
    import isaac_drive as ID
    geom, free, starts, cells = PS.setup_lifelong(map_dir, n, pitch, seed, verbose=False)
    zc = PS.charge_zone_cells(free, geom)
    _adg, _order, hist, _info = ID.plan_and_build_lifelong(
        free, starts, cells, geom, horizon=horizon, seed=seed,
        dispatch=dispatch, zone_cells=zc)
    seen = {s for snap in hist for s in snap.values()}
    return geom, sorted(seen)


def all_states(map_dir, n, pitch, seed):
    """**도달 가능한 모든 칸 x 유효 헤딩.** 시드·배차와 무관한 최악값 기준.

    선반은 물리 하드웨어라 한 번 만들면 못 줄인다. 계획이 우연히 안 간
    자리라도 다음 시드에서는 간다 — 치수는 여기에 맞춰야 한다.
    """
    from pibt_core_v2 import valid_state
    geom, free, _starts, _cells = PS.setup_lifelong(map_dir, n, pitch, seed, verbose=False)
    out = []
    for r, c in zip(*np.nonzero(free)):
        for h in range(4):
            if valid_state(free, (int(r), int(c), h)):
                out.append((int(r), int(c), h))
    return geom, out


def body_rect(geom, state, rear, front, width):
    """상태 -> 상부 직사각형의 world 경계 (x0, y0, x1, y1)."""
    r, c, h = state
    cx, cy = geom.cell_center((r, c))
    dr, dc = DIRS[h]                      # (행, 열) 증분 = (y, x) 방향
    fx, fy = dc, dr                       # 전진 단위벡터 (world)
    # 앞으로 front, 뒤로 rear, 좌우 width/2
    xs = [cx + fx * front - fy * width / 2, cx + fx * front + fy * width / 2,
          cx - fx * rear - fy * width / 2, cx - fx * rear + fy * width / 2]
    ys = [cy + fy * front - fx * width / 2, cy + fy * front + fx * width / 2,
          cy - fy * rear - fx * width / 2, cy - fy * rear + fx * width / 2]
    return min(xs), min(ys), max(xs), max(ys)


def count_hits(grid, geom, states, rear, front, width, show=0):
    """랙 셀과 겹치는 상태 수. show>0 이면 그만큼 예시를 찍는다."""
    H, W = grid.shape
    rack = grid == RACK_CODE
    hits, shown = [], 0
    for st in states:
        x0, y0, x1, y1 = body_rect(geom, st, rear, front, width)
        c0, c1 = int(np.floor(x0 / FINE)), int(np.ceil(x1 / FINE))
        r0, r1 = int(np.floor(y0 / FINE)), int(np.ceil(y1 / FINE))
        c0, c1 = max(0, c0), min(W, c1)
        r0, r1 = max(0, r0), min(H, r1)
        if c0 >= c1 or r0 >= r1:
            continue
        if rack[r0:r1, c0:c1].any():
            hits.append(st)
            if shown < show:
                shown += 1
                print(f"    {st}  center=({geom.cell_center(st[:2])[0]:.2f}, "
                      f"{geom.cell_center(st[:2])[1]:.2f})  "
                      f"rect x[{x0:.2f},{x1:.2f}] y[{y0:.2f},{y1:.2f}]")
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", default=os.path.join(ROOT, "warehouse", "map"))
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--pitch", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--horizon", type=int, default=315)
    ap.add_argument("--dispatch", default="fms")
    ap.add_argument("--rear", type=float, default=0.850,
                    help="상부 뒤 돌출 [m] (구동축 기준). 기본 0.850 = 상부 1,240 mm")
    ap.add_argument("--front", type=float, default=0.390)
    ap.add_argument("--width", type=float, default=0.800)
    ap.add_argument("--sweep", action="store_true", help="한계값을 찾는다")
    ap.add_argument("--show", type=int, default=0, help="침범 상태 예시 개수")
    ap.add_argument("--visited", action="store_true",
                    help="계획이 실제 방문한 상태만 본다 (그 시드 전용 표본). "
                         "기본은 --all: 도달 가능한 전 상태 = 시드 무관 최악값")
    a = ap.parse_args()

    grid = np.load(os.path.join(a.map, "occupancy_grid.npy"))
    if a.visited:
        geom, states = visited_states(a.map, a.n, a.pitch, a.seed, a.horizon, a.dispatch)
        kind = f"방문 상태(seed {a.seed} · {a.dispatch})"
    else:
        geom, states = all_states(a.map, a.n, a.pitch, a.seed)
        kind = "도달 가능한 전 상태"
    print(f"{kind} {len(states)}개 · 격자 {grid.shape} · 랙 셀 "
          f"{int((grid == RACK_CODE).sum()):,}\n")

    if a.sweep:
        print(f"{'상부 뒤 돌출':>12} {'상부 길이':>10} {'랙 침범':>8}")
        for rear in (1.110, 1.000, 0.950, 0.900, 0.870, 0.860, 0.850, 0.820, 0.800):
            hits = count_hits(grid, geom, states, rear, a.front, a.width)
            mark = "  <<< 여기서 0" if not hits else ""
            print(f"{rear:>12.3f} {(rear + a.front) * 1000:>9.0f}mm "
                  f"{len(hits):>8}{mark}")
        return

    hits = count_hits(grid, geom, states, a.rear, a.front, a.width, a.show)
    print(f"상부 뒤 돌출 {a.rear:.3f} m (상부 길이 {(a.rear + a.front) * 1000:.0f} mm) "
          f"· 폭 {a.width:.3f} m")
    print(f"  랙 침범 상태 {len(hits)}/{len(states)}")
    if hits:
        print("  ★ 선반 상부가 랙 데크(밑면 1,005 mm) 밑으로 들어갑니다.")
        print("     --sweep 으로 한계값을 찾으세요.")
    sys.exit(1 if hits else 0)


if __name__ == "__main__":
    main()
