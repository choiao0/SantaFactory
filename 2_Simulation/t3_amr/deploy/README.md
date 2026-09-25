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
    --build-context sim_engine=3_FMS/sim_engine --build-context fms_map=3_FMS/map \
    -t t3amr-runner:dev 2_Simulation/t3_amr                                               # Isaac 휠 26 GB, 첫 빌드 ≈ 25 분(11 MB/s)
docker run --rm --gpus all t3amr-runner:dev check                                          # GPU · Isaac import · ffmpeg · 에셋 · 계획기 원본
docker compose -f 2_Simulation/t3_amr/deploy/compose.yml run --rm t3amr-runner record 3    # 3대 녹화 1회 → deploy/data/out/*.mp4
```
`--build-context sim_engine=…` 은 빠뜨리면 안 된다 — 계획기 원본(`3_FMS/sim_engine`)이 빌드 컨텍스트 밖이라 이름 있는 컨텍스트로 넣는다
(compose 는 `additional_contexts` 로 같은 일을 한다). 없으면 계획 단계가 옛 벤더 사본으로 후퇴해 `MOVE_TICKS` ImportError 로 죽는다.
`--build-context fms_map=…` 도 같다(-275) — 궤적 재생(DES 피크 구간, FMS 격자)이 `3_FMS/map` 의 맵 데이터를 읽는다.
손 배포로 GPU 박스 트리를 맞출 때도 `3_FMS/map` 의 데이터 파일 넷(`occupancy_grid.npy`·`stations.json`·`charge_zone.json`·`rack_buffers.json`)을 함께 옮긴다.

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
**GPU capability 에 `ngx` 가 있어야 한다**(-237). compose 는 `deploy.resources.reservations.devices.capabilities` 목록이 곧 마운트 범위라
`ngx` 를 빼면 DLSS 디노이저 라이브러리가 안 들어와 프레임이 노이즈로 덮이고 mp4 가 100 Mbps 가 된다(2026-09-16 verify_4: 366 MB/30 s,
`ngx` 넣은 뒤 같은 조건 2~3 MB). 확인: 컨테이너 안 `ls /usr/lib/x86_64-linux-gnu | grep -c ngx` → 2. `docker run --gpus all` 과 k8s(env `all`)는 해당 없음.
**GPU 접근이 어느 날 조용히 사라진다**(-241, 2026-09-17 새벽 실측). unattended-upgrade 가 `systemd daemon-reload` 를 부르면 docker(systemd cgroup 드라이버, cgroup v2)가 상주 컨테이너의 device cgroup 을 다시 적용하는데, nvidia 훅이 넣어 준 `/dev/nvidia*` 허용은 그때 사라진다. 컨테이너는 살아 있고 장치 파일도 보이지만 열리지 않아 `nvidia-smi` 가 NVML 999, Kit 이 Vulkan INCOMPATIBLE_DRIVER 를 내고 프레임 0 장으로 420 s 를 태운 뒤 실패한다. 처방 둘: ① compose `devices:` 에 `/dev/nvidia0 nvidiactl nvidia-modeset nvidia-uvm nvidia-uvm-tools` 를 명시해 docker 자신의 목록(HostConfig)에 올린다 — 재적용에서 살아남는다(NVIDIA 문서의 처방, 대안은 CDI `nvidia-ctk cdi generate`). ② 엣지가 Start 마다 `nvidia-smi` 프로브(`edge/gpu.py`)를 돌려 안 되면 Kit 을 띄우지 않고 `LastError` `gpu unavailable: …` 로 ERROR 보고 뒤 종료 코드 3 으로 내려간다 → `restart: unless-stopped` 가 다시 띄우며 nvidia 훅이 장치를 재주입하고, host-orch 는 NDEATH 로 런을 바로 접어 BE 가 재시도할 수 있다. 재현·확인: `sudo systemctl daemon-reload` 뒤 `docker exec t3amr-runner nvidia-smi -L`. k8s 는 device plugin 이 장치를 스펙에 넣으므로 해당 없음.
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
| `edge/runner.py` | 상태기계 IDLE → STARTING(첫 프레임 대기) → RUNNING → STOPPING(SIGINT → mp4 조립 → 업로드 → 프레임 삭제) → IDLE/ERROR. `Runner/VideoUrl` 메트릭. Start 직전 GPU 프로브(-241) |
| `edge/recorder.py` | Start → `RUN_TAG`·`PIBT_N`·`PIBT_SEED`·`PIBT_HORIZON`·`REPLAN` 환경으로 `run_record.sh` 기동, 촬영 감지(`캡처 ON`·프레임), 정지 사다리, `remove_frames()`(업로드 성공 뒤 `out/shots_<run>/` 삭제 — 런당 1.6~2.6 GB, 실패 런은 진단용으로 남김, -241) |
| `edge/gpu.py` | Start 직전 `nvidia-smi` 프로브. 실패 사유가 `LastError` 에 실리고 엣지는 종료 코드 3 으로 내려간다 (-241, §1 'GPU 접근') |
| `edge/upload.py` | mp4 → MinIO(`MINIO_*`, 쓰기 전용 계정) → **객체 키** `<run_id>/<파일>` (-233, 버킷 이름은 안 붙는다). URL 은 백엔드가 조회 시 서명해서 만든다 |
| `edge/spec.py` | Start JSON 파싱. `window_s` 는 `timeout_s − 300` 에서 되돌린다 |

영상 길이는 compose env `SHOT_STRIDE` 로 정한다(-241): 배속 = STRIDE × `SHOT_FPS`(30) / 60. 기본을 20(10배속, 창 600 s → 26 s)에서 **10(5배속, 약 53 s)** 으로 낮췄다. 프레임 PNG 는 2배(런당 약 3 GB)지만 업로드 뒤 지우므로 디스크에 안 쌓인다.

**구간 재생 영상 (-244)** — DES 피크 구간(`scenario.trajectory_gz_b64`)을 돌리면 두 영상 모두 「주문을 처리하는 중」이 보이게 글씨를 얹는다(`path/demo_overlay.py`, 물리와 무관).

| 영상 | 무엇이 보이나 | 끄기·바꾸기 |
|---|---|---|
| 상단(`demo_<run>.mp4`) | 로봇이 다닌 범위에 맞춘 천장 시점 · 로봇마다 단계 색 원(픽업 이동·적재·운반·하역·대기) · 번호 · 진행 방향 · 포장대 이름 · 창 시계 · 전체 완료 운행/토트 | `PIBT_TOP_MARK=0` · `PIBT_TOP_FIT=0`(씬 기본 120 m 전경) |
| 추종(`demo_<run>_fpv.mp4`, 화면 「AMR 추종 시점」) | 창 안에서 운행을 가장 많이 끝내는 로봇을 **뒤·선반 위(4.5 m 뒤 · 5 m 높이)** 에서 따라간다 · 주문·토트 수 · 출발 → 도착 · 단계 · 그 로봇 실적 | `PIBT_FPV_VIEW=fpv`(1인칭 대시캠) · `PIBT_FPV_HUD=0` |

- 1인칭(대시캠)을 기본에서 뺀 이유: 포장대가 흰 벽 앞이라 **하역하는 동안 화면이 하얗게** 찍혔다(주문 처리의 핵심 장면). 추종 시점은 로봇 선반의 상자와 포장대의 토트가 한 화면에 든다.
- 한글 글꼴은 이미지의 `fonts-nanum`. 없으면 영어 글씨로 찍힌다(`PIBT_HUD_FONT`).
- 상단을 뷰포트 대신 리플리케이터로 받고, 프레임 쓰기(글씨·PNG 인코딩)는 뒤 스레드가 한다 — PNG 레벨 1(`PIBT_PNG_LEVEL`). 10대 구간 두 시점 **12.3 ms/step(실시간 1.35배)**, 이전 뷰포트 경로 15~20 ms/step.
- 회전 관문도 구간 재생 기본을 바꿨다: `PIBT_TURN_BODY_GEO=1` · `PIBT_TURN_BODY_MAX=20`(칸이 겹쳐도 차체 틈이 넉넉하면 돈다 · 대기 상한 20 s). 피크 10대 두 구간 실측 창 동작 시작 83.3→88.5 % · 54.7→76.3 %, 접촉 0.

host-orch 쪽(-215 같이): `Runner/VideoUrl` → `sim.verify.result.artifacts.video`. **EC2 host-orch 는 `--fms-node` 없이 띄운다** — t3_amr 이 자체 계획으로 돌아 fms-core 가 RUNNING 이 될 일이 없다.
**`--stop-timeout-s` 도 올려야 한다(기본 60 → 300 권장)** — Stop 뒤 Kit 정리(≤25 s) + ffmpeg 조립(프레임 수천 장이면 1 분 넘게) + MinIO 업로드가 STOPPING 안에서 일어난다. 업로드는 워커 스레드라 그동안 하트비트·NCMD 는 계속 처리된다.

단위 테스트(브로커·Isaac 없이): `cd 2_Simulation && python3 -m pytest` (66건). 브로커 붙여 손으로 돌리기:
```bash
cd 2_Simulation/t3_amr && python3 -m edge --env-file ../../3_FMS/infra/emqx/.env -v     # MINIO_* 없으면 VideoUrl = file://… (로컬 확인용)
```

| 요청 필드 | t3_amr 환경변수 | 비고 |
|---|---|---|
| `n_robots` | `PIBT_N` | 계획 폴더 `plan/traj_pibt_h/fleet_NN` 이 없으면 `REPLAN=1` 로 run_record.sh 가 먼저 계획한다(로컬, Isaac 불필요) |
| `scenario.seed` | `PIBT_SEED` | |
| `timeout_s − 300` (= window_s) | `PIBT_HORIZON`(틱 = (창+60 s) ÷ 0.333 s, 0.333 = 1.2 m ÷ (0.9 m/s × 4틱) — 211 틱 모델, `recorder.DEFAULT_TICK_S`) | 창 끝은 host-orch Stop 이 자른다. 틱 길이는 `T3AMR_TICK_S` |
| `scenario.orders` | — | **못 받는다.** t3_amr 은 lifelong 자체 발주. `PIBT_ORDER_GAP` 으로 부하만 맞춘다(후속) |

### 영상 저장소 (-233)

| 항목 | 값 |
|---|---|
| 버킷 | EC2 MinIO `verify-videos`, **비공개**(`mc anonymous set none`). 익명 URL 은 403 |
| 쓰기 계정 | `sim-runner` — 정책 `sim-runner-write` = GetBucketLocation + `verify-videos/*` PutObject·AbortMultipartUpload·ListMultipartUploadParts. HEAD·GET 은 403 이라 엣지는 올리기만 한다 |
| 읽기 계정 | `santa-be` — 정책 `santa-be-read` = GetBucketLocation + `verify-videos/*` GetObject. 백엔드가 서명 URL 을 만드는 데 쓴다 |
| 비밀 보관 | EC2 `~/minio-keys/{sim-runner,santa-be}.env`(600). GPU 박스는 `deploy/.env`(gitignored) 로 복사, k3s 는 Secret `t3amr-runner-env` |
| 만든 방법 | `docker exec a106-minio mc …` (mb · anonymous set none · admin policy create · admin user add · admin policy attach). 멱등 스크립트는 MR -233 본문 |

엣지가 `Runner/VideoUrl` 로 보내는 값은 버킷 없는 객체 키 `<run_id>/<파일>` 이고(버킷은 양쪽 `MINIO_BUCKET`), 화면용 서명 URL 은 백엔드 `VerifyVideoPresigner`(-89) 몫이다 —
서명 방법과 nginx `/media/` 함정은 `3_FMS/contracts/SIM_VERIFY_CONTRACT.md` §7 에 적었다(2026-09-16 실측: 서명 있으면 200, 없으면 403).

## 3-1. 러너 여러 대 — 후보 대수 동시 검증 (-244)

백엔드가 권장 대수 −1 · 0 · +1 을 한 번에 검증 요청하고, host-orch 가 **비어 있는 노드**에 한 건씩 나눠 준다.
노드 = 러너 컨테이너 하나(엣지 하나, `NODE_ID`). 같은 이미지를 노드 이름과 상태 폴더만 바꿔 띄운다.

```bash
docker compose -f compose.yml --profile multi up -d        # sim-runner-gpu01 + sim-runner-gpu02
```

| 필요한 것 | 어디 |
|---|---|
| 노드마다 다른 `NODE_ID` · `container_name` · 데이터 폴더(`./data`, `./data2`) | `compose.yml` 의 `t3amr-runner-2` (profile `multi`) |
| EMQX 계정 `sim-runner-gpu02`(비밀번호는 gpu01 과 같은 `MQTT_PW_SIM_RUNNER`) · ACL | `3_FMS/infra/emqx` — 떠 있는 브로커에는 한 번 손으로 추가 |
| host-orch 노드 목록 `HOST_ORCH_NODES=sim-runner-gpu01,sim-runner-gpu02` | `3_FMS/infra/compose.host-orch.yml` |

용량 실측(2026-09-26, 이 박스 RTX 5080 16 GB · RAM 64 GB, 10대 피크 구간 재생): 한 대당 RAM 약 16 GB · VRAM 약 5 GB.
**2대 동시**는 RAM 42 GB · VRAM 10.6 GB, 배속 0.83~0.86 으로 여유가 있다. 3대는 RAM 59/62 GB 에 스왑까지 쓰고
VRAM 15.4/16.3 GB 라 쓰지 않는다.

다른 GPU 서버로 옮길 때: **RT 코어가 있는 GPU**라야 한다(RTX · L4 · L40S 계열. A100 · H100 은 Isaac 렌더링 불가).
MQTT · MinIO 는 지금 tailnet 주소라 그 서버에서는 공인 경로(TLS · 출발지 제한 · 전용 계정)가 따로 필요하다.

## 4. 아직 안 정한 것
- 검증 런에서 fms-core 를 뺄지(권장, 영상이 목표) — 빼면 host-orch 를 `--fms-node` 없이 띄운다.
- 창 길이(300~600 s)와 RTF. 녹화는 실시간보다 느릴 수 있어 벽시계 = 창 ÷ RTF.
- 이미지 레지스트리(GitLab registry 또는 GHCR). 그 전까지는 `ctr import`.
