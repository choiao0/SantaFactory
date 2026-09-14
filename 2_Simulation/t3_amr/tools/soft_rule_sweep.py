# -*- coding: utf-8 -*-
"""4칸 vs 6칸 — 장점이 실제로 있나. 세 가지를 따로 묻는다.

  Q1  6칸의 뒤 대각은 hard(스윕) 안에 있나?
      있다면 soft 로 올리는 순간 hard 에서 **빠진다** (isaac_drive: hard = cells - soft).
      그러면 상대 '몸'이 들어올 수 있게 된다 -> 안전 약화지 강화가 아니다.
  Q2  4칸과 6칸의 합법쌍 차이 2쌍은 구체적으로 뭔가.
  Q3  200.0 mm 바닥을 만드는 건 mA/mB 인가.
"""
import os, sys
sys.path.insert(0, os.path.join(os.environ["W"], "path"))
import pibt_core_v2                      # noqa
from pibt_core import DIRS, occupied, swing_cells
from isaac_drive import YAW, wrap
from pibt_scene import make_geom

P = float(os.environ.get("PITCH", "1.0"))
S = int(os.environ.get("SAMPLES", "32"))
g = make_geom(P)


def cells_of(r, c, h0, h1):
    """A 가 제자리 회전할 때 몸이 쓸고 가는 칸 = 현행 hard."""
    return {(r, c)} | set(swing_cells(r, c, h0, h1)) | set(occupied((r, c, h0)))


def parts(r, c, h0, h1):
    d1, d2 = DIRS[h0], DIRS[h1]
    return dict(
        f0=(r + d1[0], c + d1[1]),
        f1=(r + d2[0], c + d2[1]),
        nose=(r + d1[0] + d2[0], c + d1[1] + d2[1]),
        rear=(r - d1[0] - d2[0], c - d1[1] - d2[1]),
        mA=(r + d1[0] - d2[0], c + d1[1] - d2[1]),
        mB=(r - d1[0] + d2[0], c - d1[1] + d2[1]),
    )


RULES = {
    "앞2":                 ("f0", "f1"),
    "앞2+mA+mB (4칸)":     ("f0", "f1", "mA", "mB"),
    "앞2+코+mA+mB (5칸)":  ("f0", "f1", "nose", "mA", "mB"),
    "앞2+대각4 (6칸)":     ("f0", "f1", "nose", "rear", "mA", "mB"),
}


def soft_of(rule, r, c, h0, h1):
    p = parts(r, c, h0, h1)
    return {p[k] for k in RULES[rule]}


def body(r, c, h0, h1):
    return set(occupied((r, c, h0))) | set(occupied((r, c, h1)))


def poses(r, c, h0, h1):
    x, y = g.cell_center((r, c))
    a0 = YAW[g.phys_heading(h0)]
    a1 = a0 + wrap(YAW[g.phys_heading(h1)] - a0)
    return [(x, y, a0 + (a1 - a0) * i / S) for i in range(S + 1)]


# ─────────────────────────── Q1 ───────────────────────────
print(f"pitch {P}\n")
print("Q1  6칸의 각 칸이 스윕(hard 후보) 안에 있나 — 있으면 soft 로 올릴 때 hard 에서 빠진다")
print(f"    {'회전':<10}{'스윕칸수':>8}   " + "".join(f"{k:>7}" for k in
      ("f0", "f1", "nose", "rear", "mA", "mB")))
demote = {k: 0 for k in ("f0", "f1", "nose", "rear", "mA", "mB")}
turns = [(h0, h1) for h0 in range(4) for h1 in ((h0 + 1) % 4, (h0 - 1) % 4)]
for h0, h1 in turns:
    cs = cells_of(5, 5, h0, h1)
    p = parts(5, 5, h0, h1)
    marks = []
    for k in ("f0", "f1", "nose", "rear", "mA", "mB"):
        inside = p[k] in cs
        demote[k] += inside
        marks.append("스윕O" if inside else "  -  ")
    print(f"    {h0}->{h1:<7}{len(cs):>8}   " + "".join(f"{m:>7}" for m in marks))
print("    " + "-" * 60)
print("    스윕 안에 든 횟수(8회전 중): " +
      "  ".join(f"{k} {v}" for k, v in demote.items()))
print()

# ─────────────────────────── Q2 · Q3 ───────────────────────────
R0 = C0 = 5
cand = [(R0 + dr, C0 + dc, h0, h1)
        for dr in range(-3, 4) for dc in range(-3, 4)
        for h0 in range(4) for h1 in ((h0 + 1) % 4, (h0 - 1) % 4)]


def run(rule, A):
    """hard = cells - soft 로 **실제 구현대로** 계산해서 합법/접촉을 센다."""
    sa, ca = soft_of(rule, *A), cells_of(*A)
    ha = ca - sa
    pa = poses(*A)
    ok, hit, worst, wB = [], [], 9.9, None
    for B in cand:
        sb, cb = soft_of(rule, *B), cells_of(*B)
        hb = cb - sb
        if body(*B) & ha or body(*A) & hb:          # 몸 vs 몸-금지칸
            continue
        if (B[0], B[1]) in sa or (A[0], A[1]) in sb:  # 축 vs 축-금지칸
            continue
        ok.append(B)
        gap = min(g.body_gap(u, v) for u in pa for v in poses(*B))
        if gap <= 0.0:
            hit.append(B)
        if gap < worst:
            worst, wB = gap, B
    return ok, hit, worst, wB


print("Q2·Q3  A 의 8개 회전 전부 — 최악값 (hard = cells - soft 로 계산)")
print(f"    {'규칙':<22}{'합법쌍최악':>10}{'접촉':>6}{'최소여유mm':>12}")
res = {}
for rule in RULES:
    rows = [run(rule, (R0, C0, h0, h1)) for h0, h1 in turns]
    res[rule] = rows
    n = min(len(r[0]) for r in rows)
    h = sum(len(r[1]) for r in rows)
    w = min(r[2] for r in rows)
    print(f"    {rule:<22}{n:>10}{h:>6}{w*1000:>12.1f}")

print("\nQ2  4칸에만 있고 6칸에 없는 합법쌍 (A h1->0 기준)")
A = (R0, C0, 1, 0)
o4 = {tuple(b) for b in run("앞2+mA+mB (4칸)", A)[0]}
o6 = {tuple(b) for b in run("앞2+대각4 (6칸)", A)[0]}
only4, only6 = sorted(o4 - o6), sorted(o6 - o4)
print(f"    4칸에만: {len(only4)}쌍  {only4[:8]}")
print(f"    6칸에만: {len(only6)}쌍  {only6[:8]}")

print("\nQ3  A h1->0 에서 각 규칙의 hard / soft / 합집합 칸수")
for rule in RULES:
    s, c = soft_of(rule, *A), cells_of(*A)
    print(f"    {rule:<22} hard {len(c - s)}  soft {len(s)}  "
          f"hard∪soft {len((c - s) | s)}   hard={sorted(c - s)}")
