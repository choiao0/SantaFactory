# -*- coding: utf-8 -*-
"""**시작 위치가 같은가** — 우리 `_assign_slots` vs FMS `make_homes_zone`.

규칙이 다르다.
    우리   charge_zone(pitch) 물리 슬롯 **2.4 m 간격** · 좌측 하단부터
           + **헤딩 서쪽(3) 우선** 2패스 (동벽이라 안쪽을 봐야 한다)
    FMS    zone_cells(free, zone_mask) 순서 · **체비쇼프 >= 2칸**
           헤딩 제약 없음 (헤딩 초기화가 따로 고른다)

칸 규약도 0.4 m 밀려 있으므로 **월드 좌표(m)로 되돌려** 맞댄다.
"""
import os, sys
sys.path.insert(0, os.path.join(os.environ["W"], "path"))
import numpy as np
import pibt_core_v2 as _pc                      # sim_engine 을 sys.path 에
import pibt_scene as PS

N = int(os.environ.get("N", "12"))
PITCH = float(os.environ.get("PIBT_PITCH", "1.0"))
SEED = int(os.environ.get("PIBT_SEED", "103"))
FMS_MAP = os.environ.get("FMS_MAP",
                         os.path.join(os.environ["W"], "..", "..", "3_FMS", "map"))

geom, free, starts, goals = PS.setup_lifelong(os.environ["MAP"], N, PITCH, SEED,
                                              "cross", verbose=False)
ours = {a: (s[0], s[1], s[2]) for a, s in starts.items()}

import map_loader as ML
ab = bool(getattr(PS._CFG, "AISLE_BLOCK", False)) if PS._CFG else False
ffree, st_cell, _st = ML.load_map(FMS_MAP, aisle_block=ab)
zm = ML.load_charge_zone(ffree, FMS_MAP)
homes = ML.make_homes_zone(ffree, zm & ffree, N)

def ow(rc):   # 우리 칸 -> 월드 (origin = pitch/2)
    return (PITCH / 2 + rc[1] * PITCH, PITCH / 2 + rc[0] * PITCH)
def fw(rc):   # FMS 칸 -> 월드
    return ((rc[1] + 0.5) * ML.CELL_M - ML.OFFSET_M, (rc[0] + 0.5) * ML.CELL_M)

print(f"대수 {N} · pitch {PITCH} · 시드 {SEED} · 통로차단 {ab}")
print(f"우리 격자 {free.shape} · FMS 격자 {ffree.shape}\n")
print("   {:>4} {:>14} {:>18} | {:>14} {:>18}".format(
    "로봇", "우리 칸(h)", "우리 월드 (x, y)", "FMS 칸", "FMS 월드 (x, y)"))
for i in range(N):
    o = ours.get(i)
    f = homes[i] if i < len(homes) else None
    ox, oy = ow(o[:2]) if o else (float("nan"),) * 2
    fx, fy = fw(f) if f else (float("nan"),) * 2
    d = ((ox - fx) ** 2 + (oy - fy) ** 2) ** 0.5 if o and f else float("nan")
    print(f"   {i:>4} {str(o):>14} ({ox:>7.2f},{oy:>7.2f}) | "
          f"{str(f):>14} ({fx:>7.2f},{fy:>7.2f})   차 {d:>6.2f} m")

OW = {ow(v[:2]) for v in ours.values()}
FW = {fw(h) for h in homes[:N]}
same = sum(1 for p in OW if any(abs(p[0]-q[0]) < 0.51 and abs(p[1]-q[1]) < 0.51 for q in FW))
print(f"\n   집합으로 봐서 0.5 m 안에 짝이 있는 것 **{same}/{N}**")
print(f"   우리 헤딩 분포 {dict(sorted({v[2]: sum(1 for u in ours.values() if u[2]==v[2]) for v in ours.values()}.items()))}"
      f"   (3=서쪽)")
