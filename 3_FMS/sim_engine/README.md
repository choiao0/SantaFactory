# sim_engine/ — B안 (알고리즘/엔지니어링팀)

PIBT 이동계층 + θ → 통행 비용 변환(`from_theta`) + Fleet 벤치마크.

입출력 계약: [`../contracts/guidance_types.py`](../contracts/guidance_types.py) (`GuidanceTheta` → `Guidance`)

## 진행 순서 (B트랙 실행 핸드오프 v1 기준)

1. **B-0** 기준선 재확정 — 로봇 속도 1.0 m/s 단일 확정, 기존 시뮬레이션 재실행
2. **B-1** 시공간 A* → PIBT 교체 (충돌 해소 priority inheritance + backtracking, 데드락 회귀 테스트)
3. **B-2** `from_theta()` 배관 — 더미 θ로 우선 검증, A안 모델 완성과 무관하게 착수 가능
4. **B-5** θ 적용 Fleet Sweep 재실측

기존 시뮬레이션 코드(이동계층 A* 등)를 아직 이 저장소로 옮기지 않았다면, 실제 코드 위치부터 확인할 것.

| 디렉토리 | 내용 | 상태 |
|---|---|---|
| [`results/`](results/) | Fleet sweep 벤치마크 결과 (csv/png) | 비어있음 |
