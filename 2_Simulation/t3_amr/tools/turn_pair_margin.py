# -*- coding: utf-8 -*-
"""회전 옆에 선 로봇 — **여유 0.05 를 로봇끼리에 넣으면 얼마를 잃나** (S15P21A106-240).

무엇이 밝혀졌길래
-----------------
`s103_gate2` 가 `t=5,610s` 에서 실제 접촉으로 죽었다. 쌍 (6,9) · 최소거리
**0.000 m** · 둘 다 회전이고 한쪽은 ADG 때문에 **서 있었다**.

기하를 전수 조사하니 원인이 하나로 좁혀졌다.

    계획기가 허용하는 배치 1,376개 중
        틈 41.3 ~ 100 mm    **80개 (5.8 %)**
        100 mm 이상       1,296개

    기하 여유 = pitch - 폭/2 - 코반경 = 1.0 - 0.400 - 0.5587 = **41.3 mm**
    제어 허용 = tol.pos 50 mm x **2대** = **100 mm**

**허용이 예산의 2.4배다.** 둘 다 규칙을 지켜도 닿을 수 있고, 22,638 액션 만에 닿았다.

여유 0.05 가 왜 답인가
----------------------
양쪽 몸을 0.05 m 씩 부풀리면 틈 100 mm 미만이 겹침으로 잡힌다 — `tol.pos` 를
기하로 옮긴 것이다. FMS-32 §2 가 **우리 t3-31 §3 을 근거로** 제안한 그 값이고,
그쪽은 그걸 **랙 마스크**에 넣었다. 로봇끼리에는 아직 아무도 안 넣었다.

    pitch 1.0   여유 0.05  ->  금지 조합 **20개** (좌회전 10 · 우회전 10)
    pitch 1.2   여유 0.05  ->  금지 조합 **0개**       <- N 이 여기서도 갈린다

☹ 실측 접촉이 그 표 안에 있다 — 좌회전 `(1,1)h1`. **예측한 자리에서 닿았다.**

★ 표가 **위치 불변**이라 틱마다 SAT 를 돌 필요가 없다. 두 로봇이 같은 격자
  위에 있으므로 판정이 (상대 칸 · 상대 헤딩 · 회전 방향) 에만 의존한다.

이 도구가 하는 일
-----------------
`swing_overlap.py` 와 **같은 판**을 돌려(같은 시드·틱·배차) 그 표가 실제로
몇 번 걸리는지 센다. 금지의 **가격표**다.

    source paths.sh
    SEEDS=2,5,9 python tools/turn_pair_margin.py
    PIBT_PITCH=1.2 python tools/turn_pair_margin.py     # 0 이어야 한다
    MARGIN=0.03 python tools/turn_pair_margin.py        # 여유를 낮춰 보기

☹ 한계 — 이건 **기존 계획을 사후에 훑는 것**이다. 규칙을 켜면 계획이 달라지므로
  실제 대가는 이 수와 다르다. 여기 수치는 **「얼마나 자주 그 배치가 생기나」**로
  읽어야 한다. 0 에 가까우면 켜도 싸고, 크면 경로가 통째로 바뀐다는 뜻이다.
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.environ["W"], "path"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import isaac_drive as D                                 # noqa: E402
from pibt_core import TURN_TICKS                        # noqa: E402
import swing_overlap as SO                              # noqa: E402

MARGIN = float(os.environ.get("MARGIN", "0.05"))
DIRS = [(1, 0), (0, 1), (-1, 0), (0, -1)]


# ---------------------------------------------------------------------------
# 상수표 — 차체 사각형으로 직접 만든다. `RobotGeom` 의 치수를 그대로 쓴다.
# ---------------------------------------------------------------------------
def _corners(cx, cy, th, g, m):
    c, s = math.cos(th), math.sin(th)
    f, b, hw = g.front_len + m, g.rear_len + m, 0.5 * g.width + m
    return [(cx + ax * c - ay * s, cy + ax * s + ay * c)
            for ax, ay in ((f, hw), (f, -hw), (-b, -hw), (-b, hw))]


def _overlap(A, B):
    """SAT — 볼록 사각형 둘이 겹치나."""
    for poly in (A, B):
        for i in range(4):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % 4]
            ax, ay = -(y2 - y1), (x2 - x1)
            pa = [ax * x + ay * y for x, y in A]
            pb = [ax * x + ay * y for x, y in B]
            if max(pa) < min(pb) or max(pb) < min(pa):
                return False
    return True


def _rear(cell, h):
    return (cell[0] - DIRS[h][0], cell[1] - DIRS[h][1])


def _swing(h0, h1):
    a, b = _rear((0, 0), h0), _rear((0, 0), h1)
    return {a, b, (a[0] + b[0], a[1] + b[1])}


def build_table(geom, margin, steps=91, span=3):
    """{회전방향: {(상대칸, 상대헤딩)}} — A 의 헤딩을 0 으로 놓은 좌표계.

    A 가 이미 예약하는 칸(자기 2칸 + 스윙 3칸)에 걸리는 배치는 **뺀다** —
    그건 계획기가 이미 막고 있어 새 규칙이 아니다.
    """
    out, h0 = {}, 0
    for sgn in (+1, -1):
        h1 = (h0 + sgn) % 4
        res = {(0, 0), _rear((0, 0), h0), _rear((0, 0), h1)} | _swing(h0, h1)
        hit = set()
        for dr in range(-span, span + 1):
            for dc in range(-span, span + 1):
                for hb in range(4):
                    if {(dr, dc), _rear((dr, dc), hb)} & res:
                        continue
                    B = _corners(dr * geom.pitch, dc * geom.pitch,
                                 hb * math.pi / 2, geom, margin)
                    if any(_overlap(_corners(0.0, 0.0,
                                             sgn * k * (math.pi / 2) / (steps - 1),
                                             geom, margin), B)
                           for k in range(steps)):
                        hit.add(((dr, dc), hb))
        out[sgn] = hit
    return out


def _rel(cell_a, h0, cell_b, h_b):
    """B 를 A 의 헤딩이 0 인 좌표계로 옮긴다."""
    dr, dc = cell_b[0] - cell_a[0], cell_b[1] - cell_a[1]
    c, s = DIRS[h0]                       # h0 를 +r 로 되돌리는 회전
    return (dr * c + dc * s, -dr * s + dc * c), (h_b - h0) % 4


def scan_pairs(geom, history, table):
    """회전 **5틱 창 내내** 표에 걸리는 이웃이 있나 — `scan_guard` 와 같은 창."""
    hits, kinds = [], {}
    for t in range(len(history) - 1):
        st0, st1 = history[t], history[t + 1]
        agents = sorted(st0)
        for a in agents:
            s0, s1 = st0[a], st1[a]
            if s0[:2] != s1[:2] or s0[2] == s1[2]:       # 회전만
                continue
            sgn = 1 if (s1[2] - s0[2]) % 4 == 1 else -1
            tab = table[sgn]
            for dt in range(TURN_TICKS):
                tt = t + dt
                if tt + 1 >= len(history):
                    break
                q0 = history[tt]
                if q0.get(a, s1)[:2] != s0[:2]:          # 회전이 끝났다
                    break
                for b in agents:
                    if b == a:
                        continue
                    key = _rel(s0[:2], s0[2], q0[b][:2], q0[b][2])
                    if key in tab:
                        stay = tuple(q0[b][:2]) == tuple(history[tt + 1][b][:2])
                        k = (f"{key[0]}h{key[1]}"
                             f"{'(상주)' if stay else ''}")
                        kinds[k] = kinds.get(k, 0) + 1
                        hits.append((tt, a, b, key, dt, stay))
    return hits, kinds


def run_history(seed):
    """`swing_overlap.run` 과 **같은 판**을 돌리되 `history` 를 돌려준다.

    저쪽은 집계만 주고 `history` 를 안 준다. 여기서 다시 만들면 판이 달라지므로
    설정을 한 글자도 안 바꾸고 그대로 옮긴다 (`swing_overlap.py:214`).
    """
    import pibt_scene
    from lifelong import Kernel, run_lifelong             # noqa: E402
    geom, free, starts, goals = pibt_scene.setup_lifelong(
        SO.MAP, SO.N, SO.PITCH, seed, "cross", verbose=False)
    zone = pibt_scene.charge_zone_cells(free, geom)

    kw = {}
    if SO.BATTERY:
        from battery import BatteryKernel                 # noqa: E402
        kw = dict(kernel_cls=BatteryKernel,
                  kernel_kw=dict(docks=list(pibt_scene.charge_docks(free, geom)),
                                 pitch=geom.pitch, seed=seed))
    if SO.DISPATCH != "fms":
        from dispatch import with_policy                  # noqa: E402
        kw["kernel_cls"] = with_policy(kw.get("kernel_cls") or Kernel, SO.DISPATCH)
        kw.setdefault("kernel_kw", {})

    history, _cells, li = run_lifelong(
        free, starts, goals, horizon=SO.HORIZON, seed=seed, order_gap=SO.GAP,
        shifts=("in", "out", "out"), zone_cells=zone, order_end=None, **kw)
    return geom, history, li


def main():
    print(f"회전-이웃 여유 검사 — n {SO.N} · pitch {SO.PITCH} · {SO.HORIZON}틱 "
          f"· 여유 **{MARGIN:.2f} m** · 배차 {SO.DISPATCH}")
    import pibt_scene
    geom = pibt_scene.make_geom(SO.PITCH)

    table = build_table(geom, MARGIN)
    n = sum(len(v) for v in table.values())
    print(f"  차체 {geom.front_len:.2f}+{geom.rear_len:.2f} m · 폭 {geom.width:.2f} m")
    print(f"  ★ 금지 조합 **{n}개** (좌 {len(table[1])} · 우 {len(table[-1])})")
    if n == 0:
        print("     여유를 줘도 걸리는 배치가 없다 — 이 격자에서는 규칙이 불필요하다.")
    else:
        for sgn in (1, -1):
            if table[sgn]:
                s = sorted(table[sgn])
                print(f"     회전 {'좌' if sgn > 0 else '우'}: "
                      + " ".join(f"{c}h{h}" for c, h in s))
    print()

    tot_hit = tot_tick = tot_task = tot_turn = 0
    allk = {}
    for seed in SO.SEEDS:
        g2, history, li = run_history(seed)
        hits, kinds = scan_pairs(g2, history, table)
        turns = sum(1 for t in range(len(history) - 1)
                    for a in history[t]
                    if history[t][a][:2] == history[t + 1][a][:2]
                    and history[t][a][2] != history[t + 1][a][2])
        tasks = li.get("tasks_done") or 0
        ticks = len(history) - 1
        print(f"  seed {seed:>2}  틱 {ticks:,} · 태스크 {tasks:,} · 회전 {turns:,}"
              f"  ->  **걸림 {len(hits):,}건**"
              f"  (회전당 {len(hits) / max(turns, 1):.3f})")
        for k, v in kinds.items():
            allk[k] = allk.get(k, 0) + v
        tot_hit += len(hits)
        tot_tick += ticks
        tot_task += tasks
        tot_turn += turns

    print(f"\n  합계  틱 {tot_tick:,} · 태스크 {tot_task:,} · 회전 {tot_turn:,}"
          f"  ->  **걸림 {tot_hit:,}건**")
    if tot_turn:
        print(f"        회전 {tot_hit / tot_turn * 100:.1f}% 가 이 규칙에 걸린다")
    if allk:
        print("\n  어느 배치에서 (상대칸 h상대헤딩):")
        for k, v in sorted(allk.items(), key=lambda kv: -kv[1])[:12]:
            print(f"     {k:>18}  {v:6,}")
    print("\n  읽는 법")
    print("    ☹ 이건 **기존 계획을 사후에 훑은 것**이다. 규칙을 켜면 계획이 달라진다")
    print("    회전당 비율이 작으면 켜도 싸다 — 그 배치가 애초에 드물다는 뜻")
    print("    (상주) 는 상대가 **그 자리에 서 있었다**는 표시 — ADG 로는 못 잡는 쪽")


if __name__ == "__main__":
    main()
