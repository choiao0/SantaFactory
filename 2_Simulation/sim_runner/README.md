# sim_runner — GPU 서버 Sparkplug B Edge 데몬 (`sim-runner-gpu01`)

host-orch 가 `NCMD Run Control/Start` 를 보내면 로봇 N 대(에이전트 + 실모드 Isaac)를 띄우고, 에이전트가 전부 ONLINE 이면 `DBIRTH ×N` → RUNNING.
로봇 VDA state 를 `Robot/*` DDATA 로 거울 발행하고, `Stop` 이면 DDEATH → 프로세스 정리 → IDLE. 규칙의 원본은
[`3_FMS/contracts/MQTT_CONTRACT.md`](../../3_FMS/contracts/MQTT_CONTRACT.md) §5 (메트릭 사전 5.2 · NCMD 5.3 · 세션 5.4). 순수 파이썬, ROS 는 자식 프로세스에서만.

| 파일 | 역할 |
|---|---|
| `runner.py` | 상태기계 IDLE → STARTING → RUNNING → STOPPING → IDLE \| ERROR. NCMD · Host STATE · VDA 인바운드, 하트비트 5 s, 텔레메트리 |
| `edge.py` | paho 연결 · 구독 · 유언(NDEATH bdSeq) · 재접속 시 bdSeq+1 · CLI (`python3 -m sim_runner`) |
| `spb.py` · `sparkplug_b_pb2.py` | Sparkplug 페이로드 코덱 + `EdgeSession`(bdSeq 파일 보존, seq 0~255). pb2 는 Tahu `sparkplug_b.proto` 생성물 |
| `mirror.py` | `uagv/v2/+/+/{state,connection}` → `Robot/*` 델타(0.05 m · 0.05 rad · 1 %), RTF = Δsim/Δwall (10 s 창) |
| `procs.py` | Start JSON 검증(`RunSpec`), `ros2 launch amr_agent` 명령 조립, 종료 사다리 SIGINT → SIGTERM → SIGKILL |
| `telemetry.py` | `Runner/RamMB`(프로세스 트리 RSS) · `VramMB`(nvidia-smi) |
| `tools/spb_tap.py` | host-orch 계정으로 붙는 관측·NCMD 발사 도구. 06 host-orch 가 생기기 전의 검증용 |
| `sim-runner.service` | systemd 사용자 유닛 (설치 절차는 파일 머리에) |
| `../tests/test_sim_runner_*.py` | 브로커 없는 단위 테스트 98개 (코덱 · 거울 · 프로세스 · 상태기계 · 텔레메트리) |

## 실행

```bash
cd 2_Simulation
# 비밀번호는 argv 가 아니라 환경에서만: MQTT_HOST · MQTT_PORT · MQTT_PW_SIM_RUNNER · MQTT_PW_AMR (팀 .env, 600)
python3 -m sim_runner --env-file ../3_FMS/infra/emqx/.env --mode fake -v          # Isaac 없이 fake_robot 에이전트
python3 -m sim_runner --env-file ../3_FMS/infra/emqx/.env --mode real       # 실모드: 기본 `cd ~/isaacsim && ./python.sh …/apps/warehouse_sim.py`
#   (--isaac-cmd 로 교체. WSIM_N · ROS_DOMAIN_ID · SIM_SCENARIO_PATH · WSIM_SPAWN 은 환경으로 전달. WSIM_LEAN 등은 명령에 직접)

# host-orch 대역 (다른 터미널) — STATE/host-orch online retained 발행 + spBv1.0/santa/# 디코드 출력
python3 -m sim_runner.tools.spb_tap --env-file ../3_FMS/infra/emqx/.env --vda
# 명령만 보낼 때는 --no-state (진짜 host 가 켜져 있거나 위 관측 tap 이 STATE 를 들고 있을 때)
python3 -m sim_runner.tools.spb_tap --env-file ../3_FMS/infra/emqx/.env --no-state --n 2 --run-id r1 --wait RUNNING
python3 -m sim_runner.tools.spb_tap --env-file ../3_FMS/infra/emqx/.env --no-state --stop --wait IDLE
python3 -m sim_runner.tools.spb_tap --env-file ../3_FMS/infra/emqx/.env --no-state --rebirth --duration 3
python3 -m sim_runner.tools.spb_tap … --start '{"run_id":"r2","n_robots":3,"models":[{"serial":"amr01"},…],"timeout_s":1200}'

python3 -m pytest tests/test_sim_runner_*.py -q     # 단위 테스트
```

옵션: `--ready-timeout-s`(Start 뒤 전원 ONLINE+포즈 상한, 기본 fake 120 · real 420) · `--host-offline-s 15` · `--heartbeat-s 5` · `--isaac-warmup-s 0`(Isaac 뒤 에이전트까지 지연; 기본은 같이 띄우고 포즈를 기다림) ·
`--state-dir ~/.local/state/sim_runner`(bdseq · 런별 에이전트 로그 `logs/<run_id>.<serial>.log`) · `--ros-setup`(반복; 기본 humble + `t4_agent/install/setup.bash`).

## 동작 요약 (계약 §5.3 · §5.4)

| 입력 | 동작 |
|---|---|
| `Run Control/Start` JSON | 검증 실패 → `LastError` "bad Start: …"(상태 불변). IDLE/ERROR 면 STARTING: (실모드) Isaac + 에이전트 ×N 기동 → 전원 ONLINE **+ 포즈 수신**(Isaac odom 이 와야 생김) → DBIRTH ×N → RUNNING. `scenario` 가 있으면 sha 대조 뒤 `<state>/runs/<run_id>/scenario.json` 으로 쓰고 `SIM_SCENARIO_PATH`·`SIM_SCENARIO_SHA256`(·`WSIM_SPAWN`) 환경으로 넘기며 `Runner/ScenarioSha` 로 되돌린다. 같은 run_id 재수신 = 상태만 재보고, 다른 run_id = "busy" 거절 |
| `Run Control/Stop` | DDEATH ×N → SIGINT(브리지 OFFLINE) → 5 s 뒤 SIGTERM → 3 s 뒤 SIGKILL → (Isaac 같은 사다리, 20 s) → IDLE |
| `Node Control/Rebirth` | NBIRTH + 살아 있는 DBIRTH |
| Host `STATE` online 복귀 (offline → online, 또는 timestamp 증가) | 재발행. offline 15 s 지속 (RUNNING 중) → ERROR "host-orch offline" |
| 스스로 | 하트비트 5 s (`Runner/Heartbeat` + 바뀐 RTF · IsaacInstances · RamMB · VramMB) · timeout_s · 프로세스 사망 → ERROR + `LastError` |
| 재접속 · 재시작 | bdSeq+1 (파일 보존) 로 NDEATH 유언 갱신 → NBIRTH. SIGTERM 정상 종료는 런 정리 뒤 NDEATH 직접 발행 |

## 검증 (2026-09-08, EC2 EMQX 6.3.0 over tailscale, `--mode fake`, 로봇 2)

호스트 대역은 `spb_tap`(STATE online retained), 명령 tap 은 `--no-state`. 로봇 계정 amr01·amr02 는 팀 `.env` 의 MQTT_PW_AMR.

| 단계 | 결과 |
|---|---|
| Start(n=2) → 에이전트 2대 ONLINE → DBIRTH ×2 → RUNNING | 0.5 s (NDATA STARTING → RUNNING), DDATA 는 첫 포즈 2건뿐(정지 로봇), seq 갭 0 |
| 같은 run_id 재발행 | 기동 없이 NDATA `State=RUNNING RunId=e2e-1` 재보고 |
| 다른 run_id (RUNNING 중) | `LastError='busy: RUNNING e2e-1; Start e2e-2 ignored'`, 상태 불변 |
| Stop | DDEATH ×2 → STOPPING → 브리지 OFFLINE → IDLE 1.45 s, 에이전트 프로세스 0 |
| Rebirth (IDLE) | NBIRTH 만 (DBIRTH 없음) |
| host-orch STATE offline (tap kill -9 → 유언) | 16 s 뒤 DDEATH ×2 → `State=STOPPING LastError='host-orch offline > 15s'` → ERROR, 에이전트 0 |
| runner kill -9 (RUNNING 중) | NDEATH(bdSeq=0) 유언 즉시. 재시작: 고아 런 프로세스 10개 reap → NBIRTH bdSeq=1 |
| runner SIGTERM | 런 정리 뒤 NDEATH(bdSeq=1) 직접 발행 |
| 에이전트 kill -9 | connection CONNECTIONBROKEN retained (LWT) |

**실모드 (2026-09-09, EC2 host-orch → EMQX → 이 박스, 로봇 2, 창 60 s, 주문 스크립트 66 KB 동봉)**

| 단계 | 결과 |
|---|---|
| NCMD Start(scenario 포함) → Isaac(`apps/warehouse_sim.py`, WSIM_N=2) + 에이전트 기동 | 19 s 뒤 2대 ONLINE + 포즈 → DBIRTH ×2 → RUNNING (헤드리스 부팅 + 첫 odom) |
| 데이터 도달 | `runs/verify-real-1/scenario.json` sha == 요청 sha, `Runner/ScenarioSha` 로 되돌려 host-orch 결과 `scenario_ack: true` |
| RUNNING 60 s | RTF 1.0, RAM 9.6 GB(Isaac+에이전트 트리), VRAM 5.4 GB, `IsaacInstances 1` |
| Stop | Isaac 이 SIGINT 를 무시해 20 s 유예 뒤 SIGTERM 으로 종료 → IDLE (창 60 s + 정리 22 s = elapsed 82 s). 잔여 프로세스 0, VRAM 22 MiB 복귀 |

단위 테스트 106개 (`tests/test_sim_runner_*.py`), 브로커·ROS 불필요. E2E 는 위 절차를 손으로 (또는 세션 스크립트로) 반복.

## 남은 것

- 실모드: Isaac 준비 감지가 `--isaac-warmup-s` 고정 대기다 — `/clock` 또는 로봇 odom 관측으로 바꿀 것. `warehouse_sim.py` 헤드리스 인자·WSIM_N 연동은 미검증
- `DCMD/sim-runner-gpu01/+` 는 구독만 하고 무시(계약에 정의된 디바이스 명령 없음)
- `Robot/AmclErr` 는 DBIRTH 에 is_null 선언만 (AMCL 폐루프 실측 뒤)
- 06 host-orch 가 생기면 `spb_tap` 은 관측 전용으로
