# 3_FMS/docs

현재 유효한 FMS 설계와 실측을 주제별 문서 7개로 정리한다. 날짜 기록은 원문 근거로 로컬에
보관하지만 git 추적 대상이 아니며, 새 링크는 아래 문서의 구체적인 절을 가리킨다.

## 주제 문서

### [이동계층 PIBT](이동계층_PIBT.md)

Isaac 회전 충돌과 셀 확대 기각부터 `(칸,방향)` 상태, 2칸 점유, 회전 스윙 예약을 설명한다.
가중 다익스트라·성능 최적화, 다중 칸 충돌과 우선순위, 라이브니스 장치 5종을 모았다.
STALL 재현 3건과 아직 구현 전인 정면 조우 양보 후보, 관련 검증 명령도 이 문서에 있다.

### [커널·시뮬 구조](커널_시뮬_구조.md)

현재 `sim_engine` 패키지 구조와 틱 루프, 로봇 상태머신, 태스크 흐름·배차 규칙을 설명한다.
`FmsKernel` 인터페이스, SimPy의 고정 시간·교대·배터리 도크, Isaac 내보내기를 모았다.
Lifelong MAPF 해석, ROS/Isaac 연결 순서와 계약 기준값 3개를 확인할 수 있다.

### [맵·충전 존](맵_충전존.md)

계획 격자 1.0 m 결정과 FMS·Isaac 맵 불일치, 보수적 정답지 생성·동기화 절차를 설명한다.
동쪽 충전 존의 좌표·용량·대안·위험, 초기 배치와 최근접 복귀·재선택 규칙을 모았다.
존 지표 5종, 2번째 존 폐기 근거와 맵·존 검증 명령을 확인할 수 있다.

### [θ 경로와 기준선](θ_경로_기준선.md)

θ 11개 스키마와 비용 규약, `from_theta`의 배타 조립·가중 거리장 연결을 설명한다.
감도 결론과 시드 역할, B0→B0′→B0″ 계보, 고부하·대수별 θ·B-5 수치를 모았다.
3~4대 절감, wallA 대수 축 θ 한 벌 판정과 견적 엔진 입력·results 파일 지도가 있다.

### [견적 워커](견적_워커.md)

백엔드 큐 명세 v0.3을 우리 커널에 붙이는 방법: 요청 필드 → 시뮬 인자, SUMMARY → KPI 14키, 실패 처리, 배포 자리.
백엔드와 맞출 항목(대수 상한 8, 시드 42, 가동률 정의)을 모았다. 이슈 S15P21A106-155.

### [주문 생성기](주문_생성기.md)

신발 창고 공개 데이터(Mendeley pf2w725pw3)에서 라인 수·수량·SKU 편중·웨이브 시각 분포를 추출해 우리 매장·상품·랙 위에
하루치 `outbound[]`(명세 §1-1 형식)를 만든다. 릴리스 기본 웨이브, ABC 는 인기 가중치만, 입고 보류. 이슈 S15P21A106-153.

### [남은 과업 계획](남은과업_계획.md)

실행 순서와 지라 초안 13건을 유지하고 ⑤ 레거시, ⑥ 코드 분리, ⑦ 문서 정리를 완료 표시했다.
A트랙 요청과 진행 규칙, 완료된 코드 분리 결과를 짧게 정리했다.
부록에는 θ 로드맵, 아키텍처 수정 5개, API 계약 7항목을 견적 엔진 설계 입력으로 모았다.

## 추적 유지하는 날짜 기록

아래 날짜 문서는 gitignore 예외로 계속 git으로 추적한다. 앞 셋은 견적 엔진 설계(⑧)의 입력이고,
뒤 셋은 A트랙이 작성한 원문이라 B트랙이 임의로 빼지 않는다.

- [백엔드 ↔ AI API 계약 검토](2026-08-31_백엔드AI_API계약_검토.md) — 응답 스키마 원본 [api_response_schema_v1.html](api_response_schema_v1.html)도 함께 추적
- [θ 실험 로드맵](2026-09-04_θ_실험_로드맵_AB공동.md)
- [시스템 아키텍처 검토](2026-09-04_시스템아키텍처_검토_B트랙관점.md)
- [θ 감도 실험](2026-09-04_θ감도_실험.md) — A트랙
- [θ 탐색 대수별 결과](2026-09-04_θ탐색_대수별_결과.md) — A트랙
- [θ 탐색 예산 측정](2026-09-04_θ탐색_예산_측정.md) — A트랙

## 기준값과 시드

### 기준값 3개

`3_FMS/sim_engine`에서 `SIM_NO_PLOT=1`로 실행한다.

| 모델·조건 | 호출 뒤 인자 | makespan | tasks/h |
|---|---|---:|---:|
| v1compat | `base 6 40 42 1 --flow=v1compat` | 2317 | 186.4 |
| 칸 + 고정 홈 | `base 6 40 42 1 --cell --fixed-homes` | 2970 | 127.3 |
| 기본 헤딩 + 존 | `base 6 40 42 1` | 2850 | 132.6 |

### 시드 역할

| 역할 | 시드 | 용도 |
|---|---|---|
| 탐색 | 42, 43, 44 | BO가 θ 후보를 고를 때 |
| 평가 | **101, 103, 104** | θ 성과·B-5·방식 비교·견적 KPI |
| 예비 | 102 | 라이브니스 STALL 재현 |
| 동일성 기준 | 42, 7 | `b0z_sweep.csv`, `load_sweep.csv` 회귀 |

## 검증 커맨드

```bash
cd 3_FMS/sim_engine

# 코어·맵·θ
python checks/pibt_mvp_demo.py
python checks/pibt_heading_demo.py
python checks/pibt_smoke_real_map.py
python checks/from_theta_demo.py
python checks/pibt_dist_identity_check.py

# 기준값 3개
SIM_CHECK=1 SIM_NO_PLOT=1 python sim_v2_tasks.py base 6 40 42 1 --flow=v1compat
SIM_NO_PLOT=1 python sim_v2_tasks.py base 6 40 42 1 --cell --fixed-homes
SIM_CHECK=1 SIM_NO_PLOT=1 python sim_v2_tasks.py base 6 40 42 1

# 회귀·사건층·A트랙
python checks/check_results_identity.py --quick
python checks/check_lifelong_battery.py
python -m pytest ../ai_theta/tests ../contracts/tests -q
```

전수 기준선 비교는 `python checks/check_results_identity.py`로 실행한다.

## 로컬 기록 보관 정책

`docs/20*.md`와 날짜 그림 `docs/*.png`는 **로컬 보관이며 gitignore 대상**이다.
위 날짜 문서 6개와 HTML 스키마 원본만 예외 규칙으로 계속 추적한다. 주제 문서 끝의 “로컬 기록
2026-…_x.md §n” 목록은 결론의 원문 위치를 나타내며, 로컬 작업 트리에서는 그대로 열 수 있다.
