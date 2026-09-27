#!/usr/bin/env bash
# .env → users.csv (EMQX 내장 DB 부트스트랩, 평문). 브로커가 최초 기동 때 한 번만 읽는다 —
# 바꾸려면 다시 만들고 `docker compose down -v` 후 재기동하거나 대시보드/REST 로 고친다.
# 반드시 `docker compose up` 보다 먼저 실행한다 (없으면 compose 가 멈추도록 compose.yml 이 configs 로 참조한다).
# sudo 로 실행해도 된다 — 파일은 644 로 남겨 컨테이너(uid 1000)가 읽게 한다.
#   ./bootstrap_users.sh            # ./.env 사용
#   ./bootstrap_users.sh path/.env  # 다른 env 파일
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
ENV_FILE="${1:-$HERE/.env}"
[ -f "$ENV_FILE" ] || { echo "$ENV_FILE 없음 — cp .env.example .env 후 값을 채운다" >&2; exit 1; }
set -a; . "$ENV_FILE"; set +a
for v in MQTT_PW_AMR MQTT_PW_FMS_CORE MQTT_PW_SIM_RUNNER MQTT_PW_HOST_ORCH MQTT_PW_SIM_WMS; do
  [ -n "${!v:-}" ] || { echo "$v 가 비어 있다" >&2; exit 1; }
  case "${!v}" in *,*) echo "$v 에 쉼표는 쓸 수 없다 (CSV)" >&2; exit 1;; esac
done
N=${AMR_POOL_SIZE:-6}
# GPU 1대에서 러너 컨테이너 여러 개(spec244 §E, 실측 3개 동시가 빠듯) — 계정군 전체가 acl.conf 의
# sim-runner-gpu\d+ 정규식에 걸리는 같은 비밀번호를 쓴다(-244). 컨테이너를 안 띄우는 노드가 있어도
# 계정만 미리 있는 건 무해하다 — ${username} 스코핑이 서로를 막는다.
R=${SIM_RUNNER_POOL_SIZE:-3}
OUT="$HERE/users.csv"
{
  echo "user_id,password,is_superuser"
  for i in $(seq -f "%02g" 1 "$N"); do echo "amr$i,$MQTT_PW_AMR,false"; done
  echo "fms-core,$MQTT_PW_FMS_CORE,false"
  for i in $(seq -f "%02g" 1 "$R"); do echo "sim-runner-gpu$i,$MQTT_PW_SIM_RUNNER,false"; done
  echo "host-orch,$MQTT_PW_HOST_ORCH,false"
  echo "sim-wms,$MQTT_PW_SIM_WMS,false"
} > "$OUT"
chmod 644 "$OUT"      # 컨테이너의 emqx 사용자(uid 1000)가 읽어야 한다 — 600 이면 부트스트랩이 조용히 건너뛰어진다 (EC2 2026-09-08 실측)
echo "$OUT: amr01..amr$(printf %02d "$N") + fms-core, sim-runner-gpu01..$(printf %02d "$R"), host-orch, sim-wms"
