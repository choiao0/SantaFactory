#!/usr/bin/env bash
# 사설 레지스트리 태그 정리 (S15P21A106-248): 숫자(빌드 번호) 태그 중 최근 KEEP 개만 남기고 나머지 manifest 를 지운 뒤 GC.
#   bash registry-prune.sh fms-estimate-worker 3
set -euo pipefail
REPO=$1
KEEP=${2:-3}
REG=${REGISTRY:-127.0.0.1:5000}
ACCEPT='Accept: application/vnd.docker.distribution.manifest.v2+json, application/vnd.oci.image.manifest.v1+json, application/vnd.oci.image.index.v1+json'

tags=$(curl -sf "http://$REG/v2/$REPO/tags/list" \
    | python3 -c 'import sys,json; print("\n".join(t for t in (json.load(sys.stdin).get("tags") or []) if t.isdigit()))' \
    | sort -n)
old=$(echo "$tags" | head -n -"$KEEP")
for t in $old; do
    digest=$(curl -sfI -H "$ACCEPT" "http://$REG/v2/$REPO/manifests/$t" \
        | awk 'tolower($1)=="docker-content-digest:"{print $2}' | tr -d '\r')
    if [ -n "$digest" ] && curl -sf -X DELETE "http://$REG/v2/$REPO/manifests/$digest"; then
        echo "레지스트리 태그 삭제 $REPO:$t"
    fi
done
# 삭제된 manifest 가 가리키던 레이어를 실제로 디스크에서 지운다
docker exec a106-registry registry garbage-collect /etc/docker/registry/config.yml > /dev/null 2>&1 || true
