# -*- coding: utf-8 -*-
import json
import math
import os

import numpy as np

from map_loader import (CELL_M, MAP_DIR, OFFSET_M, load_charge_zone,
                        load_map)
from pibt_core import DIRS, TURN_TICKS

from .common import OUT


def _grow_rect(m, r, c):
    """(r, c)에서 시작하는 True 블록을 오른쪽·아래로 그리디 확장 → (r2, c2) (배타 끝). sim_v1 과 동일 규칙."""
    hh, ww = m.shape
    c2 = c
    while c2 < ww and m[r, c2]:
        c2 += 1
    r2 = r + 1
    while r2 < hh and m[r2, c:c2].all() \
            and (c == 0 or not m[r2, c - 1]) \
            and (c2 == ww or not m[r2, c2]):
        r2 += 1
    return r2, c2


def _rects_from_mask(mask, cell=0.1, min_area=0.04):
    """0.1 m 마스크 → 축 정렬 사각형 (x, y, w, h)[m], 그리디 병합 (sim_v1 과 동일)."""
    m = mask.copy()
    hh, ww = m.shape
    out = []
    for r in range(hh):
        c = 0
        while c < ww:
            if not m[r, c]:
                c += 1
                continue
            r2, c2 = _grow_rect(m, r, c)
            m[r:r2, c:c2] = False
            w_m, h_m = (c2 - c) * cell, (r2 - r) * cell
            if w_m * h_m >= min_area:
                out.append((round(c * cell, 2), round(r * cell, 2), round(w_m, 2), round(h_m, 2)))
            c = c2
    return out


def _xy(r, c):
    return round((c + 0.5) * CELL_M - OFFSET_M, 2), round((r + 0.5) * CELL_M, 2)


def _yaw(h):
    """방향 인덱스 → yaw[rad], x축(동, 열 증가) 기준 반시계. y 는 행 증가 방향 (리플레이 atan2 규약과 동일)."""
    if h is None:
        return 0.0
    dr, dc = DIRS[h]
    return round(math.atan2(dr, dc), 4)


def _load_zones():
    """3_FMS/map/charge_zone.json → [{id, rect=[x, y, w, h]}] (m)."""
    zones = []
    zpath = os.path.join(MAP_DIR, "charge_zone.json")
    if os.path.exists(zpath):
        with open(zpath, encoding="utf-8") as f:
            for z in json.load(f).get("charge_zone", ()):
                zones.append(dict(id=z.get("id", ""), rect=[z["x0"], z["y0"],
                                                            round(z["x1"] - z["x0"], 2), round(z["y1"] - z["y0"], 2)]))
    return zones


def _grid_char(free0, zmask, free, r, c):
    return "z" if zmask[r, c] else "." if free[r, c] else "a" if free0[r, c] else "#"


def _grid_rows(ctx):
    """1 m 격자 행 문자열 (results/fleet_replay.html 범용 플레이어용, 추가 키 — isaac_replay.py 는 무시):
    '#' 장애물 · '.' 통행 가능 · 'a' 랙 사이 통로(aisle_block 으로 막힌 피커 전용 칸) · 'z' 충전 존 칸"""
    free0 = load_map(aisle_block=False)[0]
    zmask = load_charge_zone(ctx.free)
    zmask = (zmask & ctx.free) if zmask is not None else np.zeros_like(ctx.free)
    return ["".join(_grid_char(free0, zmask, ctx.free, r, c) for c in range(ctx.W)) for r in range(ctx.H)]


def _build_scene(a, ctx, model, zones):
    grid01 = np.load(os.path.join(MAP_DIR, "occupancy_grid.npy"))
    return {
        "meta": dict(variant=a.variant, source="sim_v2_tasks.py", model=model,
                     cell_fine_m=0.1, coordinate="crop-relative meters, z-up",
                     robot_dim_m=[1.50, 0.92, 1.60], speed_mps=a.speed, dt_s=a.dt, turn_ticks=TURN_TICKS,
                     pose_ref="front-axle cell center (drive axle is 0.39 m behind the front end)"),
        "obstacles": {
            "structure":      dict(height=4.0, rects=_rects_from_mask(grid01 == 1)),
            "racks":          dict(height=6.0, rects=_rects_from_mask(grid01 == 2)),
            "conveyor_table": dict(height=0.9, rects=_rects_from_mask(grid01 == 5)),
            "floor_pallets":  dict(height=1.2, rects=_rects_from_mask(grid01 == 6)),
        },
        "zones": zones,
        "stations": {k: v for k, v in ctx.stations.items() if k != "charge_zone"},
        "station_cells": {k: list(v) for k, v in ctx.st_cell.items()},      # 격자 (r, c) — 플레이어용
        "grid": _grid_rows(ctx),
        "nodes": [list(_xy(r, c)) for r, c in zip(*np.nonzero(ctx.free))],
    }


def _build_trajectories(kernel, model, dt):
    trajs, heads, acts = {}, {}, {}
    for rid, log in kernel.export_log.items():
        trajs[str(rid)] = [[round(tt * dt, 3), *_xy(r, c)] for tt, r, c, h, act in log]
        heads[str(rid)] = [[round(tt * dt, 3), _yaw(h)] for tt, r, c, h, act in log]
        acts[str(rid)] = [[round(tt * dt, 3), act] for tt, r, c, h, act in log if act != "move"]
    return dict(dt_s=dt, model=model, robots=trajs, headings=heads, actions=acts,
                tasks=[{k: v for k, v in tk.items()} for tk in kernel.tasks_done])


def export_isaac(a, kernel, ctx):
    """sim_v1 포맷(scene.json + trajectories.json, 크롭 기준 m, z-up) 유지 + headings(틱별 yaw)·actions(이동 외 틱)·
    model·zones 추가 키. 2_Simulation/isaac_replay.py 는 robots 의 [t, x, y] 3원소만 읽으므로 그대로 재생되고,
    yaw 사용은 Isaac 파트가 headings 를 읽도록 한 줄 추가. 좌표: x = (c+0.5)·CELL_M − OFFSET_M, y = (r+0.5)·CELL_M.
    헤딩 모델의 pos 는 앞축 칸 → x, y 는 앞축 중심 (구동축까지 0.39 m — 리플레이 쪽 오프셋 선택)."""
    exp_dir = os.path.join(OUT, f"isaac_export_{a.variant}")
    os.makedirs(exp_dir, exist_ok=True)
    model = "heading" if kernel.heading else "cell"
    zones = _load_zones()
    scene = _build_scene(a, ctx, model, zones)
    with open(os.path.join(exp_dir, "scene.json"), "w", encoding="utf-8") as f:
        json.dump(scene, f, indent=1)
    traj = _build_trajectories(kernel, model, a.dt)
    with open(os.path.join(exp_dir, "trajectories.json"), "w", encoding="utf-8") as f:
        json.dump(traj, f, indent=1)
    n_rect = sum(len(v["rects"]) for v in scene["obstacles"].values())
    n_pt = sum(len(v) for v in traj["robots"].values())
    print(f"[EXPORT] {os.path.relpath(exp_dir, OUT)}: 장애물 박스 {n_rect}개, 존 {len(zones)}개, "
          f"로봇 {len(traj['robots'])}대 × 궤적 {n_pt}점 (headings·actions 포함)")
