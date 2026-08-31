# ai_theta/ — A안 (AI팀)

창고 생김새(18ch) + 짐 흐름(6ch) + 통로 구조(15ch) + 운영 조건(9개) → 통행 규칙 파라미터 θ 11개(연속 8 + 범주형 3)를 예측한다.

입출력 계약: [`../contracts/guidance_types.py`](../contracts/guidance_types.py) (`GuidanceInput` → `GuidanceTheta`)
상세 스펙: [`7_Docs/AI/AI입출력명세서.md`](../../7_Docs/AI/AI입출력명세서.md)

| 디렉토리 | 내용 | 상태 |
|---|---|---|
| [`data/`](data/) | 39채널 학습 텐서 생성·저장 | 비어있음 |
| [`train/`](train/) | θ 회귀(연속 8) + 분류(범주형 3) 학습 스크립트 | 비어있음 |
