# MQTT 계약 — EMQX 백본 (v1.0-draft, 2026-09-08)

FMS ↔ AMR 에이전트 ↔ sim-runner ↔ Host ↔ 시뮬 WMS 가 한 브로커 위에서 지키는 것. 코드는 이 문서만 참조한다.
원천: 아키텍처 v3.8 §03·⑤ · MQTT 백본 가이드 Rev D(2026-09-07) · VDA 5050 2.0.0 · Sparkplug B 3.0.
실행 파일: [`../infra/emqx/`](../infra/emqx/) (compose · emqx.conf · acl.conf), 테스트: [`tests/test_acl_matrix.py`](tests/test_acl_matrix.py).
상태 표기 — **적용**: 코드·설정에 반영되고 테스트로 고정 / **예정**: 문서만.

## 0. 브로커

| 항목 | 값 | 상태 |
|---|---|---|
| 이미지 | `emqx/emqx:6.3.0@sha256:3b6d9c0c419930074b7e0e6cba07baceea584b2094d22f16ff02f6c075c3d5b8` (Hub 2026-09-08: latest = 6 = 6.3 = 6.3.0 같은 digest). compose · k3s Deployment · 이 표 세 곳 일치 | 적용 (compose) / 예정 (k3s) |
| 라이선스 | 6.x = BSL 1.1 + 동봉 Community License: "단일 노드 내부 환경 무료 사용", 클러스터·SaaS 재판매는 별도. `emqx ctl license info`: type community, max_sessions 10,000,000, 2029-03-01 까지. Apache 2.0 이 필요하면 5.8.9 (`sha256:35b46f7a…`) | 적용 |
| 설정 | HOCON `emqx.conf` — 키는 EMQX 6.3.0 실행으로 검증(2026-09-08). `node.data_dir` 필수, `security_profile` 기본 hardened | 적용 |
| 프로토콜 | MQTT 3.1.1 · clean session · QoS 상한 1 (`mqtt.max_qos_allowed`) · 패킷 1 MB · keepalive 30 s(sim-runner 60 s) | 적용 |
| 노출 | 1883 만. 로컬은 호스트 1883. EC2 는 보안 그룹이 443·80 만 열고 MQTT 는 tailscale 터널로만 — 현재 compose(`~/emqx/`) `100.100.149.68:1883`, k3s 이전 후 NodePort 31883. 공인 IP 1883/31883 차단 확인(2026-09-08). 대시보드는 127.0.0.1 / port-forward | 적용 (로컬 · EC2 compose) / 예정 (k3s) |
| 인증 | 내장 DB, `user_id_type = username`, 최초 기동 때 `etc/users.csv` 부트스트랩(평문, 644 — 컨테이너 emqx 사용자가 읽어야 함). 익명 거부. EC2 브로커에 대해 ACL 50항목 · 에이전트 접속·factsheet·LWT 확인(2026-09-08) | 적용 |
| 인가 | 파일 ACL `etc/acl.conf`, `no_match = deny`, `deny_action = disconnect` (위반 클라이언트는 끊긴다) | 적용 |
| retained | `connection`·`factsheet`·`spBv1.0/STATE/+` 에만 허용. 그 외 토픽의 retained 발행은 ACL 로 거부 | 적용 |

## 1. 결정 기록

| # | 항목 | 값 |
|---|---|---|
| 1 | Sparkplug group_id | `santa` 고정. 런 ID 는 메트릭 `Runner/RunId` |
| 2 | edge_node_id | `sim-runner-gpu01`, `fms-core` |
| 3 | device_id | VDA serialNumber 와 동일 `amr01…` |
| 4 | Primary Host | `host-orch` = GPU 런 큐(RabbitMQ `sim.verify.request`)의 유일한 소비자, 상시 Deployment 1개, AMQP ↔ MQTT 다리. 견적 BE 가 DES 결과(`sim.result`) 회수 후 최적 1건을 적재한다. DES 워커는 GPU 큐를 모른다. host_id 당 Host 하나 |
| 5 | VDA manufacturer / serial | 기종별 manufacturer(iw.hub = `idealworks`), 시리얼은 기종당 고정 풀. FMS 구독은 `uagv/v2/+/+/…` |
| 6 | username · clientId | = 시리얼 또는 edge_node_id / host_id. ACL 이 `${username}` 으로 걸린다. amr 풀은 한 비밀번호(sim-runner 가 N 대를 한 계정군으로 기동) |
| 7 | QoS · retained | §2 레인표. retained 는 connection · factsheet · STATE 뿐 |
| 8 | 런 ↔ 세션 | sim-runner 상시 NBIRTH, 런 시작 = DBIRTH ×N, 종료 = DDEATH ×N |
| 9 | 하트비트 | `Runner/Heartbeat` 5 s, 3회 결측 = 런 실패 → Stop |
| 10 | order 재발행 | 그 로봇 state 2건 도착에도 미반영 → 같은 order(같은 orderUpdateId) 재발행, state 10건 → 로봇 오류. ONLINE 복귀 시 1회. ONLINE 인데 30 s 무소식 = CONNECTIONBROKEN 취급. 벽시계 틱은 쓰지 않는다(에이전트 state 는 sim time) |
| 11 | 주문 유실 방지 | Host 가 fms-core RUNNING(NBIRTH `Fms/RunId` 일치) 확인 후 REST `POST /run/{id}/start` 로 WMS 수요 생성 시작. fms-core 단절 > keepalive = 런 실패 |
| 12 | 이벤트 | Sparkplug 메트릭에 싣지 않는다(RBE · protobuf). `biz/v1/event` JSON |
| 13 | Host 의 읽기 | host-orch 는 세 레인 전부 구독 가능(관측 창 · 런 KPI). VDA 발행은 못 한다 |
| 14 | 잡 큐 (2026-09-08, A안) | RabbitMQ 프로세스 하나(4_Web compose)에 큐 둘: DES `sim.request/result`(워커 ×M, prefetch 1 = CPU 풀 자원 관리) + Isaac `sim.verify.request/result`(host-orch 1, prefetch = IDLE GPU 러너 수). BE 는 AMQP 만, GPU 서버는 MQTT 만, host-orch 만 둘 다. 결과 발행 후 ack. 미정: `sim.verify.*` 의 consumer-timeout 정책 vs 즉시 ack + BE TIMEOUT 재시도, 검증 런 길이(DES 6 h 대비 Isaac 창), 견적 상태 `VERIFYING` |

| | VDA 5050 | Sparkplug B |
|---|---|---|
| 접속 | connection ONLINE retained QoS1 → factsheet retained QoS1 | Will = NDEATH(bdSeq) → NBIRTH(bdSeq, seq 0, 전 메트릭, Node Control/Rebirth) |
| 종료 | connection OFFLINE retained | DDEATH → NDEATH |
| 단절 | LWT CONNECTIONBROKEN retained | LWT NDEATH. Host 는 그 노드의 디바이스를 stale |
| 순번 | headerId 증가. 같은 orderUpdateId 는 오류 없이 무시, 낮으면 orderUpdateError | seq 0~255 순환, bdSeq 는 세션마다 +1. seq 갭 → Host 가 Rebirth NCMD |
| Host 재기동 | state 의 orderId · lastNodeId 로 복구 | STATE online 갱신 → Edge 가 NBIRTH · DBIRTH 재발행 |

## 2. 레인 · 토픽 · QoS

| 레인 | 표준 | 발행 → 구독 | 토픽 | QoS / retained / LWT |
|---|---|---|---|---|
| 주문 · 즉시동작 | VDA | fms-core → 에이전트 | `uagv/v2/{mfr}/{serial}/order` · `instantActions` | 0 / — / — |
| 상태 · 시각화 | VDA | 에이전트 → fms-core | `…/state` · `visualization` | 0 / — / — |
| 접속 | VDA | 에이전트 → fms-core | `…/connection` | 1 / 예 / CONNECTIONBROKEN |
| 팩트시트 | VDA | 에이전트 → fms-core | `…/factsheet` | 1 / 예 / — |
| 런 제어 | SPB | Host → sim-runner | `spBv1.0/santa/NCMD/sim-runner-gpu01` | 0 / — / — |
| 텔레메트리 | SPB | sim-runner · fms-core → Host | `…/NDATA/{edge}` · `…/DDATA/sim-runner-gpu01/{serial}` | 0 / — / — |
| 세션 | SPB | Edge, Host | `…/NBIRTH · NDEATH · DBIRTH · DDEATH`, `spBv1.0/STATE/host-orch` | NDEATH LWT QoS1 · STATE QoS1 retained |
| 주문 · 이벤트 | JSON | WMS → fms-core · fms-core → WMS · Host | `biz/v1/order` · `biz/v1/event` | 1 / — / — |

## 3. 계정 · ACL (원본 `infra/emqx/acl.conf`, 테스트 `tests/test_acl_matrix.py` 50항목 — 적용)

| 사용자명 | 역할 | publish (retained) | subscribe |
|---|---|---|---|
| `amr01…amrNN` (`^amr[0-9]+$`) | 에이전트 | `uagv/v2/+/{self}/connection · factsheet` (허용) · `state · visualization` (금지) | `uagv/v2/+/{self}/order · instantActions` |
| `fms-core` | VDA 마스터 + SPB Edge | `uagv/v2/+/+/order · instantActions` · `biz/v1/event` · `spBv1.0/santa/{NBIRTH,NDEATH,NDATA}/fms-core` (전부 금지) | `uagv/v2/+/+/{state,connection,factsheet}` · `spBv1.0/STATE/+` · `spBv1.0/santa/NCMD/fms-core` · `biz/v1/order` |
| `sim-runner-gpu01` | SPB Edge + state 거울 | `spBv1.0/santa/{NBIRTH,NDEATH,NDATA}/sim-runner-gpu01` · `{DBIRTH,DDEATH,DDATA}/sim-runner-gpu01/+` (전부 금지) | `spBv1.0/santa/NCMD/sim-runner-gpu01` · `DCMD/sim-runner-gpu01/+` · `spBv1.0/STATE/+` · `uagv/v2/+/+/{state,connection}` |
| `host-orch` | Primary Host | `spBv1.0/STATE/host-orch` (허용) · `spBv1.0/santa/NCMD/+` · `DCMD/+/+` (금지) | `spBv1.0/#` · `biz/v1/#` · `uagv/v2/+/+/#` |
| `sim-wms` | 시뮬 WMS | `biz/v1/order` (금지) | `biz/v1/event` |
| 그 외 · 익명 | — | 거부 | 거부 |

거부 = 브로커가 연결을 끊는다(`deny_action = disconnect`, 구독 위반 포함). 위 표에 없는 조합은 전부 거부.

## 4. VDA 5050 2.0.0 (`uagv/v2`)

### 4.1 메시지 · 필수 필드

공통 헤더: `headerId`(발행마다 +1) · `timestamp`(ISO 8601 UTC) · `version` `"2.0.0"` · `manufacturer` · `serialNumber`. 형식 검증은 VDA 공식 JSON 스키마(`tests/test_vda_schema.py`, 예정).

| 메시지 | 방향 | 필수 필드 (헤더 외) |
|---|---|---|
| `order` | FMS → AMR | `orderId` · `orderUpdateId`(≥ 0) · `nodes[]`(nodeId, sequenceId 짝수, released, nodePosition{x,y,theta,mapId,allowedDeviationXY/Theta}) · `edges[]`(edgeId, sequenceId 홀수, released, startNodeId, endNodeId, orientation·orientationType·length 선택) |
| `instantActions` | FMS → AMR | `actions[]`(actionType, actionId, blockingType) — 1차: `cancelOrder` |
| `state` | AMR → FMS | `orderId` · `orderUpdateId` · `lastNodeId` · `lastNodeSequenceId` · `nodeStates[]` · `edgeStates[]` · `driving` · `paused` · `actionStates[]` · `batteryState` · `operatingMode` · `errors[]` · `safetyState` · `agvPosition`(x,y,theta,mapId,positionInitialized) |
| `connection` | AMR → FMS | `connectionState` ∈ ONLINE · OFFLINE · CONNECTIONBROKEN (retained QoS1, LWT) |
| `factsheet` | AMR → FMS | `typeSpecification` · `physicalParameters` · `protocolLimits` · `protocolFeatures` · `agvGeometry` · `loadSpecification` (retained QoS1, ONLINE 직후) |

### 4.2 factsheet ← 기종 프로파일 (적용 2026-09-08: `t4_agent/config/models/iw_hub.yaml` → `StateBuilder.factsheet()`, ONLINE 직후 retained QoS1. 숫자의 원천은 `2_Simulation/sil_isaac/robot/profile.py`)

| 프로파일 (yaml 키) | factsheet 필드 | iw.hub |
|---|---|---|
| 기종 · 구동 · 등급 · 적재 | `typeSpecification.seriesName · agvKinematic · agvClass · maxLoadMass` | iw.hub · DIFF · CARRIER · 카탈로그 값 |
| 속도 · 가감속 | `physicalParameters.speedMax · speedMin · accelerationMax · decelerationMax` | 1.2 · 0.05 · 1.0 · 1.0 (에이전트 파라미터와 같은 출처) |
| 치수 | `physicalParameters.length · width · heightMin · heightMax` | 1.43 · 0.66 · 0.41 (축 기준 앞 0.40 · 뒤 1.03) |
| 바퀴 · 회전 외곽 | `agvGeometry.wheelDefinitions[] · envelopes2d[]` | r 0.08 · y ±0.29 · 스윙 반경 1.09 m |
| 타이밍 | `protocolLimits.timing.{minOrderInterval, minStateInterval, defaultStateInterval}` | 0.5 · 0.5 · 0.5 (executor 2 Hz sim time) |

### 4.3 orderUpdateId 스티칭 · 재발행 · 중복 (2_Simulation/t4_agent README 의 표를 옮김)

| PIBT 액션 | VDA 5050 표현 | 에이전트 동작 |
|---|---|---|
| 전진 1칸 | 다음 노드 released, 엣지 orientation 없음 | 헤딩 정렬(필요 시 스팟턴) → 직진 → 셀 중심 정지 |
| 후진 1칸 | 엣지 `orientation = π`, `orientationType TANGENTIAL` | 헤딩 유지, v < 0 |
| 회전 ±90° | 같은 좌표의 노드 + 새 `theta` (길이 0 엣지) | 제자리 회전 |
| 대기 | 새 노드 없음 | 정지 유지 |
| 틱 완료 ack | `state.lastNodeId` = 방금 released 된 노드 (변화 즉시 발행) | FMS 는 전 로봇 ack 후 다음 틱 |

- 1 틱 = orderUpdateId 를 1 올리며 노드 하나를 더 released 로 보내는 order 업데이트. 업데이트는 마지막 base 노드에서 시작(스티칭), 새 orderId 는 base 가 끝난 뒤에만.
- 중복: 같은 orderId · **같은** orderUpdateId 는 오류 없이 무시(state 만 재발행), **낮은** orderUpdateId 는 `orderUpdateError` (적용 2026-09-08: `OrderBook.receive` → 'duplicate' / `OrderUpdateError`, fake_fms `--repeat-last` 로 확인).
- 재발행(결정 10): fms-core 는 로봇별 outbox 를 두고 state 도착 횟수로 센다 — 2건 미반영 → 같은 order 재발행, 10건 → 로봇 오류, ONLINE 복귀 시 1회, 30 s 무소식 → broken (예정).
- 정지 허용치: 노드의 `allowedDeviationXY / Theta` (기본 0.05 m · 0.03 rad).

### 4.4 biz/v1 JSON (WMS ↔ fms-core, QoS1, 비-retained)

| 토픽 | 필수 필드 |
|---|---|
| `biz/v1/order` | `orderId` · `runId` · `createdAt` · `type` ∈ inbound · outbound · `lines[{sku, qty, fromStation, toStation}]` · `priority` |
| `biz/v1/event` | `eventId` · `runId` · `at` · `type` ∈ task_assigned · task_done · order_shipped · robot_error · stall · `orderId` · `taskId` · `robot{manufacturer, serial}` |

## 5. Sparkplug B 3.0 (`spBv1.0`, protobuf) — sim-runner 적용 2026-09-08 (`2_Simulation/sim_runner/`) · host-orch 적용 2026-09-09 (`3_FMS/host_orch/`, 잡 큐는 `SIM_VERIFY_CONTRACT.md`) · fms-core 예정

### 5.1 아이덴티티

| | 값 |
|---|---|
| group_id | `santa` |
| edge_node_id | `sim-runner-gpu01` (GPU 서버 상시 데몬) · `fms-core` (런 단위 Job) |
| device_id | VDA serialNumber `amr01…` (sim-runner 의 디바이스) |
| host_id | `host-orch` — `spBv1.0/STATE/host-orch` `{"online": true|false, "timestamp": ms}` QoS1 retained, Will = offline |

### 5.2 메트릭 사전 (NBIRTH · DBIRTH 에 전부 초기값과 함께)

| 메트릭 | 타입 | 뜻 |
|---|---|---|
| **Edge sim-runner-gpu01** | | |
| `bdSeq` · `Node Control/Rebirth` | Int64 · Boolean | 규격 필수 |
| `Runner/State` · `Runner/RunId` | String | IDLE · STARTING · RUNNING · STOPPING · ERROR / 현재 런 ID |
| `Runner/Heartbeat` | Int64 ms | 5 s 주기 |
| `Runner/RTF` · `IsaacInstances` · `RamMB` · `VramMB` | Double · Int32 | 5 s 샘플, 변화 시 |
| `Runner/LastError` | String | ERROR 이유 |
| `Runner/ScenarioSha` | String | 받은 scenario 의 sha256 (정규형). 런 없으면 `""`. Host 가 요청의 sha 와 대조 |
| `Run Control/Start` · `Run Control/Stop` | Text(JSON) · Boolean | NCMD 용. NBIRTH 에 `""` · `false` 로 선언 |
| **Device amr01… (state 거울)** | | |
| `Robot/Model` · `Robot/Connection` · `Robot/LastNodeId` | String | factsheet seriesName / ONLINE · OFFLINE · CONNECTIONBROKEN / 틱 ack |
| `Robot/PoseX` · `PoseY` · `Yaw` · `Battery` | Double | 변화 시 (0.05 m · 0.05 rad · 1 %) |
| `Robot/AmclErr` | Double | 선택. DBIRTH 에 `is_null = true` 로 선언 |
| **Edge fms-core** | | |
| `bdSeq` · `Node Control/Rebirth` · `Fms/RunId` · `Fms/Tick` · `Fms/RobotsOnline` · `Fms/OpenTasks` · `Fms/DoneTasks` | | 값만. 이벤트는 `biz/v1/event` |

### 5.3 NCMD

| 메트릭 | 값 | sim-runner 동작 |
|---|---|---|
| `Run Control/Start` | JSON `{run_id, scenario_pkg, n_robots, models[{serial, manufacturer, model}], ros_domain_id, timeout_s, scenario?, scenario_sha256?}` (scenario 는 SIM_VERIFY_CONTRACT §2, 512 KB 이하) | Isaac + 에이전트 기동 → ready(전원 ONLINE + 포즈 수신) → DBIRTH ×N → RUNNING (실패 ERROR + LastError). 멱등: 같은 run_id 가 이미 RUNNING 이면 무시하고 상태만 재보고 (RabbitMQ 재전달 대비) |
| `Run Control/Stop` | true | 에이전트 SIGTERM(OFFLINE) → DDEATH ×N → Isaac 종료 → IDLE |
| `Node Control/Rebirth` | true | NBIRTH + 살아 있는 DBIRTH 재발행 |

### 5.4 세션 규칙

- Will = NDEATH(bdSeq) QoS1 → 접속 후 NBIRTH(bdSeq, seq 0, 전 메트릭). 재접속마다 bdSeq +1. seq 0~255 순환, 갭이면 Host 가 Rebirth NCMD.
- Host STATE online 갱신을 보면 Edge 는 NBIRTH · DBIRTH 재발행. Host 는 NDEATH(bdSeq 일치)의 노드를 offline, 그 디바이스 전부 stale.
- 하트비트 5 s, 3회 결측 = 런 실패 → Stop. timeout_s 경과 · Host STATE offline 15 s · 런 프로세스 사망 → sim-runner 스스로 정지하고 `Runner/State` ERROR + `LastError`(사유). ERROR 는 IDLE 처럼 다음 Start 를 받고, Start 가 `LastError` 를 비운다.
- Stop 순서(적용): DDEATH ×N 즉시 → 에이전트 SIGINT(브리지가 OFFLINE 발행) → 5 s 뒤 SIGTERM → 3 s 뒤 SIGKILL → Isaac 같은 사다리(유예 20 s) → IDLE. bdSeq 는 `~/.local/state/sim_runner/bdseq` 에 보존.
- Host(적용): `spBv1.0/santa/#` 구독. seq 갭 · BIRTH 없는 노드 → Rebirth NCMD (노드당 5 s 에 1회). NDEATH 는 bdSeq 가 마지막 NBIRTH 와 같을 때만 offline(디바이스 stale), 아니면 stale death 로 무시. NDATA 가 15 s 없으면(하트비트 3회) 런 실패로 Stop. STATE 의 timestamp 는 접속마다 새로 — Edge 는 증가를 보고 BIRTH 재발행.
- Start 의 `models[]` 가 비면 `amr01…` 순번 시리얼 · manufacturer `idealworks` · model `iw_hub`. sim-runner 는 factsheet 를 못 보므로(ACL) `Robot/Model` 은 이 목록에서 온다. 같은 run_id 는 무시하고 상태만 재보고, 다른 run_id 는 `LastError` "busy" 로 거절(상태 불변).

## 6. 변경 절차

이 문서를 먼저 고치고 버전을 올린 뒤 호출자 전원(2_Simulation T4 · sim-runner, 3_FMS fms-core · host-orch, 4_Web WMS · k3s)에 공지한다.
토픽·QoS·retained·계정·메트릭 이름·NCMD·재발행 규칙이 바뀌면 minor, 필드 추가만이면 patch. `acl.conf` 변경은 `tests/test_acl_matrix.py` 행렬을 같이 고친다.
