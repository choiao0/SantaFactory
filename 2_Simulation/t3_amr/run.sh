#!/usr/bin/env bash
# ============================================================
# 시뮬 실행 — 이거 하나만 치면 된다.
#
# ── 기본: 그림을 안 그린다 (2026-09-21 변경) ────────────────
#   bash run.sh --planner pibt_h         렌더 없이 물리만. 화면 없음.
#
#   Kit 을 아예 안 띄우고 `python runners/headless_pibt.py` 가 돈다.
#   계획·ADG·주행·판정은 완전히 같고, 렌더만 빠진다.
#
# ── 화면으로 보려면 STREAM=1 ────────────────────────────────
#   STREAM=1 bash run.sh                 wppl 12대
#   STREAM=1 bash run.sh --planner pibt_h   화면(WebRTC)으로 본다
#
#   ★ 이 스크립트는 **녹화하지 않는다.** SHOT_* 를 export 하지만 live_pibt.py 는
#     PIBT_SHOT_* 를 읽으므로 접두사가 안 맞는다 — 의도적으로 안 고쳤다.
#     녹화는 run_record.sh 담당이다:
#
#         bash run_record.sh               pibt_h 12대 · 10배속 mp4
#
#     (예전 헤더가 "촬영+영상까지 자동, 약 37분"이라고 적어 두어 사람을 속였다.
#      2026-09-08 정정.)
#
# ── 측정 ────────────────────────────────────────────────────
#   bash run.sh --planner pibt_h                     기본이 이미 가장 빠르다
#   HEADLESS=0 bash run.sh --planner pibt_h --lite   Kit 은 띄우되 전송만 끔
#
#   ☹ `STREAM=0` 을 오래 "헤드리스"라 불러 왔는데 **아니다.** 인코딩·전송만
#     끈 것이고 RTX 렌더는 계속 돌았다 (50.51 -> 27.03 ms/스텝에서 정지).
#     진짜로 안 그리는 것은 `HEADLESS=1`(지금 기본)뿐이다.
#
#   화면이 없으므로 촬영은 자동으로 비활성된다.
#   물리는 시연 경로와 완전히 동일하다 (실측: t=10·20·30s 체크포인트 일치).
#
# ── 그 밖에 ─────────────────────────────────────────────────
#   GPU=1 bash run.sh ...                다른 GPU (팀원과 겹칠 때)
#   bash run.sh --rebuild                씬 강제 재빌드
#   python amr/main.py list              계획기 목록
#   python amr/main.py cmds --planner X  서버에서 칠 명령만 출력
#
# ── 촬영 조절 ───────────────────────────────────────────────
#   VIDEO=0        영상 조립을 건너뛴다 (프레임만 남긴다)
#   SHOTS=0        촬영 자체를 끈다
#   SHOT_STRIDE=20 몇 물리스텝마다 한 장 (기본 20 = sim 0.33초)
#   SHOT_FPS=30    출력 fps (기본 30)
#
#   RUN_TAG=이름   출력 폴더·파일 이름 (기본 시각)
#
#   영상 배속 = SHOT_FPS x SHOT_STRIDE / 60
#     기본값   30 x 20 / 60 = 10배속
#     5배속    SHOT_STRIDE=10   (프레임 2배 = 디스크 2배)
#     20배속   SHOT_STRIDE=40   (프레임 절반)
#
#   기본값에서 나오는 것:  sim 730초 -> 2,190장 -> 73초 영상 = 10배속
#   프레임은 약 0.4~1 GB 를 쓴다. 지우는 명령을 끝에 찍어준다.
#
# **이 파일에는 계획기 정보가 없다.** 환경(venv · paths.sh)만 잡고 넘긴다.
# 계획기 표는 amr/path/ 에만 둔다 (2026-09-06).
#
# 씬 빌드·입력 확인·이전 Kit 정리는 전부 main.py run 이 한다.
# ============================================================
set -uo pipefail

[ -n "${VIRTUAL_ENV:-}" ] || source "${VENV:-$HOME/khs/venv}/bin/activate"
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/paths.sh"

# ── 렌더 여부 (2026-09-21) ──────────────────────────────────
# **기본이 그림 없음으로 바뀌었다.** 근거는 아래 세 줄이다.
#
#     STREAM=1     isaacsim full.streaming --exec    렌더 + WebRTC 전송
#     STREAM=0     isaacsim base.python    --exec    렌더만 (전송만 껐다)
#     HEADLESS=1   python runners/headless_pibt.py   렌더 없음  ← 지금 기본
#
# 오래 `STREAM=0` 을 "헤드리스"라 불러 왔지만 그것은 인코딩·전송만 끈 것이고
# RTX 렌더는 계속 돌았다. 그래서 27 ms/스텝에서 더 안 내려갔다.
#
# 화면으로 보려면 **STREAM=1 을 명시**한다. 그러면 예전 동작 그대로다.
#
#     bash run.sh --planner pibt_h              그림 없음 (빠름)
#     STREAM=1 bash run.sh --planner pibt_h     WebRTC 시연
#     HEADLESS=0 bash run.sh --planner pibt_h   Kit 은 띄우되 전송만 끔
#
# ☹ 헤드리스 러너가 있는 계획기는 지금 pibt_h 뿐이다. wppl 등으로 돌리면
#   _common.py 가 무엇을 해야 하는지 알려주며 멈춘다.
_stream_given="${STREAM+yes}"
STREAM="${STREAM:-0}"
if [ -z "${HEADLESS:-}" ]; then
    if [ "$_stream_given" = "yes" ] && [ "$STREAM" != "0" ]; then
        HEADLESS=0          # 보겠다고 했으니 Kit 을 띄운다
    else
        HEADLESS=1
    fi
fi
[ "$HEADLESS" = "1" ] && STREAM=0
export STREAM HEADLESS

TAG="${RUN_TAG:-$(date +%Y%m%d_%H%M%S)}"
SHOT_EXT="${SHOT_EXT:-png}"
SHOT_FPS="${SHOT_FPS:-30}"
CAPTURE=0

# ── 촬영 가부 ───────────────────────────────────────────────
# 스크린샷은 **뷰포트가 있어야** 찍힌다. 렌더를 안 하면 당연히 없다.
if [ "$STREAM" = "0" ]; then
    if [ -n "${SHOTS:-}" ] && [ "${SHOTS:-}" != "0" ]; then
        echo "[run] ★ 그림을 안 그리는 모드라 촬영이 안 됩니다. SHOTS 를 무시합니다."
        echo "[run]   영상이 필요하면:  STREAM=1 bash run.sh ...   (또는 run_record.sh)"
        echo "[run]   숫자만 필요하면 그대로 두세요 — 무충돌 판정은 매 스텝 도는"
        echo "[run]   overlap/contact 검사가 하지, 영상이 하지 않습니다."
    fi
    unset SHOTS
elif [ "${SHOTS:-}" = "0" ]; then
    echo "[run] 촬영 끔 (SHOTS=0)"
    unset SHOTS
else
    SHOTS="${SHOTS:-$OUT/shots_$TAG}"
    export SHOTS SHOT_EXT SHOT_FPS
    export SHOT_STRIDE="${SHOT_STRIDE:-20}"
    mkdir -p "$SHOTS" || { echo "[run] ★ $SHOTS 를 만들 수 없습니다"; exit 1; }
    CAPTURE=1
    echo "[run] 촬영 -> $SHOTS"
    echo "[run]   stride ${SHOT_STRIDE}스텝 · ${SHOT_FPS}fps · $SHOT_EXT"
    echo "[run]   예상: sim 730초 -> 약 $((43800 / SHOT_STRIDE))장 -> $((43800 / SHOT_STRIDE / SHOT_FPS))초 영상"
    df -h --output=avail "$OUT" 2>/dev/null | tail -1 \
        | sed 's/^/[run]   남은 디스크: /'
fi

MP4="$OUT/demo_$TAG.mp4"

# ── 영상 조립 — EXIT 에 걸어 Ctrl-C 로 끊어도 만든다 ────────
assemble() {
    [ "$CAPTURE" = "1" ] || return 0
    [ "${VIDEO:-1}" = "1" ] || { echo "[run] VIDEO=0 — 조립 건너뜀. 프레임: $SHOTS"; return 0; }

    local n
    n=$(find "$SHOTS" -maxdepth 1 -name "f_*.$SHOT_EXT" 2>/dev/null | wc -l)
    echo
    echo "[run] ── 영상 조립 ─────────────────────────────"
    if [ "$n" -eq 0 ]; then
        echo "[run] 프레임이 없습니다. 로그에서 '캡처 N장 · 실패 M회' 를 확인하세요."
        echo "[run]   verify_start 를 통과해야 촬영이 시작됩니다."
        rmdir "$SHOTS" 2>/dev/null
        return 0
    fi
    if ! command -v ffmpeg >/dev/null 2>&1; then
        echo "[run] ffmpeg 이 없습니다. 프레임 ${n}장은 여기 있습니다:"
        echo "[run]   $SHOTS"
        return 0
    fi

    echo "[run] 프레임 ${n}장 -> $MP4"
    if ffmpeg -y -loglevel warning -stats \
              -framerate "$SHOT_FPS" -pattern_type glob \
              -i "$SHOTS/f_*.$SHOT_EXT" \
              -c:v libx264 -pix_fmt yuv420p -crf 20 "$MP4"; then
        echo
        echo "[run] ✔ $MP4"
        echo "[run]   길이 $((n / SHOT_FPS))초 · 프레임 ${n}장"
        du -sh "$MP4" "$SHOTS" 2>/dev/null | sed 's/^/[run]   /'
        echo "[run]   프레임을 지우려면:  rm -rf $SHOTS"
    else
        echo "[run] ★ ffmpeg 실패. 프레임은 $SHOTS 에 남아 있습니다."
        echo "[run]   수동:  cd $SHOTS && ffmpeg -framerate $SHOT_FPS \\"
        echo "[run]            -pattern_type glob -i 'f_*.$SHOT_EXT' \\"
        echo "[run]            -c:v libx264 -pix_fmt yuv420p -crf 20 $MP4"
    fi
}
trap assemble EXIT

# ── 실행 ────────────────────────────────────────────────────
# ★ `exec` 를 쓰지 않는다 — 뒤에서 영상을 조립해야 하므로 셸이 살아 있어야 한다.
#   그리고 main.py 가 os.execvpe 로 Isaac 을 띄우므로, 이 python 이 곧 Isaac 이다.
#   완주 시 앱이 스스로 종료해야 여기로 돌아온다 (patch_autoquit.py).
if [ "$HEADLESS" = "1" ]; then
    echo "[run] 그림 없음 (HEADLESS=1) — Kit 을 안 띄우고 python 이 물리만 돌립니다."
    echo "[run]   화면으로 보려면:  STREAM=1 bash run.sh $*"
fi
echo "[run] 실행: main.py run $*  (STREAM=$STREAM, HEADLESS=$HEADLESS, GPU=$GPU)"
python "$W/amr/main.py" run "$@"
rc=$?
echo "[run] Isaac 종료 (코드 $rc)"
exit "$rc"
