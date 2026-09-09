# host_orch — Sparkplug Primary Host `host-orch` + `sim.verify` 소비자

EC2 에 상시로 떠서 (1) `spBv1.0/STATE/host-orch` 로 자기 생사를 알리고 sim-runner 의 BIRTH/DATA/DEATH 를 추적하며,
(2) RabbitMQ `sim.verify.request` 를 하나씩 꺼내 NCMD Start → 창(window_s) → Stop 으로 GPU 검증 런을 굴리고 `sim.verify.result` 를 낸다.
규칙의 원본: [`../contracts/MQTT_CONTRACT.md`](../contracts/MQTT_CONTRACT.md) §5 (Host 쪽), [`../contracts/SIM_VERIFY_CONTRACT.md`](../contracts/SIM_VERIFY_CONTRACT.md).
짝: [`2_Simulation/sim_runner/`](../../2_Simulation/sim_runner/) (GPU 쪽 Edge).

| 파일 | 역할 |
|---|---|
| `tracker.py` | Primary Host 상태 — 노드·디바이스 메트릭, 별칭, seq 검사 → needs_rebirth, NDEATH(bdSeq 일치) → offline |
| `orchestrator.py` | `VerifyRequest` 검증, `Job` 상태기계 STARTING → RUNNING → STOPPING → DONE\|FAILED, 결과 JSON, `Coordinator`(잡 1개 + Rebirth 발송) |
| `amqp.py` | pika 소비 루프 — prefetch 1, 잡이 끝날 때까지 0.5 s tick, 결과 발행 뒤 ack. `publish_request` · `drain` 은 테스트용 |
| `mqtt_host.py` | paho — STATE online retained + 유언 offline, `spBv1.0/santa/#` 구독, NCMD 발행 |
| `app.py` | 배선 + CLI (`python3 -m host_orch`). `--once` 는 AMQP 없이 요청 1건 |
| `spb.py` · `sparkplug_b_pb2.py` | `2_Simulation/sim_runner/` 와 **바이트 동일 복사본** (`tests/test_spb_copy.py` 가 지킨다). 바꾸면 둘 다 |
| `tests/` | 브로커 없는 단위 테스트 57개 |

## 실행

```bash
cd 3_FMS
# 환경: MQTT_HOST · MQTT_PORT · MQTT_PW_HOST_ORCH (infra/emqx/.env) + RABBITMQ_URL 또는 RABBITMQ_HOST/USER/PASSWORD (infra/.env)
python3 -m host_orch --env-file infra/emqx/.env --env-file infra/.env -v                # 상주
python3 -m host_orch --env-file infra/emqx/.env --once request.json                    # AMQP 없이 1건 → 결과 JSON
python3 -m pytest host_orch/tests -q

# 요청 투입 · 결과 회수 (개발용)
python3 -c "from host_orch.amqp import publish_request, amqp_url; publish_request(amqp_url(), 'sim.verify.request', {'run_id': 'v1', 'n_robots': 2, 'window_s': 60})"
python3 -c "from host_orch.amqp import drain, amqp_url; print(drain(amqp_url(), 'sim.verify.result'))"
```

GPU 박스에서 개발할 때 RabbitMQ 는 EC2 에서 127.0.0.1 바인딩이라 `ssh -N -L 5672:127.0.0.1:5672 ubuntu@100.100.149.68` 터널로 붙는다 (`infra/.env` 의 RABBITMQ_HOST=127.0.0.1).
EC2 에서 돌릴 때는 `pip install pika paho-mqtt protobuf` (infra/requirements.txt) 후 같은 명령. k3s 매니페스트는 10 단계.

옵션: `--node sim-runner-gpu01`(NCMD 대상) · `--start-timeout-s 180` · `--stop-timeout-s 60` · `--request-queue/--result-queue` · `--group santa` · `--host-id host-orch`.

## 검증

2026-09-09, GPU 박스에서: EC2 RabbitMQ 는 ssh 터널, EC2 EMQX 는 tailnet, sim-runner 는 `--mode fake` 로봇 2. host-orch 는 이 박스에서 상주 실행.

| 단계 | 결과 |
|---|---|
| 기동 | STATE online retained → sim-runner NBIRTH 추적(IDLE, bdSeq 0) → `sim.verify.request` 소비 시작 |
| 요청 `window_s=30, n_robots=2` | NCMD Start 즉시 → RUNNING 1.1 s 뒤 → 창 30 s → NCMD Stop → IDLE → 결과 `done` 총 33 s. `robots_online 2 · rtf_mean 1.0 · ram_mb_max 520 · vram_mb_max 22 · reason "window elapsed"`, `source_run_id · estimate_id` 그대로 회신 |
| 깨진 요청 (`n_robots: "two"`) | 즉시 `failed`, `error: "bad request: n_robots must be an integer in 1..64"`, ack |
| RUNNING 중 sim-runner kill -9 | NDEATH(bdSeq 일치) 수신 → `failed`, `error "sim-runner went offline during the run"`, `reason "runner NDEATH"`, 4 s |
| DES 큐 | `sim.request/result` 와 소비자(견적 워커) 무관 — 건드리지 않음 |

단위 테스트 57개 (`host_orch/tests`), 브로커 불필요. 리뷰 반영 뒤 E2E 재실행 10:25 동일 결과.

## 남은 것

- `kpi` · `artifacts` 는 null — fms-core 가 `biz/v1/event` 로 내는 KPI 집계, 리플레이·영상 키 (fms-core 연동 뒤)
- fms-core Job · sim-wms 파드 기동 (k8s) — 결정 4 의 "런의 절반" 은 fms-core 가 생기면
- 러너가 여러 대면 NBIRTH `Runner/State` 가 IDLE 인 노드를 골라 보내고 prefetch 를 러너 수로 (지금은 `--node` 하나)
- `biz/v1/#` · `uagv/v2/+/+/#` 관측 구독은 ACL 에 있지만 아직 안 쓴다
