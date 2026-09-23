# 웹 계층 k3s 배포 — backend · pdf · frontend (S15P21A106-258)

EC2 compose 에서 상태가 없는 세 컨테이너를 k3s Deployment 로 옮긴다. 목적은 **무중단 배포**(새 파드가 준비된 뒤 옛 파드 교체)와 준비·생존 확인, 자원 상한의 명시.
DB·RabbitMQ·Redis·MinIO·EMQX·레지스트리는 compose 에 남는다. 배경과 판단은 `5_Docs/소프트웨어 아키텍처/쿠버네티스_도입.md`.

| 파일 | 역할 |
|---|---|
| `namespace.yaml` | 네임스페이스 `web` |
| `compose-services.yaml` | compose 의 db·rabbitmq·redis 를 클러스터 안 이름으로 풀어 주는 headless Service + EndpointSlice(→ 도커 게이트웨이 172.18.0.1) |
| `pdf.yaml` | PDF 변환기 Deployment + ClusterIP Service `pdf:3000` |
| `backend.yaml` | 백엔드 Deployment(롤링, probe) + 고정 ClusterIP `10.43.0.80:8080` |
| `frontend.yaml` | 프런트 Deployment + 고정 ClusterIP `10.43.0.30:80` |

## 구조

```
브라우저 ─▶ host nginx(443) ─┬─ /      ─▶ 10.43.0.30   (frontend 파드)
                            └─ /api/  ─▶ 10.43.0.80:8080 (backend 파드)
backend 파드 ─▶ db · rabbitmq · redis (이름) ─▶ 172.18.0.1:5432/5672/6379 ─▶ compose 컨테이너
             └▶ pdf (이름) ─▶ pdf 파드
```

- 세 파드는 EC2 노드(`ip-172-26-3-57`)에만 배치한다. DB·브로커가 거기 있고, control-plane taint 는 toleration 으로 넘는다.
- 백엔드 env 는 Secret `backend-env`. Jenkins 가 `docker compose config` 로 compose 가 조립한 환경을 그대로 뽑아 만든다 — compose 파일이 env 의 단일 출처로 남는다.
- NodePort 를 쓰지 않는 이유: 보안그룹이 전 포트 개방이라 30000번대가 인터넷에서 닿는다. ClusterIP 는 EC2 안에서만 닿는다.
- compose 포트는 도커 게이트웨이 `172.18.0.1` 에 추가로 바인딩한다. 서버 안 가상 주소라 인터넷에서 닿지 않아 방화벽 변경이 없다. EC2 사설 IP(172.26.3.57)는 공인 IP 와 1:1 NAT 라 밖에서 닿아 쓰지 않는다.

## 첫 전환 순서

EC2 에는 저장소가 없다(도커 컨테이너와 Jenkins 작업 폴더만). 파일은 PC 에서 `scp` 로 보내고, compose 재기동은 release 가 한다.

**PC 에서** — yaml 5개를 EC2 `~/k3s-web/` 에 평평하게 복사한다. PowerShell 이면 `$KEY="$HOME\Downloads\<키>.pem"` 뒤 `-i $KEY`. 키 권한 오류가 나면 `icacls <pem> /inheritance:r /grant:r "${env:USERNAME}:R"`.

```bash
cd <저장소>
ssh -i <키> ubuntu@j15a106.p.ssafy.io 'mkdir -p ~/k3s-web'
scp -i <키> 4_Web/k8s/*.yaml ubuntu@j15a106.p.ssafy.io:~/k3s-web/
```

**EC2 에서**

```bash
# 0. 도커 게이트웨이 확인 — 172.18.0.1 이 아니면 docker-compose.yml·compose-services.yaml 의 주소를 그 값으로 맞춘다
docker network inspect santafactory_default -f '{{(index .IPAM.Config 0).Gateway}}'
# 윈도우에서 옮긴 파일은 줄바꿈부터 정리한다(CRLF 가 남으면 셸·iptables 가 읽지 못한다)
sed -i 's/\r$//' ~/k3s-web/*

# 1. 파드 → 노드 통신을 ufw 가 막는지. CoreDNS 가 Ready 가 아니면 주석 줄 실행
sudo kubectl -n kube-system get pods -o wide
# sudo ufw allow from 10.42.0.0/16 && sudo ufw allow from 10.43.0.0/16

# 2. EC2 노드가 레지스트리에서 받을 수 있게 — nginx /v2/ 는 GCP NAT IP 만 허용하므로 EC2 노드는 루프백 미러를 쓴다
sudo sh -c 'printf "mirrors:\n  \"j15a106.p.ssafy.io\":\n    endpoint:\n      - \"http://127.0.0.1:5000\"\n" > /etc/rancher/k3s/registries.yaml'
sudo systemctl restart k3s                                  # GCP 워커 파드는 계속 돈다
```

**release 1회** (`WEB_DEPLOY` 없이, 기존 compose 경로). 이 MR 이 develop → release 로 나가면 Jenkins 가 `up -d backend` 로 db·rabbitmq·redis 를 새 포트 바인딩으로 재생성하고, actuator 가 들어간 백엔드 이미지를 빌드한다. 끝나면 `docker port a106-db` 에 `172.18.0.1:5432` 가 보여야 한다.

**EC2 에서** — 파드를 올리고 확인한 뒤 입구를 바꾼다.

```bash
# 3. 서비스 CIDR 확인(10.43.0.0/16 이어야 고정 ClusterIP 가 맞는다), 이미지 push, 안내판 적용
sudo kubectl get svc kubernetes -o jsonpath='{.spec.clusterIP}'; echo
for img in santafactory-be santafactory-pdf santafactory-fe; do docker tag $img:latest 127.0.0.1:5000/$img:latest && docker push 127.0.0.1:5000/$img:latest; done
sudo kubectl apply -f ~/k3s-web/namespace.yaml -f ~/k3s-web/compose-services.yaml

# 4. Secret — 지금 도는 compose 백엔드의 환경을 그대로 뽑는다(저장소·.env 없이). db·rabbitmq·redis·pdf 이름은 그대로 k8s Service 가 풀어 준다
docker inspect a106-backend --format '{{range .Config.Env}}{{println .}}{{end}}' \
  | grep -E '^(TZ|DB_|RABBITMQ_|REDIS_|MINIO_|JWT_|MAIL_|ADMIN_|DEMO_|PDF_|APP_)' > /tmp/backend.env
sudo kubectl -n web create secret generic backend-env --from-env-file=/tmp/backend.env --dry-run=client -o yaml | sudo kubectl apply -f - && rm -f /tmp/backend.env

# 5. 파드 적용과 확인 (compose 백엔드와 나란히 뜬다 — 포트가 달라 충돌 없음)
sudo kubectl apply -f ~/k3s-web/pdf.yaml -f ~/k3s-web/backend.yaml -f ~/k3s-web/frontend.yaml
sudo kubectl -n web rollout status deployment/backend --timeout=300s
sudo kubectl -n web exec deploy/frontend -- nslookup db          # 172.18.0.1
curl -s http://10.43.0.80:8080/actuator/health/readiness          # {"status":"UP"}
curl -sI http://10.43.0.30/ | head -1                             # 200

# 6. host nginx 세 곳(/, /api/, swagger)의 127.0.0.1:3000·8080 을 10.43.0.30·10.43.0.80:8080 으로 → 브라우저로 로그인·견적·SSE 확인
sudo nano /etc/nginx/sites-available/santafactory && sudo nginx -t && sudo systemctl reload nginx

# 7. compose 쪽 셋을 내린다(두 백엔드가 같은 큐를 나눠 받지 않게). 24시간 관찰 뒤 Jenkins 전역 환경변수 WEB_DEPLOY=k3s
docker stop a106-backend a106-pdf a106-frontend
```

이후 release 는 k3s 경로가 `docker compose up -d db rabbitmq redis minio` 로 compose 쪽 넷을 맞추고 파드를 교체한다. compose 의 backend·pdf·frontend 는 다시 뜨지 않는다.

## 배포 (Jenkins)

`Jenkinsfile` 의 백엔드·프런트 스테이지가 `WEB_DEPLOY`(전역 환경변수, 기본 `compose`) 로 갈린다.
- `compose`: 지금까지처럼 EC2 compose.
- `k3s`: 빌드 → `127.0.0.1:5000` push → Secret 갱신 → 매니페스트 apply(image 줄만 빌드 번호로) → `rollout status` → compose 쪽 컨테이너 `stop` → 레지스트리 태그 정리.
전환은 값을 `k3s` 로, 되돌리기는 값을 지우고(또는 `compose`) release 를 다시 돌리면 된다.

## 되돌리기

host nginx 세 곳을 `127.0.0.1:3000`·`127.0.0.1:8080` 으로 되돌리고 `docker start a106-backend a106-pdf a106-frontend`(stop 만 했으므로 컨테이너가 남아 있다). 파드는 `sudo kubectl -n web scale deployment --all --replicas=0`. Jenkins 는 `WEB_DEPLOY` 를 지우면 compose 경로로 돌아간다.

## 주의

- 파괴적 마이그레이션(컬럼 삭제·타입 변경)을 내는 release 는 두 버전이 같은 스키마를 못 쓴다. 그때만 `backend.yaml` 의 `maxSurge` 를 0 으로.
- 롤링 중 두 백엔드가 잠깐 `sim.result` 를 나눠 받는다. 옛 파드에 붙은 SSE 는 종료 시 닫히고 브라우저가 새 파드로 다시 붙어 snapshot 을 받는다.
- 백엔드 상한 2Gi 는 `docker stats a106-backend` 실사용을 보고 조정한다.
