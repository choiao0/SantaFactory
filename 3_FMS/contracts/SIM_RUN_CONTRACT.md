# 시뮬 실행 계약 — `sim_engine/sim_v2_tasks.py` 호출 규약 (v3.4, 2026-09-14)

> **v2 비호환 변경 (2026-09-04, S15P21A106-143):** 기본 이동 모델이 **헤딩 PIBT**로 바뀌었다. 칸 모델은 `--cell` opt-in.
> `--heading`은 그대로 받되 무시한다. **`--heading`을 넘기지 않아 칸 모델을 얻던 호출자는 `--cell`을 넘겨야 한다**
> (A트랙 워커 `objective.py`의 `heading=False` 경로). 로봇 상한 28은 유지 — 의미는 §1 참고.
>
> **v2.2 호환 변경 (2026-09-05, S15P21A106-145):** 고정 시간 실행(`--horizon`·`--shifts`)과 배터리(`--battery` 계열) 플래그·SUMMARY 키 **추가**.
> 전부 opt-in — 플래그 없는 호출의 결과·출력은 v2.1과 비트 동일(기준값 3개·CSV 80행). 기존 호출자는 바꿀 것 없음.
>
> **v2.3 규약 추가 (2026-09-07, 시드 합의):** **평가 시드 집합 = {101, 103, 104}**(예비 102). θ 성과 보고·B-5·견적 KPI는 이 시드로 채점하고,
> 탐색(BO) 시드 {42, 43, 44}·기준선 CSV 시드 {42, 7}과 **섞지 않는다**. 코드·출력 불변 — §5 참고.
>
> **v2.6 비호환 변경 (2026-09-09, S15P21A106-177):** `--capacity` 단위를 상품 수에서 **왕복당 토트 수(1~6)**로 변경.
> `--tote-units`·`--svc-per-tote`와 SUMMARY 토트·왕복·주문 리드타임 키를 추가했다. 플래그 없는 기존 KPI 값은 비트 동일.
>
> **v3 결과 변경 (2026-09-09, S15P21A106-177):** main 헤딩 모델에 규칙 기반 차선과 지속 정면 조우 양보를 기본 적용한다.
> `--no-lanes`·`--no-yield`로 각각 끌 수 있다. 차선 비용은 **θ 밖**의 시뮬 인자 `--lane-gain`·`--pocket-gain`(기본 2.0)이다 —
> θ 스키마(A트랙 계약, 11개·v2)는 바뀌지 않는다. 2.0 근거: 2·3·5 A/B 에서 5 는 평가 시드 102 의 L1 12·20대에서 새 STALL, 3·2 완주 → 안정적인 2.
> **헤딩 main 전용** — 칸 모델(`--cell`)과 v1compat 은 A/B 기준 축이라 적용하지 않는다. 패리티·기준선 비교는 두 스위치를 모두 끈다.
>
> **v3.3 호환 변경 (2026-09-13, S15P21A106-116):** `--speed=<m/s>` 추가. **커널은 1칸 = 1틱 그대로**이고 틱의 길이만
> `dt = CELL_M / speed`[초]가 된다. 초 단위 입력(창·서비스·주문 도착 시각)은 dt 로 나눠 틱이 되고, 초 단위 출력은 dt 를 곱해 나온다.
> **틱 단위 인자(`--horizon`·`--order-gap`·`--inbound-gap`·`--svc-per-tote`)는 틱 그대로** — 초를 넘기는 호출자(견적 워커)가 dt 로 환산한다.
> SUMMARY 에 `speed`·`dt_s` 항상 출력. `--speed` 를 안 주면(1.0) v3.2 와 비트 동일(기준값 4개·동일성 12행 확인).
> 회전은 속도와 무관하게 1틱(= dt 초)으로 잡히므로 물리 실측 1.511 s 와의 차이는 속도에 따라 ±(태스크당 3~6 %, docs/2026-09-11_안건6건_평가.md §5).
>
> **v3.4 결과 변경 (2026-09-14, S15P21A106-203):** 회전 발자국. 기본 `--footprint=exact` = 0.1 m 지도로 만든 **정적 회전 마스크** —
> 회전 중 차체(기종 카드 앞 0.39·뒤 1.11·폭 0.80 m + 여유 0.05 m)가 랙·벽을 스치는 (칸, 회전) 조합을 금지한다(실제 맵에서 legacy 허용
> 회전의 3.5 %). 코 모서리 반경 hypot(0.39, 0.40) = 0.56 > 0.5 라 앞 칸 경계까지 찬 랙에 0.06(여유 포함 0.13) m 들어가던 것을 막는다
> (Isaac 실측 iw.hub 2 cm·선반형 5.9 cm 침범). **기본값이 헤딩 결과를 바꾸므로 기준값이 바뀐다**(§5). `--footprint=legacy` 는 v3.3 과 비트 동일.
> 칸 모델(`--cell`)·v1compat 은 회전이 없어 그대로. `--footprint=exact,front`(앞 2칸 축 규칙 + 양보 v2)는 실험용 — 정면 대치(소싸움)
> 해소가 미완이라 처리량 −5~−27 %, 일부 시드 STALL (docs/2026-09-14_S15P21A106-203_B_앞칸축규칙_양보v2_중간보고.md).

대상: 시뮬을 **프로세스로 호출하는 쪽** — A트랙 θ 탐색 워커(`infra/worker/objective.py`), 견적 엔진 배치 워커, fleet 스윕 스크립트.
θ 스키마가 `guidance_types.py`로 고정된 것과 같은 이유로, 시뮬 호출 방법도 여기 고정한다. **이 문서에 없는 인자·출력 키에 의존하지 말 것.**
바꿀 때는 B트랙이 이 문서를 먼저 고치고 버전을 올린다(호출자 전원 공지).

## 1. 호출

```
python sim_v2_tasks.py <tag> <n_robots> <n_orders> <seed> <aisle_block> [--flow=main|v1compat] [--theta=<json>]
                       [--cell] [--fixed-homes] [--order-gap=<틱>] [--inbound-gap=<틱>]   ([--heading] 호환용, 무시)
                       [--horizon=<틱>] [--shifts=in,out,out]                                    (v2.2 고정 시간·교대)
                       [--battery] [--chargers=6] [--runtime-h=8] [--charge-h=1.5] [--soc=20,80,95]  (v2.2 배터리)
                       [--orders-file=<json>] [--capacity=1] [--tote-units=<상품 수>] [--svc-per-tote=0]
                       [--no-lanes] [--no-yield] [--map-dir=<맵 세트 폴더>]
                       [--section-limit=0] [--section-grid=3]                    (v3.2 구간 대수 제한)
                       [--speed=1.0]                                             (v3.3 속도: 틱 길이 = CELL_M / speed)
                       [--footprint=exact] [--robot-dims=0.39,1.11,0.80]         (v3.4 회전 발자국: 정적 마스크 · 기종 치수)
```
작업 디렉토리 = `3_FMS/sim_engine/` (상대 import). 맵은 `3_FMS/map/occupancy_grid.npy`·`stations.json`·`charge_zone.json`을 읽는다
(컨테이너는 `3_FMS/`를 통째로 마운트하면 된다). `--map-dir`을 주면 그 폴더에서 같은 파일들을 읽는다.

| 위치 인자 | 의미 | 기본 |
|---|---|---|
| `tag` | 실행 라벨. SUMMARY `variant`, 산출 파일명 접두 | `base` |
| `n_robots` | 로봇 대수. 공식 맵의 충전 존 초기 배치 상한 **28** (초과 시 assert). `--map-dir`을 쓰면 상한은 **그 맵의 존 용량**이다(합성 창고는 24~42, `map/synth/README.md` 표). **이 값은 이 창고 충전 인프라(동쪽 존 106칸)의 용량이며 견적 제약으로 취급한다** — 더 필요하면 맵 변경(존 추가)이고 그 자체가 견적 출력물 | 6 |
| `n_orders` | 출고 주문 수. main 흐름은 입고도 같은 수. **`--horizon`이 있으면 무시**(0을 넣어 자리만 채움) | 40 |
| `seed` | 주문 도착·구성 rng. 같은 인자 = 같은 결과(결정론) | 42 |
| `aisle_block` | `1` = 랙 사이 통로(행 47~67) 로봇 통행 금지(피커 전용). **기준선은 1** | 0 |

| 플래그 | 의미 | 비고 |
|---|---|---|
| `--flow=main` | 입고+출고 흐름. **기본** | v1compat은 B-1e 패리티 전용(A* 비교), θ 탐색에 쓰지 말 것 |
| `--theta=<json>` | θ 11개 JSON(`GuidanceTheta` 필드명). 없으면 중립 θ | 범주형은 정수 |
| `--lane-gain=<≥1.0>` `--pocket-gain=<≥1.0>` | 차선 줄 역방향·주머니 줄 통과 비용 배수(θ 밖, -177) | 기본 2.0. `--no-lanes` = 둘 다 1.0 |
| `--capacity=<1..6>` | 출고 왕복당 함께 싣는 토트 수 | 기본 1(동승 없음) |
| `--tote-units=<정수>` | 버퍼별 `ceil(qty 합 / tote_units)`로 주문 토트 수 계산 | 없으면 버퍼당 1토트 |
| `--svc-per-tote=<틱>` | 픽업·하역 각각 `토트 수 × 값`을 기본 서비스 시간에 가산 | 기본 0 |
| `--no-lanes` | 규칙 기반 출발·복귀 차선과 버퍼 주머니 비용을 끔 | 헤딩 main 기본 ON. `--lane-gain=1 --pocket-gain=1`과 같음 |
| `--map-dir=<폴더>` | 맵 세트 폴더. 격자·스테이션·충전 존·토폴로지를 전부 여기서 읽는다 | 기본 = 공식 맵 `3_FMS/map`. 합성 창고는 `map/synth/<이름>`(-139). 폴더에 `topology.json`이 있으면 통로·밴드 좌표를 거기서, 없으면 wallA 상수 |
| `--no-yield` | 8틱 이상 지속된 정면 조우의 양보 규칙을 끔 | main 헤딩 기본 ON |
| `--section-limit=<N>` | 블록당 동시 대수 상한. **0 = 끔** | 실질 0/1 스위치다 — N≥2 는 같은 블록 안 두 대가 마주보는 걸 못 막아 무효거나 악화(실측 §5-2) |
| `--section-grid=<k>` | 블록 한 변[칸]. `--section-limit>0` 일 때만 의미 | 기본 3. 크면 정체 면제로 풀려 무력해진다 |
| `--speed=<m/s>` | 로봇 속도 → **틱 길이** `dt = CELL_M / speed`[초]. 0.1~5.0 | v3.3. 기본 1.0(= 1틱 1초, 비트 동일). 틱 단위 인자는 환산하지 않는다 — 초를 가진 호출자가 `초 / dt` 로 넘길 것. 서비스 틱 `round(3.64 / dt)`·토트당 서비스는 호출자 반올림이라 속도에 따라 ±1틱 |
| `--footprint=exact\|legacy\|exact,front` | 회전 발자국 (v3.4). `exact`(기본) = 0.1 m 지도 정적 회전 마스크, `legacy` = v3.3 비트 동일(뒤 3칸만), `exact,front` = 앞 2칸 축 규칙+양보 v2(실험용, 양보 규칙 강제 ON) | 헤딩 전용 — 칸 모델·v1compat 은 legacy 로 기록 |
| `--robot-dims=<앞>,<뒤>,<폭>` | 구동축 기준 차체 치수[m] — 마스크·앞 스윙 판정·Isaac `robot_dim_m` | 기본 0.39,1.11,0.80 (선반형 기종 카드, 물리 팀 2026-09-13) |
| (기본) | **헤딩 PIBT**(2칸 차체·회전·후진·라이브니스 5종). v2부터 플래그 없이 기본 | SUMMARY에 `heading=1` |
| `--cell` | 칸 모델(점로봇). 기준선 CSV 재현·A/B 비교축 전용 | v1compat은 플래그와 무관하게 항상 칸 |
| `--heading` | **호환용, 무시** (v1 호출자가 넘기던 플래그) | v1compat에서 넘기면 `[WARN]` 한 줄 |
| `--fixed-homes` | 기존 charger 12칸 고정 홈(이력 재현). 없으면 충전 존 기본 | 견적·탐색엔 쓰지 않음 |
| `--order-gap=<틱>` | 주문·입고 도착 간격 평균(지수분포), 양수. 기본 50 | **부하 조절.** 50이면 8~10대부터 수요 제약으로 θ 효과가 안 보임 |
| `--inbound-gap=<틱>` | 입고 간격만 따로, 양수. 기본 = `--order-gap` | v2.2. 유한·고정 시간 모드 모두. v1compat은 무시(`[WARN]`) |
| `--horizon=<틱>` | **고정 시간 실행**(Lifelong): 유한 주문 대신 T틱까지 돌리고 T 안의 완료 수로 처리량. `makespan_steps`=T, 리드타임 표본 = T 안 완료분 | v2.2. main 전용. 도착은 교대 창 안에서만 생김 |
| `--shifts=in,out,out` | 전체 실행 시간 T를 토큰 수로 등분하고, 창마다 `in`(입고)/`out`(출고) **한 종류만** 도착. 연속된 같은 토큰은 한 창으로 합침. 기본 = 앞 1/3 입고, 뒤 2/3 출고 | v2.2. `--horizon` 없으면 무시. 같은 gap이면 유한 모드보다 순간 부하가 절반(한 종류만 오므로) |
| `--battery` | SoC 틱 모델 + 충전 도크(`charger[0..k)` 칸, 동쪽 존 안). 임무 없는 로봇: SoC<low 강제(배차 제외), SoC<go 기회 충전, ≥leave 종료. 임무 중엔 태스크를 끝내고 감 | v2.2. 존 기본값 전용(`--fixed-homes`·v1compat 불가). 초기 SoC 30~100 % 균등(시드) |
| `--chargers=<1..6>` `--runtime-h=8` `--charge-h=1.5` `--soc=low,go,leave` | 도크 수 / 가동 시간(주행 70 %·유휴 30 % 혼합 기준, 정지 소모 = 주행의 1/4) / 만충 시간 / 임계 % | v2.2. `--battery`와 함께. [배터리 설계](../docs/커널_시뮬_구조.md#배터리와-충전-도크) |

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
| `speed, dt_s` | `--speed` 에코와 틱 길이[초] (v3.3). 아래 초 단위 키는 전부 `틱 × dt_s` | m/s, 초 |
| `footprint, robot_dims, turn_masked` | `--footprint` 에코, 치수 [앞,뒤,폭], legacy 가 허용하던 (칸,회전) 중 마스크가 금지한 비율 (v3.4; legacy 는 0) | 문자열, m, 비율 |
| `makespan_steps` | 마지막 태스크 완료 틱 | 틱(초 = `× dt_s`) |
| `tasks_per_h` | 태스크 처리량 **(권장 목적함수)** | 태스크/시간 |
| `orders_per_h` | 주문 처리량 | 주문/시간 |
| `lead_mean_s, lead_p90_s` | 태스크 생성→완료(기존 키) | 초 |
| `order_lead_mean_s, order_lead_p90_s` | 주문 생성→모든 토트 완료 | 초 |
| `queue_mean_s, drive_mean_s` | 생성→배차 / 배차→완료 | 초 |
| `util` | v1 호환 가동률(서비스 제외·대기 이중계산) | 0~1 |
| `util_incl_service` | 서비스 포함 가동률 | 0~1 |
| `conflict_wait` | 충돌 대기 비율 | 0~1 |
| `pushed_steps` | 밀려난 이동 수 | 틱 |
| `turns_per_task` | 태스크당 회전 수 | 회 |

조건부 키: 헤딩 모델(기본) → `heading=1, rot_steps, rev_steps, replan_steps` (`--cell`이면 없음). 충전 존(기본) → `zone=1, zone_wait_steps, zone_retargets,
zone_degraded, zone_occ_mean, zone_occ_p90, idle_moves`. `--order-gap` → `order_gap`. `--inbound-gap` → `inbound_gap`. v1compat에는 존·간격 키가 없다.

v2.2 조건부 키:
- `--horizon` → `horizon_steps`(=T), `shifts`(토큰열 문자열), `orders_done`(T 안 완료 주문), `open_tasks`(접수됐으나 미완료), `tasks_in`/`tasks_out`(완료 태스크 종류별).
  이때 `n_orders` = 실제 생성된 주문 수, `orders_per_h` = 완료 주문/시간, `makespan_steps` = T. `stall_warnings`는 1500틱 완료 무진전 경고 횟수이며 고정 시간 실행은 계속된다.
- `--battery` → `battery=1, chargers, charge_events`(충전 진입 횟수), `charging_steps`(전 로봇 충전 틱 합), `dock_wait_steps`(강제 충전인데 도크 없어 기다린 로봇·틱),
  `charge_evictions`(강제 충전 로봇을 위해 `(low+go)/2` 이상 충전된 로봇을 내보낸 횟수), `soc_min`(%), `soc_end_mean`(%), `soc_empty_steps`(SoC 0 % 체류 틱 — 0이 아니면 충전기 부족 신호), `dock_util`(0~1).

v2.4 항상 키(모드 무관): `inbound_total`(생성된 입고 수 — v1compat 0), `distance_m`(전 로봇 주행 칸 합 × 1.0 m). 견적 워커(`infra/worker/estimate_worker.py`)가 명세 §1-2 `inbound_total`·`distance_total_m`으로 그대로 낸다.

v3 항상 키: `lanes`, `yield_rule`, `yield_events`. 양보 이벤트 상세는 STALL 진단 덤프의 최근 12건에 남는다.

v2.5 명시 주문 모드(-156): `--orders-file=<json>`(큐 명세 §1-1 `outbound[]` — 생성기 출력·요청 메시지·맨 리스트 허용) 이 있으면 주문을 파일에서 흘린다.
v2.6부터 도착 틱 = `ordered_at_s`(1틱 = 1초), `rack_id` → `map/rack_buffers.json` → `aisle_buf[i]`, 토트 수는 버퍼별 `ceil(qty 합 / tote_units)`이며 합계 6 초과 주문은 제외한다.
`n_orders` 위치 인자와 출고 교대 창은 무시, 입고는 기존 규칙. 항상 키 `capacity`, `tote_units`(미지정 시 null), `totes`(생성 출고 토트), `trips`(완료 출고 왕복),
`orders_oversize`, `order_lead_mean_s`, `order_lead_p90_s`; 명시 주문 조건부 키 `orders_file=1`, `orders_skipped`. 기존 `lead_*`는 태스크 기준으로 유지한다.

호출자 규칙: **모르는 키는 무시**(추가는 비호환 변경이 아님), 키 삭제·의미 변경은 이 문서 버전 업으로만.

산출 파일(`sim_engine/results/`): `SIM_NO_PLOT` 없으면 `sim_v2_<tag>_r<n>[_blk]_<flow>[_th][_h][_fh][_hz][_bat]_heat.png`. 배치는 끄고 돌린다.

## 3. 종료 코드

| 상황 | 종료 코드 | stdout/stderr |
|---|---|---|
| 정상 | 0 | `[SUMMARY]` 있음 |
| **정체(1500틱 무진전), 유한 모드** | 1 | stdout에 `[STALL] t=…` + 로봇 상태·후보 덤프, stderr `시뮬 정체 감지`. `[SUMMARY]` **없음** |
| **정체(1500틱 무진전), 고정 시간 모드** | 0 | `[WARN]`과 SUMMARY `stall_warnings`에 기록하고 T까지 계속 |
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
([성능 최적화 결론](../docs/이동계층_PIBT.md#성능-최적화-결론)).

고정 시간 모드(v2.2, 2026-09-05 실측, 같은 환경): 24대·3 h·간격 15 → 약 40 s(`SIM_CHECK=1` 포함 51 s), 24대·6 h·간격 15·배터리 → 약 60 s, **28대·6 h·간격 15·배터리 → 90 s**,
24대·6 h·간격 7.5·배터리(과부하) → 91 s. 실행 시간은 설정한 고정 시간에 비례하고 배터리는 거의 공짜다.

## 5. 재현성

- 같은 인자·같은 코드·같은 numpy 버전 → 비트 동일 결과. 기준값 (v3.4, 2026-09-14):
  `base 6 40 42 1 --flow=v1compat` → makespan 2317, tasks_per_h 186.4 (A* 패리티, 회전 없음 → 불변);
  `base 6 40 42 1 --cell --fixed-homes` → 2970 / 127.3 (칸 모델·고정 홈, B-1e 계보, 불변);
  `base 6 40 42 1 --no-lanes --no-yield` → **2823 / 133.9** (헤딩 + 충전 존 + 회전 마스크, 차선·양보 끔; v3.3 은 2850 / 132.6);
  **`base 6 40 42 1` → 2889 / 130.8 (v3.4 기본 = 헤딩 + 충전 존 + 차선 gain 2 + 양보 + 회전 마스크; v3.3 은 2822 / 133.9)**;
  `base 6 40 42 1 --speed=1.1` → 2889틱 / 143.9.
  `--footprint=legacy` 를 붙이면 v3.3 값(2850 / 132.6, 2822 / 133.9)과 비트 동일.
  결과 비교 CSV(`b0z_sweep.csv`·`load_sweep.csv`·`load_sweep_eval.csv`)는 **스위치 OFF·legacy 기준을 그대로 보존**하고
  `check_results_identity.py` 가 `--no-lanes --no-yield --footprint=legacy` 로 재현한다. v3 기본값 재측정은 `*_v3.csv`·`*_v3.png`,
  v3.4 기본값 재측정은 `*_v34.csv`·`*_v34.png` 에 따로 둔다(칸 모델 행은 원본 CSV 와 비트 동일).
  **컨테이너 이미지에서 이 세 값이 같은지 먼저 확인**(numpy 버전이 다르면 float 누적이 달라 어긋날 수 있음 — py 3.11.9/numpy 2.4.6에서 앞 두 값은 확인됨, 예산 측정 문서 §2).
- 결과 비교 기준 CSV: `sim_engine/results/b0z_sweep.csv`(40주문), `load_sweep.csv`(고부하). 시뮬 코드 변경 시 B트랙이 이 CSV로 동일성 검사.
- 시뮬은 확률적(시드) — θ 비교는 시드 ≥ 3 평균. 40주문·간격 50에서는 시드 산포가 θ 효과를 덮는다(고부하 문서 §2). **θ 탐색 권장 조건:
  헤딩(기본) `--order-gap=15`(또는 25), 20~28대, aisle_block=1.**
- **시드 역할 분리 (v2.3, 2026-09-07 합의).** 시드는 세 집합으로 나누고 역할을 넘나들지 않는다.

  | 집합 | 시드 | 쓰임 | 비고 |
  |---|---|---|---|
  | 탐색 | 42, 43, 44 | BO가 θ 후보를 채점할 때 (`run_study.py --seeds` 기본) | "쉬운 시드" — 이 시드로 성과를 재면 최대 1.6배 부풀려짐 |
  | **평가** | **101, 103, 104** | **θ 성과 보고, B-5 스윕, 방식 비교표, 견적 KPI** | 예비 102 (16대·L2·헤딩 기준선 STALL 기록, 라이브니스 후속) |
  | 기준선 | 42, 7 | 결과 동일성 검사 CSV(`b0z_sweep.csv`, `load_sweep.csv`) | 코드 변경 검증 전용. 성과 수치로 쓰지 않음 |

  평가 시드 기준선 CSV: `sim_engine/results/load_sweep_eval.csv`(시드 4개 × 고부하 격자 24). 평가 시드 처리량은 탐색 시드보다 3~5 % 낮게
  나오는 것이 정상 — 비교는 같은 집합끼리만. 근거: [시드 역할](../docs/θ_경로_기준선.md#시드-역할).

## 5-2. 구간 대수 제한 — 측정과 한계 (v3.2, S15P21A106-193)

정면 조우(소싸움)를 통행 칸의 k×k 블록별 동시 대수로 묶는다. 공식 맵 · 250건 · gap 4 ·
6토트 · 16·20대 × 평가 시드 3개 = **6런**, 지표는 "창고 전체에서 8틱 이상 지속된 정면 마주보기".

| 설정 | makespan | 8틱+ 마주보기 | 최장 지속 |
|---|---|---|---|
| 끔 (기본) | 기준 | 1115건 | 67~104틱 |
| `--section-limit=1 --section-grid=3` | **+3.2 %** | **372건 (−67 %)** | **10~16틱** |
| `--section-limit=1 --section-grid=2` | +7.2 % | 318건 (−71 %) | 8~10틱 |

**세 가지를 알고 써야 한다.**

1. **N 은 사실상 0/1 스위치다.** 소싸움은 밀도가 아니라 방향 문제라, 한 블록에 2대를 허용하면
   그 2대가 마주보는 걸 못 막는다. 실측(16대·시드 101)에서 N=2 는 8틱+ 가 102→**121건으로 늘었고**,
   N=4·5 는 진입 차단이 3회·0회로 규칙이 없는 것과 결과가 같았다. N=1 만 블록당 배타 점유가
   되어 듣는다 — 철도 폐색과 같은 구조다.
2. **k 는 클수록 조이는 게 아니라 무력해진다.** 8×8·N=1 은 64칸에 1대라 로봇이 계속 정체 →
   면제로 풀려 92건(대가 +29 %)이었다. 3×3 이 무릎이다.
3. **정체 면제가 없으면 교착으로 죽는다.** 진입만 막고 퇴출을 허용해도 순환 대기는 남는다 —
   블록 4·6·8 × N 1·2·3 의 **8가지 조합이 전부 STALL** 이었다. 정체가 `SECTION_RELEASE`(8틱)를
   넘은 로봇을 정원에서 푸는 것이 유일한 탈출구다. `section_releases` 가 `section_blocks` 에
   육박하면 규칙이 사실상 안 걸리고 있다는 신호다.

θ 탐색에는 기본(끔)을 쓴다. 이 규칙은 θ 밖의 운영 규칙이고, 켜면 혼잡 패턴이 바뀌어 θ 를
다시 뽑아야 한다.

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
| **v2.2** | 2026-09-05 | 호환(추가만, -145): **고정 시간 실행** `--horizon`·`--shifts`(입고/출고 교대, 기본 앞 1/3 입고·뒤 2/3 출고)·`--inbound-gap`, **배터리·충전 도크** `--battery`·`--chargers`·`--runtime-h`·`--charge-h`·`--soc`. SUMMARY 조건부 키 §2. 플래그 없는 호출은 v2.1과 비트 동일(기준값 3개·CSV 80행·STALL 덤프·Isaac 내보내기). `run_ticks(kernel, stream, horizon=None)` 시그니처에 선택 인자 추가. Isaac `actions` 어휘에 `"charge"` 추가(배터리 모드에서만 등장) |
| v2.3 | 2026-09-07 | 규약만(코드·출력 불변): §5 **시드 역할 분리** — 탐색 {42,43,44} / **평가 {101,103,104}**(예비 102) / 기준선 {42,7}. 평가 시드 기준선 CSV `load_sweep_eval.csv` 등재 |
| v2.4 | 2026-09-08 | 호환(키 추가만, -155): SUMMARY `inbound_total`·`distance_m` 항상 출력. 값·CLI·종료 코드 불변(기준값 3개·동일성 12행 확인). 호출자에 **견적 워커** `infra/worker/estimate_worker.py` 추가([설계](../docs/견적_워커.md)) |
| v2.5 | 2026-09-09 | 호환(추가만, -156): **명시 주문 모드** `--orders-file`·`--capacity`, 조건부 SUMMARY 키 `orders_file`·`orders_skipped`·`capacity`. `map/rack_buffers.json`(랙 → 버퍼, `build_rack_map.py`) 신설. 플래그 없는 호출은 비트 동일(기준값 3개·동일성 12행 확인) |
| **v2.6** | 2026-09-09 | **비호환**(-177): `capacity` 단위 상품 수→토트 수. `tote_units`·`svc_per_tote`, 동승 완료, 6토트 초과 제외, 토트·왕복·주문 리드타임 SUMMARY 추가. `capacity=1`, `svc_per_tote=0`, `tote_units` 미지정 시 기존 KPI 비트 동일 |
| v3.1 | 2026-09-10 | 호환(추가만, -139·-183): `--map-dir=<맵 세트 폴더>`, 조건부 SUMMARY 키 `map_dir`. 맵 세트에 `topology.json`이 있으면 통로·밴드 좌표를 거기서 읽는다(없으면 wallA 상수). `n_robots` 상한이 그 맵의 충전 존 용량이 된다. 인자를 안 주면 v3와 비트 동일(기준값 3개·동일성 12행 확인). θ 탐색 워커 `run_study.py --map-dir`이 이 인자로 호출하고 `meta.condition.map_dir`에 fms_root 기준 상대 경로를 남긴다 |
| **v3.2** | 2026-09-11 | 호환(추가만, -193): `--section-limit=<N>`·`--section-grid=<k>`, 조건부 SUMMARY 키 `section_limit`·`section_grid`·`section_blocks`·`section_releases`. 통행 칸을 k×k 블록으로 자르고 블록당 동시 대수를 N 으로 묶어 정면 조우(소싸움)를 줄인다. `--section-limit` 을 안 주면 v3.1과 비트 동일(기준값 3개 확인). 측정·한계는 §5-2 |
| **v3.3** | 2026-09-13 | 호환(추가만, -116): `--speed=<m/s>`(틱 길이 = CELL_M / speed), SUMMARY `speed`·`dt_s` 항상 출력. 커널 틱 동역학 불변, 초 환산만. 인자 없으면 v3.2 와 비트 동일(기준값 4개·동일성 12행). 견적 워커가 `amr.avg_payload_kg`+앵커로 `contracts/speed_model.speed_for_load`, 없으면 0.9 m/s(물리 계획 속도)를 넘긴다 |
| **v3.4** | 2026-09-14 | **결과 변경**(-203): 회전 발자국 `--footprint=exact`(기본) = 0.1 m 지도 정적 회전 마스크(기종 카드 0.39/1.11/0.80 + 여유 0.05), `--robot-dims`, SUMMARY `footprint`·`robot_dims`·`turn_masked` 항상. 헤딩 기준값 2822→2889 / 133.9→130.8, `--no-lanes --no-yield` 2850→2823. `--footprint=legacy` 는 v3.3 비트 동일(동일성 12행은 스크립트가 legacy 고정). 칸 모델·v1compat 불변. `exact,front`(앞 2칸 축 규칙+양보 v2)는 실험용. fms_core `--planner-opt footprint=/robot_dims=` 같은 마스크. 재측정 `*_v34.csv` |
| **v3** | 2026-09-09 | **결과 변경**(-177): 헤딩 main 기본 차선(`--lane-gain`·`--pocket-gain` 2.0, θ 밖)·양보, `--no-lanes`·`--no-yield`, SUMMARY `lanes`·`yield_rule`·`yield_events`. θ 스키마는 11개 v2 그대로. 기준선은 두 스위치를 끄면 비트 동일 |

관련: [고부하 기준](../docs/θ_경로_기준선.md#고부하-l1l2), [θ 로드맵](../docs/남은과업_계획.md#부록-a-θ-로드맵-단계표),
[시스템 아키텍처의 계산 예산](../docs/남은과업_계획.md#부록-b-아키텍처에서-고칠-것-5개), A트랙 워커 `../infra/worker/objective.py`.
