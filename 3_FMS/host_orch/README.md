# host_orch — Sparkplug Primary Host `host-orch` + `sim.verify` 소비자

EC2 에 상시로 떠서 (1) `spBv1.0/STATE/host-orch` 로 자기 생사를 알리고 sim-runner 의 BIRTH/DATA/DEATH 를 추적하며,
(2) RabbitMQ `sim.verify.request` 를 하나씩 꺼내 NCMD Start → 창(window_s) → Stop 으로 GPU 검증 런을 굴리고 `sim.verify.result` 를 낸다.
`--fms-node fms-core` 면 같은 Start/Stop 을 [`../fms_core/`](../fms_core/) 에도 보내고, 둘 다 RUNNING 일 때 창을 열며, fms-core 의 `kpi_summary` 를 결과 `kpi` 에 싣는다(결정 11).
규칙의 원본: [`../contracts/MQTT_CONTRACT.md`](../contracts/MQTT_CONTRACT.md) §5 (Host 쪽), [`../contracts/SIM_VERIFY_CONTRACT.md`](../contracts/SIM_VERIFY_CONTRACT.md).
짝: GPU 쪽 Edge — [`2_Simulation/t3_amr/`](../../2_Simulation/t3_amr/) 에 붙인다(구 `sim_runner` 는 -219, 2026-09-15 로 삭제; 아래 실측 기록은 그 시절 것).

| 파일 | 역할 |
|---|---|
| `tracker.py` | Primary Host 상태 — 노드·디바이스 메트릭, 별칭, seq 검사 → needs_rebirth, NDEATH(bdSeq 일치) → offline |
| `orchestrator.py` | `VerifyRequest` 검증(`scenario` sha256 포함), `Job` 상태기계 STARTING → RUNNING → STOPPING → DONE\|FAILED, `FmsLink`(fms-core Start 재전송 · RUNNING 게이트 · 정지 확인 · kpi_summary), 결과 JSON(`scenario_ack` · `kpi` · `verify.fms`), `Coordinator`(잡 1개 + Rebirth 발송, 재전달 멱등, `biz/v1/event` 라우팅) |
| `amqp.py` | pika 소비 루프 — prefetch 1, 잡이 끝날 때까지 0.5 s tick, 결과 발행 뒤 ack. `publish_request` · `drain` 은 테스트용 |
| `mqtt_host.py` | paho — STATE online retained + 유언 offline, `spBv1.0/santa/#` + `biz/v1/#` 구독, NCMD 발행 |
| `app.py` | 배선 + CLI (`python3 -m host_orch`). `--once` 는 AMQP 없이 요청 1건 |
| `spb.py` · `sparkplug_b_pb2.py` | Sparkplug 코덱 **참조 구현** — `../fms_core/` 사본과 바이트 동일 (`tests/test_spb_copy.py` 가 지킨다). 바꾸면 둘 다 |
| `tests/` | 브로커 없는 단위 테스트 77개 |

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
EC2 배포(compose, k3s 전까지): `infra/host_orch.Dockerfile` + `infra/compose.host-orch.yml`. RabbitMQ 네트워크(santafactory_default)와 EMQX 네트워크(backbone_default)에
같이 들어가 서비스 이름으로 붙는다. 자격증명은 `infra/.env`(RABBITMQ_USER/PASSWORD) + `infra/emqx/.env`(MQTT_PW_HOST_ORCH), 둘 다 gitignored.

```bash
# EC2 에 트리 복사 (host_orch/ + infra/{host_orch.Dockerfile,compose.host-orch.yml,.env,emqx/.env}) 뒤
cd ~/host-orch/3_FMS/infra && docker compose -f compose.host-orch.yml up -d --build && docker compose -f compose.host-orch.yml logs -f
```

옵션: `--node sim-runner-gpu01`(NCMD 대상) · `--fms-node fms-core`(기본 `$HOST_ORCH_FMS_NODE`, 비면 sim-runner 만) · `--start-timeout-s 180` · `--stop-timeout-s 60` · `--request-queue/--result-queue` · `--group santa` · `--host-id host-orch`.

## 검증

2026-09-09, GPU 박스에서: EC2 RabbitMQ 는 ssh 터널, EC2 EMQX 는 tailnet, sim-runner 는 `--mode fake` 로봇 2. host-orch 는 이 박스에서 상주 실행.

| 단계 | 결과 |
|---|---|
| 기동 | STATE online retained → sim-runner NBIRTH 추적(IDLE, bdSeq 0) → `sim.verify.request` 소비 시작 |
| 요청 `window_s=30, n_robots=2` | NCMD Start 즉시 → RUNNING 1.1 s 뒤 → 창 30 s → NCMD Stop → IDLE → 결과 `done` 총 33 s. `robots_online 2 · rtf_mean 1.0 · ram_mb_max 520 · vram_mb_max 22 · reason "window elapsed"`, `source_run_id · estimate_id` 그대로 회신 |
| 깨진 요청 (`n_robots: "two"`) | 즉시 `failed`, `error: "bad request: n_robots must be an integer in 1..64"`, ack |
| RUNNING 중 sim-runner kill -9 | NDEATH(bdSeq 일치) 수신 → `failed`, `error "sim-runner went offline during the run"`, `reason "runner NDEATH"`, 4 s |
| DES 큐 | `sim.request/result` 와 소비자(견적 워커) 무관 — 건드리지 않음 |

단위 테스트 62개 (`host_orch/tests`), 브로커 불필요. 리뷰 반영 뒤 E2E 재실행 10:25 동일 결과.

**EC2 배포 뒤 실모드 (2026-09-09 11:10)**: `a106-host-orch`(compose, `~/host-orch/3_FMS`) 가 emqx·rabbitmq 서비스 이름으로 접속.
요청(`n_robots 2, window_s 60, scenario` = 주문 생성기 seed 42 산출물 66 KB) → NCMD Start → GPU 박스 sim-runner `--mode real` 이 Isaac 을 띄워 19 s 뒤 RUNNING →
창 60 s → Stop → 결과 `done`, `scenario_ack true`, `isaac_instances 1`, `rtf_mean 1.0`, `vram_mb_max 5379`. 총 103 s. 터널은 요청 투입·결과 회수에만 썼다.

**fms-core 연동 실모드 (2026-09-09 17:33)**: `--fms-node fms-core` 로 GPU 박스에서 `--once`. sim-runner RUNNING(19 s) → fms-core Start → 3 s 정렬 → 창 180 s(커널 64 틱) →
Stop 둘 다 → sim-runner IDLE(Isaac 정리 21 s) + fms-core IDLE → `done`, `kpi` 14키 + `verify.fms{ticks 64, status done}`. 단위 테스트 77개. 상세는 [`../fms_core/README.md`](../fms_core/README.md) 검증 표.

## 남은 것

- `artifacts.video` 는 러너의 `Runner/VideoUrl`(-215, t3_amr 엣지)에서 온다 — 값은 객체 키 `verify-videos/<run_id>/<파일>` 이고 URL 이 아니다(-233, 백엔드가 서명). host-orch 는 가공 없이 옮긴다. replay·heatmap 키는 아직 null. 새 러너는 fms-core 없이 자체 계획으로 도니 EC2 host-orch 는 `--fms-node` 를 빼고 띄운다(안 빼면 창이 안 열린다)
- sim-wms 파드 · k3s Job — 지금은 fms-core 도 compose 상시 데몬(`infra/compose.fms-core.yml`)
- 러너가 여러 대면 NBIRTH `Runner/State` 가 IDLE 인 노드를 골라 보내고 prefetch 를 러너 수로 (지금은 `--node` 하나)
- `uagv/v2/+/+/#` 관측 구독은 ACL 에 있지만 아직 안 쓴다 (`biz/v1/#` 은 kpi_summary 에 쓴다)
