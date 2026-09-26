# syntax=docker/dockerfile:1.7
# ============================================================
# t3_amr 러너 이미지 — Isaac Sim(pip) + t3_amr + 계획기 원본(3_FMS/sim_engine) + ffmpeg + 상주 엣지(MQ 트리거)
#
# install.sh(2026-09) 의 레시피를 그대로 옮긴 것이다:
#   Python 3.12 venv · isaacsim[all,extscache]==6.0.1.0 (pypi.nvidia.com, cp312 전용)
#   시스템 라이브러리 libgl1 libegl1 libx11-6 libxcb1 libsm6 libgomp1 · imageio-ffmpeg · iw.hub 에셋(공개 S3)
#   여기에 install.sh 가 안 하는 것 둘을 더 굽는다 — 적재 선반 USD(-196), 계획기 원본(3_FMS/sim_engine, -220).
#
# 빌드 (저장소 루트에서. docker 그룹 권한 + buildx — deploy/README.md §0·§1):
#   docker build -f 2_Simulation/t3_amr/deploy/Dockerfile \
#       --build-context sim_engine=3_FMS/sim_engine -t t3amr-runner:dev 2_Simulation/t3_amr
# 이미지는 26 GB(Isaac 휠)다. 셰이더 캐시(약 5 GB)는 이미지가 아니라 볼륨(/cache/ov)에 쌓인다.
#
# 이미지 안 배치는 저장소와 같은 두 단이다 — /app/2_Simulation/t3_amr · /app/3_FMS/sim_engine.
# path/pibt_core_v2.py 가 계획기 원본을 `../../3_FMS/sim_engine` 로 찾기 때문이다. 못 찾으면 옛 벤더 사본으로
# 후퇴해 `MOVE_TICKS` 가 없다며 계획 단계에서 죽는다 (2026-09-16 첫 실행에서 확인). PIBT_CORE_DIR 로 가리켜도
# 되지만 그러면 매 런 "저장소 밖" 경고가 찍힌다 — 같은 커밋의 원본이니 경로를 맞추는 편이 맞다.
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
# 캐시 마운트로 재빌드 시 다시 받지 않게 한다. (첫 빌드 실측 2026-09-16: 11 MB/s 회선에서 이 단계 23 분)
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install "isaacsim[all,extscache]==${ISAAC_VER}" --extra-index-url https://pypi.nvidia.com

# ffmpeg(루트 없는 서버 관례대로 imageio-ffmpeg 의 정적 바이너리) + 엣지(paho·protobuf·minio) + 계획기(numba).
#   numba: 3_FMS/sim_engine/pibt/hgraph.py 가 `from numba import njit` 를 무조건 한다(-225). 3_FMS 는 0.67 을 쓰지만
#   Isaac(isaacsim-core) 이 llvmlite==0.46.0 을 못박고 있어 여기서는 그 llvmlite 와 맞는 numba 0.64 를 쓴다 (numpy 2.3.1 호환).
#   coverage: Isaac(isaacsim-kernel) 이 7.4.4 를 깔아 두는데 numba ≥0.63 의 coverage_support 가 coverage.types.Tracer(7.5+)를
#   요구해 import 가 죽는다(2026-09-16 실측). Kit 테스트 도구용 패키지라 올려도 런타임엔 무관 — 7.16.1 로 올린다.
#   psutil 은 핀하지 않는다 — isaacsim-kernel 이 5.9.8 을 못박고 있어 7.x 를 얹으면 pip 이 충돌을 찍는다.
#   엣지가 쓰는 API(process_iter · Process · NoSuchProcess/AccessDenied/ZombieProcess)는 5.9.8 에도 있다.
#   `pip check` 는 coverage 핀 하나만 어긋난다고 보고한다 — 알고 받아들인 것이다.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install imageio-ffmpeg paho-mqtt==2.1.0 protobuf==7.36.1 minio==7.2.15 numba==0.64.0 coverage==7.16.1 \
    && ln -sf "$(python -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())')" $VE/bin/ffmpeg \
    && ffmpeg -version | head -1 \
    && python -c 'import psutil, numba, llvmlite, numpy; from numba import njit; print("psutil", psutil.__version__, "numba", numba.__version__, "llvmlite", llvmlite.__version__, "numpy", numpy.__version__)'

# 검증 영상 글씨(-244 · 279, path/demo_overlay.py)의 한글 글꼴 — Noto Sans CJK KR 세 굵기(Regular·Medium·Bold)를 쓴다.
# 없으면 영어 글씨로 찍힌다(runners/headless_pibt.py HUD_FONT). Medium 은 fonts-noto-cjk-extra 에만 있다.
RUN apt-get update && apt-get install -y --no-install-recommends fonts-noto-cjk fonts-noto-cjk-extra \
    && apt-get clean && rm -r /var/lib/apt/lists \
    && for w in Regular Medium Bold; do test -f /usr/share/fonts/opentype/noto/NotoSansCJK-$w.ttc || exit 1; done

# 계획기 원본 — 이름 있는 컨텍스트(--build-context sim_engine=3_FMS/sim_engine). 코드만 넣는다
# (results/·tests/·sweeps/ 제외).
#   ★ 최상위 모듈 전부와 kernel/ 까지 (-275). 예전에는 pibt_core.py·pibt/ 뿐이라 궤적 재생
#     (`PIBT_TRAJ` = FMS 격자 `PIBT_FMS_GRID`)이 map_loader·topology_spec 을, 백엔드 주문
#     (`JsonOrderStream`)이 order_stream(→ kernel.core)을 못 불러 **컨테이너에서는 한 번도 못 돌았다**
#     (09-24 verify_18 로그: `No module named 'order_stream'` — 대형 주문 거름이 조용히 빠졌다).
COPY --from=sim_engine *.py /app/3_FMS/sim_engine/
COPY --from=sim_engine pibt /app/3_FMS/sim_engine/pibt
COPY --from=sim_engine kernel /app/3_FMS/sim_engine/kernel
# FMS 공식 맵 데이터(--build-context fms_map=3_FMS/map) — map_loader.MAP_DIR(= sim_engine/../map) 이
# 읽는 파일만. 코드·그림·synth/ 는 뺀다.
COPY --from=fms_map occupancy_grid.npy stations.json charge_zone.json rack_buffers.json /app/3_FMS/map/

ENV T3=/app/2_Simulation/t3_amr
WORKDIR $T3
# 에셋 둘 — 코드 COPY 보다 앞에 두어 코드만 바뀐 재빌드에서 이 레이어가 캐시를 탄다. 둘 다 git 밖(robots/)이다.
#   iw.hub: 공개 S3, 약 60 MB. 스크립트는 표준 라이브러리만 쓰고 자기 위치 기준 ../robots/iwhub 에 쓴다 (= paths.sh 의 $ROBOT).
#   적재 선반(-196): iw.hub 위에 얹는 3단 선반 + HMI 태블릿. 씬 빌드(amr/path/_common.py scene_cmd)가
#   robots/shelf/amr_shelf.usd 가 **있을 때만** 매달므로 여기서 안 만들면 영상에 맨 로봇이 나온다.
#   pxr 만 쓰므로 Kit 기동 없이 venv 파이썬으로 돈다. 기본은 스크립트 기본값(상부 안 깎음 1.110 · 3단 · 태블릿 · 콜라이더 없음).
ARG SHELF_TOP_REAR=1.110
COPY tools/fetch_iwhub.py tools/fetch_iwhub.py
COPY warehouse/scene/build_amr_shelf.py warehouse/scene/build_amr_shelf.py
RUN python tools/fetch_iwhub.py && test -f robots/iwhub/iw_hub.usd \
    && python warehouse/scene/build_amr_shelf.py --top-rear ${SHELF_TOP_REAR} && test -f robots/shelf/amr_shelf.usd
# t3_amr 코드 (빌드 컨텍스트 = 2_Simulation/t3_amr). 산출물 폴더·robots/ 는 .dockerignore 로 뺀다 — 에셋은 위 레이어 것만 쓴다.
COPY . $T3

# 상태·캐시·산출물 경로 — 전부 볼륨(/cache, /data). paths.sh 가 OUT·STAGE·LOGS 를 $W/out 등으로 고정하므로
# 그 폴더들을 볼륨으로 링크한다 (환경변수로는 못 바꾼다 — paths.sh:31-36).
ENV HOME=/home/runner \
    OV_CACHE=/cache/ov \
    T3AMR_STATE=/data/state
RUN mkdir -p /home/runner /cache/ov /data/out /data/stage /data/logs /data/state \
    && ln -s /cache/ov /home/runner/.cache \
    && for d in out stage logs; do rm -rf "$T3/$d"; ln -s "/data/$d" "$T3/$d"; done

# Vulkan/EGL 벤더 매니페스트 — nvidia-container-toolkit 은 드라이버 라이브러리(libGLX_nvidia.so.0 등)는 넣어 주지만
# 로더가 읽는 ICD JSON 은 안 넣는다. 없으면 Kit 이 "vkCreateInstance failed … Vulkan 1.1 is not supported" 로 GPU 를 못 만들어
# 렌더러가 죽고 촬영이 0 장이 된다 (2026-09-16 첫 촬영 런에서 확인, vulkaninfo = ERROR_INCOMPATIBLE_DRIVER). NGC Isaac 이미지와 같은 처방.
RUN mkdir -p /etc/vulkan/icd.d /usr/share/glvnd/egl_vendor.d \
    && printf '%s' '{"file_format_version":"1.0.0","ICD":{"library_path":"libGLX_nvidia.so.0","api_version":"1.3.0"}}' > /etc/vulkan/icd.d/nvidia_icd.json \
    && printf '%s' '{"file_format_version":"1.0.0","ICD":{"library_path":"libEGL_nvidia.so.0"}}' > /usr/share/glvnd/egl_vendor.d/10_nvidia.json

# 루트로 돌리지 않는다. uid 1000 = 호스트 개발 계정과 같게 두어 bind mount(./data)·hostPath 소유권이 맞는다.
# plan/·v2/ 는 REPLAN 이 쓰므로 /app 전체(t3_amr + sim_engine)를 runner 소유로.
# /opt/venv 는 루트 소유로 둔다(26 GB 를 chown 하면 레이어가 통째로 복사된다). Kit 이 패키지 안에 쓰는 곳은
# isaacsim/kit/data(documents·screenshots) 뿐이라(2026-09-16 실측 "Failed to create directory …/kit/data/documents/…")
# 그 폴더만 미리 만들어 runner 소유로 둔다. logs·cache 는 $HOME 쪽(~/.nvidia-omniverse, ~/.cache/ov)으로 가지만 같이 둔다.
RUN useradd -m -u 1000 -s /bin/bash runner \
    && KIT=$VE/lib/python${PY}/site-packages/isaacsim/kit \
    && mkdir -p $KIT/data $KIT/logs $KIT/cache \
    && chown -R runner:runner /home/runner /cache /data /app $KIT/data $KIT/logs $KIT/cache

# WebRTC 라이브스트림(촬영에 뷰포트가 필요하다). 클라이언트가 안 붙어도 촬영은 된다 — 포트는 문서용이고 기본으로 열지 않는다.
EXPOSE 49100/tcp 47998/udp

COPY --chown=runner:runner deploy/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
USER runner
ENTRYPOINT ["/usr/bin/tini", "--", "/app/entrypoint.sh"]
CMD ["edge"]
