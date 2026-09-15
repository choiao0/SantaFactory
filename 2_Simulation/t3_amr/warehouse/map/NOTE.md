# warehouse/map — 2026-09-08 부터 **FMS 기준**

`$MAP` 이자 `default_map()` 이 돌려주는 기본 맵. 이날 FMS(`3_FMS/map`)에 맞췄다.

> ## ★ 이 폴더는 **커밋된 소스**다. 생성물이 아니다.
>
> `warehouse_layout_v5_5_final.py` 등으로 **재생성하지 말 것.** 격자가 바뀌면
> 계획 결과가 통째로 달라진다. 기준값(2026-09-11 이관 시점):
>
> | 파일 | sha256 (앞 12) |
> |---|---|
> | `occupancy_grid.npy` | `563e6aeba9c4` |
> | `obstacle_mask.npy`  | `ae4344de2a55` ← 2026-09-11 수정 (옛값 `5ff6d11039c7`) |
> | `stations.json`      | `f8edcf71bdde` |
>
> ★ `obstacle_mask.npy` 기준값이 바뀐 이유: 이관 시점에 적어 둔 `5ff6d110…` 은
> 9/8 FMS 교체에서 **빠진 옛 v5.9 판**이었다. 격자와 짝이 안 맞아 새
> `occupancy_grid.npy` 의 장애물 128,839 칸 중 12,540 칸(9.73 %)을 덮지 못했고,
> 마스크를 읽는 A*·WPPL(`amr/make_path/`)이 **옛 창고**로 계획했다.
> `warehouse/map_fms/obstacle_mask.npy` 로 맞췄고 지금은 미커버 0 이다.
> 자세한 경위는 아래 ★ 절.
>
> 1061×1151 · 0.1 m/셀. pitch 1.2 로 풀링 → 격자 88×95 · 통행칸 5,889 ·
> 스테이션 성분 1,298.
>
> 같은 저장소의 `2_Simulation/t3_warehouse_map/map` 과 **다르다.** 그쪽(v6.0)은
> 격자 sha 가 `3f9548dba22e` 이고 `stations.json` 에 `handoff` 가 없다 —
> `GOAL_CATS` 다섯 중 하나가 조용히 빠지므로 계획에 쓰면 안 된다. 씬을 v6.0
> 격자로 다시 지은 뒤에 단일 소스를 그쪽으로 옮긴다.

## 무엇이 바뀌었나

| 파일 | 상태 |
|---|---|
| `occupancy_grid.npy` | `3_FMS/map` 과 **바이트 동일** (`f8bcfc1b…`) |
| `obstacle_mask.npy` | `warehouse/map_fms` 와 동일 (`ae4344de…`) — **2026-09-11 에야 실제로 맞췄다.** 아래 ★ |
| `stations.json` | FMS 값 + `handoff` 하나 |
| `rack_buffers.json` | FMS 에서 복사. 우리 `stations.json` 으로 재생성해도 같은 값 |
| `charge_zone.json` | FMS 에서 복사 |

### ★ obstacle_mask 는 9/8 에 **안 바뀌어 있었다** (2026-09-11 수정)

위 표는 9/8 에 쓴 것인데 `obstacle_mask.npy` 줄만 사실이 아니었다. 실제로는
옛 v5.9 판(`5ff6d110…`)이 그대로 남아 Santa 의 `.bak` 과 바이트 동일했다.
격자와 짝이 안 맞는다는 것은 숫자로 드러난다 — 새 `occupancy_grid.npy` 의
장애물 128,839 칸 중 **12,540 칸(9.73 %)을 마스크가 덮지 못했다.**

그래서 읽는 파일에 따라 **다른 창고**를 봤다.

| 무엇을 읽나 | 누가 | 창고 |
|---|---|---|
| `occupancy_grid.npy` | `path/pibt_scene.py` (PIBT 헤딩 · lifelong) | 새 것 |
| `obstacle_mask.npy` | `amr/make_path/{grid,lattice,validate}.py` (A* · WPPL) | **옛 것** |

뒤쪽은 단순히 낡은 정도가 아니라 **새 장애물을 통과하는 경로**를 낸다.
Santa 의 `warehouse/map_fms/obstacle_mask.npy` 를 복사해 맞췄고 (t3_amr 에는
`map_fms` 폴더가 없다), 지금은 못 덮는 칸이 0 이다.

★ `path/deinflate_map.py $MAP --write` 는 마스크에서 격자를 **역산해 덮어쓴다.**
  마스크가 틀린 상태에서 돌리면 멀쩡한 `occupancy_grid.npy` 가 망가진다.

스테이션 좌표 변화:

| 종류 | 이전 (v5.9) | 지금 (FMS) |
|---|---|---|
| `aisle_buf` | y 46.0 · 69.4 | **y 46.2** · 69.4 |
| `packing` | y 33.8 · x 77.0~97.8 | **y 40.4 · x 64~88** |
| `consol` | y 33.8 · x 62, 68 | **y 40.4 · x 50, 56** |
| `induction` | y 33.8 · x 38, 44 | **y 40.4 · x 36, 42** |
| `vas` | y 30.2 · x 89~100 | **y 40.4 · x 94~104** |
| `charger` `charge_q` `inbound_buf` `qc` `returns` | | 원래 같았다 |

`input`·`output`·`charge_zone` 이 새로 들어왔다. `handoff` 는 FMS 에 없는
우리 이름인데 `pibt_scene.GOAL_CATS` 와 `config.TASK_CYCLE` 이 쓰므로
`input + output` 으로 다시 정의해 남겼다 — 좌표 4개 중 3개가 원래 같았다.

## 왜 바꿨나

랙→버퍼 매핑(`build_rack_map.py`)이 **좌표 완전일치**를 요구한다. 최근접을
안 쓰는 것은 마스터와 맵이 어긋난 것을 드러내려는 의도다. 우리 `aisle_buf`
남쪽 줄이 y 46.0 이라 22개 중 11개가 떨어졌다 — **0.2 m 때문에** 명시 주문
모드(`--orders-file`)를 못 쓰고 있었다.

맞춘 뒤 검증:

    존 22개 → 버퍼 22개 (일대일) · 랙 132개 · 버퍼당 6개
    복사해 온 rack_buffers.json 과 동일

## ★ 씬 — 9/8 기록이었고, 9/9 에 다시 구웠다 (2026-09-11 갱신)

아래 본문은 **9/8 시점**이다. 그 뒤 9/9 에 새 격자로 씬을 다시 구웠다
(Santa `106160f` "usd 파일 새로운 창고에 맞게 수정", 이어서 `7c6f1ac` 벽 철골).
지금 `warehouse/scene/warehouse_scene.usd` 는 그 결과물이다 —
`9ee7829f…` · 913 KB. 팀 원본(`2_Simulation/t3_warehouse/`, 9/2)은
`581f9fca…` · 405 KB 로 **다른 파일**이다.

그런데도 "창고가 안 바뀐다" 가 계속 나온 이유는 씬이 아니라 `paths.sh` 였다.
`SCENE` 이 **팀 원본 쪽**을 가리키고 있어서, 새로 구운 씬이 저장소 안에 있는데도
안 쓰였다. 2026-09-11 에 `$W/warehouse/scene/warehouse_scene.usd` 로 고쳤다.

> **먼저 `paths.sh` 를 고친 상태로 한 번 돌려 보라.** 그것만으로 해결되면
> `build_scene.py` 를 돌릴 필요가 없다 — 그 스크립트는 `$SCENE` 을 덮어쓰므로
> 불필요하게 돌리지 않는 편이 낫다.
>
> 그래도 컨베이어·작업대가 y 33.8 · 30.2 에 서 있으면 그때는 9/9 재빌드가
> 새 격자를 안 쓴 것이므로, 아래 "다시 지으려면" 절대로 간다.

---

(이하 9/8 기록)

`warehouse_scene.usd` 의 컨베이어·작업대는 **옛 격자로 세운 것**이다.
`build_scene.py` 의 원칙이 "그리드가 곧 씬이다"이고, 그 기하는
`stations.json` 이 아니라 **`occupancy_grid.npy` 의 셀값 5** 에서 나온다.

    convs = greedy_rects(grid == 5)      # 컨베이어·작업대
    stations.json 은 충전기 6기와 앵커 Xform 에만 쓰인다

그래서 지금 계획하면 로봇이 y=40.4 의 **빈 바닥**으로 간다. 충돌은 없다
(FMS 통행영역 ⊂ 우리 통행영역). 영상으로는 말이 안 된다.

### 다시 지으려면 — ~~파일 두 개가 없다~~ **이제 다 있다** (2026-09-11)

    occupancy_grid.npy   있음
    stations.json        있음
    rack_units.npy       있음 (896 B, 9/9 수령)    build_scene.py:89
    columns.npy          있음 (320 B, 9/9 수령)    build_scene.py:330

위의 "★ 없음" 은 9/8 시점 기록이다. 9/9 에 맵 파트에서 둘 다 받았으므로
**맵 파트에 더 요청할 것은 없고, 바로 다시 지을 수 있다.**

    cd "$W" && source paths.sh
    cp "$SCENE" "$SCENE.bak"                       # 지금 것이 유일한 옛 창고 사본
    cd ~/isaacsim && ./python.sh "$W/warehouse/scene/build_scene.py"

`build_scene.py:934` 가 `stage.GetRootLayer().Save()` 로 `$SCENE` 을
**덮어쓴다.** 그래서 먼저 백업한다.

돌린 뒤 V&V 출력에서 셀값 2(랙) 재현율이 100 % 인지 보고, 컨베이어·작업대가
y≈40 대에 서는지 확인한다 (옛 격자는 y 33.8 · 30.2).

### `--rebuild` 는 필요 없다 — 창고는 참조다

`runners/build_amr_scene_v2.py:57` 이

    wh.GetReferences().AddReference(args.warehouse, Sdf.Path("/World"))

로 가져오고, `:163` 의 `st.GetRootLayer().Export(args.out)` 은 `Flatten()` 을
부르지 않는다. 즉 `stage/*.usd` 에는 창고가 **복사돼 들어가지 않고 경로로만**
걸려 있다. USD 가 열 때 합성하므로 `warehouse_scene.usd` 만 새로 구우면 다음
실행에서 바로 반영된다.

`--rebuild` 가 필요한 것은 **로봇 스폰 위치가 바뀔 때**뿐이다 — `starts.json`
은 `stage/*.usd` 에 구워진다.

## 되돌리기

시연 영상이 급하면 옛 맵으로 돌아간다. 백업은 `.gitignore` 의 `*.bak.*` 에
걸려 커밋에는 없다 — 지웠으면 git 이력에서 꺼낸다.

    cd warehouse/map
    cp occupancy_grid.npy.bak.20260908_170003 occupancy_grid.npy
    cp obstacle_mask.npy.bak.20260908_170003  obstacle_mask.npy
    cp stations.json.bak.20260908_165549      stations.json

되돌리면 `plan/traj_*` 도 그 좌표로 다시 만들어야 한다.

## 다음에 해야 하는 것

- **계획 산출물 재생성.** `plan/traj_pibt_h` 등은 옛 좌표로 만든 것이라 못 쓴다
- **도달성 확인.** `python path/diag_reach.py $MAP` — `inbound_buf`·`aisle_buf`·
  `packing`·`consol` 이 같은 성분에 있어야 한다 (로컬에 numpy 가 없어 서버에서)
- `warehouse/map_fms` 는 이제 이 폴더와 중복이다. 정리 대상
- `amr/make_path/grid.py:46` · `lattice.py:202` 가 `charge_zone` 을 하드코딩하고
  있다. 이제 `charge_zone.json` 이 있으니 읽도록 바꿀 수 있다
