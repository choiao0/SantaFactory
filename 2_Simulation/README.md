# 2_Simulation — SIL 검증 트랙 (ROS2 x Isaac Sim)

SimPy DES가 낸 "최적 구성"이 실제 로봇 스택에서 성립하는지 검증하는 계층.
로드맵: T1 텔레옵 → T2 매핑·추종 → **T3 창고 씬(현 위치)** → T4 멀티+FMS.

| 디렉토리 | 내용 | 상태 |
|---|---|---|
| [`t1_teleop/`](t1_teleop/) | iw.hub 텔레옵 — Isaac x ROS2 브리지 개통, 가감속 실측 | 완료 |
| [`t3_warehouse_map/`](t3_warehouse_map/) | 설계도 DXF → occupancy grid (v5.9, 단일 소스) | 완료 |
| [`t3_warehouse/`](t3_warehouse/) | 그리드 → Isaac USD 씬 (건물 실측·화물·omap V&V) | 완료 |
| `isaac_replay.py` + `isaac_export_t3/` | 그리드 시뮬 궤적을 실물 씬에서 재생 (WebRTC) | 도구 |

공통 전제: Isaac Sim 6.0.1 standalone, 호스트당 동시 1인스턴스(RAM),
헤드리스 서버는 WebRTC 스트리밍으로 관전. 상세는 각 디렉토리 README 참조.
