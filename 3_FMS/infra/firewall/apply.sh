#!/usr/bin/env bash
# EC2 호스트 방화벽 — docker 가 publish 한 EMQX 1883 · MinIO 9002 를 공인 NIC 에서 출발지 제한한다 (S15P21A106-245).
#
#   sudo bash apply.sh              allow.env 로 렌더 → /etc/ufw/after.rules 의 블록 교체(없으면 추가) → ufw reload
#   bash apply.sh --dry-run         렌더 결과만 출력 (루트 불필요)
#   sudo bash apply.sh --remove     블록 제거 + reload (되돌리기)
#   --env=<파일>                    allow.env 대신 다른 파일
#
# 왜 이렇게 하나 (2026-09-17 실측): 보안그룹은 전 포트 개방이고, compose 가 1883·9002 를 0.0.0.0 에 publish 했고,
# docker 의 FORWARD 규칙이 ufw 체인보다 앞이라 ufw 의 "22·80·443 만" 이 이 트래픽엔 적용된 적이 없다. EMQX 로그에
# Censys·Expanse 스캐너의 인증 실패가 매일 찍혔다. DOCKER-USER 는 docker 규칙보다 먼저 평가되는 관리자 체인이고,
# ufw after.rules 에 두면 재부팅에도 남는다(맨 iptables 는 사라진다).
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
TEMPLATE="$HERE/docker-user.after.rules"
ENV_FILE="$HERE/allow.env"
RULES="${UFW_AFTER_RULES:-/etc/ufw/after.rules}"
BEGIN="# BEGIN S15P21A106 DOCKER-USER"
END="# END S15P21A106 DOCKER-USER"
MODE=apply
for a in "$@"; do
    case "$a" in
        --dry-run) MODE=dry ;;
        --remove)  MODE=remove ;;
        --env=*)   ENV_FILE="${a#--env=}" ;;
        -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
        *) echo "알 수 없는 인자: $a" >&2; exit 2 ;;
    esac
done

render() {
    local IFACE=ens5 ALLOW_1883="" ALLOW_9002="" ALLOW_5432="" ALLOW_5672="" ALLOW_6379=""
    if [ -f "$ENV_FILE" ]; then
        # shellcheck disable=SC1090
        . "$ENV_FILE"
    else
        echo "※ $ENV_FILE 없음 — 허용 목록 비움(공인 NIC 에서 1883·9002·5432·5672·6379 전부 차단)" >&2
    fi
    awk -v iface="$IFACE" -v a1883="$ALLOW_1883" -v a9002="$ALLOW_9002" \
        -v a5432="$ALLOW_5432" -v a5672="$ALLOW_5672" -v a6379="$ALLOW_6379" '
        function emit(port, list,   n, arr, i) {
            n = split(list, arr, /[ ,]+/)
            for (i = 1; i <= n; i++) if (arr[i] != "")
                printf("-A DOCKER-USER -i %s -p tcp -m conntrack --ctorigdstport %s --ctdir ORIGINAL -s %s -j RETURN\n", iface, port, arr[i])
        }
        /^#@ALLOW 1883$/ { emit("1883", a1883); next }
        /^#@ALLOW 9002$/ { emit("9002", a9002); next }
        /^#@ALLOW 5432$/ { emit("5432", a5432); next }
        /^#@ALLOW 5672$/ { emit("5672", a5672); next }
        /^#@ALLOW 6379$/ { emit("6379", a6379); next }
        { gsub(/@IFACE@/, iface); print }
    ' "$TEMPLATE"
}

strip_block() {   # stdin → stdout, BEGIN..END 블록 제거
    awk -v b="$BEGIN" -v e="$END" '$0 == b {skip = 1} !skip {print} $0 == e {skip = 0}'
}

reload_fw() {
    if [ "${SKIP_RELOAD:-0}" = "1" ]; then echo "(SKIP_RELOAD=1 — ufw reload 생략)"; return; fi
    # ufw reload 는 after.rules 를 noflush 로 다시 읽어 DOCKER-USER 에 규칙이 **쌓인다** — 먼저 비운다.
    iptables -F DOCKER-USER 2>/dev/null || true
    ufw reload >/dev/null
    echo "── iptables -S DOCKER-USER ──"
    iptables -S DOCKER-USER
}

case "$MODE" in
    dry)
        render ;;
    remove)
        [ "$(id -u)" = 0 ] || [ "${SKIP_RELOAD:-0}" = "1" ] || { echo "루트로 실행할 것 (sudo)" >&2; exit 1; }
        cp -a "$RULES" "$RULES.bak-$(date +%Y%m%d-%H%M%S)"
        tmp=$(mktemp); strip_block < "$RULES" > "$tmp"; cat "$tmp" > "$RULES"; rm -f "$tmp"
        echo "블록 제거: $RULES"; reload_fw ;;
    apply)
        [ "$(id -u)" = 0 ] || [ "${SKIP_RELOAD:-0}" = "1" ] || { echo "루트로 실행할 것 (sudo)" >&2; exit 1; }
        block=$(render)
        cp -a "$RULES" "$RULES.bak-$(date +%Y%m%d-%H%M%S)"
        tmp=$(mktemp); strip_block < "$RULES" > "$tmp"
        { cat "$tmp"; [ -n "$(tail -c1 "$tmp")" ] && echo; printf '%s\n' "$block"; } > "$RULES"; rm -f "$tmp"
        n_rules=$(printf '%s\n' "$block" | grep -c '^-A ')
        echo "블록 기록: $RULES (규칙 ${n_rules}줄, 백업 $RULES.bak-*)"
        reload_fw
        if [ "${SKIP_RELOAD:-0}" != "1" ]; then
            live=$(iptables -S DOCKER-USER | grep -c '^-A ')
            [ "$live" = "$n_rules" ] || echo "★ 살아 있는 규칙 ${live}줄 ≠ 렌더 ${n_rules}줄 — 중복/누락 확인" >&2
        fi ;;
esac
