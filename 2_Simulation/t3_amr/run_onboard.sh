#!/usr/bin/env bash
# ============================================================
# run_onboard.sh — 가장 많이 움직이는 AMR 시점에서 진행방향을 녹화한다
#
#     bash run_onboard.sh                    주행 시점 (기본)
#     bash run_onboard.sh --mode chase       뒤 위에서 따라가며
#     bash run_onboard.sh --amr 7            로봇을 직접 지정
#     bash run_onboard.sh --skip-cam         카메라는 그대로 두고 녹화만
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
AMR=""
LINK="chassis"
SKIP_CAM=0
PASS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --mode)     MODE="$2"; shift 2 ;;
        --amr)      AMR="$2"; shift 2 ;;
        --link)     LINK="$2"; shift 2 ;;
        --skip-cam) SKIP_CAM=1; shift ;;
        *) PASS+=("$1"); shift ;;
    esac
done

# shellcheck disable=SC1091
source "$W/paths.sh"

N="${PIBT_N:-12}"
STAGE_USD="$STAGE/pibt$(printf '%02d' "$N").usd"
REC="${PIBT_RECORD:-$OUT/rec_pibt12.npz}"

echo "════════════════════════════════════════════════════"
echo " run_onboard   시점 $MODE   대수 $N"
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
    CAM_LOG="$(python tools/add_onboard_cam.py \
                  --stage "$STAGE_USD" --rec "$REC" --mode "$MODE" --link "$LINK" \
                  ${AMR:+--amr "$AMR"} 2>&1)" || {
        echo "$CAM_LOG"
        echo "★ 카메라를 못 달았습니다."
        exit 1
    }
    echo "$CAM_LOG"
    CAM="$(echo "$CAM_LOG" | tail -1)"
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
