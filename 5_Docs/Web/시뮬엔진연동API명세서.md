# 시뮬 엔진 연동 API 명세서

**버전** v0.6 · **대상** 웹 백엔드 / 시뮬 엔진(B트랙) 파트 · **갱신일** 2026-09-14

> v0.6 (호환, 추가만): 요청 `export_replay` · 결과 `replay` 추가 — §1-2 "리플레이".
> 견적 run 의 주행 궤적을 화면에서 재생하기 위한 것이고, 보내지 않으면 동작이 그대로다 (S15P21A106-205).

> v0.5 (호환, -191): 워커 기본값 — 요청에 `shifts` 가 없으면 **`out`(출고 전용)**. 워커 시뮬 상한 `SIM_TIMEOUT_S` 600 → 1,200 s.
> 백엔드가 `shifts` 를 보내면 그 값이 그대로 쓰인다(백엔드 기본도 `out`, -214; 팀 결정 2026-09-11 견적 부하 = 출고만).

> v0.4: `amr.capacity` 단위를 왕복당 **토트 수(1~6)**로 확정하고 `amr.tote_units`를 추가했다.
> 백엔드 기본 로봇은 `capacity: 6`, `tote_units: 8`을 권장한다. **-218 부터 백엔드가 `capacity: 6` 을 실제로 보낸다**(설정 `estimate.amr-capacity`) —
> 비우면 시뮬 기본 1 로 돌아 처리율이 3~4배 비관적으로 나왔다. `tote_units` 는 워커 기본 8 을 그대로 쓴다. 결과 판정에는 주문 `lead_time_p90_s` 상한이 필요하다.

> v0.3 (호환, 추가만): 요청에 **실행 조건 4개**(`horizon_s`·`shifts`·`inbound_gap_s`·`outbound_gap_s`) 추가 — §1-1.
> 고정 시간 실행을 요청에 명시해 "유한 주문 모드로 돌면 견적이 틀린다"는 가정을 계약에 남겼다.
> §3 프론트 ↔ 백엔드 API는 **`POST/GET/DELETE /api/estimates` 구현 완료** (S15P21A106-82). 남은 것은 시뮬 엔진 워커.
>
> v0.2: 백엔드 ↔ 시뮬 엔진 구간을 HTTP + 콜백에서 **RabbitMQ 큐**로 변경. 시뮬 요청·응답 DTO 필드는 그대로.

---

## 0. 전체 흐름

```
프론트                 백엔드                     RabbitMQ                시뮬 엔진 워커
  │                      │                          │                        │
  │ POST /api/simulations│                          │                        │
  │─────────────────────▶│  run_id 생성              │                        │
  │                      │  sim.request 큐에 발행    │                        │
  │                      │─────────────────────────▶│                        │
  │ 202 { run_id,        │                          │   큐에서 1건 꺼냄        │
  │       status:queued }│                          │◀───────────────────────│
  │◀─────────────────────│                          │                        │
  │                      │                          │        (수 분 계산)      │
  │ GET (폴링 또는 SSE)   │                          │                        │
  │─────────────────────▶│                          │   sim.result 큐에 발행   │
  │                      │                          │◀───────────────────────│
  │                      │  sim.result 구독, KPI 저장 │                        │
  │                      │◀─────────────────────────│                        │
  │◀─────────────────────│                          │                        │
```

- **견적(estimate)** 1건 = AMR 대수를 바꿔가며 돌리는 **run 여러 개**
- `run_id` 는 백엔드가 만든다. 형식 `{base_run_id}_n{amrCount}` (예: base `est_77` → `est_77_n3`, `est_77_n5`). 백엔드는 AMR 대수 목록만큼 `run_id` 와 `amr.count` 만 바꿔 1건씩 발행한다
- run 하나 = 요청 메시지 1건 = 결과 메시지 1건. 시뮬 엔진은 `run_id` 를 그대로 에코한다.

---

## 1. 메시지 큐 계약 (백엔드 ↔ 시뮬 엔진)

| 항목 | 값 |
|---|---|
| 브로커 | RabbitMQ (`4_Web/docker-compose.yml` 의 `rabbitmq` 서비스, 컨테이너 `a106-rabbitmq`) |
| 접속 | `amqp://${RABBITMQ_USER}:${RABBITMQ_PASSWORD}@rabbitmq:5672/` (compose 내부), 로컬은 `localhost:5672` |
| 관리 UI | `http://localhost:15672` |
| 익스체인지 | 기본 익스체인지(이름 없음). 라우팅 키 = 큐 이름 |
| 요청 큐 | `sim.request` (durable). 백엔드가 발행, 시뮬 엔진이 소비 |
| 결과 큐 | `sim.result` (durable). 시뮬 엔진이 발행, 백엔드가 소비 |
| 큐 선언 | 백엔드가 기동 시 두 큐를 선언한다. 시뮬 엔진은 선언 없이 소비·발행만 해도 된다 |
| 본문 | JSON (`content_type: application/json`), 필드는 `snake_case` |

### 1-1. 요청 메시지 (`sim.request`)

```json
{
  "run_id": "est_77_n3",
  "seed": 42,

  "horizon_s": 21600,
  "shifts": "out",
  "inbound_gap_s": 48.0,
  "outbound_gap_s": 22.5,

  "warehouse": {
    "worker_count": 4,
    "inbound_start": "01:00",  "inbound_end": "09:00",
    "outbound_start": "13:00", "outbound_end": "18:00",
    "inbound_avg": 480, "outbound_avg": 500
  },

  "amr": {
    "count": 3,
    "speed_empty": 1.2,
    "speed_loaded": 1.0,
    "consumption": 0.02,
    "battery": 100.0,
    "charge_time": 3600,
    "charge_threshold": 0.2,
    "capacity": 6,
    "tote_units": 8
  },

  "inbound": [
    {
      "inbound_id": 5001,
      "arrived_at_s": 3,
      "lines": [
        { "product_id": 7, "rack_id": "A2", "qty": 20 }
      ]
    }
  ],

  "outbound": [
    {
      "order_id": 1001,
      "ordered_at_s": 0,
      "lines": [
        { "product_id": 7,  "rack_id": "A2", "qty": 1 },
        { "product_id": 11, "rack_id": "A9", "qty": 3 }
      ]
    }
  ]
}
```

**`outbound[]` (2026-09-14)** — 백엔드 생성기가 만든 하루치 출고 주문 목록(-197/-212). **필수**다 — 비어 있으면 워커가
`failed` 로 돌려준다. `ordered_at_s` 는 `horizon_s` 시작 기준 상대 초. 주문 하나의 토트 합(같은 `rack_id` 수량을 합쳐
`ceil(합 / tote_units)` 을 랙별로 더한 값)은 **24 이하**로 백엔드가 보장한다(-214) — 시뮬 `--max-order-totes 24` 가
주문을 빼는 일이 없어 저장된 목록과 시뮬이 돈 목록이 같다. 한 줄 `qty` 는 **10 이하**(개인 온라인몰 1회 구매 기준,
백엔드 설정 `estimate.max-line-qty`, -146) — 참조 통계표의 도매 꼬리(다스·케이스 봉우리)는 추첨 대상에서 뺀다.

**실행 조건 필드 (2026-09-07 추가)**

| 필드 | 의미 | 값의 출처 |
|---|---|---|
| `horizon_s` | **고정 시간 실행** 길이(초). 워커는 이 값을 `--horizon`으로 넘겨야 한다 | 백엔드 설정 `estimate.horizon` (기본 6h) |
| `shifts` | 입고/출고 교대 토큰열. `--shifts`로 그대로 전달. 전체 시간을 토큰 수로 등분한다. **없으면 워커가 `out`(출고 전용)** (v0.5) | 백엔드 설정 `estimate.shifts` (기본 `out`, -214 — 출고는 `outbound[]` 시각을 따르므로 토큰은 입고 생성 구간만 정한다) |
| `inbound_gap_s` | 입고 도착 간격(초) 평균 → `--inbound-gap` | 창고 `inbound_avg` ÷ 입고 작업창 |
| `outbound_gap_s` | 출고 도착 간격(초) 평균 → `--order-gap` | 창고 `outbound_avg` ÷ 출고 작업창 |

**AMR 적재 필드 (2026-09-09 변경)**

| 필드 | 의미 | 워커 매핑 |
|---|---|---|
| `amr.capacity` | 왕복당 함께 싣는 토트 수(1~6) | `--capacity`; 로봇 시드의 기존 200은 6으로 변경 요청 |
| `amr.tote_units` | 토트 하나에 담는 상품 수 | `--tote-units`; 누락 시 워커 기본 8 |
| 서비스 시간 | 요청 필드 없음 | 픽업·하역 각각 토트당 5초 → `--svc-per-tote=round(5 / dt)` (dt = 틱 길이, 아래) |

**AMR 속도 필드 (2026-09-13, S15P21A106-116 — 백엔드 합의 필요)**

| 필드 | 의미 | 워커 매핑 |
|---|---|---|
| `amr.avg_payload_kg` | 사용자가 입력한 **평균 적재 무게(kg)**. 없으면(null) 속도 0.9 m/s 고정(물리 시뮬 계획 속도) | `contracts/speed_model.speed_for_load` → `--speed` |
| `amr.speed_empty` · `amr.speed_loaded` | 기종 공차·적재 운영 속도(m/s) — 감속 직선의 양 끝 | 위 함수의 앵커. `avg_payload_kg` 가 있을 때만 쓴다 |
| `amr.max_payload_kg` | 기종 최대 적재(kg) | 위 함수의 앵커. 셋 중 하나라도 null 이면 0.9 고정 + 워커 로그 |

속도는 run 내내 하나로 고정된다(토트 수와 무관). 틱 길이 dt = 1 m ÷ speed 이고, `horizon_s`·gap·서비스 초는 워커가 dt 로 틱으로 바꾼다.
물리 검증 요청 `scenario.amr` 에도 같은 `speed` 값이 실려야 두 KPI 가 같은 시계를 쓴다(`SIM_VERIFY_CONTRACT.md`).

> ⚠️ **`horizon_s`를 무시하면 견적이 틀린 답을 낸다.** 유한 주문 모드(주문을 다 처리하고 종료)로 돌면
> `orders_completed == orders_total`이라 처리율이 전 대수 100 %가 되고, 그러면 가동률이 가장 높은 최소
> 대수 — 즉 "1대 권장" — 이 뽑힌다. 백엔드는 전 대수 처리율 100 %를 감지하면 권장 대수 대신
> `LOAD_TOO_LOW` 사유를 반환하지만, 그 상태로는 견적이 나오지 않는다.

> **간격은 실제 도착률이다.** 시간(6h)만 줄이고 간격은 실제 운영값(입고 600건/8h → 48초)을 유지해
> 부하 밀도를 보존한다. 건수를 줄여 간격을 늘리면 부하가 낮아져 필요 대수를 과소 추정한다
> (백엔드↔AI API 계약 검토 §0-1 "밀도 대표성 주의").

### 1-2. 결과 메시지 (`sim.result`) — 기존 응답 DTO 그대로

```json
{
  "run_id": "est_77_n3",
  "status": "done",
  "error": null,

  "kpi": {
    "orders_total": 50,
    "orders_completed": 50,
    "inbound_total": 48,
    "inbound_completed": 48,

    "makespan_s": 1740,
    "lead_time_mean_s": 210.5,
    "lead_time_p90_s": 402.0,
    "queue_time_mean_s": 87.3,

    "throughput_orders_per_h": 96.4,
    "throughput_tasks_per_h": 182.0,

    "amr_utilization": 0.63,
    "conflict_wait_ratio": 0.004,
    "distance_total_m": 12480,
    "charge_downtime_s": 0
  }
}
```

`status` 가 `failed` 면 `error` 에 사유 문자열, `kpi` 는 `null`. 실패도 결과 큐에 정상 발행한다.

#### 리플레이 (v0.6, 선택 · S15P21A106-205)

요청에 `"export_replay": true` 가 있으면 결과에 `replay` 가 붙는다. 없으면 지금과 똑같이 동작한다 — §1-3 "모르는 필드는 무시한다"와 짝이라 옛 백엔드·옛 워커가 섞여 있어도 깨지지 않는다.

```json
{
  "run_id": "est_77_n3", "status": "done", "error": null,
  "kpi": { "…": "…" },
  "replay": {
    "dt_s": 4.444,
    "model": "heading",
    "seconds": 21600.0,
    "stride": 4,
    "robots":   { "0": [[0.0, 103.1, 48.5], "…"] },
    "headings": { "0": [1.5708, "…"] },
    "scene":    { "meta": {}, "obstacles": {}, "zones": {}, "stations": {}, "grid": [] }
  }
}
```

| 키 | 뜻 |
|---|---|
| `dt_s` | **샘플 간격**(초) = 원본 틱 × `stride`. 화면이 이 값으로 재생한다 |
| `model` | 좌표 모델. `heading` 이면 위치가 앞축 기준 |
| `seconds` | 담긴 길이(초). run 전체다 |
| `stride` | 몇 틱마다 한 점을 남겼는지 |
| `robots` | 로봇별 `[t, x, y]` 궤적 (m, z-up) |
| `headings` | 로봇별 틱당 yaw [rad] |
| `scene` | 맵·장애물·존·스테이션. 격자 좌표 규약은 `3_FMS/sim_engine/cli/export_isaac.py` |

- **run 전체를 담되 솎아낸다.** 워커 `REPLAY_STRIDE`(기본 4)가 간격을 정한다. 원본 그대로면 run 하나가 2.7 MB(4대)·19 MB(28대)라 큐와 DB 에 담을 것이 못 된다. 4 로 솎으면 run 당 0.67 MB(4대) 다.
- **솎아도 화면에서 차이가 안 난다.** 6시간을 ×32 로 재생하므로 한 프레임이 시뮬 0.5 초인데, 원본 간격(1.1 초)도 이미 프레임보다 성기다. 사이는 화면이 보간한다.
- **앞부분만 잘라서는 안 된다.** 견적은 입고 교대로 시작하고 주문도 초반에는 드물어서, 앞 600초를 담았더니 4대 중 3대가 240초 동안 충전존에 서 있기만 했다(실측). 그래서 전체를 담는다.
- **짧게 돌려서 얻는 것도 아니다.** `--shifts` 가 `horizon` 을 등분하므로 horizon 을 줄이면 앞부분이 아니라 다른 시나리오가 된다(실측: 앞 1200틱 중 296틱만 일치, 114틱째부터 갈라짐).
- **내보내기 비용은 run 당 약 +35 %** (실측 17.0 → 22.9초, 5대·43200틱). 그래서 요청에 있을 때만 켠다.
- `replay` 가 `null` 일 수 있다 — 산출물이 없거나 읽다 실패한 경우. 리플레이는 곁다리라 그것 때문에 run 을 `failed` 로 만들지 않는다.
- `scene` 은 맵이라 같은 견적의 run 끼리 같다. 백엔드는 견적당 한 벌만 보관하면 된다.

### 1-3. 시뮬 엔진 워커 규칙

- **ack 는 결과 발행 후.** 꺼낸 즉시 ack 하면 계산 중 워커가 죽을 때 run 이 사라진다.
- **prefetch 1.** 시뮬 1회가 60~90초라 미리 여러 건 가져가면 다른 워커가 놀게 된다.
- **같은 `run_id` 가 두 번 올 수 있다** (재전달). 시뮬은 결정론이라 결과가 같으니 그대로 다시 돌려도 된다. 중복 처리는 백엔드가 한다.
- 모르는 필드는 무시한다.

### 1-4. 백엔드 규칙

- 발행 실패(브로커 연결 불가) 시 프론트에 `503 SIM503` 반환.
- 같은 `run_id` 결과가 두 번 오면 두 번째는 무시한다.
- `RUNNING` 상태로 **30분** 을 넘긴 run 은 `TIMEOUT` 처리한다 (워커가 전부 죽어 있을 때 대비).

### 1-5. 추후 항목 (지금은 미구현)

- **배치 발행 + 조기 종료 (제안, S15P21A106-182).** 워커가 여러 개 병렬로 도니(EC2 4코어 기준 2개) 백엔드가 대수를 워커 수만큼 배치로 발행하고, 한 배치 결과가 모이면 판정해 더 개선이 없으면 남은 대수를 발행하지 않는다. 설계·근거는 `3_FMS/docs/견적_워커.md` "병렬 처리와 조기 종료". 큐 메시지 형식은 바뀌지 않는다.

- dead-letter 큐 (`sim.request.dlq`) 와 재전달 상한
- 결과 메시지 중복 수신 방지의 영구 저장(DB) 기반 구현
- RabbitMQ 데이터 볼륨 (배포 전 추가)

---

## 3. 프론트 → 백엔드 (초안, 미구현)

Base URL: `/api`

### 3-1. 견적(estimate)

| 메서드 | URL | 용도 | 성공 응답 |
|---|---|---|---|
| POST | `/estimates` | 견적 요청 생성. 창고 조건 + AMR 사양 + 대수 범위를 받아 run 을 만들고 시뮬 엔진에 전부 요청 | `202 Accepted` |
| GET | `/estimates` | 견적 목록 (최근순, 페이지네이션) | `200 OK` |
| GET | `/estimates/{estimateId}` | 견적 상태 + run 별 결과표(대수·가동률·처리량·비용) | `200 OK` |
| DELETE | `/estimates/{estimateId}` | 견적 취소. 이미 큐에 들어간 run 은 결과가 와도 무시 | `204 No Content` |

### 3-2. run (견적 하위)

| 메서드 | URL | 용도 | 성공 응답 |
|---|---|---|---|
| GET | `/estimates/{estimateId}/runs` | run 목록 (run_id, amr_count, status) | `200 OK` |
| GET | `/estimates/{estimateId}/runs/{runId}` | run 하나의 KPI 전체 (1-2 의 `kpi` 그대로) | `200 OK` |
| POST | `/estimates/{estimateId}/runs/{runId}/retry` | 실패·타임아웃 run 재실행 | `202 Accepted` |

### 3-3. 진행 알림

| 메서드 | URL | 용도 |
|---|---|---|
| GET | `/estimates/{estimateId}/events` | SSE. run 완료마다 이벤트 1건, 전체 완료 시 `estimate.done` 후 종료 |

SSE 대신 `GET /estimates/{estimateId}` 폴링(5초 간격)으로 시작해도 된다. 프론트 요구에 따라 결정.

### 3-4. 상태값

**run 상태**

| 값 | 의미 | 전이 |
|---|---|---|
| `QUEUED` | 요청 큐에 발행됨 | → RUNNING / FAILED |
| `RUNNING` | 워커가 꺼내서 계산 중 (현재는 QUEUED 와 구분 없이 처리) | → DONE / FAILED / TIMEOUT |
| `DONE` | 결과 메시지 `status: done` 수신 | 종료 |
| `FAILED` | 결과 메시지 `status: failed` 수신, 또는 발행 실패 | → QUEUED (retry) |
| `TIMEOUT` | 30분 내 결과 없음 | → QUEUED (retry) |

**견적 상태**

| 값 | 의미 |
|---|---|
| `RUNNING` | 미완료 run 이 하나 이상 |
| `DONE` | 모든 run `DONE` |
| `PARTIAL` | 일부 run 이 `FAILED`/`TIMEOUT`. 나머지 결과는 조회 가능 |
| `CANCELLED` | 사용자 취소 |

---

## 4. 네이밍 규칙

| 항목 | 규칙 |
|---|---|
| URL | 소문자, 복수형 명사, 단어 구분은 `-` |
| 백엔드 ↔ 시뮬 엔진 메시지 필드 | `snake_case` (시뮬 엔진이 Python 이므로 DTO 기준 유지) |
| 백엔드 ↔ 프론트 JSON 필드 | `camelCase` (`ApiResponse` 규칙과 통일) |
| 프리픽스 | 백엔드 API 는 `/api` 프리픽스, 버전 없음. 시뮬 엔진는 프리픽스 없음 |
| 식별자 | 견적은 숫자 `estimateId`, run 은 문자열 `run_id` (`est_{estimateId}_n{amrCount}`) |

---

## 5. 환경 변수

| 변수 | 사용처 | 예시 |
|---|---|---|
| `RABBITMQ_USER` / `RABBITMQ_PASSWORD` | RabbitMQ 컨테이너, 백엔드, 시뮬 엔진 워커 공통 | `4_Web/.env` |
| `RABBITMQ_HOST` | 백엔드 (compose 는 `rabbitmq` 고정, 로컬은 `localhost`) | |
| `sim.request-queue` / `sim.result-queue` | 백엔드 `application.yml` | `sim.request` / `sim.result` |
