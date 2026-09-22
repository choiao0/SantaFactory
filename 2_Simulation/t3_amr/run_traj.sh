#!/usr/bin/env bash
# ============================================================
# run_traj.sh — FMS 궤적을 **검증된 설정 한 벌**로 재생한다.
#
#     bash run_traj.sh                       13대 · r13 궤적 · 헤드리스
#     PIBT_TURN_BODY_MAX=30 bash run_traj.sh 한도만 바꿔 비교
#     PIBT_W_ACCEL=0 bash run_traj.sh        회전 가속 제한만 꺼서 비교
#     RENDER=1 bash run_traj.sh              렌더까지 (영상이 필요할 때)
#
# 왜 이 파일이 필요한가
# ---------------------
# 이 설정은 **어디에도 안 적혀 있었다.** 코드 기본값도 아니고 `run_record.sh`
# 도 안 준다. 매 판 손으로 `export` 해 왔고, 그래서 2026-09-22 에 「지난 판이
# 무슨 설정이었나」를 로그로 되짚는 일이 반복됐다. 한 벌로 묶어 둔다.
#
# ★ 한도 90초 (2026-09-22)
#   `docs/LOCAL_작업순서.md` 「열려 있는 것」의 첫 항목이 **관문이 포기하고
#   밀고 들어간다** 이고, 그 아래 세 줄이 후보다.
#
#       - 양보(간선 면제)는 몸 간선에서 거부됨          ☒
#       - 기하 게이트는 한계가 회전 밀림보다 작아 못 씀  ☒
#       - 한도 90초는 안 재 봤다 (제일 싸다)            <- 이것
#
#   사고 ①은 34.8초를 기다려야 했는데 30초로 잘려 **4.8초 모자랐다.**
#   대가 어림 -0.4 % (회전이 더 기다린다 = 처리량, **교착이 아니다**).
#   한도에 닿으면 `isaac_drive.py:3216` 이 반드시 출발시키므로 영구 교착은
#   구조상 안 난다. 그래서 올려서 사는 것은 기다림뿐이다.
#
#   ☹ 아직 **한 번도 안 돌렸다.** 이 파일은 그 판을 한 줄로 만드는 것이지
#     결과를 주장하는 것이 아니다.
#
# 마지막 헤드리스 판 (`hl_zone2`, 한도 30)
#       액션 3,079/4,284 (72%)  ·  차체 접촉 1  ·  최소 간격 ~0.8 mm
#       turn_gaveup_body 39/39  <- 포기가 **전부** 「남의 몸」 경우였다
#       랙 접촉 0  ·  피커 구역 진입 420
# ============================================================
set -uo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

N="${1:-13}"

# --- 궤적 재생 ---
#   FMS 가 낸 길을 그대로 따라간다. 계획을 하지 않으므로 회전 마스크도 뜻이 없다.
export PIBT_TRAJ="${PIBT_TRAJ:-docs/모음/r13_peak10/trajectories.json}"
export PIBT_FMS_GRID="${PIBT_FMS_GRID:-1}"   # 궤적의 칸 번호는 FMS 격자(107x116)
export PIBT_TURN_SWEEP="${PIBT_TURN_SWEEP:-0}"

# --- ADG ---
#   FRONT_RULE=4 는 이 궤적에서 ADG 순환이 난다. ADG_RANK 가 틱 순위로 그걸 편다.
export PIBT_FRONT_RULE="${PIBT_FRONT_RULE:-4}"
export PIBT_ADG_RANK="${PIBT_ADG_RANK:-1}"
export PIBT_ADG_BODY="${PIBT_ADG_BODY:-1}"

# --- 회전 관문 ---
export PIBT_TURN_BODY_GATE="${PIBT_TURN_BODY_GATE:-1}"
export PIBT_TURN_BODY_MAX="${PIBT_TURN_BODY_MAX:-90}"    # ★ 30 -> 90
export PIBT_TURN_YIELD="${PIBT_TURN_YIELD:-1}"

# --- 회전 가속 제한 ---
#   회전 가지에는 가속도 제한이 **없었다.** 직진은 한 스텝에 a_exec 만큼만
#   바뀌는데, 회전은 clamp(3*err, +-w_max) 를 그대로 돌려준다. 90도면
#   3*1.571 = 4.71 이라 **첫 스텝에 곧바로 w_max(2.07)** 다. 60 Hz 에서 바퀴
#   접선속도 0.83 m/s 짜리 계단이고, 속도 제어 조인트에 계단을 주면 마찰
#   한도를 잠깐 넘어 **미끄러진다.**
#
#       회전 162건 중 1건이 363.4 mm 밀렸다 (중앙 47.7 · p95 61.6)
#       시작 48.4 -> 끝 363.4 이므로 **회전 그 자체가 315 mm 를 만들었다**
#
#   20 rad/s^2 이면 한 스텝 변화가 2.07 -> 0.33 rad/s 로 **6배 작아지고**,
#   90도 소요는 0.76 -> 0.81 s 라 거의 안 변한다. TURN_TICKS=5 는 FMS 와
#   공유하므로 이 틱 모델이 깨지면 안 된다 — 그래서 20 이다.
#
#   ☹ 구현은 2026-09-17(-240)에 됐는데 기본이 0(꺼짐)이라 **한 번도 안 돌았다.**
#     회전 밀림은 기하 예산 41.3 mm 를 먹는 두 항 중 큰 쪽이다.
export PIBT_W_ACCEL="${PIBT_W_ACCEL:-20}"

# --- 공차 ---
#   0.02 는 회전 교착이 난다. 제어 정착 바닥이 20.0 mm 라 기하 요구(20.65 mm)와
#   창이 0.65 mm 뿐이다. 0.03 이 실측으로 도는 유일한 값이다.
export PIBT_TOL_POS="${PIBT_TOL_POS:-0.03}"
export PIBT_TOL_CROSS="${PIBT_TOL_CROSS:-0.03}"

export PIBT_SEED="${PIBT_SEED:-104}"
export PIBT_MODE="${PIBT_MODE:-lifelong}"

echo "════════════════════════════════════════════════════"
echo " run_traj   대수 $N   시드 $PIBT_SEED"
echo "  궤적        $PIBT_TRAJ"
echo "  회전 한도   ${PIBT_TURN_BODY_MAX}s   (관문 $PIBT_TURN_BODY_GATE · 양보 $PIBT_TURN_YIELD)"
echo "  공차        pos $PIBT_TOL_POS · cross $PIBT_TOL_CROSS"
echo "  회전 가속   ${PIBT_W_ACCEL} rad/s^2   (0 이면 끔 — 계단 그대로)"
echo "  앞 칸 규칙  $PIBT_FRONT_RULE   (ADG 순위 $PIBT_ADG_RANK · 몸 $PIBT_ADG_BODY)"
echo "════════════════════════════════════════════════════"

# ★ 기본은 헤드리스다 — 같은 판이 벽시계 1h25m -> 28분.
#   영상이 필요하면 RENDER=1. ☹ 헤드리스와 렌더가 같은 결과인지는 **아직 안 갈렸다**
#   (2026-09-22: 렌더 완주 · 헤드리스 72%). 비교는 같은 쪽끼리만 한다.
if [ "${RENDER:-0}" = "1" ]; then
    exec bash run_record.sh "$N"
fi
exec bash run_headless.sh "$N"
