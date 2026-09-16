#!/usr/bin/env bash
# ============================================================
# install.sh — 새 GPU 서버에서 이것 하나만 돌리면 된다.
#
#     git clone https://lab.ssafy.com/s15-mobility-smarthome-sub1/S15P21A106.git
#     cd S15P21A106/2_Simulation/t3_amr && bash install.sh
#
#   이미 받아 뒀으면 최신화만 하고 다시 돌리면 된다 (재실행 안전):
#     cd <저장소>/2_Simulation/t3_amr && git pull && bash install.sh
#
#     bash install.sh --check    설치하지 않고 조건만 본다
#     bash install.sh --force    이미 있는 venv 를 지우고 다시 만든다
#
#   ★ 어디서 불러도 된다. `$W` 를 이 파일 위치에서 뽑으므로(44행) 저장소를
#     어디에 두든, 어느 폴더에서 실행하든 t3_amr 을 기준으로 동작한다.
#
# 여러 번 돌려도 안전하다 (이미 된 단계는 건너뛴다).
#
# 하는 일
#   0. 조건 확인 — Python 3.12 · 드라이버 · 디스크 · 망 · 시스템 라이브러리
#   1. venv 생성  ~/khs/venv
#   2. Isaac Sim 6.0.1.0 + 의존 설치 (NVIDIA 인덱스 · EULA 자동 동의)
#   3. iw.hub 로봇 에셋 다운로드 (236 MB)
#   4. paths.sh 의 GPU 번호가 이 서버에 있는 장치인지 확인
#   5. import 확인 — pxr · isaacsim · live 모듈 체인 · pibt_core 출처
#
# 하지 않는 일 (해서는 안 되는 것)
#   - venv 를 옛 서버에서 복사. `pyvenv.cfg` 에 절대경로가 박혀 있어 깨진다
#   - `~/.cache/ov` 복사. 셰이더 캐시는 GPU·드라이버에 묶인다. 첫 실행이
#     느린 것은 정상이고, 자동으로 다시 만들어진다
#   - `stage/*.usd` 복사. 창고·로봇 경로가 절대경로로 박혀 있어 못 연다.
#     `main.py run` 이 다시 빌드한다
#
# 기준 환경 (여기서 동작 확인, 2026-09-08 jupyter04)
#   Python 3.12.6 · Isaac Sim 6.0.1.0 · 드라이버 570.211.01 · CUDA 12.8
#   L40S ×4 · Ubuntu 24.04.3 · venv 는 /opt/tljh/user/bin/python3.12 기반
# ============================================================
set -uo pipefail

CHECK_ONLY=0
FORCE=0
for a in "$@"; do
    case "$a" in
        --check) CHECK_ONLY=1 ;;
        --force) FORCE=1 ;;
        *) echo "모르는 인자: $a"; echo "사용법: bash install.sh [--check] [--force]"; exit 2 ;;
    esac
done

W="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$W"
VE="$HOME/khs/venv"
ISAAC_VER="6.0.1.0"
NEED_DRV="570.211.01"
NEED_GB=30

fail=0
warn=0
note() { echo "  $*"; }
bad()  { echo "  ★ $*"; fail=1; }
soft() { echo "  · $*"; warn=1; }
head_() { echo; echo "== $*"; }

# ============================================================
# 0) 조건 확인 — 여기서 막는 게 가장 싸다
# ============================================================
head_ "0) 조건 확인"

# --- Python 3.12 (Isaac 6.0.1 휠은 cp312 다) ------------------------
PY=""
for c in python3.12 /opt/tljh/user/bin/python3.12 "$(command -v python3 || true)"; do
    [ -n "$c" ] && command -v "$c" >/dev/null 2>&1 || continue
    v="$("$c" -V 2>&1 | awk '{print $2}')"
    case "$v" in 3.12.*) PY="$(command -v "$c")"; note "Python $v  ($PY)"; break ;; esac
done
if [ -z "$PY" ]; then
    bad "Python 3.12 가 없습니다."
    echo "     Isaac Sim $ISAAC_VER 휠은 cp312 전용입니다 — 3.11/3.13 으로는 설치가 안 됩니다."
    echo "     찾아본 것: python3.12, /opt/tljh/user/bin/python3.12, python3"
    echo "     있는 것:   $(ls /usr/bin/python3.* /opt/tljh/user/bin/python3.* 2>/dev/null | tr '\n' ' ')"
fi

# --- GPU·드라이버 ---------------------------------------------------
NGPU=0
if command -v nvidia-smi >/dev/null 2>&1; then
    drv="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1)"
    cuda="$(nvidia-smi 2>/dev/null | sed -n 's/.*CUDA Version: *\([0-9.]*\).*/\1/p' | head -1)"
    NGPU="$(nvidia-smi -L 2>/dev/null | wc -l)"
    note "$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1) × ${NGPU}장 · 드라이버 $drv · CUDA $cuda"
    # 문자열이 아니라 숫자로 비교한다 ("570.86.10" > "570.211.01" 가 되는 함정)
    _num() { echo "$1" | awk -F. '{printf "%d%03d%03d", $1, $2+0, $3+0}'; }
    # ★ 경고이지 차단이 아니다 (2026-09-13 수정).
    #   `NEED_DRV` 는 **jupyter04 에서 동작을 확인한 값**이지 Isaac 6.0.1 의 최소
    #   요구가 아니다. 그런데 `bad` 라 fail=1 이 되어 설치가 통째로 막혔다 —
    #   Brev(L40S 1장 · 드라이버 565.57.01)에서 걸렸다. 낮은 드라이버로 Kit 이
    #   뜨는지는 **깔아서 띄워 봐야** 알고, 실패해도 venv 만 지우면 된다.
    #   여기서 막으면 확인할 기회 자체가 없다.
    if [ -n "$drv" ] && [ "$(_num "$drv")" -lt "$(_num "$NEED_DRV")" ]; then
        soft "드라이버 $drv < 확인값 $NEED_DRV — Kit 이 안 뜰 수 있습니다."
        soft "  뜨면 그대로 쓰고, 검은 화면이나 기동 실패면 드라이버를 올리세요."
    fi
    busy="$(nvidia-smi --query-compute-apps=gpu_uuid,used_memory --format=csv,noheader 2>/dev/null | wc -l)"
    [ "$busy" -gt 0 ] && soft "이미 ${busy}개 프로세스가 GPU 를 쓰고 있습니다 (공용 서버 — 4단계에서 빈 장치를 고릅니다)"
else
    bad "nvidia-smi 가 없습니다. GPU 서버가 맞습니까?"
fi

# --- 디스크 ---------------------------------------------------------
avail="$(df -BG --output=avail "$HOME" 2>/dev/null | tail -1 | tr -dc '0-9')"
if [ -n "$avail" ]; then
    note "남은 디스크 ${avail} GB  (필요 약 ${NEED_GB} GB — venv 십수 GB + 셰이더 캐시 약 5 GB)"
    [ "$avail" -lt "$NEED_GB" ] && bad "디스크가 부족합니다."
fi

# --- 망 -------------------------------------------------------------
_reach() {
    curl -sS -m 15 -o /dev/null -w '%{http_code}' "https://$1/" 2>/dev/null \
      | grep -qE '^[2345]'      # 5xx 도 도달은 한 것이다
}
for h in pypi.nvidia.com pypi.org \
         omniverse-content-production.s3-us-west-2.amazonaws.com; do
    if _reach "$h"; then note "망 OK  $h"
    else bad "망에서 $h 에 못 닿습니다."; fi
done

# --- 시스템 라이브러리 (pip 로는 안 들어온다) ------------------------
MISS_LIB=""
for so in libGL.so.1 libEGL.so.1 libX11.so.6 libxcb.so.1 libSM.so.6 libgomp.so.1; do
    ldconfig -p 2>/dev/null | grep -q "$so" || MISS_LIB="$MISS_LIB $so"
done
if [ -n "$MISS_LIB" ]; then
    soft "없는 시스템 라이브러리:$MISS_LIB"
    echo "     Kit 이 뜰 때 필요할 수 있습니다. sudo 가 되면:"
    echo "       sudo apt-get install -y libgl1 libegl1 libx11-6 libxcb1 libsm6 libgomp1"
    echo "     안 되면 관리자에게 요청하세요. (설치는 계속합니다)"
fi

# --- ffmpeg ---------------------------------------------------------
# 막지는 않는다 — 2b 단계에서 pip 로 넣는다. `--check` 가 여기서 멈추므로
# 현재 상태만 알려 준다.
if command -v ffmpeg >/dev/null 2>&1; then
    note "ffmpeg 있음  $(command -v ffmpeg)"
else
    note "ffmpeg 없음 — 2b 단계에서 imageio-ffmpeg 로 넣습니다 (루트 불필요)"
fi

echo
if [ "$fail" != 0 ]; then
    echo "★★ 조건이 안 맞습니다. 위 ★ 항목을 해결한 뒤 다시 돌리세요."
    exit 1
fi
[ "$warn" != 0 ] && echo "조건 통과 (· 표시는 경고이며 설치를 막지 않습니다)." \
                 || echo "조건 통과."
if [ "$CHECK_ONLY" = 1 ]; then echo "(--check 이므로 여기서 멈춥니다)"; exit 0; fi

# ============================================================
# 1) venv
# ============================================================
head_ "1) venv  $VE"
if [ -d "$VE" ] && [ "$FORCE" = 1 ]; then
    note "--force 이므로 지웁니다."
    rm -rf "$VE"
fi
if [ -d "$VE" ]; then
    note "이미 있습니다 (다시 만들려면 --force)."
else
    "$PY" -m venv "$VE" || { echo "  ★ venv 생성 실패"; exit 1; }
    note "생성했습니다."
fi
# shellcheck disable=SC1091
source "$VE/bin/activate" || { echo "  ★ activate 실패"; exit 1; }
note "python $(python -V 2>&1 | awk '{print $2}') · $(which python)"
python -m pip install -q --upgrade pip setuptools wheel

# ============================================================
# 2) 패키지
# ============================================================
head_ "2) 패키지 설치 — 수십 분 걸립니다 (Isaac 이 십수 GB 입니다)"

# EULA 는 pip 밖에 있다. 없으면 첫 실행이 멈춘다.
export OMNI_KIT_ACCEPT_EULA=YES

# 이미 되어 있으면 건너뛴다 (재실행 안전)
if python -c "import isaacsim, pxr" 2>/dev/null && [ "$FORCE" != 1 ]; then
    note "isaacsim · pxr 이 이미 들어 있습니다 — 건너뜁니다."
else
    NV="--extra-index-url https://pypi.nvidia.com"

    if [ -f "$W/env/requirements.txt" ]; then
        # 옛 서버에서 pip freeze 한 것이 있으면 그것이 가장 정확하다
        note "env/requirements.txt 로 정확 재현합니다 ($(wc -l < "$W/env/requirements.txt")줄)."
        # shellcheck disable=SC2086
        pip install -r "$W/env/requirements.txt" $NV
        rc=$?
    else
        note "Isaac Sim $ISAAC_VER 를 명시 목록으로 설치합니다."
        note "(env/requirements.txt 가 있으면 그쪽이 더 정확합니다 — freeze_env.sh 참고)"
        # ★ 2026-09-08 jupyter04 의 `pip list` 에 있던 25개를 그대로 못박는다.
        #   메타패키지 extras(`isaacsim[all,extscache]`)에 의존하지 않는다 —
        #   extras 이름은 판마다 바뀌는데 이 목록은 실측이다.
        PKGS=""
        for p in isaacsim isaacsim-app isaacsim-asset isaacsim-benchmark \
                 isaacsim-code-editor isaacsim-core isaacsim-cortex \
                 isaacsim-example isaacsim-extscache-kit \
                 isaacsim-extscache-kit-sdk isaacsim-extscache-physics \
                 isaacsim-gui isaacsim-kernel isaacsim-replicator isaacsim-rl \
                 isaacsim-robot isaacsim-robot-motion isaacsim-robot-setup \
                 isaacsim-ros1 isaacsim-ros2 isaacsim-sensor isaacsim-storage \
                 isaacsim-template isaacsim-test isaacsim-utils; do
            PKGS="$PKGS $p==$ISAAC_VER"
        done
        # shellcheck disable=SC2086
        pip install $PKGS $NV
        rc=$?
        if [ "$rc" != 0 ]; then
            echo
            note "명시 목록이 실패했습니다. 메타패키지 extras 로 한 번 더 시도합니다."
            # shellcheck disable=SC2086
            pip install "isaacsim[all,extscache]==$ISAAC_VER" $NV
            rc=$?
        fi
    fi

    if [ "$rc" != 0 ]; then
        echo
        echo "★★ 설치 실패. 흔한 원인 세 가지:"
        echo "   1. Python 이 3.12 가 아니다        지금: $(python -V 2>&1)"
        echo "   2. pypi.nvidia.com 이 막혔다        pip config 나 프록시 확인"
        echo "   3. 디스크가 찼다                    df -h $HOME"
        echo
        echo "   되돌리려면:  rm -rf $VE"
        exit 1
    fi
fi

python - <<'PY'
import importlib.metadata as md
try:
    print("  isaacsim %s" % md.version("isaacsim"))
except Exception as e:
    print("  ★ isaacsim 버전을 못 읽습니다: %s" % e)
n = len(list(md.distributions()))
print("  설치된 패키지 %d개" % n)
PY
note "isaacsim 런처: $(command -v isaacsim || echo '★ 없음 — 설치가 불완전합니다')"

# ============================================================
# 2b) ffmpeg
# ============================================================
head_ "2b) ffmpeg (영상 조립)"

# `run_record.sh`·`run.sh` 는 프레임을 PNG 로 찍고 **끝나고 나서** ffmpeg 으로
# mp4 를 만든다. 없으면 프레임만 남기고 조용히 넘어간다 — 20분 돌린 뒤에야
# 영상이 없는 걸 알게 된다 (2026-09-13 Brev 에서 그렇게 날렸다).
#
# ★ apt 가 아니라 **pip 의 imageio-ffmpeg** 를 쓴다. 루트가 없어도 되고
#   (사내망 jupyter04 가 그랬다), 저장소가 이미 그 규약이다
#   (`runners/make_clip.sh:54`). 정적 빌드라 시스템 라이브러리도 안 탄다.
#
# 링크는 `~/bin` 이 아니라 **venv 의 bin** 에 건다. activate 가 거기를 PATH 에
# 넣으므로 사용자가 PATH 를 따로 손질할 필요가 없다 — `~/bin` 은 기본 PATH 가
# 아니라서 "깔았는데 command not found" 가 난다.
if command -v ffmpeg >/dev/null 2>&1 && [ "$FORCE" != 1 ]; then
    note "이미 있습니다: $(command -v ffmpeg)"
else
    pip install -q imageio-ffmpeg || soft "imageio-ffmpeg 설치가 실패했습니다."
    FF="$(python -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())' 2>/dev/null)"
    if [ -x "$FF" ]; then
        ln -sf "$FF" "$VE/bin/ffmpeg"
        note "ffmpeg -> $VE/bin/ffmpeg"
    else
        soft "ffmpeg 을 못 얻었습니다. 루트가 되면:  sudo apt-get install -y ffmpeg"
        echo "     없어도 시뮬레이션은 돕니다 — 프레임(PNG)만 남고 mp4 조립을 못 합니다."
    fi
fi

# ★ 버전 문자열만 보면 부족하다. `run_record.sh:234` 가 쓰는 것은 두 가지고,
#   둘 다 **빌드 옵션**이라 있는 척하다 실행 때 죽는다:
#     -c:v libx264          인코더
#     -pattern_type glob    libavformat 이 HAVE_GLOB 으로 빌드돼야 한다
#   그래서 진짜로 한 번 말아 본다. 프레임은 ffmpeg 이 직접 만든다(의존성 0).
if command -v ffmpeg >/dev/null 2>&1; then
    note "$(ffmpeg -version 2>/dev/null | head -1 | cut -c1-72)"
    _T="$(mktemp -d)"
    if ffmpeg -y -loglevel error -f lavfi \
              -i testsrc=duration=1:size=64x64:rate=6 "$_T/f_%06d.png" 2>/dev/null \
       && ffmpeg -y -loglevel error -framerate 6 -pattern_type glob \
              -i "$_T/f_*.png" -c:v libx264 -pix_fmt yuv420p -crf 20 \
              "$_T/o.mp4" 2>/dev/null \
       && [ -s "$_T/o.mp4" ]; then
        note "libx264 · pattern_type glob 동작 확인 (실제 mp4 인코딩)"
    else
        soft "이 ffmpeg 으로는 run_record.sh 의 조립이 실패합니다 (libx264 또는 glob 없음)."
        echo "     루트가 되면:  sudo apt-get install -y ffmpeg"
    fi
    rm -rf "$_T"
fi

# ============================================================
# 3) 로봇 에셋
# ============================================================
head_ "3) iw.hub 로봇 에셋 (236 MB)"
# ★ 받는 자리는 `paths.sh` 의 $ROBOT 하나다 — `$W/robots/iwhub/iw_hub.usd`.
#
#   [2026-09-13 수정] 여기가 이관 뒤에도 Santa 시절 경로를 보고 있었다.
#     - 검사:  $W/warehouse/robots/iwhub/  ← `warehouse/` 가 한 겹 더 있다
#     - 실행:  v2/server/fetch_iwhub.py    ← 옛 스크립트
#   그쪽은 DEST 를 $ROBOT·$IWHUB_DEST 에서 역산하는데, install.sh 는 paths.sh 를
#   source 하지 않아 그 변수가 없다. 그래서 엉뚱한 자리에 받거나 "다운로드는
#   끝났는데 iw_hub.usd 가 없습니다" 로 빠졌다. 로봇이 없으면 씬 빌드가 안 되므로
#   새 서버 설치가 **여기서 멈춘다.**
#   정본은 `tools/fetch_iwhub.py` 다 — DEST 가 $ROBOT 부모로 고정돼 있다.
ROBOT_USD="$W/robots/iwhub/iw_hub.usd"
if [ -f "$ROBOT_USD" ]; then
    note "이미 있습니다."
else
    if python "$W/tools/fetch_iwhub.py"; then
        [ -f "$ROBOT_USD" ] \
          && note "받았습니다: $ROBOT_USD" \
          || bad "다운로드는 끝났는데 $ROBOT_USD 가 없습니다 — tools/fetch_iwhub.py 의 DEST 를 확인하세요."
    else
        bad "다운로드 실패. 망(S3)을 확인하세요. 로봇 없이는 씬 빌드가 안 됩니다."
    fi
fi

# ============================================================
# 3b) 결과 폴더 — .gitignore 되어 있어 clone 직후엔 없다
# ============================================================
head_ "3b) 결과 폴더"
#   `run_record.sh` 는 `$LOGS/record_<태그>.log` 에 쓴다. 그 폴더가 없으면
#   `script` 가 바로 실패한다. `$STAGE` 는 씬 빌드 출력이다.
for d in out logs stage plan; do
    if [ -d "$W/$d" ]; then note "$d/  있음"
    else mkdir -p "$W/$d" && note "$d/  만들었습니다"; fi
done

# ============================================================
# 3c) 입력 자산 — 이 셋이 없으면 설치가 끝나도 주행이 안 된다
# ============================================================
head_ "3c) 입력 자산 (paths.sh 의 \$SCENE · \$MAP · \$ROBOT)"
#   paths.sh 끝에서도 없는 파일을 찍지만, 그때는 이미 주행을 시작한 뒤다.
#   설치 단계에서 막는 게 싸다. 경로 정의는 paths.sh 가 단일 소스이므로
#   여기서 다시 쓰지 않고 **그것을 읽어서** 확인한다 — 두 곳이 갈리지 않게.
#   `#` 부터는 주석이므로 먼저 떼고 공백을 다듬는다. (`\(.*\)#*.*` 는 탐욕
#   매칭이라 주석이 값에 딸려 온다 — 2026-09-13 실측으로 걸렀다.)
_pv() { sed -n "s/^export $1=//p" "$W/paths.sh" | head -1 | sed 's/#.*//' | xargs; }
_SCENE="$(_pv SCENE)"
_MAP="$(_pv MAP)"
SIM="$(cd "$W/.." && pwd)"
for spec in "SCENE:$_SCENE" "MAP:$_MAP/occupancy_grid.npy" "ROBOT:$ROBOT_USD"; do
    nm="${spec%%:*}"; p="${spec#*:}"
    # paths.sh 의 $W·$SIM 을 실제 값으로 편다
    p="${p//\$W/$W}"; p="${p//\$SIM/$SIM}"
    if [ -e "$p" ]; then note "$nm  있음"
    else bad "$nm  없음: $p"; fi
done

# ============================================================
# 4) GPU 번호
# ============================================================
head_ "4) GPU 선택 확인"
# ★ 더 이상 `paths.sh` 를 고치지 않는다 (2026-09-13).
#
#   예전에는 `sed -i` 로 저장소 파일을 직접 고쳤다. 그래서 설치 뒤 `git pull`
#   마다 "Your local changes would be overwritten" 이 났다 (Brev 에서 발생).
#   **설치가 저장소를 더럽히면 안 된다.** 이제 `paths.sh` 가 실행 시점에
#   nvidia-smi 로 가장 한가한 장치를 스스로 고른다 — 여기서는 확인만 한다.
if [ "$NGPU" -gt 0 ]; then
    # shellcheck disable=SC1091
    ( unset GPU; . "$W/paths.sh" >/dev/null 2>&1; echo "$GPU" ) > /tmp/_gpu_pick 2>/dev/null
    PICK="$(cat /tmp/_gpu_pick 2>/dev/null)"; rm -f /tmp/_gpu_pick
    note "이 서버 장치 ${NGPU}개 · paths.sh 가 고른 값: GPU=${PICK:-?}"
    if [ -n "$PICK" ] && [ "$PICK" -ge "$NGPU" ] 2>/dev/null; then
        bad "고른 GPU=$PICK 가 장치 수(${NGPU})를 넘습니다 — paths.sh 의 선택 로직을 보세요."
    fi
    nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu \
               --format=csv 2>/dev/null | sed 's/^/    /'
    note "다른 장치를 쓰려면:  GPU=<번호> bash run_record.sh   (파일은 안 고칩니다)"
fi

# ============================================================
# 5) import 확인
# ============================================================
head_ "5) import 확인"
python - "$W" <<'PY'
import sys, os
W = sys.argv[1]
ok = True
# ★ numba 는 2026-09-16 에 필수가 됐다 (FMS -225 가 `pibt/hgraph.py` 의
#   재계획 거리장을 Numba 커널로 바꾸면서 `from numba import njit` 을
#   모듈 최상단에 넣었다). `pibt_core_v2` 가 그 파일을 직접 로드하므로
#   **계획 층 도구도 주행도 전부 여기서 막힌다** — `live_pibt` ->
#   `isaac_drive` -> `pibt_core_v2` -> `hgraph` 라 별도 venv 로 못 피한다.
#
#   ★★ 버전을 반드시 박아서 설치할 것. `pip install numba` 로 최신을
#      받으면 **Isaac 이 깨진다** (2026-09-16 실제로 깨뜨렸다):
#
#          isaacsim-core 6.0.1.0  requires  llvmlite==0.46.0
#          numba 0.67             requires  llvmlite>=0.49
#
#      numba 와 llvmlite 는 한 칸씩 맞물린다. Isaac 핀에서 **역산**해서
#      고른다 — llvmlite 0.46 의 짝은 numba 0.63 이다.
#
#          pip install "numba==0.63.*" "llvmlite==0.46.0" "numpy==2.3.1"
#
#      확인된 조합 (jupyter04, 2026-09-16):
#          numba 0.63.1 · llvmlite 0.46.0 · numpy 2.3.1 · isaacsim 6.0.1.0
#
#      numba 0.67 은 `coverage.types.Tracer` 를 쓰는데 Isaac 이 핀한
#      coverage 7.4.4 에는 그 API 가 없어 import 조차 안 된다.
#      (남은 불일치 하나: coverage 7.16.1 vs isaacsim-kernel 의 ==7.4.4.
#       coverage 는 테스트 도구라 런타임 영향이 없어 보이나 미검증이다.)
for m in ("numpy", "numba", "pxr", "isaacsim"):
    try:
        __import__(m); print("  OK   %s" % m)
    except Exception as e:
        print("  ★★   %s | %s: %s" % (m, type(e).__name__, e)); ok = False
sys.path.insert(0, os.path.join(W, "amr", "make_path"))
sys.path.insert(0, os.path.join(W, "path"))
for m in ("pibt_scene", "metrics", "lifelong", "battery", "dispatch",
          "isaac_drive", "amr_driver_v2"):
    try:
        __import__(m); print("  OK   %s" % m)
    except Exception as e:
        print("  ★★   %s | %s: %s" % (m, type(e).__name__, e)); ok = False
try:
    import pibt_core_v2 as pc
    print("  pibt_core 출처: %s%s"
          % (pc.__pibt_source__, "   ★ 벤더 후퇴" if pc.__pibt_vendored__ else ""))
except Exception as e:
    print("  ★★   pibt_core_v2 | %s: %s" % (type(e).__name__, e)); ok = False
sys.exit(0 if ok else 1)
PY
IMPORT_RC=$?

# ============================================================
# 끝
# ============================================================
echo
if [ "$IMPORT_RC" != 0 ] || [ "$fail" != 0 ]; then
    echo "★★ 아직 안 됩니다. 위 ★ 항목을 해결하세요."
    echo "   패키지를 다시 깔려면:  bash install.sh --force"
    exit 1
fi
cat <<EOF
════════════════════════════════════════════════════════════
 설치 완료
════════════════════════════════════════════════════════════

 매번 쓸 것:
   cd $W
   source $VE/bin/activate
   source paths.sh

 ── 먼저 이것부터 — 물리가 옛 서버와 같은지 확인한다 ──────

   STREAM=0 bash run.sh --planner pibt_h

   첫 실행은 셰이더 컴파일로 느립니다 (정상, 캐시가 만들어집니다).
   t=10·20·30s 에서 아래가 그대로 나오면 이전 성공입니다:

     probe 지문   0.07323
     체크포인트   5,4 / 10,8 / 19,17

   다르면 자산이나 코어가 갈린 것입니다. \`pibt_core 출처\` 줄과
   \`warehouse/\` 의 씬·맵을 옛 서버와 비교하세요
   (옛 서버에서 freeze_env.sh 를 돌려두면 체크섬으로 대조됩니다).

 ── 그 다음 ──────────────────────────────────────────────

   bash run_record.sh          녹화 + mp4 (약 29분, 10배속 73초 영상)
   python amr/main.py list     계획기 목록

 ── 업무 종료 후 전원 충전존 복귀 (시연용) ────────────────

   PIBT_HORIZON=550 PIBT_ORDER_END=315 PIBT_ORDER_GAP=40 \\
     REPLAN=1 bash run_record.sh

   시작 30초 안에 이 두 줄이 나와야 합니다 — 안 나오면 바로 끊으세요:
     [pibt] ... 주문간격 40틱 · 업무종료 315틱
     [pibt] 계획 종료 시 충전존 주차 12/12대
EOF
