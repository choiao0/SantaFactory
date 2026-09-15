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

## 2. k3s

- EC2 의 k3s 서버에 이 박스를 agent 로 붙인다 (tailnet 주소로). 노드 라벨 `santa.io/gpu=true`.
- 노드에 툴킷이 있으면 k3s 가 `nvidia` 런타임을 자동 등록한다 → `k8s/runtimeclass.yaml`. GPU 리소스는 NVIDIA device plugin DaemonSet.
- 레지스트리가 아직 없으니 이미지는 로컬 빌드 후 k3s 의 containerd 로 넣는다:
  `docker save t3amr-runner:dev | sudo k3s ctr images import -`
- `k8s/secret.example.yaml` 을 채워 apply → `k8s/deployment.yaml` apply.

## 3. 엣지(상주 러너) — 다음 단계

219 로 지운 `sim_runner`(마지막 커밋 ac10c76)의 Sparkplug 코덱·NBIRTH/NDATA·NCMD 상태기계를 `t3_amr/edge/` 로 되살리고,
프로세스 런처만 `run_record.sh` + MinIO 업로드로 바꾼다. host-orch 쪽은 `Runner/VideoUrl` 을 `artifacts.video` 에 싣는 한 줄과
`--fms-node` 제거가 필요하다. 계약은 `3_FMS/contracts/SIM_VERIFY_CONTRACT.md` · `MQTT_CONTRACT.md` §5.

| 요청 필드 | t3_amr 환경변수 | 비고 |
|---|---|---|
| `n_robots` | `PIBT_N` | 1..64 (씬의 충전 존 한도는 별도) |
| `scenario.seed` | `PIBT_SEED` | |
| `window_s` | `PIBT_HORIZON`(틱) | 창 길이. 초 → 틱 환산은 run 의 dt 로 |
| `scenario.orders` | — | **못 받는다.** t3_amr 은 lifelong 자체 발주. `PIBT_ORDER_GAP` 으로 부하만 맞춘다 |

## 4. 아직 안 정한 것
- 검증 런에서 fms-core 를 뺄지(권장, 영상이 목표) — 빼면 host-orch 를 `--fms-node` 없이 띄운다.
- 창 길이(300~600 s)와 RTF. 녹화는 실시간보다 느릴 수 있어 벽시계 = 창 ÷ RTF.
- 이미지 레지스트리(GitLab registry 또는 GHCR). 그 전까지는 `ctr import`.
