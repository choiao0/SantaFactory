#!/usr/bin/env bash
# t3_amr 러너 컨테이너 엔트리포인트.
#   edge            상주 엣지 — MQTT(Sparkplug) NCMD Start 를 받아 run_record.sh 를 돌리고 mp4 를 MinIO 에 올린다 (기본)
#   record [N]      엣지 없이 한 번 녹화 (컨테이너·GPU·촬영 검증용). N = 로봇 대수, 기본 3
#   check           Isaac import 와 GPU 만 확인하고 끝
#   shell           bash
set -euo pipefail
cd /app/t3_amr

export OMNI_KIT_ACCEPT_EULA=YES
export GPU="${GPU:-0}"                      # 컨테이너 안에서는 보이는 장치가 곧 0 번이다 — paths.sh 의 자동 선택을 막는다
export STREAM="${STREAM:-1}"                # 촬영에는 뷰포트(라이브스트림)가 있어야 한다 (run_record.sh 가 검사)
mkdir -p /data/out /data/stage /data/logs /data/state   # paths.sh 의 OUT·STAGE·LOGS 는 여기로 링크돼 있다 (Dockerfile)

case "${1:-edge}" in
  check)
    nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader || true
    python - <<'PY'
import importlib.metadata as md
print("isaacsim", md.version("isaacsim"))
import isaacsim  # noqa: F401  (무거운 import 는 Kit 기동이라 여기서 하지 않는다)
print("import ok")
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
