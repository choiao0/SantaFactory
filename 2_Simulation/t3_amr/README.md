# t3_amr — AMR 계획·주행 스택 (Isaac Sim)

T3 창고 씬 **위에서 도는** AMR 스택. 씬 자체는 [`../t3_warehouse/`](../t3_warehouse/)
와 [`../scene_builder/`](../scene_builder/) 담당이고, 여기는 그 씬에서 iw.hub AMR 12대를
계획·주행시키고 처리량을 잰다.

계획은 로컬(Isaac 불필요), 주행은 GPU 서버의 Isaac Sim 6.0.1.

```bash
source 2_Simulation/t3_amr/paths.sh

python amr/main.py list                          계획기 목록
python amr/main.py plan --planner pibt_h         계획 (로컬)
python amr/main.py cmds --planner pibt_h         서버에서 칠 명령만 출력

bash run.sh --planner pibt_h                     시연 (WebRTC 화면)
bash run_record.sh                               시연 + mp4 (10배속)
STREAM=0 bash run.sh --planner pibt_h --lite     측정 (헤드리스)
```

---

## 폴더

```
t3_amr/
├─ amr/         진입점 + 계획기 어댑터(레지스트리) + 계획기 본체
├─ path/        ★ 계획 코어·ADG 주행·lifelong — 서버로 배포되는 모듈
├─ runners/     Isaac 안에서 도는 --exec 스크립트
├─ tools/       에셋 내려받기 등
├─ todo/        열려 있는 과제
└─ *.sh         run · run_record · paths · install
```

계층은 셋이다. **어디서 도는 파이썬인지**가 다르다.

| | 도는 곳 | 무엇 |
|---|---|---|
| **계획** | 로컬 python | `amr/make_path/`, `path/pibt_scene.py`, `../../3_FMS/sim_engine/` |
| **기동** | 로컬 python → `os.execvpe` | `run.sh`, `amr/main.py`, `amr/path/` |
| **주행** | Isaac Sim 내부 python | `runners/live_*.py`, `path/isaac_drive.py` |

---

## 주행 파이프라인 (`pibt_h`)

```
pibt_core.run_h()  →  extract_actions  →  build_adg  →  AdgRuntime  →  드라이버  →  Isaac
   (3_FMS 코어)                      (여기, path/isaac_drive.py)
```

1. **계획** — `path/pibt_scene.py` 가 맵을 PIBT 격자로 바꾸고, `path/lifelong.py` 가
   매 틱 `step_h()` 를 돌린다. 결과는 틱마다 로봇별 `State(r, c, h)` — **시간표**다
2. **액션 추출** — 상태 차이를 전진/회전/후진으로 묶는다. **대기는 버린다**
3. **ADG** — 같은 칸을 쓰는 액션 사이에 간선을 건다. "계획에서 A 가 먼저 썼으면
   실행에서도 A 가 끝나야 B 가 시작한다". 순환이면 데드락이므로 그 자리에서 던진다
4. **런타임** — 프레임마다 선행 완료·장애물·릴리스 바닥을 보고 액션을 내보낸다
5. **주행** — `MotionController` → `DifferentialDriver` 가 좌우 바퀴 각속도를 쓴다

**시간표가 아니라 순서로 돌기 때문에** 로봇 하나가 미끄러져도 뒤차가 그만큼 기다린다.
시각 추종(`path/amr_driver_v2.py`, wppl·astar·fms)이면 늦은 차를 앞질러 겹친다.

ADG 가 예약하는 칸은 코어의 `cells_hist` 가 **아니라** `RobotGeom.swept_cells()` 다.
코어 점유는 틱 경계에서만 맞아서 회전 중 차체가 쓸고 지나가는 칸이 빠진다
(12대 실측: `cells_hist` 근거 겹침 10,148건 → 실제 스윕 근거 0건).

---

## 계획기

`amr/path/` 에 모듈 하나 = 계획기 하나. 파일을 넣으면 `main.py` 는 안 고쳐도 된다.

| 이름 | 주행 | 설명 |
|---|---|---|
| `pibt_h` | `adg` | PIBT 헤딩(2칸 점유·스윙 예약·후진) + ADG · 1.2 m 격자. **현행 주력** |
| `wppl` | `time` | Windowed Parallel PIBT-LNS · 2.4 m 격자 · lifelong 420초 |
| `astar` | `time` | 우선순위 space-time A* · 0.2 m 격자 · 비교군 |
| `fms` | `time` | 3_FMS 커널 내보내기 재생. 계획 안 함 · 통제 비교용 |

---

## PIBT 코어는 사본이 아니다

`path/pibt_core_v2.py` 는 **로더**다. `../../3_FMS/sim_engine/pibt_core.py` **원본**을
직접 로드하고 `sys.modules` 를 치환해 `pibt_core` 와 같은 객체가 되게 한다.

한때 이 파일은 그 원본의 바이트 동일 사본이었고, 상류가 `pibt/` 패키지로 분해되면서
**조용히 갈렸다** — 헤딩 거리장 정적 테이블(28대 57~86 s → 7~11 s) 같은 개선이 하나도
안 들어왔다. 같은 저장소로 들어오면서 사본이 필요 없어졌다.

`PIBT_CORE_DIR` 로만 덮을 수 있고, 그때는 stderr 에 남긴다.

---

## 맵

맵은 [`../t3_warehouse_map/`](../t3_warehouse_map/) 이 **단일 소스**다 — `scene_builder`
도, ROS SIL 스택(`sil_ros/gridmap.py`)도, Nav2 위치추정도 같은 폴더를 본다.
여기서 사본을 들지 않는다.

`paths.sh` 가 `$MAP`(기본)과 `$MAP_FMS` 를 잡는다.

```bash
MAP=$MAP_FMS python amr/main.py plan --planner pibt_h    # 3_FMS 와 좌표를 맞춰 계획
```

두 맵은 `aisle_buf` 남쪽 줄이 y 46.0 vs 46.2, 작업 라인이 y 33.8 vs 40.4 로 다르다.
그 0.2 m 때문에 랙→버퍼 매핑(`3_FMS/map/build_rack_map.py`)이 기본 맵에서는
성립하지 않는다 — 좌표 완전일치를 요구하기 때문이다.

**기본값을 `map_fms` 로 두지 않는 이유**는, 그 맵으로 계획하고 현행 씬에서 주행하면
로봇이 작업대가 없는 빈 바닥으로 가기 때문이다. 씬을 그 격자로 다시 지은 뒤에 옮긴다.
([`todo/2026-09-08_asset_이동.md`](todo/2026-09-08_asset_이동.md))

---

## 실행 전에

```bash
python tools/fetch_iwhub.py        # iw.hub 에셋 236 MB (git 제외분)
```

`paths.sh` 가 끝에 없는 파일을 찍어준다 — `$SCENE`·`$ROBOT`·`$MAP` 셋을 본다.

계획 산출물은 `$PLAN` 아래로 간다. **`main.py plan` 이 쓰는 곳과 주행이 읽는 곳이
같은지 확인할 것** — 다르면 새 계획을 만들고도 옛 궤적으로 돌고 로그에는 아무 표시가
없다 (실측 2026-09-08).

---

## 검증

```bash
python path/test_lifelong_battery.py           # lifelong + 배터리 + ADG. Isaac 불필요
python path/diag_reach.py $MAP                 # 스테이션이 같은 성분에 있나 (4/4)
```

`diag_reach` 를 먼저 돌리는 이유는, 스테이션이 서로 다른 성분에 갈리면 배차가 영원히
안 끝나는데 계획이 얼어붙은 것처럼만 보이기 때문이다.
