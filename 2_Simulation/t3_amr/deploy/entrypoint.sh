#!/usr/bin/env bash
# t3_amr 러너 컨테이너 엔트리포인트.
#   edge            상주 엣지 — MQTT(Sparkplug) NCMD Start 를 받아 run_record.sh 를 돌리고 mp4 를 MinIO 에 올린다 (기본)
#   record [N]      엣지 없이 한 번 녹화 (컨테이너·GPU·촬영 검증용). N = 로봇 대수, 기본 3
#   check           GPU · Isaac import · ffmpeg · 에셋(iw.hub·선반) · 계획기 원본(3_FMS/sim_engine)만 확인하고 끝
#   shell           bash
set -euo pipefail
cd /app/2_Simulation/t3_amr            # Dockerfile 의 $T3. 저장소와 같은 두 단 배치 — path/pibt_core_v2.py 가 ../../3_FMS/sim_engine 을 찾는다

export OMNI_KIT_ACCEPT_EULA=YES
export GPU="${GPU:-0}"                      # 컨테이너 안에서는 보이는 장치가 곧 0 번이다 — paths.sh 의 자동 선택을 막는다
export STREAM="${STREAM:-1}"                # 촬영에는 뷰포트(라이브스트림)가 있어야 한다 (run_record.sh 가 검사)
mkdir -p /data/out /data/stage /data/logs /data/state   # paths.sh 의 OUT·STAGE·LOGS 는 여기로 링크돼 있다 (Dockerfile)

case "${1:-edge}" in
  check)
    nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader || true
    python - <<'PY'
import importlib.metadata as md
import os
import sys
print("isaacsim", md.version("isaacsim"))
import isaacsim  # noqa: F401  (무거운 import 는 Kit 기동이라 여기서 하지 않는다)
print("import ok")
missing = [f for f in ("robots/iwhub/iw_hub.usd", "robots/shelf/amr_shelf.usd") if not os.path.isfile(f)]
print("assets", "ok" if not missing else "MISSING " + " ".join(missing))
sys.path.insert(0, "path")
import pibt_core_v2  # noqa: F401  — 계획기 로더. 원본을 못 찾으면 stderr 에 벤더 후퇴 경고를 찍는다
import pibt_core
print("planner", pibt_core.__pibt_source__, "vendored" if pibt_core.__pibt_vendored__ else "upstream",
      "MOVE_TICKS", pibt_core.MOVE_TICKS)
if missing or pibt_core.__pibt_vendored__:
    sys.exit(1)
PY
    ffmpeg -version | head -1
    ;;
  record)
    export PIBT_N="${2:-${PIBT_N:-3}}"
    source paths.sh
    exec bash run_record.sh --planner "${PLANNER:-pibt_h}"
    ;;
  edge)
    source paths.sh
    exec python -m edge --env-from-environ
    ;;
  shell)
    exec bash
    ;;
  *)
    exec "$@"
    ;;
esac
