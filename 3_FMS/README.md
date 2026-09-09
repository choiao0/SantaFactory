# 3_FMS — Fleet Management System (PIBT 통행 규칙 최적화)

FMS 파트는 두 트랙으로 나눠 진행한다.

| 트랙 | 담당 | 산출물 | 위치 |
|---|---|---|---|
| A안 | AI팀 | 창고 생김새 + 짐 흐름 + 운영 조건 → 통행 규칙 파라미터 θ(11개) | [`ai_theta/`](ai_theta/) |
| B안 | 알고리즘/엔지니어링팀 | PIBT 이동계층, θ → 통행 비용, Fleet 벤치마크, **06 견적 계산 엔진** | [`sim_engine/`](sim_engine/) |

두 트랙을 잇는 인터페이스는 둘이다 — **θ 11개 벡터**([`contracts/guidance_types.py`](contracts/guidance_types.py))와
**시뮬 실행 계약**([`contracts/SIM_RUN_CONTRACT.md`](contracts/SIM_RUN_CONTRACT.md): θ 탐색 워커·견적 엔진이 `sim_v2`를 부르는 방법).
θ 스키마는 [`contracts/`](contracts/)에 고정해두고,
θ의 개수·순서·범위를 바꿀 때는 양쪽 합의가 먼저다.

상세 입출력 스펙: [`5_Docs/AI/AI입출력명세서.md`](../5_Docs/AI/AI입출력명세서.md)

## 구조

```
3_FMS/
├── contracts/     # A-B 공유 데이터 계약 (GuidanceInput / GuidanceTheta / Guidance)
├── ai_theta/      # A안 — 입력 텐서 → θ 예측 모델
├── sim_engine/    # B안 — PIBT 이동계층, from_theta, Fleet 벤치마크·견적 엔진 기반
├── map/           # FMS 공식 맵·스테이션·충전 존과 동기화 도구
├── infra/         # θ 탐색 워커·견적 워커·EMQX 브로커 구성과 산출 θ
├── host_orch/     # Sparkplug Primary Host + sim.verify 큐 소비자 (Isaac 검증 런 오케스트레이션, EC2 상시)
└── docs/          # 주제별 설계·결정·기준선과 작업 계획
```

주제별 설계 인덱스: [`docs/README.md`](docs/README.md)
