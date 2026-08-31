# -*- coding: utf-8 -*-
# ============================================================
# PIBT 실제 창고 맵 스모크 테스트 (S15P21A106-107)
#
# pibt_core.py를 확정 창고 맵(occupancy_grid.npy, 1.0m 격자로 다운샘플)에서
# 실제 규모로 검증한다. 이벤트 루프 통합 전에 확인할 것 세 가지:
#   1) 실제 지형(통로차단 ON 포함)에서 교착 없이 전원 목표 도달 (B-1d)
#   2) 매 틱 vertex/edge 충돌 없음 (pibt_mvp_demo와 동일한 전수 검사)
#   3) 틱당 계산 시간 — 시뮬 1회(수천 틱)에 감당 가능한 수준인지
#
# 시나리오:
#   A) 충전존 홈 10대 -> 스테이션 도킹 칸 (실전과 같은 OD 패턴)
#   B) 랜덤 OD 30대 스트레스 (시드 고정) — 통로 곳곳에서 교차/정면충돌 유발
#
# 맵 로드 규칙은 sim_v1_tasks.py L51-58과 동일 (그쪽은 import 시 실행되는
# 스크립트라 재사용 불가 — 규칙 변경 시 양쪽 함께 수정할 것).
#
# 사용: python pibt_smoke_real_map.py
# ============================================================
import json
import os
import time

import numpy as np

from pibt_core import dist_map, run
from pibt_mvp_demo import check_collisions

OUT = os.path.dirname(os.path.abspath(__file__))
CELL_M, OFFSET_M = 1.0, 0.4
K, OX = round(CELL_M / 0.1), round(OFFSET_M / 0.1)

# ---- 맵 로드 + 다운샘플 (sim_v1_tasks.py와 동일 규칙) ----
grid01 = np.load(os.path.join(OUT, "occupancy_grid.npy"))
stations = json.load(open(os.path.join(OUT, "stations.json")))
raw = np.isin(grid01, (1, 2, 5)).astype(np.uint8)
m2 = np.pad(raw, ((0, 0), (OX, 0)), constant_values=1)
h, w = m2.shape
m2 = np.pad(m2, ((0, (-h) % K), (0, (-w) % K)), constant_values=1)
coarse = m2.reshape(m2.shape[0] // K, K, m2.shape[1] // K, K).max(axis=(1, 3))
FREE = coarse == 0
H, W = coarse.shape

# 통로차단 ON (fleet_sweep과 같은 보수적 초기실험 방침)
for k in range(11):
    c = int((35.1 + 6 * k + OFFSET_M) / CELL_M)
    FREE[48:68, c - 1:c + 2] = False

st_cell = {}
for kind, pts in stations.items():
    for i, (x, y) in enumerate(pts):
        r, c = int(y / CELL_M), int((x + OFFSET_M) / CELL_M)
        for rr, cc in [(r, c), (r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)]:
            if 0 <= rr < H and 0 <= cc < W and FREE[rr, cc]:
                st_cell[f"{kind}[{i}]"] = (rr, cc)
                break
print(f"[0] 맵 coarse {H}x{W}, free 칸 {int(FREE.sum())}개, 통로차단 ON")


def report(name, history, n_agents, elapsed):
    steps = len(history) - 1
    print(f"{name}: {n_agents}대 전원 도달, {steps}스텝, "
          f"총 {elapsed*1000:.0f}ms = 틱당 {elapsed/steps*1000:.2f}ms")


def scenario_stations():
    """충전존 홈 10대 -> 스테이션 도킹 칸 (B-0 최적 대수 기준)."""
    starts = {i: st_cell[f"charger[{i}]"] for i in range(6)}
    starts.update({6 + i: st_cell[f"charge_q[{i}]"] for i in range(4)})
    goal_names = ["induction[0]", "induction[1]", "aisle_buf[0]", "aisle_buf[5]",
                  "aisle_buf[10]", "consol[0]", "consol[1]", "packing[0]",
                  "packing[2]", "packing[4]"]
    goals = {i: st_cell[nm] for i, nm in enumerate(goal_names)}
    assert len(set(goals.values())) == len(goals), "목표 칸 중복"
    t0 = time.perf_counter()
    history = run(FREE, starts, goals, max_steps=600)
    elapsed = time.perf_counter() - t0
    check_collisions(history, FREE)
    for a, g in goals.items():
        assert history[-1][a] == g, f"agent{a} 미도달: {history[-1][a]} != {g}"
    report("[A] 충전존->스테이션", history, len(starts), elapsed)


def scenario_random_stress(n_agents=30, seed=42):
    """랜덤 OD 스트레스 — 통로 전역에서 교차/정면충돌 유발."""
    rng = np.random.default_rng(seed)
    free_cells = list(zip(*np.nonzero(FREE)))
    # 도달 가능성 보장: 가장 큰 연결 성분 기준점에서 dist >= 0 인 칸만 사용
    ref = dist_map(FREE, st_cell["induction[0]"])
    cells = [rc for rc in free_cells if ref[rc] >= 0]
    picks = rng.choice(len(cells), size=n_agents * 2, replace=False)
    starts = {i: cells[picks[i]] for i in range(n_agents)}
    goals = {i: cells[picks[n_agents + i]] for i in range(n_agents)}
    t0 = time.perf_counter()
    history = run(FREE, starts, goals, max_steps=800)
    elapsed = time.perf_counter() - t0
    check_collisions(history, FREE)
    for a, g in goals.items():
        assert history[-1][a] == g, f"agent{a} 미도달: {history[-1][a]} != {g}"
    report(f"[B] 랜덤 OD 스트레스(seed={seed})", history, n_agents, elapsed)


if __name__ == "__main__":
    scenario_stations()
    for seed in [42, 7, 11, 123, 999, 2026]:
        scenario_random_stress(n_agents=30, seed=seed)
    for seed in [42, 7]:                      # B-0 최적점(10대)의 6배 과밀
        scenario_random_stress(n_agents=60, seed=seed)
    print("[DONE] 실제 창고 맵 PIBT 스모크 테스트 통과")
