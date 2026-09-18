# k3s 워커 배포 (S15P21A106-248)

견적 DES 워커를 EC2 의 k3s 가 GCP 노드 3대에 배치한다. 배경과 결정은 `5_Docs/소프트웨어 아키텍처/쿠버네티스_도입_검토.md`.
브로커 접속은 GCP compose 워커와 같다 — 공인 5671(TLS) + 전용 계정 `sim-worker`(`infra/nginx/`). 바뀐 것은 워커를 올리는 주체만이다.

| 파일 | 역할 |
|---|---|
| `namespace.yaml` | 네임스페이스 `fms` |
| `sim-worker-secret.example.yaml` | 브로커 주소 Secret 의 예시. 실제 값은 EC2 에서 명령으로 만든다 |
| `sim-worker-deployment.yaml` | 워커 12개, `role=sim-worker` 노드에 4개씩, CPU 1·메모리 3Gi |
| `registry-prune.sh` | 사설 레지스트리(`../compose.registry.yml`)의 오래된 빌드 태그 정리. Jenkins 가 배포 뒤 호출 |

## EC2 (k3s 서버) — 2026-09-18 설치됨

```
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="server --disable traefik --disable servicelb \
  --node-ip 100.100.149.68 --advertise-address 100.100.149.68 --tls-san 100.100.149.68 \
  --flannel-iface tailscale0 --node-taint node-role.kubernetes.io/control-plane=true:NoSchedule" sh -
```
- traefik·servicelb 를 끈 이유: 80·443 을 nginx 가 쓴다. flannel 을 tailscale0 에 묶어 노드 간 통신은 tailnet 으로만 간다.
- EC2 노드에는 taint 를 걸어 워커가 올라가지 않는다(백엔드·DB 와 코어를 다투지 않게).
- `/etc/rancher/k3s/registries.yaml` 에 사설 레지스트리를 평문으로 받는 설정(아래 노드와 같은 내용).
- Jenkins 용 접속 파일: `/etc/rancher/k3s/k3s.yaml` 의 `127.0.0.1` 을 `100.100.149.68` 로 바꿔 Jenkins 파일 자격증명 `k3s-kubeconfig` 로 등록.

## GCP 노드 합류

인스턴스 템플릿의 시작 스크립트(`../gcp/start.sh`)가 부팅마다 한다 — 메타데이터 `k3s-url`·`k3s-token` 을 읽어 registries.yaml 을 쓰고 `k3s agent --node-label role=sim-worker` 로 합류.
Spot 회수로 VM 이 다시 만들어져도 같은 절차로 돌아온다. 사라진 옛 노드 객체는 `kubectl delete node <이름>` 으로 치운다.

## 처음 적용 (EC2 에서 한 번)

```
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml      # 또는 sudo kubectl
kubectl apply -f 3_FMS/infra/k8s/namespace.yaml
. ~/rabbitmq-keys/sim-worker.env                   # RABBITMQ_USER / RABBITMQ_PASSWORD
kubectl -n fms create secret generic sim-worker-broker \
  --from-literal=RABBITMQ_URL="amqps://$RABBITMQ_USER:$RABBITMQ_PASSWORD@j15a106.p.ssafy.io:5671/"
kubectl apply -f 3_FMS/infra/k8s/sim-worker-deployment.yaml
kubectl -n fms set image deployment/sim-worker worker=100.100.149.68:5000/fms-estimate-worker:<빌드번호>
kubectl -n fms rollout status deployment/sim-worker
```

## 확인

```
kubectl get nodes -L role                                  # GCP 3대 Ready, role=sim-worker
kubectl -n fms get pods -o wide                            # 12개 Running, 노드마다 4개
docker exec a106-rabbitmq rabbitmqctl list_queues name consumers | grep sim.request   # 12
```

## 배포 (Jenkins)

`Jenkinsfile` FMS 단계가 `FMS_DEPLOY` 값으로 갈린다(Jenkins 전역 환경변수, 기본 `compose`).
- `compose`: 지금까지처럼 EC2 에서 compose 워커. `WORKER_REPLICAS=0` 이면 올리지 않는다.
- `k3s`: 빌드 → `127.0.0.1:5000` 으로 push → `kubectl set image` → rollout 완료 대기 → EC2 compose 워커 내림 → 레지스트리 태그 정리.
전환은 값을 `k3s` 로, 되돌리기는 `compose` 로 바꾸고 release 를 다시 돌리면 된다.

## 워커 개수·자원

- 개수는 Deployment 의 `replicas` 하나. 노드를 늘리면 합류 뒤 숫자만 올린다. `kubectl -n fms scale deployment/sim-worker --replicas=16`
- 메모리 3Gi 는 로봇 13대·주문 4,000 건 실측 기준. 로봇 28대·주문 6,000 건은 넘칠 수 있다(`../gcp/README.md`).

## tailnet 을 없앨 때

지금은 노드 합류·레지스트리 pull 이 tailnet(100.100.149.68) 위로 간다. tailnet 을 걷어내면 합류 주소를 공인 `j15a106.p.ssafy.io:6443`(ufw 로 GCP NAT IP 만), 레지스트리를 nginx 443 `/v2/` 뒤로 옮기고, Deployment 에 `dnsPolicy: Default` 를 넣는다.
정리된 표는 `5_Docs/소프트웨어 아키텍처/쿠버네티스_도입_검토.md` 5-1 절.
