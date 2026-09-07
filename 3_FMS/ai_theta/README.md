# ai_theta/ — A안 (AI팀)

창고 생김새(18ch) + 짐 흐름(6ch) + 통로 구조(15ch) + 운영 조건(9개) → 통행 규칙 파라미터 θ 11개(연속 8 + 범주형 3)를 예측한다.

입출력 계약: [`../contracts/guidance_types.py`](../contracts/guidance_types.py) (`GuidanceInput` → `GuidanceTheta`)
상세 스펙: [`5_Docs/AI/AI입출력명세서.md`](../../5_Docs/AI/AI입출력명세서.md)

| 파일/디렉토리 | 내용 | 상태 |
|---|---|---|
| [`theta_fixtures.py`](theta_fixtures.py) | 규칙별 θ 검증 세트 + 기대 히트맵 (`from_theta` 배관 확인용) | 세트 10개 |
| [`tests/`](tests/) | 세트를 실제 `from_theta` 출력과 대조 | 테스트 10개 |
| [`data/`](data/) | 창고 + 운영조건 → `GuidanceInput` (39채널 + 운영조건 9) | `build_input.py`, 테스트 22개 |
| [`train/`](train/) | θ 회귀(연속 8) + 분류(범주형 3) 학습 스크립트 | 비어있음 |
| [`experiments/`](experiments/) | θ 감도 실험 (`theta_sensitivity.py`, `--from-csv` 로 시뮬 없이 재판정) · 대수별 θ 검증 (`eval_fleet.py`, 탐색/평가 시드 분리) | 케이스 17개 |
| [`results/`](results/) | 실험 산출물 CSV (기존 결과 덮어쓰기 금지) | |

## theta_fixtures.py

각 세트는 `GuidanceTheta.neutral()`에서 **규칙 하나만** 켠다. 나머지 배율이 전부
1.0이므로 히트맵에 나타난 패턴을 그 규칙 탓으로 특정할 수 있다.

```bash
python ai_theta/theta_fixtures.py           # 세트 10개와 기대 결과를 표로 출력
python ai_theta/tests/test_theta_fixtures.py # 실제 from_theta 출력과 대조
```

`from_theta` 자체의 성질 검산(중립 uniform / 포화 없음 / 배타 규칙 / station
`entry_dir` / 교차로 경계)은 [`../sim_engine/from_theta_demo.py`](../sim_engine/from_theta_demo.py)가
이미 `[1]`~`[5]`로 수행한다. 이쪽은 그 데모가 다루지 않는 **범주형 3개**
(`aisle_period`, `aisle_phase`, `loop_dir`)를 기본값 이외의 값으로 검증한다.
데모는 세 값을 전부 neutral 기본값(1 / 0 / 0)으로만 쓴다.

### 격리의 한계 — 읽기 전에 알아야 할 것

배타 순서는 θ 값이 아니라 **기하**로 판정된다. 간선이 상위 그룹 마스크에 걸리면
그 배율이 중립 1.0이어도 "적용됨"으로 표시되고 뒤 그룹은 건너뛴다.

```
선점 순서: station_spur > loop > intersection_entry > aisle_interior
```

따라서 상위 그룹이 선점한 간선에서는 격리한 규칙의 효과가 **아예 보이지 않는다.**
히트맵에 "몇몇 간선만 1.0으로 남았다"면 버그가 아니라 이 선점일 수 있다.
실측 wallA에서는 `LOOP_ONEWAY_*` 세트가 셀 1개(43,93)에서 여기 해당한다.
