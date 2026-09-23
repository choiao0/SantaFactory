# EC2 호스트 방화벽 — docker publish 포트 출발지 제한 (S15P21A106-245)

## 왜
2026-09-17 실측. EC2 보안그룹은 전 포트 개방(임시 리스너로 TCP 6443·UDP 51820 이 밖에서 통함)이고, ufw 는 22·80·443 만
허용하지만 **docker 가 publish 한 포트에는 ufw 가 적용되지 않는다** — docker 가 FORWARD 체인에 자기 ACCEPT 규칙을 ufw 체인보다
앞에 끼우기 때문이다. EMQX compose 는 `1883:1883`, MinIO 는 `9002:9000` 으로 0.0.0.0 에 publish 돼 있어 둘 다 인터넷에 열렸다.
EMQX 로그에 Censys(66.132.x)·Palo Alto Expanse(205.210.31.x·147.185.132.x) 스캐너의 인증 실패가 09-14~16 매일 찍혔다.

`DOCKER-USER` 는 docker 가 관리자용으로 비워 두는 체인이고 DOCKER 규칙보다 먼저 평가된다. 포트는 `--dport` 가 아니라
`-m conntrack --ctorigdstport` 로 맞춘다 — FORWARD 에 올 때는 DNAT 가 끝나 9002 가 컨테이너 포트 9000 으로 바뀌어 있다(실측: `--dport 9002` 는 안 막혔다). 여기에 **공인 NIC(ens5) 인바운드**만
보는 규칙을 두면 tailnet(tailscale0)·루프백·컨테이너 간 트래픽은 그대로다. ufw `after.rules` 에 두어 재부팅에도 남긴다.

## 파일
| 파일 | 역할 |
|---|---|
| `docker-user.after.rules` | 블록 템플릿. `#@ALLOW <포트>` 자리에 허용 IP 마다 RETURN 이 렌더된다 |
| `allow.env.example` → `allow.env` | 허용 IP 목록(gitignore). `IFACE` · `ALLOW_1883` · `ALLOW_9002` |
| `apply.sh` | 렌더 → `/etc/ufw/after.rules` 의 BEGIN/END 블록 교체(없으면 추가, 백업 남김) → `ufw reload` → 규칙 출력·개수 검증 |

## 쓰는 법 (EC2, ubuntu)
```
scp -r 3_FMS/infra/firewall ubuntu@EC2:~/firewall && ssh ubuntu@EC2
cp ~/firewall/allow.env.example ~/firewall/allow.env && vi ~/firewall/allow.env   # 허용 IP
bash ~/firewall/apply.sh --dry-run          # 렌더 확인
sudo bash ~/firewall/apply.sh               # 적용
sudo bash ~/firewall/apply.sh --remove      # 되돌리기
```
노드를 추가할 때(클라우드 GPU 노드·GCP 워커)는 `allow.env` 에 IP 를 붙이고 `apply.sh` 를 다시 돌린다. 멱등이다.

## 누가 어디로 붙는가 (2026-09-17)
| 포트 | 정당한 클라이언트 | 경로 | 이 규칙의 영향 |
|---|---|---|---|
| 1883 EMQX | GPU 박스 엣지, host-orch, fms-core | tailnet(100.100.149.68) · docker 네트워크 | 없음 |
| 9002 MinIO | GPU 박스 엣지 업로드 | tailnet | 없음 |
| 9002 MinIO | 브라우저 영상 재생 | 443 → nginx `/media` → 127.0.0.1:9002 | 없음 |
| 1883·9002 | 인터넷 스캐너 | ens5 | **차단** |

## 확인
```
sudo iptables -S DOCKER-USER                       # RETURN(허용) → DROP → RETURN
sudo iptables -L DOCKER-USER -v -n | grep DROP     # 패킷 카운터가 늘면 차단이 동작 중
docker logs --since 24h emqx 2>&1 | grep -c authentication_failure   # 다음 날 0 이어야 한다
```
밖에서 `bash -c '</dev/tcp/j15a106.p.ssafy.io/1883'` 이 허용 IP 에서는 통하고, 그 밖에서는 시간 초과여야 한다.

## 한계·다음
- ens5 에는 공인 IPv6 가 없어 `after6.rules` 는 두지 않았다. docker 는 `[::]:1883` 도 열지만 닿을 주소가 없다.
- 대시보드(18083·9001·15672)는 compose 에서 이미 127.0.0.1 이다. 밖에 나갈 이유가 없는 포트는 publish 주소로 묶는 편이 먼저다.
- RabbitMQ 5672 는 127.0.0.1 에만 열려 있다(tailnet 리스너는 09-18 닫음). GCP 워커는 AMQPS 5671(nginx stream, `infra/nginx/`)로 붙고,
  nginx 는 호스트 프로세스라 `ufw allow from 34.47.111.62 to any port 5671 proto tcp` 로 제한한다(-246, 적용됨).
- k3s 6443 도 같은 방식이다(-249): `ufw allow from 34.47.111.62 to any port 6443 proto tcp`.
  EC2 노드 위 파드(CoreDNS·웹 파드)도 API 서버를 공인 주소 52.79.145.233:6443 으로 부른다(k3s advertise 주소). AWS 를 돌아 자기 공인 IP 가
  출발지로 들어오므로 `ufw allow from 52.79.145.233 to any port 6443 proto tcp` 가 필요하다. 없으면 CoreDNS 가 새 Service 를 못 받아
  이름 조회가 NXDOMAIN 이 된다(-258, 2026-09-23 적용). 레지스트리는 공인 포트를 따로 열지 않고 nginx 443 `/v2/` 안에서 출발지를 제한한다(infra/nginx/registry-v2.conf).
- Jenkins 에는 안 붙였다. 배포는 SSH 로 `apply.sh` 한 번(host-orch 와 같은 수동 관례).
