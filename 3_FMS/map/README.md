# 3_FMS/map — 벽있음 확정 맵 기준 + 충전 존 (맵 파트 전달용, 2026-09-03, S15P21A106-130)

FMS 시뮬 엔진(3_FMS)이 쓰는 맵과 Isaac 씬(2_Simulation v5.8)이 다른 버전임을 확인했습니다.
팀 확정은 **벽있음**입니다. 아래 파일을 기준으로 벽있음 산출물 세트를 재생성·커밋해 주시고,
Isaac 씬도 그 세트로 재빌드해 주세요.

## 이 폴더

| 파일 | 내용 |
|---|---|
| `occupancy_grid_wall_ref.npy` | 벽있음 원판 (0.1 m, shape 1061×1151). 남쪽 r38~39 벽, 기둥 전부 포함. **여기에 아래 조건 ②를 더해 주세요** |
| `stations_wall_ref.json` | 스테이션 좌표 기준 (m). packing·induction·consol·vas = y≈40 라인 (기존 12개 charger/charge_q 포함) |
| `charge_zone.json` | **충전 존 좌표** (m) + 규약 메타. stations.json에 `charge_zone` 키로 합쳐 넣어 주세요 |
| `map_diff_wall_vs_v58.png` | 두 버전 비교 — 빨강: 우리만 통행(=Isaac에 물체 있음, 충돌 위험), 파랑: v5.8만 통행(벽있음이면 무시), 채운 마커: 우리 스테이션, 빈 마커: v5.8 |
| `charge_zone_east.png` | 충전 존 위치 그림 |

## 요청 조건

1. **벽있음** (`grid_v56a_wall` 변형) — 남쪽 r26~39·북쌍 r75~ 구역 폐쇄, 스테이션은 `stations_wall_ref.json` 위치
2. v5.8 요소 반영: **바닥 파렛트 블록(셀값 6)** — 북동 c103~108×r67~73, 서편 c16~17 등 — 와 **랙 길이 1칸 연장**(통로 입구 r47·r67)
3. **기둥은 도면의 105개 전부 유지** (랙 밖 x=26.1, 104.1 포함, 외벽 파일라스터 포함)
4. `charge_zone.json`의 내용을 `stations.json`에 `charge_zone` 키로 추가. 기존 `charger`/`charge_q` 12개는 남겨도 무관 (FMS 폴백용)
5. Isaac 씬을 이 세트로 재빌드. **벽을 물리 객체로 세우는 것은 보류** (FMS가 벽 구역에 진입하지 않음)

## 충전 존 좌표 (m, 원본 0.1 m 맵 좌표계, 기존 stations 규약과 동일)

```json
"charge_zone": [ {"x0": 102.6, "y0": 48.0, "x1": 108.6, "y1": 67.0} ]
```
- FMS 1 m 격자로 c=103~108 × r=48~66. 격자 칸 c ↔ x ∈ [c−0.4, c+0.6), 행 r ↔ y ∈ [r, r+1)
- 통행 통로 c99~102 (x 98.6~102.6)는 존에 포함하지 않음
- 좌표 규약: (x, y) = 로봇 구동축 중점 = 셀 중심 (기존 합의 그대로)
- 존 안에 로봇 몸이 있으면 충전. 슬롯·레인 없음. Isaac 씬은 존 바닥 표시(충전 패드) 정도면 충분

## 산출물 세트 (기존 `2_Simulation/t3_warehouse_map/map/`과 같은 구성)

`occupancy_grid.npy`, `obstacle_mask.npy`, `stations.json`, `rack_units.npy`, `columns.npy`, `map.pgm`, `map.yaml`, `zones.json`

## 배경 문서 (3_FMS/docs)

- `2026-09-03_맵버전_동기화_결정.md` — 발견 경위·결정
- `2026-09-03_충전존_결정.md` — 충전 존 결정과 대안 검토
