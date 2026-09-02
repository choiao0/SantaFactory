# B-2: from_theta() 배관 설계

작성일: 2026-09-01, v2 개정 2026-09-02 (§3·§6). 지라: S15P21A106-78 (다중 로봇 충돌·혼잡 회피 구현).
브랜치: `feature/S15P21A106-78-fms-fromtheta배관`.
근거: [B트랙_실행_핸드오프_v2.md](B트랙_실행_핸드오프_v2.md) §3 B-2,
AI입출력명세서 §11~13 (7_Docs/AI/).

## 0. 목적과 DoD

θ 11개(`GuidanceTheta`)를 칸별 통행 비용(`Guidance: edge_cost (H,W,4), wait_cost (H,W)`)으로
바꾸는 `from_theta()`를 구현하고 sim_v2에 연결한다.

**DoD (v1 핸드오프 그대로):** 더미 θ(특정 방향 극단 비용)를 넣었을 때
히트맵/방향별 흐름에서 회피(방향 분극)가 보일 것. 기본 실행(θ 없음)은
기존과 완전히 동일할 것 (B-1e 벤치마크 불변).

## 1. 배치 결정

| 항목 | 결정 | 이유 |
|---|---|---|
| 구현 위치 | `sim_engine/from_theta.py` (신규) | `contracts/`는 타입 전용 — 명세 §13도 from_theta를 "다음 단계 참고"로 계약 밖에 둠. 구현은 B트랙 소유 |
| 토폴로지 | 같은 파일에 wallA 전용 규칙 기반 추출 | A트랙 topology_tensor(15ch)는 스키마 합의 대기. from_theta에 필요한 최소 필드만 코드 규칙으로 추출 (명세 §14-11 "코드 규칙으로 자동 추출") |
| sim_v2 연결 | `--theta=<json경로>` 옵션. 없으면 uniform 1.0 | 기본 경로가 안 바뀌므로 v1compat rng 패리티·기존 벤치마크에 영향 0 |

## 2. wallA 토폴로지 정의 (1.0m coarse 격자, 좌표 실측 2026-09-01)

맵 107×116. r 증가 = 북, c 증가 = 동 (명세 §3).

| 필드 | 정의 | wallA 좌표 |
|---|---|---|
| `v_aisle_rank (H,W) int` | 세로 통로 번호 (서쪽부터 0) | 통로 k=0..10: 열 `c_k=int((35.1+6k+0.4)/1.0)` = 35,41,…,95의 ±1 (폭 3), 행 48~66 |
| `main_aisle (H,W) bool` | 큰 통로 (가로 간선 2개) | 남 밴드 r40~47, 북 밴드 r67~73 (free인 칸만) |
| `loop_fwd (H,W) int` | 외곽 순환로의 시계방향 접선 방향 (-1=순환로 아님) | 남 밴드=서(3), 북 밴드=동(1), 서 밴드 c20~31=북(0), 동 밴드 c99~108=남(2). 겹치는 코너는 가로 밴드가 우선 |
| `junction (H,W) bool` | 교차로 = 세로 통로가 가로 간선에 접속하는 목 | 통로 열 ±1 × 행 {47, 67} |
| `station_cells` | 흐름용 스테이션 도킹 칸 | `st_cell` 중 charger/charge_q 제외 전부 |

미사용으로 결정한 것:
- **가로 통로 rank** (명세 §12의 "가로 통로 그룹"): wallA의 가로 통로는 남/북 간선
  2개뿐이고 이들은 순환로(loop)의 위/아래 변과 동일하다. 같은 칸에 aisle_alt와
  loop를 겹쳐 걸면 효과가 곱으로 얽혀 해석 불가 → **가로 밴드는 loop+main_aisle
  전용, aisle_alt는 세로(랙 사이) 통로 전용**.
- r57의 폭 1 가로 컷(랙 중간 크로스컷)은 일반 칸으로 둔다 (특별 취급 없음).

## 3. θ → 비용 규칙 — **v2 개정 (2026-09-02, θ스키마 합의안 반영)**

근거: [2026-09-01_θ스키마_합의안.md](2026-09-01_θ스키마_합의안.md) "비용 조립 규칙",
`contracts/guidance_types.py` v2 (`EDGE_RULE_PRECEDENCE`, `EDGE_RULE_ALWAYS`, `COST_MIN/MAX`).
`edge_cost[r,c,d]` = (r,c)에서 방향 d로 **나가는** 간선. 아래 "간선 (u→v, d)"는 u에서 d로 v에 도달.

### 3-1. 조립 순서 (배타)

```
1. 모든 간선 1.0
2. 간선마다 아래 그룹 중 "가장 먼저 걸리는 하나"만 적용
     station_spur → loop → intersection_entry → aisle_interior
3. main_aisle_gain 은 독립 — 양 끝이 main_aisle 인 간선에 항상 곱
4. 마지막에 한 번만 [COST_MIN, COST_MAX] = [0.5, 5.0] clamp
```
v1 구현(모든 규칙 곱셈 중첩)은 `3.5×3.0×1.2 = 12.6`이 5.0으로 잘려 파라미터 식별이 불가했다.
배타 적용 후 최악 `3.5×1.2 = 4.2 < 5.0` — `max_realizable_edge_cost(θ)`로 데모에서 검산.

### 3-2. 그룹별 간선 조건 (wallA 토폴로지 기준)

| 그룹 | θ | 간선 조건 |
|---|---|---|
| station_spur | `station_in` | v가 도킹 칸이고 `d == (entry_dir[v]+2)%4` (통로 쪽에서 station 쪽으로 진입) |
| station_spur | `station_out` | u가 도킹 칸이고 `d == entry_dir[u]` (진입로를 되짚어 이탈 = 역주행) |
| loop | `loop_gain` | u, v 모두 순환로 칸이고 `d == (pref(u)+2)%4` (선호 순환방향의 정확한 역방향) |
| intersection_entry | `junction_penalty` | u는 교차로 아님, v는 교차로 (경계 진입 1회. 내부·이탈 간선 제외) |
| aisle_interior | `aisle_alt_boost` / `aisle_alt_gain` | u, v의 `aisle_id`가 같고(≥0) d가 통로 축(N/S)에 평행. 선호 방향(그룹0=북, 1=남) boost, 역방향 gain |
| (항상) | `main_aisle_gain` | u, v 모두 main_aisle (경계 진입 간선 제외) |
| — | `wait_cost` | `wait_cost[:,:] = θ.wait_cost` |

- 스퍼 길이: wallA의 도킹 칸은 전부 간선 밴드 위/인접이라 스퍼 = 도킹 칸 1개 → 합의안 미합의 항목
  "스퍼 전체 vs 마지막 간선 1개"가 이 맵에서는 같은 결과. 다른 맵에서 스퍼가 길어지면 재론.
- `station_out` 예외(walkable 이웃 ≤1인 station 미적용)는 wallA에 해당 없음 — 규칙은 구현해 둠.
- 대상 station: `st_cell` 중 charger/charge_q 제외 (홈은 작업자리가 아님). entry_dir을 못 정하면 미적용 + 경고.

### 3-3. `station_entry_dir` 추출 규칙 (명세 §6-3 "작업자리에서 가장 가까운 큰 통로 쪽", 코드 규칙)

1. 도킹 칸의 4방향 **인접** 칸에 non-free(벽·구조물)가 있으면 그 **반대** 방향.
   packing·induction·consol·vas (r40, 남쪽 r39 벽) → **N**. charger (동쪽 벽) → W.
2. 없으면 도킹 칸이 속한 밴드의 **중심선 쪽**: 남 밴드(r40~47) 중심 43.5 → aisle_buf r46은 **S**,
   북 밴드(r67~73) 중심 70 → aisle_buf r69는 **N**, 서 밴드(c20~31) 중심 25.5 → inbound_buf c24는 **E**.
3. 둘 다 아니면 -1 (미적용, 경고).

2026-09-02 실측 표 (규칙 1만으로는 aisle_buf·inbound_buf가 결정 불가 → 규칙 2 추가):

| station | 도킹 칸 | 규칙 | entry_dir | 진입 이동(station_in) | 이탈 역주행(station_out) |
|---|---|---|---|---|---|
| aisle_buf[0..10] | (69, c) | 2 | N | S로 (70,c)→(69,c) | (69,c)→N |
| aisle_buf[11..21] | (46, c) | 2 | S | N로 (45,c)→(46,c) | (46,c)→S |
| packing / induction / consol / vas | (40, c) | 1 | N | S로 (41,c)→(40,c) | (40,c)→N |
| inbound_buf[0..2] | (52/58/64, 24) | 2 | E | W로 (r,25)→(r,24) | (r,24)→E |

검산 성질 (데모에서 assert):
1. **중립 θ** (`GuidanceTheta.neutral()`) → 전부 1.0.
2. 범위 clamp + **포화 없음**: `edge_cost.max() ≤ max_realizable_edge_cost(θ)` (배타 규칙 증명).
3. 그룹 방향 부호 (통로 내부 N/S).
4. 규칙별 단독 검사: loop 역행 간선, 교차로 **진입만**(내부·이탈 1.0), station in/out 간선과 무관 간선 1.0.
5. **배타**: loop∧교차로진입 겹치는 간선 = `loop_gain` 하나만 (loop가 우선).

## 4. θ가 경로에 먹히는 방식 — 거리항 (2026-09-02 개정)

PIBT 후보 score = `edge_cost + dist[다음칸]` (pibt_core.candidates).
**`--theta`일 때 dist는 θ 가중 다익스트라**(pibt_core.dist_map(edge_cost=...)),
θ 없으면 비가중 BFS 그대로 (기본 경로·벤치마크 불변).
결정 근거: [2026-09-02 결정 §5](2026-09-02_Isaac회전충돌_격자유지_PIBT확장_결정.md).

이력 — 비가중 BFS였던 첫 구현(2026-09-01)에서 실측된 두 문제와 해소:
- **영구 정체**: dist를 1 줄이는 유일한 이동의 엣지 비용이 `wait_cost + 1` 이상이면
  대기가 매 틱 이겨 정체 (gain 3.5 + wait 1.0으로 STALL). 임시 규칙
  `gain < wait + 1`을 두었으나, 가중 거리항에서는 최적 경로 전진 = `d` < 대기
  `wait + d`라 **θ 값과 무관하게 소멸.** 데모가 gain 3.5로 완주하는 것이 회귀 테스트.
- **진입 시점 통로 선택 불가**: 비가중이면 θ는 같은 칸 수 후보 간 타이브레이크로만
  작용해, 통로 진입 엣지까지 규칙을 확장하는 꼼수를 넣었었다 (분극 격차 +0.31).
  가중 거리항은 비싼 통로의 dist 자체를 키워 진입 전부터 우회를 유도 → 꼼수 제거,
  θ 합의안의 "통로 규칙 = 내부 간선"과 일치. 제거 후 분극 격차 **+1.00** (완전 분리).

주의: θ가 바뀌면 목표별 dist 캐시를 버려야 한다 (시뮬 1회 안에서는 θ 고정).

## 5. sim_v2 연결과 계측

- `--theta=<path.json>`: json 키 = GuidanceTheta 필드 11개. 로드 → from_theta →
  `edge_cost`/`wait_cost` 교체. **옵션이 없으면 지금과 비트 단위 동일 경로.**
- 히트맵 파일명: `--theta` 사용 시 `_th` 접미사 추가 (기존 결과 덮어쓰기 방지,
  핸드오프 §2 규칙).
- `SIM_DIRFLOW=1`: NAV 이동의 방향별 카운트 `(H,W,4)`를 npz로 저장 —
  DoD의 "회피가 보인다"를 히트맵(방향 무관)보다 정직하게 판정하기 위한 계측.
  이동계층 로직은 불변 (카운터만 추가).

## 6. 검증 — v2 재작업 후 결과 (2026-09-02)

`python from_theta_demo.py` 전부 통과: [1] 중립 θ=uniform, [2] 극단 θ 최대 3.60 ≤ 실현 상한 4.20
(포화 없음 = 배타 규칙 검산), [3] 통로 내부 방향 부호, [4] 규칙별 단독 간선(loop 역행·교차로 진입만·
station in/out, 도킹 칸 43개, entry_dir packing N·aisle_buf S/N·inbound E), [5] 배타(loop∧교차로 = loop만)
+ main_aisle_gain 독립 곱, [6~8] 더미 θ(3.5/0.5) 완주·분극 격차 +0.03→+0.98. 헤딩 모델 + θ 조합
(`--heading --theta`) 10대 SIM_CHECK 완주. `returns[0..1]`은 entry_dir 미결정(밴드 밖·인접 벽 없음,
흐름 미사용) → 경고 후 미적용.

### 원래 검증 계획

1. `python from_theta_demo.py` (신규) — §3 검산 4종 assert + uniform vs 더미 θ
   (gain 3.5/boost 0.5/period 1/phase 0) sim_v2 2회 실행 — 극단 θ 완주 자체가 라이브니스 회귀, 짝수 통로 북행 점유율이
   uniform 대비 상승하는지 assert, 방향 분극 비교 PNG 저장.
2. 기존 검증 커맨드 4종 (핸드오프 §2) 전부 통과 — θ 미사용 경로 불변 확인.
   특히 `SIM_CHECK=1 ... --flow=v1compat` 검산과 `fleet_sweep_b1e.py`.

## 7. 미결 — A트랙/팀 합의 필요 (θ 스키마 합의 시 같이 볼 것)

- junction을 목(폭 3×행 1)으로 정의 — 서/동 밴드와 간선의 코너는 미포함.
- 가로 통로 rank 미사용 결정(§2)은 wallA 한정 — 가로 랙 통로가 있는 맵이 오면 재론.
- θ json 스키마: `GuidanceTheta` 필드명 그대로, 로드 시 `validate()`로 v2 범위 검사.
- station_in/out 스퍼 길이·예외, 하한 포화(0.5×0.5), 2칸 폭 통로 aisle_id 등 합의안 미합의 항목은 그쪽 문서 기준으로 추적.
