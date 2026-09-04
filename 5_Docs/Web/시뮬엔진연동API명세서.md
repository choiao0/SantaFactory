# 시뮬 엔진 연동 API 명세서

**버전** v0.2 · **대상** 웹 백엔드 / 시뮬 엔진(B트랙) 파트 · **갱신일** 2026-09-04

> v0.2: 백엔드 ↔ 시뮬 엔진 구간을 HTTP + 콜백에서 **RabbitMQ 큐**로 변경. 시뮬 요청·응답 DTO 필드는 그대로.
> 프론트 ↔ 백엔드 구간(§3)은 HTTP 유지.

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
- `run_id` 는 백엔드가 만든다. 형식 `est_{estimateId}_n{amrCount}` (예: `est_77_n3`)
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

### 1-1. 요청 메시지 (`sim.request`) — 기존 요청 DTO 그대로

```json
{
  "run_id": "est_77_n3",
  "seed": 42,

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
    "capacity": 8
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

- dead-letter 큐 (`sim.request.dlq`) 와 재전달 상한
- 결과 메시지 중복 수신 방지의 영구 저장(DB) 기반 구현
- RabbitMQ 데이터 볼륨 (배포 전 추가)

---

## 3. 프론트 → 백엔드 (백엔드가 제공)

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
