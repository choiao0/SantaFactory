# T3 — 창고 씬 빌더 (그리드 → Isaac USD)

"그리드가 곧 씬"이 원칙: 맵(`../t3_warehouse_map/map/`)의 occupancy grid와 랙 좌표를
그대로 Isaac USD 씬으로 세운다. DES와 SIL이 단일 소스를 공유하는 구조의 물리 실체.
콜라이더는 전부 그리드 rect에서 나오고, 에셋은 시각 전용이다.

## 파일 (2026-09-07 리팩토링 — 구현은 `../apps/`·`../sil_isaac/`·`../scene_builder/`·`../sil_ros/`, 이 폴더의 .py 는 옛 경로 셔임)

| 파일 | 역할 |
|---|---|
| `build_scene.py` | 씬 빌더 엔트리 셔임 → `../apps/build_scene.py` (`scene_builder/` 패키지: config·prims·materials·building·roof·racks·stations·offices·vnv·shots·build) |
| `roof_structure.py` | 셔임 → `scene_builder/roof.py` (박공지붕·철골·H형강 기둥, 치수 상수는 `scene_builder/config.py`) |
| `warehouse_scene.usd` | 산출 씬 — 커밋본 그대로 열림 (에셋은 NVIDIA S3 원격 참조, 383KB) |
| `view_scene.py` | 셔임 → `../apps/view_scene.py` (WebRTC 관전 뷰어) |
| `http_stream.py` | 셔임 → `sil_isaac/viewer/http_stream.py` (TCP MJPEG :8211 — UDP 차단망 대응) |
| `export_replay.py` | 셔임 → `sil_ros/tools/export_replay.py` (맵 → `../isaac_export_t3/` 재생 데이터, isaac_replay 포맷) |
| `warehouse_sim.py` | **T3 본편** 셔임 → `../apps/warehouse_sim.py` (`sil_isaac/`: app·robot·sensors·ros2·viewer·scene·runtime). 씬 + iw.hub ×N + 물리 라이다, ROS2 개통. `WSIM_N=3`이면 `/amr01~03/…` 네임스페이스 |
| `ros2/multi_check.py` | 다중 로봇 개통 검증 — 로봇별 odom·scan·/clock 발행률, /tf 프레임, 지정 로봇만 이동하는지 확인(JSON + exit code) |
| `ros2/` | AMCL + map_server + foxglove_bridge 런치·파라미터는 그대로. `patrol.py`·`multi_check.py` 는 셔임 → `sil_ros/nodes/` |
| `out/scene_*.png` | 검수 스크린샷 (외관·트러스·통로·스테이션·사무실 등) |

## 실행

```bash
# 씬 열람만 (빌드 불필요 — 커밋된 usd 사용)
cd <isaacsim> && ./python.sh <repo>/2_Simulation/t3_warehouse/view_scene.py
# 접속: Isaac Sim WebRTC Streaming Client → 서버 IP (동시 1인스턴스 주의)
# UDP 차단망(교육장 내부망 — tailscale이 DERP/TCP 릴레이로 떨어지는 환경)에서는
# WebRTC 대신 브라우저로 http://<서버IP>:8211/  (TCP MJPEG ~6fps, 관전 전용)

# 씬 재생성 (맵 산출물 갱신 시)
cd <repo>/2_Simulation/t3_warehouse_map/map && python warehouse_layout_v5_5_final.py
cd <isaacsim> && ./python.sh <repo>/2_Simulation/t3_warehouse/build_scene.py
```

## 구성 요소

- **건물** (설계도 DXF 치수선 실측): 처마 +9.0m, 박공지붕 i=15%(릿지면 ~+14.5m),
  K1 트러스 15프레임(6m 간격) + 퍼린 + 단부 X-브레이싱, 릿지 환기 모니터 4.5m,
  릿지 지지 H형강 기둥 12개(+11.0m, columns.npy 실기둥 중심). 외벽 샌드위치 패널
- **랙** (rack_units, 세로형 더블로우): NVIDIA 랙 부품 z 90° 회전 조립, 빔 2단
  (1.35/2.7 — 층간 여유 0.97m로 화물 관통 원천 차단)
- **화물** (운영 모델): 바닥 파렛트 밴드(셀값 6)는 랩핑 재고 더미 최대 4단,
  랙은 피킹 낱박스 1,923점(슬롯별 채움 45~90% 편차) — 결정적 의사난수 배치
- **스테이션**: 작업대 16개소 = 투명 그리드 콜라이더 + `packing_table` 에셋
  (내장 콜라이더 비활성 — 콜라이더 단일 소스 유지), 지게차 1대(인바운드 밴드)
- **사무실 2개소**: 파티션·모니터·철제 책상·강관 의자·캐비닛·마커보드 등 가구
  186점 (시각 전용, V&V에서 사무실 마스크 제외)
- **충전 스테이션 6기** (stations.json charger): 동벽 벽걸이 캐비닛·LED·베이 도장 —
  도킹 셀은 자유 공간이라 실물은 벽 팽창역 안 시각 전용(collide=False)
- **도어 4개소** (서·동 박공벽): 롤업 셔터 **폐쇄 상태** + 하우징·잼 포스트·상부 메꿈.
  그리드의 문 구간이 벽 라미나로 봉인돼 있어(실측) 셔터 폐쇄가 콜라이더와 정확히
  일치 — 라이다에 문이 벽으로 잡히는 게 폐쇄 셔터의 실제 물리
- **스테이션 앵커 46개**: stations.json 전 지점 = `/World/anchors/<type>_<i>` Xform.
  재생기·warehouse_sim·FMS가 좌표를 씬에서 직접 질의하는 표준 통로
- 설계도의 메자닌(+4.5m)은 **범위 외 확정** — 지지 기둥이 그리드(2D 단일 소스)를
  바꾸므로 미구현. AMR은 지면 주행·라이다 밴드 z 0.2~1.2라 운영상 무관
- **V&V**: `isaacsim.asset.gen.omap`으로 씬→점유맵 역생성 후 원 그리드와 diff —
  현행: 벽·컨베이어·작업대·파렛트 재현율 100.0% · 랙 풋프린트 점유 93.3% ·
  풋프린트 밖 오검출 0셀. 빌드 시 자동 실행

## 재생 (그리드 시뮬 검증 재생기 연동)

`../isaac_replay.py`(재생기)의 홈서버 확장 — 실물 씬 안에서 궤적 재생 + WebRTC:

```bash
./python.sh 2_Simulation/isaac_replay.py --export-dir 2_Simulation/isaac_export_t3 \
    --stage 2_Simulation/t3_warehouse/warehouse_scene.usd --livestream --loop
```

- `../isaac_export_t3/`는 `export_replay.py` 산출(스테이션 미션 6건, A* 침범 0 자가검증)
- sim_v1 익스포트를 쓰려면 `--export-dir`만 바꾸면 됨 (포맷 동일)

## ROS2 — 라이다 · localization (T3 본편 1단계, 개통 완료)

AMR 내부 = ROS2 원칙(외부는 VDA5050/MQTT 예정). 물리 레이캐스트 라이다(720빔
0.5° 0.4~20m — 콜라이더 기준이라 map.pgm과 원천 일치)로 AMCL이 우리 맵 위에서
실시간 추적한다(개통 검증: 회전·직진 중 오차 0.1~0.4m, 70회 갱신).

```bash
# 1) 시뮬 (Isaac — ROS2 소싱 필수)
source /opt/ros/humble/setup.bash
cd <isaacsim> && ./python.sh <repo>/2_Simulation/t3_warehouse/warehouse_sim.py
# 2) localization (별도 셸)
source /opt/ros/humble/setup.bash
ros2 launch <repo>/2_Simulation/t3_warehouse/ros2/loc.launch.py
# 3) 조종: ros2 run teleop_twist_keyboard teleop_twist_keyboard
#    또는 자동 순회 데모: python3 <repo>/2_Simulation/t3_warehouse/ros2/patrol.py
#    (스테이션 그랜드 투어 A* 무한 순회 + AMCL 오차 로그)
#    재시드: /initialpose 발행 (Foxglove의 Pose Estimate 버튼도 가능)
```

시각화(전부 TCP — UDP 차단망 통과):
- **Foxglove**: https://app.foxglove.dev → Open connection → `ws://<서버IP>:8765`
  (/map + /scan + /amcl_pose + /particle_cloud + TF 표준 패널)
- **3D 관전**: 브라우저 `http://<서버IP>:8211/` (MJPEG) 또는 WebRTC 클라이언트

iw.hub 에셋 주의(6.0.1 실측): 섀시·캐스터 Collision 스케일이 ×100 깨져 있어
warehouse_sim.py가 런타임 수술(깨진 콜리전 비활성 + 자체 하부 재구성)을 한다.
바퀴 실측 반경 0.08m·트랙 0.58m — T1의 0.115/0.413은 오류였음. 물리 센서는
반드시 리지드바디 링크(chassis) 밑에 부착(루트 Xform은 시뮬 중 동결).

## 다중 로봇 (2026-09-06)

`warehouse_sim.py`는 환경변수로 로봇 수를 정한다. 로봇마다 스폰·수술·라이다·ROS2 그래프를 따로 만들고 `/clock`은 1번 로봇만 낸다.

| 환경변수 | 기본 | 뜻 |
|---|---|---|
| `WSIM_N` | 1 | 로봇 수. 2 이상이면 네임스페이스 모드 |
| `WSIM_NS` | auto | N=1에서도 네임스페이스를 강제(1)하거나 해제(0) |
| `WSIM_SPACING` | 3.0 | 스폰 간격 [m]. 남측 코리도 (36.0, 40.8)부터 +x (x 36~60 구간 장애물 이격 ≥ 3.9 m) |
| `WSIM_SPAWN` | — | `"x,y;x,y;…"`로 직접 지정(개수 = N) |

이름 규칙: 프림 `/World/amr01`, 토픽 `/amr01/{cmd_vel,odom,scan}`, 프레임 `amr01/{odom,base_link,laser}`.
`../t4_agent/` `agent.launch.py serial:=amr01`의 기본 토픽과 같아서 `flat_topics` 없이 붙는다. 단일 모드(기본)는 예전 그대로 `/World/iw_hub` · `/odom` · `/cmd_vel`이라 `loc.launch.py`·`patrol.py`가 그대로 돈다.

```bash
cd <isaacsim> && WSIM_N=3 ./python.sh <repo>/2_Simulation/t3_warehouse/warehouse_sim.py     # 3대
source /opt/ros/humble/setup.bash && python3 <repo>/2_Simulation/t3_warehouse/ros2/multi_check.py --n 3 --drive amr02
```

개통 검증(9/6, 원본 렌더 구성, 창고 씬): N=1 평면 토픽 57 Hz · 0.83 m 이동(회귀 동일) / N=3 로봇별 40 Hz · 720빔 유효 · amr02만 0.58 m 이동, 나머지 0.000 m.
3대에서 프레임이 40 fps(RTF ≈ 0.66)로 떨어지므로 검증 런은 경량 구성으로 돌리거나 배리어 틱이 시뮬 시각 기준임을 FMS 파트와 맞춘다.

## 남은 것 (T3 본편 다음 단계)

경로 추종은 `../t4_agent/`의 그리드 프리미티브 컨트롤러가 맡는다(개루프 직진의 슬립 비대칭 휨은 셀 단위 폐루프가 흡수).
스테이션 왕복 order 연쇄, 리프트 도킹 1장면, 사이클 타임 분해 + 도킹 시간 분포
실측(DES 환류), 오돔 노이즈 주입(현재는 정답 오돔이라 AMCL alpha 최소 설정).
