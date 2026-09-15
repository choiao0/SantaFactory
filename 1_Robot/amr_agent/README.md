# AMR agent (ROS 2 Humble) · VDA 5050 ↔ PIBT 틱

FMS(PIBT 틱 루프)와 로봇(Isaac 또는 실기) 사이의 실행 계층. FMS 파트가 넘긴 요구사항
(스팟턴 · 경유점 오차 ≤ 0.1 m · 틱 배리어 동기 · 후진 1칸)을 VDA 5050 계약 위에서 구현한다.
2026-09-11 `2_Simulation/t4_agent` → `1_Robot/amr_agent` 로 이동(배포 단위 분리). **동작을 정하는 숫자는 코드가 아니라
프로파일에서 온다** — 기종 yaml 위에 BE 견적 요청의 `amr` 블록을 그대로 덮어쓴다.

```
src/amr_agent_msgs   MovePrimitive.action   (TURN | DRIVE, reverse 플래그)
src/amr_agent
  amr_agent/profile.py   프로파일 3층 병합 · BE 키 번역 · 검증 · 노드별 파생값        — 순수 파이썬
  amr_agent/battery.py   SoC 모델 (주행/정지 소모 · 충전 · threshold)                   — 순수 파이썬
  amr_agent/vda5050      topics · order(주문 모델·OrderBook 스티칭 규칙) · state · models(yaml 로더·factsheet 기하)
  amr_agent/control      primitives (TurnController · DriveController, 램프·정지거리)  — 순수 파이썬
  amr_agent/nodes        vda5050_bridge(MQTT↔ROS) · order_executor · primitive_controller · fake_robot
  amr_agent/tools        fake_fms — 배리어 틱으로 계획을 한 노드씩 풀어 주는 가짜 FMS
  config/models/<model>.yaml   기종 팩토리 프로파일 (iw_hub)
  config/overrides.example.yaml  BE amr 블록 예시 (profile_file 로 바로 쓸 수 있다)
  launch/agent.launch.py · test/
```

## 파라미터 — 프로파일 3층

노드 4개가 같은 입력(`model` · `profile_file` · `profile_overrides`)을 받아 **같은 규칙**으로 하나의 프로파일을 만든다.
그래서 브리지가 factsheet 로 내보내는 속도와 컨트롤러가 실제로 지키는 속도가 같다.

| 층 (위가 이긴다) | 넣는 법 | 누가 넣나 |
|---|---|---|
| `profile_overrides:='<JSON>'` | 런치 인자. BE 키·프로파일 키 모두 | **sim-runner** — Start 의 `scenario.amr` 을 그대로 (`sim_runner/procs.py::agent_cmd`) |
| `profile_file:=<yaml\|json>` | 파일 경로 | 손으로 돌릴 때, 나중에 컨테이너 볼륨 |
| `config/models/<model>.yaml` | `model:=iw_hub` | 기종 팩토리 값 (치수·바퀴·한계·타이밍) + `profile.py` SECTION_DEFAULTS |

모르는 키, 범위 밖 값(`wheels` 형식 포함), BE 키와 그 대상 프로파일 키를 동시에 주는 것, `capacity`/`tote_units` 의 소수 → **런치 실패**(기본값으로 몰래 돌지 않는다). 기종 yaml 이 절에 더한 키는 오버라이드 가능하다.
각 노드는 기동 로그에 `profile[model=… v_max=… soc=…]` 한 줄을 남긴다.

### BE `amr` 블록 → 프로파일 (5_Docs/Web/시뮬엔진연동API명세서 §1-1)

| BE 키 | 프로파일 | 단위 | 어디에 쓰이나 |
|---|---|---|---|
| `speed_empty` | `v_max` | m/s | 컨트롤러 속도 상한 · factsheet `speedMax` · 정지거리 |
| `speed_loaded` | `v_max_loaded` | m/s | 저장만 — 적재 상태 추적(order 액션 pick/drop) 전까지 미적용 |
| `consumption` | `battery.consumption_pct_per_s` | %/s (주행 중; 정지는 ×0.25) | SoC 감소 → `state.batteryState` · threshold 아래면 `information[batteryLow]` |
| `battery` | `battery.soc_init_pct` | % (0<v<1 은 비율, 1 이상은 %) | 초기 SoC. **dict 로 주면 BE 키가 아니라 `battery` 절 오버라이드** |
| `charge_time` | `battery.charge_time_s` | s | 충전 속도 (100 %/charge_time) |
| `charge_threshold` | `battery.charge_threshold_pct` | % (0<v<1 은 비율, 1 이상은 %) | batteryLow 경계 |
| `capacity` | `load.capacity_totes` | 토트 1~6 | 검증 조건 기록 (DES 와 같은 값이어야 함, fms-core 도 같은 기본값) |
| `tote_units` | `load.tote_units` | 상품/토트 | 〃 |

`consumption` 의 단위는 명세에 정의가 없다 — **%/s 가정**. 웹팀이 확정하면 `profile.py` `BE_KEYS` 의 변환 한 줄만 바뀐다.

### 프로파일 키 (기종 yaml · profile_file 에서 직접)

| 절 | 키 | 뜻 |
|---|---|---|
| 상위 | `v_min v_max v_max_loaded a_max w_max alpha_max w_min` | 컨트롤러 한계 = factsheet physicalParameters |
| 상위 | `length width height front_overhang rear_overhang swing_radius wheels` | factsheet 기하 (원천이던 `2_Simulation/sil_isaac/robot/profile.py` 는 -219 로 삭제, 값은 `2_Simulation/README.md` 실측 상수 절) |
| 상위 | `state_interval order_interval` | state 발행 주기(1/state_interval Hz) · factsheet timing |
| `control` | `rate_hz tol_xy tol_theta timeout_s turn_threshold zero_edge_eps first_node_tol k_turn k_heading k_lateral` | 제어기 성질. order 의 `allowedDeviationXY/Theta` 가 더 작으면 그것 |
| `battery` | `soc_init_pct consumption_pct_per_s idle_ratio charge_time_s charge_threshold_pct` | 위 BE 매핑 대상 |
| `load` | `capacity_totes tote_units` | 〃 |
| `plant` | `v_max w_max a_max alpha_max` | **fake_robot 만** — 가짜 로봇의 물리 응답(T1 실측 ~6 m/s², 에셋 상한 0.835) |

`v_max` 기본 0.8: T1 실측 에셋 상한 0.835 m/s. 카탈로그 1.2 는 시뮬 에셋이 못 내고, BE 가 1.2 를 보내면 컨트롤러는 1.2 를 명령하되 플랜트가 0.835 에서 포화한다.

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
엣지 `maxSpeed` 가 오면 그 구간은 그 속도까지만(FMS 가 구간별로 더 낮출 수 있다).

## 실행

```bash
cd 1_Robot/amr_agent
source /opt/ros/humble/setup.bash
PYTHONNOUSERSITE=1 colcon build --symlink-install && source install/setup.bash

# 1) 브로커 — EMQX (3_FMS/infra/emqx: compose 또는 tar.gz, 계정은 .env → bootstrap_users.sh). 익명 접속은 거부된다

# 2) 에이전트 + 가짜 로봇 (Isaac 없이). 사용자명 = 시리얼, manufacturer 기본 idealworks
ros2 launch amr_agent agent.launch.py serial:=amr01 fake_robot:=true mqtt_username:=amr01 mqtt_password:=$MQTT_PW_AMR
#    BE 파라미터로 — sim-runner 가 보내는 것과 같은 형태
ros2 launch amr_agent agent.launch.py serial:=amr01 fake_robot:=true mqtt_username:=amr01 mqtt_password:=$MQTT_PW_AMR \
     profile_overrides:='{"speed_empty": 1.2, "speed_loaded": 1.0, "consumption": 0.02, "battery": 100, "charge_threshold": 0.2, "capacity": 6, "tote_units": 8}'
#    같은 것을 파일로
ros2 launch amr_agent agent.launch.py serial:=amr02 fake_robot:=true fake_x:=3.0 mqtt_username:=amr02 mqtt_password:=$MQTT_PW_AMR \
     profile_file:=$(ros2 pkg prefix amr_agent)/share/amr_agent/config/overrides.example.yaml

# 3) 가짜 FMS (fms-core 계정) — F 전진 · B 후진 · L/R 회전, 한 노드씩 배리어 틱. --repeat-last = 같은 order 재발행이 무시되는지
python3 -m amr_agent.tools.fake_fms --user fms-core --pw $MQTT_PW_FMS_CORE --serial amr01 --plan F,F,L,F,B --repeat-last

# 관측 (host-orch 계정): connection·factsheet 는 retained 라 늦게 붙어도 바로 온다. factsheet.speedMax 에 BE 값이 보인다
mosquitto_sub -h localhost -u host-orch -P $MQTT_PW_HOST_ORCH -v -t 'uagv/v2/+/+/connection' -t 'uagv/v2/+/+/factsheet'

# Isaac 상대 — WSIM_N 모드(/amr01/odom …)면 remap 불필요, 단일 모드면 flat_topics:=true
ros2 launch amr_agent agent.launch.py serial:=amr01 mqtt_username:=amr01 mqtt_password:=$MQTT_PW_AMR pose_source:=odom use_sim_time:=true
```

빌드 주의: `~/.local` 에 최신 setuptools 가 있으면 `amr_agent_msgs` 의 egg_info 가 시스템 packaging 과 충돌한다
(`canonicalize_version() … strip_trailing_zero`). `PYTHONNOUSERSITE=1 colcon build --symlink-install` 로 빌드하고 실행은 평소대로.

### sim-runner 연동

`2_Simulation/sim_runner` 는 기본으로 `1_Robot/amr_agent/install/setup.bash` 를 source 하고(`--ros-setup` 으로 바꿀 수 있다),
NCMD Start 의 `scenario.amr`(= BE 견적 요청의 amr 블록, SIM_VERIFY_CONTRACT §2)을 `profile_overrides:=` 로 그대로 넘긴다.
`models[]` 의 `model` 이 `model:=` 이 된다. 그래서 **검증 런의 로봇은 견적이 받은 그 파라미터로 돈다.**

## 브로커 접속 규약 (MQTT_CONTRACT §3·§4)

| 항목 | 동작 |
|---|---|
| 계정 | `mqtt_username` = 시리얼(`amrNN`), clientId `idealworks-amrNN-agent`. ACL 이 `uagv/v2/+/<시리얼>/…` 만 연다 — 남의 토픽에 쓰면 브로커가 끊는다 |
| 접속 직후 | `connection` ONLINE(retained, QoS1) → `factsheet`(retained, QoS1). factsheet = 병합 프로파일 → `StateBuilder.factsheet()` |
| 단절 | LWT `connection` CONNECTIONBROKEN(retained). keepalive 30 s → 최대 45 s 안에 도착. 정상 종료는 OFFLINE |
| 중복 order | 같은 orderId·같은 orderUpdateId = FMS 재발행 → 무시하고 state 만 다시 낸다(오류 없음). 낮은 orderUpdateId → `orderUpdateError` |
| state | `batteryState.batteryCharge` 가 SoC 모델을 따라 움직인다. threshold 아래면 `information[{infoType: batteryLow}]` — 충전 결정은 FMS 몫 |
| 기종 추가 | `config/models/<model>.yaml` 하나 추가 + `model:=<model>`. 숫자의 원천은 `2_Simulation/README.md` 실측 상수 절(구 sil_isaac/robot/profile.py, -219 로 삭제) |

## 테스트

```bash
cd 1_Robot/amr_agent && python3 -m pytest -q     # ROS 불필요: profile 13 · battery 5 · state · order book · primitives
```
CI: `.gitlab-ci.yml` `robot-python-test` (MR 에서 `1_Robot/**` 변경 시).

## 남은 것

- 컨테이너화: 이 패키지 + humble 베이스 이미지 → GPU 서버에서 `profile_file` 볼륨/`profile_overrides` env 로 기동 (sim-runner 가 컨테이너를 띄우는 형태로)
- `speed_loaded` 적용 — order 의 pick/drop 액션으로 적재 상태를 추적한 뒤
- 배터리: 충전 존 진입/이탈을 FMS 가 instantAction 으로 알려주면 `charging` 을 켠다 (지금은 소모만)
- AMCL 폐루프(`pose_source:=amcl`)에서의 정지 정밀도 실측, 오돔 노이즈 주입
