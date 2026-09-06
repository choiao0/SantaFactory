# 2_Simulation — SIL 검증 트랙 (ROS2 x Isaac Sim)

SimPy DES가 낸 "최적 구성"이 실제 로봇 스택에서 성립하는지 검증하는 계층.
로드맵: T1 텔레옵 → T2 매핑·추종 → **T3 창고 씬(현 위치)** → T4 멀티+FMS.

| 디렉토리 | 내용 | 상태 |
|---|---|---|
| [`t1_teleop/`](t1_teleop/) | iw.hub 텔레옵 — Isaac x ROS2 브리지 개통, 가감속 실측 | 완료 |
| [`t3_warehouse_map/`](t3_warehouse_map/) | 설계도 DXF → occupancy grid + stations.json·zones.json (v6.0 구역제 A~V 22구역, 단일 소스) | 완료 |
| [`t3_warehouse/`](t3_warehouse/) | 그리드 → Isaac USD 씬 (건물 실측·화물·omap V&V) + iw.hub ×N·물리 라이다·AMCL 개통(`WSIM_N`으로 `/amr01~/…` 네임스페이스) | 완료 |
| [`calibration/turn_probe/`](calibration/turn_probe/) | iw.hub 스팟턴 실측 — 회전 중심 = 구동축 = 포즈 원점, 차체 앞 0.40 m·뒤 1.03 m(뒤 칸 1개 점유, 스윙 반경 1.09 m), 90° 폐루프 1.9 s → FMS 헤딩 상수 | 완료 (9/6) |
| `isaac_replay.py` + `isaac_export_t3/` | 그리드 시뮬 궤적을 실물 씬에서 재생 (WebRTC) | 도구 |

공통 전제: Isaac Sim 6.0.1 standalone, 헤드리스 서버는 WebRTC 또는 TCP MJPEG(:8211)로 관전.
동시 실행(2026-09-05 실측, RTX 5080 16GB·RAM 64GB): 원본 구성은 인스턴스당 RAM 8.1GB·VRAM 5.3GB로 2개까지,
렌더·시각화를 끈 경량 구성은 RAM 7GB·VRAM 2.3GB로 6개 동시 정상(RTF 1.25). 상세는 각 디렉토리 README 참조.
