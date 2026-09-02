# 3_FMS — Fleet Management System (PIBT 통행 규칙 최적화)

FMS 파트는 두 트랙으로 나눠 진행한다.

| 트랙 | 담당 | 산출물 | 위치 |
|---|---|---|---|
| A안 | AI팀 | 창고 생김새 + 짐 흐름 + 운영 조건 → 통행 규칙 파라미터 θ(11개) | [`ai_theta/`](ai_theta/) |
| B안 | 알고리즘/엔지니어링팀 | PIBT 이동계층, θ → 통행 비용(from_theta), Fleet 벤치마크 | [`sim_engine/`](sim_engine/) |

두 트랙을 잇는 유일한 인터페이스는 **θ 11개 벡터**다. 스키마는 [`contracts/`](contracts/)에 고정해두고,
θ의 개수·순서·범위를 바꿀 때는 양쪽 합의가 먼저다.

상세 입출력 스펙: [`5_Docs/AI/AI입출력명세서.md`](../5_Docs/AI/AI입출력명세서.md)

## 구조

```
3_FMS/
├── contracts/     # A-B 공유 데이터 계약 (GuidanceInput / GuidanceTheta / Guidance)
├── ai_theta/      # A안 — 입력 텐서 → θ 예측 모델
└── sim_engine/    # B안 — PIBT 이동계층, from_theta, Fleet 벤치마크
```
