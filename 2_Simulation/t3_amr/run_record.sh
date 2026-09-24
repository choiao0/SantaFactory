#!/usr/bin/env bash
# ============================================================
# run_record.sh — 시연 영상 한 번에 (녹화 -> mp4)
#
#   bash run_record.sh                       pibt_h 12대 · **시드 104**, 10배속 73초 영상
#   bash run_record.sh 16                    16대 · 시드 104
#   bash run_record.sh 16 103                16대 · **시드 103**   ← 대수 다음이 시드
#   bash run_record.sh --seed 103            12대 · 시드 103
#   bash run_record.sh --planner pibt_h      같음 (명시)
#   bash run_record.sh --rebuild             씬 재빌드부터
#
#   ★ 시드 기본값은 **104** 다. 12대 3시간 창에서 랙·차체 접촉을 둘 다 0 으로
#     완주한 유일한 시드라 시연·회귀의 기준판으로 쓴다.
#     안 주면 `pibt_h.py` 의 모듈 상수 9 로 돌던 것을 여기서 막는다.
#
#   ☹ 시드를 바꾸면 `plan/traj_pibt_h/fleet_NN/` 의 계획은 **다른 시나리오**다
#     (디렉터리 이름에 대수만 박혀 있다). 주행은 in-process 로 다시 계획하니
#     옳지만, 영상·검증이 읽는 `trajectories.json` 은 안 맞는다.
#     머리말이 「계획은 시드 N 으로 만들어졌다」로 알려 준다. 맞추려면 REPLAN=1.
#
# `run.sh` 를 **고치지 않고 감싼다.** 하는 일 네 가지:
#   1. PIBT_SHOTS 등 촬영 환경변수를 넣는다
#   2. 촬영이 실제로 켜졌는지 **2분 안에 확인**하고, 안 켜졌으면 끊는다
#   3. 주행 (약 29분. Ctrl-C 로 언제든 끊어도 된다)
#   4. 프레임을 mp4 로 조립한다 — 끊어도 그 시점까지로 만든다
#
# ── 조절 ────────────────────────────────────────────────────
#   SHOT_STRIDE=20   몇 물리스텝마다 한 장 (기본 20)
#   WATCH_SEC=420    촬영 확인까지 대기 (기본 420초)
#   ISOLATE=0        GPU 격리 해제 (기본은 CUDA_VISIBLE_DEVICES=$GPU)
#   FINISH_GRACE=5   완주(post_quit) 표시 뒤 끊기까지 초 (기본 5, 0 = 즉시)
#   IDLE_KILL=300    프레임이 이만큼 안 늘면 끝난 것으로 보고 끊는다 (기본 300)
#   MIN_AGE=120      이보다 이른 완주 표시는 무시 (기본 120초 — 부팅만 20초)
#   SHOT_FPS=30      출력 fps (기본 30)
#   SHOT_EXT=png     png | jpg
#   RUN_TAG=이름     출력 폴더·파일 이름 (기본 시각)
#   VIDEO=0          조립 건너뛰고 프레임만 남긴다 (★ 캡처는 그대로 돈다)
#   CAPTURE=0        ★ 촬영을 **아예 끈다**. 계측 판·디스크 절약용
#   CAPTURE=fpv      ★ 1번(천장)을 끄고 **1인칭만** 찍는다. 시연 영상용
#                      — 1번 프레임 14 GB 를 안 쓴다. 검증 런에는 쓰지 말 것
#   WAIT_BUSY=3600   ★ 내 Kit 이 돌고 있으면 그만큼 기다린다 (기본 0 = 즉시 끊음)
#                    시드를 for 루프로 돌릴 때 반드시 준다
#   STRICT=0         촬영이 안 켜져도 끊지 않는다 (기본은 끊는다)
#   GPU=1            다른 GPU
#
#   영상 배속 = SHOT_FPS x SHOT_STRIDE / 60
#     기본 30x20/60 = 10배속 · sim 730초 -> 2,190장 -> 73초
#     5배속  SHOT_STRIDE=10   (프레임·디스크 2배)
#     20배속 SHOT_STRIDE=40   (프레임 절반)
#
# ── 왜 `script` 로 감싸나 ───────────────────────────────────
#   `... | tee 파일` 로 하면 stdout 이 파이프가 되어 블록 버퍼링된다.
#   4 KB 가 찰 때까지 화면이 비고 (실측: 4분씩 멈춰 보였다), `tail` 을 붙이면
#   EOF 까지 아무것도 안 나온다. `script` 는 pty 를 만들어 라인 버퍼링을
#   유지하면서 파일에도 남긴다 — 2번 확인이 그 파일을 읽는다.
#
# ── 쓰지 말아야 할 것 ───────────────────────────────────────
#   --lite         랙이 안 보인다. 측정용이다
#   STREAM=0       헤드리스라 뷰포트가 없다 -> 촬영 불가
#   PIBT_RENDER_EVERY>1  물리 뷰가 무효화된다 (2026-09-08 미해결)
#   -> 세 개가 들어오면 아래에서 거부한다
# ============================================================
set -uo pipefail

# ★ paths.sh 는 **자기 옆의 것**을 쓴다 (run.sh 와 같은 방식).
#   예전에는 `$HOME/khs/wh/paths.sh` 가 박혀 있었다. 저장소를 t3_amr 로 옮긴
#   뒤에도 그 줄이 남아 있어서, 여기서 돌리면 조용히 **옛 Santa 체크아웃의**
#   paths.sh 를 읽었다 — $W·$MAP·$PLAN 이 전부 남의 폴더를 가리킨다.
#   그쪽이 없으면 source 가 실패하는데 `set -e` 가 아니라 그냥 지나가고,
#   뒤에서 빈 변수로 엉뚱한 경로를 만든다. (2026-09-11)
[ -n "${VIRTUAL_ENV:-}" ] || source "${VENV:-$HOME/khs/venv}/bin/activate"
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/paths.sh"

ME="${USER:-$(id -un)}"
TAG="${RUN_TAG:-$(date +%Y%m%d_%H%M%S)}"
SHOT_STRIDE="${SHOT_STRIDE:-20}"
SHOT_FPS="${SHOT_FPS:-30}"
SHOT_EXT="${SHOT_EXT:-png}"
STRICT="${STRICT:-1}"
WATCH_SEC="${WATCH_SEC:-420}"
VIDEO="${VIDEO:-1}"
# ★ 촬영 자체를 끄는 스위치 (2026-09-17). `VIDEO=0` 은 **ffmpeg 조립만**
#   건너뛰고 PNG 캡처는 그대로 돈다 — 이름이 그렇게 읽히지 않아 실제로 그
#   함정에 걸렸다.
#
#   ☹ **속도 이득은 근거가 없다** (2026-09-17 정정). 처음에 「약 3배 빠르다」고
#     적었는데 `omni.renderercapture` 경고를 보고 추측한 것이었다. 재 보니
#     캡처 ON 30초/10초sim · OFF 40초/10초sim 으로 **오히려 느렸다** (판이
#     달라 직접 비교는 아니다). 끄는 이유는 디스크와 잡음이지 속도가 아니다.
#
#     `CAPTURE=0` 은 PNG 인코딩·쓰기만 끈다. **렌더는 그대로 돈다** —
#     STREAM=1 · PIBT_RENDER_EVERY=1 이라 매 물리 스텝마다 뷰포트를 그린다.
#     속도를 원하면 그쪽(STREAM=0)을 봐야 한다.
CAPTURE="${CAPTURE:-1}"
ISOLATE="${ISOLATE:-1}"

# ── GPU 격리 ────────────────────────────────────────────────
#   `--/renderer/activeGpu=$GPU` 는 **렌더러(Vulkan)만** 묶는다.
#   PhysX / warp / torch 쪽 CUDA 는 보이는 장치마다 primary context 를
#   하나씩 만든다 — 실측 2026-09-08 13:03: GPU0 518MiB, GPU1 436MiB,
#   GPU2 436MiB, GPU3 6449MiB. 1,2 는 일 안 하고 VRAM 만 잡고 있었다.
#   CUDA_VISIBLE_DEVICES 가 이걸 막는 유일한 수단이다.
#   Vulkan 열거는 CUDA_VISIBLE_DEVICES 를 따르지 않으므로 activeGpu 는
#   그대로 $GPU 를 쓴다. 렌더러가 엉뚱한 장치로 가면 ISOLATE=0 으로 끈다.
if [ "$ISOLATE" = "1" ]; then
    export CUDA_VISIBLE_DEVICES="$GPU"
fi

SHOTS="$OUT/shots_$TAG"
MP4="$OUT/demo_$TAG.mp4"

# ★★ 두 번째 시점 (2026-09-22, -264). `FPV_CAM` 이 비면 종전과 같다.
#   백엔드가 상단 키에서 `_fpv` 를 계산해 MinIO 에 있는지 보고 버튼을
#   띄운다. 그래서 **이름만** 지키면 되고 결과 페이로드는 안 바뀐다.
#   Cam_Overview 는 남쪽 62 m 에서 비스듬히 본다 — 위치와 높이가 한
#   화면에 들어와 시연용으로 맞다 (build_amr_scene_v2.py:288).
# ★ 기본은 **1인칭 주행 시점**이다 (2026-09-23). `Cam_Spot` 을
#   `PIBT_FPV_FOLLOW` 로봇 앞머리에 붙여 주행 방향을 본다
#   (`headless_pibt._fpv_track`).
#
#   조망 -> 3인칭 추종 -> 1인칭 순으로 옮겨 왔다. 조망은 1.5 m 짜리 AMR 이
#   점이라 못 썼고, 3인칭은 창고를 넓게 담아 렌더가 무거웠다.
#
#   되돌리려면:  PIBT_FPV_VIEW=chase              3인칭 추종
#               PIBT_FPV_FOLLOW=5                 특정 로봇을 따라간다
#               PIBT_FPV_FOLLOW=-1 FPV_CAM=/World/Cameras/Cam_Overview   조망
FPV_CAM="${FPV_CAM:-/World/Cameras/Cam_Spot}"
SHOTS_FPV="$OUT/shots_${TAG}_fpv"
MP4_FPV="$OUT/demo_${TAG}_fpv.mp4"
MYLOG="$LOGS/record_$TAG.log"
# [patch_record_seed] `--seed N` 을 **인자 목록에서 빼낸다** (2026-09-20).
#   남은 인자는 그대로 run.sh 로 가므로, 여기서 안 빼면 run.sh 가 모르는
#   플래그를 받는다. 위치 인자(아래)보다 먼저 처리해야 `run_record.sh --seed 7 20`
#   같은 순서도 받는다.
_PASS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --seed|-s) PIBT_SEED="${2:-}"; shift 2 ;;
        --seed=*)  PIBT_SEED="${1#*=}"; shift ;;
        *)         _PASS+=("$1"); shift ;;
    esac
done
set -- ${_PASS[@]+"${_PASS[@]}"}

# [patch_record_n] 첫 인자가 순수 정수면 로봇 대수로 먹는다
# [patch_record_seed] **두 번째** 순수 정수는 시드로 먹는다
#   bash run_record.sh 20 --rebuild  →  PIBT_N=20, run.sh 로는 --rebuild 만 간다
#   bash run_record.sh 16 103        →  16대 · 시드 103
#   bash run_record.sh --seed 103    →  대수는 기본값, 시드 103
#   대수를 안 주면 환경변수 PIBT_N, 그것도 없으면 12.
if [ $# -ge 1 ] && [[ "$1" =~ ^[0-9]+$ ]]; then
    PIBT_N="$1"; shift
    if [ $# -ge 1 ] && [[ "$1" =~ ^[0-9]+$ ]]; then
        PIBT_SEED="$1"; shift
    fi
fi
PIBT_N="${PIBT_N:-12}"
if [ "$PIBT_N" -lt 1 ] 2>/dev/null; then
    echo "★ 대수는 1 이상의 정수여야 합니다: $PIBT_N" >&2; exit 1
fi
export PIBT_N

# [patch_record_seed] ★ 시드 기본값 **104** (2026-09-20).
#
#   왜 여기서 정하나 — `pibt_h.py:_e()` 는 셸을 먼저 보고 없을 때만 모듈 상수
#   (`SEED`, 9)를 쓴다. 즉 **여기서 export 안 하면 9 로 돈다.** pitch·horizon 이
#   이미 같은 이유로 이 파일에서 기본값을 정하고 있고, 시드만 빠져 있었다.
#
#   왜 104 인가 — 12대 3시간 창에서 **랙·차체 접촉을 둘 다 0 으로 완주한
#   유일한 시드**다 (`s104_strict`, 24,882.4 s · 108,476 액션). 시연·회귀
#   기본판으로 이것을 쓴다.
#
#   ☹ 시드는 **주문 스트림과 배차**를 정한다. 출발 칸은 충전존 슬롯이라
#     시드와 무관하니 스폰은 안 틀어진다 (pibt_h.py:118 의 근거와 같다).
if ! [[ "${PIBT_SEED:-104}" =~ ^[0-9]+$ ]]; then
    echo "★ 시드는 0 이상의 정수여야 합니다: $PIBT_SEED" >&2; exit 1
fi
PIBT_SEED="${PIBT_SEED:-104}"
export PIBT_SEED

# ★ 격자·규칙을 **계획보다 먼저** 정한다 (2026-09-17, S15P21A106-224).
#
#   예전에는 이 두 줄이 187행쯤, 즉 REPLAN 계획 블록(105행) **뒤에** 있었다.
#   그래서 `REPLAN=1 bash run_record.sh` 가
#
#       계획   pibt_h.PITCH 기본값 1.2 로 선다 (PIBT_PITCH 가 아직 없다)
#       주행   PIBT_PITCH=1.0
#
#   로 갈렸다. 충전존 시작 슬롯이 pitch 에서 나오므로 (x [103.8, 106.2] vs
#   [103.5, 105.5, 107.5]) **무대 스폰이 주행 계획과 다른 자리**가 된다.
#   추종기가 자기 경로를 못 잡는 그 실패 모드다. 오류는 안 난다.
#
#   자세한 값·근거는 아래 원래 주석에 그대로 둔다.
export PIBT_FRONT_RULE="${PIBT_FRONT_RULE:-4}"
export PIBT_PITCH="${PIBT_PITCH:-1.0}"

# ★ 주행 스위치 한 벌 (2026-09-22). **백엔드가 띄우는 것이 이 파일이다**
#   (edge/recorder.py:104). 여기 안 걸면 백엔드 주행만 코드 기본값으로
#   도는데, 공차 0.05 는 isaac_drive.py:1633 이 「5판 중 2판이 차체
#   접촉으로 중단됐다」고 적어 둔 값이다.
#   ★ pitch·앞 칸 규칙을 **정한 뒤**에 읽는다 — 배너가 그 둘도 찍는다.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/switches.sh"

# [patch_record_n] 계획과 대수가 일치해야 한다 — 계획 디렉터리 이름에 대수가 박혀 있다.
#   안 맞으면 35초 부팅하고 계획 로드까지 간 뒤에야 죽는다. 0초에 막는다.
# [patch_record_n_fix] 계획 디렉터리는 0 패딩이다 — pibt_h.py 의 f"fleet_{n:02d}"
#   실측: ls plan/traj_pibt_h/ → fleet_01  fleet_12
PLAN_DIR="$PLAN/traj_pibt_h/fleet_$(printf '%02d' "$PIBT_N")"
# ★ REPLAN=1 이면 **이미 있어도** 다시 만든다 (2026-09-11 수정).
#   예전 조건은 `[ ! -d "$PLAN_DIR" ] && [ REPLAN = 1 ]` 이라, 계획이 이미
#   있으면 REPLAN=1 을 줘도 통째로 건너뛰었다. 이름은 "다시 계획" 인데 실제로는
#   "없으면 만든다" 였다. 맵을 새 창고로 바꾼 뒤 REPLAN=1 로 돌렸는데 옛 좌표
#   궤적이 그대로 재생되는 일이 여기서 나왔다.
#   기본값은 그대로 0 이므로, 안 주던 사람의 동작은 바뀌지 않는다.
if [ "${REPLAN:-0}" = "1" ]; then
    echo "── 계획 생성 (PIBT_N=$PIBT_N · PIBT_SEED=$PIBT_SEED) ──────"
    [ -d "$PLAN_DIR" ] && echo "  기존 계획을 지우고 다시 만듭니다: $PLAN_DIR"
    rm -rf "$PLAN_DIR"                     # 남은 옛 파일이 섞이지 않게
# [patch_record_n_fix] `--n` 을 넘겨야 한다. main.py:164 의 default 는 12다.
    ( cd "$W" && python amr/main.py plan --planner pibt_h --n "$PIBT_N" ) || exit 1
    cp -a "$W/v2/traj_pibt_h/." "$PLAN/traj_pibt_h/" || exit 1
    # [patch_record_seed] 어느 시드로 만든 계획인지 **남긴다**.
    #   계획 디렉터리 이름에는 대수만 박혀 있어서(`fleet_16`), 시드를 바꿔 돌면
    #   다른 시나리오의 `trajectories.json` 이 그대로 남는다. 파일이 없으면
    #   아래 검사가 「모름」으로 경고한다.
    echo "$PIBT_SEED" > "$PLAN_DIR/.seed" 2>/dev/null || true
    echo "── 계획 완료 ───────────────────────────────────────"
fi

# [patch_record_seed] ☹ **계획의 시드와 이번 판의 시드가 다르면 알린다** (2026-09-20).
#
#   주행은 `live_pibt` 가 in-process 로 다시 계획하므로 **주행 자체는 옳다.**
#   틀리는 것은 저장된 `trajectories.json` 을 읽는 쪽 — 씬 빌더·검증·영상이다.
#   둘을 같은 판으로 알고 비교하면 조용히 틀린다 (pibt_h.py:121 의 그 함정).
if [ -d "$PLAN_DIR" ]; then
    _PLAN_SEED="$(cat "$PLAN_DIR/.seed" 2>/dev/null || echo "")"
    if [ -z "$_PLAN_SEED" ]; then
        _SEED_NOTE="☹ 계획의 시드 **모름** (.seed 없음 — REPLAN=1 로 만들면 남는다)"
    elif [ "$_PLAN_SEED" != "$PIBT_SEED" ]; then
        _SEED_NOTE="☹☹ 계획은 시드 **$_PLAN_SEED** 로 만들어졌다 — 주행은 $PIBT_SEED"
    else
        _SEED_NOTE="계획도 같은 시드 ✓"
    fi
else
    _SEED_NOTE=""
fi
# ★ 궤적을 쓰면 계획 폴더가 필요 없다 (2026-09-22).
#   `PIBT_TRAJ` 는 `live_pibt.py:1084` 에서 **계획을 통째로 건너뛴다.** 그런데
#   아래 검사가 계획 폴더를 요구해서, 「궤적으로 돌리는데 계획이 없다」는 이유로
#   죽었다. 백엔드가 `scenario.trajectory` 를 보내는 경로(-261)가 정확히 그 모양이다.
#   검사를 없애지는 않는다 — 궤적이 없는 판은 종전대로 계획을 요구한다.
#   ★★ 건너뛰기만 하면 **씬을 못 짓는다** (-275, 2026-09-24 컨테이너 실측). `amr/main.py run` 이
#     스폰 자리를 이 폴더의 `starts.json`·`trajectories.json` 에서 읽는다 — 로컬에는 손으로 둔
#     `plan/` 이 있어 드러나지 않았다. 그래서 궤적 **첫 틱**으로 그 폴더를 만든다.
if [ -n "${PIBT_TRAJ:-}" ] && [ ! -d "$PLAN_DIR" ]; then
    case "$PIBT_TRAJ" in
        /*) _TJ0="$PIBT_TRAJ" ;;
        *)  _TJ0="$W/$PIBT_TRAJ" ;;
    esac
    echo "[preflight] 궤적 첫 틱으로 계획 폴더를 만듭니다 -> $PLAN_DIR"
    if ! ( cd "$W" && python path/fms_traj.py --plan-folder "$_TJ0" "$PLAN_DIR" ); then
        echo "★ 궤적에서 계획 폴더를 못 만들었습니다 — 위 오류를 보세요 ($_TJ0)" >&2
        exit 1
    fi
fi
if [ ! -d "$PLAN_DIR" ] && [ "${SKIP_PLAN_CHECK:-0}" != "1" ]; then
    echo "★ ${PIBT_N}대 계획이 없습니다: $PLAN_DIR" >&2
    echo "  먼저:  python amr/main.py plan --planner pibt_h --n $PIBT_N" >&2
    echo "         cp -a v2/traj_pibt_h/. plan/traj_pibt_h/" >&2
    echo "  또는:  REPLAN=1 bash run_record.sh $PIBT_N" >&2
    echo "  (검사만 끄려면 SKIP_PLAN_CHECK=1 — 계획이 없으면 주행이 실패합니다)" >&2
    exit 1
fi

ARGS=("$@")
[ ${#ARGS[@]} -eq 0 ] && ARGS=(--planner pibt_h)

# [patch_record_n_fix] `--n` 을 run.sh -> main.py run 까지 넘긴다
#   pibt_h.py:launch(n) 이 PIBT_STAGE="$STAGE/"+USD%n 을 쓴다 — 씬 USD 가
#   대수별이다. main.py run 이 씬 빌드까지 하므로(run.sh:49) --n 이 거기까지
#   가야 stage/pibt0N.usd 가 만들어진다. export PIBT_N 은 live_pibt.py 용이고,
#   둘 다 필요하다.
case " ${ARGS[*]} " in
    *" --n "*) ;;                       # 사용자가 직접 줬으면 그대로 둔다
    *) ARGS+=(--n "$PIBT_N") ;;
esac

# ── 들어오면 안 되는 조합 거부 ──────────────────────────────
for a in "${ARGS[@]}"; do
    if [ "$a" = "--lite" ]; then
        echo "★ --lite 는 랙을 숨깁니다 — 시연 영상에 쓸 수 없습니다."
        echo "  측정이 목적이면:  STREAM=0 bash run.sh --planner pibt_h --lite"
        exit 2
    fi
done
# ★ 촬영은 **뷰포트가 있어야** 한다. 2026-09-21 부터 `run.sh` 의 기본이
#   그림 없음(HEADLESS=1)으로 바뀌었으므로, 촬영 경로에서는 되돌려 놓는다.
#   안 되돌리면 run.sh 가 Kit 을 안 띄워 프레임이 0장 나온다.
# ── 렌더 경로 (2026-09-21) ──────────────────────────────────
# 기본은 **예전 그대로** Kit 을 띄운다. `run.sh` 의 기본이 그림 없음으로
# 바뀌었으므로 여기서 되돌려 놓는다 — 안 되돌리면 프레임이 0장 나온다.
#
# `HEADLESS=1` 로 주면 **새 경로**를 쓴다. 다른 점은 하나뿐이다.
#
#     기존       매 스텝 렌더 -> STRIDE 스텝마다 한 장 저장 (그린 것의 95% 버림)
#     HEADLESS=1 저장할 스텝에만 렌더                      (버리는 것이 없다)
#
# 파일명·조립 공식·배속 계산은 완전히 같다. 다만 **아직 실측 전이다** —
# 헤드리스 experience 에 활성 뷰포트가 없으면 리플리케이터로 넘어가는데,
# 거기서 막히면 긴 주행 끝에 0장이 나올 수 있다. 짧은 판으로 먼저 확인하라.
if [ "${HEADLESS:-0}" = "1" ]; then
    echo "[rec] ★ 새 경로: 저장할 스텝에만 렌더합니다 (HEADLESS=1)."
    echo "[rec]   아직 실측 전입니다. 짧은 판으로 프레임이 나오는지 먼저 보세요."
    export STREAM=0
else
    export HEADLESS=0
    export STREAM="${STREAM:-1}"
    if [ "$STREAM" = "0" ]; then
        echo "★ STREAM=0 은 WebRTC 만 끈 것이지만, 이 경로는 뷰포트가 필요합니다."
        echo "  더 빠른 촬영을 원하면:  HEADLESS=1 bash run_record.sh ..."
        exit 2
    fi
fi
if [ "${PIBT_RENDER_EVERY:-1}" != "1" ]; then
    echo "★ PIBT_RENDER_EVERY>1 은 물리 뷰를 무효화합니다 (2026-09-08 미해결)."
    echo "  주지 마세요. 지금은 이 값이 1 이어야 주행이 됩니다."
    exit 2
fi

# ── 촬영 환경변수 (live_pibt.py 가 읽는 이름) ───────────────
#   `live_pibt.py:191` 은 `PIBT_SHOTS` 가 **비면 아무것도 안 한다.** 그래서
#   촬영을 끄는 방법은 이 값을 비우는 것뿐이다 — `VIDEO=0` 으로는 안 꺼진다.
# ★ `CAPTURE=fpv` — **1번(천장)을 끄고 1인칭만** 찍는다 (2026-09-23).
#   옛 이름 `side` 도 받는다 — 백엔드가 키를 `_side` 에서 `_fpv` 로 바꾸기 전에
#   쓰던 이름이라 손에 익은 사람이 있다.
#   시연 영상만 뽑을 때 쓴다. 1번 캡처 자체는 싸지만(뷰포트 비동기, 약
#   1.0 ms/step) **프레임 디스크가 크다** — 13대 10분 판에서 약 14 GB 다.
#   ☹ 검증 런에는 쓰지 말 것. 백엔드가 기다리는 것은 1번(`demo_<run_id>.mp4`)이다.
if [ "$CAPTURE" = "0" ] || [ "$CAPTURE" = "fpv" ] || [ "$CAPTURE" = "side" ]; then
    export PIBT_SHOTS=""
else
    export PIBT_SHOTS="$SHOTS"
fi
# ★ 측면 — 헤드리스(리플리케이터) 경로에서만 찍는다. 뷰포트 경로는
#   활성 뷰포트 하나뿐이라 두 시점을 못 받는다.
if [ "$CAPTURE" = "0" ] || [ -z "$FPV_CAM" ] || [ "${HEADLESS:-0}" != "1" ]; then
    export PIBT_SHOTS_FPV=""
    export PIBT_CAMERA_FPV=""
    [ -n "$FPV_CAM" ] && [ "${HEADLESS:-0}" != "1" ] && \
        echo "[rec] 2번영상은 HEADLESS=1 에서만 찍습니다 — 이번 판은 1번만."
else
    export PIBT_SHOTS_FPV="$SHOTS_FPV"
    export PIBT_CAMERA_FPV="$FPV_CAM"
    # 근접 화면이라 조망만큼 클 필요가 없다. **복사량이 곧 비용**이다 —
    # 1280x720 두 시점이 28 ms/step(배속 0.60)이었다 (2026-09-23 실측).
    export PIBT_FPV_RES="${PIBT_FPV_RES:-960x540}"
    # ★ `auto` — 초반에 가장 많이 움직인 로봇을 고른다 (2026-09-23).
    #   여기가 `0` 으로 박혀 있어서 `headless_pibt` 의 auto 기본값이 못 닿았다.
    #   0번은 충전존에서 시작해 한참 서 있어 영상이 33초 동안 안 바뀌었다
    #   (`cam1` 실측: #0 도 #100 도 (103.50, 48.50) 그대로).
    export PIBT_FPV_FOLLOW="${PIBT_FPV_FOLLOW:-auto}"
    # ★ 기본 **1인칭**(대시캠). 3인칭 추종은 창고를 넓게 담아 렌더가 무겁다.
    #   되돌리려면:  PIBT_FPV_VIEW=chase PIBT_FPV_DIST=6
    export PIBT_FPV_VIEW="${PIBT_FPV_VIEW:-fpv}"
    export PIBT_FPV_DIST="${PIBT_FPV_DIST:-6}"
    # 렉이 심하면 올린다 — 측면 복사가 그만큼 나뉜다 (대신 측면만 그 배수로 빨라짐)
    export PIBT_FPV_EVERY="${PIBT_FPV_EVERY:-1}"
fi
export PIBT_SHOT_STRIDE="$SHOT_STRIDE"
export PIBT_SHOT_FPS="$SHOT_FPS"
export PIBT_SHOT_EXT="$SHOT_EXT"

# ── ADG 앞 칸 규칙 · 격자 (S15P21A106-204) ──────────────────
#   ★ `pibt_h.py:launch()` 의 env 목록에 **있는 이름만** Isaac 까지 간다.
#     `PIBT_FRONT_RULE` 과 `PIBT_PITCH` 는 거기 `_e(...)` 로 들어 있어 여기
#     값이 이긴다. 목록에 없는 이름은 export 해도 전달조차 안 된다
#     (README 「함정」· pibt_h.py:120 실측).
#
#   규칙은 계획기와 ADG 가 **같은 칸**을 보게 만든다. 전에는 계획기가 3칸
#   모델로 풀고 ADG 는 실제 스윕으로 지어서, pitch 1.0 에서 ADG 에 순환이
#   생겼다 (= 주행 전 데드락). 20시드 측정: 규칙 없이 순환 10/20, 규칙을
#   켜면 0/20.
#
#   ★ 규칙은 **pitch 게이팅**을 받는다. 1.2 에서는 무엇을 넣든 꺼진다 —
#     칸이 넓어 규칙이 필요 없기 때문이다. 규칙이 사는 곳은 1.0~1.1 이다.
#
#   ── 기본 격자를 1.0 으로 둔다 ────────────────────────────
#   바뀐 ADG 로 주행하는 것이 지금의 기본 동작이다. 1.2 로 두면 규칙이 게이팅에
#   걸려 꺼지므로, 기본값으로는 **바뀐 ADG 를 영영 못 본다.**
#
#   ★ 1.0 은 2칸 점유 + 스윙 3칸 모델의 **유효 구간(1.117~2.220) 밖**이다.
#     `RobotGeom.describe()` 가 로그에 「★구간 밖」과 함께
#     「회전 스윙 : ★모델 밖 [(5,6), (6,5)]」 을 찍는다. 그 두 칸이 바로
#     4칸 규칙이 덮는 칸이다 — front_cells = [(4,6),(5,6),(6,4),(6,5)].
#     즉 경고는 "규칙 없이 쓰면 안 된다" 는 뜻이지 설정 오류가 아니다.
#
#   ★ 1.0 채택은 **아직 확정이 아니다.** 1.0 vs 1.2 포화 처리량이 남아 있고
#     거기서 1.2 로 되돌아갈 수 있다. 그때는 이 한 줄만 1.2 로 바꾸면 된다.
#     1.2 로 한 판 돌리려면:  PIBT_PITCH=1.2 bash run_record.sh
#
# ★ 이 두 줄은 위(계획 블록 앞)로 옮겼다 — 여기 두면 REPLAN 계획이 기본값
#   1.2 로 서고 주행만 1.0 이 된다 (2026-09-17). 값·근거는 위 주석 그대로다.

# 규칙을 켜 달라고 했는데 격자가 게이팅 구간이면, 29분을 쓰고 나서 "규칙이
# 안 걸렸네" 를 깨닫는 것이 가장 나쁘다. 0초에 알린다.
RULE_LIVE="예"
case "$PIBT_FRONT_RULE" in
    off|0|no|"") RULE_LIVE="아니오 (규칙 없음)" ;;
    *) awk -v p="$PIBT_PITCH" 'BEGIN{exit !(p >= 1.15)}' && \
           RULE_LIVE="아니오 — pitch $PIBT_PITCH 는 게이팅 구간" ;;
esac

SPEED=$(awk -v s="$SHOT_STRIDE" -v f="$SHOT_FPS" 'BEGIN{printf "%.1f", s*f/60}')
EXPN=$(awk -v s="$SHOT_STRIDE" 'BEGIN{printf "%d", 43800/s}')
EXPSEC=$(awk -v n="$EXPN" -v f="$SHOT_FPS" 'BEGIN{printf "%d", n/f}')

# ── 띄우기 전 검사 (2026-09-22) ─────────────────────────────
#   Isaac 을 45초 띄운 뒤에야 드러나던 둘을 여기서 0.1초에 잡는다.
if [ -n "${PIBT_TRAJ:-}" ]; then
    # ① 궤적 파일이 실제로 있나.
    #    `live_pibt.py:1086` 은 **절대경로가 아니면** $W 를 붙인다. 그래서
    #    `PIBT_TRAJ="$W/..."` 를 $W 가 빈 채로 쓰면 "/docs/..." 가 되고,
    #    맨 앞 슬래시 때문에 절대경로로 보여 $W 가 안 붙는다.
    case "$PIBT_TRAJ" in
        /*) _TJ="$PIBT_TRAJ" ;;
        *)  _TJ="$W/$PIBT_TRAJ" ;;
    esac
    if [ ! -f "$_TJ" ]; then
        echo "★ 궤적 파일이 없습니다: $_TJ"
        echo "  PIBT_TRAJ=$PIBT_TRAJ"
        [ -z "${W:-}" ] && echo "  ☹ \$W 가 비어 있습니다 — source paths.sh 를 먼저 하세요."
        echo "  ※ \$W 기준 **상대경로**로 주는 편이 안전합니다:"
        echo "      export PIBT_TRAJ=\"docs/모음/r13_peak10/trajectories.json\""
        exit 1
    fi
    echo "[preflight] 궤적 확인 — $_TJ"

    # ② 앞 칸 규칙 4 + ADG_RANK 없음 = ADG 순환 (fms_traj.build 독스트링).
    if [ "$PIBT_FRONT_RULE" = "4" ] && [ -z "${PIBT_ADG_RANK:-}" ]; then
        echo "★ 궤적 재생인데 PIBT_FRONT_RULE=4 이고 PIBT_ADG_RANK 가 없습니다."
        echo "  이 조합은 **ADG 순환**으로 죽습니다 (앞 2칸은 비순환 · 4칸은 순환)."
        echo "  둘 중 하나를 주세요:"
        echo "      export PIBT_ADG_RANK=1      # 틱 순위로 편다 (259 이상)"
        echo "      export PIBT_FRONT_RULE=2    # 궤적 발자국에 맞춘다"
        exit 1
    fi
fi

echo "════════════════════════════════════════════════════"
echo " run_record  $TAG"
echo "  인자        ${ARGS[*]}"
# [patch_record_n] 플래그가 걸렸는지 로그로 증명한다 (규칙 1번)
echo "  대수        ${PIBT_N}대"
# [patch_record_seed] 시드도 찍는다 — 안 찍으면 어느 판인지 나중에 못 가린다
echo "  시드        ${PIBT_SEED}   (기본 104)"
echo "  계획        $PLAN_DIR"
[ -n "${_SEED_NOTE:-}" ] && echo "              $_SEED_NOTE"
# 플래그가 실제로 걸렸는지 로그로 증명한다 (규칙 1번).
#   '규칙 적용' 이 '아니오' 인데 규칙을 기대했다면 지금 끊는 편이 낫다.
echo "  격자        pitch $PIBT_PITCH   (기본 1.0 — 바뀐 ADG 가 사는 격자)"
echo "  앞 칸 규칙  PIBT_FRONT_RULE=$PIBT_FRONT_RULE   규칙 적용 $RULE_LIVE"
case "$RULE_LIVE" in
    아니오*게이팅*)
        echo "              ※ pitch $PIBT_PITCH 는 칸이 넓어 규칙이 필요 없는 구간입니다."
        echo "                옛 ADG 로 도는 판이고, 그게 의도였다면 그대로 두세요."
        ;;
esac
if [ "$PIBT_N" -gt 16 ]; then
    echo "  ※ 충전존의 서쪽헤딩 슬롯이 2.4 m 간격에서 16개입니다."
    echo "    ${PIBT_N}대면 CHARGE_STEP_Y=1.2 로 계획해야 할 수 있습니다."
fi
if [ "$PIBT_N" != "12" ]; then
    echo "  ※ 아래 '예상' 줄은 12대 기준(43,800스텝)이라 부정확합니다."
fi
echo "  프레임      $SHOTS"
echo "  영상        $MP4"
echo "  로그        $MYLOG"
if [ "$CAPTURE" = "fpv" ] || [ "$CAPTURE" = "side" ]; then
    echo "  설정        ★ 1번(천장) 꺼짐 (CAPTURE=fpv) — 1인칭만 만듭니다"
fi
if [ "$CAPTURE" = "0" ]; then
    echo "  설정        ★ 촬영 꺼짐 (CAPTURE=0) — 프레임도 영상도 안 만듭니다"
else
    echo "  설정        ${SHOT_STRIDE}스텝마다 · ${SHOT_FPS}fps · $SHOT_EXT · GPU $GPU"
fi
echo "  예상        약 ${EXPN}장 -> ${EXPSEC}초 영상 = ${SPEED}배속 · 주행 약 29분"
echo "════════════════════════════════════════════════════"

command -v ffmpeg >/dev/null 2>&1 || \
    echo "  ★ ffmpeg 이 없습니다 — 프레임만 남고 조립은 못 합니다"
df -h --output=avail "$OUT" 2>/dev/null | tail -1 | sed 's/^/  남은 디스크 /'
# ★ 패턴에 `bin/` 을 넣고 자기 pid·부모를 제외한다.
#   `-f 'isaacsim isaacsim.exp'` 만으로는 **그 문구가 들어간 자기 셸**까지
#   잡힌다 (실측: 이 스크립트를 부른 bash 의 명령줄에 걸렸다).
KITPAT='bin/isaacsim isaacsim\.exp'
#   그리고 **실제 프로그램 이름까지 본다** — 패턴만 보면 그 문구가 들어간
#   조상 셸까지 걸린다 (실측). Isaac 본체는 comm 이 python* 이다.
_busy_pids() {
    local _out="" _p
    for _p in $(pgrep -u "$ME" -f "$KITPAT" 2>/dev/null); do
        [ "$_p" = "$$" ] && continue
        case "$(cat /proc/$_p/comm 2>/dev/null)" in
            python*|isaacsim*|kit*) _out="$_out $_p" ;;
        esac
    done
    printf '%s' "$_out"
}
BUSY="$(_busy_pids)"
# ★ 배치로 여러 시드를 도는 경우 (2026-09-17). 예전에는 Kit 이 하나라도
#   돌고 있으면 **즉시 exit 2** 였다. 그래서
#
#       for S in 7 14 101 103 104; do PIBT_SEED=$S bash run_record.sh 12; done
#   [patch_record_seed] 이제 더 짧게도 쓴다 — 둘 다 같은 뜻이다
#       for S in 7 14 101 103 104; do WAIT_BUSY=3600 bash run_record.sh 12 $S; done
#
#   이 앞 판이 아직 도는 동안 **1초 안에 다섯 번 튕겼다.** 로그만 다섯 벌
#   남고 주행은 하나도 안 했다. 실제로 그렇게 날렸다.
#
#   `WAIT_BUSY=<초>` 를 주면 그동안 10초마다 다시 본다. 기본 0 은 옛 동작이라
#   혼자 돌리는 사람의 경험은 안 바뀐다.
WAIT_BUSY="${WAIT_BUSY:-0}"
if [ -n "$BUSY" ] && [ "$WAIT_BUSY" != "0" ]; then
    echo "  ★ 내 Kit 이 돌고 있습니다 — 최대 ${WAIT_BUSY}초 기다립니다"
    _t=0
    while [ -n "$BUSY" ] && [ "$_t" -lt "$WAIT_BUSY" ]; do
        sleep 10
        _t=$((_t + 10))
        BUSY="$(_busy_pids)"
    done
    if [ -z "$BUSY" ]; then
        echo "  비었습니다 (${_t}초 기다림). 시작합니다"
    else
        echo "  ${WAIT_BUSY}초를 기다렸는데 아직 돕니다."
    fi
fi
if [ -n "$BUSY" ]; then
    echo "  ★ 내 Kit 이 이미 돌고 있습니다:"
    for p in $BUSY; do
        ps -o pid=,args= -p "$p" 2>/dev/null | cut -c1-95 | sed 's/^/     /'
    done
    echo "     끝나기를 기다리거나 종료하세요:"
    echo "       pkill -u \$USER -INT -f 'bin/isaacsim isaacsim.exp'"
    exit 2
fi
mkdir -p "$SHOTS" || { echo "★ $SHOTS 를 만들 수 없습니다"; exit 1; }
echo

# ── 조립 — EXIT 에 걸어 Ctrl-C 로 끊어도 만든다 ─────────────
# ★ 시점이 둘이 될 수 있어 인자로 받는다 (-264). 안 주면 종전과 같다.
assemble() {
    local SHOTS="${1:-$SHOTS}" MP4="${2:-$MP4}" WHAT="${3:-}"
    local n
    # 촬영을 **일부러** 껐으면 「프레임이 0장입니다」가 오해를 부른다 —
    # 촬영이 실패한 것처럼 읽히고, 실제로 그 아래 줄이 verify_start 를
    # 의심하라고 시킨다. 껐을 때는 껐다고 말한다.
    if [ "$CAPTURE" = "0" ]; then
        echo
        echo "──────────── 조립 ────────────"
        echo "CAPTURE=0 — 촬영을 끄고 돌았습니다. 만들 프레임이 없습니다."
        rmdir "$SHOTS" 2>/dev/null
        return 0
    fi
    n=$(find "$SHOTS" -maxdepth 1 -name "f_*.$SHOT_EXT" 2>/dev/null | wc -l)
    echo
    echo "──────────── 조립 ${WHAT}────────────"
    if [ "$n" -eq 0 ]; then
        echo "프레임이 0장입니다."
        echo "  로그에서 확인:  grep -a '캡처' \"$MYLOG\""
        echo "  verify_start 를 통과해야 촬영이 시작됩니다."
        rmdir "$SHOTS" 2>/dev/null
        return 0
    fi
    if [ "$VIDEO" != "1" ]; then
        echo "VIDEO=0 — 조립 건너뜀. 프레임 ${n}장: $SHOTS"
        return 0
    fi
    if ! command -v ffmpeg >/dev/null 2>&1; then
        echo "ffmpeg 이 없습니다. 프레임 ${n}장: $SHOTS"
        return 0
    fi
    echo "프레임 ${n}장 -> $MP4"
    if ffmpeg -y -loglevel warning -stats \
              -framerate "$SHOT_FPS" -pattern_type glob \
              -i "$SHOTS/f_*.$SHOT_EXT" \
              -c:v libx264 -pix_fmt yuv420p -crf 20 "$MP4"; then
        echo
        echo "✔ $MP4"
        awk -v n="$n" -v f="$SHOT_FPS" -v s="$SPEED" \
            'BEGIN{printf "  길이 %.0f초 · 프레임 %d장 · %s배속\n", n/f, n, s}'
        du -sh "$MP4" "$SHOTS" 2>/dev/null | sed 's/^/  /'
        echo "  프레임을 지우려면:  rm -rf $SHOTS"
    else
        echo "★ ffmpeg 실패. 프레임은 남아 있습니다: $SHOTS"
        echo "  수동:  cd $SHOTS && ffmpeg -framerate $SHOT_FPS \\"
        echo "           -pattern_type glob -i 'f_*.$SHOT_EXT' \\"
        echo "           -c:v libx264 -pix_fmt yuv420p -crf 20 $MP4"
    fi
}
# ── 감시 서브셸 정리 — ★ 반드시 trap 안에서 ───────────────
#   `( ... ) &` 로 띄운 서브셸은 **SIGINT 를 무시한다** (POSIX: 비대화형 셸의
#   비동기 목록). 그래서 Ctrl-C 를 치면 script·Isaac·이 스크립트는 죽는데 감시
#   둘은 살아남는다. 살아남은 옛 감시가 자기 옛 폴더(38장)를 300초 세다가
#   `pkill -f` 로 **다음 런의 Isaac 을 죽였다** (2026-09-08 15:44 실측).
#   두 가지로 막는다: (1) 여기서 trap 으로 반드시 죽인다,
#   (2) 감시는 매 회 부모 생존을 확인하고, 죽일 대상도 패턴이 아니라
#       **자기 script 의 자손**으로 한정한다 (아래 _desc).
WATCH=""; FINWATCH=""; SCRIPT_PID=""
cleanup() {
    [ -n "$WATCH" ]    && kill "$WATCH"    2>/dev/null
    [ -n "$FINWATCH" ] && kill "$FINWATCH" 2>/dev/null
    # Ctrl-C 로 들어왔으면 script/Isaac 이 아직 죽는 중일 수 있다. 프레임을 다 쓰고
    # GPU 를 놓을 때까지 잠깐 기다린 뒤 조립한다 — 안 그러면 ffmpeg 이 쓰는 중인
    # PNG 를 읽는다.
    if [ -n "$SCRIPT_PID" ] && kill -0 "$SCRIPT_PID" 2>/dev/null; then
        _kill_mine INT
        for _ in $(seq 25); do sleep 1; kill -0 "$SCRIPT_PID" 2>/dev/null || break; done
        kill -0 "$SCRIPT_PID" 2>/dev/null && { _kill_mine KILL; kill -KILL "$SCRIPT_PID" 2>/dev/null; }
    fi
    # `CAPTURE=fpv` 면 1번은 애초에 안 찍었다 — 「0장입니다」로 오해시키지 않는다.
    case "$CAPTURE" in fpv|side) ;; *) assemble "$SHOTS" "$MP4" "1번(천장) " ;; esac
    # ★ 측면이 켜져 있으면 이어서 만든다. 프레임이 0장이면 조용히 지나간다.
    #   업로드가 상단 -> 측면 순서로 기다리므로 여기서도 상단을 먼저 만든다.
    [ -n "${PIBT_SHOTS_FPV:-}" ] && assemble "$SHOTS_FPV" "$MP4_FPV" "2번영상(1인칭) "
}
trap cleanup EXIT
trap 'exit 130' INT TERM

# 자손 PID 나열 (재귀). 패턴 매칭 대신 이걸로 죽인다 — 남의 런·다른 팀을 안 건드린다.
_desc() {
    local c
    for c in $(pgrep -P "$1" 2>/dev/null); do
        echo "$c"; _desc "$c"
    done
}
_kit_alive() {                 # 내 script 의 자손 중 Kit 본체가 있나
    local p
    [ -n "$SCRIPT_PID" ] || return 1
    for p in $(_desc "$SCRIPT_PID"); do
        case "$(cat /proc/$p/comm 2>/dev/null)" in
            python*|isaacsim*|kit*) return 0 ;;
        esac
    done
    return 1
}
_kill_mine() {                 # $1 = 신호. 내 script 의 자손 전부에게
    local p
    for p in $(_desc "$SCRIPT_PID"); do kill "-$1" "$p" 2>/dev/null; done
}
_parent_gone() { ! kill -0 "$MAIN_PID" 2>/dev/null; }
MAIN_PID=$$

# ── 주행을 먼저 띄운다 — 감시가 그 PID 의 자손을 봐야 하므로 ─────────
# ★ `SHOTS=0` 은 **자식에만** 준다 (이 스크립트의 $SHOTS 는 mkdir·감시·조립이 쓴다).
#   `run.sh` 는 `SHOTS`/`SHOT_*` 를 export 하는데 `live_pibt.py` 는 `PIBT_*` 를 읽는다
#   (접두사 불일치, 2026-09-08 확인). `SHOTS=0` 이면 run.sh 가 그 분기를 통째로 건너뛴다.
# ★ `-f` (flush) — 없으면 `script` 가 typescript 를 블록 버퍼링해서 감시가 읽는
#   로그가 수 분 늦는다 (2026-09-08 15:13 런에서 90초 경로를 못 잡은 원인).
script -q -f -e -c "SHOTS=0 bash \"$W/run.sh\" ${ARGS[*]}" "$MYLOG" &
SCRIPT_PID=$!

# ── 촬영이 켜졌는지 확인 ────────────────────────────────────
#   안 켜진 채로 29분을 버리는 것이 가장 나쁘다.
#   ★ 로그를 읽지 않고 **프레임 폴더를 센다.** `script` 의 typescript 는
#     즉시 flush 되지 않아서 로그 기반 확인은 조용히 통과해버린다 (실측).
#     프레임은 실제 산출물이므로 거짓 통과가 없다.
#   ★ 150초는 너무 짧았다 (2026-09-08 13:04, 정상 런을 끊었다). Kit 부팅 +
#     USD 로드 + play 전 프레임 대기까지 합쳐 첫 장까지 5분 넘게 걸린다.
#     420초로 늘렸다. 그래도 첫 장이 없으면 촬영이 정말 꺼진 것이다.
( # ★ 촬영을 **일부러** 껐으면 이 감시는 돌면 안 된다 (2026-09-17).
  #   프레임도 「캡처 ON」도 영영 안 나오므로 ${WATCH_SEC}초에 무조건 걸려
  #   STRICT=1 기본값으로 **판을 죽인다.** 계측 판이 7분마다 끊긴다.
  [ "$CAPTURE" = "0" ] && exit 0
  # `CAPTURE=fpv` 면 1번 폴더는 영영 비어 있다 — 1인칭 폴더를 본다.
  _WSHOTS="$SHOTS"
  case "$CAPTURE" in fpv|side) _WSHOTS="$SHOTS_FPV" ;; esac
  sleep "$WATCH_SEC"
  _parent_gone && exit 0                                   # 부모가 죽었으면 나도 끝
  n=$(find "$_WSHOTS" -maxdepth 1 -name "f_*.$SHOT_EXT" 2>/dev/null | wc -l)
  if [ "$n" -gt 0 ]; then exit 0; fi                       # 촬영 중
  # ★ 「촬영 ON」은 헤드리스 경로(`headless_pibt.py:226,242`)의 말이다.
  #   안 보면 HEADLESS=1 판이 ${WATCH_SEC}초에 무조건 끊긴다 (2026-09-22).
  if grep -aq "캡처 ON\|촬영 ON" "$MYLOG" 2>/dev/null; then exit 0; fi
  if grep -aq "전원 완주\|주행 종료\|시작 pose 불일치\|계획 정체\|겹침" \
       "$MYLOG" 2>/dev/null; then exit 0; fi               # 다른 이유로 끝났다
  echo
  echo "★★★ ${WATCH_SEC}초가 지났는데 프레임이 0장입니다 — 촬영이 꺼진 상태입니다."
  echo "     $SHOTS"
  if [ "$STRICT" = "1" ]; then
      echo "     STRICT=1 이므로 끊습니다 (29분을 버리지 않기 위해)."
      echo "     확인:  grep -a '캡처\\|뷰포트' \"$MYLOG\""
      _kill_mine INT
  else
      echo "     STRICT=0 이므로 계속합니다. 영상은 안 나옵니다."
  fi ) &
WATCH=$!

# ── 완주 후 안 죽는 것을 끊는다 ─────────────────────────────
#   실측 2026-09-08 04:50 — `post_quit` 이 나간 뒤 32 ms 만에
#     [carb.windowing-glfw.plugin] GLFW initialization failed.
#     [carb] Failed to startup plugin carb.windowing-glfw.plugin
#   이 찍히고 프로세스가 안 끝난다. `--no-window` 인데 종료 경로에서 윈도잉
#   플러그인을 다시 올리려다 실패하고 멈춘다. 그래서 사람이 Ctrl-C 를 쳐야 했다.
#
#   신호를 무엇으로 잡나 — 세 개를 함께 본다:
#     1. Carb 자체 로그 (무버퍼! typescript 와 달리 즉시 flush 된다)
#     2. typescript (버퍼링돼 늦게 보이지만, 있으면 확실하다)
#     3. 프레임 정체 — 위 둘을 못 봐도 캡처가 멈추면 주행은 끝난 것이다
#
#   ★ typescript 만 믿으면 안 된다 — 즉시 flush 되지 않는다 (이 파일 위쪽 실측).
START_TS=$(date +%s)
MIN_AGE="${MIN_AGE:-120}"             # 이보다 이른 완주 표시는 믿지 않는다 (부팅만 20초)
FINISH_GRACE="${FINISH_GRACE:-5}"     # 완주 표시 뒤 이만큼만 기다린다 (마지막 PNG 비동기 쓰기 몫).
                                      # 90초였는데 정상 종료가 성공한 적이 한 번도 없어 줄였다 (2026-09-08).
                                      # 0 으로 주면 즉시 끊는다.
IDLE_KILL="${IDLE_KILL:-300}"         # 프레임이 이만큼 안 늘면 끝난 것으로 본다
POLL=2                                 # 표시 확인 주기. script -f 라 typescript 가 즉시 반영된다
SLOW_EVERY=7                           # 무거운 확인(Carb 로그 grep · 프레임 세기)은 7회마다 = 약 14초


( marker_at=0; idle=0; prev=-1; slow=0; n=0
  while sleep "$POLL"; do
      _parent_gone && exit 0                     # ★ 부모(run_record)가 죽었으면 나도 끝 — 고아 금지
      _kit_alive || exit 0                       # 스스로 잘 끝났다

      # ── 매 회(2초): 완주 표시 — 이것만 빠르면 된다 ──────────
      seen=0
      if [ "$marker_at" = 0 ]; then
          # 「주행 종료」는 헤드리스 경로의 완주 표시 (`headless_pibt.py:369`).
          grep -aq "post_quit\|전원 완주\|주행 종료" "$MYLOG" 2>/dev/null && seen=1
      fi

      # ── 7회마다(약 14초): 무거운 확인 ───────────────────────
      #   ★ 프레임 세기는 표시 게이트도 쓰므로 `n` 이 늦게 갱신되면 첫 표시를
      #     한 주기 놓친다. 표시를 본 회차에는 즉시 한 번 더 센다 (아래).
      slow=$((slow + 1))
      if [ "$seen" = 1 ] || [ "$slow" -ge "$SLOW_EVERY" ]; then
          [ "$slow" -ge "$SLOW_EVERY" ] && slow=0
          n=$(find "$SHOTS" -maxdepth 1 -name "f_*.$SHOT_EXT" 2>/dev/null | wc -l)
          if [ "$slow" = 0 ]; then                 # 정주기 회차에서만 정체를 센다
              if [ "$n" -gt 0 ] && [ "$n" = "$prev" ]; then
                  idle=$((idle + POLL * SLOW_EVERY))
              else
                  idle=0
              fi
              prev="$n"
          fi
      fi
      # ★★ Carb 로그(`~/.nvidia-omniverse/logs/Kit/*/kit_*.log`)는 **보지 않는다.**
      #   `-mmin -10` 으로 훑었더니 **직전 런의 로그**에 있는 `post_quit` 을 읽고
      #   부팅 20초에 정상 런을 끊었다 (2026-09-08 23:42 실측: app ready 19.76s 직후).
      #   그 파일은 이번 런의 것인지 구분되지 않는다. 원래 Carb 로그를 본 이유는
      #   typescript 가 버퍼링돼 늦어서였는데 그건 `script -f` 로 해결됐다 —
      #   우회로가 남아서 해가 됐다. typescript 는 이번 런만 담으므로 모호함이 없다.

      # ★ 정상 완주는 **반드시 프레임이 있다.** 프레임 0장에서 온 표시는 이번 런의
      #   것이 아니거나 촬영이 꺼진 것이다 — 어느 쪽이든 이 경로로 끊지 않는다
      #   (촬영이 꺼진 경우는 위쪽 WATCH_SEC 감시가 담당한다).
      if [ "$seen" = 1 ] && [ "$n" -eq 0 ]; then
          seen=0
      fi
      # ★ 부팅만 해도 20초다. 그보다 이른 표시는 믿지 않는다.
      if [ "$seen" = 1 ] && [ $(( $(date +%s) - START_TS )) -lt "$MIN_AGE" ]; then
          seen=0
      fi
      [ "$seen" = 1 ] && [ "$marker_at" = 0 ] && marker_at=$(date +%s)

      why=""
      if [ "$marker_at" != 0 ] \
         && [ $(( $(date +%s) - marker_at )) -ge "$FINISH_GRACE" ]; then
          why="완주 표시 뒤 ${FINISH_GRACE}초가 지났는데 프로세스가 남아 있습니다"
      elif [ "$idle" -ge "$IDLE_KILL" ]; then
          why="프레임이 ${IDLE_KILL}초 동안 ${n}장에서 안 늘었습니다"
      fi
      [ -z "$why" ] && continue

      # `script` 가 터미널을 raw 모드로 잡고 있어 `\n` 만 찍으면 줄이 오른쪽으로
      # 밀린다 (2026-09-08 실측). `\r\n` 으로 찍는다.
      say() { printf '%s\r\n' "$*"; }
      say
      say "──────────── 자동 종료 ────────────"
      say "$why."
      say "Kit 종료 지연으로 보고 끊습니다 (GLFW 종료 경로 결함, 2026-09-08 실측)."
      say "프레임은 남아 있으니 영상은 그대로 만들어집니다."
      _kill_mine INT                             # 내 자손에게만
      for _ in $(seq 20); do sleep 1; _kit_alive || break; done
      if _kit_alive; then
          say "SIGINT 로 안 죽어 SIGKILL 을 보냅니다."
          _kill_mine KILL
      fi
      exit 0
  done ) &
FINWATCH=$!

# ── 주행이 끝나기를 기다린다 (script 는 위에서 이미 띄웠다) ──
wait "$SCRIPT_PID"
rc=$?
echo
echo "Isaac 종료 (코드 $rc)"
exit "$rc"
