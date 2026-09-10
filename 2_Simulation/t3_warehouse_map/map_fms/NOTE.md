# map_fms — 3_FMS 정렬 맵 (계획용)

`3_FMS/map/` 과 좌표를 맞춘 맵. **기본 맵(`../map/`)을 대체하지 않는다** —
`t3_amr` 가 `MAP=$MAP_FMS` 로 명시할 때만 쓴다.

## 왜 따로 두나

`../map/` 은 **공유 자원**이다. 바꾸면 아래가 같이 흔들린다.

    scene_builder/config.py            MAP_DIR
    sil_ros/gridmap.py:31              DEFAULT_MAP_DIR (ROS SIL 스택)
    t3_warehouse/ros2/loc.launch.py    Nav2 map.yaml (위치추정)
    tests/test_scene_builder_gridutil.py:126   경로를 고정하는 테스트

특히 `map.pgm`·`map.yaml` 은 v5.6 격자에서 나온 것이라, 격자만 갈아끼우면
위치추정 맵과 어긋난다. 그래서 제자리 교체를 하지 않는다.

## 무엇이 다른가

| | `../map/` (v5.6) | 여기 (FMS) |
|---|---|---|
| `occupancy_grid.npy` | `160e18ae` | `f8bcfc1b` — `3_FMS/map/` 과 **바이트 동일** |
| 장애물 | 8.92% | **10.55%** (벽 19,909칸 = 199 m²) |
| `aisle_buf` 남쪽 줄 | y 46.0 | **y 46.2** |
| 작업 라인 | packing y 33.8 · consol 33.8 · vas 30.2 | **전부 y 40.4** |

두 맵의 장애물을 0.1 m 격자에서 대조하면 **`map_fms` 통행영역 ⊂ `map` 통행영역**
이다 (v5.6 에만 있는 장애물 0칸). 이 맵으로 계획한 경로는 현행 씬에서 물체를
통과하지 않는다.

## 왜 필요한가 — 0.2 m

랙→버퍼 매핑(`3_FMS/map/build_rack_map.py`)이 **좌표 완전일치**를 요구한다.
최근접을 안 쓰는 것은 마스터와 맵이 어긋난 것을 드러내려는 의도다.
`aisle_buf` 남쪽 줄이 y 46.0 이면 22개 중 11개가 떨어져서 매핑표가 안 만들어지고,
`3_FMS` 의 명시 주문 모드(`--orders-file`)를 못 쓴다.

맞춘 뒤 검증: 존 22개 → 버퍼 22개(일대일) · 랙 132개 · 버퍼당 6개.

## 파일

| | |
|---|---|
| `occupancy_grid.npy` · `obstacle_mask.npy` | 격자. `3_FMS/map/` 과 동일 |
| `stations.json` | `3_FMS/map/` 값 + `handoff`(= FMS 의 `input`+`output`). 공통 키 13개는 값이 전부 같다 |
| `rack_buffers.json` · `charge_zone.json` | `3_FMS/map/` 에서 복사 |
| `rack_units.npy` · `columns.npy` | **격자에서 파생**. 셀값 2 가 랙 풋프린트, 셀값 1 중 y 57.35 폭 1.90 런이 릿지 기둥 12곳. 되만든 값으로 마스크를 다시 그려 원 격자와 diff: 48,420 / 48,420 · 누락 0 · 초과 0 (100.00%) |
| `conveyors.json` | 벨트 좌표 7줄. v5.6 의 6줄 + 이 격자에 새로 생긴 수직 구간 `(106.4, 39.9, 3.2, true)` |

`conveyors.json` 이 없으면 `scene_builder` 가 v5.6 값으로 되돌아간다. 그러면
그 수직 벨트가 작업대로 분류되어 `packing_table` 이 잘못 얹힌다.

## 이 맵으로 씬을 지으면

```
컨베이어 콜라이더 37 · 작업대 rect 172 · packing_table 28 · 벨트 섹션 25
랙 24세그 · 132개 · 프레임 176 · 데크 264
```

## 아직 안 한 것

**이 격자로 씬을 다시 짓지 않았다.** `t3_warehouse/warehouse_scene.usd` 는 v5.6
격자로 세운 것이라, 이 맵으로 계획하고 그 씬에서 주행하면 로봇이 작업대가 없는
빈 바닥으로 간다. 충돌은 없다(통행영역이 부분집합이므로).

씬을 이 격자로 지으려면 `scene_builder/config.py` 의 `MAP_DIR` 을 여기로 돌려야
하는데, 그러면 위의 공유 참조가 같이 흔들린다. **씬 재빌드는 별도 결정이다.**
