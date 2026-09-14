# -*- coding: utf-8 -*-
# ============================================================
# 맵 로드 + 1.0m 다운샘플 + 스테이션 매핑 — 공용 모듈
#
# 맵 로드 규칙(장애물 값·다운샘플·스테이션 매핑·통로 행 범위)의 **단일 소스**다 (2026-09-07, S15P21A106-152).
# sim_v2 커널·스윕·A트랙 build_input·map/check_map_set 이 전부 여기를 import 한다. sim_v1_tasks.py(A* 기준선,
# 같은 규칙의 복사본)는 레거시 정리에서 삭제됨 — 패리티 값(2384틱/181.2 tasks/h)은 docs 에만 남는다.
# ============================================================
import json
import math
import os

import numpy as np

from topology_spec import WALL_A, load_spec  # noqa: F401  (통로·밴드 좌표, -139)

CELL_M, OFFSET_M = 1.0, 0.4
K, OX = round(CELL_M / 0.1), round(OFFSET_M / 0.1)
# 0.1 m 원본 셀값 중 장애물 (1 구조물·기둥 / 2 랙 / 5 컨베이어 / 6 바닥 파렛트).
OBSTACLE_VALUES = (1, 2, 5, 6)
# 랙 사이 세로 통로의 행 범위 [47, 68) — 통로차단(aisle_block) 구간이자 from_theta.VA_ROWS.
# 2026-09-03 맵 동기화 실측(랙 c±2 막힘 행 47~67). 2026-09-08(-139): 값은 wallA 스펙에서 온다.
AISLE_ROWS = WALL_A.va_rows

# 공식 맵 폴더 (3_FMS/map). charge_zone.json 이 여기 있고, 맵 세트 수신 후에는
# occupancy_grid/stations 도 여기서 읽는다 (docs/맵_충전존.md#fms-정답지-생성-절차).
MAP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "map")


def _padded_obstacles(grid01):
    """0.1 m 원본 → 장애물 uint8 (H·K, W·K): 왼쪽 OX 칸 패딩, K 배수로 오른·아래 패딩(패딩 = 장애물).
    load_map 의 다운샘플과 turn_mask 의 스윕 조회가 같은 좌표계를 보도록 한 곳에 둔다."""
    # 1=구조물 2=랙 5=컨베이어 6=바닥 파렛트 블록 (v5.8, 맵 세트 수신 후 등장 — 빠지면 그 위를 지나감)
    raw = np.isin(grid01, OBSTACLE_VALUES).astype(np.uint8)
    m2 = np.pad(raw, ((0, 0), (OX, 0)), constant_values=1)
    h, w = m2.shape
    return np.pad(m2, ((0, (-h) % K), (0, (-w) % K)), constant_values=1)


def load_map(base_dir=None, aisle_block=False):
    """0.1m 원본을 1.0m coarse로 다운샘플(max pooling, 보수적).
    base_dir 생략 = 공식 맵 폴더 MAP_DIR (3_FMS/map, build_fms_map.py 산출물).
    반환: (free (H,W) bool, st_cell {"kind[i]": (r,c)}, stations 원본 dict)"""
    if base_dir is None:
        base_dir = MAP_DIR
    grid01 = np.load(os.path.join(base_dir, "occupancy_grid.npy"))
    stations = json.load(open(os.path.join(base_dir, "stations.json"), encoding="utf-8"))
    m2 = _padded_obstacles(grid01)
    coarse = m2.reshape(m2.shape[0] // K, K, m2.shape[1] // K, K).max(axis=(1, 3))
    free = coarse == 0
    H, W = coarse.shape

    if aisle_block:
        # 렉 사이 통로 내부 = 피커 전용 구역, 로봇 통행 금지. 행 범위 = 랙 행(va_rows).
        # 2026-09-03 맵 동기화: 랙 1 m 연장으로 [48,68) → [47,68) (실측 c±2 막힘 행 47~67)
        # 2026-09-08(-139): 좌표를 맵 세트의 topology.json 에서 받는다. 공식 맵은 그 파일이
        # 없어 wallA 상수로 떨어지므로 결과는 이전과 비트 동일하다.
        spec = load_topology_spec(base_dir)
        r0, r1 = spec.va_rows
        for center in spec.va_centers:
            c0, c1 = spec.aisle_cols(center)
            free[r0:r1, c0:c1] = False

    return free, _station_cells(stations, free), stations


# ---- 회전 발자국 마스크 (S15P21A106-203, docs/2026-09-13_S15P21A106-203_회전발자국마스크_설계.md §2) ----
ROBOT_DIMS = (0.39, 1.11, 0.80)   # 기종 카드(선반형, 물리 팀 2026-09-13 확정): 구동축 앞·뒤·폭 (m)
_DIRS = ((1, 0), (0, 1), (-1, 0), (0, -1))   # pibt.geometry.DIRS 와 같은 순서 (0=N 1=E 2=S 3=W, (dr, dc))
_SAMPLE_M, _ANGLE_DEG = 0.05, 1


def front_swing(dims=ROBOT_DIMS):
    """회전 중 코가 앞 칸에 들어가는가: hypot(앞, 반폭) > 반 칸. (0.39, 0.80) → 0.559 > 0.5 → True."""
    return math.hypot(dims[0], dims[2] / 2) > CELL_M / 2


def _sweep_offsets(dims, margin, h, h2):
    """h→h2 90° 회전 중 차체(여유 포함) 가 지나는 0.1 m 칸 오프셋 (dy, dx) — 칸 중심 기준, 위치 불변.
    사각형 [-rear-m, front+m] × [-w/2-m, w/2+m] 을 0.05 m 로 표본화, 1° 간격으로 회전."""
    front, rear, width = dims
    a = np.arange(-rear - margin, front + margin + 1e-9, _SAMPLE_M)
    b = np.arange(-width / 2 - margin, width / 2 + margin + 1e-9, _SAMPLE_M)
    A, B = np.meshgrid(a, b, indexing="ij")
    A, B = A.ravel(), B.ravel()
    th0 = math.radians(90 * h)
    step = 1 if h2 == (h + 1) % 4 else -1
    angles = th0 + np.radians(step * np.arange(0, 90 + _ANGLE_DEG, _ANGLE_DEG))
    cos, sin = np.cos(angles)[:, None], np.sin(angles)[:, None]
    dy = A * cos - B * sin                       # 전방 (cos, sin), 좌측 (-sin, cos) — DIRS 순서 (dr, dc)
    dx = A * sin + B * cos
    half = K / 2
    oy = np.floor(half + dy / (CELL_M / K)).astype(np.int64)
    ox = np.floor(half + dx / (CELL_M / K)).astype(np.int64)
    return np.unique(np.stack([oy.ravel(), ox.ravel()], axis=1), axis=0)


def turn_mask_from_grid(grid01, dims=ROBOT_DIMS, margin=0.05):
    """0.1 m 원본 → bool[H, W, 4, 4]. [r, c, h, h2] = (r,c)에서 h→h2 90° 회전 시 차체 스윕이 장애물과 안 겹침.
    h2 ∉ {h±1} 은 False. 통행 불가 칸·범위 밖은 장애물로 본다(load_map 패딩 규칙과 같다)."""
    m2 = _padded_obstacles(grid01)
    H, W = m2.shape[0] // K, m2.shape[1] // K
    free = m2.reshape(H, K, W, K).max(axis=(1, 3)) == 0
    pad = 2 * K
    obst = np.pad(m2, pad, constant_values=1).astype(bool)
    rs, cs = np.nonzero(free)
    base_r, base_c = rs * K + pad, cs * K + pad
    mask = np.zeros((H, W, 4, 4), dtype=bool)
    for h in range(4):
        for h2 in ((h + 1) % 4, (h - 1) % 4):
            off = _sweep_offsets(dims, margin, h, h2)
            hit = obst[base_r[:, None] + off[:, 0], base_c[:, None] + off[:, 1]].any(axis=1)
            mask[rs, cs, h, h2] = ~hit
    return mask


def masked_turn_ratio(free, mask):
    """legacy 가 허용하는 (칸, 회전) 조합(양쪽 상태 valid + 대각 칸 free) 중 마스크가 금지한 비율 — SUMMARY turn_masked."""
    H, W = free.shape
    f = np.pad(free, 1, constant_values=False)
    allowed = masked = 0
    for h in range(4):
        for h2 in ((h + 1) % 4, (h - 1) % 4):
            d1, d2 = _DIRS[h], _DIRS[h2]
            # 뒤 칸 free(= 상태 valid) 두 개 + 대각 칸 free. f 는 1칸 패딩이라 인덱스 +1.
            rear1 = f[1 - d1[0]:H + 1 - d1[0], 1 - d1[1]:W + 1 - d1[1]]
            rear2 = f[1 - d2[0]:H + 1 - d2[0], 1 - d2[1]:W + 1 - d2[1]]
            diag = f[1 - d1[0] - d2[0]:H + 1 - d1[0] - d2[0], 1 - d1[1] - d2[1]:W + 1 - d1[1] - d2[1]]
            ok = free & rear1 & rear2 & diag
            allowed += int(ok.sum())
            masked += int((ok & ~mask[:, :, h, h2]).sum())
    return masked / allowed if allowed else 0.0


def masked_turn_ratio(free, mask):
    """legacy 가 허용하는 (칸, 회전) 조합(양쪽 상태 valid + 대각 칸 free) 중 마스크가 금지한 비율 — SUMMARY turn_masked."""
    H, W = free.shape
    f = np.pad(free, 1, constant_values=False)
    allowed = masked = 0
    for h in range(4):
        for h2 in ((h + 1) % 4, (h - 1) % 4):
            d1, d2 = _DIRS[h], _DIRS[h2]
            # 뒤 칸 free(= 상태 valid) 두 개 + 대각 칸 free. f 는 1칸 패딩이라 인덱스 +1.
            rear1 = f[1 - d1[0]:H + 1 - d1[0], 1 - d1[1]:W + 1 - d1[1]]
            rear2 = f[1 - d2[0]:H + 1 - d2[0], 1 - d2[1]:W + 1 - d2[1]]
            diag = f[1 - d1[0] - d2[0]:H + 1 - d1[0] - d2[0], 1 - d1[1] - d2[1]:W + 1 - d1[1] - d2[1]]
            ok = free & rear1 & rear2 & diag
            allowed += int(ok.sum())
            masked += int((ok & ~mask[:, :, h, h2]).sum())
    return masked / allowed if allowed else 0.0


def turn_mask(base_dir=None, dims=ROBOT_DIMS, margin=0.05):
    """`<base_dir>/occupancy_grid.npy` 로 turn_mask_from_grid. 시작 시 1회(< 1 s)."""
    if base_dir is None:
        base_dir = MAP_DIR
    return turn_mask_from_grid(np.load(os.path.join(base_dir, "occupancy_grid.npy")), dims, margin)


def load_topology_spec(map_dir=None):
    """`<map_dir>/topology.json` → TopologySpec, 없으면 wallA 상수 (topology_spec.WALL_A).

    맵 로드 규칙의 단일 소스가 여기라서 토폴로지 스펙도 여기를 통해 읽는다 — from_theta·
    build_input 이 각자 파일을 찾으면 격자와 토폴로지가 다른 세트에서 올 수 있다.
    """
    return load_spec(MAP_DIR if map_dir is None else map_dir)


def _station_cells(stations, free):
    """스테이션 좌표(m) → 격자 칸: 정확한 칸이 막혀 있으면 상하좌우 첫 free 칸으로 (v1 규칙)."""
    H, W = free.shape
    st_cell = {}
    for kind, pts in stations.items():
        if kind == "charge_zone":            # 사각형 목록(m) — 스테이션 점이 아님, load_charge_zone 이 읽음
            continue
        for i, (x, y) in enumerate(pts):
            r, c = int(y / CELL_M), int((x + OFFSET_M) / CELL_M)
            for rr, cc in [(r, c), (r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)]:
                if 0 <= rr < H and 0 <= cc < W and free[rr, cc]:
                    st_cell[f"{kind}[{i}]"] = (rr, cc)
                    break
    return st_cell


def load_charge_zone(free, map_dir=None):
    """`<map_dir>/charge_zone.json` 의 사각형(m)을 1 m 격자 bool 마스크로. 없으면 None.

    시뮬(존 내 복귀)과 A트랙 입력 텐서(zone_charging 채널)가 같은 존을 보도록
    여기 한 곳에만 둔다 — 두 곳에 두면 규약이 갈릴 때 AI가 배운 존과 시뮬이
    쓰는 존이 어긋난다. 좌표 규약은 load_map 의 스테이션 변환과 동일:
    칸 c ↔ x ∈ [c−OFFSET_M, c+1−OFFSET_M), 행 r ↔ y ∈ [r, r+1).
    반환 마스크는 사각형 그대로(장애물 포함) — 통행 가능 존 칸은 `mask & free`.
    `free` 는 격자 크기(H, W) 기준으로만 쓴다.
    """
    if map_dir is None:
        map_dir = MAP_DIR
    path = os.path.join(map_dir, "charge_zone.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        spec = json.load(f)
    H, W = free.shape
    mask = np.zeros((H, W), dtype=bool)
    for z in spec.get("charge_zone", ()):
        r0 = int(z["y0"] / CELL_M)
        r1 = int(z["y1"] / CELL_M)
        c0 = int((z["x0"] + OFFSET_M) / CELL_M)
        c1 = int((z["x1"] + OFFSET_M) / CELL_M)
        mask[max(r0, 0):min(r1, H), max(c0, 0):min(c1, W)] = True
    return mask


def load_rack_map(map_dir=None):
    """`<map_dir>/rack_buffers.json` 의 랙 필드("A2") → aisle_buf 인덱스 dict. 없으면 None.

    WMS 명시 주문(OrderStream orders=)의 rack_id 를 시뮬 픽업 지점으로 바꾸는 유일한 표.
    생성 규칙·검증은 map/build_rack_map.py (존 좌표 == aisle_buf 좌표 정확 일치, -156).
    """
    if map_dir is None:
        map_dir = MAP_DIR
    path = os.path.join(map_dir, "rack_buffers.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return {k: int(v) for k, v in json.load(f)["racks"].items()}


def zone_cells(free, zone_mask):
    """존 안 통행 가능 칸을 열 오름차순(통로 쪽 c103부터) → 행 오름차순으로.
    make_homes_zone 의 채움 순서이자 sim_v2 zone_goal 의 후보 순서(동률 결정론)."""
    rs, cs = np.nonzero(zone_mask & free)
    return sorted(zip(rs.tolist(), cs.tolist()), key=lambda rc: (rc[1], rc[0]))


def make_homes_zone(free, zone_mask, n_robots, spacing=2):
    """충전 존 초기 배치 (충전존_결정 §2 '통로 쪽부터, 몸 겹침 없이').
    zone_cells 순서로 훑으며 기존 홈과 체비쇼프 거리 ≥ spacing 인 칸을 채택.
    spacing=2: 2칸 차체가 어느 방향으로 서도 앞축 칸이 겹치지 않고 뒤 칸은 헤딩
    초기화가 골라 피한다 (간격 3은 용량 1/9 — 구현 설계 §3). 부족하면 assert."""
    homes = []
    for rc in zone_cells(free, zone_mask):
        if len(homes) >= n_robots:
            break
        if all(max(abs(rc[0] - hr), abs(rc[1] - hc)) >= spacing for hr, hc in homes):
            homes.append(rc)
    assert len(homes) >= n_robots, f"충전 존 용량 부족: {len(homes)}칸(간격 {spacing}) < {n_robots}대"
    return homes


def _kind_list(st_cell, kind):
    """`kind[i]` 칸을 i 순서로 (있는 만큼)."""
    out = []
    while f"{kind}[{len(out)}]" in st_cell:
        out.append(st_cell[f"{kind}[{len(out)}]"])
    return out


def make_homes(free, st_cell, n_robots):
    """로봇 홈 = 충전기/대기열 셀, 초과분은 충전존 인근 여유 칸 (v1 동일).

    충전기·대기열 개수는 맵 세트에서 온다 — wallA 는 6+6=12 라 기존과 같다 (-139).
    초과분 채우기(_fill_extra_homes)는 wallA 좌표 창을 쓰므로 합성 창고에서는 못 쓴다.
    합성 창고는 충전 존 복귀(기본값, --fixed-homes 없음)로 돌려야 한다.
    """
    homes = _kind_list(st_cell, "charger") + _kind_list(st_cell, "charge_q")
    if n_robots > len(homes):
        _fill_extra_homes(free, st_cell, homes, n_robots)
    assert n_robots <= len(homes), \
        f"홈 슬롯 부족: {len(homes)} < {n_robots} (합성 창고면 --fixed-homes 를 빼고 충전 존으로)"
    return homes[:n_robots]


def _fill_extra_homes(free, st_cell, homes, n_robots):
    """12대 초과분: 충전존 인근(행 45~76, 열 100~111) free 칸 중 기존 홈과 맨해튼 ≥ 2 인 칸을 행 우선으로 채운다 (v1 동일).

    좌표 창이 wallA 전용이다. 여기 값을 바꾸면 --fixed-homes 12대 초과 기준선이 전부 바뀌므로
    합성 창고를 위해 일반화하지 않았다 (-139) — 합성 창고는 충전 존 경로를 쓴다."""
    H, W = free.shape
    taken = set(homes) | set(st_cell.values())
    for r in range(45, min(77, H)):
        for c in range(100, min(112, W)):
            if len(homes) >= n_robots:
                break
            if free[r, c] and (r, c) not in taken and \
                    all(abs(r - hr) + abs(c - hc) >= 2 for hr, hc in homes):
                homes.append((r, c))
                taken.add((r, c))
