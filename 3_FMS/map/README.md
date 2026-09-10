# 3_FMS/map — FMS 공식 맵 (벽있음 ∪ v5.8 장애물) + 충전 존 (2026-09-03, S15P21A106-135)

FMS 시뮬 엔진(3_FMS)이 읽는 **단일 맵 위치**입니다. `map_loader.load_map()`(단일 소스)·A트랙 `build_input.py`
전부 이 폴더의 `occupancy_grid.npy`·`stations.json`을 읽습니다 (엔진 폴더 복사본은 2026-09-03 삭제).

## 경위

FMS 엔진 맵(벽있음, 8/31 복사본)과 Isaac 씬 맵(2_Simulation v5.8, 벽없음)이 다른 버전이었습니다
([맵 불일치와 동기화 결정](../docs/맵_충전존.md#맵-불일치와-동기화-결정)). 팀 확정은 **벽있음 + v5.8 요소**.
맵 파트가 생성 스크립트로 공식 세트를 다시 만드는 동안 기다리지 않고, FMS는 두 원본을 합쳐 **정답지**를 만들어
바로 씁니다. 맵 파트 결과물은 `check_map_set.py`로 이 정답지와 대조해 차이 0을 확인한 뒤 교체합니다.

## 이 폴더

| 파일 | 내용 |
|---|---|
| **`occupancy_grid.npy`** | **FMS 공식 맵** (0.1 m, 1061×1151). `build_fms_map.py` 산출물 = 벽있음 기준 ∪ v5.8 장애물 |
| **`stations.json`** | 스테이션 좌표(m, 팀 확정 r40 작업 라인) + **`charge_zone` 키** (충전 존 사각형) |
| `build_fms_map.py` | 위 두 파일 생성 스크립트 (규칙은 파일 머리 주석). 입력이 바뀌면 다시 실행 |
| `check_map_set.py` | 맵 파트 세트 ↔ 정답지 대조 (0.1 m 장애물 차이, 1 m 통행성 차이, stations 키) |
| `map_fms_build_report.txt` | 생성 보고 (추가 장애물 칸 수, 값 분포) |
| `occupancy_grid_wall_ref.npy` | 벽있음 원판 (= 8/31 엔진 복사본). 생성 입력 |
| `stations_wall_ref.json` | 스테이션 원판. 생성 입력 |
| `charge_zone.json` | 충전 존 좌표(m) + 규약 메타. 생성 입력 (`stations.json`에도 합쳐짐, `load_charge_zone`은 이 파일을 읽음) |
| **`rack_buffers.json`** | WMS 랙 `"A2"` → `aisle_buf[i]` 매핑 132개 (-156). `build_rack_map.py` 산출물, `load_rack_map`이 읽음. [규칙](../docs/맵_충전존.md#랙--통로-버퍼-매핑) |
| `build_rack_map.py` | 위 표 생성: 존 facility 좌표 == aisle_buf 좌표 정확 일치(마스터 `order_gen/master/santafactory_sample.json` 입력). 백엔드 시드가 바뀌면 다시 실행 |
| **`synth_warehouse.py`** | **합성 창고 생성기** (-139). 파라미터 → 맵 세트 한 벌(위 파일들 + `topology.json`). 산출물은 `synth/` 112개(저장소 포함). [문서](../docs/합성_창고_생성기.md) |
| `map_diff_wall_vs_v58.png` | 두 원본 비교 — 빨강: 벽있음만 통행(=Isaac에 물체, 이번 합성으로 막힘), 파랑: v5.8만 통행(벽있음 유지로 여전히 막힘) |
| `charge_zone_east.png` | 충전 존 위치 그림 |

## 합성 규칙 (build_fms_map.py)

- 벽있음 원판을 그대로 두고, **v5.8에서 장애물(1 구조물·기둥 / 2 랙 / 5 컨베이어 / 6 바닥 파렛트)인데 원판이 비장애물인 칸**을
  v5.8 값으로 덮는다 → 두 맵 중 하나라도 막힌 칸은 막힘(보수적). FMS 경로가 Isaac 물체를 통과하는 일이 없다.
- v5.8이 통행으로 바꾼 칸(벽 제거)은 **벽있음 확정에 따라 여전히 막힘**.
- 결과(0.1 m): 추가 장애물 49,715칸 = 파렛트 34,932 / 컨베이어 5,761 / 랙 5,380 / 구조물·기둥 3,642. 1 m 격자 free 10,020 → 9,333.
- 1 m 격자 영향: **랙이 양 끝 1 m 연장** → 랙 사이 통로 행 48~66 → **47~67** (`map_loader.AISLE_ROWS`, `from_theta.VA_ROWS` 등 재산출).
  세로 통로 11 × 63칸(구 57), 교차로 66칸(동일), 충전 존 free 106칸(동일), 스테이션 57개 전부 도킹 가능.

## 맵 파트에 요청 (공식 세트)

1. **벽있음** (`grid_v56a_wall` 변형) — 남쪽 r26~39·북쪽 r75~ 구역 폐쇄, 스테이션은 `stations_wall_ref.json` 위치(r40 라인)
2. v5.8 요소 반영: 바닥 파렛트 블록(셀값 6), 랙 길이 1칸 연장, 기둥 도면 105개 전부
3. `charge_zone.json` 내용을 `stations.json`에 `charge_zone` 키로 추가 (기존 `charger`/`charge_q` 12개는 남겨도 무관)
4. **저장 위치: `2_Simulation/t3_warehouse_map/map/`에 덮어써서 커밋** (Isaac 씬이 읽는 곳). FMS는 `check_map_set.py`로
   이 폴더 정답지와 대조해 1 m 통행성 차이 0이면 그 세트로 교체하고, 이 폴더의 `occupancy_grid.npy`는 그 사본으로 갱신
5. Isaac 씬을 그 세트로 재빌드. 벽을 물리 객체로 세우는 것은 보류 (FMS가 벽 구역에 진입하지 않음)

```
python check_map_set.py ../../2_Simulation/t3_warehouse_map/map     # 세트 수신 후 대조
```

## 합성 창고 (S15P21A106-139)

`synth_warehouse.py` 는 같은 형식의 맵 세트를 파라미터로 만든다. 공식 맵과 다른 점은 **자기
토폴로지를 `topology.json` 으로 같이 들고 다닌다**는 것뿐이고, `map_loader` 는 그 파일이 있으면
거기서, 없으면 wallA 상수에서 통로·밴드 좌표를 읽는다 (이 폴더에는 없다 → 공식 맵 동작 불변).

```bash
python synth_warehouse.py racks synth --n 112     # 격자 전부 (2.3 s, 97 MB). 라벨링은 이 중 25개부터
python synth_warehouse.py wallA /tmp/wallA        # 실측 프로파일 재현
python synth_warehouse.py check /tmp/wallA        # 공식 맵과 링 영역 대조 → 차이 0
```

`synth/` 112개는 **저장소에 들어 있다.** 디스크 97 MB 지만 압축하면 0.77 MB 라 무겁지 않고,
θ 라벨이 특정 맵 바이트에 묶이기 때문에 얼려 두는 편이 낫다 — 생성기를 고친 뒤 재생성하면 맵이
바뀌는데 라벨은 그대로 남아 조용히 무효가 된다.

재생성은 시드 없이 결정적이라, 위 명령을 다른 폴더에 돌려 SHA256 을 비교하면 560개 파일이 전부
일치한다. 자세한 것은 [합성 창고 생성기](../docs/합성_창고_생성기.md).

## 충전 존 좌표 (m, 원본 0.1 m 맵 좌표계, 기존 stations 규약과 동일)

```json
"charge_zone": [ {"id": "east", "x0": 102.6, "y0": 48.0, "x1": 108.6, "y1": 67.0} ]
```
- FMS 1 m 격자로 c=103~108 × r=48~66. 격자 칸 c ↔ x ∈ [c−0.4, c+0.6), 행 r ↔ y ∈ [r, r+1)
- 통행 통로 c99~102 (x 98.6~102.6)는 존에 포함하지 않음. 좌표 규약: (x, y) = 로봇 구동축 중점 = 셀 중심
- 존 안에 로봇 몸이 있으면 충전. 슬롯·레인 없음. Isaac 씬은 존 바닥 표시(충전 패드) 정도면 충분

## 배경 문서 (3_FMS/docs)

- [맵·충전 존](../docs/맵_충전존.md#fms-정답지-생성-절차) — 발견 경위, 합성 절차와 충전 존 규칙
- [θ 경로와 기준선](../docs/θ_경로_기준선.md#기준선-계보) — 이 맵 위의 B0″ fleet 기준선
