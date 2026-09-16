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

COPY infra/worker/ /opt/worker/

# SIM_ENGINE_DIR 을 반드시 명시한다. 안 주면 estimate_worker.py:26 이
# /work/sim_engine 을 찾다 없으면 파일 기준 3단계 위로 폴백하는데,
# /opt/worker 에서 그건 루트라 /sim_engine 을 가리킨다.
ENV PYTHONPATH=/opt/worker \
    SIM_ENGINE_DIR=/app/sim_engine

# THETA_PATH 는 **여기서 정하지 않는다** (S15P21A106-234). 전에는 이 줄에
# theta_wallA_r24_g15.json 을 박아 두었는데, 그 뒤 코드 기본값이 v3.6 조건 θ
# (theta_wallA_r20_c6_v36.json)로 옮겨졌는데도 여기가 안 따라와 **ENV 가 코드를 덮었다** —
# estimate_worker.py:39 이 "구 조건(1토트·속도 1.0·1칸=1틱·마스크 없음)이라 지금 시뮬과
# 다른 세계의 값"이라고 적어 둔 바로 그 파일로 배포 워커가 돌고 있었다(실측: 이미지 ENV 확인).
# 값을 새 파일명으로 바꿔 적으면 같은 드리프트가 또 난다 — 기본값은 코드 한 곳에만 둔다.
# FMS_DIR = dirname(SIM_ENGINE_DIR) = /app 이라 /app/infra/out/ 아래에서 풀린다(COPY infra/out/).
# 다른 θ 로 돌리려면 compose/런타임에서 THETA_PATH 를 준다("" 이면 중립).

CMD ["python", "/opt/worker/estimate_worker.py"]
