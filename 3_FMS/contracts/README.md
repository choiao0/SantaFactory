# contracts/

A안(AI)과 B안(PIBT 엔진)이 공유하는 데이터 계약. 여기 정의를 바꾸려면 양쪽 합의가 먼저다.

- `guidance_types.py` — `GuidanceInput` / `GuidanceTheta` / `Guidance` dataclass.
  출처: [`7_Docs/AI/AI입출력명세서.md`](../../7_Docs/AI/AI입출력명세서.md) §13 코드 계약.

θ의 개수·순서·의미가 바뀌면 데이터 버전도 함께 올린다 (명세서 §14-18).
