# 1_Robot — 로봇 쪽 소프트웨어

GPU 서버(Isaac)와 나중의 실기(實機) 양쪽에 **같은 코드로** 올라가는 것들. 시뮬(2_Simulation)·FMS(3_FMS)와 배포 단위를 분리한다.

| 디렉토리 | 내용 | 상태 |
|---|---|---|
| [`amr_agent/`](amr_agent/) | ROS 2 Humble AMR 에이전트 — VDA 5050 MQTT 브리지 · order executor · 그리드 프리미티브 컨트롤러 · fake robot/FMS. 동작 값은 **기종 프로파일 + BE 파라미터**로 결정 | 2026-09-11 `2_Simulation/t4_agent` 에서 이동, 프로파일 3층 도입 |

다음: GPU 서버에 올라가는 요소(에이전트 · sim-runner · Isaac 런처)를 컨테이너로 묶어 관리 — 에이전트가 첫 대상.
