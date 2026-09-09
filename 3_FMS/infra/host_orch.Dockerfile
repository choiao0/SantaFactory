# host-orch — Sparkplug Primary Host + sim.verify 소비자 (S15P21A106-86). 빌드 컨텍스트 = 3_FMS
#   docker compose -f compose.host-orch.yml up -d --build
FROM python:3.10-slim
WORKDIR /app
RUN pip install --no-cache-dir pika==1.3.2 paho-mqtt==2.1.0 protobuf==7.36.1 psutil==7.2.2
COPY host_orch/ /app/host_orch/
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python3", "-m", "host_orch"]
