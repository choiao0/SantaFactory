# 2_Simulation — SIL 검증 트랙 (ROS2 x Isaac Sim)

SimPy DES가 낸 "최적 구성"이 실제 로봇 스택에서 성립하는지 검증하는 계층.
로드맵: T1 텔레옵 → T2 매핑·추종 → T3 창고 씬 → **T4 에이전트(현 위치)** → 다중 로봇 검증 런.
실행 환경: 홈 GPU 서버(RTX 5080 16 GB · RAM 64 GB), Isaac Sim 6.0.1 `~/isaacsim` + `/opt/ros/humble`.

| 디렉토리 | 내용 | 상태 |
|---|---|---|
| [`t1_teleop/`](t1_teleop/) | iw.hub 텔레옵 — Isaac x ROS2 브리지 개통, 가감속 실측 | 완료 |
| [`t2_mapping/`](t2_mapping/) · [`t2_follower/`](t2_follower/) | GT 방 SLAM 매핑 런(커미셔닝 재현, 지도 오차 정량) + 자체 추종기(Pure Pursuit·가속 램프·보호 필드, 엣지 통과시간 실측) | 완료 (9/8 이식) |
| [`t3_warehouse_map/`](t3_warehouse_map/) | 설계도 DXF → occupancy grid + stations.json·zones.json (v6.0 구역제 A~V 22구역, 단일 소스) | 완료 |
| [`t3_warehouse/`](t3_warehouse/) | 그리드 → Isaac USD 씬 (건물 실측·화물·omap V&V) + iw.hub ×N·물리 라이다·AMCL 개통(`WSIM_N`으로 `/amr01~/…` 네임스페이스) | 완료 |
| [`calibration/turn_probe/`](calibration/turn_probe/) | iw.hub 스팟턴 실측 — 회전 중심 = 구동축 = 포즈 원점, 차체 앞 0.40 m·뒤 1.03 m(뒤 칸 1개 점유, 스윙 반경 1.09 m), 90° 폐루프 1.9 s → FMS 헤딩 상수 | 완료 (9/6) |
| `isaac_replay.py` + `isaac_export_t3/` | 그리드 시뮬 궤적을 실물 씬에서 재생 (WebRTC) | 도구 |
| [`t4_agent/`](t4_agent/) | ROS 2 AMR 에이전트 — VDA 5050 MQTT 브리지 + order executor(틱당 노드 1개 스티칭·`lastNodeId` ack) + 그리드 프리미티브(스팟턴 · 직진 · 후진 1칸) + fake robot/fake FMS | 뼈대 완료 — Isaac 없이 배리어 틱 E2E 통과(7틱, 정지 오차 4 mm) |

| [`sim_runner/`](sim_runner/) | GPU 서버 상시 Sparkplug B Edge 데몬 `sim-runner-gpu01` — host-orch 의 NCMD Start/Stop 으로 에이전트 ×N(+Isaac) 기동·정리, VDA state 를 `Robot/*` DDATA 로 거울, 하트비트·RTF·RAM·VRAM. `--fake` 로 Isaac 없이 동작, `tools/spb_tap.py` 가 host-orch 대역 | fake 모드 EC2 브로커 E2E 통과 (9/8) |

노드·토픽 구조(FMS 틱 ↔ VDA 5050 매핑, 실행 방법, 남은 일)는 [`t4_agent/README.md`](t4_agent/README.md) 참조.

## 코드 구조 (2026-09-07 리팩토링)

T1~T4 스크립트를 라이브러리 패키지로 분할했다. 옛 경로의 `.py`(`t3_warehouse/warehouse_sim.py`, `t1_teleop/teleop_sim.py`,
`t2_mapping/mapping_sim.py`, `t3_warehouse/view_scene.py`, `t3_warehouse/ros2/patrol.py` 등)는 셔임이라 각 README 의 실행 명령이 그대로 동작한다.

```
2_Simulation/
├─ apps/            실행 엔트리 (Isaac python.sh). 얇다 — 설정 읽고 라이브러리를 조립만 한다
│   warehouse_sim.py  T3 창고 씬 + iw.hub ×N + 물리 라이다 + ROS 2   (WSIM_N · WSIM_LEAN · WSIM_INST …)
│   teleop_sim.py     T1 격자 환경 텔레옵            mapping_sim.py  T2 GT 방 + RTX 라이다 + 패트롤
│   view_scene.py     T3 씬 관전                     build_scene.py  그리드 → USD 씬 빌더
├─ sil_isaac/       Isaac 쪽 공용 라이브러리 (omni/pxr 는 함수 안에서 lazy import → 순수부는 시스템 python 으로 테스트)
│   app.py            SimulationApp 기동 · 확장 · 물리 · 경량 프로파일 a~g(LeanProfile) · 인스턴스 포트
│   stage.py          스테이지 초기화 · 참조 로드(물리 전용 스테이지 치환)
│   robot/profile.py  RobotProfile(기종 하나의 숫자 전부) · IWHUB 실측값     robot/iwhub.py  에셋 런타임 수술 3단계
│   robot/spawn.py    spawn_robot → RobotHandle(drive · sample · clamp)     robot/kinematics.py  포즈·속도·쿼터니언
│   sensors/raycast_lidar.py  LidarSpec · ray_table · 물리 레이캐스트 라이다   sensors/rtx_lidar.py  RTX 회전 라이다(T2)
│   ros2/graph.py     graph_spec(순수 명세) · Ros2Graph(편집·핸들·publish)  — 네임스페이스·/clock 규칙이 여기 한 곳
│   viewer/           http_stream.py(TCP MJPEG) · follow_camera.py
│   scene/            warehouse.py(씬 로드·스폰 좌표) · gt_room.py(T2 GT 방·장애물)
│   runtime/loop.py   SimLoop — 재생/리셋 처리 · 프레임 콜백 · 주기 로그
├─ sil_ros/         ROS 2 쪽 (시스템 python3 + rclpy). geometry · gridmap(A*) 공용 + nodes/(patrol · multi_check · follower · measure_accel · spin_probe) + tools/export_replay
├─ scene_builder/   build_scene.py 분할 패키지 (config · prims · materials · building · roof · racks · stations · offices · vnv · shots · build)
├─ tests/           pytest — Isaac·rclpy 없이 도는 순수부 (sil_isaac 명세·운동학·스폰 좌표·경량 프로파일, sil_ros gridmap, scene_builder gridutil)
├─ t4_agent/        ROS 2 에이전트 패키지 (VDA 5050 브리지 · order executor · 그리드 프리미티브) — 구조 변경 없음
├─ t1_teleop/ t2_mapping/ t2_follower/ t3_warehouse/  옛 경로: 실행 셔임 + 데이터(USD·YAML·out)   ← 문서·README 의 경로가 그대로 동작
├─ t3_warehouse_map/  DXF → occupancy grid 파이프라인 (단일 소스 map/)
└─ calibration/     스팟턴 실측(wsim_wrap 은 새 엔트리에 훅)
```

원칙: 엔트리는 설정·조립만, 숫자는 `RobotProfile`·`LidarSpec`·`LeanProfile` 한 곳에, 토픽·프레임 규약은 `ros2/graph.py` 한 곳에.
새 기종은 `robot/profile.py` 에 `RobotProfile` 하나를 더 적으면 spawn·수술·라이다·factsheet 가 같은 값을 본다.

## 실행

```bash
source /opt/ros/humble/setup.bash
cd ~/isaacsim && ./python.sh <repo>/2_Simulation/apps/warehouse_sim.py                 # T3 단일 (/cmd_vel /odom /scan)
cd ~/isaacsim && WSIM_N=3 ./python.sh <repo>/2_Simulation/apps/warehouse_sim.py        # 3대 (/amr01~03/…)
cd ~/isaacsim && WSIM_N=6 WSIM_LEAN=e WSIM_INST=0 ./python.sh <repo>/2_Simulation/apps/warehouse_sim.py   # 경량 e (렌더 off) — 병렬 실측 구성
python3 <repo>/2_Simulation/t3_warehouse/ros2/multi_check.py --n 3 --drive amr02       # 개통 검증 (PASS 면 exit 0)
ros2 launch <repo>/2_Simulation/t3_warehouse/ros2/loc.launch.py                        # AMCL (단일 모드)
cd ~/isaacsim && ./python.sh <repo>/2_Simulation/apps/teleop_sim.py                    # T1
cd ~/isaacsim && ./python.sh <repo>/2_Simulation/apps/mapping_sim.py --laps 2          # T2
```

`WSIM_INST=k` 는 인스턴스별 포트(MJPEG 8211+k · 스트리밍 49100+k)를 띄우고, `WSIM_LEAN=a..g` 는 렌더·시각화를 단계별로 끈 경량 프로파일이다
(병렬 실측 래퍼 `wsim_lean.py` 의 몽키패치를 대체).

## 테스트

```bash
cd <repo>/2_Simulation && python3 -m pytest      # sil_isaac 순수부 · sil_ros · scene_builder · t4_agent 단위 테스트 (Isaac 불필요)
```
Isaac 실물 검증(리팩토링 후): `WSIM_N=2 apps/warehouse_sim.py` 부팅 → `multi_check --n 2 --drive amr02` PASS
(odom·scan 45 Hz, amr02 만 이동, TF 프레임 전부 확인). `scene_builder` 재빌드는 리팩토링 전과 byte 동일한 `warehouse_scene.usd` 를 낸다.

## 실측 상수 (FMS 인도용, 상세 `calibration/turn_probe/README.md`)

- 회전 중심 = 구동축 = 포즈(/odom) 원점. 회전 중 원점 이탈 ≤ 1.3 cm.
- 차체: 축 기준 앞 0.40 m · 뒤 1.03 m · 폭 0.66 m → 1 m 격자에서 자기 칸 + 뒤 칸 1개 점유, 스팟턴 스윙 반경 1.09 m.
- 각속도: 지령 대비 95~97 %, 90° 폐루프 회전 1.9 s(T4 한계 1.2 rad/s), 1 m 직진 2.2 s(T4 E2E).
- 운동학: 바퀴 반경 0.08 m · 트랙 0.58 m (`sil_isaac/robot/profile.py`). T1 의 옛 0.115/0.413 은 오류였고 그때의 0.835 m/s 상한은 그 결과다.

공통 전제: Isaac Sim 6.0.1 standalone, 헤드리스 서버는 WebRTC 또는 TCP MJPEG(:8211)로 관전.
동시 실행(2026-09-05 실측, RTX 5080 16GB·RAM 64GB): 원본 구성은 인스턴스당 RAM 8.1GB·VRAM 5.3GB로 2개까지,
렌더·시각화를 끈 경량 구성(`WSIM_LEAN=e`)은 RAM 7GB·VRAM 2.3GB로 6개 동시 정상(RTF 1.25). 상세는 각 디렉토리 README 참조.

남은 것: sim-runner 데몬(Sparkplug NCMD) · 에이전트 ×N 기동, AMCL 폐루프 정지 정밀도 · 오돔 노이즈, 엣지 통과 · 도킹 시간 분포 실측(DES 환류).
