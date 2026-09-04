# 시뮬 실행 계약 — `sim_engine/sim_v2_tasks.py` 호출 규약 (v2, 2026-09-04)

> **v2 비호환 변경 (2026-09-04, S15P21A106-143):** 기본 이동 모델이 **헤딩 PIBT**로 바뀌었다. 칸 모델은 `--cell` opt-in.
> `--heading`은 그대로 받되 무시한다. **`--heading`을 넘기지 않아 칸 모델을 얻던 호출자는 `--cell`을 넘겨야 한다**
> (A트랙 워커 `objective.py`의 `heading=False` 경로). 로봇 상한 28은 유지 — 의미는 §1 참고.

대상: 시뮬을 **프로세스로 호출하는 쪽** — A트랙 θ 탐색 워커(`infra/worker/objective.py`), 견적 엔진 배치 워커, fleet 스윕 스크립트.
θ 스키마가 `guidance_types.py`로 고정된 것과 같은 이유로, 시뮬 호출 방법도 여기 고정한다. **이 문서에 없는 인자·출력 키에 의존하지 말 것.**
바꿀 때는 B트랙이 이 문서를 먼저 고치고 버전을 올린다(호출자 전원 공지).

## 1. 호출

```
python sim_v2_tasks.py <tag> <n_robots> <n_orders> <seed> <aisle_block> [--flow=main|v1compat] [--theta=<json>]
                       [--cell] [--fixed-homes] [--order-gap=<틱>]   ([--heading] 호환용, 무시)
```
작업 디렉토리 = `3_FMS/sim_engine/` (상대 import). 맵은 `3_FMS/map/occupancy_grid.npy`·`stations.json`·`charge_zone.json`을 읽는다
(컨테이너는 `3_FMS/`를 통째로 마운트하면 된다).

| 위치 인자 | 의미 | 기본 |
|---|---|---|
| `tag` | 실행 라벨. SUMMARY `variant`, 산출 파일명 접두 | `base` |
| `n_robots` | 로봇 대수. 충전 존 초기 배치 상한 **28** (초과 시 assert). **이 값은 이 창고 충전 인프라(동쪽 존 106칸)의 용량이며 견적 제약으로 취급한다** — 더 필요하면 맵 변경(존 추가)이고 그 자체가 견적 출력물 | 6 |
| `n_orders` | 출고 주문 수. main 흐름은 입고도 같은 수 | 40 |
| `seed` | 주문 도착·구성 rng. 같은 인자 = 같은 결과(결정론) | 42 |
| `aisle_block` | `1` = 랙 사이 통로(행 47~67) 로봇 통행 금지(피커 전용). **기준선은 1** | 0 |

| 플래그 | 의미 | 비고 |
|---|---|---|
| `--flow=main` | 입고+출고 흐름. **기본** | v1compat은 B-1e 패리티 전용(A* 비교), θ 탐색에 쓰지 말 것 |
| `--theta=<json>` | θ 11개 JSON(`GuidanceTheta` 필드명). 없으면 uniform 비용(기준선) | 범주형은 정수 |
| (기본) | **헤딩 PIBT**(2칸 차체·회전·후진·라이브니스 5종). v2부터 플래그 없이 기본 | SUMMARY에 `heading=1` |
| `--cell` | 칸 모델(점로봇). 기준선 CSV 재현·A/B 비교축 전용 | v1compat은 플래그와 무관하게 항상 칸 |
| `--heading` | **호환용, 무시** (v1 호출자가 넘기던 플래그) | v1compat에서 넘기면 `[WARN]` 한 줄 |
| `--fixed-homes` | 기존 charger 12칸 고정 홈(이력 재현). 없으면 충전 존 기본 | 견적·탐색엔 쓰지 않음 |
| `--order-gap=<틱>` | 주문·입고 도착 간격 평균(지수분포). 기본 50 | **부하 조절.** 50이면 8~10대부터 수요 제약으로 θ 효과가 안 보임 |

환경변수: `SIM_NO_PLOT=1`(히트맵 png 생략 — **배치는 필수**), `PYTHONIOENCODING=utf-8`(콘솔 한글), `SIM_CHECK=1`(점유 겹침 전수 검사, 느림),
`SIM_DIRFLOW=1`(방향별 흐름 npz), `SIM_NO_DOCK_PRIO=1`(라이브니스 장치 ⑤ 끄기 — A/B용),
`SIM_EXPORT_ISAAC=1`(Isaac 리플레이용 `sim_engine/isaac_export_<tag>/scene.json`·`trajectories.json` — 결과·SUMMARY 불변, 배치에서는 끔). BLAS 스레드는 1로(워커 병렬 시).

## 2. 출력

stdout 마지막 부근에 정확히 한 줄:
```
[SUMMARY] {"variant": ..., "n_robots": ..., ...}
```
JSON 키 (항상 있는 것):

| 키 | 의미 | 단위 |
|---|---|---|
| `variant, n_robots, n_orders, seed, aisle_block, flow` | 입력 에코 | |
| `makespan_steps` | 마지막 태스크 완료 틱 | 틱(=초) |
| `tasks_per_h` | 태스크 처리량 **(권장 목적함수)** | 태스크/시간 |
| `orders_per_h` | 주문 처리량 | 주문/시간 |
| `lead_mean_s, lead_p90_s` | 주문 생성→완료 | 초 |
| `queue_mean_s, drive_mean_s` | 생성→배차 / 배차→완료 | 초 |
| `util` | v1 호환 가동률(서비스 제외·대기 이중계산) | 0~1 |
| `util_incl_service` | 서비스 포함 가동률 | 0~1 |
| `conflict_wait` | 충돌 대기 비율 | 0~1 |
| `pushed_steps` | 밀려난 이동 수 | 틱 |
| `turns_per_task` | 태스크당 회전 수 | 회 |

조건부 키: 헤딩 모델(기본) → `heading=1, rot_steps, rev_steps, replan_steps` (`--cell`이면 없음). 충전 존(기본) → `zone=1, zone_wait_steps, zone_retargets,
zone_degraded, zone_occ_mean, zone_occ_p90, idle_moves`. `--order-gap` → `order_gap`. v1compat에는 존·간격 키가 없다.

호출자 규칙: **모르는 키는 무시**(추가는 비호환 변경이 아님), 키 삭제·의미 변경은 이 문서 버전 업으로만.

산출 파일(`sim_engine/results/`): `SIM_NO_PLOT` 없으면 `sim_v2_<tag>_r<n>[_blk]_<flow>[_th][_h][_fh]_heat.png`. 배치는 끄고 돌린다.

## 3. 종료 코드

| 상황 | 종료 코드 | stdout/stderr |
|---|---|---|
| 정상 | 0 | `[SUMMARY]` 있음 |
| **정체(1500틱 무진전)** | 1 | stdout에 `[STALL] t=…` + 로봇 상태·후보 덤프, stderr `시뮬 정체 감지`. `[SUMMARY]` **없음** |
| 입력 오류(존 용량 초과, 맵 없음 등) | 1 | Traceback |
| 틱 상한 200,000 | 1 | AssertionError |

호출자는 `[SUMMARY]` 부재 = 실패로 처리하고, 극단 θ가 정체를 일으킬 수 있으니 wall-clock 타임아웃(300 s 권장)을 둔다.
정체는 정보다 — θ 탐색에서는 버리지 말고 기록·가지치기(objective.py가 이미 그렇게 한다).

## 4. 실행 시간 (2026-09-04 실측, 동기화 맵, 로컬 Python 3.14 / numpy 2.5.1, 성능 최적화 -136 반영)

| 조건 | 칸 모델 | 헤딩 모델 | (최적화 전) |
|---|---|---|---|
| 6대·40주문·간격 50 | 0.4 s | 1.3 s | 5 s |
| 12대·40주문·간격 50 | 0.4 s | 2.4 s | 12 s |
| 16대·40주문 | 0.5 s | 3.2 s | 16 s |
| 20대·120주문·간격 15 | 0.7 s | 5.5 s | 36 s |
| 24대·120주문·간격 15 | 0.8 s | 7.6 s | 46 s |
| 28대·120주문·간격 15 | 0.9 s | **7.4 s** | 57 s |
| 28대·80주문·간격 25 | 0.7 s | **10.8 s** | 86 s |

θ 탐색·데이터셋 예산은 **헤딩 모델 기준**으로 잡을 것 (1 trial = 시드 3 × 위 시간). 결과는 최적화 전과 비트 동일
([성능최적화_결과](../docs/2026-09-04_성능최적화_결과.md)).

## 5. 재현성

- 같은 인자·같은 코드·같은 numpy 버전 → 비트 동일 결과. 기준값 세 개:
  `base 6 40 42 1 --flow=v1compat` → makespan 2317, tasks_per_h 186.4 (A* 패리티);
  `base 6 40 42 1 --cell --fixed-homes` → 2970 / 127.3 (칸 모델·고정 홈, B-1e 계보);
  **`base 6 40 42 1` → 2850 / 132.6 (v2 기본 = 헤딩 + 충전 존)**.
  **컨테이너 이미지에서 이 세 값이 같은지 먼저 확인**(numpy 버전이 다르면 float 누적이 달라 어긋날 수 있음 — py 3.11.9/numpy 2.4.6에서 앞 두 값은 확인됨, 예산 측정 문서 §2).
- 결과 비교 기준 CSV: `sim_engine/results/b0z_sweep.csv`(40주문), `load_sweep.csv`(고부하). 시뮬 코드 변경 시 B트랙이 이 CSV로 동일성 검사.
- 시뮬은 확률적(시드) — θ 비교는 시드 ≥ 3 평균. 40주문·간격 50에서는 시드 산포가 θ 효과를 덮는다(고부하 문서 §2). **θ 탐색 권장 조건:
  헤딩(기본) `--order-gap=15`(또는 25), 20~28대, aisle_block=1.**

## 6. 권장 탐색 호출 예

```
SIM_NO_PLOT=1 PYTHONIOENCODING=utf-8 python sim_v2_tasks.py bo17 24 120 42 1 --order-gap=15 --theta=/tmp/theta_17.json
```
(`--heading`을 붙여도 결과는 같다. 칸 모델 예비 조사는 `--cell`.)

## 7. 변경 이력

| 버전 | 날짜 | 내용 |
|---|---|---|
| v1 | 2026-09-04 | 최초. `--heading`·`--fixed-homes`·`--order-gap`, 존 키, 장치 ⑤, 동기화 맵 경로 반영 |
| v1.1 | 2026-09-04 | §4 실행 시간 표를 성능 최적화(-136) 후 값으로 갱신 (호출 규약·출력 불변) |
| **v2** | 2026-09-04 | **비호환**: 기본 모델 = 헤딩, `--cell` 신설, `--heading` 호환 무시(-143). §5 헤딩 기본 기준값 2850/132.6 등재. `n_robots` 상한 28의 의미(견적 제약) 명시. 환경변수 `SIM_EXPORT_ISAAC=1`(리플레이 내보내기, 출력 불변) |
| v2.1 | 2026-09-04 | 호환: 시뮬 본체가 `fms_kernel.FmsKernel` + `order_stream.OrderStream` 라이브러리로 분리(-144). **CLI·SUMMARY·종료 코드 불변**(기준값 3개·CSV 80행 비트 동일). 프로세스 대신 in-process 로 부르려면 `sim_v2_tasks.parse_args/build/run_ticks/report` 를 import (simpy_harness.py 가 예) |

관련: [고부하_무릎_판정](../docs/2026-09-04_고부하_무릎_판정.md), [θ_실험_로드맵](../docs/2026-09-04_θ_실험_로드맵_AB공동.md),
[시스템아키텍처_검토](../docs/2026-09-04_시스템아키텍처_검토_B트랙관점.md) §2-4, A트랙 워커 `../infra/worker/objective.py`.
