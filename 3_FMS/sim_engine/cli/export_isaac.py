# -*- coding: utf-8 -*-
import json
import os

import numpy as np

from map_loader import (CELL_M, MAP_DIR, OFFSET_M, load_charge_zone,
                        load_map)
from pibt_core import DIRS, TURN_TICKS

from .common import DT, OUT, SPEED

def export_isaac(a, kernel, ctx):
    """sim_v1 포맷(scene.json + trajectories.json, 크롭 기준 m, z-up) 유지 + headings(틱별 yaw)·actions(이동 외 틱)·
    model·zones 추가 키. 2_Simulation/isaac_replay.py 는 robots 의 [t, x, y] 3원소만 읽으므로 그대로 재생되고,
    yaw 사용은 Isaac 파트가 headings 를 읽도록 한 줄 추가. 좌표: x = (c+0.5)·CELL_M − OFFSET_M, y = (r+0.5)·CELL_M.
    헤딩 모델의 pos 는 앞축 칸 → x, y 는 앞축 중심 (구동축까지 0.39 m — 리플레이 쪽 오프셋 선택)."""
    import math

    exp_dir = os.path.join(OUT, f"isaac_export_{a.variant}")
    os.makedirs(exp_dir, exist_ok=True)
    grid01 = np.load(os.path.join(MAP_DIR, "occupancy_grid.npy"))
    model = "heading" if kernel.heading else "cell"

    def rects_from_mask(mask, cell=0.1, min_area=0.04):
        """0.1 m 마스크 → 축 정렬 사각형 (x, y, w, h)[m], 그리디 병합 (sim_v1 과 동일)."""
        m = mask.copy()
        hh, ww = m.shape
        out = []
        for r in range(hh):
            c = 0
            while c < ww:
                if m[r, c]:
                    c2 = c
                    while c2 < ww and m[r, c2]:
                        c2 += 1
                    r2 = r + 1
                    while r2 < hh and m[r2, c:c2].all() \
                            and (c == 0 or not m[r2, c - 1]) \
                            and (c2 == ww or not m[r2, c2]):
                        r2 += 1
                    m[r:r2, c:c2] = False
                    w_m, h_m = (c2 - c) * cell, (r2 - r) * cell
                    if w_m * h_m >= min_area:
                        out.append((round(c * cell, 2), round(r * cell, 2), round(w_m, 2), round(h_m, 2)))
                    c = c2
                else:
                    c += 1
        return out

    def xy(r, c):
        return round((c + 0.5) * CELL_M - OFFSET_M, 2), round((r + 0.5) * CELL_M, 2)

    def yaw(h):
        """방향 인덱스 → yaw[rad], x축(동, 열 증가) 기준 반시계. y 는 행 증가 방향 (리플레이 atan2 규약과 동일)."""
        if h is None:
            return 0.0
        dr, dc = DIRS[h]
        return round(math.atan2(dr, dc), 4)

    zones = []
    zpath = os.path.join(MAP_DIR, "charge_zone.json")
    if os.path.exists(zpath):
        with open(zpath, encoding="utf-8") as f:
            for z in json.load(f).get("charge_zone", ()):
                zones.append(dict(id=z.get("id", ""), rect=[z["x0"], z["y0"],
                                                            round(z["x1"] - z["x0"], 2), round(z["y1"] - z["y0"], 2)]))
    # 1 m 격자 행 문자열 (results/fleet_replay.html 범용 플레이어용, 추가 키 — isaac_replay.py 는 무시):
    #   '#' 장애물 · '.' 통행 가능 · 'a' 랙 사이 통로(aisle_block 으로 막힌 피커 전용 칸) · 'z' 충전 존 칸
    free0 = load_map(aisle_block=False)[0]
    zmask = load_charge_zone(ctx.free)
    zmask = (zmask & ctx.free) if zmask is not None else np.zeros_like(ctx.free)
    grid_rows = ["".join("z" if zmask[r, c] else "." if ctx.free[r, c] else "a" if free0[r, c] else "#"
                         for c in range(ctx.W)) for r in range(ctx.H)]
    scene = {
        "meta": dict(variant=a.variant, source="sim_v2_tasks.py", model=model,
                     cell_fine_m=0.1, coordinate="crop-relative meters, z-up",
                     robot_dim_m=[1.44, 0.641, 0.22], speed_mps=SPEED, dt_s=DT, turn_ticks=TURN_TICKS,
                     pose_ref="front-axle cell center (drive axle is 0.39 m behind the front end)"),
        "obstacles": {
            "structure":      dict(height=4.0, rects=rects_from_mask(grid01 == 1)),
            "racks":          dict(height=6.0, rects=rects_from_mask(grid01 == 2)),
            "conveyor_table": dict(height=0.9, rects=rects_from_mask(grid01 == 5)),
            "floor_pallets":  dict(height=1.2, rects=rects_from_mask(grid01 == 6)),
        },
        "zones": zones,
        "stations": {k: v for k, v in ctx.stations.items() if k != "charge_zone"},
        "station_cells": {k: list(v) for k, v in ctx.st_cell.items()},      # 격자 (r, c) — 플레이어용
        "grid": grid_rows,
        "nodes": [list(xy(r, c)) for r, c in zip(*np.nonzero(ctx.free))],
    }
    with open(os.path.join(exp_dir, "scene.json"), "w", encoding="utf-8") as f:
        json.dump(scene, f, indent=1)

    trajs, heads, acts = {}, {}, {}
    for rid, log in kernel.export_log.items():
        trajs[str(rid)] = [[round(tt * DT, 3), *xy(r, c)] for tt, r, c, h, act in log]
        heads[str(rid)] = [[round(tt * DT, 3), yaw(h)] for tt, r, c, h, act in log]
        acts[str(rid)] = [[round(tt * DT, 3), act] for tt, r, c, h, act in log if act != "move"]
    with open(os.path.join(exp_dir, "trajectories.json"), "w", encoding="utf-8") as f:
        json.dump(dict(dt_s=DT, model=model, robots=trajs, headings=heads, actions=acts,
                       tasks=[{k: v for k, v in tk.items()} for tk in kernel.tasks_done]), f, indent=1)
    n_rect = sum(len(v["rects"]) for v in scene["obstacles"].values())
    n_pt = sum(len(v) for v in trajs.values())
    print(f"[EXPORT] {os.path.relpath(exp_dir, OUT)}: 장애물 박스 {n_rect}개, 존 {len(zones)}개, "
          f"로봇 {len(trajs)}대 × 궤적 {n_pt}점 (headings·actions 포함)")
