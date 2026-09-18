# GCP DES 워커 (S15P21A106-246 → 249)

견적 DES 워커(`infra/worker/estimate_worker.py`)를 EC2 에서 GCP Spot VM 3대로 옮겼다(2026-09-18, 246). 이유: 단일 스레드 속도.
EC2 Xeon 8259CL 2.5 GHz 에서 런당 70~77 s 이던 것이 GCP C4(Xeon 8581C, SMT 끔) 에서 28~37 s — 견적(6런) 벽시계 6~7분 → 약 37 s.

249 에서 **워커를 올리는 주체**가 바뀌었다: VM 마다 compose 4개 → EC2 k3s 의 Deployment 12개(`infra/k8s/`). VM 은 k3s 에이전트 노드일 뿐이고,
배포는 Jenkins FMS 단계(`FMS_DEPLOY=k3s`)가 한다. **tailnet 은 쓰지 않는다** — 246 의 브로커 경로(공인 AMQPS 5671)와 같은 원칙으로,
노드 합류는 공인 6443, 이미지는 nginx 443 `/v2/` 뒤 레지스트리다. GCP→EC2 한 방향만 있으면 되므로 GCP VM 에 외부 IP 가 없어도 된다.

## 구성
| 항목 | 값 |
|---|---|
| 프로젝트 / 리전 | `santafactory` / asia-northeast3 (서울), 존 a·b·c 에 1대씩 |
| 머신 | `c4-highcpu-8`, 코어당 vCPU 1(SMT 끔) → 물리 4코어 · 15.6 GB · Spot(종료 동작 "중지") · 외부 IP 없음 |
| 관리형 인스턴스 그룹 | `des-workers` 크기 3, 템플릿 `des-worker-tpl-v2`(이미지 `des-worker-v1` + 시작 스크립트 `start.sh` + 메타데이터 `k3s-token`, 선택 `k3s-url`·`k3s-version`) |
| 이그레스 | Cloud NAT 고정 IP 34.47.111.62 — EC2 ufw 의 5671(브로커)·6443(k3s) 와 nginx `/v2/` 의 허용 대상 |
| 워커 | Deployment `sim-worker` 12개, 노드당 4개(코어 수), CPU 1 · **메모리 3Gi** (`infra/k8s/sim-worker-deployment.yaml`) |
| 브로커 접속 | `amqps://sim-worker:…@j15a106.p.ssafy.io:5671/` — Secret `sim-worker-broker`, EC2 nginx stream TLS 종단(`infra/nginx/`) |
| 이미지 | `j15a106.p.ssafy.io/fms-estimate-worker:<빌드번호>` — nginx 443 `/v2/` → EC2 registry 127.0.0.1:5000 (`infra/nginx/registry-v2.conf`) |
| 관리 접속 | 콘솔 SSH(IAP 35.235.240.0/20). VM 에 들어갈 일이 거의 없다 — 워커 로그는 EC2 에서 `kubectl -n fms logs` |

## 파일
| 파일 | 역할 |
|---|---|
| `start.sh` | 템플릿 시작 스크립트. 메타데이터 `k3s-token` 으로 k3s 에이전트 합류(`role=sim-worker`), 옛 compose 워커가 남아 있으면 내림 |
| `../compose.estimate.gcp.yml` | 246 세대 compose 판. k3s 이전 뒤에는 비상용(VM 에서 수동 `up -d --build`) |
| `deploy_gcp.sh` | 246 세대 배포 스크립트(PC → VM rsync, tailnet SSH). 249 부터 쓰지 않는다 — 코드 배포는 Jenkins |

## 템플릿 v2 만들기 (콘솔, 사용자 문서 PJT-2 `docs/GCP_DES워커_콘솔_가이드.md` §15)
1. EC2 에서 에이전트 토큰: `sudo cat /var/lib/rancher/k3s/server/agent-token` (서버 토큰 `server/token` 이 아니다).
2. 인스턴스 템플릿 `des-worker-tpl` 복사 → 이름 `des-worker-tpl-v2`. 메타데이터에 `k3s-token`=<1 의 값> 추가, `tailscale-authkey`·`worker-replicas` 삭제.
   시작 스크립트 = 이 폴더의 `start.sh` 전문. 액세스 범위는 기본 그대로(레지스트리·API 를 안 쓴다).
3. 그룹 `des-workers` → 템플릿을 v2 로 교체 → "인스턴스 업데이트/재생성". 3대가 차례로 새로 뜨며 합류한다.
4. 확인은 아래 운용 절. 옛 tailnet 노드(des-workers-*, des-test)는 Tailscale 관리 화면에서 지운다.

## 메모리 (2026-09-18 실측, 주문 4,000건)
| n(로봇) | 8 | 9 | 10 | 11 | 12 | 13 |
|---|---|---|---|---|---|---|
| 워커 최고치 | 1,664 MB | 1,783 | 1,843 | 1,914 | 2,048(한도) | 2,048(한도) |

VM 에 스왑이 없어 한도에 닿으면 회수(reclaim)가 돌고 그래도 안 되면 OOM kill 이다. n=12·13 이 2 GiB 한도에 부딪혀(`memory.events max` 48·181회) 3 GiB 로 올렸다.
+70 MB/로봇 이라 n≈28·주문 6,000 은 3 GiB 도 넘을 수 있다 — 그때는 Deployment 의 requests/limits 를 4Gi 로(노드당 3개) 바꾸거나 리플레이 이력(21,601 s × 로봇)의 메모리를 줄여야 한다.
EC2 워커도 2 GiB 한도였다(`compose.estimate.yml`).

## 운용
- 워커 수는 Deployment `replicas` 하나. Spot 회수로 노드가 빠지면 그 노드 몫 4개는 Pending 으로 남았다가 새 VM 이 합류하면 뜬다
  (CPU 요청 900m 때문에 남은 노드로 몰리지 않는다). 사라진 노드 객체는 `kubectl delete node <이름>`.
- 안 쓸 때 그룹 크기 0. 처리 중이던 런은 워커가 ack 전에 죽으면 RabbitMQ 가 다른 워커에 재전달한다.
- Jenkins 전역 환경변수: `WORKER_REPLICAS=0`(EC2 compose 워커를 띄우지 않음) + `FMS_DEPLOY=k3s`(빌드 → 레지스트리 push → `kubectl set image`).
- 확인 (EC2):
  ```
  kubectl get nodes -L role                                   # GCP 3대 Ready, role=sim-worker
  kubectl -n fms get pods -o wide                             # 12개 Running, 노드마다 4개
  docker exec a106-rabbitmq rabbitmqctl list_queues name consumers | grep sim.request   # 12
  ```
- 246 세대(tailnet, compose)로 되돌려야 하면: 템플릿을 v1 로, EC2 ufw 5671 은 그대로. `deploy_gcp.sh` 는 tailnet SSH 가 있어야 돈다.
