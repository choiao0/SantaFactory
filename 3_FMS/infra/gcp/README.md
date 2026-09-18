# GCP DES 워커 (S15P21A106-246)

견적 DES 워커(`infra/worker/estimate_worker.py`)를 EC2 에서 GCP Spot VM 3대로 옮겼다(2026-09-18). 이유: 단일 스레드 속도.
EC2 Xeon 8259CL 2.5 GHz 에서 런당 70~77 s 이던 것이 GCP C4(Xeon 8581C, SMT 끔) 에서 28~37 s — 견적(6런) 벽시계 6~7분 → 약 37 s.

## 구성
| 항목 | 값 |
|---|---|
| 프로젝트 / 리전 | `santafactory` / asia-northeast3 (서울), 존 a·b·c 에 1대씩 |
| 머신 | `c4-highcpu-8`, 코어당 vCPU 1(SMT 끔) → 물리 4코어 · 15.6 GB · Spot · 외부 IP 없음 |
| 관리형 인스턴스 그룹 | `des-workers` 크기 3, 템플릿 `des-worker-tpl`(이미지 `des-worker-v1` + 시작 스크립트 `start.sh` + 메타데이터 `tailscale-authkey`·`worker-replicas`) |
| 이그레스 | Cloud NAT 고정 IP 34.47.111.62 — EC2 ufw 의 5671 허용 대상 |
| 워커 | VM 당 4개(코어 수), 워커당 cpus 1.0 · **메모리 3G** (`compose.estimate.gcp.yml`) |
| 브로커 접속 | `amqps://sim-worker:…@j15a106.p.ssafy.io:5671/` — EC2 nginx stream TLS 종단(`infra/nginx/`), 전용 계정 |
| 배치 | VM `~/fms/3_FMS/{sim_engine,map,contracts,infra/{out,worker,requirements.txt,estimate.Dockerfile,compose.estimate.gcp.yml,.env.estimate}}` |
| 관리 접속 | tailscale(SSH 전용). 브로커 트래픽은 tailnet 을 쓰지 않는다 |

## 파일
| 파일 | 역할 |
|---|---|
| `../compose.estimate.gcp.yml` | EC2 compose 의 GCP 판 — external 네트워크 없음, AMQPS URL, replicas·메모리 |
| `start.sh` | 템플릿 시작 스크립트. 인증 키로 tailnet 가입(상태 파일 삭제 후 — 이미지에 든 신원을 복제 VM 이 나눠 쓰는 문제) + compose 기동 |
| `deploy_gcp.sh` | 이 PC → VM 들로 3_FMS 동기화 + 재빌드·재기동. 새 이미지를 구울 때는 한 대에만 → 중지 → 이미지 → 템플릿 교체 |

## 메모리 (2026-09-18 실측, 주문 4,000건)
| n(로봇) | 8 | 9 | 10 | 11 | 12 | 13 |
|---|---|---|---|---|---|---|
| 워커 최고치 | 1,664 MB | 1,783 | 1,843 | 1,914 | 2,048(한도) | 2,048(한도) |

VM 에 스왑이 없어 한도에 닿으면 회수(reclaim)가 돌고 그래도 안 되면 OOM kill 이다. n=12·13 이 2 GiB 한도에 부딪혀(`memory.events max` 48·181회) 3 GiB 로 올렸다.
+70 MB/로봇 이라 n≈28·주문 6,000 은 3 GiB 도 넘을 수 있다 — 그때는 워커 3×4G 로 바꾸거나 리플레이 이력(21,601 s × 로봇)의 메모리를 줄여야 한다.
EC2 워커도 2 GiB 한도였다(`compose.estimate.yml`).

## 운용
- EC2 워커는 정지해 둔다(`docker stop fms-estimate-estimate-worker-{1,2}`). Jenkins 가 release 마다 2개로 되돌리므로 Jenkins 환경에 `WORKER_REPLICAS=0` 이 필요하다.
- 안 쓸 때 그룹 크기 0. Spot 회수는 그룹이 재생성하고, 처리 중 메시지는 RabbitMQ 가 재전달한다.
- 소비자 확인: EC2 `rabbitmqctl list_queues name consumers | grep sim.request` → 12.
- 콘솔 단계별 가이드(사용자 문서): PJT-2 `docs/GCP_DES워커_콘솔_가이드.md`.
