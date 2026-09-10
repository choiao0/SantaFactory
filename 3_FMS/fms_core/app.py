"""fms-core 진입점 — Sparkplug Edge(fms-core) 데몬 CLI.

  python3 -m fms_core --env-file 3_FMS/infra/emqx/.env                          # 상주: host-orch 의 NCMD Start/Stop 을 받는다
  python3 -m fms_core --env-file … --once start.json --once-window-s 60          # Start 1건을 직접 넣고 창 뒤 Stop, 결과 stdout
  python3 -m fms_core --spawn 3                                                  # DES 와 같은 초기 배치의 Isaac spawn 문자열
비밀번호는 환경에서만: MQTT_PW_FMS_CORE (또는 --env-file). 플래너 옵션은 --planner-opt key=value (반복).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time
from typing import Optional

from .conductor import ERROR, IDLE, RUNNING, Conductor, ConductorConfig
from .edge import TICK_S, Edge
from .spb import EdgeSession

log = logging.getLogger("fms_core")
DEFAULT_STATE_DIR = os.path.expanduser("~/.local/state/fms_core")
CONNECT_WAIT_S = 30.0


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


def parse_options(items) -> dict:
    """--planner-opt key=value → dict. 값은 bool · int · float · 문자열 순으로 해석."""
    out: dict = {}
    for item in items or ():
        if "=" not in item:
            raise SystemExit(f"--planner-opt needs key=value: {item!r}")
        key, raw = item.split("=", 1)
        out[key.strip()] = _coerce(raw.strip())
    return out


def _coerce(raw: str):
    low = raw.lower()
    if low in ("true", "false"):
        return low == "true"
    for conv in (int, float):
        try:
            return conv(raw)
        except ValueError:
            continue
    return raw


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fms_core",
                                description="fms-core — VDA 5050 fleet manager + Sparkplug Edge (MQTT_CONTRACT §4 · §5)")
    p.add_argument("--env-file", action="append", help=".env (MQTT_HOST · MQTT_PORT · MQTT_PW_FMS_CORE), 반복 가능")
    p.add_argument("--host", help="브로커 (기본 $MQTT_HOST 또는 localhost)")
    p.add_argument("--port", type=int, help="브로커 포트 (기본 $MQTT_PORT 또는 1883)")
    p.add_argument("--group", default="santa")
    p.add_argument("--node-id", default="fms-core", help="edge_node_id = username = clientId")
    p.add_argument("--planner", default="kernel", help="주행 로직 (fms_core.planner.PLANNERS)")
    p.add_argument("--planner-opt", action="append", metavar="KEY=VALUE",
                   help="플래너 옵션 (kernel: aisle_block · theta_path · lanes · yield_rule · fixed_homes · horizon_ticks …)")
    p.add_argument("--tick-s", type=float, default=1.0, help="틱 최소 길이 [s] (= DES DT)")
    p.add_argument("--ack-timeout-s", type=float, default=30.0, help="노드 하나 도착 상한 [s]")
    p.add_argument("--ready-timeout-s", type=float, default=420.0, help="Start 뒤 전원 ONLINE+포즈 상한 [s]")
    p.add_argument("--heartbeat-s", type=float, default=5.0)
    p.add_argument("--host-offline-s", type=float, default=15.0, help="host-orch STATE offline 지속 → 런 실패")
    p.add_argument("--state-dir", default=DEFAULT_STATE_DIR, help="bdseq 파일")
    p.add_argument("--once", help="Start JSON 파일 1건을 직접 넣고 끝나면 종료 (host-orch 없이)")
    p.add_argument("--once-window-s", type=float, default=60.0, help="--once: RUNNING 뒤 이만큼 지나면 Stop")
    p.add_argument("--spawn", type=int, metavar="N", help="DES 초기 배치 N대의 Isaac WSIM_SPAWN 문자열을 출력하고 종료")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def build(args: argparse.Namespace) -> tuple:
    """인자 + 환경 → (Edge, host, port). 비밀번호가 없으면 SystemExit(2)."""
    for f in args.env_file or ():
        load_env_file(f)
    host = args.host or os.environ.get("MQTT_HOST") or "localhost"
    port = args.port or int(os.environ.get("MQTT_PORT") or 1883)
    password = os.environ.get("MQTT_PW_FMS_CORE")
    if not password:
        raise SystemExit("MQTT_PW_FMS_CORE must be set (env or --env-file)")
    session = EdgeSession(os.path.join(args.state_dir, "bdseq"))
    cfg = ConductorConfig(args.group, args.node_id, args.planner, parse_options(args.planner_opt), args.tick_s,
                          args.ack_timeout_s, args.ready_timeout_s, args.heartbeat_s, args.host_offline_s)
    conductor = Conductor(cfg, session, None)
    edge = Edge(args.node_id, password, session, conductor)
    conductor.pub = edge
    return edge, host, port


def spawn_string_for(n: int) -> str:
    from .kernel_planner import des_homes
    from .world import spawn_string
    return spawn_string(des_homes(n))


def run_once(edge: Edge, host: str, port: int, path: str, window_s: float) -> int:
    """Start 1건: 접속 → handle_start → RUNNING 이 window_s 지나면 Stop → IDLE/ERROR 까지 tick → 결과 stdout."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    c = edge.conductor
    edge.connect(host, port)
    try:
        if not edge.connected.wait(CONNECT_WAIT_S):
            log.error("broker connect timeout")
            return 2
        with edge.lock:
            c.handle_start(text, time.time())
            left_idle = c.state != IDLE
        while not edge.stop_event.is_set():
            time.sleep(TICK_S)
            with edge.lock:
                now = time.time()
                c.tick(now)
                if c.state == RUNNING and c.running_since is not None and now - c.running_since >= window_s:
                    c.handle_stop(now)
                left_idle = left_idle or c.state != IDLE
                if left_idle and c.state in (IDLE, ERROR):
                    break
        result = c.snapshot()
    finally:
        edge.shutdown()
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if result["state"] == IDLE else 1


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.spawn:
        print(spawn_string_for(args.spawn))
        return 0
    edge, host, port = build(args)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: edge.stop_event.set())
    if args.once:
        return run_once(edge, host, port, args.once, args.once_window_s)
    edge.run(host, port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
