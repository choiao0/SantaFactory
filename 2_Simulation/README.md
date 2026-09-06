# 2_Simulation — SIL 검증 트랙 (ROS2 x Isaac Sim)

SimPy DES가 낸 "최적 구성"이 실제 로봇 스택에서 성립하는지 검증하는 계층.
로드맵: T1 텔레옵 → T2 매핑·추종 → T3 창고 씬 → **T4 에이전트(현 위치)** → 다중 로봇 검증 런.

| 디렉토리 | 내용 | 상태 |
|---|---|---|
| [`t1_teleop/`](t1_teleop/) | iw.hub 텔레옵 — Isaac x ROS2 브리지 개통, 가감속 실측 | 완료 |
| [`t3_warehouse_map/`](t3_warehouse_map/) | 설계도 DXF → occupancy grid (v5.9, 단일 소스) | 완료 |
| [`t3_warehouse/`](t3_warehouse/) | 그리드 → Isaac USD 씬 (건물 실측·화물·omap V&V) | 완료 |
| `isaac_replay.py` + `isaac_export_t3/` | 그리드 시뮬 궤적을 실물 씬에서 재생 (WebRTC) | 도구 |
| [`t4_agent/`](t4_agent/) | ROS 2 AMR 에이전트 — VDA 5050 MQTT 브리지 + order executor(틱당 노드 1개 스티칭·`lastNodeId` ack) + 그리드 프리미티브(스팟턴 · 직진 · 후진 1칸) + fake robot/fake FMS | 뼈대 완료 — Isaac 없이 배리어 틱 E2E 통과(7틱, 정지 오차 4 mm) |

노드·토픽 구조(FMS 틱 ↔ VDA 5050 매핑, 실행 방법, 남은 일)는 [`t4_agent/README.md`](t4_agent/README.md) 참조.

공통 전제: Isaac Sim 6.0.1 standalone, 호스트당 동시 1인스턴스(RAM),
헤드리스 서버는 WebRTC 스트리밍으로 관전. 상세는 각 디렉토리 README 참조.
