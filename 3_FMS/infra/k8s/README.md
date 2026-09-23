# k3s 워커 배포 (S15P21A106-248 → 249)

견적 DES 워커를 EC2 의 k3s 가 GCP 노드 3대에 배치한다. 배경과 결정은 `5_Docs/소프트웨어 아키텍처/쿠버네티스_도입.md`.
브로커 접속은 GCP compose 워커와 같다 — 공인 5671(TLS) + 전용 계정 `sim-worker`(`infra/nginx/`). 바뀐 것은 워커를 올리는 주체만이다.

**tailnet 을 쓰지 않는다(249).** 248 은 노드 합류·레지스트리·Jenkins 접속을 tailnet(100.100.149.68) 위에 두었는데, 도입 검토 5-1 절의
표대로 공인 경로로 옮겼다: 합류 `https://j15a106.p.ssafy.io:6443`(ufw 로 GCP NAT IP 만), 레지스트리 nginx 443 `/v2/`(공인 CA, NAT IP 만),
파드 DNS `dnsPolicy: Default`, Jenkins kubeconfig 서버 `127.0.0.1:6443`. GCP→EC2 한 방향이면 된다 — kubectl logs/exec 는 에이전트가 연
터널로 돌아오고, EC2↔GCP 파드 통신은 없지만 워커는 브로커에 밖으로 붙기만 한다.

| 파일 | 역할 |
|---|---|
| `namespace.yaml` | 네임스페이스 `fms` |
| `sim-worker-secret.example.yaml` | 브로커 주소 Secret 의 예시. 실제 값은 EC2 에서 명령으로 만든다 |
| `sim-worker-deployment.yaml` | 워커 12개, `role=sim-worker` 노드에 4개씩, CPU 1·메모리 3Gi, `dnsPolicy: Default` |
| `registry-prune.sh` | 사설 레지스트리(`../compose.registry.yml`)의 오래된 빌드 태그 정리. Jenkins 가 배포 뒤 호출 |
| `../nginx/registry-v2.conf` | 노드가 이미지를 받는 공인 경로 — 443 `/v2/` → 127.0.0.1:5000, 출발지 NAT IP, GET/HEAD 만 |
| `../gcp/start.sh` | GCP 템플릿 시작 스크립트 — 에이전트 합류 |

## EC2 (k3s 서버)

2026-09-18 설치본은 tailnet 주소로 세워졌다(`--node-ip/--advertise-address/--tls-san 100.100.149.68 --flannel-iface tailscale0`).
공인 경로로 바꾸려면 설치 스크립트를 다시 돌린다 — 만든 객체(네임스페이스·Deployment·Secret)는 그대로 남는다.

```
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="server --disable traefik --disable servicelb \
  --tls-san j15a106.p.ssafy.io --node-external-ip <EC2 공인 IP> \
  --node-taint node-role.kubernetes.io/control-plane=true:NoSchedule" sh -
sudo ufw allow from 34.47.111.62 to any port 6443 proto tcp comment "k3s agents GCP (249)"
sudo cp 3_FMS/infra/nginx/registry-v2.conf /etc/nginx/snippets/   # 443 server 블록에 include snippets/registry-v2.conf; → nginx -t && reload
sudo rm -f /etc/rancher/k3s/registries.yaml                        # 평문 tailnet 레지스트리 설정 — 더 안 쓴다
```
- traefik·servicelb 를 끈 이유: 80·443 을 nginx 가 쓴다. EC2 노드에는 taint 를 걸어 워커가 올라가지 않는다(백엔드·DB 와 코어를 다투지 않게).
- `--tls-san` 에 공인 이름이 없으면 에이전트의 TLS 검증이 실패한다. `--node-external-ip` 는 에이전트가 서버 주소 목록을 받을 때 사설 172.26 대신
  공인 주소를 쓰게 하려는 것이다 — 합류 뒤 에이전트 로그(`journalctl -u k3s-agent`)에 172.26 주소 접속 실패가 반복되면 `--advertise-address` 까지
  공인 IP 로 바꿔야 한다(미검증, 2026-09-18).
- 6443·10250·8472 는 호스트 프로세스 리슨이라 ufw 가 먹는다(기본 deny). 공인에서 닫혀 있음을 실측했다(09-18). tailnet 을 걷어내면
  tailscale 이 INPUT 앞에 넣던 `ts-input ACCEPT` 도 사라지므로 위 ufw 허용이 필수다.
- Jenkins 용 접속 파일: `/etc/rancher/k3s/k3s.yaml` 그대로(서버 `127.0.0.1:6443`, Jenkins 가 EC2 안) → Jenkins 파일 자격증명 `k3s-kubeconfig`.
  248 때 등록한 것은 서버가 100.100.149.68 이라 교체한다.

## GCP 노드 합류

인스턴스 템플릿의 시작 스크립트(`../gcp/start.sh`)가 부팅마다 한다 — 메타데이터 `k3s-token`(에이전트 토큰)을 읽어
`k3s agent --node-label role=sim-worker` 로 합류. 서버 주소·버전은 `k3s-url`·`k3s-version` 로 바꿀 수 있고 기본은 공인 6443·v1.36.4+k3s1.
registries.yaml 은 필요 없다(레지스트리가 공인 CA 뒤). Spot 회수로 VM 이 다시 만들어져도 같은 절차로 돌아온다.
사라진 옛 노드 객체는 `kubectl delete node <이름>` 으로 치운다.

## 처음 적용 (EC2 에서 한 번)

```
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml      # 또는 sudo kubectl
kubectl apply -f 3_FMS/infra/k8s/namespace.yaml
. ~/rabbitmq-keys/sim-worker.env                   # RABBITMQ_USER / RABBITMQ_PASSWORD
kubectl -n fms create secret generic sim-worker-broker \
  --from-literal=RABBITMQ_URL="amqps://$RABBITMQ_USER:$RABBITMQ_PASSWORD@j15a106.p.ssafy.io:5671/"
kubectl apply -f 3_FMS/infra/k8s/sim-worker-deployment.yaml
kubectl -n fms set image deployment/sim-worker worker=j15a106.p.ssafy.io/fms-estimate-worker:<빌드번호>
kubectl -n fms rollout status deployment/sim-worker
```

## 확인

```
kubectl get nodes -L role                                  # GCP 3대 Ready, role=sim-worker
kubectl -n fms get pods -o wide                            # 12개 Running, 노드마다 4개
docker exec a106-rabbitmq rabbitmqctl list_queues name consumers | grep sim.request   # 12
curl -sI https://j15a106.p.ssafy.io/v2/ | head -1          # 허용 IP 밖(이 PC)에서는 403, GCP 노드에서는 200
```

## 배포 (Jenkins)

`Jenkinsfile` FMS 단계가 `FMS_DEPLOY` 값으로 갈린다(Jenkins 전역 환경변수, 기본 `compose`).
- `compose`: 지금까지처럼 EC2 에서 compose 워커. `WORKER_REPLICAS=0` 이면 올리지 않는다.
- `k3s`: 빌드 → `127.0.0.1:5000` 으로 push → `kubectl apply`(namespace + `sim-worker-deployment.yaml`, image 줄만 `j15a106.p.ssafy.io/…:<빌드번호>` 로 치환) → rollout 완료 대기 → EC2 compose 워커 내림 → 레지스트리 태그 정리.
  매니페스트가 기준이라 자원·개수·정책 변경도 release 로 나간다. Secret 은 값이 레포에 없어 apply 대상이 아니다.
전환은 값을 `k3s` 로, 되돌리기는 `compose` 로 바꾸고 release 를 다시 돌리면 된다. k3s 경로는 FMS 변경이 감지될 때만 도니 전환 첫 release 는 전체 빌드(기준 SHA 삭제)로.
노드가 합류하기 전에 `k3s` 로 켜면 rollout 대기 600 s 가 실패하고 뒤의 EMQX·fms-core 단계까지 건너뛴다 — 노드 Ready 를 본 뒤 켠다.

## 워커 개수·자원

- 개수는 Deployment 의 `replicas` 하나 — 파일을 고쳐 release 에 넣는다. `kubectl -n fms scale deployment/sim-worker --replicas=16` 은 즉시 반영되지만 다음 release 때 파일 값으로 돌아온다.
- 환경변수는 EC2 `compose.estimate.yml` 과 같아야 한다(-253): `RABBITMQ_URL` 은 Secret, 나머지(지금은 `THETA_MODEL`)는 Deployment 의 `env`. EC2 판에 변수를 더하면 여기와 `compose.estimate.gcp.yml` 에도 더한다.
- 메모리 3Gi 는 로봇 13대·주문 4,000 건 실측 기준. 로봇 28대·주문 6,000 건은 넘칠 수 있다(`../gcp/README.md`).
- 노드 하나가 빠지면 12개 유지가 아니라 8개 가동 + 4개 Pending 이다(CPU 요청 900m × 4 = 노드 한도). 노드가 돌아오면 자동 배치된다.
