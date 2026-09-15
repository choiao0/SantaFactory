"""t3_amr 엣지 — Sparkplug B 노드 `sim-runner-gpu01` 로 상주하며 host-orch 의 NCMD Start 를 받아 Isaac 녹화를 돌린다.

경로: host-orch(EC2) --NCMD Start--> 여기 --run_record.sh--> Isaac(같은 컨테이너) --mp4--> MinIO --NDATA Runner/VideoUrl--> host-orch
계약: 3_FMS/contracts/MQTT_CONTRACT.md §5 (메트릭 사전·NCMD·세션 규칙), SIM_VERIFY_CONTRACT.md §2·§3.

219 로 지운 `2_Simulation/sim_runner`(마지막 커밋 ac10c76)에서 코덱(spb)·세션(EdgeSession)·텔레메트리·MQTT 연결부를 되살렸고,
에이전트 ×N + Isaac 을 띄우던 런처 대신 `run_record.sh` 하나를 띄우는 `recorder` 와 `upload` 를 새로 붙였다.
로봇 디바이스(DBIRTH/DDATA)는 내지 않는다 — t3_amr 은 로봇을 Isaac 안에서 직접 구동하므로 ROS 2 에이전트가 없다.
"""
