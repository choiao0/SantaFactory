# fms_core — VDA 5050 플릿 매니저 + Sparkplug Edge `fms-core` (주행 로직 교체형)

EC2 에 상시로 떠서 host-orch 의 NCMD Start 를 받으면 (1) GPU 박스의 T4 에이전트(로봇)가 전원 ONLINE+포즈가 될 때까지 기다리고,
(2) **플래너**(기본 `kernel` = `3_FMS/sim_engine` 의 DES 결정 커널, 무수정)를 만들어 틱마다 로봇별 다음 칸/헤딩을 VDA 5050 order 로 보내고,
(3) 전 로봇이 그 노드에 도착하면(틱 배리어) 다음 틱을 계산한다. Stop 이 오면 `cancelOrder` 를 보내고 DES 와 같은 산식의 KPI 를
`biz/v1/event` kpi_summary 로 낸다 — host-orch 가 `sim.verify.result.kpi` 에 싣는다.
규칙의 원본: [`../contracts/MQTT_CONTRACT.md`](../contracts/MQTT_CONTRACT.md) §4 (VDA 마스터) · §5 (Edge fms-core), [`../contracts/SIM_VERIFY_CONTRACT.md`](../contracts/SIM_VERIFY_CONTRACT.md) §3.
짝: [`../host_orch/`](../host_orch/) (Host), [`2_Simulation/sim_runner/`](../../2_Simulation/sim_runner/) (로봇 쪽 Edge), [`1_Robot/amr_agent/`](../../1_Robot/amr_agent/) (order 수용자).

| 파일 | 역할 |
|---|---|
| `planner.py` | **주행 로직 경계** — `Planner` 프로토콜(`robots · step(t) · drain_events · counters · kpi`), `PlannerSpec` · `RobotView` · `Command`, `PLANNERS` 등록표 + `build_planner` |
| `kernel_planner.py` | `kernel` 플래너 = `FmsKernel + OrderStream` 어댑터. sim_v2_tasks.build() 와 같은 순서로 만들고 CLI 셸과 같은 순서(arrivals → dispatch → move)로 틱을 돌린다. `des_homes(n)` = DES 초기 배치 |
| `conductor.py` | 상태기계 IDLE → STARTING(로봇 대기 → 플래너 → 정렬) → RUNNING(틱 배리어) → IDLE \| ERROR. Sparkplug 메트릭(`Fms/*`) · NCMD · Host STATE · biz 이벤트 |
| `vda.py` | 로봇별 order 스티칭(orderUpdateId = 보낸 노드 번호, 갱신 = [n_k, n_{k+1}]), 재발행 규칙(state 2건 미반영 → 재발행, 10건 → 오류), 도착 판정(`lastNodeId == n_k`), `cancelOrder`, state/connection 거울 |
| `world.py` | 격자 ↔ 월드: 칸 (r, c) → (c + 0.1, r + 0.5) m, 헤딩 h(0=N=+y) ↔ yaw, 한 틱 액션 분류(forward · reverse · turn · wait) |
| `scenario.py` | Start JSON → `RunSpec`(sha 대조), `scenario.orders` → 커널 주문(`window_start_s` 오프셋), DES pass-through(`capacity(토트/왕복) · tote_units · outbound_gap_s · inbound_gap_s · shifts · seed`) |
| `kpi.py` | `cli/report.py` 고정 시간 산식 그대로 → 견적 워커 `to_kpi` 의 14개 키 (`test_kernel_planner` 가 report() 와 대조) |
| `edge.py` · `app.py` | paho 연결부(유언 NDEATH · NBIRTH · ACL 과 1:1 구독) · CLI |
| `spb.py` · `sparkplug_b_pb2.py` | `2_Simulation/sim_runner/` 와 **바이트 동일 복사본** (`tests/test_spb_copy.py`) |
| `tests/` | 브로커 없는 단위 테스트 123개 (1_Robot/amr_agent 의 `OrderBook` 을 오라클로 쓴다). `test_des_parity.py` 는 견적 워커·sim_v2 와 직접 대조한다 |

## 견적과 같은 조건으로 돈다 (S15P21A106-185)

검증 런의 KPI 는 DES 견적 KPI 와 비교하려고 내는 값이다. 그래서 커널 설정은 견적 워커
(`../infra/worker/estimate_worker.py` → `objective.run_once` → `../sim_engine/sim_v2_tasks.py`)와 같아야 한다.
기준을 문서가 아니라 **워커 코드**에서 읽어 대조하는 게 `tests/test_des_parity.py` 다 — 같은 주문·같은 홈이면 두 틱 루프가
같은 KPI 를 낸다(`test_same_orders_give_the_same_kpi`). sim_engine 이 바뀌면 여기서 깨진다.

| 조건 | 값 | 출처 |
|---|---|---|
| 통로차단 | ON | `run_once(aisle_block=1)` — `DES_AISLE_BLOCK` |
| θ 비용 | `THETA_PATH` 또는 `infra/out/theta_wallA_r24_g15.json`, 없으면 중립 + 경고 | 워커 `THETA_PATH` |
| 차선·양보 | ON (`lane_gain = pocket_gain = 2.0`) | sim_v2 v3 기본 (헤딩 main) |
| 적재 | `capacity` = 왕복당 토트 1~6, `tote_units` = 토트당 상품(기본 10, 계약 v3.9 — 개인 주문 상한 10개 = 토트 1개; v2.6~v3.8 은 8), `svc_per_tote` = 5틱 | 워커 `_orders_flags` (계약 v2.6) |
| 교대 | **출고 전용** (견적 기본은 `in,out,out`) | 의도된 차이 — 검증 창은 출고 구간 한 조각이라 창 길이에 in 교대를 다시 자르면 그 시각의 견적 모델과 달라진다 |

바꿔 끼우려면 `--planner-opt aisle_block=0 · theta_path= · lanes=false · yield_rule=false` (전부 견적과 달라지는 방향이다).
합성 창고(`--map-dir`, -139)는 `rack_buffers.json`(WMS 마스터)이 없어 명시 주문 모드를 못 쓴다 — 검증 런 대상이 아니다.

## 주행 로직 바꾸기

새 알고리즘 = `Planner` 프로토콜을 만족하는 클래스 하나 + `planner.PLANNERS` 에 한 줄. 셸(conductor · vda · edge)은 손대지 않는다.
계약은 "한 틱 = 로봇당 한 칸 전진 · 후진 · 90° 회전 · 대기 중 하나, 위치의 진실은 플래너 모델"이다 — 실 로봇은 명령한 칸 중심에
5 cm · 0.03 rad 안으로 멈추므로(에이전트 stop 허용) 다음 틱의 시작 상태가 모델과 같다. `--planner-opt key=value` 로 옵션을 넘긴다
(`kernel`: `aisle_block · theta_path · lanes · yield_rule · fixed_homes · horizon_ticks · order_gap` — 기본값은 위 "견적과 같은 조건" 표).

## 실행

```bash
cd 3_FMS
python3 -m fms_core --env-file infra/emqx/.env -v                       # 상주 (MQTT_HOST · MQTT_PORT · MQTT_PW_FMS_CORE)
python3 -m fms_core --env-file infra/emqx/.env --once start.json --once-window-s 120   # host-orch 없이 Start 1건 → 창 뒤 Stop → 결과 stdout
python3 -m fms_core --spawn 3                                            # DES 와 같은 초기 배치 → Isaac WSIM_SPAWN 문자열
python3 -m pytest fms_core/tests host_orch/tests sim_engine/tests -q   # MR CI(.gitlab-ci.yml fms-python-test)가 도는 것과 같은 묶음
```

옵션: `--planner kernel` · `--tick-s`(틱 최소 길이, 기본 = DES 틱 길이 1 m ÷ 속도, 속도 0.9 → 1.11 s; `--planner-opt speed=` 로 속도 지정) · `--ack-timeout-s 30`(노드 하나 도착 상한) · `--ready-timeout-s 420` ·
`--heartbeat-s 5` · `--host-offline-s 15` · `--state-dir`(bdseq) · `--node-id fms-core` · `--group santa`.

EC2 배포(compose, k3s 전까지): `infra/fms_core.Dockerfile` + `infra/compose.fms-core.yml` (EMQX 네트워크 backbone_default 만).
host-orch 는 `--fms-node fms-core` 로 이 노드를 런에 묶는다(`compose.host-orch.yml` 기본).

```bash
cd ~/fms-core/3_FMS/infra && docker compose -f compose.fms-core.yml up -d --build && docker compose -f compose.fms-core.yml logs -f
```

## 한 런의 흐름

1. host-orch: sim-runner 가 RUNNING(로봇 ONLINE+포즈) 이면 같은 Start 를 fms-core 에 NCMD.
2. fms-core: sha 대조 → STARTING. `uagv/v2/+/+/{connection,state}` 로 전원 ONLINE+포즈 확인 → 로봇 첫 포즈 칸 = 홈으로 플래너 생성 →
   로봇마다 orderUpdateId 0(현재 포즈 = n0) · 1(칸 중심 · 커널 헤딩 = n1) 발행 → 전원 n1 도착 → RUNNING (`Fms/State`).
3. 틱: `planner.step(t)` → 이동·회전 로봇에 orderUpdateId k+1 = [n_k, n_{k+1}] (후진은 엣지 `orientation = π`, 회전은 길이 0) →
   `lastNodeId == n_{k+1}` 전원 도착 + `--tick-s` 경과 → 다음 틱. `Fms/Tick · OpenTasks · DoneTasks · OrdersDone` NDATA, 배차·완료·출하는 `biz/v1/event`.
4. Stop(또는 timeout_s · 로봇 오류/단절 · host offline): 전 로봇 `cancelOrder` → kpi_summary(`kpi` 14키 · `ticks` · `counters`) → IDLE / ERROR.

## 검증

2026-09-09 17:33, GPU 박스에서: EC2 EMQX(tailnet), sim-runner `--mode real`(Isaac, 로봇 2), fms-core · host-orch(`--once --fms-node fms-core`)는 이 박스에서 실행.
요청 = `n_robots 2 · window_s 180 · scenario{orders 8건(seed 42 산출물 앞 8건을 5 s 간격으로), spawn = --spawn 2}`.

| 단계 | 결과 |
|---|---|
| Start → 로봇 준비 | sim-runner Start 뒤 19 s 에 2대 ONLINE+포즈 → host-orch 가 fms-core 에 Start → 0.4 s 뒤 플래너 생성(홈 = (48,103) · (50,103)) |
| 정렬 | orderUpdateId 0(현재 포즈) · 1(칸 중심 + 커널 헤딩 N) → 2대 도착 3.0 s → RUNNING |
| 틱 루프 | 창 180 s 동안 **64 틱** (2.8 s/틱: 1 칸 ≈ 2.2 s + 회전), 재발행 0 · 오류 0, 주행 112 m, `Fms/Tick · OpenTasks` NDATA, `task_assigned` 이벤트 |
| Stop → 결과 | cancelOrder ×2 → kpi_summary → IDLE. host-orch 결과 `done`, `scenario_ack true`, `verify.fms.ticks 64`, `kpi.makespan_s 64 · distance_total_m 112 · amr_utilization 0.961` (창이 짧아 완료 주문 0) |
| 종료 | sim-runner 가 에이전트 → Isaac 사다리로 정리, 고아 프로세스 0 |

**배포 뒤 큐 경로 (2026-09-09 17:41)**: EC2 compose `a106-fms-core` + `a106-host-orch --fms-node`. GPU 박스에서 ssh 터널로 `sim.verify.request` 1건(창 120 s) 투입 →
host-orch Start → sim-runner RUNNING 19 s → fms-core Start → 정렬 3 s → 42 틱 → Stop 둘 다 → `sim.verify.result` `done` + `kpi`(makespan_s 42 · distance 73 m), 투입부터 결과까지 169 s. Isaac 잔여 0.

첫 시도는 실패했다: 로봇 `connection ONLINE` 은 retained 라 fms-core 가 접속 직후(런 없음)에만 받고 버려 `all_ready` 가 안 됐다 → 런 밖에서도 connection 을 기억하도록 고침(`test_retained_connection_before_start_counts`).
리뷰(2026-09-09)가 잡은 것: 재발행이 state 카운터·전송 시각을 되돌려 10건 오류·30 s 도착 상한이 영원히 안 걸리던 버그 → 카운터는 pending 창 안에서 단조 증가, 재발행은 마지막 재발행 대비 2건.

## 남은 것

- 실 로봇 1 칸 ≈ 2.2 s · 90° ≈ 2.5 s 라 커널 틱(1 s)보다 느리다 — 틱 수(`Fms/Tick`)가 창의 DES 초. RTF 를 올리거나 `--tick-s` 를 줄여도 이동 틱은 로봇이 정한다.
- 비동기 실행(ADG 창) · 다른 MAPF 는 새 플래너로. 커널의 `zone_stats["occ"]` 는 틱마다 자라므로 수 시간 런은 아직 아니다.
- `biz/v1/order`(WMS 주문) 구독은 ACL 에 있지만 아직 안 쓴다 — 지금은 Start 의 `scenario.orders` 재생만.
