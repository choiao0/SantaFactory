# ============================================================
# fms-core 배포 이미지 (S15P21A106-92) — VDA 5050 플릿 매니저 + Sparkplug Edge(fms-core)
#
# 견적 워커 이미지(estimate.Dockerfile)와 같은 파이썬·numpy 를 쓴다 — 같은 sim_engine 커널이 같은 부동소수점 순서로 돌아야
# DES 견적과 KPI 를 비교할 수 있다. 배치가 계약이다: map_loader.py:24 가 map 을 sim_engine 의 형제로,
# from_theta.py:25 가 contracts 를 sim_engine 의 형제로 찾고, fms_core/kernel_planner.py 가 sim_engine 을 자기 형제로 찾는다.
#
#   docker build -f 3_FMS/infra/fms_core.Dockerfile -t fms-core:latest 3_FMS
#   docker compose -f 3_FMS/infra/compose.fms-core.yml up -d --build
# ============================================================
FROM python:3.11.9-slim

ENV OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=utf-8

WORKDIR /app
RUN pip install --no-cache-dir numpy==2.4.6 paho-mqtt==2.1.0 protobuf==7.36.1

COPY sim_engine/ /app/sim_engine/
COPY map/        /app/map/
COPY contracts/  /app/contracts/
# θ 는 견적 워커 이미지와 같은 파일을 쓴다 (estimate.Dockerfile 과 같은 줄). 없으면 fms-core 가 중립 θ 로 돌아
# 같은 주문에서도 견적과 다른 경로를 내고, 그 KPI 는 견적과 비교할 수 없다 (S15P21A106-185).
COPY infra/out/  /app/infra/out/
COPY fms_core/   /app/fms_core/

VOLUME ["/state"]
ENTRYPOINT ["python3", "-m", "fms_core", "--state-dir", "/state"]
