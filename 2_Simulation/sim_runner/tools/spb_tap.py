"""host-orch 시점의 Sparkplug 관측 + NCMD 발사 — 06 host-orch 가 생기기 전의 검증 도구.

  python3 -m sim_runner.tools.spb_tap --env-file 3_FMS/infra/emqx/.env                      # 관측만 (STATE online 발행)
  python3 -m sim_runner.tools.spb_tap --env-file … --n 2 --run-id r1 --wait RUNNING          # Start 보내고 RUNNING 대기
  python3 -m sim_runner.tools.spb_tap --env-file … --stop --wait IDLE
  python3 -m sim_runner.tools.spb_tap --env-file … --rebirth --duration 5
`--no-state` 면 STATE/host-orch 를 건드리지 않는다(진짜 host-orch 가 있을 때). 종료 시 offline retained 를 남긴다.
종료 코드: 0 = 조건 충족/시간 종료, 1 = --wait 시간 초과, 2 = 접속 실패.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from typing import Optional

import paho.mqtt.client as mqtt

from .. import spb
from ..edge import load_env_file
from ..runner import CMD_START, CMD_STOP, REBIRTH, STATE

SEQ_MOD = spb.SEQ_MOD


def fmt_value(v) -> str:
    if isinstance(v, float):
        return f"{v:.3f}"
    if isinstance(v, str) and len(v) > 60:
        return repr(v[:57] + "…")
    return repr(v) if isinstance(v, str) else str(v)


def summarize_json(payload: bytes) -> str:
    """VDA connection 은 connectionState 만, 그 외는 앞 120자."""
    if not payload:
        return "(cleared)"
    try:
        d = json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        return repr(payload[:120])
    if isinstance(d, dict) and "connectionState" in d:
        return f"connectionState={d['connectionState']} headerId={d.get('headerId')}"
    return json.dumps(d)[:120]


def start_payload(run_id: str, n: int, timeout_s: float, scenario_pkg: str) -> str:
    return json.dumps({"run_id": run_id, "scenario_pkg": scenario_pkg, "n_robots": n, "models": [],
                       "ros_domain_id": 0, "timeout_s": timeout_s})


class Tap:
    def __init__(self, args, password: str):
        self.args = args
        self.node_topic = f"spBv1.0/{args.group}"
        self.seq: dict = {}
        self.runner_state: Optional[str] = None
        self.wait_hit = threading.Event()
        self.connected = threading.Event()
        self.t_conn = int(time.time() * 1000)
        # clientId 는 인스턴스마다 달라야 한다(같으면 브로커가 먼저 붙은 tap 을 밀어낸다). ACL 은 username 기준.
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"{args.username}-tap-{os.getpid()}",
                                  protocol=mqtt.MQTTv311, clean_session=True)
        self.client.username_pw_set(args.username, password)
        if not args.no_state:
            self.client.will_set(f"spBv1.0/STATE/{args.username}",
                                 json.dumps({"online": False, "timestamp": self.t_conn}), qos=1, retain=True)
        self.client.on_connect, self.client.on_message = self._on_connect, self._on_message

    def _on_connect(self, client, _u, _f, rc, _p=None) -> None:
        if rc != 0:
            print(f"!! connect refused: {rc}", flush=True)
            return
        client.subscribe([(f"{self.node_topic}/#", 0), ("spBv1.0/STATE/+", 1)]
                         + ([("uagv/v2/+/+/connection", 1)] if self.args.vda else []))
        if not self.args.no_state:
            client.publish(f"spBv1.0/STATE/{self.args.username}",
                           json.dumps({"online": True, "timestamp": self.t_conn}), qos=1, retain=True)
        self.connected.set()

    def _on_message(self, _c, _u, msg) -> None:
        stamp = time.strftime("%H:%M:%S") + f".{int(time.time() * 1000) % 1000:03d}"
        if msg.topic.startswith("spBv1.0/STATE/") or msg.topic.startswith("uagv/"):
            print(f"{stamp} {msg.topic}  {summarize_json(msg.payload)}", flush=True)
            return
        _, _, kind, node, *rest = msg.topic.split("/")
        try:
            d = spb.decode(msg.payload)
        except Exception as e:  # noqa: BLE001
            print(f"{stamp} {kind} {node} !! undecodable: {e}", flush=True)
            return
        gap = self._check_seq(kind, node, d.seq)
        who = node + ("/" + rest[0] if rest else "")
        body = " ".join(f"{m.name or '#' + str(m.alias)}={fmt_value(m.value)}" for m in d.metrics)
        print(f"{stamp} {kind:<6} {who:<28} seq={d.seq if d.seq is not None else '-':<3} {body}{gap}", flush=True)
        self._track_state(kind, d)

    def _check_seq(self, kind: str, node: str, seq: Optional[int]) -> str:
        """노드별 seq 연속성. BIRTH 를 못 본 노드는 판단을 보류한다."""
        if seq is None or kind in ("NCMD", "DCMD"):
            return ""
        if kind == "NBIRTH":
            self.seq[node] = 0
            return ""
        last = self.seq.get(node)
        self.seq[node] = seq
        if last is None:
            return ""
        expected = (last + 1) % SEQ_MOD
        return "" if seq == expected else f"   !! seq gap (expected {expected})"

    def _track_state(self, kind: str, d: spb.Decoded) -> None:
        if kind not in ("NBIRTH", "NDATA"):
            return
        state = spb.metrics_by_name(d).get(STATE)
        if state is not None:
            self.runner_state = state
            if self.args.wait and state == self.args.wait:
                self.wait_hit.set()

    def send_ncmd(self, values: list) -> None:
        self.client.publish(f"{self.node_topic}/NCMD/{self.args.node}", spb.encode_cmd(values), qos=0)

    def run(self, host: str, port: int) -> int:
        try:
            self.client.connect(host, port, keepalive=30)
        except OSError as e:
            print(f"!! cannot reach {host}:{port}: {e}", flush=True)
            return 2
        self.client.loop_start()
        try:
            if not self.connected.wait(10):
                return 2
            self._send_commands()
            return self._wait()
        finally:
            self._close()

    def _send_commands(self) -> None:
        a = self.args
        if a.rebirth:
            self.send_ncmd([(REBIRTH, spb.BOOLEAN, True)])
        if a.stop:
            self.send_ncmd([(CMD_STOP, spb.BOOLEAN, True)])
        if a.start or a.n:
            text = a.start or start_payload(a.run_id, a.n, a.timeout_s, a.scenario_pkg)
            if text.startswith("@"):
                with open(text[1:], encoding="utf-8") as f:
                    text = f.read()
            self.send_ncmd([(CMD_START, spb.TEXT, text)])

    def _wait(self) -> int:
        if self.args.wait:
            hit = self.wait_hit.wait(self.args.wait_timeout)
            print(f"-- wait {self.args.wait}: {'ok' if hit else 'TIMEOUT'} (state={self.runner_state})", flush=True)
            if self.args.duration:
                time.sleep(self.args.duration)
            return 0 if hit else 1
        time.sleep(self.args.duration if self.args.duration else 10 ** 9)
        return 0

    def _close(self) -> None:
        if not self.args.no_state:
            info = self.client.publish(f"spBv1.0/STATE/{self.args.username}",
                                       json.dumps({"online": False, "timestamp": self.t_conn}), qos=1, retain=True)
            info.wait_for_publish(3)
        self.client.disconnect()
        self.client.loop_stop()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="spb_tap", description="Sparkplug host-orch tap + NCMD sender")
    p.add_argument("--env-file")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.add_argument("--username", default="host-orch", help="비밀번호는 $MQTT_PW_<USERNAME 대문자, - → _>")
    p.add_argument("--group", default="santa")
    p.add_argument("--node", default="sim-runner-gpu01")
    p.add_argument("--no-state", action="store_true", help="STATE/host-orch 를 발행하지 않는다")
    p.add_argument("--vda", action="store_true", help="uagv/v2/+/+/connection 도 출력")
    p.add_argument("--start", help="Run Control/Start JSON 또는 @파일")
    p.add_argument("--n", type=int, help="Start 를 조립: 로봇 수")
    p.add_argument("--run-id", default=f"tap-{int(time.time())}")
    p.add_argument("--timeout-s", type=float, default=600.0)
    p.add_argument("--scenario-pkg", default="tap")
    p.add_argument("--stop", action="store_true")
    p.add_argument("--rebirth", action="store_true")
    p.add_argument("--wait", help="Runner/State 가 이 값이 되면 종료 (예: RUNNING, IDLE, ERROR)")
    p.add_argument("--wait-timeout", type=float, default=120.0)
    p.add_argument("--duration", type=float, help="이 시간(초) 뒤 종료. --wait 와 같이 쓰면 충족 뒤 추가 관측")
    return p


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.env_file:
        load_env_file(args.env_file)
    host = args.host or os.environ.get("MQTT_HOST") or "localhost"
    port = args.port or int(os.environ.get("MQTT_PORT") or 1883)
    key = "MQTT_PW_" + args.username.upper().replace("-", "_")
    password = os.environ.get(key)
    if not password:
        raise SystemExit(f"{key} must be set (env or --env-file)")
    return Tap(args, password).run(host, port)


if __name__ == "__main__":
    sys.exit(main())
