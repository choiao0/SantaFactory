# -*- coding: utf-8 -*-
"""문서 §2·§4 의 숫자를 **한 설정으로** 전부 다시 잰다. 정합이 목적이다."""
import os, sys, math
sys.path.insert(0, os.path.join(os.environ["W"], "path"))
import pibt_core_v2                      # noqa
from pibt_core import DIRS, occupied, swing_cells
from isaac_drive import YAW, wrap
from pibt_scene import make_geom

P = float(os.environ.get("PITCH", "1.0"))
S = 32
g = make_geom(P)
R0 = C0 = 5
turns = [(h0, h1) for h0 in range(4) for h1 in ((h0 + 1) % 4, (h0 - 1) % 4)]


def parts(r, c, h0, h1):
    d1, d2 = DIRS[h0], DIRS[h1]
    return dict(f0=(r+d1[0], c+d1[1]), f1=(r+d2[0], c+d2[1]),
                nose=(r+d1[0]+d2[0], c+d1[1]+d2[1]),
                rear=(r-d1[0]-d2[0], c-d1[1]-d2[1]),
                mA=(r+d1[0]-d2[0], c+d1[1]-d2[1]),
                mB=(r-d1[0]+d2[0], c-d1[1]+d2[1]))


RULES = {"앞2": ("f0","f1"), "4칸": ("f0","f1","mA","mB"),
         "5칸": ("f0","f1","nose","mA","mB"),
         "6칸": ("f0","f1","nose","rear","mA","mB")}
HARD5 = "앞2를 hard 로"


def cells_model(r,c,h0,h1):
    return {(r,c)} | set(swing_cells(r,c,h0,h1)) | set(occupied((r,c,h0)))
def body(r,c,h0,h1):
    return set(occupied((r,c,h0))) | set(occupied((r,c,h1)))
def rot_poses(r,c,h0,h1):
    x,y = g.cell_center((r,c)); a0 = YAW[g.phys_heading(h0)]
    a1 = a0 + wrap(YAW[g.phys_heading(h1)] - a0)
    return [(x,y,a0+(a1-a0)*i/S) for i in range(S+1)]
def rest_pose(r,c,h):
    x,y = g.cell_center((r,c)); return [(x,y,YAW[g.phys_heading(h)])]

print(f"=== pitch {P}  ·  A 축 ({R0},{C0})  ·  회전 {S}단계 샘플링 ===\n")

# ── §2 (1) A 회전 · B 정지 ──────────────────────────────────────────────
print("§2 (1)  A 가 회전 · B 는 정지 — 예약이 겹치지 않는 배치만")
tot = hit = 0; worst = 9.9
for h0,h1 in turns:
    ha = cells_model(R0,C0,h0,h1)
    pa = rot_poses(R0,C0,h0,h1)
    for dr in range(-3,4):
        for dc in range(-3,4):
            for hb in range(4):
                B = (R0+dr, C0+dc, hb)
                if set(occupied(B)) & ha:      # 몸끼리 겹치는 배치는 애초에 불법
                    continue
                tot += 1
                gap = min(g.body_gap(u,v) for u in pa for v in rest_pose(*B))
                if gap <= 0.0: hit += 1
                worst = min(worst, gap)
print(f"        배치 {tot}   접촉 {hit}   최악 {worst*1000:+.1f} mm\n")

# ── §2 (2) A·B 동시 회전 (규칙 없음) ────────────────────────────────────
print("§2 (2)  A·B 동시 회전 — 규칙 없음 (현행 hard 만)")
per = []
for h0,h1 in turns:
    ha = cells_model(R0,C0,h0,h1); pa = rot_poses(R0,C0,h0,h1)
    ok = h = 0; w = 9.9
    for dr in range(-3,4):
        for dc in range(-3,4):
            for g0 in range(4):
                for g1 in ((g0+1)%4,(g0-1)%4):
                    B = (R0+dr,C0+dc,g0,g1)
                    if body(*B) & ha or body(R0,C0,h0,h1) & cells_model(*B):
                        continue
                    ok += 1
                    gap = min(g.body_gap(u,v) for u in pa for v in rot_poses(*B))
                    if gap <= 0.0: h += 1
                    w = min(w,gap)
    per.append((ok,h,w))
print(f"        합법쌍  최소 {min(p[0] for p in per)}  최대 {max(p[0] for p in per)}")
print(f"        접촉    합 {sum(p[1] for p in per)}   최악 회전에서 {max(p[1] for p in per)}")
print(f"        최악 여유 {min(p[2] for p in per)*1000:+.1f} mm\n")

# ── §2 (3) 정지 두 대 ───────────────────────────────────────────────────
print("§2 (3)  정지 두 대가 이웃")
tot = hit = 0; worst = 9.9
for ha_ in range(4):
    A = (R0,C0,ha_)
    for dr in range(-2,3):
        for dc in range(-2,3):
            for hb in range(4):
                B = (R0+dr,C0+dc,hb)
                if (dr,dc)==(0,0) or set(occupied(A)) & set(occupied(B)): continue
                tot += 1
                gap = min(g.body_gap(u,v) for u in rest_pose(*A) for v in rest_pose(*B))
                if gap <= 0.0: hit += 1
                worst = min(worst,gap)
print(f"        배치 {tot}   접촉 {hit}   최악 {worst*1000:+.1f} mm\n")

# ── §4 규칙별 ───────────────────────────────────────────────────────────
print("§4  규칙별 (hard = 모델스윕 - soft,  8회전 최악값)")
print(f"     {'규칙':<14}{'합법쌍':>8}{'접촉':>6}{'최소여유mm':>12}{'hard∪soft':>11}")
def b_turns():
    """B 후보 — A 둘레 7x7 칸 × 8가지 90° 회전."""
    return [(R0+dr, C0+dc, g0, g1)
            for dr in range(-3,4) for dc in range(-3,4)
            for g0 in range(4) for g1 in ((g0+1)%4, (g0-1)%4)]


def zones(r, c, h0, h1, keys, hard_mode):
    """회전 하나가 잡는 칸 — (guard, hard).

    guard  규칙이 지정한 칸 그대로. soft 로 쓰면 상대의 **축**만 막는다
    hard   상대 **몸**이 못 들어오는 칸
             soft 모드   모델스윕에서 guard 를 덜어낸다  (ca - ga∩ca)
             hard 모드   반대로 guard 를 몸 금지로 더한다 (ca | ga)
    """
    pr = parts(r, c, h0, h1)
    ca = cells_model(r, c, h0, h1)
    ga = frozenset(pr[k] for k in keys)
    return (ga, ca | ga) if hard_mode else (ga, ca - (ga & ca))


def pair_ok(A, B, za, zb, hard_mode):
    """A·B 가 동시에 돌아도 되는가. za·zb 는 zones() 결과."""
    ga, ha = za
    gb, hb = zb
    if body(*B) & ha or body(*A) & hb:
        return False                       # 몸끼리 — 어느 규칙이든 금지
    if hard_mode:
        return True
    # soft 로 쓸 때만 묻는다: 상대의 **축**이 guard 안에 있으면 안 된다
    return not ((B[0],B[1]) in ga or (A[0],A[1]) in gb)


def one_turn(A, keys, hard_mode):
    """A 의 회전 하나 — (합법쌍, 접촉, 최악여유, hard∪guard 칸수)."""
    za = zones(*A, keys, hard_mode)
    pa = rot_poses(*A)
    ok = hit = 0; w = 9.9
    for B in b_turns():
        if not pair_ok(A, B, za, zones(*B, keys, hard_mode), hard_mode):
            continue
        ok += 1
        gap = min(g.body_gap(x,y) for x in pa for y in rot_poses(*B))
        if gap <= 0.0: hit += 1
        w = min(w, gap)
    return ok, hit, w, len(za[1] | za[0])


def run(keys, hard_mode=False):
    """8가지 회전 전부. 표에는 이 목록의 최소/합/최대가 들어간다."""
    return [one_turn((R0,C0,h0,h1), keys, hard_mode) for h0,h1 in turns]
for name,keys in RULES.items():
    r=run(keys)
    print(f"     {name:<14}{min(x[0] for x in r):>8}{sum(x[1] for x in r):>6}"
          f"{min(x[2] for x in r)*1000:>12.1f}{max(x[3] for x in r):>11}")
r=run(("f0","f1"), hard_mode=True)
print(f"     {HARD5:<14}{min(x[0] for x in r):>8}{sum(x[1] for x in r):>6}"
      f"{min(x[2] for x in r)*1000:>12.1f}{max(x[3] for x in r):>11}")
