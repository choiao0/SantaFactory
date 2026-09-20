#!/bin/bash
# GCP DES 워커 노드 시작 스크립트 — 인스턴스 템플릿 "시작 스크립트" 란에 그대로 붙인다 (S15P21A106-249, 2026-09-18).
# 매 부팅마다 루트로 돈다. 하는 일 하나: 이 VM 을 EC2 k3s 의 에이전트 노드(role=sim-worker)로 합류시킨다.
# 워커 컨테이너는 여기서 올리지 않는다 — EC2 k3s 의 Deployment(infra/k8s/sim-worker-deployment.yaml)가 노드에 배치한다.
#
# tailnet 을 쓰지 않는다(249). 합류는 공인 https://j15a106.p.ssafy.io:6443 으로 GCP→EC2 한 방향이면 된다
# (EC2 ufw 가 Cloud NAT 고정 IP 만 허용, kubectl logs/exec 는 에이전트가 연 터널로 돌아온다). 이미지는 nginx 443 뒤
# 레지스트리(infra/nginx/registry-v2.conf)에서 공인 CA 로 받으므로 registries.yaml 이 필요 없다.
#
# 템플릿 메타데이터:
#   k3s-token    (필수) EC2 /var/lib/rancher/k3s/server/agent-token 의 값. 서버 토큰(server/token)이 아니다 — 에이전트 전용
#   k3s-url      (선택) 기본 https://j15a106.p.ssafy.io:6443
#   k3s-version  (선택) 기본 v1.36.4+k3s1 = EC2 서버 버전. 에이전트가 서버보다 새 마이너 버전이면 합류가 거부된다
set -u
MD="http://metadata.google.internal/computeMetadata/v1/instance/attributes"
md() { curl -sf -H "Metadata-Flavor: Google" "$MD/$1" || true; }
TOKEN=$(md k3s-token)
URL=$(md k3s-url);     URL=${URL:-https://j15a106.p.ssafy.io:6443}
VER=$(md k3s-version); VER=${VER:-v1.36.4+k3s1}
if [ -z "$TOKEN" ]; then
    echo "start.sh: 메타데이터 k3s-token 이 없어 k3s 에 합류하지 않는다" >&2
    exit 1
fi

# 246 세대 VM 이미지에는 compose 워커 4개가 restart 정책과 함께 남아 있을 수 있다. 그대로 두면 k3s 워커와 겹쳐 소비하므로 내린다.
if command -v docker > /dev/null 2>&1; then
    old=$(docker ps -aq --filter name=fms-estimate-estimate-worker)
    if [ -n "$old" ]; then
        # shellcheck disable=SC2086
        docker rm -f $old > /dev/null && echo "start.sh: 옛 compose 워커 $(echo "$old" | wc -l)개 제거"
    fi
fi

# 처음 만든 VM 에만 설치한다. 재부팅(Spot 중지→재개)은 설치 스크립트가 등록한 k3s-agent 서비스가 스스로 뜬다.
if [ ! -x /usr/local/bin/k3s ]; then
    curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION="$VER" K3S_URL="$URL" K3S_TOKEN="$TOKEN" \
        INSTALL_K3S_EXEC="agent --node-label role=sim-worker" sh -
else
    systemctl start k3s-agent
fi
