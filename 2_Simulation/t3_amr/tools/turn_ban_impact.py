# -*- coding: utf-8 -*-
"""회전을 금지하면 **무엇을 잃나** — 고치기 전에 값을 본다 (S15P21A106-240).

무엇이 밝혀졌길래
-----------------
`A3#253 turn(46,68,3)->(46,68,0)` 이 시작 48.4 mm -> 끝 363.4 mm 로 밀렸고,
원인이 제어가 아니라 **계획**이었다. 그 회전은 -47도 지점에서 차체가 랙을
**58 mm 파고든다**(`tools/turn_sweep_check.py`). Isaac 의 랙 콜라이더가
밀어내면서 회전 중심이 축을 벗어나고(역산 (+187,-133)·|r|229 — 어느 부품도
아니다), 다음 액션이 진입 362 mm 를 물려받는다. 한 액션이 지울 수 있는
상한은 90 mm 라 구조적으로 못 끝내고, 제어기는 평형에 앉아 w=0 이 된다.

맵 전체로는 회전 가능 전이 30,487건 중 **960건(3.1%)** 이 파고든다.

왜 바로 안 고치나
-----------------
`turn_ok` 는 `HGraph` 가 **테이블에 미리 구워** 쓰므로(스윙 대각 칸 인덱스),
`dispatch.py` 처럼 함수를 감싸는 우회가 안 통한다. 공유 코드(FMS 원본)를
고쳐야 하고, 그러면 FMS 패리티와 표 F(전 수치 재측정)가 걸린다.

**그래서 고치기 전에 잃는 것을 먼저 센다.** 이 도구가 그것만 한다.

    python tools/turn_ban_impact.py
    BAN_MM=20 python tools/turn_ban_impact.py     # 20 mm 넘게 파고들 때만 금지

재는 것
-------
    ① 금지되는 회전 수
    ② **모든 회전을 잃는 칸** — 그 칸에 잘못된 헤딩으로 들어가면 직진밖에 못 한다
    ③ 상태 그래프 도달성 — 스테이션까지 못 가게 되는 상태가 생기나
    ④ 경로 길이 — 평균·p95 가 얼마나 늘어나나

간선 규칙은 `_pibt_core_vendor.candidates_h` 를 그대로 옮겼다.
전진 `_inb(free, 앞칸)` · 회전 `turn_ok` · 후진 `valid_state(free, 뒤칸)`.

☹ 한계 — 이건 **정적 그래프**다. PIBT 는 함대 알고리즘이라 실제 처리량은
  혼잡으로 더 나빠질 수 있다. 여기 수치는 **최선의 경우**로 읽어야 한다.
"""
import heapq
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.environ["W"], "path"))
os.environ.setdefault("PIBT_RECOVER", "0")
import pibt_scene as PS                                # noqa: E402
import pibt_core_v2 as PC                              # noqa: E402
import isaac_drive as D                                # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from turn_sweep_check import load_mask, penetrate      # noqa: E402

PITCH = float(os.environ.get("PIBT_PITCH", "1.0"))
MAP = os.environ.get("PIBT_MAP", os.path.join(os.environ["W"], "warehouse/map"))
BAN_MM = float(os.environ.get("BAN_MM", "0"))
DIRS = [(1, 0), (0, 1), (-1, 0), (0, -1)]


def banned_turns(free, geom, mask):
    """금지할 (r, c, h, h2) 집합. 침투 > BAN_MM 인 것."""
    R, C = free.shape
    ban, seen = set(), 0
    for r in range(R):
        for c in range(C):
            if not free[r, c]:
                continue
            for h in range(4):
                for h2 in ((h + 1) % 4, (h - 1) % 4):
                    if not PC.turn_ok(free, r, c, h, h2):
                        continue
                    seen += 1
                    # ★ 칸 판정으로 미리 거르지 **않는다.** `mode="cross"` 는
                    #   칸의 중앙 행·열만 보므로 「칸은 비었는데 귀퉁이는
                    #   막힌」 경우를 놓친다 — 거르면 그게 통째로 빠진다.
                    #   빈 창이면 `penetrate` 가 바로 빠져나오므로 싸다.
                    pen, _a, _g = penetrate(mask, geom, r, c, h, h2)
                    if pen * 1000.0 > BAN_MM:
                        ban.add((r, c, h, h2))
    return ban, seen


def edges(free, r, c, h, ban):
    """이 상태에서 나가는 간선 [(다음 상태, 비용)] — candidates_h 와 같은 규칙."""
    out = []
    dr, dc = DIRS[h]
    rr, cc = r + dr, c + dc
    H, W = free.shape
    if 0 <= rr < H and 0 <= cc < W and free[rr, cc]:
        out.append(((rr, cc, h), float(D.MOVE_TICKS)))
    for h2 in ((h + 1) % 4, (h - 1) % 4):
        if PC.turn_ok(free, r, c, h, h2) and (r, c, h, h2) not in ban:
            out.append(((r, c, h2), float(D.TURN_TICKS)))
    br, bc = r - dr, c - dc
    if PC.valid_state(free, (br, bc, h)):
        out.append(((br, bc, h), float(D.MOVE_TICKS) * D.REVERSE_FACTOR))
    return out


def dijkstra_to(free, goal_cell, ban):
    """goal 칸(방향 무관)까지의 비용. 역방향 간선으로 한 번에 푼다."""
    H, W = free.shape
    INF = float("inf")
    dist = {}
    pq = []
    for h in range(4):
        if PC.valid_state(free, (goal_cell[0], goal_cell[1], h)):
            s = (goal_cell[0], goal_cell[1], h)
            dist[s] = 0.0
            heapq.heappush(pq, (0.0, s))
    # 역간선을 만들기보다, 정방향 간선을 훑어 역으로 완화한다 (상태 수가 작다)
    rev = {}
    for r in range(H):
        for c in range(W):
            if not free[r, c]:
                continue
            for h in range(4):
                if not PC.valid_state(free, (r, c, h)):
                    continue
                for nxt, w in edges(free, r, c, h, ban):
                    rev.setdefault(nxt, []).append(((r, c, h), w))
    while pq:
        d, s = heapq.heappop(pq)
        if d > dist.get(s, INF):
            continue
        for p, w in rev.get(s, ()):
            nd = d + w
            if nd < dist.get(p, INF):
                dist[p] = nd
                heapq.heappush(pq, (nd, p))
    return dist


def main():
    geom = PS.make_geom(PITCH)
    free, _k = PS.build_free(MAP, PITCH)
    mask, src = load_mask(MAP)
    H, W = free.shape
    states = [(r, c, h) for r in range(H) for c in range(W) if free[r, c]
              for h in range(4) if PC.valid_state(free, (r, c, h))]
    print(f"  맵 {free.shape} · 상태 {len(states):,}개 · 마스크 {src}")
    print(f"  금지 기준: 침투 > {BAN_MM:.0f} mm\n")

    ban, seen = banned_turns(free, geom, mask)
    print(f"  ① 회전 전이 {seen:,}건 중 **금지 {len(ban):,}건** "
          f"({100.0 * len(ban) / max(seen, 1):.1f}%)")

    # ② 모든 회전을 잃는 (칸, 헤딩)
    lost = 0
    for (r, c, h) in states:
        ok = [h2 for h2 in ((h + 1) % 4, (h - 1) % 4)
              if PC.turn_ok(free, r, c, h, h2) and (r, c, h, h2) not in ban]
        had = [h2 for h2 in ((h + 1) % 4, (h - 1) % 4)
               if PC.turn_ok(free, r, c, h, h2)]
        if had and not ok:
            lost += 1
    print(f"  ② **회전을 통째로 잃는 (칸,헤딩) {lost:,}개** "
          f"({100.0 * lost / max(len(states), 1):.2f}%)")
    if lost:
        print("     이 수 하나만 보고 판단하지 말 것 — **거리장이 금지를 반영**하므로")
        print("     계획이 애초에 그 회전을 안 쓰고 돌아간다. 진짜 비용은 ③④ 다.")
        print(f"     (꼬리 스윙 반지름 {np.hypot(geom.rear_len, geom.width / 2):.3f} m 가")
        print(f"      반칸 {PITCH / 2:.2f} m 보다 크면 제자리 회전은 **항상** 이웃을")
        print("      침범한다. pitch 1.2 로 올려도 마찬가지다 — 실측으로 확인했다.)")

    # ③④ 스테이션 몇 곳으로 도달성·거리 비교
    try:
        # {카테고리: [(r,c)...]} 다. 카테고리 이름이 아니라 **칸**을 써야 한다.
        by_cat = PS.station_cells(free, geom, MAP)
        cells = sorted({rc for pts in by_cat.values() for rc in pts})
    except Exception as e:
        print(f"  ☹ 스테이션을 못 읽었다 ({e!r}) — ③④ 는 건너뛴다")
        return
    goals = cells[:: max(1, len(cells) // 6)][:6]
    print(f"\n  ③④ 스테이션 {len(cells)}곳 중 {len(goals)}곳으로 비교\n")
    print("     {:>12} {:>10} {:>10} {:>9} {:>9}".format(
        "목표칸", "도달 전", "도달 후", "평균+", "p95+"))
    for g in goals:
        d0 = dijkstra_to(free, g, set())
        d1 = dijkstra_to(free, g, ban)
        both = [s for s in states if s in d0 and s in d1]
        if not both:
            print(f"     {str(g):>12}  비교 불가")
            continue
        diff = sorted(d1[s] - d0[s] for s in both)
        mean = sum(diff) / len(diff)
        p95 = diff[min(len(diff) - 1, int(len(diff) * 0.95))]
        print(f"     {str(g):>12} {len(d0):>10,} {len(d1):>10,} "
              f"{mean:>8.2f}틱 {p95:>8.2f}틱")

    print()
    print("  읽는 법")
    print("    ② 가 0 이 아니면 그 칸에 잘못된 헤딩으로 들어간 로봇은 **직진밖에 못 한다**")
    print("    ③ 의 「도달 후」가 줄면 **갈 수 없게 된 상태**가 생긴 것이다 — 그건 못 받는다")
    print("    ④ 가 크면 경로가 길어져 처리량이 준다. 표 F 대로 전 수치 재측정이다")
    print("    ☹ 정적 그래프다. 실제로는 혼잡이 더해져 **이보다 나쁘다**")


if __name__ == "__main__":
    main()
