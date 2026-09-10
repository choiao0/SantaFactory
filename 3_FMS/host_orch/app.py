"""host-orch 진입점 — Primary Host(MQTT) + sim.verify 소비자(AMQP) 배선, CLI.

  python3 -m host_orch --env-file 3_FMS/infra/emqx/.env --env-file 3_FMS/infra/.env       # 상주 (EC2)
  python3 -m host_orch --env-file … --once request.json                                     # AMQP 없이 1건 → 결과 JSON stdout
비밀번호는 환경에서만: MQTT_PW_HOST_ORCH · RABBITMQ_URL(또는 RABBITMQ_HOST/USER/PASSWORD).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
from typing import Optional

from .amqp import REQUEST_QUEUE, RESULT_QUEUE, Consumer, amqp_url
from .mqtt_host import HostClient
from .orchestrator import Coordinator, JobConfig
from .tracker import HostTracker

log = logging.getLogger("host_orch")
TICK_S = 0.5
RUNNER_WAIT_S = 30.0       # --once: sim-runner NBIRTH 를 이만큼 기다린다


def load_env_file(path: str) -> dict:
    """KEY=VALUE 파일(.env). 이미 있는 환경변수는 덮지 않는다."""
    loaded = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value
                loaded[key] = value
    return loaded


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="host_orch", description="Sparkplug Primary Host + sim.verify consumer")
    p.add_argument("--env-file", action="append", help=".env (반복 가능: emqx/.env + infra/.env)")
    p.add_argument("--mqtt-host", help="기본 $MQTT_HOST 또는 localhost")
    p.add_argument("--mqtt-port", type=int, help="기본 $MQTT_PORT 또는 1883")
    p.add_argument("--host-id", default="host-orch", help="host_id = username = clientId")
    p.add_argument("--group", default="santa")
    p.add_argument("--node", default="sim-runner-gpu01", help="NCMD 를 보낼 sim-runner edge_node_id")
    p.add_argument("--fms-node", default=os.environ.get("HOST_ORCH_FMS_NODE", ""),
                   help="fms-core edge_node_id (기본 $HOST_ORCH_FMS_NODE, 비면 fms-core 없이 sim-runner 만 굴린다)")
    p.add_argument("--amqp-url", help="기본 $RABBITMQ_URL 또는 RABBITMQ_HOST/USER/PASSWORD")
    p.add_argument("--request-queue", default=REQUEST_QUEUE)
    p.add_argument("--result-queue", default=RESULT_QUEUE)
    p.add_argument("--start-timeout-s", type=float, default=180.0)
    p.add_argument("--stop-timeout-s", type=float, default=60.0)
    p.add_argument("--once", help="요청 JSON 파일 1건을 AMQP 없이 실행하고 결과를 stdout 에")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


class App:
    def __init__(self, args: argparse.Namespace):
        for f in args.env_file or ():
            load_env_file(f)
        password = os.environ.get("MQTT_PW_HOST_ORCH")
        if not password:
            raise SystemExit("MQTT_PW_HOST_ORCH must be set (env or --env-file)")
        self.args = args
        self.mqtt_host = args.mqtt_host or os.environ.get("MQTT_HOST") or "localhost"
        self.mqtt_port = args.mqtt_port or int(os.environ.get("MQTT_PORT") or 1883)
        self.lock = threading.RLock()
        self.tracker = HostTracker(args.group)
        self.client = HostClient(args.host_id, password, args.group, self._on_mqtt, self.lock,
                                 extra_subscriptions=(("biz/v1/#", 1),))      # fms-core kpi_summary (acl: biz/v1/#)
        self.coord = Coordinator(self.tracker, self.client.send_ncmd, args.node,
                                 JobConfig(start_timeout_s=args.start_timeout_s, stop_timeout_s=args.stop_timeout_s),
                                 fms_node_id=args.fms_node or None)
        self.stop_event = threading.Event()

    def _on_mqtt(self, topic: str, payload: bytes) -> None:
        for ev in self.coord.on_mqtt(topic, payload):
            if ev.kind in ("nbirth", "ndeath", "seq_gap", "unknown_node", "stale_death"):
                snap = self.coord.runner_snapshot() if ev.node == self.args.node else (
                    self.coord.fms_snapshot() if ev.node == self.coord.fms_node_id else "")
                log.info("%s %s %s", ev.kind, ev.node, snap)

    def serve(self) -> int:
        self.client.connect(self.mqtt_host, self.mqtt_port)
        consumer = Consumer(self.args.amqp_url or amqp_url(), self.coord, self.lock,
                            self.args.request_queue, self.args.result_queue)
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: (self.stop_event.set(), consumer.stop_event.set()))
        log.info("host-orch up — MQTT %s:%d, runner %s, fms %s", self.mqtt_host, self.mqtt_port, self.args.node,
                 self.coord.fms_node_id or "(none)")
        try:
            consumer.run_forever()
        finally:
            self.client.close()
        return 0

    def once(self, path: str) -> int:
        """AMQP 없이 요청 1건: runner NBIRTH 대기 → submit → 끝날 때까지 tick → 결과 stdout."""
        with open(path, encoding="utf-8") as f:
            body = f.read()
        self.client.connect(self.mqtt_host, self.mqtt_port)
        try:
            deadline = time.time() + RUNNER_WAIT_S
            while time.time() < deadline and not self.coord.runner_snapshot().get("online"):
                time.sleep(TICK_S)
            with self.lock:
                job = self.coord.submit(body)
            while not job.done and not self.stop_event.is_set():
                time.sleep(TICK_S)
                with self.lock:
                    self.coord.tick()
            result = job.result()
        finally:
            self.client.close()
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0 if result["status"] == "done" else 1


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("pika").setLevel(logging.WARNING)      # pika DEBUG 는 소켓 콜백까지 찍어 잡 로그를 덮는다
    app = App(args)
    if args.once:
        signal.signal(signal.SIGINT, lambda *_: app.stop_event.set())
        return app.once(args.once)
    return app.serve()


if __name__ == "__main__":
    sys.exit(main())
