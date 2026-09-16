# t3_amr 러너 컨테이너 — Isaac Sim 파이프라인을 k3s 아래로

목표: 견적 화면의 검증 버튼 → host-orch(EC2) → **이 컨테이너**(GPU 박스) → Isaac 녹화 → MinIO → 화면에 영상.
컨테이너 하나가 Isaac Sim(pip) + t3_amr + 계획기 원본(3_FMS/sim_engine) + ffmpeg + 상주 엣지(MQTT/Sparkplug)를 다 품는다.
엣지가 Start 를 받으면 같은 컨테이너 안에서 `run_record.sh` 를 띄우고, 끝나면 mp4 를 올려 `Runner/VideoUrl` 로 알린다.

왜 한 컨테이너인가: 계획기는 서비스가 아니라 **Isaac 파이썬 안의 import** 다(`runners/live_pibt.py` → `isaac_drive` → `pibt_core`, lifelong 재계획 + ADG 구동).
엣지는 그 프로세스를 띄우고 SIGINT 로 조립시키고 트리를 거두므로 같은 PID 공간이 편하다. 나중에 붙을 ROS 2 에이전트(1_Robot/amr_agent)는 별도 컨테이너로 같은 Pod 에 둔다.

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
※ 툴킷 설치의 마지막 `systemctl restart docker` 는 돌고 있는 빌드를 끊는다 — 빌드 중이면 끝난 뒤에.

루트 없이 되는 것 — Docker 29 는 `buildx`·`compose` 를 플러그인으로 따로 둔다(이 박스엔 없었다). 사용자 홈에 넣으면 된다:
```bash
mkdir -p ~/.docker/cli-plugins
curl -fsSL -o ~/.docker/cli-plugins/docker-buildx  https://github.com/docker/buildx/releases/download/v0.37.1/buildx-v0.37.1.linux-amd64
curl -fsSL -o ~/.docker/cli-plugins/docker-compose https://github.com/docker/compose/releases/download/v5.5.1/docker-compose-linux-x86_64
chmod +x ~/.docker/cli-plugins/docker-*
docker buildx version && docker compose version
```
usermod 뒤 재로그인이 어려우면 `sg docker -c '<docker 명령>'` 으로 그 자리에서 쓸 수 있다.

## 1. 이미지 빌드·단독 검증 (k3s 전)

```bash
cd <repo>
docker build -f 2_Simulation/t3_amr/deploy/Dockerfile \
    --build-context sim_engine=3_FMS/sim_engine -t t3amr-runner:dev 2_Simulation/t3_amr   # Isaac 휠 26 GB, 첫 빌드 ≈ 25 분(11 MB/s)
docker run --rm --gpus all t3amr-runner:dev check                                          # GPU · Isaac import · ffmpeg · 에셋 · 계획기 원본
docker compose -f 2_Simulation/t3_amr/deploy/compose.yml run --rm t3amr-runner record 3    # 3대 녹화 1회 → deploy/data/out/*.mp4
```
`--build-context sim_engine=…` 은 빠뜨리면 안 된다 — 계획기 원본(`3_FMS/sim_engine`)이 빌드 컨텍스트 밖이라 이름 있는 컨텍스트로 넣는다
(compose 는 `additional_contexts` 로 같은 일을 한다). 없으면 계획 단계가 옛 벤더 사본으로 후퇴해 `MOVE_TICKS` ImportError 로 죽는다.

이미지에 굽는 것과 재빌드 비용:

| 레이어 | 내용 | 코드만 바뀐 재빌드 |
|---|---|---|
| Isaac 휠 · pip 부속(numba 포함) | 22 GB, 첫 빌드 23 분 | 캐시 |
| 계획기 원본 `pibt_core.py` · `pibt/` | 3_FMS 가 바뀌면 다시 | 캐시 |
| iw.hub(공개 S3) · 적재 선반(`build_amr_shelf.py`, `--build-arg SHELF_TOP_REAR=`) | 에셋 둘, 1 분 | 캐시 |
| `COPY .` 이후 | 코드 · 심링크 · 소유권 | **1 분 안팎** |

pip 핀은 Isaac 이 못박은 것을 따른다 — llvmlite 0.46(→ numba 0.64, 3_FMS 의 0.67 이 아니다) · psutil 5.9.8(핀 없음). 예외 하나: coverage 를 7.4.4 → 7.16.1 로 올린다 —
numba ≥0.63 이 `coverage.types.Tracer`(7.5+)를 요구해 import 가 죽기 때문이고, Kit 테스트 도구용 패키지라 런타임엔 무관하다. `pip check` 가 그 하나를 보고하는 건 의도한 것.

개발 중 코드 수정은 재빌드 없이도 된다 — compose 에서 작업 트리를 `/app/2_Simulation/t3_amr` 에 bind mount 하면 그대로 보인다(`out/`·`stage/`·`logs/` 심링크가 가려지니 그 셋은 따로 마운트).
첫 실행은 셰이더 캐시(볼륨 `ov-cache`)를 만드느라 몇 분 더 걸린다.
컨테이너는 uid 1000 `runner` 로 돈다 — bind mount 하는 `deploy/data` 는 호스트 계정(uid 1000) 소유면 된다. 다른 uid 면 소유권을 1000 으로 맞춘다.

첫 빌드·실행 기록(2026-09-16, 이 박스): 빌드 25 분·26.4 GB, `check` 통과(RTX 5080 · 595.91 · isaacsim 6.0.1.0). 첫 `record 2` 에서 드러난 것 셋과 그 수정(-220):
1. 계획 단계 — `3_FMS/sim_engine` 이 이미지에 없어 벤더 사본으로 후퇴, `MOVE_TICKS` ImportError → `--build-context sim_engine=…` + 두 단 배치.
2. Kit 기동 — `vkCreateInstance failed … Vulkan 1.1 is not supported` 로 GPU 장치 0 개 → 렌더러 죽음. 툴킷이 드라이버 라이브러리는 넣어 주지만 Vulkan ICD JSON 은 안 넣는다 → Dockerfile 이 `/etc/vulkan/icd.d/nvidia_icd.json`·`/usr/share/glvnd/egl_vendor.d/10_nvidia.json` 을 쓴다(NGC 이미지와 같은 처방). 안에서 `vulkaninfo --summary` 로 확인.
3. 비루트 — Kit 이 `site-packages/isaacsim/kit/data/documents/…` 를 못 만들었다(루트 소유 venv). 그 폴더만 runner 소유로 미리 만든다. venv 전체 chown 은 레이어 복사 26 GB 라 안 한다.

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

단위 테스트(브로커·Isaac 없이): `cd 2_Simulation && python3 -m pytest` (58건). 브로커 붙여 손으로 돌리기:
```bash
cd 2_Simulation/t3_amr && python3 -m edge --env-file ../../3_FMS/infra/emqx/.env -v     # MINIO_* 없으면 VideoUrl = file://…
```

| 요청 필드 | t3_amr 환경변수 | 비고 |
|---|---|---|
| `n_robots` | `PIBT_N` | 계획 폴더 `plan/traj_pibt_h/fleet_NN` 이 없으면 `REPLAN=1` 로 run_record.sh 가 먼저 계획한다(로컬, Isaac 불필요) |
| `scenario.seed` | `PIBT_SEED` | |
| `timeout_s − 300` (= window_s) | `PIBT_HORIZON`(틱 = (창+60 s) ÷ 0.333 s, 0.333 = 1.2 m ÷ (0.9 m/s × 4틱) — 211 틱 모델, `recorder.DEFAULT_TICK_S`) | 창 끝은 host-orch Stop 이 자른다. 틱 길이는 `T3AMR_TICK_S` |
| `scenario.orders` | — | **못 받는다.** t3_amr 은 lifelong 자체 발주. `PIBT_ORDER_GAP` 으로 부하만 맞춘다(후속) |

## 4. 아직 안 정한 것
- 검증 런에서 fms-core 를 뺄지(권장, 영상이 목표) — 빼면 host-orch 를 `--fms-node` 없이 띄운다.
- 창 길이(300~600 s)와 RTF. 녹화는 실시간보다 느릴 수 있어 벽시계 = 창 ÷ RTF.
- 이미지 레지스트리(GitLab registry 또는 GHCR). 그 전까지는 `ctr import`.
