# ============================================================
# 시뮬 + BO 워커 이미지 (S15P21A106-127)
#
# 베이스 태그를 로컬 개발 환경(python 3.11.9)에 맞춰 고정한다. numpy 버전이
# 다르면 float 누적이 달라져 B-0 기준선이 재현되지 않는다 — 130이 맵 복사본
# 어긋남으로 겪은 것과 같은 부류의 사고를 버전으로 반복하지 않으려는 것.
#
# 코드는 이미지에 넣지 않고 /work 에 마운트한다. sim_engine 을 고칠 때마다
# 다시 빌드하지 않아도 되고, 컨테이너 안팎이 항상 같은 소스를 본다.
#
# 빌드:  docker build -f 3_FMS/infra/sim.Dockerfile -t fms-sim:local 3_FMS/infra
# 실행:  docker run --rm -v "$PWD/3_FMS:/work" -w /work/sim_engine \
#            -e SIM_NO_PLOT=1 fms-sim:local \
#            python sim_v2_tasks.py smoke 10 40 42 0 --flow=main
# ============================================================
FROM python:3.11.9-slim

# 워커 1개 = 1코어. BLAS 가 코어를 더 잡으면 워커 N개 × 스레드 N개로
# 컨텍스트 스위칭이 폭발해 처리율이 오히려 떨어진다.
ENV OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MPLBACKEND=Agg \
    SIM_NO_PLOT=1

WORKDIR /work

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# 워커 코드만 이미지에 넣는다 (시뮬 코드는 마운트).
COPY worker/ /opt/worker/
ENV PYTHONPATH=/opt/worker

CMD ["python", "-c", "import optuna, numpy; print('optuna', optuna.__version__, '/ numpy', numpy.__version__)"]
