# T3 AMR 경로 정의 — 한 번 source 하면 이후 명령이 짧아진다.
#
#   source 2_Simulation/t3_amr/paths.sh
#
# 스크립트들이 전부 환경변수를 먼저 보므로, 폴더를 옮겨도 이 파일만 고치면 된다.
# (하드코딩된 경로를 서버에서 손으로 고치다가 기능이 통째로 빠진 판이 남은 적이
#  있다 — 2026-09-04. 그래서 경로는 한 곳에 모은다.)

# ★ 자기 위치에서 뽑는다. 옛 판은 `$HOME/khs/wh` 를 박아 두어서 저장소를 옮기면
#   조용히 남의 폴더를 봤다. `source` 라 $0 은 못 쓰고 BASH_SOURCE 를 쓴다.
export W="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
export SIM="$(cd "$W/.." && pwd)"                    # 2_Simulation

# --- 입력 자산 (보존) ---
# ★ 씬도 t3_amr 안의 것이 단일 소스다 (2026-09-11 수정).
#   예전에는 `$SIM/t3_warehouse/warehouse_scene.usd`(팀 원본, 9/2 · 405 KB)를
#   가리켰다. 그런데 9/9 에 새 격자로 다시 구운 씬(913 KB)이 저장소 안
#   `warehouse/scene/` 에 이미 들어와 있었고, 그게 안 쓰이고 있었다 —
#   맵은 새 창고인데 화면은 옛 창고인 상태가 여기서 나왔다.
#   `build_scene.py` 가 덮어쓰는 대상도 아래 경로다. 둘을 어긋나게 두면
#   "다시 구웠는데 안 바뀐다" 가 반복된다.
export SCENE=$W/warehouse/scene/warehouse_scene.usd  # 구운 T3 창고 씬 (build_scene.py 산출)
# ★ 계획 맵은 t3_amr 안의 것이 **단일 소스**다 (occupancy_grid sha 563e6aeb…).
#   팀 기본 맵(t3_warehouse_map/map, v6.0)은 격자가 다르고 stations.json 에
#   `handoff` 가 없다 — GOAL_CATS 다섯 중 하나가 조용히 빠진다. 씬을 v6.0
#   격자로 다시 지은 뒤에 이 줄을 그쪽으로 옮긴다.
export MAP=$W/warehouse/map
export ROBOT=$W/robots/iwhub/iw_hub.usd              # iw.hub 에셋 (git 제외, tools/fetch_iwhub.py 가 여기 받는다)

# --- 파생물 (지워도 된다. 빌드로 다시 만들어진다) ---
export STAGE=$W/stage                                # 빌드된 씬 USD
export PLAN=$W/plan                                  # 궤적 (계획 산출물, 로컬에서 옴)

# --- 결과 ---
export OUT=$W/out                                    # kpi · trace · rec · video
export LOGS=$W/logs

# --- 실행·계획 모듈 ($W/path/) — **8개다** ---
#   amr_driver_v2 · pibt_core_v2 · isaac_drive · pibt_scene
#   lifelong · battery · dispatch · metrics
#
#   ★ 4개로 적어 두었다가 틀렸다 (2026-09-08). 현행 pibt_h 는 뒤의 넷을 추가로
#     import 하므로, 앞의 넷만 올리면 `plan_and_build_lifelong` 이 ImportError
#     로 죽는다. 배포 목록을 바꿀 때는 러너의 sys.path 주입과 **함께** 확인할 것.
#
#   러너는 BASE 와 BASE/path 를 모두 sys.path 에 넣으므로 AMR_BASE 는 그
#   부모(=W)를 가리키면 된다.
export AMR_BASE=$W
export MODS=$W/path

# --- 스트리밍 ---
# ★ 미리 준 값이 있으면 그것을 쓴다 (2026-09-13).
#   `hostname -I` 는 **내부 IP** 다. 사내망(jupyter04)에서는 그게 접속 주소라
#   맞지만, 클라우드(Brev 등)에서는 밖에서 그 주소로 못 붙는다 — WebRTC 서버가
#   "미디어를 여기로 보내라"고 알려주는 주소라서 틀리면 화면이 안 나온다.
#   예전에는 무조건 덮어써서 셸에서 공인 IP 를 줘도 소용이 없었다.
#       LAN_IP=$(curl -s ifconfig.me) bash run.sh ...
export LAN_IP=${LAN_IP:-$(hostname -I | awk '{print $1}')}
# ★ 포트를 바꿔서 내보내는 클라우드용 (2026-09-13 Brev). 기본은 Isaac 기본값이라
#   사내망은 달라지는 것이 없다. 자세한 이유는 `amr/path/_common.py` 의 주석.
#   Brev 는 공개 포트를 제가 정하고 **Destination Port 만 편집**을 받아 준다.
#   그러니 공개 포트에 맞춰 Destination 을 고치고, 여기에 같은 번호를 준다.
export SIGNAL_PORT=${SIGNAL_PORT:-49100}   # TCP 시그널링
export STREAM_PORT=${STREAM_PORT:-47998}   # UDP 미디어
# ★ 장치 선택 (2026-09-14 수정)
#
#   1) `GPU=1 bash run.sh ...` 로 준 값이 항상 이긴다
#   2) **3번이 있으면 3번** — 여러 장 꽂힌 서버(jupyter04 L40S x4)에서 0~2 는
#      다른 팀이 쓴다. 다른 번호를 쓰려면 `PREFER_GPU=2 source paths.sh`
#   3) 3번이 없으면(Brev 처럼 1장) **가장 한가한 장치**
#   4) nvidia-smi 가 없으면(로컬·WSL) 0 — 어차피 안 쓴다
#
#   예전에는 `${GPU:-3}` 하드코딩이었고, 서버가 바뀌면 `install.sh` 4단계가
#   **이 파일을 sed 로 고쳤다.** 추적 중인 파일이라 그 뒤 `git pull` 마다
#       error: Your local changes to the following files would be overwritten
#   가 났다 (2026-09-13 Brev 에서 발생). 설치가 저장소를 더럽히면 안 된다.
#   그래서 하드코딩이 아니라 **있으면 쓰고 없으면 떨어지는** 방식으로 둔다.
#
#   ★ `cut -d, -f1` 로 **index 만** 떼야 한다. `tr -dc '0-9'` 만 쓰면
#     "2, 100" 이 `2100` 이 된다 (2026-09-13 실측으로 걸렀다).
#   ★ **다시 source 해도 새로 고른다** (2026-09-14). `paths.sh` 는 `GPU` 를
#     export 하므로, 한 번 source 한 셸에는 값이 남는다. 그러면 다음 source
#     때 `[ -z "$GPU" ]` 가 거짓이라 **선택 로직이 통째로 건너뛰어진다** —
#     이 파일을 고쳐도 그 셸에서는 옛 값이 계속 쓰였다 (실제로 겪었다).
#     앞선 source 가 넣은 값은 "사용자가 준 값" 이 아니므로 지우고 다시 고른다.
#     사용자가 직접 준 값(`GPU=1 bash ...`)은 이 표시가 없어 그대로 살아남는다.
if [ -n "${GPU:-}" ] && [ "${GPU}" = "${_PATHS_GPU_AUTO:-}" ]; then
    unset GPU
fi
if [ -z "${GPU:-}" ]; then
    _pg="${PREFER_GPU:-3}"
    if nvidia-smi --query-gpu=index --format=csv,noheader,nounits 2>/dev/null \
         | tr -d ' ' | grep -qx "$_pg"; then
        GPU="$_pg"
    else
        GPU="$(nvidia-smi --query-gpu=index,memory.used \
                 --format=csv,noheader,nounits 2>/dev/null \
               | sort -t, -k2 -n | head -1 | cut -d, -f1 | tr -dc '0-9')"
    fi
    unset _pg
    export GPU=${GPU:-0}              # nvidia-smi 가 없거나 비었을 때
    export _PATHS_GPU_AUTO="$GPU"     # 자동 선택 표시 — 다음 source 때 다시 고른다
else
    unset _PATHS_GPU_AUTO             # 사용자가 준 값이다. 건드리지 않는다
fi

# [patch_gpu_isolate] GPU 격리 — 이 한 줄이 run.sh·run_record.sh·build_scene 전부에 적용된다
#   `--/renderer/activeGpu=$GPU` 는 **렌더러(Vulkan)만** 묶는다. PhysX/warp 쪽
#   CUDA 는 보이는 장치마다 primary context 를 만든다 — 실측 2026-09-08 13:03:
#   GPU0 518 · GPU1 436 · GPU2 436 · GPU3 6449 MiB. 1·2 는 일도 안 하면서
#   VRAM 을 잡아 다른 팀 문의를 받았다. CUDA_VISIBLE_DEVICES 만이 이걸 막는다.
#
#   activeGpu 는 그대로 $GPU — Vulkan 열거는 이 변수를 따르지 않아 인덱스가
#   안 밀린다 (2026-09-09 실측: GPU3 6479 MiB 작업 · GPU0 6.89 MiB 그래픽만).
#
#     GPU=1 bash run.sh ...       다른 GPU
#     ISOLATE=0 bash run.sh ...   격리 해제 (렌더러가 엉뚱한 장치로 갈 때)
if [ "${ISOLATE:-1}" = "1" ]; then
    export CUDA_VISIBLE_DEVICES=$GPU
fi

mkdir -p "$STAGE" "$PLAN" "$OUT" "$LOGS"

echo "W=$W"
echo "  입력  SCENE=$(basename $SCENE)  MAP=$(basename $MAP)  ROBOT=$(basename $ROBOT)"
echo "  파생  STAGE=$STAGE"
echo "  계획  PLAN=$PLAN"
echo "  결과  OUT=$OUT  LOGS=$LOGS"
echo "  LAN=$LAN_IP  시그널 =$SIGNAL_PORT/TCP  미디어 =$STREAM_PORT/UDP"
echo "  GPU=$GPU  CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-<격리 해제>}"
for f in "$SCENE" "$ROBOT" "$MAP/occupancy_grid.npy"; do
    [ -e "$f" ] || echo "  ★ 없음: $f"
done
