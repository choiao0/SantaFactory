# sim.verify 큐 계약 — Isaac 검증 런 (v0.1-draft, 2026-09-09)

견적 BE ↔ host-orch 가 RabbitMQ 로 주고받는 것. DES 큐 계약([`5_Docs/Web/시뮬엔진연동API명세서.md`](../../5_Docs/Web/시뮬엔진연동API명세서.md) §1)과
같은 브로커·같은 규칙(durable · JSON snake_case · 결과 발행 뒤 ack · prefetch 1)이고, 큐 이름만 다르다.
근거: [`MQTT_CONTRACT.md`](MQTT_CONTRACT.md) §1 결정 4 · 14, §5.3. 구현: [`../host_orch/`](../host_orch/). **웹 팀 합의 전 초안** — 이 문서가 그 §1-6 초안이다.

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
  "priority": 0                         // 선택. x-max-priority 는 미구현
}
```

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
    "rtf_mean": 1.02, "ram_mb_max": 5120, "vram_mb_max": 9800,
    "reason": "window elapsed"          // window elapsed | heartbeat lost | runner ended the run | runner NDEATH | start timeout | stop timeout
  },
  "kpi": null,                          // fms-core 연동 뒤 DES 와 같은 kpi 블록
  "artifacts": null,                    // 뒤에 {video, replay, heatmap} 키
  "source_run_id": "est_77_n3", "estimate_id": 77
}
```

요청 자체가 깨졌으면(`bad request: …`) `run_id` 를 읽을 수 있는 만큼 채워 `failed` 로 발행하고 ack 한다 (DES 명세 §1-2 와 같이 실패도 정상 발행).

## 4. host-orch 가 지키는 것

| 상황 | 동작 |
|---|---|
| 요청 수신 | sim-runner 가 NBIRTH 로 보이고 IDLE/ERROR 면 NCMD Start. 다른 run_id 로 바쁘면 기다렸다가 start_timeout(180 s) 에 failed |
| Start 반영 없음 | 15 s 마다 재전송 (sim-runner 는 같은 run_id 멱등, QoS 0 유실 대비) |
| RUNNING · RunId 일치 | 창 시작. `Runner/RTF · RamMB · VramMB`, DBIRTH 수를 모은다 |
| 창 종료 | NCMD Stop → sim-runner IDLE 확인 → `done`. Stop 무응답 60 s → 재전송 1회 → failed "stop timeout" |
| sim-runner 가 먼저 접음 (ERROR · RunId 비움) | failed, `error` = `Runner/LastError` |
| NDEATH (bdSeq 일치) | failed "runner NDEATH" |
| NDATA 15 s 없음 (하트비트 3회 결측) | Stop 보내고 failed "heartbeat lost" |
| seq 갭 · BIRTH 없는 노드 | NCMD Rebirth (노드당 5 s 에 1회) |
| 자기 생사 | `spBv1.0/STATE/host-orch` `{"online", "timestamp"}` retained QoS1, 유언 offline. 재접속마다 timestamp 갱신 → sim-runner 가 BIRTH 재발행 |

## 5. BE 쪽 (제안, 미구현)

- 견적 상태에 `VERIFYING` 추가 (미결 ③). `sim.verify.result` 의 `status` 로 `VERIFIED` / `VERIFY_FAILED`.
- 재시도: `failed` + `reason` 이 `start timeout` · `runner NDEATH` · `heartbeat lost` 면 재발행 가능(같은 run_id 는 sim-runner 가 멱등 처리). `runner ended the run` 은 원인(`error`) 확인 후.

## 6. 미결 (로드맵 §04)

① 창 길이 — DES 6 h 대비 Isaac 10~20 분 창, 같은 창의 DES KPI 와 비교하는 정의. 지금은 요청의 `window_s` 로 열어 둔다.
② 20 분 초과 창과 `consumer_timeout` — 큐 정책(`consumer_timeout`)을 늘릴지, 꺼내자마자 ack 하고 BE 의 TIMEOUT 재시도로 갈지.
③ `VERIFYING` 상태값. ④ `kpi` 산출 주체 — fms-core 가 `biz/v1/event` 로 낸 것을 host-orch 가 집계.
