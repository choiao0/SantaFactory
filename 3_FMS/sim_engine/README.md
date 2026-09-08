# sim_engine/ — B안 (알고리즘/엔지니어링팀)

PIBT 이동계층 + θ → 통행 비용 변환(`from_theta`) + Fleet 벤치마크.

입출력 계약: [`../contracts/guidance_types.py`](../contracts/guidance_types.py) (`GuidanceTheta` → `Guidance`) ·
실행 계약: [`../contracts/SIM_RUN_CONTRACT.md`](../contracts/SIM_RUN_CONTRACT.md) (sim_v2 CLI·SUMMARY·종료 코드 — 외부 호출자는 이것만 의존)

## 진행 상태

1. **B-0/B-1** — SPEED 1.0 m/s 기준선과 A*→PIBT 교체를 완료했다. PIBT가 A*보다 전 구간 낮지 않았으며 옛 스크립트와 산출물은 git 이력과 `results/archive/`에 보존한다.
2. **B-2** — θ v2 배타 조립, 가중 다익스트라 거리항과 `from_theta()` 연결을 완료했다.
3. **3a~3h 완료 요약** — `(칸,방향)` 헤딩 PIBT와 2칸 차체·회전 스윙·후진, 동기화 맵과 충전 존, 고부하·라이브니스 장치 5종, HGraph 성능 최적화, 헤딩 기본값과 Isaac 내보내기, 순수 `FmsKernel`·`OrderStream` 분리, SimPy 고정 시간·교대·배터리 사건층까지 구현했다. 칸 모델은 `--cell`, 고정 홈은 `--fixed-homes` 비교축이고, 28대는 현재 존 용량의 견적 제약이다. 상세는 [이동계층](../docs/이동계층_PIBT.md#현재-결론), [커널·시뮬](../docs/커널_시뮬_구조.md#현재-구조), [맵·충전 존](../docs/맵_충전존.md#충전-존-결정)에 있다.
4. **B-5** — 평가 시드 {101,103,104}에서 θ 20~21대가 중립 24대와 같은 처리량을 냈다(3~4대 절감, 동일 대수 +10~15%). wallA의 대수 축에서는 [θ 한 벌이면 충분](../docs/θ_경로_기준선.md#θ-한-벌-판정)했고, 중립 STALL 3건·θ 0건을 기록했다.

설계·결정 문서 인덱스: [`../docs/README.md`](../docs/README.md)

검증 커맨드 (코어·배관·로더 수정 후, 이 폴더에서, `PYTHONIOENCODING=utf-8`):
```
python checks/pibt_mvp_demo.py            # 코어 4종
python checks/pibt_heading_demo.py        # 헤딩 6종
python checks/pibt_smoke_real_map.py      # 실맵: 칸 60대 + 헤딩 30대×3시드 + 충전 존 20대×2시드
python checks/from_theta_demo.py          # θ v2 검산 + 더미 θ 분극 (~1분)
SIM_CHECK=1 SIM_NO_PLOT=1 python sim_v2_tasks.py base 6 40 42 1 --flow=v1compat        # 패리티: 2317틱, 186.4 tasks/h (맵 동기화 전 2311/186.9)
SIM_CHECK=1 SIM_NO_PLOT=1 python sim_v2_tasks.py base 6 40 42 1                        # 헤딩(기본)+존(기본): 계약 v2 §5 기준값
SIM_CHECK=1 SIM_NO_PLOT=1 python sim_v2_tasks.py base 12 40 42 1                       # 존(기본) 엔드투엔드 완주·겹침 0
SIM_NO_PLOT=1 python sim_v2_tasks.py base 6 40 42 1 --cell --fixed-homes                # 칸 모델·고정 홈: 2970틱, 127.3 tasks/h (동기화 전 2797/135.1 = B-1e)
SIM_EXPORT_ISAAC=1 SIM_NO_PLOT=1 python sim_v2_tasks.py base 12 40 42 1                # Isaac 리플레이용 isaac_export_base/ 생성
SIM_NO_PLOT=1 python simpy_harness.py base 6 40 42 1                                    # (simpy 설치 시) SUMMARY 가 위 CLI 와 비트 동일해야 함
SIM_CHECK=1 SIM_NO_PLOT=1 python sim_v2_tasks.py hz 24 0 42 1 --horizon=21600 --order-gap=15 --battery   # 고정 시간 6h·교대·배터리 (-145) — [5] 배터리 줄
python checks/check_lifelong_battery.py                                                 # 고정 시간·교대·배터리 불변 검사 7항목 (~20초)
python -m pytest ../ai_theta/tests -q                                                   # A트랙 (map_loader·from_theta 를 import)
python checks/pibt_dist_identity_check.py                                               # 거리장 vs 참조 구현 비트 동일 (~1분)
python checks/check_results_identity.py --quick                                         # 기준선 CSV 대표 12행 재실행 동일 (~2분; 전수는 옵션 없이)
```

| 파일 | 내용 |
|---|---|
| `pibt_core.py`, `pibt/` | 기존 import를 보존하는 파사드 + PIBT 구현. `cell`·`liveness`·`geometry`·`hgraph`·`heading`으로 분리하며 `_dist_map_h_ref`도 재수출 |
| `checks/pibt_dist_identity_check.py`, `checks/check_results_identity.py` | **결과 동일성 검사** — 거리장 vs 참조 구현(비트 동일) / 기준선 CSV(b0z·load) 재실행 비교. 코어·거리장 수정 시 필수 |
| `checks/check_lifelong_battery.py` | **고정 시간·교대·배터리 불변 검사** (-145) — 유한 모드 시각표 불변, 교대 창 밖 도착 0, 배터리 매 틱 불변(SoC 범위·도크 소유·배차 제외), CLI vs 하네스 패리티, 0 간격 거부·고정 시간 워치독 계속 실행 |
| `map_loader.py` | 맵 로드(**`3_FMS/map` 공식 맵**, 2026-09-03 동기화)/1.0m 다운샘플/스테이션 (**로드 규칙 단일 소스**: `OBSTACLE_VALUES`, `AISLE_ROWS`) + 충전 존 `load_charge_zone`·`make_homes_zone` (A트랙 `build_input.py`도 import — 단일 소스) |
| **`fms_kernel.py`, `kernel/`** | 기존 import를 보존하는 파사드 + **FMS 결정 커널**. `core` 상태머신·배차·이동·워치독, `battery.BatteryMixin`, `metrics.MetricsMixin`, `states`(로봇 상태·계급 상수)로 분리 |
| **`order_stream.py`** | 주문·입고 스트림 `OrderStream` (02 시뮬 WMS 역할, 커널 밖) — 도착 시각표, 주문→태스크 분해(라인 1~3, 통로별 토트), v1compat 체인, 주문 완료 카운터. rng 는 여기만. **고정 시간 모드**(`horizon`, `shifts`): 교대 창 안에서만 그 종류의 도착, `shift_windows()`·`arrival_ticks()` |
| `sim_v2_tasks.py`, `cli/` | 계약 진입점(`parse_args`/`build`/`run_ticks`/`main`) + `cli/common`(OUT·SPEED·DT)·`report`·`export_isaac`·`plot` 구현. `report`·`export_isaac`·`plot_heat`·`DT`는 진입점에서 재수출 |
| `simpy_harness.py` | **SimPy 셸**(선택) — 같은 커널·스트림을 SimPy 시계로: 도착 프로세스(URGENT, 같은 시각 틱보다 먼저) + 틱 프로세스, 고정 시간 실행은 `env.run(until=T)`. `import simpy` 지연, 없으면 종료 코드 2. SUMMARY 가 CLI 와 동일해야 함 |
| `sweeps/_common.py` | **스윕 공통 골격** (-149) — `run_sim`(서브프로세스 + SUMMARY 파싱 + STALL 행·덤프), CSV·시드 집계·plot 공통 함수. 계약 v2.3 호출만 의존 |
| `sweeps/fleet_sweep_theta.py` | **B-5 θ 적용 스윕** (-149) — 중립 vs 대수별 θ(최근접, 동률은 큰 쪽) vs 24대 θ 고정. `SWEEP_PLOT_ONLY` 등 지원 |
| `sweeps/fleet_sweep_b0z.py`, `sweeps/fleet_sweep_load.py` | **B0″ 기준선** / **고부하** 스윕. 이번 이동에서는 두 스크립트 구현을 `_common`으로 합치지 않음 |
| `from_theta.py` | B-2: wallA 토폴로지 추출 + θ→비용 변환, 스키마 v2 배타 조립 ([설계](../docs/θ_경로_기준선.md#from_theta-조립-규칙)) |
| `checks/` | PIBT 데모 3종·`from_theta` 데모·거리/결과 동일성·고정 시간/배터리 불변 검사 |
| [`results/`](results/) | 벤치마크·검증 산출물 (csv/png/npz) — 기존 결과 덮어쓰기 금지. 대체된 기준선·초기 산출물은 `results/archive/` |
