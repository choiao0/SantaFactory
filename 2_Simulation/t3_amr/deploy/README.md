# t3_amr 러너 컨테이너 — Isaac Sim 파이프라인을 k3s 아래로

목표: 견적 화면의 검증 버튼 → host-orch(EC2) → **이 컨테이너**(GPU 박스) → Isaac 녹화 → MinIO → 화면에 영상.
컨테이너 하나가 Isaac Sim(pip) + t3_amr + ffmpeg + 상주 엣지(MQTT/Sparkplug)를 다 품는다.
엣지가 Start 를 받으면 같은 컨테이너 안에서 `run_record.sh` 를 띄우고, 끝나면 mp4 를 올려 `Runner/VideoUrl` 로 알린다.

## 0. GPU 박스 전제 (루트 필요 — 한 번만)

```bash
# docker 소켓 권한 (재로그인 필요)
sudo usermod -aG docker "$USER"
# NVIDIA 컨테이너 툴킷 — docker 와 (나중에) k3s containerd 양쪽에 런타임 등록
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker
```
확인: `docker run --rm --gpus all nvidia/cuda:12.6.3-base-ubuntu22.04 nvidia-smi`

## 1. 이미지 빌드·단독 검증 (k3s 전)

```bash
cd <repo>
docker build -f 2_Simulation/t3_amr/deploy/Dockerfile -t t3amr-runner:dev 2_Simulation/t3_amr   # Isaac 휠 십수 GB, 첫 빌드 수십 분
docker run --rm --gpus all t3amr-runner:dev check                                              # import · GPU · ffmpeg
docker compose -f 2_Simulation/t3_amr/deploy/compose.yml run --rm t3amr-runner record 3        # 3대 녹화 1회 → deploy/data/out/*.mp4
```
첫 실행은 셰이더 캐시(볼륨 `ov-cache`)를 만드느라 몇 분 더 걸린다.
컨테이너는 uid 1000 `runner` 로 돈다 — bind mount 하는 `deploy/data` 는 호스트 계정(uid 1000) 소유면 된다. 다른 uid 면 소유권을 1000 으로 맞춘다.

## 2. k3s

- EC2 의 k3s 서버에 이 박스를 agent 로 붙인다 (tailnet 주소로). 노드 라벨 `santa.io/gpu=true`.
- 노드에 툴킷이 있으면 k3s 가 `nvidia` 런타임을 자동 등록한다 → `k8s/runtimeclass.yaml`. GPU 리소스는 NVIDIA device plugin DaemonSet.
- 레지스트리가 아직 없으니 이미지는 로컬 빌드 후 k3s 의 containerd 로 넣는다:
  `docker save t3amr-runner:dev | sudo k3s ctr images import -`
- `k8s/secret.example.yaml` 을 채워 apply → `k8s/deployment.yaml` apply.

## 3. 엣지(상주 러너) — `edge/` (-215)

`python -m edge` 가 Sparkplug B 노드 `sim-runner-gpu01` 로 상주한다(`entrypoint.sh edge`). 219 로 지운 `sim_runner`(ac10c76)의
코덱(`spb.py`)·세션(`EdgeSession`)·텔레메트리·MQTT 연결부를 되살렸고, 에이전트 런처 대신 `recorder.py` 가 `run_record.sh` 하나를 띄운다.

| 파일 | 역할 |
|---|---|
| `edge/edge.py` | paho 연결, NDEATH 유언·NBIRTH, NCMD/STATE 구독, 틱 루프, `alive` 파일(livenessProbe) |
| `edge/runner.py` | 상태기계 IDLE → STARTING(첫 프레임 대기) → RUNNING → STOPPING(SIGINT → mp4 조립 → 업로드) → IDLE/ERROR. `Runner/VideoUrl` 메트릭 |
| `edge/recorder.py` | Start → `RUN_TAG`·`PIBT_N`·`PIBT_SEED`·`PIBT_HORIZON`·`REPLAN` 환경으로 `run_record.sh` 기동, 촬영 감지(`캡처 ON`·프레임), 정지 사다리 |
| `edge/upload.py` | mp4 → MinIO(`MINIO_*`) → `PUBLIC_MEDIA_BASE/<bucket>/<run_id>/<파일>` |
| `edge/spec.py` | Start JSON 파싱. `window_s` 는 `timeout_s − 300` 에서 되돌린다 |

host-orch 쪽(-215 같이): `Runner/VideoUrl` → `sim.verify.result.artifacts.video`. **EC2 host-orch 는 `--fms-node` 없이 띄운다** — t3_amr 이 자체 계획으로 돌아 fms-core 가 RUNNING 이 될 일이 없다.
**`--stop-timeout-s` 도 올려야 한다(기본 60 → 300 권장)** — Stop 뒤 Kit 정리(≤25 s) + ffmpeg 조립(프레임 수천 장이면 1 분 넘게) + MinIO 업로드가 STOPPING 안에서 일어난다. 업로드는 워커 스레드라 그동안 하트비트·NCMD 는 계속 처리된다.

단위 테스트(브로커·Isaac 없이): `cd 2_Simulation && python3 -m pytest` (40건). 브로커 붙여 손으로 돌리기:
```bash
cd 2_Simulation/t3_amr && python3 -m edge --env-file ../../3_FMS/infra/emqx/.env -v     # MINIO_* 없으면 VideoUrl = file://…
```

| 요청 필드 | t3_amr 환경변수 | 비고 |
|---|---|---|
| `n_robots` | `PIBT_N` | 계획 폴더 `plan/traj_pibt_h/fleet_NN` 이 없으면 `REPLAN=1` 로 run_record.sh 가 먼저 계획한다(로컬, Isaac 불필요) |
| `scenario.seed` | `PIBT_SEED` | |
| `timeout_s − 300` (= window_s) | `PIBT_HORIZON`(틱 = (창+60 s) ÷ 1.33 s) | 창 끝은 host-orch Stop 이 자른다. 틱 길이는 `T3AMR_TICK_S` |
| `scenario.orders` | — | **못 받는다.** t3_amr 은 lifelong 자체 발주. `PIBT_ORDER_GAP` 으로 부하만 맞춘다(후속) |

## 4. 아직 안 정한 것
- 검증 런에서 fms-core 를 뺄지(권장, 영상이 목표) — 빼면 host-orch 를 `--fms-node` 없이 띄운다.
- 창 길이(300~600 s)와 RTF. 녹화는 실시간보다 느릴 수 있어 벽시계 = 창 ÷ RTF.
- 이미지 레지스트리(GitLab registry 또는 GHCR). 그 전까지는 `ctr import`.
