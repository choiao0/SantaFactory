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
def run(keys, hard_mode=False):
    res=[]
    for h0,h1 in turns:
        pr = parts(R0,C0,h0,h1); ca = cells_model(R0,C0,h0,h1)
        ga = frozenset(pr[k] for k in keys)
        sa = ga & ca if not hard_mode else frozenset()
        ha = (ca - sa) | (ga if hard_mode else frozenset())
        pa = rot_poses(R0,C0,h0,h1)
        ok=h=0; w=9.9; u=len(ha|ga)
        for dr in range(-3,4):
         for dc in range(-3,4):
          for g0 in range(4):
           for g1 in ((g0+1)%4,(g0-1)%4):
            B=(R0+dr,C0+dc,g0,g1); prb=parts(*B); cb=cells_model(*B)
            gb=frozenset(prb[k] for k in keys)
            sb = gb & cb if not hard_mode else frozenset()
            hb = (cb - sb) | (gb if hard_mode else frozenset())
            if body(*B) & ha or body(R0,C0,h0,h1) & hb: continue
            if not hard_mode and ((B[0],B[1]) in ga or (R0,C0) in gb): continue
            ok+=1
            gap=min(g.body_gap(x,y) for x in pa for y in rot_poses(*B))
            if gap<=0.0: h+=1
            w=min(w,gap)
        res.append((ok,h,w,u))
    return res
for name,keys in RULES.items():
    r=run(keys)
    print(f"     {name:<14}{min(x[0] for x in r):>8}{sum(x[1] for x in r):>6}"
          f"{min(x[2] for x in r)*1000:>12.1f}{max(x[3] for x in r):>11}")
r=run(("f0","f1"), hard_mode=True)
print(f"     {HARD5:<14}{min(x[0] for x in r):>8}{sum(x[1] for x in r):>6}"
      f"{min(x[2] for x in r)*1000:>12.1f}{max(x[3] for x in r):>11}")
