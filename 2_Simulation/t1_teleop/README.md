# T1 — iw.hub 텔레옵 (Isaac Sim × ROS2 브리지 개통)

iw.hub 1대를 간단 씬(Grid)에 띄우고, ROS2 `/cmd_vel`로 구동하며 `/clock`·`/odom`을 발행한다.
SIL 로드맵 T1 — 스크립트 내장 주행을 ROS2 토픽 제어로 교체해 브리지 파이프라인을 개통한 것.

## 환경

- Isaac Sim 6.0.1 (standalone) + ROS2 Humble (시스템 설치)
- GPU 서버(RTX 5080)에서 헤드리스 실행, WebRTC 스트리밍으로 관전
- 브리지는 Isaac 기동 전 Humble 소싱만 하면 됨 (RMW 기본 = Fast DDS)

## 실행 (검증된 절차, 2026-08-27)

```bash
# 1) 시뮬 — Humble 소싱 후 Isaac 기동
source /opt/ros/humble/setup.bash
cd <isaacsim 설치 경로> && ./python.sh <repo>/2_Simulation/t1_teleop/teleop_sim.py
# "[t1_teleop] ready" 로그 후 조작 가능 (부팅 ~80초)

# 2) 키보드 조종 (서버 SSH 셸 어디서든)
source /opt/ros/humble/setup.bash
ros2 run teleop_twist_keyboard teleop_twist_keyboard   # i/j/l/, 이동 · k 정지

# 3) 관전 — Isaac Sim WebRTC Streaming Client → 서버 IP
```

- Isaac은 호스트당 동시 1인스턴스 (인스턴스당 RAM ~16GB — 2개면 32GB 초과 OOM 실측)
- 기동 전 기존 인스턴스 확인: `pgrep -f teleop_sim.py` — 이중 기동 시 스트리밍 포트(49100) 경합으로 접속 불가
- 스크립트 안전 클램프: 선속 1.2 m/s · 각속 1.5 rad/s / 추적 카메라(지수 평활) 내장

## 검증 결과 (2026-08-27 실측)

| 항목 | 결과 |
|---|---|
| 토픽 | /cmd_vel(구독) · /clock 185Hz · /odom 200Hz |
| 직진 | 0.8 m/s 명령 → 5.37m 주행, 횡편차 9mm |
| 회전 | +z 명령 → 좌회전(CCW), 쿼터니언 xyzw 변환 정확 |
| 정지 | 제로 트위스트 1발로 정지 |

## 가감속 실측 — DES 보정 환류 (`out/accel_step_max.csv`)

`measure_accel.py`(시스템 Humble python, rclpy)로 /odom을 기록하며 스텝 명령 인가.
타임스탬프는 시뮬 시간이라 실행 속도(RTF)와 무관.

| 항목 | 실측값 | 시사점 |
|---|---|---|
| 최고 속도 | **0.835 m/s** (명령 1.2에도 불구) | 에셋 휠 조인트 한계 추정(휠 7.27 rad/s) — 공식 스펙과의 괴리, 보정 루프 의제 |
| 가속 0→95% | 0.13 시뮬s (~6.0 m/s²) | 즉답형 응답 — 물리에 가속 램프 없음 |
| 감속 →0 | 0.12 시뮬s (~5.7 m/s²) | 동일 |

**핵심 발견**: 기본 물리 응답이 즉답형이므로, 실제 iw.hub의 가감속(통상 ≤1 m/s² 급)은
물리가 아니라 **명령 램프(컨트롤러 수준 가속 제한)**로 모델링해야 한다.
→ DES의 가감속 파라미터는 "물리 측정값"이 아니라 "램프 설정값" — T2 추종기부터 램프 적용.

## 파일

| 파일 | 역할 |
|---|---|
| `teleop_sim.py` | Isaac 쪽 — WheeledRobot 구동 + OmniGraph ROS2 브리지(SubscribeTwist·PublishClock·PublishOdometry) + 추적 카메라 |
| `measure_accel.py` | ROS2 쪽 — rclpy /odom 로거 → CSV + 요약 (가감속 실측) |
| `out/accel_step_max.csv` | 실측 결과 (t, x, y, speed) |

## 알아두면 좋은 것

- 브리지 기동 시 `[humble.rclpy] Could not import rclpy` 경고는 무해 — Isaac 내장 파이썬(3.12)과 Humble(3.10) 차이로, 브리지는 C++ 레벨로 동작
- livestream `StreamSdk ... INVALID_STATE` Fatal 로그는 클라이언트 미접속 상태의 소음 — 앱은 정상
- teleop_twist_keyboard는 키를 누를 때만 발행 — 로봇은 마지막 명령을 유지하므로 정지는 `k`
