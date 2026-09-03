# data/ — AI 입력 텐서 생성 (S15P21A106-134)

창고 + 운영조건 → `GuidanceInput` (명세 §8: 생김새 18 + 짐 흐름 6 + 통로 구조 15 = 39채널, 운영조건 9).

```bash
# 3_FMS/ 에서
python ai_theta/data/build_input.py            # 39채널 요약표 출력 (로봇 10 · 주문 40)
python ai_theta/tests/test_build_input.py      # 22 tests
```

```python
from ai_theta.data.build_input import build_guidance_input, stack_channels
inp = build_guidance_input(n_agents=30, order_rate=200)   # → GuidanceInput
x = stack_channels(inp)                                     # (39, H, W)
```

| 파일 | 내용 |
|---|---|
| `build_input.py` | 채널 생성 전부. `build_static_map` / `build_task_profile` / `build_topology_tensor` / `build_scenario` |

## 설계 결정 — 토폴로지는 `from_theta.extract_topology()` 재사용

명세 §6-3은 통로·순환로·진입 방향을 **규칙 기반으로 자동 추출**하라고 한다. 지금은
그렇게 하지 않고 `sim_engine/from_theta.py`의 wallA 좌표 기반 추출을 그대로 쓴다. 이유 둘.

**1. 일반 규칙을 구현해봤는데 이 맵에서 깨졌다.**
run length로 통로 축 판정 → 연결성분으로 묶기 → 폭 임계로 큰 통로 → 영역을 가두는
성분이 순환로, 이렇게 짰다. 도달 불가 구역(벽으로 막힌 남·북)을 걸러낸 뒤에도
**세로 통로 50개(기대 11), 순환로 0개**. 북쪽 개방 구역이 큰 통로로 잡혀 링이 안 닫힌다.
임계값 조정으로 넘길 문제가 아니라 규칙 자체를 더 설계해야 한다.

**2. AI가 배우는 구조와 실제 비용을 만드는 구조가 같아야 한다.**
`from_theta`가 wallA 좌표로 토폴로지를 뽑아 비용을 만드는데, AI 입력이 다른 추출기로
다른 토폴로지를 보면 학습이 무의미하다. `test_topology_channels_match_from_theta`가
이걸 못 박는다. 맵 로더도 `map_loader.load_map`을 그대로 써서 격자가 어긋나지 않게 했다
(`docs/2026-09-03_맵버전_동기화_결정.md` 결정 5).

**대가: 현재 wallA 맵 전용.** 새 창고 일반화는 합성 창고 도입(S15P21A106-128)과 함께
`from_theta`의 토폴로지 추출을 같이 일반화해야 한다.

## 채널별 근거

| 채널 | 출처 | 비고 |
|---|---|---|
| 0~1 obstacle / walkable | `map_loader.load_map` | 합 = 전체 칸 |
| 2 main_aisle | `topo.main_aisle` | 남·북 밴드 (from_theta 정의) |
| 3 sub_aisle | 세로 통로 ∧ ¬main | 랙 사이 11개 × 57칸 |
| 4 intersection | `topo.junction` | 통로 목 66칸 |
| 5 station | `topo.station` | 충전기·충전대기열 **제외** (§4 "작업하는 자리") |
| 6~12 zone_* | 스테이션 종류 매핑 `ZONE_STATION_KINDS` | ⚠️ 아래 |
| 12 zone_charging | + `3_FMS/map/charge_zone.json` 사각형 | 130 결정 반영 |
| 13 degree | free 이웃 수 ÷ 4 | |
| 14~17 dist_* | BFS ÷ 창고 대각선 (§9) | 도달 불가·비통행 = 1.0 |
| 18~19 pickup / dropoff | `od_distribution` | 합 1 |
| 20~23 demand_dir | 모든 최단경로에 확률 균등 분배 | 전체 합 1 (§5-2) |
| 24 세로 통로 | `v_aisle_rank ≥ 0` | |
| 25 가로 통로 | `main_aisle ∧ ¬세로` | 남·북 밴드 |
| 26 통로 번호 | `rank ÷ max_rank` (§9) | |
| 27~31 순환로 + 방향 | `loop_fwd` | |
| 32~35 진입 방향 | `station_dir` | **station → 통로** 방향 (합의안 '규약 주의') |
| 36~38 rank_mod | `rank % 2`, `% 3` | §6-2 |

## 짐 흐름은 `sim_v2`의 주문 규칙과 같다

`od_distribution()`은 `sim_v2_tasks.py`의 `spawn_order` / `spawn_inbound`를 그대로 따른다.

```
출고  aisle_buf[a] → packing[p]     a·p 균등,  가중 1.660 (주문당 기대 태스크 수)
입고  inbound_buf[i] → aisle_buf[a] i·a 균등,  가중 1.0
```

시뮬 규칙이 바뀌면 여기도 바꿔야 한다. 어긋나면 `task_profile`이 시뮬이 실제로 만드는
흐름과 다른 것을 말한다.

## 알아야 할 것 2개

**demand_dir이 동쪽으로 치우쳐 있다 (E 0.58 / W 0.06).** 버그가 아니다.
`inbound_buf`(열 24) → `aisle_buf`(평균 열 65) → `packing`(평균 열 76)으로 전부 동쪽이고,
명세 §5-2가 **적재 구간만** 세기 때문이다. 공차 복귀는 안 센다. 명세 §11-4가 "로봇은
왕복한다"고 경고하는 그 비대칭이다. 실제 트래픽은 이보다 균형 잡혀 있다. 복귀 구간을
넣을지는 명세 변경 사안이라 여기서 정하지 않았다.

**구역 채널(6~12)은 스테이션 칸 단위다.** 명세가 "구역"이라 하지만 지금 자산으로는
스테이션 좌표뿐이라 칸 몇 개씩이다 (`zone_receiving` 2칸). `qc`→검수, `returns`→출고
매핑은 이름에서 유추했다 — **팀 확인 필요.** `2_Simulation/.../zones.json`(랙 22존)으로
`zone_storage`를 면으로 채우는 건 후속.
