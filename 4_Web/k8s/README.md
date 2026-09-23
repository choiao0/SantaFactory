# 웹 계층 k3s 배포 — backend · pdf · frontend (S15P21A106-258)

EC2 compose 에서 상태가 없는 세 컨테이너를 k3s Deployment 로 옮긴다. 목적은 **무중단 배포**(새 파드가 준비된 뒤 옛 파드 교체)와 준비·생존 확인, 자원 상한의 명시.
DB·RabbitMQ·Redis·MinIO·EMQX·레지스트리는 compose 에 남는다. 배경과 판단은 `5_Docs/소프트웨어 아키텍처/쿠버네티스_도입.md`.

| 파일 | 역할 |
|---|---|
| `namespace.yaml` | 네임스페이스 `web` |
| `compose-services.yaml` | compose 의 db·rabbitmq·redis 를 클러스터 안 이름으로 풀어 주는 headless Service + EndpointSlice(→ 172.26.3.57) |
| `pdf.yaml` | PDF 변환기 Deployment + ClusterIP Service `pdf:3000` |
| `backend.yaml` | 백엔드 Deployment(롤링, probe) + 고정 ClusterIP `10.43.0.80:8080` |
| `frontend.yaml` | 프런트 Deployment + 고정 ClusterIP `10.43.0.30:80` |

## 구조

```
브라우저 ─▶ host nginx(443) ─┬─ /      ─▶ 10.43.0.30   (frontend 파드)
                            └─ /api/  ─▶ 10.43.0.80:8080 (backend 파드)
backend 파드 ─▶ db · rabbitmq · redis (이름) ─▶ 172.26.3.57:5432/5672/6379 ─▶ compose 컨테이너
             └▶ pdf (이름) ─▶ pdf 파드
```

- 세 파드는 EC2 노드(`ip-172-26-3-57`)에만 배치한다. DB·브로커가 거기 있고, control-plane taint 는 toleration 으로 넘는다.
- 백엔드 env 는 Secret `backend-env`. Jenkins 가 `docker compose config` 로 compose 가 조립한 환경을 그대로 뽑아 만든다 — compose 파일이 env 의 단일 출처로 남는다.
- NodePort 를 쓰지 않는 이유: 보안그룹이 전 포트 개방이라 30000번대가 인터넷에서 닿는다. ClusterIP 는 EC2 안에서만 닿는다.
- compose 포트를 `172.26.3.57` 에도 바인딩하므로 공인 NIC 로 들어오는 5432·5672·6379 는 `3_FMS/infra/firewall`(DOCKER-USER) 이 막는다. **compose 바인딩보다 먼저 적용한다.**

## EC2 에서 한 번 하는 순서

```bash
# 0. 방화벽 먼저 — allow.env 에 ALLOW_5432/5672/6379 를 빈 값으로 두면 공인 NIC 전면 차단
cd ~/S15P21A106/3_FMS/infra/firewall && sudo bash apply.sh && sudo iptables -S DOCKER-USER | grep -c DROP     # 5

# 1. 파드 → 노드 통신을 ufw 가 막는지. CoreDNS 가 Ready 가 아니면 아래 두 줄
sudo kubectl -n kube-system get pods -o wide
# sudo ufw allow from 10.42.0.0/16 && sudo ufw allow from 10.43.0.0/16

# 2. compose 포트 바인딩 반영(db·rabbitmq·redis 재생성, 몇 초 끊김 — 백엔드가 재접속한다)
cd ~/S15P21A106/4_Web && docker compose up -d db rabbitmq redis

# 3. EC2 노드가 레지스트리에서 받을 수 있게 — nginx /v2/ 는 GCP NAT IP 만 허용하므로 EC2 노드는 루프백 미러를 쓴다
sudo sh -c 'printf "mirrors:\n  \"j15a106.p.ssafy.io\":\n    endpoint:\n      - \"http://127.0.0.1:5000\"\n" > /etc/rancher/k3s/registries.yaml'
sudo systemctl restart k3s                                  # GCP 워커 파드는 계속 돈다

# 4. 서비스 CIDR 확인(10.43.0.0/16 이어야 고정 ClusterIP 가 맞는다) 뒤 적용
sudo kubectl get svc kubernetes -o jsonpath='{.spec.clusterIP}'; echo
for img in santafactory-be santafactory-pdf santafactory-fe; do docker tag $img:latest 127.0.0.1:5000/$img:latest && docker push 127.0.0.1:5000/$img:latest; done
sudo kubectl apply -f 4_Web/k8s/namespace.yaml -f 4_Web/k8s/compose-services.yaml
docker compose -f 4_Web/docker-compose.yml --env-file 4_Web/.env config --format json \
  | python3 -c 'import sys,json; [print(f"{k}={v}") for k,v in json.load(sys.stdin)["services"]["backend"]["environment"].items()]' > /tmp/backend.env
sudo kubectl -n web create secret generic backend-env --from-env-file=/tmp/backend.env --dry-run=client -o yaml | sudo kubectl apply -f - && rm -f /tmp/backend.env
sudo kubectl apply -f 4_Web/k8s/pdf.yaml -f 4_Web/k8s/backend.yaml -f 4_Web/k8s/frontend.yaml
sudo kubectl -n web rollout status deployment/backend --timeout=300s

# 5. 확인
sudo kubectl -n web exec deploy/frontend -- nslookup db          # 172.26.3.57
curl -s http://10.43.0.80:8080/actuator/health/readiness          # {"status":"UP"}
curl -sI http://10.43.0.30/ | head -1                             # 200

# 6. host nginx 두 곳을 ClusterIP 로(server-setup/nginx-santafactory.conf 참고) → 브라우저로 로그인·견적·SSE 확인
sudo nginx -t && sudo systemctl reload nginx

# 7. compose 쪽 셋을 내린다. 24시간 관찰 뒤 Jenkins 전역 환경변수 WEB_DEPLOY=k3s
docker compose -f 4_Web/docker-compose.yml stop backend pdf frontend
```

## 배포 (Jenkins)

`Jenkinsfile` 의 백엔드·프런트 스테이지가 `WEB_DEPLOY`(전역 환경변수, 기본 `compose`) 로 갈린다.
- `compose`: 지금까지처럼 EC2 compose.
- `k3s`: 빌드 → `127.0.0.1:5000` push → Secret 갱신 → 매니페스트 apply(image 줄만 빌드 번호로) → `rollout status` → compose 쪽 컨테이너 `stop` → 레지스트리 태그 정리.
전환은 값을 `k3s` 로, 되돌리기는 값을 지우고(또는 `compose`) release 를 다시 돌리면 된다.

## 되돌리기

host nginx 두 곳을 `127.0.0.1:3000`·`127.0.0.1:8080` 으로 되돌리고 `docker compose up -d backend pdf frontend`. 파드는 `kubectl -n web scale deployment --all --replicas=0`.

## 주의

- 파괴적 마이그레이션(컬럼 삭제·타입 변경)을 내는 release 는 두 버전이 같은 스키마를 못 쓴다. 그때만 `backend.yaml` 의 `maxSurge` 를 0 으로.
- 롤링 중 두 백엔드가 잠깐 `sim.result` 를 나눠 받는다. 옛 파드에 붙은 SSE 는 종료 시 닫히고 브라우저가 새 파드로 다시 붙어 snapshot 을 받는다.
- 백엔드 상한 2Gi 는 `docker stats a106-backend` 실사용을 보고 조정한다.
