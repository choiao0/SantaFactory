# t3_amr — AMR 계획·주행 스택 (Isaac Sim)

T3 창고 씬 **위에서 도는** AMR 스택. 씬은 [`warehouse/scene/`](warehouse/scene/)(굽기 스크립트 포함), 맵은
[`warehouse/map/`](warehouse/map/)(설계도 원본·생성기는 `map/source/`)에 있고, 여기는 그 씬에서 iw.hub AMR 12대를
계획·주행시키고 처리량을 잰다. (옛 `../t3_warehouse/`·`../scene_builder/` 는 -219 로 삭제.)

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

> **★ 2026-09-15: `run_record.sh` · `run_onboard.sh` 의 기본 격자가 1.0 m 다.**
> 앞 칸 규칙(`PIBT_FRONT_RULE=4`)도 기본으로 켜진다. 1.2 로 돌리려면
> `PIBT_PITCH=1.2 bash run_record.sh`. 아래 [격자와 앞 칸 규칙](#격자와-앞-칸-규칙)
> 참고. `amr/main.py` 를 직접 부르면 모듈 상수(1.2)가 그대로다.

---

## 폴더

```
t3_amr/
├─ amr/         진입점 + 계획기 어댑터(레지스트리) + 계획기 본체
├─ path/        ★ 계획 코어·ADG 주행·lifelong — 서버로 배포되는 모듈
├─ runners/     Isaac 안에서 도는 --exec 스크립트
├─ warehouse/   map/ (계획 맵 단일 소스) · scene/ (창고 씬 + 빌드 스크립트)
├─ v2/          계획기가 **쓰는** 출력 자리 (traj_*)
├─ plan/        주행이 **읽는** 궤적 ($PLAN). v2/ 에서 복사해 온다
├─ tools/       에셋 내려받기 + **측정·검증 도구 20여 개** (아래 「도구」)
├─ docs/        설계·실측 문서.  `LOCAL_*` · `20*` 는 커밋 안 함 (로컬 메모)
├─ todo/        (비어 있음)
└─ *.sh         run · run_record · run_onboard · paths · install

  stage/ out/ logs/  — paths.sh 가 만드는 산출물. 지워도 다시 생긴다
```

`v2/` 와 `plan/` 에 같은 이름의 하위 폴더가 양쪽에 있는 것은 **생성물과 배치본**
이기 때문이다. `run_record.sh` 는 **`REPLAN=1` 일 때만** `v2/traj_pibt_h/` →
`plan/traj_pibt_h/` 로 복사한다. 평소에는 `plan/` 에 이미 커밋돼 있는 것을 쓴다
(새 체크아웃에서 바로 돌게 하려고 추적한다).

계층은 셋이다. **어디서 도는 파이썬인지**가 다르다.

| | 도는 곳 | 무엇 |
|---|---|---|
| **계획** | 로컬 python | `amr/make_path/`, `path/pibt_scene.py`, `../../3_FMS/sim_engine/` |
| **기동** | 로컬 python → `os.execvpe` | `run.sh`, `amr/main.py`, `amr/path/` |
| **주행** | Isaac Sim 내부 python | `runners/live_*.py`, `path/isaac_drive.py` |

---

## `pibt_h` 만 쓸 때 — 무엇이 쓰이고 무엇이 안 쓰이나

현행 주력은 `pibt_h` 하나다. 아래는 그 경로에서 **실제로 import 되는 것**을
추린 것이다 (주석·배포 목록 매칭 제외, 2026-09-11 기준).

진입점: `amr/main.py` · `amr/path/{__init__,_common,pibt_h}.py` ·
`path/pibt_scene.py` · `runners/{live_pibt,build_amr_scene_v2}.py`

### 쓰는 것

```
amr/main.py                    amr/path/{__init__,_common,pibt_h}.py
amr/make_path/config.py        ★ 이것 하나만 쓴다 (아래 주의)
path/pibt_scene.py             path/lifelong.py       path/battery.py
path/dispatch.py               path/isaac_drive.py    path/metrics.py
path/pibt_core_v2.py           (→ ../../3_FMS/sim_engine/pibt_core.py 로더)
runners/live_pibt.py           runners/build_amr_scene_v2.py
runners/{make_clip,make_video}.sh                     ← run_record.sh 의 영상 조립
warehouse/map/                 warehouse/scene/warehouse_scene.usd
v2/traj_pibt_h/  plan/traj_pibt_h/
paths.sh  run.sh  run_record.sh
```

> ### ★ `amr/make_path/` 를 폴더째 지우면 안 된다
>
> 이름 때문에 WPPL 전용으로 보이지만, `path/pibt_scene.py` 가 통로차단
> (`AISLE_BLOCK`) 규칙 때문에 **`config.py` 하나를 읽는다.**
> `config.py` 는 import 가 하나도 없는 독립 파일이라 그 외에는 다 빼도 된다.
>
> **지워도 죽지 않는다 — 조용히 다른 격자가 된다.** 못 찾으면 통로 차단이
> 꺼져 랙 사이 통로가 열린 격자가 만들어진다 (필터 전 8919 → 9425칸).
> 계획이 달라지는데 결과만 보면 알 수가 없다.
>
> 2026-09-15 에 FMS 가 우리 도구를 재현하려고 `path/` · `warehouse/map` ·
> `tools/` 만 꺼내 가고 이 파일을 빠뜨렸다. 시드별 틱 수가 전부 달랐고 그것을
> 플랫폼 차이(Windows · Python 3.14 · numpy 2.5)로 의심하며 하루를 썼다.
> 파일을 넣자 우리 표가 **틱 수까지** 재현됐다.
>
> 그래서 지금은 못 찾으면 **stderr 로 경고**한다. 저장소 일부만 복사해 쓸 때는
> `amr/make_path/config.py` 를 반드시 같이 가져올 것.

### import 그래프에는 없지만 **필요한 것**

동적 로드거나 사람이 직접 실행하는 것들이라 자동 추적에 안 잡힌다.

| 파일 | 왜 필요한가 |
|---|---|
| `warehouse/scene/{build_scene,roof_structure,view_scene}.py` | 창고 씬을 굽는다. Isaac 에서 직접 실행 |
| `path/_pibt_core_vendor.py` | `pibt_core_v2` 가 `3_FMS/sim_engine` 을 못 찾을 때의 후퇴 사본 |
| `tools/fetch_iwhub.py` | iw.hub 에셋(git 제외)을 받는다. 없으면 씬 빌드 불가 |
| `path/diag_reach.py` · `path/deinflate_map.py` | 진단 도구 (아래 "검증" 절) |
| `path/test_lifelong_battery.py` | 테스트 |
| `amr/__init__.py` | 패키지 마커 — 지우면 `amr.path` import 가 깨진다 |

### 안 쓰는 것 — `pibt_h` 만 쓸 경우

**지금은 남겨 두고 있다.** 지워도 `pibt_h` 는 안 깨지지만(레지스트리가 폴더
스캔이라 파일이 빠지면 목록에서 조용히 사라진다), 굳이 지워서 얻는 것도 없다.
비교군을 다시 돌릴 일이 없다고 확정되면 별도 커밋으로 정리한다.

| 무엇 | 딸린 것 |
|---|---|
| 계획기 `wppl` · `astar` · `fms` | `amr/path/{wppl,astar,fms}.py` |
| WPPL·A* 계획 생성기 | `amr/make_path/` 의 `config.py` **외 전부** — `grid` `lattice` `planner` `wppl` `generate` `generate_wppl` `generate_scenario` `validate` `fms_import` |
| 시각추종 주행 | `path/amr_driver_v2.py`, `runners/{live_wppl12,headless_wppl,render_video_wppl,replay_wppl}.py` |
| 기타 러너 | `runners/{http_stream,ros2_ping}.py` |
| 옛 궤적 | `plan/{traj_cmp,traj_v59,traj_wppl,traj_wppl_new}`, `v2/{traj_cmp,traj_pibt_official,traj_v59,traj_wppl,traj_wppl_new}` |
| 일회성·중복 | `patch_fetch_dest.py`, `v2/server/fetch_iwhub.py`(= `tools/` 와 중복) |
| 빈 폴더 | `todo/` |

★ `tools/` 는 더 이상 "일회성" 이 아니다. 2026-09 에 측정·검증 도구가 20여 개로
늘었고 그중 여럿이 판단 근거를 낸다 (아래 「도구」).

★ `plan/traj_fms` 는 **아예 없다.** `amr/path/fms.py` 는 `$PLAN/traj_fms/...` 를
찾으므로 `fms` 계획기는 지금 상태로는 궤적을 못 읽는다. 쓸 일이 생기면 먼저 볼 것.

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
4. **런타임** — 프레임마다 ①장애물 ②릴리스 바닥 ③ADG 선행 셋을 보고 액션을
   내보낸다. **바닥은 태스크의 첫 동작에만 건다** — 주문 도착 제약이라
   중간 동작에 걸 이유가 없다 (2026-09-15 수정. 전에는 모든 동작에 걸었고,
   그 상태에서 막힘의 66% 가 바닥이었다). 막힘 귀속은 `[adg-why]` 로 찍힌다
5. **주행** — `MotionController` → `DifferentialDriver` 가 좌우 바퀴 각속도를 쓴다

**시간표가 아니라 순서로 돌기 때문에** 로봇 하나가 미끄러져도 뒤차가 그만큼 기다린다.
시각 추종(`path/amr_driver_v2.py`, wppl·astar·fms)이면 늦은 차를 앞질러 겹친다.

ADG 가 예약하는 칸은 코어의 `cells_hist` 가 **아니라** `RobotGeom.swept_cells()` 다.
코어 점유는 틱 경계에서만 맞아서 회전 중 차체가 쓸고 지나가는 칸이 빠진다
(12대 실측: `cells_hist` 근거 겹침 10,148건 → 실제 스윕 근거 0건).

---

## 격자와 앞 칸 규칙

pitch 1.0 에서는 회전할 때 **코가 이웃 칸에 들어간다.** 그래서 앞 칸을 예약에
넣는 규칙이 있다. 켜고 끄는 것은 `PIBT_FRONT_RULE` 이다.

```
4     앞 2칸 + 섞임 대각 2칸 {f0, f1, mA, mB}   ← 기본. 채택한 규칙
2     앞 2칸만 {f0, f1}
off   규칙 없음 (대조군)
```

**규칙은 pitch 게이팅을 받는다** — 1.2 에서는 무엇을 넣든 꺼진다. 칸이 넓어
코가 안 나가기 때문이다. 그래서 `run_record.sh` 가 머리말에 실제로 걸렸는지
찍는다.

```
격자        pitch 1.0   (기본 1.0 — 바뀐 ADG 가 사는 격자)
앞 칸 규칙  PIBT_FRONT_RULE=4   규칙 적용 예
```

로그에 `[scene] 앞 칸 규칙 PIBT_FRONT_RULE=4 -> 4칸` 이 없으면 안 걸린 것이다.

pitch 1.0 은 2칸 점유 + 스윙 3칸 모델의 **유효 구간(1.117~2.220) 밖**이라
`RobotGeom.describe()` 가 이렇게 찍는데, **규칙이 켜져 있으면 정상이다.**

```
pitch      : 1.00 m   (이 모델의 유효 구간 1.12 ~ 2.22 m  ★구간 밖)
회전 스윙  : ★모델 밖 [(5, 6), (6, 5)]
```

저 두 칸이 바로 규칙이 덮는 칸이다 (`front_cells((5,5,1)->(5,5,0))
= [(4,6), (5,6), (6,4), (6,5)]`). 위험한 조합은 **규칙을 끄고 1.0 으로 도는 것**
이고, 그건 머리말에 `규칙 적용 아니오` 로 찍힌다.

규칙이 왜 4칸인지, 검사가 무엇을 막는지, 켜면 순환이 어떻게 되는지는
[ADG 축 규칙](docs/ADG_축규칙.md) 에 있다. 20시드 실측으로 **규칙을 끄면 순환
3건, 켜면 0건**이다 (순환 = 주행 전 데드락).

★ **1.0 채택은 아직 확정이 아니다.** 1.0 vs 1.2 포화 처리량이 마지막 게이트이고
  거기서 1.2 로 되돌아갈 수 있다. 되돌릴 때는 두 스크립트의
  `export PIBT_PITCH="${PIBT_PITCH:-1.0}"` 한 줄씩만 바꾸면 된다.

### 실행 속도

```bash
PIBT_V_EXEC=2.2 bash run_record.sh        # 안 주면 geom.v_max(0.9) = 계획 속도
```

**안 주면 실행 속도가 계획 속도와 같아진다.** 계획을 느리게 잡는 근거 자체가
"실행이 더 빨라 회전 손실을 따라잡는다" 이므로, 둘이 같으면 그 논리가 성립하지
않는다. 채택 속도를 정했으면 명시할 것.

---

## ★ 환경변수가 Isaac 까지 가는 규칙

`amr/main.py:155` 가 이렇게 띄운다.

```python
os.execvpe(argv[0], argv, dict(os.environ, **env))
```

**셸 환경 전체를 깔고 그 위에 `pibt_h.launch()` 의 `env` 목록을 얹는다.**

| | |
|---|---|
| 목록에 **있는** 이름 | `pibt_h` 의 값이 이긴다 — 셸 값이 무시된다 |
| 목록에 **없는** 이름 | 셸에서 **그대로 상속된다** |

실제로 덮이는 것은 `PIBT_N` · `PIBT_STAGE` · `PIBT_MAP` · `PIBT_MODE` 넷이다.
나머지는 `_e(name, default)` 로 감싸 있어 **셸이 이긴다**.

```
PIBT_MODE=oneshot bash run_record.sh     ->  무시된다 (lifelong 로 하드코딩)
PIBT_HORIZON=550 bash run_record.sh      ->  먹는다 (_e 로 감싸 있다)
PIBT_V_EXEC=2.2  bash run_record.sh      ->  먹는다
```

> ★ 2026-09-15 정정. `pibt_h.py` 주석이 오래 "목록에 없는 이름은 전달조차
> 안 된다" 고 적고 있었고 **그것이 틀렸다.** 그 서술을 믿고 "실행 속도가
> 전달 안 돼 주행이 늘 0.9 였다" 고 잘못 진단한 적이 있다. `dict(os.environ,
> **env)` 는 2026-09-09 도입 이래 바뀐 적이 없다.
>
> 2026-09-11 의 `PIBT_HORIZON=550` 이 안 먹은 것은 **그때는 하드코딩이어서**
> 맞다. 지금은 `_e` 로 바뀌어 먹는다.

`PIBT_MODE` 가 하드코딩인 것은 의도된 것이다 — one-shot 은 12대에서 **어느
시드도 완주하지 못한다** (통로차단 이후 도달 가능한 목표가 한 줄로 쏠린다).

---

## 계획기

`amr/path/` 에 모듈 하나 = 계획기 하나. 파일을 넣으면 `main.py` 는 안 고쳐도 된다.

| 이름 | 주행 | 설명 |
|---|---|---|
| `pibt_h` | `adg` | PIBT 헤딩(2칸 점유·스윙 예약·후진) + ADG. **현행 주력**<br>격자는 모듈 상수 1.2 이지만 **주행 스크립트 기본은 1.0** (위 절) |
| `wppl` | `time` | Windowed Parallel PIBT-LNS · 2.4 m 격자 · lifelong 420초 |
| `astar` | `time` | 우선순위 space-time A* · 0.2 m 격자 · 비교군 |
| `fms` | `time` | 3_FMS 커널 내보내기 재생. 계획 안 함 · 통제 비교용 |

### 배차 정책 — 기본은 `fms` (이산쪽 정렬)

계획기와 **별개 축**이다. `pibt_h` 안에서 태스크를 어느 순서로 나눠줄지를 정한다.

| 정책 | 순회 | 쓸 때 |
|---|---|---|
| `fms` (**기본**) | 태스크 순회 — waiting FIFO 순으로 가장 가까운 유휴 로봇 | 3_FMS 와 KPI 비교 |
| `robot_first` | 로봇 순회 — 로봇마다 가장 가까운 태스크 | **시연·처리량** |

```bash
python path/pibt_scene.py ... --dispatch robot_first     # 계획
PIBT_DISPATCH=robot_first bash run_record.sh             # 주행
```

`robot_first` 가 **처리량은 더 높다.** 12시드 실측(12대·horizon 315·
`order_gap` 15·배터리 ON·존복귀 ON, 완료 태스크 수):

```
robot_first  175   |   fms  149        9승 2패 1무 (+17.4%)
```

그런데도 기본을 `fms` 로 둔 것은 **3_FMS 이산 시뮬과 정책을 같게** 두기
위해서다. 배차가 다르면 두 시뮬의 KPI 차이를 물리 탓으로 돌릴 수 없다.
격자(1.0 vs 1.2 m)와 목표열은 AMR 기하 제약이라 못 맞추지만 정책은 맞출 수 있다.
왜 1.2 m 이고 왜 경로는 못 맞추는지는 [격자 1.2 m 근거](docs/2026-09-13_격자_1.2m_근거.md)에
수치로 적어 두었다 — 배차 함수를 그대로 못 가져온 이유와 **남은 차이(토트 합승)** 도 거기 있다.
틱이 실제로 몇 초인지(전진 1칸 2.37 s · 회전 90° 1.51 s)는
[이동·회전 실측시간](docs/2026-09-13_이동회전_실측시간.md) 에 있다.

pitch 1.0 으로 내리려면 회전 시 코가 이웃 칸에 들어가는 것을 예약으로
처리해야 한다. 그 규칙과 ADG 구조는
[ADG 축 규칙](docs/ADG_축규칙.md) 에 있다 — 왜 4칸인지, 검사가 무엇을
막는지, 규칙을 켜면 순환이 어떻게 되는지까지.

**시연 영상을 뽑을 때는 `robot_first` 를 쓰는 편이 낫다.**

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

**계획 맵은 `warehouse/map/` 이 단일 소스다.** `paths.sh` 가 그것만 잡는다.

```bash
export MAP=$W/warehouse/map        # paths.sh:27
```

> 이 절은 원래 "맵은 `../t3_warehouse_map/` 이 단일 소스이고 여기서 사본을 들지
> 않는다", "`paths.sh` 가 `$MAP` 과 `$MAP_FMS` 를 잡는다" 고 적혀 있었다.
> **둘 다 지금은 사실이 아니다** (2026-09-11 정정). `$MAP_FMS` 는 이 저장소의
> `paths.sh` 에 없고, `$MAP` 은 t3_amr 안의 사본을 가리킨다.

한때 팀 기본 맵이던 `../t3_warehouse_map/map`(v6.0)을 쓰지 않은 이유는 두
가지였다. **그 폴더는 -219 로 삭제됐으므로 아래는 이력이다** — 지금 단일
소스는 `warehouse/map/` 이다.

- 격자가 다르다 (`occupancy_grid` sha `3f9548db…` vs 여기 `563e6aeb…`)
- `stations.json` 에 `handoff` 가 없다 — `pibt_scene.GOAL_CATS` 다섯 중 하나가
  조용히 빠진다

`warehouse/map/` 은 2026-09-08 에 `3_FMS/map` 기준으로 맞췄다. 그때 `aisle_buf`
남쪽 줄이 y 46.0 → 46.2, 작업 라인이 y 33.8 → 40.4 로 옮겨졌다. 그 0.2 m 때문에
랙→버퍼 매핑(`3_FMS/map/build_rack_map.py`)이 옛 좌표에서는 성립하지 않았다 —
좌표 완전일치를 요구하기 때문이다.

경위·주의사항·되돌리는 법은 [`warehouse/map/NOTE.md`](warehouse/map/NOTE.md) 에
있다. 특히 **`path/deinflate_map.py $MAP --write` 는 함부로 돌리지 말 것** —
`obstacle_mask.npy` 에서 격자를 역산해 `occupancy_grid.npy` 를 덮어쓴다.

씬(`warehouse/scene/warehouse_scene.usd`)도 이 격자로 지어진 것이라야 한다.
`$SCENE` 이 팀 원본을 가리키면 "맵은 새 창고인데 화면은 옛 창고" 가 된다
(2026-09-11 에 겪었다).

---

## 업무 종료 후 충전존 복귀

lifelong 은 기본적으로 **horizon 끝까지 주문이 들어온다.** 그래서 로봇이 쉬는 틈이
없고, 충전존 복귀 구현이 켜져 있어도 `TO_HOME` 에 한 번도 진입하지 않는다.
실측 (12대 · seed 1 · `order_gap` 15 · horizon 315):

    태스크 30건 도착 · 13건 완료 · **대기 8건 남은 채 종료** · TO_HOME 진입 0회

"업무가 끝나면 충전존으로 돌아온다" 를 보려면 **두 가지를 같이** 줘야 한다.

| 무엇 | 왜 |
|---|---|
| `order_end` | 이 틱부터 새 주문이 없다. 업무 구간 `[0, order_end)` · 복귀 구간 `[order_end, horizon)` |
| `order_gap` ↑ | 15 는 선단 처리량을 넘는다. 적체가 남으면 주문을 끊어도 계속 일한다 |

교대 창(`shifts`)은 horizon 이 아니라 **업무 구간**을 등분한다. 그래서 horizon 만
늘리면 업무 일정도 같이 늘어나 복귀 시간이 안 생긴다 (실측: 업무 315틱 고정으로
horizon 을 315→500 으로 늘려도 주차 2/12 → 3/12).

실측 (12대 · seed 1 · 업무 315틱 고정 · **배터리 OFF · 배차 `fms`** — 현행 기본값):

| `order_gap` | horizon | 복귀 구간 | 생성 | 완료 | 대기 | 종료 시 존 |
|---|---|---|---|---|---|---|
| 15 (기본) | 315 | 0틱 | 30 | 12 | 6 | 0/12 |
| 15 | 550 | 235틱 | 30 | 26 | 0 | 4/12 |
| 25 | 550 | 235틱 | 16 | 16 | 0 | 10/12 |
| 40 | 420 | 105틱 | 14 | 13 | 0 | 10/12 |
| **40** | **550** | **235틱** | 14 | **14** | 0 | **12/12** |

> 배터리 ON · `robot_first` 였을 때는 `order_gap` **25** 로 12/12 였다. 배차를
> `fms` 로 맞추며 처리량이 내려가 **부하를 더 낮춰야** 전원이 돌아온다.
> 설정을 바꾸면 이 표를 다시 재야 한다.

```bash
# 계획만 (Isaac 불필요)
python path/pibt_scene.py --lifelong --plan --n 12 \
       --horizon 550 --order-end 315 --order-gap 40

# 주행
PIBT_HORIZON=550 PIBT_ORDER_END=315 PIBT_ORDER_GAP=40 REPLAN=1 bash run_record.sh
```

`--order-end` 는 1 이하면 horizon 비율, 1 초과면 틱이다. **생략하면 동작이 이전과
완전히 같다** — 교대 창도 horizon 기준으로 돌아간다.

`info["parked_end"]` 가 종료 시 충전존 안 대수다. 러너가 로그에 찍는다.

★ 복귀가 늦는 로봇은 대개 **고장이 아니라 긴 왕복 중**이다. 업무 종료 직전에
태스크를 받으면 목적지까지 갔다가 돌아와야 한다 (실측: 한 대가 t=126 에 받은
태스크로 c=25 → c=74 를 이동 중 horizon 을 넘겼다). 복귀 구간은 **마지막 태스크
소요 + 귀환 거리**를 덮어야 한다.

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
python tools/adg_fingerprint.py                # ADG 간선 회귀 — 규칙을 건드리면 먼저
```

`diag_reach` 를 먼저 돌리는 이유는, 스테이션이 서로 다른 성분에 갈리면 배차가 영원히
안 끝나는데 계획이 얼어붙은 것처럼만 보이기 때문이다.

`adg_fingerprint` 는 **규칙이 꺼진 상태에서 간선이 한 줄도 안 바뀌었는지**를
지킨다. 액션과 간선을 정규 직렬화해 sha256 을 비교하므로, 예약 규칙을 건드릴
때 이것부터 돌린다.

---

## 도구

`tools/` 는 전부 **Isaac 없이** 돈다 (`add_onboard_cam.py` 만 pxr 을 쓴다).
`.npz` 를 받는 것들은 `run_record.sh` 에 `PIBT_RECORD=...` 를 주면 나오는
자세 기록을 읽는다.

```bash
source paths.sh
PIBT_RECORD=$OUT/rec.npz bash run_record.sh 12        # 녹화를 만든다
```

### 계획 층 — Isaac 도, 녹화도 필요 없다

| | |
|---|---|
| `adg_fingerprint.py` | ADG 간선 회귀. 규칙을 건드리면 **먼저** 돌린다 |
| `adg_cycles.py` | 앞 칸 규칙이 ADG 순환을 없애는가. `RULE=off` 로 대조군 |
| `goal_oscillation.py` | 목표 앞 왕복 정체 재현. 지금은 전부 완주해야 맞다 |
| `rule_numbers.py` · `axle_rule.py` · `soft_rule_sweep.py` | 규칙 후보별 합법쌍·접촉·여유 |
| `remeasure_adg_basis.py` | ADG 를 무엇으로 짓느냐에 따른 접촉 수 |
| `why_blocked.py` · `wait_hotspots.py` | 대기가 진짜 경합인가 · 어디서 나는가 |
| `speed_sweep.py` · `try_carry.py` · `try_swing5.py` | 속도·이어달리기·규칙 변형 쓸기 |

### 녹화를 읽는 것 — 실측

| | 무엇을 재나 |
|---|---|
| `cross_track.py` | 직진 중 횡방향 이탈. **`--diag` 를 먼저** 돌려 격자를 고른다 |
| `turn_error.py` | 회전 자세 오차. **세로/가로 분해가 핵심** — 예산을 먹는 건 가로다 |
| `axle_frame.py` | 회전 중 축 이탈이 진짜 밀림인지 좌표 프레임 오차인지 |
| `measure_turns.py` | 회전·전진이 **실제로 몇 초**인지 (계획 틱과 대조) |
| `motion_profile.py` | 멈춤의 정체 — 회전 / 대기 / 감속 / 순항 |
| `measure_seq.py` | 칸마다 멈추나 · 회전→전진 전환 비용 |

> **★ `cross_track.py --diag` 를 건너뛰지 말 것.** 격자를 못 찾으면 모든
> 녹화에서 최대가 `500.0 mm = pitch/2` 로 딱 떨어지는데, 그건 이탈이 큰 것이
> 아니라 **차선을 못 고른 것**이다. 1등과 2등의 격차를 봐야 한다.
>
> **★ 격자를 받는 도구에는 격자를 줄 것.** `PITCH` 를 안 주면 기본 1.2 로
> 환산한다. `motion_profile` 을 뺀 다섯 개가 `PITCH`(없으면 `PIBT_PITCH`)를
> 읽고 머리말에 `칸 ? m` 또는 `pitch ?` 를 찍으니 **첫 줄을 보고 시작할 것**.
> 틀리면 **칸을 세는 숫자만** 조용히 어긋난다 — 회전·자세 오차는 거리와
> 무관해 멀쩡하니 눈에 안 띈다. `motion_profile` 은 속도·시간만 보므로
> 격자와 무관하다.
