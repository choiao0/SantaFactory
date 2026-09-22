#!/usr/bin/env bash
# ============================================================
# run_traj.sh — FMS 궤적을 그대로 재생한다.
#
#     bash run_traj.sh                       13대 · r13 궤적 · 헤드리스
#     bash run_traj.sh 13
#     RENDER=1 bash run_traj.sh              렌더까지 (영상이 필요할 때)
#
# ★ 주행 스위치는 여기 없다 — `switches.sh` 한 벌이고, `run_headless.sh` 와
#   `run_record.sh` 가 둘 다 그것을 읽는다. 이 파일은 **궤적 재생에만 필요한
#   것**을 얹는다. 전부 `${VAR:-기본}` 이라 셸이 준 값이 이긴다.
#
#     PIBT_TURN_BODY_MAX=30 bash run_traj.sh    한 변수만 되돌려 비교
#     PIBT_W_ACCEL=0 bash run_traj.sh
#
# ☹ 셸에 옛 export 가 남아 있으면 그것이 이긴다. 깨끗이 돌리려면
#       for v in $(compgen -v | grep ^PIBT_); do unset "$v"; done
# ============================================================
set -uo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

N="${1:-13}"

# --- 궤적 재생에만 필요한 것 --------------------------------
#   FMS 가 낸 길을 그대로 따라간다. `live_pibt.py:1084` 가 계획을 통째로
#   건너뛴다.
export PIBT_TRAJ="${PIBT_TRAJ:-docs/모음/r13_peak10/trajectories.json}"

#   궤적의 칸 번호는 **FMS 격자(107x116)** 기준이다. 안 주면 우리 격자
#   (106x115)로 읽어 칸이 딴 자리를 가리킨다 — live_pibt 가 「스폰이 궤적 첫
#   틱과 다르다」로 운다.
export PIBT_FMS_GRID="${PIBT_FMS_GRID:-1}"

#   계획을 안 하므로 회전 마스크는 아무것도 안 막는다. 굽는 시간만 든다.
export PIBT_TURN_SWEEP="${PIBT_TURN_SWEEP:-0}"

#   FRONT_RULE=4 는 이 궤적에서 ADG 순환이 난다. switches.sh 의 ADG_RANK 가
#   틱 순위로 그걸 편다 (그래서 이 판에서는 ADG_RANK 를 끄면 안 된다).
export PIBT_FRONT_RULE="${PIBT_FRONT_RULE:-4}"

export PIBT_SEED="${PIBT_SEED:-104}"
export PIBT_MODE="${PIBT_MODE:-lifelong}"

echo "════════════════════════════════════════════════════"
echo " run_traj   대수 $N   궤적 $PIBT_TRAJ"
echo "════════════════════════════════════════════════════"

# ★ 기본은 헤드리스다 — 같은 판이 벽시계 1h25m -> 28분.
#   ☹ 헤드리스와 렌더가 같은 결과인지는 **아직 안 갈렸다** (2026-09-22:
#     렌더 완주 · 헤드리스 72 %). 비교는 같은 쪽끼리만 한다.
#   둘 다 switches.sh 를 읽으므로 스위치는 같다.
if [ "${RENDER:-0}" = "1" ]; then
    exec bash run_record.sh "$N"
fi
exec bash run_headless.sh "$N"
