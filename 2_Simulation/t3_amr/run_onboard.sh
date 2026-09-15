#!/usr/bin/env bash
# ============================================================
# run_onboard.sh — 가장 많이 움직이는 AMR 시점에서 진행방향을 녹화한다
#
#     bash run_onboard.sh                    주행 시점 (기본)
#     bash run_onboard.sh --mode chase       뒤 위에서 따라가며
#     bash run_onboard.sh --amr 7            로봇을 직접 지정 (기록을 안 읽는다)
#     bash run_onboard.sh --rec $OUT/rec_full.npz   로봇을 고를 기록을 지정
#     bash run_onboard.sh --skip-cam         카메라는 그대로 두고 녹화만
#
# ★ 읽을 기록(`--rec`)과 이번 판의 녹화 대상(`PIBT_RECORD`)은 **달라야 한다.**
#   같으면 방금 읽은 파일을 이 판이 덮어쓴다. 같으면 실행 전에 죽는다.
#
# 나머지 인자는 `run_record.sh` 로 그대로 넘어간다.
#
# 무엇을 하는가
# -------------
#   1. 자세 기록(`out/rec_*.npz`)에서 **주행거리가 가장 긴 로봇**을 고른다
#   2. 그 로봇의 `chassis` 링크에 진행방향을 보는 카메라를 단다 (Isaac 불필요, 몇 초)
#   3. `PIBT_CAMERA` 로 그 카메라를 활성 뷰포트에 물리고 `run_record.sh` 를 부른다
#
# 왜 링크에 다는가
# ----------------
# `/World/Robots/amr_N` 은 ArticulationRoot Xform 이고 **PhysX 가 그걸 안 움직인다.**
# 자세는 각 링크 prim 에 쓴다. 루트에 달면 로봇만 달리고 카메라는 출발 자리에
# 남는다 — 선반에서 똑같이 당했고 영상에서만 보였다 (2026-09-13).
#
# ★ `PIBT_CAMERA` 는 `pibt_h.py:launch()` 의 env 목록에 **없다.** 그래서 셸
#   export 가 그대로 통과한다. 목록에 있는 이름(PIBT_HORIZON 등)은 export 해도
#   덮인다 — 이 저장소의 대표적인 함정이다 (README 「함정」).
# ============================================================
set -uo pipefail

W="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$W"

# run.sh:53 과 같은 규약
[ -n "${VIRTUAL_ENV:-}" ] || source "${VENV:-$HOME/khs/venv}/bin/activate"

MODE="nose"
REC_IN=""
AMR=""
LINK="chassis"
SKIP_CAM=0
PASS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --mode)     MODE="$2"; shift 2 ;;
        --amr)      AMR="$2"; shift 2 ;;
        --rec)      REC_IN="$2"; shift 2 ;;
        --link)     LINK="$2"; shift 2 ;;
        --skip-cam) SKIP_CAM=1; shift ;;
        *) PASS+=("$1"); shift ;;
    esac
done

# shellcheck disable=SC1091
source "$W/paths.sh"

N="${PIBT_N:-12}"
STAGE_USD="$STAGE/pibt$(printf '%02d' "$N").usd"
# ★ **읽기용 기록과 이번 판의 녹화 대상을 분리한다** (2026-09-14).
#   예전에는 `PIBT_RECORD` 하나를 둘 다에 썼다. 그런데 그 값은 자식(run_record
#   -> live_pibt)으로 그대로 내려가 **녹화 대상**이 된다 — 로봇을 고르려고 읽은
#   파일을 그 판이 덮어쓴다. 25분 걸려 만든 기록이 날아간다.
#   `--rec` 로 읽을 파일을 따로 준다. 안 주면 PIBT_RECORD, 그것도 없으면 기본값.
REC="${REC_IN:-${PIBT_RECORD:-$OUT/rec_pibt12.npz}}"
if [ -n "${PIBT_RECORD:-}" ] && [ "$REC" = "${PIBT_RECORD:-}" ]; then
    echo "★ 읽을 기록과 녹화 대상이 같습니다: $REC"
    echo "  이 판의 녹화가 그 파일을 덮어씁니다. 읽을 파일을 따로 주세요:"
    echo "    bash run_onboard.sh --rec \$OUT/rec_full.npz"
    echo "  (또는 --amr 로 로봇을 직접 지정하면 기록을 안 읽습니다)"
    exit 1
fi

# ── ADG 앞 칸 규칙 · 격자 (S15P21A106-204) ──────────────────
#   `run_record.sh` 와 **같은 기본값**을 여기서도 정한다. 이유는 둘이다.
#     1. 아래 머리말에서 실제로 걸릴 값을 찍으려면 여기서 정해져 있어야 한다
#     2. 여기서 export 해 두면 `exec run_record.sh` 가 그대로 물려받아,
#        두 스크립트가 서로 다른 격자로 도는 일이 생기지 않는다
#   ★ 규칙은 pitch 게이팅을 받는다 — 1.2 에서는 무엇을 넣든 꺼진다. 그래서
#     기본 격자가 1.0 이다 (`run_record.sh` 의 같은 자리에 근거를 적어 두었다).
#     1.2 로 한 판:  PIBT_PITCH=1.2 bash run_onboard.sh
export PIBT_FRONT_RULE="${PIBT_FRONT_RULE:-4}"
export PIBT_PITCH="${PIBT_PITCH:-1.0}"

echo "════════════════════════════════════════════════════"
echo " run_onboard   시점 $MODE   대수 $N"
echo "  격자 pitch $PIBT_PITCH   앞 칸 규칙 $PIBT_FRONT_RULE"
echo "════════════════════════════════════════════════════"

[ -f "$STAGE_USD" ] || {
    echo "★ 씬이 없습니다: $STAGE_USD"
    echo "  먼저 한 번 돌려서 씬을 만드세요:  bash run_record.sh"
    exit 1
}

# ── 낡은 계획 덫 ───────────────────────────────────────────
#   `amr/main.py:128` 은 **계획이 씬보다 새로우면 씬을 다시 짓는다.** 그 경로는
#   `--shelf` 도 이 카메라도 모른다. 즉 조용히 둘 다 사라진다.
PLAN_TRAJ="$PLAN/traj_pibt_h/fleet_$(printf '%02d' "$N")/trajectories.json"
if [ -f "$PLAN_TRAJ" ] && [ "$PLAN_TRAJ" -nt "$STAGE_USD" ]; then
    echo "★ 계획이 씬보다 새롭습니다 — main.py 가 씬을 다시 지어 카메라와 선반이 사라집니다."
    echo "    계획  $(stat -c %y "$PLAN_TRAJ" | cut -c1-19)"
    echo "    씬    $(stat -c %y "$STAGE_USD" | cut -c1-19)"
    echo "  씬을 선반 포함으로 다시 지은 뒤 이 스크립트를 도세요:"
    echo "    python runners/build_amr_scene_v2.py --n $N --warehouse \$SCENE --robot \$ROBOT \\"
    echo "        --traj $PLAN_TRAJ --starts \${PLAN_TRAJ%/*}/starts.json \\"
    echo "        --out $STAGE_USD --shelf \$W/robots/shelf/amr_shelf.usd"
    exit 1
fi

# ── 카메라 ─────────────────────────────────────────────────
if [ "$SKIP_CAM" = 1 ]; then
    CAM="${PIBT_CAMERA:-}"
    [ -n "$CAM" ] || { echo "★ --skip-cam 이면 PIBT_CAMERA 를 직접 주세요."; exit 1; }
    echo "[onboard] 카메라 그대로: $CAM"
else
    echo
    echo "── 카메라 ──────────────────────────────────────────"
    # ★ stdout 과 stderr 를 **합치지 말 것.** pxr 이 창고 팔레트 참조 때문에
    #   경고를 수백 줄 쏟는데, 그게 stderr 로 나온다. `2>&1` 로 합치면 마지막
    #   줄이 카메라 경로가 아니라 **경고**가 된다 (2026-09-13 실측).
    #   도구는 경로를 stdout 마지막 줄에 찍는다. stderr 는 따로 받아 걸러 보여준다.
    CAM_ERR="$(mktemp)"
    CAM_OUT="$(python tools/add_onboard_cam.py \
                  --stage "$STAGE_USD" --rec "$REC" --mode "$MODE" --link "$LINK" \
                  ${AMR:+--amr "$AMR"} 2>"$CAM_ERR")" || {
        echo "$CAM_OUT"
        grep -v -E "_ReportErrors|instantiating stage" "$CAM_ERR" | tail -20
        rm -f "$CAM_ERR"
        echo "★ 카메라를 못 달았습니다."
        exit 1
    }
    grep -v -E "_ReportErrors|instantiating stage" "$CAM_ERR" | grep -q . \
        && grep -v -E "_ReportErrors|instantiating stage" "$CAM_ERR" | tail -5
    rm -f "$CAM_ERR"
    echo "$CAM_OUT"
    CAM="$(echo "$CAM_OUT" | tail -1)"
    case "$CAM" in
        /World/Robots/amr_*) : ;;
        *) echo "★ 카메라 경로를 못 읽었습니다: '$CAM'"; exit 1 ;;
    esac
fi
export PIBT_CAMERA="$CAM"

# ── 녹화 ───────────────────────────────────────────────────
echo
echo "── 녹화 ────────────────────────────────────────────"
echo "  카메라  $PIBT_CAMERA"
echo "  이 시점은 로봇과 같이 움직입니다. 화면이 고정돼 보이면 링크가 아니라"
echo "  루트에 붙은 것이니 --link 를 확인하세요."
echo
exec bash "$W/run_record.sh" "${PASS[@]}"
