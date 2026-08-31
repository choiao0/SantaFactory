# -*- coding: utf-8 -*-
# ============================================================
# 맵 로드 + 1.0m 다운샘플 + 스테이션 매핑 — 공용 모듈
#
# sim_v1_tasks.py의 로드 규칙(L51-75, L192-206)과 동일. v1은 B-1e 벤치마크
# 기준선 보존 원칙에 따라 수정하지 않고 중복인 채로 둔다 — 규칙을 바꾸면
# 반드시 양쪽을 함께 고칠 것.
# ============================================================
import json
import os

import numpy as np

CELL_M, OFFSET_M = 1.0, 0.4
K, OX = round(CELL_M / 0.1), round(OFFSET_M / 0.1)


def load_map(base_dir, aisle_block=False):
    """0.1m 원본을 1.0m coarse로 다운샘플(max pooling, 보수적).
    반환: (free (H,W) bool, st_cell {"kind[i]": (r,c)}, stations 원본 dict)"""
    grid01 = np.load(os.path.join(base_dir, "occupancy_grid.npy"))
    stations = json.load(open(os.path.join(base_dir, "stations.json")))
    raw = np.isin(grid01, (1, 2, 5)).astype(np.uint8)   # 1=구조물 2=랙 5=컨베이어
    m2 = np.pad(raw, ((0, 0), (OX, 0)), constant_values=1)
    h, w = m2.shape
    m2 = np.pad(m2, ((0, (-h) % K), (0, (-w) % K)), constant_values=1)
    coarse = m2.reshape(m2.shape[0] // K, K, m2.shape[1] // K, K).max(axis=(1, 3))
    free = coarse == 0
    H, W = coarse.shape

    if aisle_block:
        # 렉 통로 내부(y48~67) = 피커 전용 구역, 로봇 통행 금지
        for k in range(11):
            c = int((35.1 + 6 * k + OFFSET_M) / CELL_M)
            free[48:68, c - 1:c + 2] = False

    st_cell = {}
    for kind, pts in stations.items():
        for i, (x, y) in enumerate(pts):
            r, c = int(y / CELL_M), int((x + OFFSET_M) / CELL_M)
            for rr, cc in [(r, c), (r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)]:
                if 0 <= rr < H and 0 <= cc < W and free[rr, cc]:
                    st_cell[f"{kind}[{i}]"] = (rr, cc)
                    break
    return free, st_cell, stations


def make_homes(free, st_cell, n_robots):
    """로봇 홈 = 충전기/대기열 셀, 12대 초과분은 충전존 인근 여유 칸 (v1 동일)."""
    H, W = free.shape
    homes = [st_cell[f"charger[{i}]"] for i in range(6)] + \
            [st_cell[f"charge_q[{i}]"] for i in range(6)]
    if n_robots > len(homes):
        taken = set(homes) | set(st_cell.values())
        for r in range(45, min(77, H)):
            for c in range(100, min(112, W)):
                if len(homes) >= n_robots:
                    break
                if free[r, c] and (r, c) not in taken and \
                        all(abs(r - hr) + abs(c - hc) >= 2 for hr, hc in homes):
                    homes.append((r, c))
                    taken.add((r, c))
    assert n_robots <= len(homes), f"홈 슬롯 부족: {len(homes)}"
    return homes[:n_robots]
