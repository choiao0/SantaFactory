# sim.verify 큐 계약 — Isaac 검증 런 (v0.3-draft, 2026-09-10)

견적 BE ↔ host-orch 가 RabbitMQ 로 주고받는 것. DES 큐 계약([`5_Docs/Web/시뮬엔진연동API명세서.md`](../../5_Docs/Web/시뮬엔진연동API명세서.md) §1)과
같은 브로커·같은 규칙(durable · JSON snake_case · 결과 발행 뒤 ack · prefetch 1)이고, 큐 이름만 다르다.
근거: [`MQTT_CONTRACT.md`](MQTT_CONTRACT.md) §1 결정 4 · 11 · 14, §5.3. 구현: [`../host_orch/`](../host_orch/) (큐·런 오케스트레이션), [`../fms_core/`](../fms_core/) (로봇 주행 · KPI). **웹 팀 합의 전 초안** — 이 문서가 그 §1-6 초안이다.

> v0.2 (2026-09-09, 추가만): §2 `scenario.window_start_s`, §3 `kpi` 는 fms-core 가 채운다 + `verify.fms`, §4 fms-core 행, §6 ⑤ 해소.
> v0.3 (2026-09-10, S15P21A106-185): §2 적재 필드를 [`SIM_RUN_CONTRACT.md`](SIM_RUN_CONTRACT.md) v2.6 에 맞춘다 —
> `scenario.amr.capacity`(최상위 `scenario.capacity` 도 받는다)는 **왕복당 토트 수(1~6)**, 토트당 상품 수는
> `scenario.amr.tote_units`(기본 8). 옛 뜻(상품 수)으로 보내면 거절된다. §3 `verify.fms.warnings` 추가 —
> null 이 아니면 그 런은 견적과 다른 조건에서 돌았다는 뜻이라 KPI 를 견적과 비교하면 안 된다.
> 견적과 같은 조건으로 도는지는 `fms_core/tests/test_des_parity.py` 가 견적 워커 코드에서 기준을 읽어 대조한다.

## 1. 큐

| 항목 | 값 |
|---|---|
| 요청 큐 | `sim.verify.request` (durable). BE 가 발행, host-orch 가 유일 소비자 (prefetch 1 = GPU 러너 1대 직렬) |
| 결과 큐 | `sim.verify.result` (durable). host-orch 가 발행, BE 가 소비 |
| 선언 | host-orch 가 기동 시 둘 다 선언한다(멱등). BE 도 선언해도 된다 |
| 언제 | BE 가 DES 결과(`sim.result`) 중 최적 1건을 고른 뒤. DES 워커는 이 큐를 모른다 |
| ack | 결과 발행 뒤. 창(window_s)이 RabbitMQ `consumer_timeout`(기본 30 분) 안에 끝나야 한다 — 20 분 초과 창은 큐 정책으로 timeout 을 늘린다 (미결 ②) |

## 2. 요청 (`sim.verify.request`)

```json
{
  "run_id": "verify_77_n3",            // 필수. [A-Za-z0-9][A-Za-z0-9_.-]{0,63}. sim-runner Run Control/Start 의 run_id 로 그대로 간다
  "n_robots": 3,                        // 필수. 1..64
  "scenario_pkg": "wallA_v6",           // 맵·시나리오 식별자. sim-runner 는 지금 기록만 한다
  "window_s": 600,                      // Isaac 검증 창(초). 기본 600. 창이 끝나면 host-orch 가 Stop 을 보낸다
  "timeout_s": 900,                     // 선택. sim-runner 쪽 백스톱. 기본 window_s + 300
  "models": [{"serial": "amr01", "manufacturer": "idealworks", "model": "iw_hub"}],   // 선택. 비면 amr01… iw_hub
  "ros_domain_id": 0,                   // 선택
  "source_run_id": "est_77_n3",         // DES run_id (추적용, 결과에 그대로 돌려준다)
  "estimate_id": 77,                    // 견적 id (추적용, 결과에 그대로)
  "seed": 42,                           // 선택. fms-core · WMS 연동 뒤 사용
  "priority": 0,                        // 선택. x-max-priority 는 미구현
  "scenario": {                         // 선택. 런 입력 묶음 — 정규형 JSON 512 KB 이하 (MQTT 패킷 1 MB 아래)
    "seed": 42, "map_version": "v6.0",
    "orders": { "meta": {…}, "outbound": [ {"order_id": 1, "ordered_at_s": 23659, "store_id": 1,
                                            "lines": [{"product_id": 3, "qty": 2, "rack_id": "A3"}]} ] },   // 주문 생성기 산출물 그대로 (DES 워커가 쓴 것)
    "spawn": "103.1,48.5;103.1,50.5",   // 선택. 로봇 초기 위치(m) → Isaac WSIM_SPAWN. DES 와 같은 배치는 `python3 -m fms_core --spawn N` 이 준다
    "window_start_s": 5400,             // 선택. 주문 시각을 이만큼 앞당겨 재생(창 오프셋, §6 ①). 음수가 되는 주문은 버린다
    "amr": {"capacity": 3, "tote_units": 8, "speed_empty": 1.2, …},   // 선택. DES 요청 amr 블록 pass-through: capacity = 왕복당 토트 수 1~6, tote_units = 토트당 상품 수(기본 8). sim-runner 가 이 블록을 에이전트 `profile_overrides` 로 그대로 넘겨 속도·배터리·적재가 로봇 동작에 반영된다 (1_Robot/amr_agent README "파라미터")
    "outbound_gap_s": 50.0, "inbound_gap_s": 48.0, "shifts": "in,out,out"   // 선택. 없으면 **출고 전용** — 검증 런은 견적 지평선 안의 출고 창 한 조각만 재생한다 (§6 ①)
  }
}
```

`scenario` 는 host-orch 가 정규형(키 정렬·공백 없음)으로 sha256 을 계산해 NCMD Start 에 `scenario_sha256` 과 함께 싣고, sim-runner 는 같은 규칙으로
다시 계산해 다르면 런을 거부한다. sim-runner 는 `<state>/runs/<run_id>/scenario.json` 에 떨어뜨리고 Isaac·에이전트에 `SIM_SCENARIO_PATH`·`SIM_SCENARIO_SHA256` 환경변수로 알린다.
주문 500건 산출물 ≈ 66 KB. 이 안에 못 들어가는 입력(영상·리플레이)은 아티팩트 키로.

DES 요청의 `horizon_s · shifts · inbound_gap_s · outbound_gap_s · warehouse · amr · inbound · outbound` 는 fms-core/WMS 연동 뒤 이 메시지에
그대로 실린다(pass-through). host-orch 는 모르는 필드를 버리지 않고 `raw` 로 보관만 한다.

## 3. 결과 (`sim.verify.result`)

```json
{
  "run_id": "verify_77_n3",
  "status": "done",                     // done | failed
  "error": null,                        // failed 면 사유 문자열
  "verify": {
    "runner": "sim-runner-gpu01",
    "n_robots": 3, "robots_online": 3,  // DBIRTH 로 본 최대 동시 로봇 수
    "window_s": 600, "elapsed_s": 600.4,
    "started_at": "2026-09-09T02:10:00.000Z", "ended_at": "2026-09-09T02:20:00.400Z",
    "rtf_mean": 1.02, "ram_mb_max": 5120, "vram_mb_max": 9800, "isaac_instances": 1,
    "scenario_sha256": "…64hex…", "scenario_ack": true,   // sim-runner 가 NDATA `Runner/ScenarioSha` 로 같은 sha 를 되돌렸는가 = 데이터 도달 증명
    "reason": "window elapsed",         // window elapsed | heartbeat lost | runner ended the run | runner NDEATH | start timeout | stop timeout | fms-core ended the run | fms-core NDEATH | fms-core heartbeat lost | fms-core rejected Start | fms stop timeout
    "fms": { "node": "fms-core", "ticks": 118, "status": "done", "error": null, "planner": "kernel",
             "counters": {"open_tasks": 3, "done_tasks": 11, "orders_done": 9, "orders_total": 12},
             "warnings": null }   // host-orch 가 --fms-node 없이 돌면 null. warnings 가 null 이 아니면 이 런은 견적과 다른 조건에서 돌았다(예: θ 파일 없음 → 중립 θ) → KPI 를 견적과 비교하지 말 것
  },
  "kpi": { "orders_total": 12, "orders_completed": 9, "inbound_total": 0, "inbound_completed": 0, "makespan_s": 118,
           "lead_time_mean_s": 61.2, "lead_time_p90_s": 90.0, "queue_time_mean_s": 3.1, "throughput_orders_per_h": 274.6,
           "throughput_tasks_per_h": 335.6, "amr_utilization": 0.71, "conflict_wait_ratio": 0.02, "distance_total_m": 140,
           "charge_downtime_s": 0 },       // fms-core 의 kpi_summary(MQTT_CONTRACT §4.4) — DES 견적 워커 to_kpi 와 같은 14개 키. 분모(makespan_s) = 실제로 돈 커널 틱 수. fms-core 가 없거나 플래너 전에 끝났으면 null
  "artifacts": null,                    // 뒤에 {video, replay, heatmap} 키
  "source_run_id": "est_77_n3", "estimate_id": 77
}
```

요청 자체가 깨졌으면(`bad request: …`) `run_id` 를 읽을 수 있는 만큼 채워 `failed` 로 발행하고 ack 한다 (DES 명세 §1-2 와 같이 실패도 정상 발행).

## 4. host-orch 가 지키는 것

| 상황 | 동작 |
|---|---|
| 요청 수신 | sim-runner 가 NBIRTH 로 보이고 IDLE/ERROR 면 NCMD Start. 다른 run_id 로 바쁘면 기다렸다가 start_timeout(180 s) 에 failed |
| sim-runner RUNNING (fms-core 켜짐, `--fms-node`) | 같은 Start 를 fms-core 에 NCMD (15 s 마다 재전송). `Fms/State` RUNNING · `Fms/RunId` 일치일 때 창 시작(결정 11). fms-core ERROR/IDLE · `bad Start` · start_timeout → failed |
| RUNNING 중 fms-core NDEATH · ERROR/IDLE · NDATA 15 s 없음 | Stop 둘 다 → failed (`fms-core NDEATH` · `fms-core ended the run` · `fms-core heartbeat lost`) |
| Start 반영 없음 | 15 s 마다 재전송 (sim-runner 는 같은 run_id 멱등, QoS 0 유실 대비) |
| RUNNING · RunId 일치 | 창 시작. `Runner/RTF · RamMB · VramMB · IsaacInstances · ScenarioSha`, DBIRTH 수를 모은다 |
| 창 종료 | NCMD Stop(둘 다) → sim-runner IDLE 확인 + fms-core 가 run_id 를 놓음(IDLE/ERROR) → `done`. `biz/v1/event` kpi_summary(runId 일치)의 `kpi` 를 결과에 싣는다. Stop 무응답 60 s → 재전송 1회 → failed "stop timeout" / fms-core 60 s → "fms stop timeout" |
| sim-runner 가 먼저 접음 (ERROR · RunId 비움) | failed, `error` = `Runner/LastError` |
| NDEATH (bdSeq 일치) | failed "runner NDEATH" |
| NDATA 15 s 없음 (하트비트 3회 결측) | Stop 보내고 failed "heartbeat lost" |
| seq 갭 · BIRTH 없는 노드 | NCMD Rebirth (노드당 5 s 에 1회) |
| 자기 생사 | `spBv1.0/STATE/host-orch` `{"online", "timestamp"}` retained QoS1, 유언 offline. 재접속마다 timestamp 갱신 → sim-runner 가 BIRTH 재발행 |

## 5. BE 쪽 (제안, 미구현)

- 견적 상태에 `VERIFYING` 추가 (미결 ③). `sim.verify.result` 의 `status` 로 `VERIFIED` / `VERIFY_FAILED`.
- 재시도: `failed` + `reason` 이 `start timeout` · `runner NDEATH` · `heartbeat lost` 면 재발행 가능(같은 run_id 는 sim-runner 가 멱등 처리). `runner ended the run` 은 원인(`error`) 확인 후.

## 6. 미결 (로드맵 §04)

① 창 길이 — DES 6 h 대비 Isaac 10~20 분 창, 같은 창의 DES KPI 와 비교하는 정의. 지금은 요청의 `window_s` 로 열어 둔다. 실측(2026-09-09, 명세 예시 조건 seed 42): DES 창의 첫 10 분에는 주문 2건, 10~20 분에 124건(wave) — "첫 W 분" 은 쓸 수 없고 `scenario.window_start_s` 로 안정 구간을 잘라야 한다(제안: 출고 시작 + 90 분, 600 s). 실 로봇 1 칸 ≈ 2.2 s · 90° ≈ 2.5 s 라 커널 틱(1 s)보다 느리다 — `verify.fms.ticks` 가 그 창에서 돈 DES 초이고 KPI 분모다.
② 20 분 초과 창과 `consumer_timeout` — 큐 정책(`consumer_timeout`)을 늘릴지, 꺼내자마자 ack 하고 BE 의 TIMEOUT 재시도로 갈지.
③ `VERIFYING` 상태값. ④ 주문 스크립트 전달 — 워커가 `sim.result` 에 `orders` + `orders_sha256` 을 동봉(ⓐ, 제안) vs seed 재생성(ⓑ). ⑤ `kpi` 산출 주체 — **해소(2026-09-09)**: fms-core 가 DES 와 같은 산식(`fms_core/kpi.py` = `sim_engine/cli/report.py`)으로 계산해 `kpi_summary` 로 내고 host-orch 는 그대로 싣는다.
