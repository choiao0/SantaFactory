# sim_engine/ — B안 (알고리즘/엔지니어링팀)

PIBT 이동계층 + θ → 통행 비용 변환(`from_theta`) + Fleet 벤치마크.

입출력 계약: [`../contracts/guidance_types.py`](../contracts/guidance_types.py) (`GuidanceTheta` → `Guidance`) ·
실행 계약: [`../contracts/SIM_RUN_CONTRACT.md`](../contracts/SIM_RUN_CONTRACT.md) (sim_v2 CLI·SUMMARY·종료 코드 — 외부 호출자는 이것만 의존)

## 진행 상태

1. **B-0** 기준선 재확정 — 완료 (SPEED 1.0 m/s, 단일 맵 wallA)
2. **B-1** 시공간 A* → PIBT 교체 — 완료 (벤치마크: PIBT ≥ A* 전 구간)
3. **B-2** `from_theta()` 배관 — 완료 (스키마 v2 배타 규칙, 더미 θ 방향 분극 검증 통과, 거리항 가중 다익스트라)
3b. **PIBT 헤딩 모델** (2026-09-02 결정 ②③④⑤) — 완료. B0′ 기준선(무릎 8→10대, `TURN_TICKS=2`) → Isaac 실측 반영(`TURN_TICKS=1`, 2026-09-03) → B0″ 재실측 → **2026-09-04 기본값 전환(-143, 계약 v2)**: 칸 모델은 `--cell` opt-in, `--heading` 은 호환용 무시
3c. **충전 존** (2026-09-03 결정) — 완료, **main 흐름 기본값** (`--fixed-homes`로 기존 고정 홈 12칸). 존 내 최근접 빈 칸 복귀·초기 배치, 지표(복귀 대기·재선택·예약 무시·체류 평균/p90·비임무 밀림), 스모크 [D]. B-1e CSV 원칙 종료 → 기준선 B0″(`fleet_sweep_b0z.py`, 동기화 맵)
3d. **고부하 스윕** (2026-09-04) — `fleet_sweep_load.py` (`--order-gap`). 헤딩이 칸을 28대 +38%, STALL → 라이브니스 장치 ⑤(도킹 칸 이탈 최우선 sticky, sim_v2 헤딩 기본)
3e. **성능 최적화** (2026-09-04, -136) — `pibt_core.HGraph`(정적 테이블) + 재계획 증분 복구. 헤딩 28대 57~86 s → 7~11 s, 결과 비트 동일
3f. **헤딩 기본값 + Isaac 내보내기** (2026-09-04, -143, [설계](../docs/2026-09-04_헤딩기본값_Isaac내보내기_설계.md)) — 기본 모델 = 헤딩, `SIM_EXPORT_ISAAC=1` 로 sim_v2 궤적·yaw·액션을 `isaac_replay.py` 포맷으로. 2번째 존은 폐기(28대 = 존 용량 = 견적 제약), 배터리·충전 도크는 SimPy 단계로
3g. **커널 라이브러리화 + SimPy 하네스** (2026-09-04, -144, [설계](../docs/2026-09-04_커널_라이브러리화_SimPy하네스_설계.md)) — 틱 루프를 `fms_kernel.FmsKernel`(시계·난수·I/O 없음, `submit_task`/`dispatch`/`move`)로, 주문 생성은 `order_stream.OrderStream`(커널 밖). `sim_v2_tasks.py`는 얇은 CLI 셸, `simpy_harness.py`는 같은 커널을 SimPy 시계로. **동작 불변** — 기준값 3개·CSV 80행·내보내기·STALL 덤프 비트 동일, 실행 시간 동일. 다음: 배터리·충전 도크·지평 실행(이 커널 위에)
4. **B-5** θ 적용 Fleet Sweep 재실측 — A트랙 산출물 대기

설계·결정 문서 인덱스: [`../docs/README.md`](../docs/README.md)

검증 커맨드 (코어·배관·로더 수정 후, 이 폴더에서, `PYTHONIOENCODING=utf-8`):
```
python pibt_mvp_demo.py            # 코어 4종
python pibt_heading_demo.py        # 헤딩 6종
python pibt_smoke_real_map.py      # 실맵: 칸 60대 + 헤딩 30대×3시드 + 충전 존 20대×2시드
python from_theta_demo.py          # θ v2 검산 + 더미 θ 분극 (~1분)
SIM_CHECK=1 SIM_NO_PLOT=1 python sim_v2_tasks.py base 6 40 42 1 --flow=v1compat        # 패리티: 2317틱, 186.4 tasks/h (맵 동기화 전 2311/186.9)
SIM_CHECK=1 SIM_NO_PLOT=1 python sim_v2_tasks.py base 6 40 42 1                        # 헤딩(기본)+존(기본): 계약 v2 §5 기준값
SIM_CHECK=1 SIM_NO_PLOT=1 python sim_v2_tasks.py base 12 40 42 1                       # 존(기본) 엔드투엔드 완주·겹침 0
SIM_NO_PLOT=1 python sim_v2_tasks.py base 6 40 42 1 --cell --fixed-homes                # 칸 모델·고정 홈: 2970틱, 127.3 tasks/h (동기화 전 2797/135.1 = B-1e)
SIM_EXPORT_ISAAC=1 SIM_NO_PLOT=1 python sim_v2_tasks.py base 12 40 42 1                # Isaac 리플레이용 isaac_export_base/ 생성
SIM_NO_PLOT=1 python simpy_harness.py base 6 40 42 1                                    # (simpy 설치 시) SUMMARY 가 위 CLI 와 비트 동일해야 함
SIM_NO_PLOT=1 python sim_v1_tasks.py base 6 40 42 1                                     # A* 기준선: 2384틱, 181.2 tasks/h (동기화 전 2378/181.7)
python -m pytest ../ai_theta/tests -q                                                   # A트랙 (map_loader·from_theta 를 import)
python pibt_dist_identity_check.py                                                      # 거리장 vs 참조 구현 비트 동일 (~1분)
python check_results_identity.py --quick                                                # 기준선 CSV 대표 12행 재실행 동일 (~2분; 전수는 옵션 없이)
```

| 파일 | 내용 |
|---|---|
| `pibt_core.py` | PIBT 코어 — 칸 모델(`dist_map/step/run`, 가중 다익스트라) + 헤딩 모델(`*_h`: (칸,방향) 상태, 2칸 점유, 회전·후진, 스윙 예약, 대기 상승·재계획). 거리장은 `HGraph`(정적 테이블·목표별 캐시·재계획 증분 복구), 참조 구현 `_dist_map_h_ref` 보존 |
| `pibt_dist_identity_check.py`, `check_results_identity.py` | **결과 동일성 검사** — 거리장 vs 참조 구현(비트 동일) / 기준선 CSV(b0z·load) 재실행 비교. 코어·거리장 수정 시 필수 |
| `map_loader.py` | 맵 로드(**`3_FMS/map` 공식 맵**, 2026-09-03 동기화)/1.0m 다운샘플/스테이션 (v1과 규칙 동기 유지: `OBSTACLE_VALUES`, `AISLE_ROWS`) + 충전 존 `load_charge_zone`·`make_homes_zone` (A트랙 `build_input.py`도 import — 단일 소스) |
| `sim_v1_tasks.py` | A* 기준선 — **이동계층 수정 금지** |
| **`fms_kernel.py`** | **FMS 결정 커널** `FmsKernel` — 로봇 상태머신·배차(FIFO×최근접)·PIBT 이동(헤딩/칸)·충전 존 복귀·서비스·지표 카운터·워치독(`StallError`). 시계·난수·I/O 없음. 셸이 `submit_task` → `dispatch(t)` → [종료 판단] → `move(t)` 순으로 부른다. `KernelConfig`로 헤딩/존/θ/검사/내보내기 선택 |
| **`order_stream.py`** | 주문·입고 스트림 `OrderStream` (02 시뮬 WMS 역할, 커널 밖) — 도착 시각표, 주문→태스크 분해(라인 1~3, 통로별 토트), v1compat 체인, 주문 완료 카운터. rng 는 여기만 |
| `sim_v2_tasks.py` | **CLI 셸** (`parse_args`/`build`/`run_ticks`/`report`/`export_isaac`/`plot_heat`) — 인자·맵·비용·홈 준비, 틱 루프, [SUMMARY]·히트맵·DIRFLOW·Isaac 내보내기. 기본 헤딩 모델 (`--flow=main\|v1compat`, `--theta=<json>`, `--cell`, `--fixed-homes`, `--order-gap=<틱>`; `SIM_NO_DOCK_PRIO=1`, `SIM_EXPORT_ISAAC=1`) |
| `simpy_harness.py` | **SimPy 셸**(선택) — 같은 커널·스트림을 SimPy 시계로. `import simpy` 지연, 없으면 종료 코드 2. 배터리·지평 실행이 붙을 자리 |
| `fleet_sweep_b0z.py`, `fleet_sweep_load.py` | **B0″ 기준선**(40주문) / **고부하**(80·120주문, 8~28대) — 칸 vs 헤딩, 존 지표. `SWEEP_PLOT_ONLY=1`로 그래프만 |
| `from_theta.py` | B-2: wallA 토폴로지 추출 + θ→비용 변환, 스키마 v2 배타 조립 ([설계](../docs/2026-09-01_B2_from_theta_설계.md)) |
| `pibt_mvp_demo.py`, `pibt_heading_demo.py`, `pibt_smoke_real_map.py`, `from_theta_demo.py` | 회귀 테스트 — 코어/배관 수정 시 재실행 |
| `fleet_sweep.py`, `fleet_sweep_b1e.py`, `fleet_sweep_b0h.py` | v1 스윕 / A* vs PIBT 벤치마크(회전 0초, 이력) / **B0′ 기준선**(칸 vs 헤딩) |
| [`results/`](results/) | 벤치마크·검증 산출물 (csv/png/npz) — 기존 결과 덮어쓰기 금지 |
