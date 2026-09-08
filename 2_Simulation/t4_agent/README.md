# T4 — AMR agent (ROS 2 Humble) · VDA 5050 ↔ PIBT 틱

FMS(PIBT 틱 루프)와 Isaac 로봇 사이의 실행 계층. FMS 파트가 넘긴 요구사항
(스팟턴 · 경유점 오차 ≤ 0.1 m · 틱 배리어 동기 · 후진 1칸)을 VDA 5050 계약 위에서 구현한다.

```
src/amr_agent_msgs   MovePrimitive.action   (TURN | DRIVE, reverse 플래그)
src/amr_agent
  amr_agent/vda5050  topics · order(주문 모델·OrderBook 스티칭 규칙) · state(상태 메시지)  — 순수 파이썬
  amr_agent/control  primitives (TurnController · DriveController, 램프·정지거리)          — 순수 파이썬
  amr_agent/nodes    vda5050_bridge(MQTT↔ROS) · order_executor · primitive_controller · fake_robot
  amr_agent/tools    fake_fms — 배리어 틱으로 계획을 한 노드씩 풀어 주는 가짜 FMS
  launch/agent.launch.py · config/agent.yaml · test/
```

## FMS 틱 ↔ VDA 5050 매핑

| PIBT 액션 | VDA 5050 표현 | 에이전트 동작 |
|---|---|---|
| 전진 1칸 | 다음 노드 released, 엣지 orientation 없음 | 헤딩 정렬(필요 시 스팟턴) → 직진 → 셀 중심 정지 |
| 후진 1칸 | 엣지 `orientation = π`, `orientationType TANGENTIAL` | 헤딩 유지, v < 0 |
| 회전 ±90° | 같은 좌표의 노드 + 새 `theta` (길이 0 엣지) | 제자리 회전 |
| 대기 | 새 노드 없음 | 정지 유지 |
| 틱 완료 ack | `state.lastNodeId` = 방금 released 된 노드 (변화 즉시 발행) | FMS는 전 로봇 ack 후 다음 틱 |

1 틱 = orderUpdateId 를 1 올리며 노드 하나를 더 released 로 보내는 order 업데이트.
업데이트는 마지막 base 노드에서 시작해야 하고(스티칭), 새 orderId 는 base 가 끝난 뒤에만 받는다.
노드의 `allowedDeviationXY / Theta` 가 정지 허용치 상한이다(기본 0.05 m · 0.03 rad).

## 실행

```bash
cd 2_Simulation/t4_agent
source /opt/ros/humble/setup.bash
colcon build --symlink-install && source install/setup.bash

# 1) 브로커 — EMQX (3_FMS/infra/emqx: compose 또는 tar.gz, 계정은 .env → bootstrap_users.sh). 익명 접속은 거부된다
#    (급할 때 계정 없는 로컬 브로커: amqtt — 그때는 mqtt_username 을 비운다)

# 2) 에이전트 + 가짜 로봇 (Isaac 없이). 사용자명 = 시리얼, manufacturer 기본 idealworks, factsheet 는 config/models/iw_hub.yaml
ros2 launch amr_agent agent.launch.py serial:=amr01 fake_robot:=true mqtt_username:=amr01 mqtt_password:=$MQTT_PW_AMR
ros2 launch amr_agent agent.launch.py serial:=amr02 fake_robot:=true fake_x:=3.0 mqtt_username:=amr02 mqtt_password:=$MQTT_PW_AMR

# 3) 가짜 FMS (fms-core 계정) — F 전진 · B 후진 · L/R 회전, 한 노드씩 배리어 틱. --repeat-last = 같은 order 재발행이 무시되는지
python3 -m amr_agent.tools.fake_fms --user fms-core --pw $MQTT_PW_FMS_CORE --serial amr01 --plan F,F,L,F,B --repeat-last

# 관측 (host-orch 계정): connection·factsheet 는 retained 라 늦게 붙어도 바로 온다
mosquitto_sub -h localhost -u host-orch -P $MQTT_PW_HOST_ORCH -v -t 'uagv/v2/+/+/connection' -t 'uagv/v2/+/+/factsheet'

# Isaac 상대 — WSIM_N 모드(/amr01/odom …)면 remap 불필요, 단일 모드면 flat_topics:=true
ros2 launch amr_agent agent.launch.py serial:=amr01 mqtt_username:=amr01 mqtt_password:=$MQTT_PW_AMR pose_source:=odom use_sim_time:=true
```

빌드 주의: `~/.local` 에 최신 setuptools 가 있으면 `amr_agent_msgs` 의 egg_info 가 시스템 packaging 과 충돌한다
(`canonicalize_version() … strip_trailing_zero`). `PYTHONNOUSERSITE=1 colcon build --symlink-install` 로 빌드하고 실행은 평소대로.

## 브로커 접속 규약 (MQTT_CONTRACT §3·§4)

| 항목 | 동작 |
|---|---|
| 계정 | `mqtt_username` = 시리얼(`amrNN`), clientId `idealworks-amrNN-agent`. ACL 이 `uagv/v2/+/<시리얼>/…` 만 연다 — 남의 토픽에 쓰면 브로커가 끊는다 |
| 접속 직후 | `connection` ONLINE(retained, QoS1) → `factsheet`(retained, QoS1). factsheet 는 `config/models/<model>.yaml` → `StateBuilder.factsheet()` |
| 단절 | LWT `connection` CONNECTIONBROKEN(retained). keepalive 30 s → 최대 45 s 안에 도착. 정상 종료는 OFFLINE |
| 중복 order | 같은 orderId·같은 orderUpdateId = FMS 재발행 → 무시하고 state 만 다시 낸다(오류 없음). 낮은 orderUpdateId → `orderUpdateError` |
| 기종 추가 | `config/models/<model>.yaml` 하나 추가 + `model:=<model>`. 숫자의 원천은 `2_Simulation/sil_isaac/robot/profile.py` |

단위 테스트(ROS 불필요): `cd src/amr_agent && python3 -m pytest -q test/`

## 남은 것

- Isaac 다중 로봇: warehouse_sim 이 로봇별 네임스페이스(`/amr01/odom` …)로 발행하도록 확장
- 앞축 종방향 위치·회전 각속도 실측 → FMS 헤딩 상수(REAR_CELLS · TURN_TICKS) 확정
- sim-runner 데몬(Sparkplug NCMD Start/Stop)과 에이전트 ×N 기동 연동, 런 아티팩트(리플레이·영상) — `2_Simulation/sim_runner/` (다음)
- AMCL 폐루프(`pose_source:=amcl`)에서의 정지 정밀도 실측, 오돔 노이즈 주입
