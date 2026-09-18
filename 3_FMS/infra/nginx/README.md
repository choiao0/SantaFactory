# EC2 nginx — AMQPS 종단 (S15P21A106-246)

RabbitMQ 5672 는 127.0.0.1 에만 열려 있다. 밖(GCP DES 워커)에서 붙는 정석은 **TLS 종단 + 출발지 제한 + 전용 계정**이다.
nginx `stream` 으로 5671 에서 TLS 를 풀어 루프백 5672 로 넘긴다. RabbitMQ 설정은 손대지 않는다.

## EC2 에 넣는 순서 (2026-09-18 적용됨)
```
sudo apt-get install -y libnginx-mod-stream          # Ubuntu nginx 는 stream 이 동적 모듈 — 없으면 "unknown directive stream"
sudo mkdir -p /etc/nginx/stream.d && sudo cp amqps-stream.conf /etc/nginx/stream.d/amqps.conf
printf '\nstream {\n    include /etc/nginx/stream.d/*.conf;\n}\n' | sudo tee -a /etc/nginx/nginx.conf   # http 블록 밖, 파일 끝
sudo nginx -t && sudo systemctl reload nginx
sudo ufw allow from <GCP NAT 고정 IP> to any port 5671 proto tcp comment "AMQPS GCP DES workers"
```
- nginx 는 호스트 프로세스라 ufw 가 그대로 먹는다(docker publish 포트와 다르다). 보안그룹은 전 포트 개방 상태.
- 브로커 쪽에서는 연결이 `127.0.0.1`(정확히는 docker 게이트웨이 172.18.0.1) 에서 온 평문으로 보인다 — TLS 는 nginx 에서 끝난다.
- 전용 계정: `rabbitmqctl add_user sim-worker …` · `set_permissions -p / sim-worker "^$" "^amq\.default$" "^sim\.request$"`
  (큐 선언 없음 · 기본 교환기로 발행 · sim.request 소비). 비밀은 EC2 `~/rabbitmq-keys/sim-worker.env`(600) 와 각 워커 VM `.env.estimate` 에만.
- 워커 쪽 URL: `amqps://sim-worker:…@j15a106.p.ssafy.io:5671/`. pika 가 amqps 를 그대로 받고 공인 CA 라 인증서 파일이 필요 없다.
- 예전 임시 경로였던 tailnet 리스너(`tailscale serve --tcp 5672`)는 09-18 닫았다.

## 확인
```
sudo ss -ltn | grep :5671
docker exec a106-rabbitmq rabbitmqctl list_connections user peer_host | sort | uniq -c   # sim-worker 12 = GCP 3대 × 4
echo | openssl s_client -connect j15a106.p.ssafy.io:5671 -servername j15a106.p.ssafy.io | grep "Verify return code"   # 허용 IP 에서 0 (ok)
```
