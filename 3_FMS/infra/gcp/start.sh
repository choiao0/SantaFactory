#!/bin/bash
# GCP DES 워커 시작 스크립트 — 인스턴스 템플릿 "시작 스크립트" 란에 그대로 붙인다 (S15P21A106-246, 2026-09-18).
# 매 부팅마다 루트로 돈다. 하는 일 둘:
#   1) 템플릿 메타데이터 tailscale-authkey 가 있고 아직 가입 표시(/var/lib/tailscale/.joined)가 없으면 상태 파일을 지우고 새 노드로 가입
#   2) 워커 compose 기동 (restart 정책이 있어 재부팅엔 어차피 뜨지만, 처음 만든 VM 에도 같은 절차로 뜨게 한다)
set -u
MD="http://metadata.google.internal/computeMetadata/v1/instance/attributes"
KEY=$(curl -sf -H "Metadata-Flavor: Google" "$MD/tailscale-authkey" || true)
# ★ logout 만으로는 안 된다 (2026-09-18 실측). 이미지에 든 /var/lib/tailscale/tailscaled.state 에 머신 키까지 들어 있어
#   복제된 VM 셋이 같은 노드(100.110.129.36)를 나눠 썼고, `up --authkey` 는 authURL 로 튕겨 옛 신원으로 돌아갔다.
#   상태 파일을 지우고 데몬을 다시 띄운 뒤 가입해야 새 머신이 된다. 이미 자기 노드가 있는 VM(재부팅)은 건너뛴다.
if [ -n "$KEY" ] && [ ! -f /var/lib/tailscale/.joined ]; then
    systemctl stop tailscaled
    rm -f /var/lib/tailscale/tailscaled.state
    systemctl start tailscaled
    sleep 2
    if timeout 90 tailscale up --authkey="$KEY" --hostname="$(hostname -s)" --accept-dns=false; then
        touch /var/lib/tailscale/.joined
    fi
fi
WORKERS=$(curl -sf -H "Metadata-Flavor: Google" "$MD/worker-replicas" || nproc)
cd /home/claude-gpubox/fms/3_FMS/infra || exit 1
WORKER_REPLICAS="$WORKERS" docker compose -f compose.estimate.gcp.yml --env-file .env.estimate up -d
