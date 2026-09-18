# -*- coding: utf-8 -*-
"""**같은 계획기가 두 격자에서 같은 길을 내나** (S15P21A106-240).

왜
--
`map_parity.py` 가 두 격자가 4.1 % 다르다는 것까지 답했다. 남은 물음은
**그 차이가 경로를 바꾸나**다. 통로 폭이 한 칸 다르면 지나갈 수 있는지가
갈리고, 그러면 같은 주문에 다른 길이 나온다.

계획 코드는 **양쪽이 똑같다** — `pibt_core_v2` 가 `3_FMS/sim_engine/pibt_core.py`
원본을 로드하므로 `turn_ok`·`valid_state`·`candidates_h` 가 글자 그대로 같다.
그래서 **격자만 바꿔** 같은 코드를 돌리면 차이의 원인이 격자로 특정된다.

칸 규약 (`map_parity.py` §3 에서 확인)
--------------------------------------
    우리   origin=(pitch/2, pitch/2) · world_to_cell = round((y-oy)/pitch)
           -> 칸 (r,c) 중심 = (0.5+c, 0.5+r) m      x ∈ [c, c+1)
    FMS    r = int(y/CELL_M) · c = int((x+OFFSET_M)/CELL_M)
           -> 칸 (r,c) 중심 = (c+0.1, r+0.5) m      x ∈ [c-0.4, c+0.6)

**행은 같은 규약이고 열만 0.4 m 밀려 있다.** 그래서 칸 인덱스로 맞대면 안 되고
**월드 좌표(m)로 되돌려** 비교해야 한다.

재는 것
-------
    ① 도달성      같은 두 지점이 양쪽에서 다 닿나
    ② 비용        틱 단위 최단 비용이 얼마나 다른가
    ③ 경로 길이   실제 주행 거리 [m]
    ④ **이탈**    두 경로가 월드에서 최대 몇 m 떨어지나 (양방향 하우스도르프)

    ④가 0.5 m 안이면 **같은 통로를 지난 것**이다 (칸 규약 차이 0.4 m 수준).
    2 m 를 넘으면 **다른 통로로 돌아간 것**이라 같은 주문에 다른 길이 나온다.

쓰는 법
-------
    source paths.sh
    python tools/route_parity.py
    PAIRS=30 python tools/route_parity.py      # 더 많이
"""
import heapq
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.environ["W"], "path"))
os.environ.setdefault("PIBT_RECOVER", "0")

import pibt_core_v2 as PC                               # noqa: E402  (sim_engine 을 경로에 넣는다)
import pibt_scene as PS                                 # noqa: E402
import isaac_drive as D                                 # noqa: E402

PITCH = float(os.environ.get("PIBT_PITCH", "1.0"))
OUR_MAP = os.environ["MAP"]
FMS_MAP = os.environ.get("FMS_MAP",
                         os.path.join(os.environ["W"], "..", "..", "3_FMS", "map"))
PAIRS = int(os.environ.get("PAIRS", "12"))
DIRS = [(1, 0), (0, 1), (-1, 0), (0, -1)]


# ---------------------------------------------------------------------------
# 격자 둘
# ---------------------------------------------------------------------------
def fms_grid():
    """FMS `load_map` 을 그대로 부른다. 우리가 다시 구현하면 정의가 두 벌이 된다."""
    import map_loader as ML
    ab = bool(getattr(PS._CFG, "AISLE_BLOCK", False)) if PS._CFG else False
    free, _st, _raw = ML.load_map(FMS_MAP, aisle_block=ab)
    return np.asarray(free), ML.CELL_M, ML.OFFSET_M, ab


def our_cell(x, y):
    return (int(round((y - PITCH / 2.0) / PITCH)), int(round((x - PITCH / 2.0) / PITCH)))


def our_world(rc):
    return (PITCH / 2.0 + rc[1] * PITCH, PITCH / 2.0 + rc[0] * PITCH)


def fms_cell(x, y, cell_m, off_m):
    return (int(y / cell_m), int((x + off_m) / cell_m))


def fms_world(rc, cell_m, off_m):
    return ((rc[1] + 0.5) * cell_m - off_m, (rc[0] + 0.5) * cell_m)


# ---------------------------------------------------------------------------
# 최단 경로 — `candidates_h` 와 같은 간선 규칙 (turn_ban_impact.py 와 동일)
# ---------------------------------------------------------------------------
def edges(free, r, c, h):
    out = []
    dr, dc = DIRS[h]
    H, W = free.shape
    rr, cc = r + dr, c + dc
    if 0 <= rr < H and 0 <= cc < W and free[rr, cc]:
        out.append(((rr, cc, h), float(D.MOVE_TICKS)))
    for h2 in ((h + 1) % 4, (h - 1) % 4):
        if PC.turn_ok(free, r, c, h, h2):
            out.append(((r, c, h2), float(D.TURN_TICKS)))
    br, bc = r - dr, c - dc
    if PC.valid_state(free, (br, bc, h)):
        out.append(((br, bc, h), float(D.MOVE_TICKS) * D.REVERSE_FACTOR))
    return out


def shortest(free, start_cell, goal_cell):
    """start 칸의 어느 헤딩에서든 출발해 goal 칸에 닿는 최소 비용 경로.

    돌려주는 것: (비용, [(r,c,h)...]) 또는 (None, None).
    """
    H, W = free.shape
    starts = [(start_cell[0], start_cell[1], h) for h in range(4)
              if PC.valid_state(free, (start_cell[0], start_cell[1], h))]
    if not starts or not (0 <= goal_cell[0] < H and 0 <= goal_cell[1] < W
                          and free[goal_cell]):
        return None, None
    dist, prev = {}, {}
    pq = []
    for s in starts:
        dist[s] = 0.0
        heapq.heappush(pq, (0.0, s))
    goal = None
    while pq:
        d, s = heapq.heappop(pq)
        if d > dist.get(s, float("inf")):
            continue
        if s[:2] == tuple(goal_cell):
            goal = s
            break
        for nxt, w in edges(free, s[0], s[1], s[2]):
            nd = d + w
            if nd < dist.get(nxt, float("inf")):
                dist[nxt] = nd
                prev[nxt] = s
                heapq.heappush(pq, (nd, nxt))
    if goal is None:
        return None, None
    path = [goal]
    while path[-1] in prev:
        path.append(prev[path[-1]])
    return dist[goal], list(reversed(path))


# ---------------------------------------------------------------------------
# 경로를 월드 폴리라인으로 — 그리고 두 폴리라인의 이탈
# ---------------------------------------------------------------------------
def polyline(path, to_world):
    """회전은 제자리라 점이 겹친다. 연속 중복을 접는다."""
    pts = []
    for s in path:
        p = to_world((s[0], s[1]))
        if not pts or abs(p[0] - pts[-1][0]) > 1e-9 or abs(p[1] - pts[-1][1]) > 1e-9:
            pts.append(p)
    return pts


def _pt_seg(p, a, b):
    ax, ay = a; bx, by = b; px, py = p
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def hausdorff(A, B):
    """양방향 최대 이탈 [m]. 한쪽 점에서 상대 **선분**까지 재므로 표본 간격에 안 흔들린다."""
    def one(P, Q):
        return max(min(_pt_seg(p, Q[i], Q[i + 1]) for i in range(len(Q) - 1))
                   for p in P) if len(Q) > 1 else float("inf")
    return max(one(A, B), one(B, A))


def length(P):
    return sum(math.hypot(P[i + 1][0] - P[i][0], P[i + 1][1] - P[i][1])
               for i in range(len(P) - 1))


def main():
    ours, k = PS.build_free(OUR_MAP, PITCH, "cross")
    theirs, cell_m, off_m, ab = fms_grid()
    print(f"[route_parity] pitch {PITCH} · 통로차단 {ab}")
    print(f"  우리 {ours.shape} cross 풀링 · 통행 {int(ours.sum()):,}칸")
    print(f"  FMS  {theirs.shape} max  풀링 · 통행 {int(theirs.sum()):,}칸 "
          f"(CELL_M={cell_m} OFFSET_M={off_m})")
    if abs(cell_m - PITCH) > 1e-9:
        print(f"  ☹ FMS 격자는 {cell_m} m 고정이라 pitch {PITCH} 와 맞대면 의미가 없다")
        return

    # 스테이션을 물리 좌표로 받아 양쪽 규약으로 각각 칸을 만든다
    st = json.load(open(os.path.join(OUR_MAP, "stations.json"), encoding="utf-8"))
    pts = [(cat, i, float(p[0]), float(p[1]))
           for cat, v in sorted(st.items()) if isinstance(v, list)
           for i, p in enumerate(v)
           if isinstance(p, (list, tuple)) and len(p) == 2]
    if len(pts) < 2:
        print("  ☹ 스테이션이 모자라다")
        return
    step = max(1, len(pts) // max(1, int(math.isqrt(PAIRS * 2))))
    sel = pts[::step]
    pairs = [(sel[i], sel[j]) for i in range(len(sel)) for j in range(i + 1, len(sel))][:PAIRS]

    print(f"\n  스테이션 {len(pts)}곳 중 {len(sel)}곳 · 쌍 {len(pairs)}개\n")
    print("   {:>26} {:>9} {:>9} {:>9} {:>9} {:>10}".format(
        "출발 -> 도착", "우리 틱", "FMS 틱", "우리 m", "FMS m", "**이탈 m**"))

    rows, bad, unreach = [], 0, 0
    for (ca, ia, xa, ya), (cb, ib, xb, yb) in pairs:
        name = f"{ca}[{ia}] -> {cb}[{ib}]"
        c1 = shortest(ours, our_cell(xa, ya), our_cell(xb, yb))
        c2 = shortest(theirs, fms_cell(xa, ya, cell_m, off_m),
                      fms_cell(xb, yb, cell_m, off_m))
        if c1[0] is None or c2[0] is None:
            unreach += 1
            w = "우리 못감" if c1[0] is None else ""
            w += " FMS 못감" if c2[0] is None else ""
            print(f"   {name:>26}  ☹ {w}")
            continue
        A = polyline(c1[1], our_world)
        B = polyline(c2[1], lambda rc: fms_world(rc, cell_m, off_m))
        dev = hausdorff(A, B)
        la, lb = length(A), length(B)
        tag = "" if dev <= 0.5 else ("  ☹" if dev <= 2.0 else "  ☹☹ **다른 길**")
        if dev > 2.0:
            bad += 1
        rows.append((c1[0], c2[0], la, lb, dev))
        print(f"   {name:>26} {c1[0]:>9.0f} {c2[0]:>9.0f} "
              f"{la:>9.1f} {lb:>9.1f} {dev:>10.2f}{tag}")

    if rows:
        dt = [abs(a - b) / max(a, 1) for a, b, _, _, _ in rows]
        dl = [abs(a - b) for _, _, a, b, _ in rows]
        dv = [d for *_, d in rows]
        print(f"\n  비교된 쌍 {len(rows)}개 · 도달 실패 {unreach}개")
        print(f"    비용 차   평균 {100 * sum(dt) / len(dt):.1f}% · "
              f"최대 {100 * max(dt):.1f}%")
        print(f"    길이 차   평균 {sum(dl) / len(dl):.2f} m · 최대 {max(dl):.2f} m")
        print(f"    **이탈**  평균 {sum(dv) / len(dv):.2f} m · **최대 {max(dv):.2f} m**")
        print(f"    ☹☹ 2 m 넘게 갈린 쌍 **{bad}개**")
    print("\n  읽는 법")
    print("    이탈 <= 0.5 m   같은 통로다. 칸 규약 0.4 m 차이 수준")
    print("    0.5 ~ 2 m       같은 통로인데 칸이 밀렸다")
    print("    > 2 m           **다른 통로로 돌았다** — 같은 주문에 다른 길이 나온다")
    print("    ☹ 이건 **정적 최단경로**다. 함대 혼잡은 안 들어 있다")


if __name__ == "__main__":
    main()
