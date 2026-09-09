# ============================================================
# 견적 워커 배포 이미지 (S15P21A106-157)
#
# fms-sim:local 과 다른 점 하나 — 시뮬 코드를 마운트가 아니라 이미지에 굽는다.
# EC2 에는 이 컨테이너만 올라가고 호스트에 3_FMS 트리가 없어도 된다.
#
# sim.Dockerfile 을 고치지 않고 파일을 나눈 이유:
#   - sim.Dockerfile 에 구우면 θ 이미지 안에도 시뮬 사본이 생긴다. 평소엔
#     /work 마운트가 덮어 안 보이지만, 마운트 없이 돌리면 에러가 아니라
#     **구워진 옛 사본이 조용히 돈다**. 실패보다 나쁜 실패다.
#   - θ 이미지의 존재 이유가 "코드를 안 넣어서 재빌드가 필요 없다"인데,
#     구우면 시뮬을 고칠 때마다 그 캐시가 깨진다.
#   - -155 는 "이미지·compose 를 새로 만들지 않는다"고 정했었다(docs/견적_워커.md).
#     그때 전제는 "같은 호스트에 마운트해서 돌린다"였고, -157 에서 워커만
#     올리기로 하면서 그 전제가 사라졌다.
#
# 컨텍스트는 infra 가 아니라 3_FMS 다 — sim_engine·map 이 infra 밖에 있어
# COPY 가 컨텍스트를 벗어날 수 없기 때문이다.
#
#   docker build -f 3_FMS/infra/estimate.Dockerfile -t fms-estimate-worker:latest 3_FMS
# ============================================================
FROM python:3.11.9-slim

# 워커 1개 = 1코어. BLAS 가 코어를 더 잡으면 처리율이 오히려 떨어진다
# (sim.Dockerfile 과 같은 이유).
ENV OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=utf-8 \
    MPLBACKEND=Agg \
    SIM_NO_PLOT=1

# 버전 고정은 θ 이미지와 같은 파일을 공유한다 — 두 이미지가 어긋나면
# 같은 요청이 서버마다 다른 KPI 를 낸다.
COPY infra/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# 배치가 계약이다. map_loader.py:24 가 map 을 sim_engine 의 형제로 찾고,
# from_theta.py:25 가 contracts 를 sim_engine 의 형제로 찾는다. /app 아래
# 이 배치를 지키면 코드 수정이 필요 없다.
COPY sim_engine/ /app/sim_engine/
COPY map/        /app/map/
COPY contracts/  /app/contracts/
COPY infra/out/  /app/infra/out/
# 주문 자체 생성(-158): 워커가 ORDER_GEN_DIR(기본 <3_FMS>/order_gen = /app/order_gen)에서 생성기·프로파일·마스터를 읽는다.
COPY order_gen/  /app/order_gen/

COPY infra/worker/ /opt/worker/

# SIM_ENGINE_DIR 을 반드시 명시한다. 안 주면 estimate_worker.py:26 이
# /work/sim_engine 을 찾다 없으면 파일 기준 3단계 위로 폴백하는데,
# /opt/worker 에서 그건 루트라 /sim_engine 을 가리킨다.
ENV PYTHONPATH=/opt/worker \
    SIM_ENGINE_DIR=/app/sim_engine \
    THETA_PATH=/app/infra/out/theta_wallA_r24_g15.json

CMD ["python", "/opt/worker/estimate_worker.py"]
