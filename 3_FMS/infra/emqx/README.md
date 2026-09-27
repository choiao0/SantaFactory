# 3_FMS/infra/emqx — MQTT 백본 브로커 (EMQX 6.3.0)

VDA 5050(AMR 제어) · Sparkplug B(런 제어·텔레메트리) · biz/v1 JSON(주문·이벤트) 세 레인이 한 브로커를 쓴다.
규칙의 원본은 [`../../contracts/MQTT_CONTRACT.md`](../../contracts/MQTT_CONTRACT.md), 이 디렉토리는 그 계약을 실행하는 파일이다.
로컬 compose 와 EC2 k3s(`4_Web/k8s/emqx/`, 예정)가 **같은 `emqx.conf`·`acl.conf`·이미지 digest** 를 쓴다.

| 파일 | 역할 |
|---|---|
| `compose.yml` | `emqx/emqx:6.3.0@sha256:3b6d9c0c…` 단일 노드. 1883(MQTT) · 127.0.0.1:18083(대시보드, 로컬 전용) |
| `emqx.conf` | HOCON. 내장 DB 계정(`etc/users.csv` 부트스트랩) · 파일 ACL(`no_match = deny`, 위반 시 `disconnect`) · QoS 상한 1 · retainer |
| `acl.conf` | 계정별 허용 토픽. retained 는 `connection`·`factsheet`·`STATE` 에만 (`{publish, [{retain, false}]}`) |
| `bootstrap_users.sh` | `.env` → `users.csv` (amr01..amrNN, fms-core, sim-runner-gpu01..0N, host-orch, sim-wms) |
| `.env.example` | 쿠키 · 대시보드 비밀번호 · 계정 비밀번호 견본. `.env`·`users.csv` 는 커밋되지 않는다 |
| `../../contracts/tests/test_acl_matrix.py` | ACL 행렬 50항목을 살아 있는 브로커에 대고 고정 |

## 실행

```bash
cd 3_FMS/infra/emqx
cp .env.example .env            # 값을 채운다 (비밀번호에 쉼표 금지)
./bootstrap_users.sh            # users.csv 생성 — 브로커가 최초 기동 때 한 번만 읽는다
docker compose up -d            # sudo 가 필요한 호스트면 sudo docker compose up -d
docker compose logs emqx | grep -E 'Listener|ERROR'      # tcp:default 1883 started, ERROR 없음
cd ../.. && python3 -m pytest contracts/tests/test_acl_matrix.py -q      # 50 passed (약 2.5 분)
```

계정을 바꾸려면 `users.csv` 를 다시 만들고 `docker compose down -v && docker compose up -d` (볼륨의 내장 DB 초기화),
또는 대시보드(http://127.0.0.1:18083, admin / `EMQX_DASHBOARD_PASSWORD`) · REST(API 키 필요) 로 고친다.

### 떠 있는 브로커에 계정 하나만 추가 (재기동 없이, -244)

`users.csv` 는 **최초 기동 때만** 읽는다 — 노드를 하나 더 늘려 `sim-runner-gpu04` 같은 계정을 나중에 추가하려는데
`down -v` 로 볼륨(내장 DB)을 지우고 싶지 않다면(다른 노드 계정까지 같이 날아간다) 다음 중 하나로 간다.
`emqx ctl` 에는 내장 DB(built_in_database) 인증에 계정을 추가하는 서브커맨드가 없다(5.x/6.x 공통) — 대시보드 또는
REST API 만 된다.

- **대시보드**: http://127.0.0.1:18083 → Access Control → Authentication → `password_based:built_in_database` →
  Users → Add.
- **REST API** (API 키는 대시보드 → System → API Keys 에서 발급):
  ```bash
  curl -u "$API_KEY:$API_SECRET" -H 'content-type: application/json' \
    -X POST 'http://127.0.0.1:18083/api/v5/authentication/password_based:built_in_database/users' \
    -d '{"user_id": "sim-runner-gpu04", "password": "<MQTT_PW_SIM_RUNNER 와 같은 값>"}'
  ```
  `acl.conf` 는 파일이라 재기동 없이는 안 바뀌지만, `sim-runner-gpu\d+` 정규식이 이미 새 노드 이름도 매칭하므로
  ACL 쪽은 손댈 것이 없다 — 계정만 있으면 바로 붙는다.

두 방법 다 대시보드 인증서(cookie)나 API 키가 필요해 `.env` 만으로는 못 하고, 위 REST 예시는 로컬 포트포워드
기준이다 — EC2 등 원격 브로커는 대시보드 포트(18083)가 공인망에 열려 있지 않으므로 tailnet·SSH 터널로 붙는다.

도커 없이(예: GPU 서버에서 sudo 없이 확인할 때): 같은 버전의 tar.gz 를 받아 같은 etc 파일로 띄운다.

```bash
curl -LO https://www.emqx.com/en/downloads/enterprise/6.3.0/emqx-enterprise-6.3.0-ubuntu22.04-amd64.tar.gz   # 6.x 는 단일 배포판(Community License 포함)
mkdir emqx-6.3.0 && tar xzf emqx-enterprise-6.3.0-ubuntu22.04-amd64.tar.gz -C emqx-6.3.0
cp emqx.conf acl.conf users.csv emqx-6.3.0/etc/
cd emqx-6.3.0 && EMQX_NODE__COOKIE=… EMQX_DASHBOARD__DEFAULT_PASSWORD=… ./bin/emqx foreground
```

## 수동 확인 (mosquitto-clients 또는 mqttx)

```bash
mosquitto_sub -h localhost -t '#'                                             # 1) 익명 → Connection refused: not authorised
mosquitto_sub -h localhost -u host-orch -P "$MQTT_PW_HOST_ORCH" -v -t 'uagv/v2/+/+/#' -t 'spBv1.0/#' -t 'biz/v1/#'   # 2) 관측 창
mosquitto_pub -h localhost -u amr01 -P "$MQTT_PW_AMR" -q 1 -r -t uagv/v2/idealworks/amr01/connection \
  -m '{"headerId":1,"timestamp":"2026-09-08T00:00:00Z","version":"2.0.0","manufacturer":"idealworks","serialNumber":"amr01","connectionState":"ONLINE"}'   # 3) retained
mosquitto_pub -h localhost -u amr01 -P "$MQTT_PW_AMR" -t uagv/v2/idealworks/amr02/state -m '{}'           # 4) 남의 시리얼 → 연결 끊김
mosquitto_pub -h localhost -u amr01 -P "$MQTT_PW_AMR" -r -t uagv/v2/idealworks/amr01/state -m '{}'        # 5) retained state → 연결 끊김
mosquitto_pub -h localhost -u amr01 -P "$MQTT_PW_AMR" -q 1 -r -t uagv/v2/idealworks/amr01/connection -m ''   # retained 삭제
```

## 검증 기록 (2026-09-08, EMQX 6.3.0 tar.gz, 이 디렉토리의 emqx.conf·acl.conf 그대로)

| 항목 | 결과 |
|---|---|
| 기동 | tcp:default 1883 started · ssl/ws/wss disabled · dashboard 18083 · 로그 ERROR 0 |
| 계정 부트스트랩 | users.csv 7 계정 전부 로그인, 익명·오답 거부 |
| ACL 행렬 | 44 칸 전부 기대대로 (허용 = PUBACK/SUBACK + 관측자 수신, 거부 = 즉시 연결 끊김 + 관측자 무수신) |
| retained | connection retained → 늦은 구독자 즉시 수신(retain 플래그). state·order·NCMD·biz 의 retained 발행은 거부 |
| LWT | 소켓만 닫으면 CONNECTIONBROKEN 유언이 관측자에게 도착 |
| QoS | QoS 2 발행 거부 (`mqtt.max_qos_allowed = 1`) |
| 라이선스 | Community License 포함: 단일 노드 내부 사용 무료, max_sessions 10,000,000, 2029-03-01 까지. 클러스터(2 노드+)는 별도 |

## 배포에서 걸린 것 (EC2 2026-09-08)

- `users.csv` 가 root 600 이면 컨테이너의 emqx 사용자(uid 1000)가 못 읽어 계정 0개로 뜬다 — 익명은 물론 모든 계정이 "Not authorized". 스크립트가 644 로 만들고, `sudo` 로 돌렸어도 644 를 유지한다.
- `bootstrap_users.sh` 를 `docker compose up` 뒤에 돌리면 계정이 안 들어간다(최초 기동 때만 읽음). `down -v` 후 다시 `up`.
- 수동 복사 시 실행 권한이 빠지면 `sudo bash bootstrap_users.sh` 로 돌린다. 숨김 파일 `.env.example`·`.gitignore` 도 같이 옮긴다.
- EC2 위치 `~/emqx/` (k3s 이전 전 임시). GPU 서버에서의 주소는 tailnet `100.100.149.68:1883` — 공인 IP 로는 보안 그룹(443·80)이 막는다.

## 6.3 에서 걸린 것

- `node.data_dir` 가 필수다 — 이미지 기본 emqx.conf 를 마운트로 덮으면 직접 적어야 한다(`"data"`).
- ACL 의 qos·retain 조건은 토픽이 아니라 **동작**에 붙는다: `{allow, who, {publish, [{retain, false}]}, [topics]}`. 토픽 튜플 `{"t", [{retain,false}]}` 는 문법 오류.
- 6.3 부터 `security_profile = hardened` 가 기본이라 기본 acl.conf 의 `{allow, {security_profile, legacy}}` 는 적용되지 않는다. 우리는 어차피 `{deny, all}` + `no_match = deny`.
- `deny_action = disconnect` 는 구독 거부에도 적용된다 — 잘못 구독한 클라이언트는 SUBACK 대신 끊긴다. 테스트가 이 동작을 고정한다.
