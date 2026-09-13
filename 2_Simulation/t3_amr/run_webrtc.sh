#!/usr/bin/env bash
# ============================================================
# run_webrtc.sh — 선반을 얹고 WebRTC 로 눈으로 확인한다 (S15P21A106-196)
#
#     bash run_webrtc.sh                 선반 얹고 씬 재빌드 + 스트리밍
#     bash run_webrtc.sh --top-rear 0.850    상부를 깎아서
#     bash run_webrtc.sh --no-shelf      선반 없이 (대조군)
#     bash run_webrtc.sh --skip-build    씬은 그대로 두고 스트리밍만
#
# 왜 이 스크립트가 필요한가
# -------------------------
# 선반이 랙 데크(밑면 1,005 mm)를 뚫는지는 **물리로 안 잡힌다.** 랙이
# `instance=True` 참조라 콜라이더가 없다 (build_scene.py 가 CollisionAPI 를
# 랙에는 안 붙인다). `overlap_events` 도 로봇끼리만 본다. 그래서 **눈으로**
# 봐야 하고, 그러려면 WebRTC 가 필요하다.
#
# 클라우드에서 걸리는 것 둘 — 둘 다 여기서 처리한다
# --------------------------------------------------
#   ① 공인 IP. `paths.sh` 의 `hostname -I` 는 내부 IP 다. WebRTC 서버가
#      "미디어를 여기로 보내라"고 알려주는 주소라 틀리면 화면이 안 온다.
#      -> `PUBLIC_IP` 를 주거나, 없으면 ifconfig.me 로 자동 조회한다.
#
#   ② 포트. **49100/TCP(시그널링) · 47998/UDP(미디어)** 를 인바운드로 열어야
#      한다. 둘 다 TCP 로 열면 "연결됨" 으로 보이는데 영상만 안 나온다 —
#      2026-08-28·08-30 에 두 번 겪은 함정이다.
#      ★ SSH 터널로는 안 된다. 미디어가 UDP 라 `ssh -L` 이 못 나른다.
#        Brev/클라우드 콘솔에서 인바운드를 열어야 한다.
#
# 그리고 `NVST_R_BUSY` — 스트리밍 앱이 둘이면 NVENC 를 두고 싸워 검은 화면이
# 된다. 기동 전에 정리하고 **한 자리 수까지 떨어지는지** 확인한다 (한 번의
# pkill 을 믿지 말 것 — 692 MiB 로 남아 있던 적이 있다).
# ============================================================
set -uo pipefail

W="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$W"

TOP_REAR=""
SHELF=1
SKIP_BUILD=0
PASS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --top-rear) TOP_REAR="$2"; shift 2 ;;
        --no-shelf) SHELF=0; shift ;;
        --skip-build) SKIP_BUILD=1; shift ;;
        *) PASS+=("$1"); shift ;;
    esac
done

# ── 공인 IP ────────────────────────────────────────────────
#   paths.sh 보다 **먼저** export 해야 한다. 이제 paths.sh 가
#   `${LAN_IP:-...}` 라 미리 준 값을 존중한다 (2026-09-13 수정).
if [ -z "${PUBLIC_IP:-}" ]; then
    PUBLIC_IP="$(curl -s -m 10 ifconfig.me || true)"
fi
if [ -z "$PUBLIC_IP" ]; then
    echo "★ 공인 IP 를 못 얻었습니다. 직접 주세요:  PUBLIC_IP=x.x.x.x bash run_webrtc.sh"
    exit 1
fi
export LAN_IP="$PUBLIC_IP"

# shellcheck disable=SC1091
source "$W/paths.sh"

echo "════════════════════════════════════════════════════"
echo " run_webrtc"
echo "  접속 주소   $PUBLIC_IP"
echo "  선반        $([ "$SHELF" = 1 ] && echo "ON${TOP_REAR:+ (상부 뒤 $TOP_REAR)}" || echo OFF)"
echo "  씬 빌드     $([ "$SKIP_BUILD" = 1 ] && echo 건너뜀 || echo 실행)"
echo "════════════════════════════════════════════════════"
echo
echo "  ★ 콘솔에서 인바운드가 열려 있어야 합니다:"
echo "      49100/TCP   시그널링"
echo "      47998/UDP   미디어   <- UDP 여야 합니다. TCP 로 열면 영상만 안 옵니다"
echo

# ── 남은 Kit 정리 (NVST_R_BUSY 예방) ───────────────────────
if pgrep -f 'bin/isaacsim isaacsim\.exp' >/dev/null 2>&1; then
    echo "[webrtc] 남아 있는 Kit 을 정리합니다."
    pkill -INT -f 'bin/isaacsim isaacsim\.exp' 2>/dev/null
    for i in $(seq 1 12); do
        sleep 5
        used="$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1)"
        echo "  ${i}0초 · GPU ${used:-?} MiB"
        [ -n "$used" ] && [ "$used" -lt 100 ] && break
    done
    still="$(pgrep -cf 'bin/isaacsim isaacsim\.exp' 2>/dev/null || echo 0)"
    if [ "$still" != 0 ]; then
        echo "★ Kit 이 아직 ${still}개 남아 있습니다. 강제 종료 후 다시 도세요:"
        echo "    pkill -9 -f 'bin/isaacsim isaacsim.exp'"
        exit 2
    fi
fi

# ── 선반 USD ───────────────────────────────────────────────
SHELF_USD="$W/robots/shelf/amr_shelf.usd"
if [ "$SHELF" = 1 ]; then
    echo
    echo "── 선반 USD ────────────────────────────────────────"
    ISAAC_PY="$(command -v isaacsim >/dev/null 2>&1 && echo python || echo python)"
    $ISAAC_PY "$W/warehouse/scene/build_amr_shelf.py" \
        ${TOP_REAR:+--top-rear "$TOP_REAR"} || {
            echo "★ 선반 USD 생성 실패."
            echo "  Isaac 파이썬이 필요합니다 (pxr). venv 가 켜져 있는지 보세요:"
            echo "    source ~/khs/venv/bin/activate"
            exit 1
        }
    [ -f "$SHELF_USD" ] || { echo "★ $SHELF_USD 가 없습니다."; exit 1; }
fi

# ── 씬 재빌드 ──────────────────────────────────────────────
#   `main.py run` 이 씬을 짓지만 `--shelf` 를 모른다. 그래서 여기서 직접 짓는다.
if [ "$SKIP_BUILD" != 1 ]; then
    echo
    echo "── 씬 빌드 ─────────────────────────────────────────"
    N="${PIBT_N:-12}"
    PLAN_DIR="$PLAN/traj_pibt_h/fleet_$(printf '%02d' "$N")"
    [ -d "$PLAN_DIR" ] || {
        echo "★ 계획이 없습니다: $PLAN_DIR"
        echo "  먼저:  python amr/main.py plan --planner pibt_h --n $N"
        echo "         cp -a v2/traj_pibt_h/. plan/traj_pibt_h/"
        exit 1
    }
    isaacsim isaacsim.exp.base.python --no-window \
        --/renderer/activeGpu="$GPU" --/renderer/multiGpu/enabled=false \
        --exec "$W/runners/build_amr_scene_v2.py \
                --warehouse $SCENE --robot $ROBOT \
                --traj $PLAN_DIR/trajectories.json \
                --starts $PLAN_DIR/starts.json --n $N \
                --out $STAGE/pibt$(printf '%02d' "$N").usd \
                $([ "$SHELF" = 1 ] && echo "--shelf $SHELF_USD")" || {
        echo "★ 씬 빌드 실패."; exit 1; }
fi

# ── 스트리밍 ───────────────────────────────────────────────
echo
echo "── 스트리밍 ────────────────────────────────────────"
echo "  Isaac Sim WebRTC Streaming Client 에서 Server = $PUBLIC_IP"
echo "  (첫 실행은 셰이더 컴파일로 수 분 걸립니다 — 정상입니다)"
echo
exec bash "$W/run.sh" --planner pibt_h "${PASS[@]}"
