# -*- coding: utf-8 -*-
# ============================================================
# B-2: from_theta() — θ 11개를 칸별 통행 비용(Guidance)으로 변환
# (설계: docs/2026-09-01_B2_from_theta_설계.md, 명세: AI입출력명세서 §11~13)
#
# 토폴로지는 wallA 전용 규칙 기반 추출 (A트랙 topology_tensor 15ch는
# 스키마 합의 대기 — 여기서는 from_theta에 필요한 최소 필드만).
# dist_map은 비가중 BFS 그대로 — θ는 PIBT 후보 score의 edge_cost 항으로만
# 작용한다 (설계 §4: 엣지 비용 차 2 초과 시 우회 강제 가능).
# ============================================================
import json
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 3_FMS/
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from contracts.guidance_types import Guidance, GuidanceTheta  # noqa: E402

from map_loader import CELL_M, OFFSET_M  # noqa: E402
from pibt_core import DIRS  # noqa: E402  (0=북 1=동 2=남 3=서)

CLIP_LO, CLIP_HI = 0.5, 5.0            # 명세 §12 출력 범위

# wallA 좌표 상수 (설계 §2, 2026-09-01 실측)
VA_ROWS = (48, 67)                     # 세로 통로 행 [48, 67) — 랙 내부
VA_XS_M = [35.1 + 6 * k for k in range(11)]   # 통로 중심 x (m), 서쪽부터
BAND_S_ROWS = (40, 48)                 # 남쪽 가로 간선 [40, 48)
BAND_N_ROWS = (67, 74)                 # 북쪽 가로 간선 [67, 74)
BAND_W_COLS = (20, 32)                 # 서쪽 연결 통로 [20, 32)
BAND_E_COLS = (99, 109)                # 동쪽 연결 통로 [99, 109)
JUNCTION_ROWS = (47, 67)               # 통로가 간선에 접속하는 목


class Topology:
    """from_theta가 소비하는 wallA 토폴로지 (설계 §2)."""

    def __init__(self, v_aisle_rank, main_aisle, loop_fwd, junction, station):
        self.v_aisle_rank = v_aisle_rank   # (H,W) int16, -1=통로 아님
        self.main_aisle = main_aisle       # (H,W) bool
        self.loop_fwd = loop_fwd           # (H,W) int8, 시계방향 접선, -1=아님
        self.junction = junction           # (H,W) bool
        self.station = station             # (H,W) bool — 흐름용 도킹 칸


def extract_topology(free, st_cell):
    """wallA 규칙 기반 추출. free가 통로차단 ON이면 랙 내부 통로 칸이
    free=False라 자동으로 비활성 (비용은 free 칸에만 의미)."""
    H, W = free.shape
    rank = np.full((H, W), -1, dtype=np.int16)
    for k, x in enumerate(VA_XS_M):
        c = int((x + OFFSET_M) / CELL_M)
        rank[VA_ROWS[0]:VA_ROWS[1], c - 1:c + 2] = k

    main = np.zeros((H, W), dtype=bool)
    main[BAND_S_ROWS[0]:BAND_S_ROWS[1], :] = True
    main[BAND_N_ROWS[0]:BAND_N_ROWS[1], :] = True

    loop = np.full((H, W), -1, dtype=np.int8)
    r_lo, r_hi = BAND_S_ROWS[0], BAND_N_ROWS[1]
    loop[r_lo:r_hi, BAND_W_COLS[0]:BAND_W_COLS[1]] = 0   # 서 밴드 → 북행
    loop[r_lo:r_hi, BAND_E_COLS[0]:BAND_E_COLS[1]] = 2   # 동 밴드 → 남행
    loop[BAND_S_ROWS[0]:BAND_S_ROWS[1], :] = 3           # 남 밴드 → 서행 (코너 우선)
    loop[BAND_N_ROWS[0]:BAND_N_ROWS[1], :] = 1           # 북 밴드 → 동행

    junc = np.zeros((H, W), dtype=bool)
    for k, x in enumerate(VA_XS_M):
        c = int((x + OFFSET_M) / CELL_M)
        for r in JUNCTION_ROWS:
            junc[r, c - 1:c + 2] = True

    station = np.zeros((H, W), dtype=bool)
    for name, rc in st_cell.items():
        if not name.startswith(("charger", "charge_q")):
            station[rc] = True

    # free 밖은 전부 비활성 (칸 자체를 못 가는 것은 격자가 담당 — 명세 §12)
    rank[~free] = -1
    main &= free
    loop[~free] = -1
    junc &= free
    station &= free
    return Topology(rank, main, loop, junc, station)


def _edges_into(mask):
    """mask 칸으로 '들어가는' 엣지 선택자: sel[r,c,d] = 이웃(r,c,d)이 mask."""
    H, W = mask.shape
    sel = np.zeros((H, W, 4), dtype=bool)
    sel[:-1, :, 0] = mask[1:, :]     # 북(r+1)으로 들어감
    sel[:, :-1, 1] = mask[:, 1:]     # 동(c+1)
    sel[1:, :, 2] = mask[:-1, :]     # 남(r-1)
    sel[:, 1:, 3] = mask[:, :-1]     # 서(c-1)
    return sel


def from_theta(free, topo, theta):
    """GuidanceTheta → Guidance. 전부 곱셈, 시작 1.0, 최종 clip [0.5, 5.0]."""
    H, W = free.shape
    ec = np.ones((H, W, 4), dtype=np.float32)

    # 1) 세로 통로 교대 순환 (명세 §12 그룹 공식. 그룹0=북 선호, 그룹1=남 선호)
    #    통로 칸에서 나가는 N/S 엣지 + 통로 칸으로 들어가는 N/S 엣지 모두 적용.
    #    진입 엣지가 중립이면 PIBT의 국소 score는 통로 안에 들어간 뒤에야
    #    방향 비용을 보게 되어 진입 시점의 통로 선택 유도가 안 된다 (설계 §4).
    on = topo.v_aisle_rank >= 0
    group = (topo.v_aisle_rank // theta.aisle_period + theta.aisle_phase) % 2
    for g, pref in ((0, 0), (1, 2)):                     # (그룹, 선호 방향)
        cells = on & (group == g)
        into = _edges_into(cells)
        anti = (pref + 2) % 4
        ec[..., pref][cells | into[..., pref]] *= theta.aisle_alt_boost
        ec[..., anti][cells | into[..., anti]] *= theta.aisle_alt_gain

    # 2) 외곽 순환 — 순방향의 역방향 엣지에 벌금 (수직 진출입은 불변)
    fwd = topo.loop_fwd if theta.loop_dir == 0 else \
        np.where(topo.loop_fwd >= 0, (topo.loop_fwd + 2) % 4, -1)
    for d in range(4):
        ec[..., (d + 2) % 4][fwd == d] *= theta.loop_gain

    # 3) 큰 통로 할인 / 교차로 진입 벌금 / 작업자리 접근·퇴장 — 진입 엣지 기준
    ec[_edges_into(topo.main_aisle)] *= theta.main_aisle_gain
    ec[_edges_into(topo.junction)] *= theta.junction_penalty
    ec[_edges_into(topo.station)] *= theta.station_in
    ec[topo.station] *= theta.station_out                # 도킹 칸에서 나가는 4방향

    wc = np.full((H, W), theta.wait_cost, dtype=np.float32)
    return Guidance(edge_cost=np.clip(ec, CLIP_LO, CLIP_HI),
                    wait_cost=np.clip(wc, CLIP_LO, CLIP_HI))


def load_theta(path):
    """json(GuidanceTheta 필드 11개) → GuidanceTheta. 범위는 명세 §11 참고용
    경고만 — 극단값 실험(더미 θ 검증)을 막지 않는다."""
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    theta = GuidanceTheta(**d)
    assert theta.aisle_period in (1, 2, 3), "aisle_period는 1|2|3"
    assert theta.aisle_phase in (0, 1) and theta.loop_dir in (0, 1)
    return theta
