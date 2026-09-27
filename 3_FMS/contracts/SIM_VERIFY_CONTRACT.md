# sim.verify 큐 계약 — Isaac 검증 런 (v0.5-draft, 2026-09-26)

견적 BE ↔ host-orch 가 RabbitMQ 로 주고받는 것. DES 큐 계약([`5_Docs/Web/시뮬엔진연동API명세서.md`](../../5_Docs/Web/시뮬엔진연동API명세서.md) §1)과
같은 브로커·같은 규칙(durable · JSON snake_case · 결과 발행 뒤 ack)이고, 큐 이름만 다르다. prefetch 는 러너 노드 수(§1 · §4).
근거: [`MQTT_CONTRACT.md`](MQTT_CONTRACT.md) §1 결정 4 · 11 · 14, §5.3. 구현: [`../host_orch/`](../host_orch/) (큐·런 오케스트레이션), [`../fms_core/`](../fms_core/) (로봇 주행 · KPI). **웹 팀 합의 전 초안** — 이 문서가 그 §1-6 초안이다.

> v0.2 (2026-09-09, 추가만): §2 `scenario.window_start_s`, §3 `kpi` 는 fms-core 가 채운다 + `verify.fms`, §4 fms-core 행, §6 ⑤ 해소.
> v0.3 (2026-09-10, S15P21A106-185): §2 적재 필드를 [`SIM_RUN_CONTRACT.md`](SIM_RUN_CONTRACT.md) v2.6 에 맞춘다 —
> `scenario.amr.capacity`(최상위 `scenario.capacity` 도 받는다)는 **왕복당 토트 수(1~6)**, 토트당 상품 수는
> `scenario.amr.tote_units`(기본 10, v3.9; v2.6~v3.8 은 8). 옛 뜻(상품 수)으로 보내면 거절된다. §3 `verify.fms.warnings` 추가 —
> null 이 아니면 그 런은 견적과 다른 조건에서 돌았다는 뜻이라 KPI 를 견적과 비교하면 안 된다.
> 견적과 같은 조건으로 도는지는 `fms_core/tests/test_des_parity.py` 가 견적 워커 코드에서 기준을 읽어 대조한다.
> v0.4 (2026-09-14, S15P21A106-197 반영): `scenario.orders` 의 원천은 **백엔드가 견적 생성 시 저장한 목록**(`estimates.outbound_orders_json`)이고
> DES 스윕 `outbound[]` 와 같은 목록이다. §6 ④ 해소. 3_FMS 의 Python 주문 생성기와 워커 자체 생성(-158)은 제거 — 주문 원천은 백엔드 하나.
> v0.5 (2026-09-26, S15P21A106-244 반영): §2 `scenario.trajectory_gz_b64` + `scenario.slice`(DES 피크 구간 인라인 재생, 있으면
> 주문 자르기 생략) 추가, 크기 상한 512 KiB → 900 KiB, `timeout_s` 는 BE 가 보내지 않고 host-orch 가 궤적/주문별로
> 기본값을 낸다(§2), `run_id` 형식에 `attempt` 추가. §3 `physics` 객체 추가(러너 `Runner/Physics` 를 파싱, 판정은 백엔드
> 한 곳 — D). §4 host-orch 가 노드를 **여러 개**(`sim-runner-gpu01..0N`) 들고 비어 있는 노드에 배정 — prefetch = 노드 수,
> `Runner/VideoUrl`·`Runner/Physics` 는 그 잡의 run_id 를 확인한 뒤에만 받는다(이전 런 값이 새는 버그 수정).

## 1. 큐

| 항목 | 값 |
|---|---|
| 요청 큐 | `sim.verify.request` (durable). BE 가 발행, host-orch 가 유일 소비자 (prefetch = 러너 노드 수 — GPU 1대에 컨테이너 N개, §4 동시성) |
| 결과 큐 | `sim.verify.result` (durable). host-orch 가 발행, BE 가 소비 |
| 선언 | host-orch 가 기동 시 둘 다 선언한다(멱등). BE 도 선언해도 된다 |
| 언제 | BE 가 DES 결과(`sim.result`) 중 최적 1건을 고른 뒤. DES 워커는 이 큐를 모른다 |
| ack | 결과 발행 뒤. 창(window_s)이 RabbitMQ `consumer_timeout`(기본 30 분) 안에 끝나야 한다 — 20 분 초과 창은 큐 정책으로 timeout 을 늘린다 (미결 ②) |

## 2. 요청 (`sim.verify.request`)

```json
{
  "run_id": "verify_77_n3_1",          // 필수. [A-Za-z0-9][A-Za-z0-9_.-]{0,63}, 형식 verify_<estimateId>_n<K>_<attempt>
                                        //   (attempt 는 그 (견적, 대수)의 요청 횟수, 1부터 — 같은 값 재요청은 §4 멱등, 다시 돌리려면 attempt 를 올린다)
  "n_robots": 3,                        // 필수. 1..64
  "scenario_pkg": "wallA_v6",           // 맵·시나리오 식별자. sim-runner 는 지금 기록만 한다
  "window_s": 600,                      // Isaac 검증 창(초) = verify_slice.window_s(워밍업 제외). 기본 600. host-orch 가 Runner/SimTime 으로 이만큼 지나면 Stop
  "models": [{"serial": "amr01", "manufacturer": "idealworks", "model": "iw_hub"}],   // 선택. 비면 amr01… iw_hub
  "ros_domain_id": 0,                   // 선택
  "source_run_id": "est_77_n3",         // DES run_id (추적용, 결과에 그대로 돌려준다)
  "estimate_id": 77,                    // 견적 id (추적용, 결과에 그대로)
  "seed": 42,                           // 선택. fms-core · WMS 연동 뒤 사용
  "priority": 0,                        // 선택. x-max-priority 는 미구현
  "scenario": {                         // 선택. 런 입력 묶음 — 정규형 JSON 900 KiB 이하 (MQTT 패킷 1 MB 아래, -244)
    "seed": 42, "map_version": "v6.0",
    "trajectory_gz_b64": "H4sI…",       // (S15P21A106-244·275) DES 피크 구간 궤적 — sim.result.verify_slice.gz_b64 그대로(gzip+base64).
                                        //   있으면 host-orch 는 주문을 자르지 않고 scenario 를 그대로(sha 도 그대로) 싣는다 — 디코드하지 않는다(형식 검사는 러너 몫)
    "slice": {"t0_s": 4420.0, "warmup_s": 60.0, "window_s": 600.0, "tasks_done": 162},  // 궤적일 때만. warmup_s 기본 60(없으면 이 기본값)
    "orders": { "meta": {…}, "outbound": [ {"order_id": 1, "ordered_at_s": 23659, "store_id": 1,
                                            "lines": [{"product_id": 3, "qty": 2, "rack_id": "A3"}]} ] },   // trajectory_gz_b64 가 없는 run(구 견적 등)의 폴백. 백엔드가 견적 생성 시 저장한 목록 그대로 (-197). 둘 다 싣지 않는다 — 둘 다 있으면 궤적이 이긴다
    "spawn": "108.1,57.5;108.1,66.5",   // 선택. 로봇 초기 위치(m) → Isaac WSIM_SPAWN. DES 와 같은 배치는 `python3 -m fms_core --spawn N` 이 준다
    "window_start_s": 5400,             // 선택. 주문 시각을 이만큼 앞당겨 재생(창 오프셋, §6 ①). 음수가 되는 주문은 버린다. orders 폴백에서만 뜻이 있다
    "amr": {"capacity": 3, "tote_units": 8, "speed_empty": 1.2, …},   // 선택. DES 요청 amr 블록 pass-through: capacity = 왕복당 토트 수 1~6, tote_units = 토트당 상품 수(기본 10 — 2026-09-15 개인 주문 상한 10개·토트 10개들이). sim-runner 가 이 블록을 에이전트 `profile_overrides` 로 그대로 넘겨 속도·배터리·적재가 로봇 동작에 반영된다 (1_Robot/amr_agent README "파라미터")
    "outbound_gap_s": 50.0, "inbound_gap_s": 48.0, "shifts": "in,out,out"   // 선택. 없으면 **출고 전용** — 검증 런은 견적 지평선 안의 출고 창 한 조각만 재생한다 (§6 ①)
  }
}
```

`timeout_s` 는 **BE 가 보내지 않는다** — host-orch 가 NCMD Start 에 실을 값을 스스로 낸다: 궤적 재생이면
`ceil((warmup_s + window_s) / 0.5) + 300`(위 예시로 1620 s — 배속 하한 0.5 로 계산한 벽시계 위에 시작/정지 여유),
주문(폴백) 이면 종전대로 `window_s + 300`. BE 가 명시로 보내면 그 값이 이긴다(레거시·실험용 구멍).

`scenario` 는 host-orch 가 정규형(키 정렬·공백 없음)으로 sha256 을 계산해 NCMD Start 에 `scenario_sha256` 과 함께 싣고, sim-runner 는 같은 규칙으로
다시 계산해 다르면 런을 거부한다(궤적이면 자르지 않은 그대로, 주문이면 창으로 자른 뒤의 scenario 로 낸다). sim-runner 는 `<state>/runs/<run_id>/scenario.json` 에 떨어뜨리고 Isaac·에이전트에 `SIM_SCENARIO_PATH`·`SIM_SCENARIO_SHA256` 환경변수로 알린다.
주문 500건 산출물 ≈ 66 KB, 궤적 10대 ≈ 300 KiB · 15대 ≈ 440 KiB(§4). 이 안에 못 들어가는 입력(영상·리플레이)은 아티팩트 키로.

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
  "artifacts": {                        // 시점별 mp4. video 는 상단 시점(기존 키 그대로), video_fpv 는 추가
    "video":      "verify_77_n3/demo_verify_77_n3.mp4",
    "video_fpv": "verify_77_n3/demo_verify_77_n3_fpv.mp4"
  },
                                        // (-215/-233) 러너가 Runner/VideoUrl 로 준 mp4 의 **객체 키** `<run_id>/<파일>` — URL 이 아니고 버킷 이름도 안 붙는다(버킷은 양쪽 설정).
                                        // 버킷은 비공개, 화면용 서명 URL 은 BE 가 조회 시 만든다(§7). 영상이 없으면 artifacts 는 null. replay·heatmap 키는 예정
  "physics": {                          // (S15P21A106-244·275) 러너 Runner/Physics(JSON 문자열)를 파싱한 객체. 없거나 깨졌으면 null(경고 로그만 남긴다)
    "engine": "isaac-headless", "n_robots": 10,
    "sim_s": 660.0, "window_sim_s": 600.0, "warmup_s": 60.0, "window_s": 600.0, "wall_s": 701.3, "rtf": 0.94,
    "robot_contacts": 0, "robot_min_gap_m": 0.334, "rack_contacts": 0, "rack_worst_pen_mm": 0.0,
    "zone_intrusions": 284, "zone_worst_pen_mm": 46.6,
    "stall_steps": 0, "turn_gaveup": 1, "recover_events": 0, "cell_overlaps": 62,
    "actions_started": 3140, "actions_completed": 3134,
    "lag": {"n": 2804, "p50_s": 40.4, "p90_s": 91.9, "max_s": 157.6, "mean_s": 47.0, "late_ratio": 0.9},          // 구간 재생이 아니면 null
    "window_actions": {"planned": 3365, "started": 2804, "ratio": 0.833, "overdue_s": 157.0},                     // 구간 재생이 아니면 null
    "blocked": {"robot_frames": 372000, "obstacle": 0, "release": 10406, "adg_self": 0, "adg_other": 89963, "ratio": 0.27},
    "des_window": {"tasks_done": 162, "moves": 2970, "turns": 191, "reverses": 205}                               // 구간 재생이 아니면 null
  },
  "source_run_id": "est_77_n3", "estimate_id": 77
}
```

물리 판정(PASS/WARN/FAIL/N/A)은 **백엔드 한 곳**에서 `physics` 필드로 계산한다(화면·견적서 공통) — host-orch 는 파싱만 하고
판정하지 않는다. 판정 규칙과 화면 문구는 상위 설계 문서(DES 피크 구간 → 물리 검증, spec244 §D)를 따른다: 대략
`robot_contacts == 0 && rack_contacts == 0 && window_actions.ratio ≥ 0.80` 이면 PASS, 접촉 0 이지만 ratio 미달이면
WARN(지연), 접촉 > 0 이면 FAIL, `status: failed`(검증을 끝내지 못함)이거나 `window_actions` 가 null(구간 재생이 아님)이면
N/A — 끝내지 못한 회차는 로봇이 부적합하다는 뜻이 아니라 판정하지 않는다(S15P21A106-280, 화면 · 견적서 「판정 불가」).

요청 자체가 깨졌으면(`bad request: …`) `run_id` 를 읽을 수 있는 만큼 채워 `failed` 로 발행하고 ack 한다 (DES 명세 §1-2 와 같이 실패도 정상 발행). 이때 `physics` 도 `null`.

## 4. host-orch 가 지키는 것

| 상황 | 동작 |
|---|---|
| 요청 수신 | 노드 목록(`sim-runner-gpu01..0N`, GPU 1대에 컨테이너 여러 개 — spec244 §E) 중 **온라인 · IDLE/ERROR · 활성 잡 없음 · 대기 중인 Rebirth 없음**인 노드 하나에 NCMD Start. 그런 노드가 없으면(전부 사용 중) Busy — AMQP 쪽이 메시지를 들고 있다가 다시 시도한다(짧게 보류한 뒤 requeue, `../host_orch/amqp.py`). 진행 중인 잡은 노드마다 하나(prefetch = 노드 수) |
| 같은 run_id 재요청 | 진행 중이면 그 잡(재전달 멱등, Start 한 번), `done` 으로 끝났으면 결과만 재발행(GPU 런 반복 안 함), **`failed` 로 끝났으면 새 런**(-241). BE 는 run_id 를 견적 id 로 고정한 채 재발행하면 된다 — 실패한 견적의 재검증이 옛 실패 결과로 되돌아오던 문제 (2026-09-17) |
| 요청 파싱 실패 | 결과 `failed` 를 바로 발행. `estimate_id` · `source_run_id` 는 본문에서 그대로 옮긴다 — BE 가 어느 견적의 실패인지 알아 화면에 알릴 수 있게 (-235, 2026-09-16 verify_2 가 이것 없이 버려져 화면이 굳었다) |
| `scenario.trajectory_gz_b64` 있음 | **주문을 자르지 않는다** — 궤적에 이미 배정 결과가 있다. scenario 를 받은 그대로(디코드하지 않고) 900 KiB 상한만 재고 sha 를 낸다(-244) |
| `scenario.orders.outbound` (궤적 없을 때 폴백) | **창 밖 주문은 러너에 보내지 않는다.** 창 = [t0, t0 + window_s + 60], t0 = `window_start_s`(있으면) 아니면 첫 주문 시각(§6 ① 의 저장 주문 기준). 잘라낸 scenario 에 `window_start_s = t0` 와 `orders.window {start_s, end_s, kept, total}` 를 적고 sha 도 그 기준으로 낸다. 900 KiB 상한(-244, 옛 512 KiB)은 자른 뒤에 잰다 — 하루 6,000 건(586 KB)을 통째로 보내던 요청이 거절되던 문제 (-235) |
| sim-runner RUNNING (fms-core 켜짐, `--fms-node`) | 같은 Start 를 fms-core 에 NCMD (15 s 마다 재전송). `Fms/State` RUNNING · `Fms/RunId` 일치일 때 창 시작(결정 11). fms-core ERROR/IDLE · `bad Start` · start_timeout → failed. **노드가 여럿이면 첫 노드(목록의 첫 항목)의 잡에만 묶는다** — fms-core 는 브로커에 하나뿐이라 두 런을 동시에 못 돈다. 나머지 노드의 잡은 fms-core 없이 돈다(`kpi` null) |
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
- 재시도: `failed` + `reason` 이 `start timeout` · `runner NDEATH` · `heartbeat lost` 면 재발행 가능(같은 run_id 는 sim-runner 가 멱등 처리). `runner ended the run` 은 원인(`error`) 확인 후. host-orch 는 `failed` 였던 run_id 의 재요청을 새 런으로 돌린다(-241, §4) — `done` 이었던 run_id 는 결과만 다시 온다.

## 6. 미결 (로드맵 §04)

① 창 길이 — DES 6 h 대비 Isaac 10~20 분 창, 같은 창의 DES KPI 와 비교하는 정의. 지금은 요청의 `window_s` 로 열어 둔다. 실측(2026-09-09, 명세 예시 조건 seed 42): DES 창의 첫 10 분에는 주문 2건, 10~20 분에 124건(wave) — "첫 W 분" 은 쓸 수 없고 `scenario.window_start_s` 로 안정 구간을 잘라야 한다(제안: 출고 시작 + 90 분, 600 s). 실 로봇 1 칸 ≈ 2.2 s · 90° ≈ 2.5 s 라 커널 틱(1 s)보다 느리다 — `verify.fms.ticks` 가 그 창에서 돈 DES 초이고 KPI 분모다.
② 20 분 초과 창과 `consumer_timeout` — 큐 정책(`consumer_timeout`)을 늘릴지, 꺼내자마자 ack 하고 BE 의 TIMEOUT 재시도로 갈지.
③ `VERIFYING` 상태값. ④ 주문 스크립트 전달 — **해소(2026-09-14, -197)**: 백엔드 `OutboundOrderGenerator` 가 견적 생성 시 1회 만들어 저장하고 DES 요청 `outbound[]` 와 여기 `scenario.orders` 에 같은 목록을 싣는다. 워커 자체 생성(-158)·3_FMS `order_gen` 은 제거. 남은 제안: 워커가 `sim.result` 에 `orders_sha256` 에코(저장본 대조). ⑤ `kpi` 산출 주체 — **해소(2026-09-09)**: fms-core 가 DES 와 같은 산식(`fms_core/kpi.py` = `sim_engine/cli/report.py`)으로 계산해 `kpi_summary` 로 내고 host-orch 는 그대로 싣는다.


## 7. `artifacts.video` 를 화면 URL 로 (백엔드, -233)

러너가 주는 값은 URL 이 아니라 **객체 키** `<run_id>/<파일>` 이다 — 버킷 이름은 안 붙는다(버킷 `verify-videos` 는 양쪽 설정 `MINIO_BUCKET`). 버킷은 비공개라 키만으로는 아무도 못 연다.
백엔드는 `estimates.verify_video_url` 에 키를 그대로 저장하고, 견적 조회·검증 SSE 에서 **그때그때** 짧은 만료의 presigned GET 을 만들어
`video_url` 로 준다. 화면(`<video src>`)은 무변경. 견적 번호만 바꿔 남의 영상을 여는 일은 API 의 소유권 검사가 막는다.
구현: 4_Web `VerifyVideoPresigner`(-89, 2026-09-16 develop) — `objectKey()` 가 URL 이 아닌 값을 통째로 키로 보고, 215 시절 공개 URL 형식은 `/verify-videos/` 뒤를 키로 뽑아 재서명한다. TTL 30 분, 만료 뒤 구간 이동 403 은 FE 가 상세를 다시 불러 새 URL 로 이어 간다.

| 항목 | 값 |
|---|---|
| 계정 | `santa-be` — 읽기 전용(정책 `santa-be-read`: `verify-videos/*` GetObject + GetBucketLocation). 비밀은 EC2 `~/minio-keys/santa-be.env`, 환경변수로 주입, git 밖 |
| 서명 엔드포인트 | `https://j15a106.p.ssafy.io` (secure), region `us-east-1`, 경로 `/verify-videos/<키>` |
| 브라우저에 주는 URL | 서명한 뒤 경로 **앞에 `/media` 를 끼운다** → `https://j15a106.p.ssafy.io/media/verify-videos/<키>?X-Amz-…` |
| 만료 | 짧게(예 10 분). 조회마다 새로 만든다 — DB 에는 키만 둔다 |

왜 `/media` 를 서명 뒤에 끼우나: nginx 가 `location /media/ { proxy_pass http://127.0.0.1:9002/; proxy_set_header Host $host; }` 라
`/media` 를 떼고 Host 는 그대로 넘긴다. SigV4 는 Host 와 경로를 서명하므로 MinIO 가 실제로 보는 조합(`j15a106.p.ssafy.io` + `/verify-videos/…`)으로
서명해야 맞는다. 내부 주소(`http://minio:9000`)나 `/media` 를 포함한 경로로 서명하면 브라우저 요청에서 403 이다.
서명은 네트워크 없이 계산된다 — minio-java 는 `MinioClient.builder().endpoint("https://j15a106.p.ssafy.io").region("us-east-1").credentials(…)` 뒤
`getPresignedObjectUrl(GetPresignedObjectUrlArgs … method(GET).bucket("verify-videos").object(키).expiry(10, MINUTES))`. region 을 명시하면
GetBucketLocation 호출도 없어 BE 컨테이너가 MinIO 에 닿을 필요가 없다.

실측 2026-09-16(minio-py 로 같은 절차): 서명 URL(`/media` 삽입) → **200**, video/mp4 2.5 MB · 서명 없이 → **403** · `/media` 없이 → FE 의 index.html(200, text/html — MinIO 가 아니다).
