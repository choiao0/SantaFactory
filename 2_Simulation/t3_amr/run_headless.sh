#!/usr/bin/env bash
# ============================================================
# run_headless.sh — 그림 없이 주행한다. `run_record.sh` 의 헤드리스 짝.
#
#     bash run_headless.sh                    기본 (12대 · 우리 계획)
#     bash run_headless.sh 13                 13대
#     PIBT_TRAJ=docs/모음/r13_peak10/trajectories.json \
#       bash run_headless.sh 13               FMS 궤적을 그대로 실행
#
# 왜 이 파일이 필요한가
# ---------------------
# `python runners/headless_pibt.py` 를 손으로 부르면 **다섯 가지가 빠진다.**
# 2026-09-22 에 그 다섯을 하나씩 밟으며 판을 네 번 날렸다.
#
#   ① $W          `paths.sh` 를 안 읽으면 `pibt_scene._fms_map_dir` 가
#                 `KeyError: 'W'` 로 죽는다
#   ② PIBT_STAGE  기본이 `v2/warehouse_v59_pibt12.usd` 라 13대 판에서 못 찾는다
#                 (`run_record.sh` 는 `pibt_h.launch(n)` 이 채워 준다)
#   ③ PIBT_MODE   기본이 `oneshot` 이다. 그러면 `PS.setup()` 으로 가서
#                 **FMS 격자도 정적 감시도 PIBT_TRAJ 도 전부 안 탄다**
#   ④ PIBT_SEED   안 주면 9 로 돈다
#   ⑤ HL_SETUP_CAP 기본 12,000 프레임인데 헤드리스는 그게 **4초**다.
#                 준비(계획·probe·재정렬)는 30~60초 걸린다
#
# `run_record.sh` 와의 차이
# -------------------------
#   run_record.sh   Kit `--exec live_pibt.py`. 앱이 주루프를 쥐어 **렌더가 돈다**
#   run_headless.sh `python headless_pibt.py`. 우리가 루프를 돌아 **렌더가 없다**
#
#   실측 (13대 · r13 궤적 · 2026-09-22)
#       run_record    3.1배 실시간  ·  1,662초 판이 벽시계 1h25m
#       run_headless  1.06배       ·  같은 판이 벽시계 28분
#
# ★ `isaacsim ... --exec runners/headless_pibt.py` 로 부르면 **안 된다.**
#   그러면 앱이 주루프를 되찾아 렌더가 돌고 이 파일의 존재 이유가 사라진다.
# ============================================================
set -uo pipefail

W_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$W_DIR"

# run.sh:53 과 같은 규약
[ -n "${VIRTUAL_ENV:-}" ] || source "${VENV:-$HOME/khs/venv}/bin/activate"
# shellcheck disable=SC1091
source "$W_DIR/paths.sh"                       # ① $W · $STAGE · $OUT · $LOGS

N="${1:-${PIBT_N:-12}}"
export PIBT_N="$N"

# ② 씬 USD — `run_record.sh` 가 만드는 것과 같은 이름
export PIBT_STAGE="${PIBT_STAGE:-$STAGE/pibt$(printf '%02d' "$N").usd}"

# ③④ 러너 기본값. 셸에서 준 값이 이긴다
export PIBT_MODE="${PIBT_MODE:-lifelong}"
export PIBT_SEED="${PIBT_SEED:-104}"
export PIBT_PITCH="${PIBT_PITCH:-1.0}"


# ⑤ 준비 프레임 상한 — 헤드리스는 프레임이 빨라 12,000 이 4초다
export PIBT_HL_SETUP_CAP="${PIBT_HL_SETUP_CAP:-400000}"

# 촬영 없음. `PIBT_SHOTS` 가 비면 `live_pibt.py` 가 아무것도 안 한다
export PIBT_SHOTS=""

TAG="${TAG:-$(date +%Y%m%d_%H%M%S)}"
LOG="$LOGS/hl_$TAG.log"

# ★★ **여기서부터 모든 출력이 로그에 남는다** (2026-09-22).
#
#   예전 마지막 줄이 `exec python ... | tee "$LOG"` 였다. 그러면 tee 가
#   **파이썬 출력만** 받는다 — 그 앞의 echo 는 전부 터미널로만 간다.
#   그래서 「이 판이 무슨 설정이었나」가 로그에 안 남았고, 2026-09-22 에
#   그걸 로그 본문에서 되짚느라 판을 세 번 헛돌렸다.
#
#   stdout 을 먼저 tee 로 바꿔 두면 **이 줄 아래 전부**가 남는다.
#   run_record.sh 는 이 문제가 없다 — 백엔드가 자식 stdout 을 파일로
#   받고(edge/recorder.py:211), 손으로 돌릴 때는 터미널에 보인다.
mkdir -p "$LOGS"
exec > >(tee "$LOG") 2>&1

# 주행 스위치 한 벌 — run_record.sh 와 **같은 파일**을 읽는다.
#   pitch 를 정한 뒤라야 배너가 그것도 찍고, tee 뒤라야 로그에 남는다.
source "$W_DIR/switches.sh"

if [ ! -f "$PIBT_STAGE" ]; then
    echo "★ 씬이 없습니다: $PIBT_STAGE"
    echo "  먼저 한 번 돌려서 씬을 만드세요:  bash run_record.sh $N"
    exit 1
fi

echo "════════════════════════════════════════════════════"
echo " run_headless   대수 $N   시드 $PIBT_SEED   모드 $PIBT_MODE"
echo "  씬      $PIBT_STAGE"
echo "  격자    pitch $PIBT_PITCH   앞 칸 규칙 ${PIBT_FRONT_RULE:-(기본 4)}"
if [ -n "${PIBT_TRAJ:-}" ]; then
    echo "  ★ 궤적  $PIBT_TRAJ   (계획을 하지 않는다)"
else
    echo "  계획    우리 lifelong + PIBT"
fi
echo "  로그    $LOG"
echo "════════════════════════════════════════════════════"

# stdout 은 위에서 이미 tee 로 갈아 뒀다 — 여기서 다시 파이프하면 안 된다.
exec python runners/headless_pibt.py
