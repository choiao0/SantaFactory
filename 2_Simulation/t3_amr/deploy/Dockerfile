# syntax=docker/dockerfile:1.7
# ============================================================
# t3_amr 러너 이미지 — Isaac Sim(pip) + t3_amr + ffmpeg + 상주 엣지(MQ 트리거)
#
# install.sh(2026-09) 의 레시피를 그대로 옮긴 것이다:
#   Python 3.12 venv · isaacsim[all,extscache]==6.0.1.0 (pypi.nvidia.com, cp312 전용)
#   시스템 라이브러리 libgl1 libegl1 libx11-6 libxcb1 libsm6 libgomp1 · imageio-ffmpeg · iw.hub 에셋(공개 S3)
#
# 빌드 (GPU 박스, docker 그룹 권한 필요):
#   docker build -f 2_Simulation/t3_amr/deploy/Dockerfile -t t3amr-runner:dev 2_Simulation/t3_amr
# 이미지 크기는 십수 GB(Isaac 휠)다. 셰이더 캐시(약 5 GB)는 이미지가 아니라 볼륨(/cache/ov)에 쌓인다.
# ============================================================
ARG ISAAC_VER=6.0.1.0
ARG PY=3.12

FROM nvidia/cuda:12.6.3-base-ubuntu22.04 AS base
ARG ISAAC_VER
ARG PY
ENV DEBIAN_FRONTEND=noninteractive \
    NVIDIA_DRIVER_CAPABILITIES=all \
    NVIDIA_VISIBLE_DEVICES=all \
    OMNI_KIT_ACCEPT_EULA=YES \
    PYTHONUNBUFFERED=1
# Kit 이 요구하는 GL/EGL/X 라이브러리 + Python 3.12 (Ubuntu 22.04 는 3.10 이라 deadsnakes)
RUN apt-get update && apt-get install -y --no-install-recommends \
        software-properties-common ca-certificates curl gnupg tini \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
        python${PY} python${PY}-venv python${PY}-dev \
        libgl1 libegl1 libx11-6 libxcb1 libsm6 libgomp1 libxext6 libxrender1 libglu1-mesa \
        vulkan-tools libvulkan1 \
    && apt-get clean && rm -r /var/lib/apt/lists

# venv — install.sh 의 $HOME/khs/venv 에 해당. 경로만 /opt/venv 로 고정한다.
# VIRTUAL_ENV 를 박아 두어야 run_record.sh 가 $HOME/khs/venv 를 source 하려 들지 않는다 (run_record.sh:53).
ENV VE=/opt/venv VIRTUAL_ENV=/opt/venv
RUN python${PY} -m venv $VE && $VE/bin/pip install -q --upgrade pip setuptools wheel
ENV PATH=$VE/bin:$PATH

# Isaac Sim 휠 — install.sh 는 25개 패키지를 낱개로 못박지만 같은 버전의 메타패키지로 충분하다.
# 캐시 마운트로 재빌드 시 다시 받지 않게 한다.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install "isaacsim[all,extscache]==${ISAAC_VER}" --extra-index-url https://pypi.nvidia.com

# ffmpeg — 루트 없는 서버 관례대로 imageio-ffmpeg 의 정적 바이너리를 쓴다 (apt ffmpeg 도 무방)
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install imageio-ffmpeg paho-mqtt==2.1.0 protobuf==7.36.1 psutil==7.2.2 minio==7.2.15 \
    && ln -sf "$(python -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())')" $VE/bin/ffmpeg \
    && ffmpeg -version | head -1

# t3_amr 코드 (빌드 컨텍스트 = 2_Simulation/t3_amr). 산출물 폴더는 .dockerignore 로 뺀다.
WORKDIR /app/t3_amr
COPY . /app/t3_amr
# iw.hub 에셋 — git 밖(공개 S3). 빌드 시 받아 이미지에 굽는다 (약 60 MB).
RUN python tools/fetch_iwhub.py && test -f robots/iwhub/iw_hub.usd

# 상태·캐시·산출물 경로 — 전부 볼륨(/cache, /data). paths.sh 가 OUT·STAGE·LOGS 를 $W/out 등으로 고정하므로
# 그 폴더들을 볼륨으로 링크한다 (환경변수로는 못 바꾼다 — paths.sh:31-36).
ENV HOME=/home/runner \
    OV_CACHE=/cache/ov \
    T3AMR_STATE=/data/state
RUN mkdir -p /home/runner /cache/ov /data/out /data/stage /data/logs /data/state \
    && ln -s /cache/ov /home/runner/.cache \
    && for d in out stage logs; do rm -rf "/app/t3_amr/$d"; ln -s "/data/$d" "/app/t3_amr/$d"; done

# WebRTC 라이브스트림(촬영에 뷰포트가 필요하다). 클라이언트가 안 붙어도 촬영은 된다.
EXPOSE 49100/tcp 47998/udp

COPY deploy/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["/usr/bin/tini", "--", "/app/entrypoint.sh"]
CMD ["edge"]
