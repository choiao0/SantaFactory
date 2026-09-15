# 2_Simulation — Isaac Sim 물리 검증 트랙

중심은 [`t3_amr/`](t3_amr/) 하나다 — iw.hub AMR 을 T3 창고 씬 위에서 계획·주행(ADG 연속 주행)시키고 처리량을 잰다.
맵(`t3_amr/warehouse/map/`, 3_FMS/map 과 정합)과 씬(`t3_amr/warehouse/scene/`)도 그 안에 있다. 사용법은 `t3_amr/README.md`.

## 2026-09-15 정리 (S15P21A106-219)

SIL 트랙(ROS 2 에이전트 + Isaac 브리지 + sim-runner)은 t3_amr 로 통일하면서 삭제했다:
`apps/ sil_isaac/ sil_ros/ sim_runner/ scene_builder/ t3_warehouse/ t3_warehouse_map/ t1_teleop/ t2_follower/ t2_mapping/
calibration/ isaac_export_t3/ tests/ isaac_replay.py`. 마지막으로 남아 있던 커밋은 `ac10c76` — 필요하면 거기서 꺼낸다.
host-orch 와의 통신(Sparkplug NBIRTH·Start/Stop)과 1_Robot ROS 2 연동은 t3_amr 에 새로 붙인다. 계약은
`3_FMS/contracts/MQTT_CONTRACT.md`·`SIM_VERIFY_CONTRACT.md`, Sparkplug 코덱 참조 구현은 `3_FMS/host_orch/spb.py`.

## 실측 상수 (FMS 인도용, 삭제된 `calibration/turn_probe` 결과)

- 회전 중심 = 구동축 = 포즈(/odom) 원점. 회전 중 원점 이탈 ≤ 1.3 cm.
- 차체: 축 기준 앞 0.40 m · 뒤 1.03 m · 폭 0.66 m → 1 m 격자에서 자기 칸 + 뒤 칸 1개 점유, 스팟턴 스윙 반경 1.09 m.
- 각속도: 지령 대비 95~97 %, 90° 폐루프 회전 1.9 s(T4 한계 1.2 rad/s), 1 m 직진 2.2 s(T4 E2E).
- 운동학: 바퀴 반경 0.08 m · 트랙 0.58 m. T1 의 옛 0.115/0.413 은 오류였고 그때의 0.835 m/s 상한은 그 결과다.
- 이후 연속 주행 기준 실측(2026-09-13, t3_amr)은 `3_FMS/contracts/SIM_RUN_CONTRACT.md` v4 머리에 있다: 칸당 1.193 s · 회전 1.450 s 하한.

공통 전제: Isaac Sim 6.0.1 standalone, 헤드리스 서버는 WebRTC 또는 TCP MJPEG 로 관전.
동시 실행(2026-09-05 실측, RTX 5080 16GB·RAM 64GB): 원본 구성은 인스턴스당 RAM 8.1GB·VRAM 5.3GB 로 2개까지,
렌더·시각화를 끈 경량 구성은 RAM 7GB·VRAM 2.3GB 로 6개 동시 정상(RTF 1.25).
