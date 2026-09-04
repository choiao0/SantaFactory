# 시뮬 엔진 연동 API 명세서

**버전** v0.1 · **대상** 웹 백엔드 / 시뮬 엔진(B트랙) 파트 · **작성일** 2026-09-04

> 시뮬레이션 요청·응답 DTO는 기존 것을 그대로 쓴다.
> 원래 한 번의 요청/응답으로 처리하려던 것을 **요청(백엔드→시뮬 엔진)** 과 **결과 콜백(시뮬 엔진→백엔드)** 으로 분리했다.
> DTO 필드는 추가·수정·삭제하지 않았다.

---

## 0. 전체 흐름

```
프론트                 백엔드                          시뮬 엔진
  │                      │                               │
  │ POST /estimates      │                               │
  │─────────────────────▶│  견적 생성, AMR 대수별 run 생성  │
  │                      │                               │
  │                      │  POST /simulations  (run마다)  │
  │                      │──────────────────────────────▶│  ① 요청
  │                      │◀──────────────────────────────│     202 { run_id } 즉시 응답
  │ 202 { estimateId }   │                               │
  │◀─────────────────────│                               │
  │                      │                    (수 분 계산) │
  │ GET /estimates/{id}  │                               │
  │  (폴링 또는 SSE)      │                               │
  │─────────────────────▶│                               │
  │                      │  POST /api/sim/results        │
  │                      │◀──────────────────────────────│  ② 결과 콜백
  │                      │  run 상태 DONE, KPI 저장        │
  │                      │──────────────────────────────▶│     200
  │                      │                               │
  │ GET /estimates/{id}  │  모든 run 완료 → 견적 DONE       │
  │◀─────────────────────│                               │
```

- **견적(estimate)** 1건 = AMR 대수를 바꿔가며 돌리는 **run 여러 개**
- `run_id` 는 백엔드가 만든다. 형식 `est_{estimateId}_n{amrCount}` (예: `est_77_n3`)
- 시뮬 엔진 호출은 run 하나당 한 번. AI는 `run_id` 를 그대로 에코한다.

---

## 1. 백엔드 → 시뮬 엔진 (시뮬 엔진가 제공)

Base URL: `${SIM_BASE_URL}` (예: `http://sim:8000`)

| 메서드 | URL | 용도 | 성공 응답 |
|---|---|---|---|
| POST | `/simulations` | 시뮬레이션 실행 요청. 즉시 접수 응답만 반환 | `202 Accepted` |
| GET | `/simulations/{run_id}` | 상태 조회. 콜백 유실 시 백엔드가 보조로 사용 | `200 OK` |
| DELETE | `/simulations/{run_id}` | 실행 취소 (선택 구현) | `204 No Content` |

### 1-1. `POST /simulations` 요청 본문 — 기존 요청 DTO 그대로

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

### 1-2. `POST /simulations` 즉시 응답 (신규, 최소 필드)

```json
{
  "run_id": "est_77_n3",
  "status": "queued"
}
```

| 상태 코드 | 의미 |
|---|---|
| 202 | 접수됨. 결과는 콜백으로 전달 |
| 400 | 요청 본문 검증 실패 |
| 409 | 같은 `run_id` 가 이미 실행 중 |

### 1-3. `GET /simulations/{run_id}` 응답

콜백 본문(2-1)과 같은 형태. 아직 끝나지 않았으면 `status` 가 `queued` 또는 `running` 이고 `kpi` 는 `null`.

---

## 2. 시뮬 엔진 → 백엔드 콜백 (백엔드가 제공)

Base URL: `${BACKEND_BASE_URL}` (compose 내부: `http://backend:8080`)

| 메서드 | URL | 용도 | 성공 응답 |
|---|---|---|---|
| POST | `/api/sim/results` | 시뮬레이션 결과 전달 | `200 OK` |

### 2-1. 요청 본문 — 기존 응답 DTO 그대로

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

`status` 가 `failed` 면 `error` 에 사유 문자열, `kpi` 는 `null`.

### 2-2. 헤더

| 헤더 | 값 | 설명 |
|---|---|---|
| `Content-Type` | `application/json` | |
| `X-Sim-Callback-Token` | `${SIM_CALLBACK_TOKEN}` | 공유 시크릿. 불일치 시 401 |

### 2-3. 백엔드 응답

백엔드 공통 포맷 `ApiResponse` 로 내려간다.

| 상태 코드 | 코드 | 의미 |
|---|---|---|
| 200 | `COMMON200` | 정상 반영 |
| 200 | `COMMON200` | 이미 `DONE` 인 run 에 중복 콜백 → 무시하고 200 (멱등) |
| 401 | `SIM401` | 콜백 토큰 불일치 |
| 404 | `COMMON404` | 알 수 없는 `run_id` |

### 2-4. 재시도 규칙

- 백엔드가 5xx 를 주거나 연결 실패 시 시뮬 엔진은 **최대 3회, 10초 간격**으로 재시도한다.
- 백엔드는 run 이 `RUNNING` 상태로 **30분**을 넘기면 `GET /simulations/{run_id}` 로 상태를 확인하고, 그래도 미완료면 `TIMEOUT` 처리한다.

---

## 3. 프론트 → 백엔드 (백엔드가 제공)

Base URL: `/api`

### 3-1. 견적(estimate)

| 메서드 | URL | 용도 | 성공 응답 |
|---|---|---|---|
| POST | `/estimates` | 견적 요청 생성. 창고 조건 + AMR 사양 + 대수 범위를 받아 run 을 만들고 시뮬 엔진에 전부 요청 | `202 Accepted` |
| GET | `/estimates` | 견적 목록 (최근순, 페이지네이션) | `200 OK` |
| GET | `/estimates/{estimateId}` | 견적 상태 + run 별 결과표(대수·가동률·처리량·비용) | `200 OK` |
| DELETE | `/estimates/{estimateId}` | 견적 취소. 미완료 run 에 대해 시뮬 엔진으로 `DELETE /simulations/{run_id}` 전파 | `204 No Content` |

### 3-2. run (견적 하위)

| 메서드 | URL | 용도 | 성공 응답 |
|---|---|---|---|
| GET | `/estimates/{estimateId}/runs` | run 목록 (run_id, amr_count, status) | `200 OK` |
| GET | `/estimates/{estimateId}/runs/{runId}` | run 하나의 KPI 전체 (2-1 의 `kpi` 그대로) | `200 OK` |
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
| `QUEUED` | 시뮬 엔진에 요청 보냄, 접수 응답 받음 | → RUNNING / FAILED |
| `RUNNING` | 시뮬 엔진이 계산 중 | → DONE / FAILED / TIMEOUT |
| `DONE` | 콜백 `status: done` 수신 | 종료 |
| `FAILED` | 콜백 `status: failed` 수신, 또는 요청 자체 실패 | → QUEUED (retry) |
| `TIMEOUT` | 30분 내 콜백 없음 | → QUEUED (retry) |

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
| 백엔드 ↔ 시뮬 엔진 JSON 필드 | `snake_case` (시뮬 엔진이 Python 이므로 DTO 기준 유지) |
| 백엔드 ↔ 프론트 JSON 필드 | `camelCase` (`ApiResponse` 규칙과 통일) |
| 프리픽스 | 백엔드 API 는 `/api` 프리픽스, 버전 없음. 시뮬 엔진는 프리픽스 없음 |
| 식별자 | 견적은 숫자 `estimateId`, run 은 문자열 `run_id` (`est_{estimateId}_n{amrCount}`) |

---

## 5. 환경 변수

| 변수 | 사용처 | 예시 |
|---|---|---|
| `SIM_BASE_URL` | 백엔드 | `http://sim:8000` |
| `SIM_CALLBACK_TOKEN` | 백엔드·시뮬 엔진 공통 | 랜덤 문자열 |
| `BACKEND_BASE_URL` | 시뮬 엔진 | `http://backend:8080` |
