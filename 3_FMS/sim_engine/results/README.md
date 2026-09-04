# results/

Fleet sweep 벤치마크·검증 산출물 (csv/png/npz). **기존 파일은 덮어쓰지 말고 새 이름으로** (이력 보존).

| 파일 | 내용 | 지위 |
|---|---|---|
| `b0z_sweep.csv`, `b0z_cell_vs_heading.png`, `b0z_zone_metrics.png` | **B0″ 현재 기준선** — 동기화 맵(벽있음 ∪ v5.8) + 충전 존 기본 + TURN_TICKS=1, 칸 vs 헤딩 (`fleet_sweep_b0z.py`) | 현재. [문서](../../docs/2026-09-03_B0z_충전존_기준선.md) |
| `load_sweep.csv`, `load_throughput.png`, `load_zone.png` | **고부하 스윕** — L1(80주문/25틱)·L2(120주문/15틱) × 8~28대, 칸 vs 헤딩 (`fleet_sweep_load.py`) | 현재. [문서](../../docs/2026-09-04_고부하_무릎_판정.md) |
| `b0z_sweep_map0831.csv`, `*_map0831.png` | 같은 구성을 8/31 맵 복사본 위에서 돈 중간 결과 (맵 동기화 효과 비교용) | 이력 |
| `b0h_sweep.csv`, `b0h_cell_vs_heading.png`, `b0h_heading_cost.png` | B0′ — 8/31 맵, 고정 홈 12칸, 회전 2틱 (`fleet_sweep_b0h.py`) | 이력 (B0″로 대체) |
| `b1e_sweep.csv`, `b1e_astar_vs_pibt.png`, `fleet_sweep_v2_main.png` | B-1e — A*(sim_v1) vs PIBT(v1compat) + main 흐름, 8/31 맵 (`fleet_sweep_b1e.py`, pibt_main은 `--fixed-homes`) | 이력 (A* 비교) |
| `fleet_sweep_results.csv`, `fleet_sweep.png` | B-0 — sim_v1 단독 fleet 곡선 (`fleet_sweep.py`) | 이력 |
| `b2_from_theta_dirflow.png`, `sim_v2_b2demo_*` , `theta_b2_dummy.json` | B-2 from_theta 검증 산출물 (`from_theta_demo.py`가 매번 재생성) | 검증 |
| `sim_v2_*_heat.png`, `map_overview.png`, `pibt_viewer.html` | 개별 실행 히트맵·맵 그림·뷰어 | 보조 |
