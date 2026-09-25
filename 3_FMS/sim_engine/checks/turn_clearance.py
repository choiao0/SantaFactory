# -*- coding: utf-8 -*-
# ============================================================
# 회전 여유 점검 — DES 궤적의 회전마다 「물리로 돌 수 있었나」를 잰다 (S15P21A106-277)
#
# 왜: 09-24 DES 피크 10분을 Isaac 이 재현하자 회전 관문에서 서로 기다리다 1분 만에 굳었다
#     (창 동작의 16~19 % 만 시작). 원인 후보가 둘이라 숫자로 가른다.
#
#       ① DES 가 정말 위험한 회전을 계획한다     → 금지 조합표(제어 오차 5 cm)에 걸린다 → DES 를 고친다
#       ② 계획은 안전한데 실행기 칸 관문이 과하다  → 앞 칸에 남의 몸이 **걸치기만** 해도 막는다
#
#     그때 운영 DES 발자국은 `exact`(앞 칸 규칙 없음)였고, Isaac 구간 재생은 앞 2칸 칸 관문(PIBT_FRONT_RULE=2)으로
#     돈다 — 둘이 다른 규칙을 봤다. 이 도구로 ①을 확인해 기본을 exact,ban 으로 바꿨다(계약 v3.17).
#
# 회전마다 세는 것
#   gate2 / gate4   남의 점유 칸(축·뒤)이 내 앞 2칸 / 4칸(+섞임 대각)에 있다 — Isaac 칸 관문이 막는다
#   banned          물리 팀 금지 조합표(checks/ban_table.py, 여유 5 cm)에 걸린다 — 실제 위험
#   gap             실제 회전을 쓸어 이웃 몸과의 최소 틈 [m] (여유 0, 칸 중심 자세)
#   over_block      칸 관문은 막는데 금지 조합표에 안 걸리고 틈도 10 cm 이상 — 과대 검출
#
# 이웃은 둘로 나눠 본다. DES 는 다틱 동작의 자세를 **첫 틱**에 바꾸고 떠나는 칸을 그 틱에 푼다.
#   동시   회전 틱 [k, k+TURN_TICKS) 에 같이 있던 자세(다가오는 로봇 포함) — 위 네 항목은 이것만 센다
#   인계   돌기 직전 틱 k−1 에만 있던 자세 — 막 떠난 몸(전진 4 · 후진 12틱 동안 빠진다)을 쓸고 들어간다
#          handoff_banned · handoff_gap_lt_100mm 로 따로 센다
#
# 사용:
#   python checks/turn_clearance.py <trajectories.json | slice.json(.gz) | 내보내기 폴더>
#          [--from S --to S] [--margin 0.05] [--json out.json]
#   slice 블록이 있으면 창 [t0, t0+window) 만 센다(구간 파일). 없으면 전부.
# ============================================================
import argparse
import gzip
import json
import math
import os
import sys
from dataclasses import dataclass

ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ENGINE_DIR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ban_table import banned, build_table, corners, overlap  # noqa: E402
from map_loader import CELL_M, OFFSET_M  # noqa: E402
from pibt.geometry import DIRS, TURN_TICKS, rear_cell  # noqa: E402

NEAR = 3             # 이웃 = 축이 체비쇼프 거리 3칸 안 (금지 조합표 span 과 같다)
SWEEP_STEPS = 31     # 90° 를 3° 씩 — 코 반경 0.559 에서 현 오차 0.2 mm
SAFE_GAP_M = 0.10    # 과대 검출 문턱 = 양쪽 제어 오차 5 cm × 2 (금지 조합표 여유와 같은 뜻)
N_EXAMPLES = 20


@dataclass(frozen=True)
class TurnEvent:
    robot: str
    k: int              # 전역 틱 번호 = round(t / dt) — 회전 자세로 바뀐 첫 틱
    t: float
    s0: tuple           # 돌기 전 (r, c, h)
    s1: tuple           # 돈 뒤 (r, c, h)


def _cell(x, y):
    """export_isaac._xy 의 역: x = (c+0.5)·CELL_M − OFFSET_M, y = (r+0.5)·CELL_M."""
    return int(round(y / CELL_M - 0.5)), int(round((x + OFFSET_M) / CELL_M - 0.5))


def _heading(yaw):
    """export_isaac._yaw 의 역: yaw = atan2(dr, dc)."""
    return DIRS.index((int(round(math.sin(yaw))), int(round(math.cos(yaw)))))


def states_from_export(doc):
    """{로봇: [(t, (r, c, h)), ...]} — 행 순서 그대로(틱마다 한 행)."""
    out = {}
    for rid, rows in doc["robots"].items():
        heads = doc["headings"][rid]
        if len(heads) != len(rows):
            raise ValueError(f"로봇 {rid}: robots {len(rows)}행 ≠ headings {len(heads)}행")
        out[rid] = [(float(t), (*_cell(x, y), _heading(yw))) for (t, x, y), (_, yw) in zip(rows, heads)]
    return out


def turn_events(states, dt=None):
    """제자리에서 헤딩만 바뀐 틱 = 회전 시작. 이동(칸이 바뀜)은 회전이 아니다."""
    ev = []
    for rid, seq in states.items():
        step = dt or _dt_of(seq)
        for (_, a), (t, b) in zip(seq, seq[1:]):
            if a[:2] == b[:2] and a[2] != b[2]:
                ev.append(TurnEvent(rid, int(round(t / step)), t, a, b))
    return ev


def _dt_of(seq):
    return (seq[1][0] - seq[0][0]) if len(seq) > 1 else 1.0


def _by_tick(states, dt):
    """{로봇: {전역 틱: 상태}} — 로봇마다 행 수가 달라도 시각으로 맞춘다."""
    return {rid: {int(round(t / dt)): s for t, s in seq} for rid, seq in states.items()}


def _seg_point(p, a, b):
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    L = dx * dx + dy * dy
    u = 0.0 if L == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L))
    return math.hypot(p[0] - ax - u * dx, p[1] - ay - u * dy)


def poly_gap(P, Q):
    """볼록 다각형 둘의 최소 거리. 겹치면 0."""
    if overlap(P, Q):
        return 0.0
    best = float("inf")
    for A, B in ((P, Q), (Q, P)):
        for p in A:
            for i in range(len(B)):
                best = min(best, _seg_point(p, B[i], B[(i + 1) % len(B)]))
    return best


def sweep_gap(s0, s1, other):
    """s0 → s1 제자리 회전을 쓸며 `other` 몸과의 최소 틈 [m]. 좌표는 ban_table 규약((r, c), 각 = h·π/2)."""
    sgn = 1 if (s1[2] - s0[2]) % 4 == 1 else -1
    th0 = s0[2] * math.pi / 2
    B = corners(other[0] * CELL_M, other[1] * CELL_M, other[2] * math.pi / 2, 0.0)
    best = float("inf")
    for k in range(SWEEP_STEPS):
        A = corners(s0[0] * CELL_M, s0[1] * CELL_M, th0 + sgn * (math.pi / 2) * k / (SWEEP_STEPS - 1), 0.0)
        best = min(best, poly_gap(A, B))
        if best == 0.0:
            break
    return best


def front_cells(s0, s1, diag=False):
    """Isaac 칸 관문의 앞 칸 — 2칸(옛·새 헤딩 앞), diag 면 섞임 대각 2칸을 더해 4칸 (pibt/geometry.front_cells 와 같다)."""
    (r, c, h), h2 = s0, s1[2]
    d1, d2 = DIRS[h], DIRS[h2]
    cells = {(r + d1[0], c + d1[1]), (r + d2[0], c + d2[1])}
    if diag:
        cells |= {(r + d1[0] - d2[0], c + d1[1] - d2[1]), (r - d1[0] + d2[0], c - d1[1] + d2[1])}
    return cells


def _cells(s):
    return {s[:2], rear_cell(*s)}


def _near(q, s0):
    return max(abs(q[0] - s0[0]), abs(q[1] - s0[1])) <= NEAR


def _neighbors(ev, ticks):
    """이웃 자세를 둘로 — (동시, 인계). 둘 다 {로봇: {상태, ...}}.

    동시   회전 틱 [k, k+TURN_TICKS) 에 같이 있던 자세 — DES 가 허락한 **배치**다.
    인계   돌기 직전 틱 k−1 에만 있던 자세 — 그 틱에 떠났다. DES 는 첫 틱에 칸을 풀지만 몸은
           전진 4 · 후진 12틱 동안 빠져나간다. 회전이 그 몸을 쓸고 들어가는지 본다.
    """
    now, before = {}, {}
    for rid, by_k in ticks.items():
        if rid == ev.robot:
            continue
        seen = {by_k[k] for k in range(ev.k, ev.k + TURN_TICKS) if k in by_k}
        seen = {q for q in seen if _near(q, ev.s0)}
        if seen:
            now[rid] = seen
        prev = by_k.get(ev.k - 1)
        if prev is not None and prev not in seen and _near(prev, ev.s0):
            before[rid] = {prev}
    return now, before


def judge(ev, near, tab):
    """회전 하나의 판정 — gate2·gate4·banned·gap 과 가장 가까운 이웃."""
    f2, f4 = front_cells(ev.s0, ev.s1), front_cells(ev.s0, ev.s1, diag=True)
    res = {"gate2": False, "gate4": False, "banned": False, "gap": None, "other": None, "other_state": None}
    for rid, qs in near.items():
        for q in qs:
            occ = _cells(q)
            res["gate2"] |= bool(occ & f2)
            res["gate4"] |= bool(occ & f4)
            res["banned"] |= banned(tab, ev.s0, ev.s1, [q])
            g = sweep_gap(ev.s0, ev.s1, q)
            if res["gap"] is None or g < res["gap"]:
                res.update(gap=g, other=rid, other_state=q)
    return res


def _window(doc, lo_s, hi_s):
    sl = doc.get("slice") or {}
    if lo_s is None and sl:
        lo_s = float(sl["t0_s"])
    if hi_s is None and sl:
        hi_s = float(sl["t0_s"]) + float(sl["window_s"])
    return lo_s, hi_s


def _example(ev, res):
    return {"t": round(ev.t, 3), "robot": ev.robot, "s0": list(ev.s0), "s1": list(ev.s1),
            "other": res["other"], "other_state": list(res["other_state"] or ()),
            "gap_m": None if res["gap"] is None else round(res["gap"], 4)}


def scan(doc, lo_s=None, hi_s=None, margin=0.05):
    """궤적 전체(또는 창)의 회전 판정 요약."""
    lo_s, hi_s = _window(doc, lo_s, hi_s)
    dt = float(doc["dt_s"])
    states = states_from_export(doc)
    ticks = _by_tick(states, dt)
    tab = build_table(CELL_M, margin)
    rep = {"window": [lo_s, hi_s], "margin_m": margin, "turns": 0, "gate2": 0, "gate4": 0,
           "banned": 0, "over_block": 0, "gap_lt_50mm": 0, "gap_lt_100mm": 0, "min_gap_m": None,
           "handoff_banned": 0, "handoff_gap_lt_100mm": 0,
           "examples": [], "examples_over_block": [], "examples_handoff": []}
    for ev in sorted(turn_events(states, dt), key=lambda e: (e.t, e.robot)):
        if (lo_s is not None and ev.t < lo_s) or (hi_s is not None and ev.t >= hi_s):
            continue
        rep["turns"] += 1
        now, before = _neighbors(ev, ticks)
        if before:
            ho = judge(ev, before, tab)
            rep["handoff_banned"] += ho["banned"]
            rep["handoff_gap_lt_100mm"] += ho["gap"] is not None and ho["gap"] < SAFE_GAP_M
            if ho["banned"] and len(rep["examples_handoff"]) < N_EXAMPLES:
                rep["examples_handoff"].append(_example(ev, ho))
        res = judge(ev, now, tab)
        rep["gate2"] += res["gate2"]
        rep["gate4"] += res["gate4"]
        rep["banned"] += res["banned"]
        g = res["gap"]
        if g is not None:
            rep["gap_lt_50mm"] += g < 0.05
            rep["gap_lt_100mm"] += g < SAFE_GAP_M
            rep["min_gap_m"] = g if rep["min_gap_m"] is None else min(rep["min_gap_m"], g)
        over = res["gate2"] and not res["banned"] and (g is None or g >= SAFE_GAP_M)
        rep["over_block"] += over
        if res["banned"] and len(rep["examples"]) < N_EXAMPLES:
            rep["examples"].append(_example(ev, res))
        if over and len(rep["examples_over_block"]) < N_EXAMPLES:
            rep["examples_over_block"].append(_example(ev, res))
    if rep["min_gap_m"] is not None:
        rep["min_gap_m"] = round(rep["min_gap_m"], 4)
    return rep


def load(path):
    """내보내기 폴더(trajectories.json), 평문 JSON, gzip JSON 을 받는다."""
    if os.path.isdir(path):
        path = os.path.join(path, "trajectories.json")
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def _pct(n, d):
    return f"{n:,} ({100.0 * n / d:.1f} %)" if d else f"{n:,}"


def main(argv=None):
    p = argparse.ArgumentParser(description="DES 궤적의 회전 여유 점검 (S15P21A106-277)")
    p.add_argument("path")
    p.add_argument("--from", dest="lo", type=float, default=None, help="창 시작 [s] (기본: slice t0 또는 전부)")
    p.add_argument("--to", dest="hi", type=float, default=None, help="창 끝 [s]")
    p.add_argument("--margin", type=float, default=0.05, help="금지 조합표 여유 [m] (제어 오차)")
    p.add_argument("--json", default=None, help="요약을 이 파일에 쓴다")
    a = p.parse_args(argv)
    rep = scan(load(a.path), a.lo, a.hi, a.margin)
    n = rep["turns"]
    print(f"창 {rep['window']} · 회전 {n:,}")
    print(f"  칸 관문 2칸 {_pct(rep['gate2'], n)} · 4칸 {_pct(rep['gate4'], n)}")
    print(f"  금지 조합표(여유 {a.margin * 1000:.0f} mm) {_pct(rep['banned'], n)}")
    print(f"  과대 검출(2칸이 막는데 틈 ≥ {SAFE_GAP_M * 1000:.0f} mm) {_pct(rep['over_block'], n)}")
    print(f"  틈 < 50 mm {_pct(rep['gap_lt_50mm'], n)} · < 100 mm {_pct(rep['gap_lt_100mm'], n)} · "
          f"최소 {rep['min_gap_m']}")
    print(f"  인계(막 떠난 몸을 쓸고 들어감) 조합표 {_pct(rep['handoff_banned'], n)} · "
          f"틈 < 100 mm {_pct(rep['handoff_gap_lt_100mm'], n)}")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=1)
    return rep


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
