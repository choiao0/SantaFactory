#!/usr/bin/env bash
# 이 PC → GCP 워커 VM 배포 (S15P21A106-246, 2026-09-18). 레포 3_FMS 를 VM ~/fms/3_FMS 로 올리고 이미지 재빌드·재기동.
# ★ 249 부터 쓰지 않는다 — 워커는 EC2 k3s 의 Deployment 가 노드에 배치하고 코드 배포는 Jenkins FMS 단계(FMS_DEPLOY=k3s)가 한다.
#   tailnet SSH 가 있어야 도는 246 세대 스크립트라 비상용으로만 남긴다(README "246 세대로 되돌려야 하면").
#   bash deploy_gcp.sh [tailnet-ip ...]     기본 = MIG 3대(09-18). 새 이미지를 구울 때는 한 대에 배포 → 중지 → 이미지 → 템플릿 교체.
set -euo pipefail
REPO=$(cd "$(dirname "$0")/../../.." && pwd)         # infra/gcp → 저장소 루트
KEY="${GCP_SSH_KEY:-$HOME/.ssh/id_ed25519_gcp}"
USER_="${GCP_SSH_USER:-claude-gpubox}"
HOSTS=("$@"); [ ${#HOSTS[@]} -gt 0 ] || HOSTS=(100.124.62.47 100.66.243.31 100.87.169.93)
for H in "${HOSTS[@]}"; do
    SSH="ssh -o BatchMode=yes -o ConnectTimeout=10 -i $KEY"
    echo "== $H =="
    rsync -az --delete --exclude __pycache__ --exclude .pytest_cache --exclude "*.pyc" --exclude results --exclude tests \
        -e "$SSH" "$REPO/3_FMS/sim_engine" "$REPO/3_FMS/map" "$REPO/3_FMS/contracts" "$REPO/3_FMS/ai_theta" "$USER_@$H:~/fms/3_FMS/"   # ai_theta: Dockerfile 이 COPY 한다(-206·-253)
    rsync -az --exclude __pycache__ -e "$SSH" "$REPO/3_FMS/infra/out" "$REPO/3_FMS/infra/worker" \
        "$REPO/3_FMS/infra/requirements.txt" "$REPO/3_FMS/infra/estimate.Dockerfile" \
        "$REPO/3_FMS/infra/compose.estimate.gcp.yml" "$USER_@$H:~/fms/3_FMS/infra/"
    $SSH "$USER_@$H" 'cd ~/fms/3_FMS/infra && test -f .env.estimate || { echo "★ .env.estimate 없음 (RABBITMQ_USER/PASSWORD)"; exit 1; }
        docker compose -f compose.estimate.gcp.yml --env-file .env.estimate up -d --build 2>&1 | tail -3
        docker compose -f compose.estimate.gcp.yml --env-file .env.estimate ps --format "{{.Name}} {{.Status}}"'
done
