# results/

Fleet sweep 벤치마크·검증 산출물 (csv/png/npz). **기존 파일은 덮어쓰지 말고 새 이름으로** (이력 보존).
대체된 기준선·초기 산출물은 [`archive/`](archive/)에 있다 (2026-09-07 레거시 정리, S15P21A106-152 — git 이력은 이동으로 이어진다).

## 현재
| 파일 | 내용 | 지위 |
|---|---|---|
| `b0z_sweep.csv`, `b0z_cell_vs_heading.png`, `b0z_zone_metrics.png` | **B0″ 현재 기준선** — 동기화 맵(벽있음 ∪ v5.8) + 충전 존 기본 + TURN_TICKS=1, 칸 vs 헤딩 (`sweeps/fleet_sweep_b0z.py`) | 현재. [문서](../../docs/θ_경로_기준선.md#기준선-계보) |
| `load_sweep.csv`, `load_throughput.png`, `load_zone.png` | **고부하 스윕** — L1(80주문/25틱)·L2(120주문/15틱) × 8~28대, 칸 vs 헤딩 (`sweeps/fleet_sweep_load.py`) | 현재. [문서](../../docs/θ_경로_기준선.md#고부하-l1l2) |
| `load_sweep_eval.csv`, `load_throughput_eval.png`, `load_zone_eval.png`, `stall_load_r16_o120_g15_s102_heading.txt` | **평가 시드 기준선** — 같은 고부하 격자를 평가 시드 {101,102,103,104}로 (`SWEEP_SEEDS=... SWEEP_OUT=... sweeps/fleet_sweep_load.py`). **평가 시드 {101,103,104}는 2026-09-07 합의·계약 v2.3 §5** — θ 성과·B-5·견적 KPI는 이 시드로. 시드 102·16대·L2·헤딩 STALL 덤프 포함 | 현재. [문서](../../docs/θ_경로_기준선.md#시드-역할) |
| `theta_sweep.csv`, `theta_sweep_throughput.png`, `theta_sweep_gain.png`, `theta_sweep_cross.csv` | **B-5 θ 적용 스윕** (-149) — 8~28대 × L1/L2 × {neutral, theta_n, theta_24} × 평가 시드 {101,103,104}, 234행. 교차표 = 중립 N대를 처음 넘는 θ 최소 대수 (`sweeps/fleet_sweep_theta.py`). STALL 덤프 `stall_b5_L1_neutral_r14_*.txt`(스테이션 뒤 칸), `stall_b5_L2_neutral_r22_*.txt`(정면 교착) | 현재. [결과](../../docs/θ_경로_기준선.md#b-5-결과) |
| `b0z_sweep_v3.csv`·`*_v3.png`, `load_sweep_v3.csv`·`*_v3.png`, `load_sweep_eval_v3.csv`·`*_eval_v3.png` | **v3 기본값 재측정**(-177: 차선 gain 2 + 양보) — 같은 격자를 v3 기본으로. 칸 모델 행은 당시 차선이 칸에도 걸린 상태라 원본과 다름(-177 리뷰에서 헤딩 전용으로 고침) | 이력 |
| `b0z_sweep_v34.csv`·`*_v34.png`, `load_sweep_v34.csv`·`*_v34.png`, `load_sweep_eval_v34.csv`·`*_eval_v34.png` | **v3.4 기본값 재측정**(-203: + 회전 발자국 마스크, 2026-09-14) — 칸 모델 행은 원본 CSV 와 비트 동일(회전 없음), 헤딩 행만 바뀐다. 아래 "v3 → v3.4" 표 | 현재 |
| **`fleet_replay.html`** | **범용 리플레이 플레이어** — 브라우저로 열고 `isaac_export_<tag>/scene.json`·`trajectories.json`(`SIM_EXPORT_ISAAC=1`)을 선택/드래그하면 1 m 격자 위에서 틱 단위 재생(2칸 차체·방향·동작색·존·스테이션·완료 태스크 피드). 서버·파이썬 불필요, 데이터 미내장 | 도구 (-144) |

## archive/ — 대체된 산출물

생성 스크립트(`fleet_sweep.py`·`fleet_sweep_b1e.py`·`fleet_sweep_b0h.py`, `sim_v1_tasks.py`)는 -152에서 삭제됨 — 재생성하려면 git 이력(2026-09-06 이전)에서 꺼낸다.
`sweeps/fleet_sweep_b0z.py`는 B0′ 점선 비교용으로 `archive/b0h_sweep.csv`를 읽는다.

| 파일 | 내용 | 지위 |
|---|---|---|
| `b0z_sweep_map0831.csv`, `*_map0831.png` | 같은 구성을 8/31 맵 복사본 위에서 돈 중간 결과 (맵 동기화 효과 비교용) | 초기 |
| `b0h_sweep.csv`, `b0h_cell_vs_heading.png`, `b0h_heading_cost.png` | B0′ — 8/31 맵, 고정 홈 12칸, 회전 2틱 (`fleet_sweep_b0h.py`) | B0″로 대체 |
| `b1e_sweep.csv`, `b1e_astar_vs_pibt.png`, `fleet_sweep_v2_main.png` | B-1e — A*(sim_v1) vs PIBT(v1compat) + main 흐름, 8/31 맵 (`fleet_sweep_b1e.py`, pibt_main은 `--fixed-homes`) | A* 비교 이력 |
| `fleet_sweep_results.csv`, `fleet_sweep.png` | B-0 — sim_v1 단독 fleet 곡선 (`fleet_sweep.py`) | 초기 |
| `pibt_viewer.html` | PIBT MVP 데모 뷰어(8/31, 데이터 내장) — 범용 플레이어 `fleet_replay.html`로 대체 | 대체 |

## v3 → v3.4 (회전 발자국 마스크, S15P21A106-203) 헤딩 행 비교 — 2026-09-14

같은 격자·같은 시드를 v3 기본(`*_v3.csv`)과 v3.4 기본(`*_v34.csv`)으로. 값은 tasks/h 변화율(v3.4 ÷ v3 − 1).

| 스윕 | 헤딩 행 | 평균 | 중앙 | 범위 | STALL v3 → v3.4 |
|---|---|---|---|---|---|
| `b0z_sweep`(40주문, 2~16대 × 시드 42·7) | 16 | −0.0 % | −0.1 % | −6.5 ~ +3.1 % | 0 → 0 |
| `load_sweep`(L1·L2 × 8~28대 × 시드 42·7) | 22 | +0.5 % | −0.1 % | −7.7 ~ +7.3 % | 1 → 1 (28·42·L1 완주, **24·42·L1 새로 STALL** — 포장대 (40,82) 앞 6대 군집, 기존 라이브니스 결함 부류·B3) |
| `load_sweep_eval`(같은 격자 × 시드 101·102·103·104) | 46 | −1.1 % | −0.5 % | −8.6 ~ +4.8 % | **2 → 0** (12·102·L1, 20·102·L1 완주) |

기준값(`base 6 40 42 1`): 2822/133.9 → 2889/130.8(−2.3 %). STALL 재현 3건(exp 16·14·22) 완주 340.9 / 281.6 / 411.8 (v3 351.4 / 259.0 / 416.9).
6,000건/6h 출고+입고(`in,out,out`, θ r24, 워커 조건) — v3 에서 입고 × 차선·양보 교착이던 3건: 12대·s101 완료 2,334 → **4,460**(용량 한계, 정체 경고 6 → 0),
24대·s103 3,992 → **5,926 / 5,944**(정체 경고 6 → 0), 28대·s103 4,264 → **5,923 / 5,944**(양보 582 → 8, 경고 0 → 1). 마스크가 랙 옆 줄에서 랙 쪽으로 코를 돌리는
회전을 막자 그 교착 패턴이 사라졌다 — B4 진단의 출발점. 재현: `docs/2026-09-13_S15P21A106-203_회전발자국마스크_설계.md` §8 표의 명령에 기본값 그대로.
