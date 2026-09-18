#!/usr/bin/env bash
# 헤드리스가 **같은 판인가** — 배속이 아니라 동일성을 잰다 (S15P21A106-240)
#
# ☹ 처음에 PIBT_RENDER_EVERY 를 손잡이로 잡았는데 **틀렸다.**
#   run_record.sh:180 이 그것을 막아 뒀다 —
#     「PIBT_RENDER_EVERY>1 은 물리 뷰를 무효화합니다 (2026-09-08 미해결)」
#   maxSubSteps 를 건드려 **물리가 바뀐다.** 증명 주행에 쓸 수 없다.
#
# ★ 맞는 길은 STREAM=0 + --lite 다. 둘 다 **렌더만** 끈다.
#     live_pibt.py:917  「MakeInvisible() 은 렌더만 끄고 CollisionAPI 는
#                        건드리지 않는다 -> 물리 결과가 전혀 바뀌지 않는다」
#     run.sh:19         STREAM=0 ... --lite   약 13분 (배속 0.91)
#
# 그래서 이 스크립트가 재는 것은 배속이 아니라 **동일성**이다.
# 배속은 이미 적혀 있고, 우리가 확인할 것은 「그 판으로 증명해도 되나」다.
set -u
cd ~/S15P21A106/2_Simulation/t3_amr
source paths.sh >/dev/null 2>&1
OUT=$LOGS/headless; mkdir -p "$OUT"

SEED=${SEED:-2}            # 시드 2 는 완주한다 (2,719/2,719 · 접촉 0 · 561.1 s)
HZ=${HZ:-1260}

echo "=== A) 지금 방식 — STREAM=1 (뷰포트 O) ==="
CAPTURE=0 VIDEO=0 PIBT_PITCH=1.0 PIBT_SEED=$SEED PIBT_HORIZON=$HZ WATCH_SEC=0 \
  bash run_record.sh > "$OUT/a_stream1.log" 2>&1

echo "=== B) 헤드리스 — STREAM=0 --lite (렌더만 끈다) ==="
STREAM=0 PIBT_PITCH=1.0 PIBT_SEED=$SEED PIBT_HORIZON=$HZ \
  bash run.sh --planner pibt_h --lite > "$OUT/b_headless.log" 2>&1

echo
echo "================ 동일성 판정 ================"
row () {   # $1 라벨  $2 로그
  local f="$2"
  [ -f "$f" ] || { printf "  %-12s 로그 없음\n" "$1"; return; }
  local pv pr fin con ovl gap sim wall
  pv=$(grep -o "probe amr_[0-9]*: .* 변화 [0-9.]*" "$f" | head -1 | awk '{print $NF}')
  pr=$(grep -o "probe 후 잔여(슬립) 최대 [0-9.]*" "$f" | head -1 | awk '{print $NF}')
  fin=$(grep -o "completed=[0-9]*" "$f" | tail -1 | cut -d= -f2)
  con=$(grep -o "contact_events=[0-9]*" "$f" | tail -1 | cut -d= -f2)
  ovl=$(grep -o "overlap_events=[0-9]*" "$f" | tail -1 | cut -d= -f2)
  gap=$(grep -o "worst_gap=[0-9.]*" "$f" | tail -1 | cut -d= -f2)
  sim=$(grep -o "sim_time=[0-9.]*" "$f" | tail -1 | cut -d= -f2)
  wall=$(grep -o "\[[0-9,]*ms\]" "$f" | tail -1 | tr -d '[],ms')
  printf "  %-12s probe %-9s 잔여 %-9s 완료 %-6s 접촉 %-4s 겹침 %-6s 간격 %-8s sim %-8s 벽 %ss\n" \
    "$1" "${pv:-?}" "${pr:-?}" "${fin:-?}" "${con:-?}" "${ovl:-?}" "${gap:-?}" "${sim:-?}" \
    "$(awk -v w="${wall:-0}" 'BEGIN{printf "%.0f", w/1000}')"
}
row "A STREAM=1" "$OUT/a_stream1.log"
row "B 헤드리스"  "$OUT/b_headless.log"
echo
echo "★ 읽는 법 — **probe · 완료 · 접촉 · 겹침이 같아야** 헤드리스로 증명할 수 있다"
echo "   하나라도 다르면 렌더가 물리를 건드린 것이고, 그 판으로는 증명을 못 한다."
echo "   같으면 배속만 남는다 (run.sh:19 실측 0.91 — 지금 0.29 대비 약 3배)."
