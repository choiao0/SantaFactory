# sim_engine/ — B안 (알고리즘/엔지니어링팀)

PIBT 이동계층 + θ → 통행 비용 변환(`from_theta`) + Fleet 벤치마크.

입출력 계약: [`../contracts/guidance_types.py`](../contracts/guidance_types.py) (`GuidanceTheta` → `Guidance`)

## 진행 상태

1. **B-0** 기준선 재확정 — 완료 (SPEED 1.0 m/s, 단일 맵 wallA)
2. **B-1** 시공간 A* → PIBT 교체 — 완료 (벤치마크: PIBT ≥ A* 전 구간)
3. **B-2** `from_theta()` 배관 — 완료 (더미 θ 방향 분극 검증 통과)
4. **B-5** θ 적용 Fleet Sweep 재실측 — A트랙 산출물 대기

상세 코드 지도·검증 커맨드·함정 목록: [`../docs/B트랙_실행_핸드오프_v2.md`](../docs/B트랙_실행_핸드오프_v2.md)

| 파일 | 내용 |
|---|---|
| `pibt_core.py` | PIBT 코어 (순수 모듈, 방향 0=북 1=동 2=남 3=서) |
| `map_loader.py` | 맵 로드/1.0m 다운샘플/스테이션 (v1과 규칙 동기 유지) |
| `sim_v1_tasks.py` | A* 기준선 — **이동계층 수정 금지** |
| `sim_v2_tasks.py` | PIBT 틱 시뮬 본체 (`--flow=main\|v1compat`, `--theta=<json>`) |
| `from_theta.py` | B-2: wallA 토폴로지 추출 + θ→비용 변환 ([설계](../docs/2026-09-01_B2_from_theta_설계.md)) |
| `pibt_mvp_demo.py`, `pibt_smoke_real_map.py`, `from_theta_demo.py` | 회귀 테스트 — 코어/배관 수정 시 재실행 |
| `fleet_sweep.py`, `fleet_sweep_b1e.py` | v1 스윕 / A* vs PIBT 벤치마크 |
| [`results/`](results/) | 벤치마크·검증 산출물 (csv/png/npz) — 기존 결과 덮어쓰기 금지 |
