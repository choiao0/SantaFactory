# sim_engine/ — B안 (알고리즘/엔지니어링팀)

PIBT 이동계층 + θ → 통행 비용 변환(`from_theta`) + Fleet 벤치마크.

입출력 계약: [`../contracts/guidance_types.py`](../contracts/guidance_types.py) (`GuidanceTheta` → `Guidance`) ·
실행 계약: [`../contracts/SIM_RUN_CONTRACT.md`](../contracts/SIM_RUN_CONTRACT.md) (sim_v2 CLI·SUMMARY·종료 코드 — 외부 호출자는 이것만 의존)

## 진행 상태

1. **B-0** 기준선 재확정 — 완료 (SPEED 1.0 m/s, 단일 맵 wallA)
2. **B-1** 시공간 A* → PIBT 교체 — 완료 (벤치마크: PIBT ≥ A* 전 구간)
3. **B-2** `from_theta()` 배관 — 완료 (스키마 v2 배타 규칙, 더미 θ 방향 분극 검증 통과, 거리항 가중 다익스트라)
3b. **PIBT 헤딩 모델** (2026-09-02 결정 ②③④⑤) — 완료, `--heading` opt-in. B0′ 기준선 측정 완료(무릎 8→10대, `TURN_TICKS=2` 기준). Isaac 실측 반영(`TURN_TICKS=1`, 2026-09-03) → 맵 동기화 후 재실측 → 기본값 전환 예정
3c. **충전 존** (2026-09-03 결정) — 완료, **main 흐름 기본값** (`--fixed-homes`로 기존 고정 홈 12칸). 존 내 최근접 빈 칸 복귀·초기 배치, 지표(복귀 대기·재선택·예약 무시·체류 평균/p90·비임무 밀림), 스모크 [D]. B-1e CSV 원칙 종료 → 기준선 B0″(`fleet_sweep_b0z.py`, 동기화 맵)
3d. **고부하 스윕** (2026-09-04) — `fleet_sweep_load.py` (`--order-gap`). 헤딩이 칸을 28대 +38%, STALL → 라이브니스 장치 ⑤(도킹 칸 이탈 최우선 sticky, sim_v2 헤딩 기본). 다음: 성능 최적화 → 헤딩 기본값 전환 → 2번째 존
4. **B-5** θ 적용 Fleet Sweep 재실측 — A트랙 산출물 대기

설계·결정 문서 인덱스: [`../docs/README.md`](../docs/README.md)

검증 커맨드 (코어·배관·로더 수정 후, 이 폴더에서, `PYTHONIOENCODING=utf-8`):
```
python pibt_mvp_demo.py            # 코어 4종
python pibt_heading_demo.py        # 헤딩 6종
python pibt_smoke_real_map.py      # 실맵: 칸 60대 + 헤딩 30대×3시드 + 충전 존 20대×2시드
python from_theta_demo.py          # θ v2 검산 + 더미 θ 분극 (~1분)
SIM_CHECK=1 SIM_NO_PLOT=1 python sim_v2_tasks.py base 6 40 42 1 --flow=v1compat        # 패리티: 2317틱, 186.4 tasks/h (맵 동기화 전 2311/186.9)
SIM_CHECK=1 SIM_NO_PLOT=1 python sim_v2_tasks.py base 12 40 42 1 --heading             # 존(기본) 엔드투엔드 완주·겹침 0
SIM_NO_PLOT=1 python sim_v2_tasks.py base 6 40 42 1 --fixed-homes                       # 고정 홈: 2970틱, 127.3 tasks/h (동기화 전 2797/135.1 = B-1e)
SIM_NO_PLOT=1 python sim_v1_tasks.py base 6 40 42 1                                     # A* 기준선: 2384틱, 181.2 tasks/h (동기화 전 2378/181.7)
python -m pytest ../ai_theta/tests -q                                                   # A트랙 (map_loader·from_theta 를 import)
```

| 파일 | 내용 |
|---|---|
| `pibt_core.py` | PIBT 코어 — 칸 모델(`dist_map/step/run`, 가중 다익스트라) + 헤딩 모델(`*_h`: (칸,방향) 상태, 2칸 점유, 회전·후진, 스윙 예약, 대기 상승·재계획) |
| `map_loader.py` | 맵 로드(**`3_FMS/map` 공식 맵**, 2026-09-03 동기화)/1.0m 다운샘플/스테이션 (v1과 규칙 동기 유지: `OBSTACLE_VALUES`, `AISLE_ROWS`) + 충전 존 `load_charge_zone`·`make_homes_zone` (A트랙 `build_input.py`도 import — 단일 소스) |
| `sim_v1_tasks.py` | A* 기준선 — **이동계층 수정 금지** |
| `sim_v2_tasks.py` | PIBT 틱 시뮬 본체 (`--flow=main\|v1compat`, `--theta=<json>`, `--heading`, `--fixed-homes`, `--order-gap=<틱>`; 헤딩 장치 ⑤ 끄기 `SIM_NO_DOCK_PRIO=1`) |
| `fleet_sweep_b0z.py`, `fleet_sweep_load.py` | **B0″ 기준선**(40주문) / **고부하**(80·120주문, 8~28대) — 칸 vs 헤딩, 존 지표. `SWEEP_PLOT_ONLY=1`로 그래프만 |
| `from_theta.py` | B-2: wallA 토폴로지 추출 + θ→비용 변환, 스키마 v2 배타 조립 ([설계](../docs/2026-09-01_B2_from_theta_설계.md)) |
| `pibt_mvp_demo.py`, `pibt_heading_demo.py`, `pibt_smoke_real_map.py`, `from_theta_demo.py` | 회귀 테스트 — 코어/배관 수정 시 재실행 |
| `fleet_sweep.py`, `fleet_sweep_b1e.py`, `fleet_sweep_b0h.py` | v1 스윕 / A* vs PIBT 벤치마크(회전 0초, 이력) / **B0′ 기준선**(칸 vs 헤딩) |
| [`results/`](results/) | 벤치마크·검증 산출물 (csv/png/npz) — 기존 결과 덮어쓰기 금지 |
