"""VDA 5050 state · connection → Sparkplug Device 메트릭 거울 + RTF 추정 (MQTT_CONTRACT §5.2 Device amr01…).

sim-runner 는 `uagv/v2/+/+/{state,connection}` 만 구독한다(ACL). factsheet 는 못 보므로 Robot/Model 은
Start 명령의 models[] 에서 온다. 변화 임계(0.05 m · 0.05 rad · 1 %)는 마지막으로 *보고한* 값 기준이라 드리프트가 누적된다.
"""
from __future__ import annotations

import json
import math
import statistics
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Optional

POSE_EPS_M = 0.05
YAW_EPS_RAD = 0.05
BATTERY_EPS_PCT = 1.0
RTF_WINDOW_S = 10.0
RTF_MIN_SPAN_S = 1.0
CONNECTION_STATES = ("ONLINE", "OFFLINE", "CONNECTIONBROKEN")

MODEL, CONNECTION, LAST_NODE = "Robot/Model", "Robot/Connection", "Robot/LastNodeId"
POSE_X, POSE_Y, YAW, BATTERY, AMCL_ERR = "Robot/PoseX", "Robot/PoseY", "Robot/Yaw", "Robot/Battery", "Robot/AmclErr"
DEVICE_METRIC_NAMES = (MODEL, CONNECTION, LAST_NODE, POSE_X, POSE_Y, YAW, BATTERY, AMCL_ERR)


def parse_vda_topic(topic: str) -> Optional[tuple[str, str, str]]:
    """'uagv/v2/{manufacturer}/{serial}/{name}' → (manufacturer, serial, name), 아니면 None."""
    parts = topic.split("/")
    if len(parts) != 5 or parts[0] != "uagv" or parts[1] != "v2":
        return None
    return parts[2], parts[3], parts[4]


def parse_iso_s(ts: Any) -> Optional[float]:
    """VDA timestamp(ISO 8601, 'Z' 접미) → epoch 초. 형식이 아니면 None."""
    if not isinstance(ts, str) or not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def wrap_angle(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def _float(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _dict(v: Any) -> dict:
    return v if isinstance(v, dict) else {}


@dataclass
class RobotMirror:
    serial: str
    model: str = ""
    connection: str = ""
    last_node_id: str = ""
    x: Optional[float] = None
    y: Optional[float] = None
    yaw: Optional[float] = None
    battery: Optional[float] = None
    _reported: dict = field(default_factory=dict)
    _rtf: deque = field(default_factory=deque)

    def values(self) -> dict[str, Any]:
        return {MODEL: self.model, CONNECTION: self.connection, LAST_NODE: self.last_node_id,
                POSE_X: self.x, POSE_Y: self.y, YAW: self.yaw, BATTERY: self.battery, AMCL_ERR: None}

    def birth_values(self) -> dict[str, Any]:
        """DBIRTH 용 전체값. 지금 값을 전부 '보고함' 으로 표시한다."""
        v = self.values()
        self._reported = dict(v)
        return v

    def update_connection(self, msg: dict) -> list[str]:
        state = msg.get("connectionState")
        if state not in CONNECTION_STATES:
            return []
        self.connection = state
        return self._delta([(CONNECTION, state, None)])

    def update_state(self, msg: dict, wall_s: float) -> list[str]:
        node = msg.get("lastNodeId")
        self.last_node_id = node if isinstance(node, str) else self.last_node_id
        pos = _dict(msg.get("agvPosition"))
        self.x = _float(pos.get("x")) if _float(pos.get("x")) is not None else self.x
        self.y = _float(pos.get("y")) if _float(pos.get("y")) is not None else self.y
        self.yaw = _float(pos.get("theta")) if _float(pos.get("theta")) is not None else self.yaw
        charge = _float(_dict(msg.get("batteryState")).get("batteryCharge"))
        self.battery = charge if charge is not None else self.battery
        self._sample_rtf(wall_s, parse_iso_s(msg.get("timestamp")))
        return self._delta([(LAST_NODE, self.last_node_id, None), (POSE_X, self.x, POSE_EPS_M),
                            (POSE_Y, self.y, POSE_EPS_M), (YAW, self.yaw, YAW_EPS_RAD),
                            (BATTERY, self.battery, BATTERY_EPS_PCT)])

    def _delta(self, items: Iterable[tuple[str, Any, Optional[float]]]) -> list[str]:
        """보고값과 임계 이상 다른 것만 골라 보고값을 갱신하고 이름을 돌려준다. 포즈는 한쪽만 바뀌어도 x·y 같이."""
        changed = [name for name, value, eps in items if value is not None and self._differs(name, value, eps)]
        if POSE_X in changed or POSE_Y in changed:
            changed = [n for n in changed if n not in (POSE_X, POSE_Y)] + [POSE_X, POSE_Y]
        for name in changed:
            self._reported[name] = self.values()[name]
        return changed

    def _differs(self, name: str, value: Any, eps: Optional[float]) -> bool:
        old = self._reported.get(name)
        if old is None:
            return True
        if eps is None:
            return value != old
        diff = wrap_angle(value - old) if name == YAW else value - old
        return abs(diff) >= eps

    def _sample_rtf(self, wall_s: float, sim_s: Optional[float]) -> None:
        if sim_s is None:
            return
        self._rtf.append((wall_s, sim_s))
        while self._rtf and wall_s - self._rtf[0][0] > RTF_WINDOW_S:
            self._rtf.popleft()

    def rtf(self) -> Optional[float]:
        """창(10 s) 안 첫·끝 표본의 Δsim/Δwall. 벽시계 폭이 1 s 미만이면 None."""
        if len(self._rtf) < 2:
            return None
        (w0, s0), (w1, s1) = self._rtf[0], self._rtf[-1]
        if w1 - w0 < RTF_MIN_SPAN_S:
            return None
        return (s1 - s0) / (w1 - w0)


class Fleet:
    """런 하나의 로봇 거울 묶음. 런마다 새로 만든다(옛 retained 를 이어받지 않기 위해)."""

    def __init__(self, robots: Iterable[tuple[str, str]]):
        self.robots = {serial: RobotMirror(serial, model) for serial, model in robots}

    def handle(self, topic: str, payload: bytes, wall_s: float) -> Optional[tuple[str, list[str]]]:
        """VDA 메시지 하나를 반영. (serial, 바뀐 메트릭 이름들) 또는 무관/깨진 메시지면 None."""
        parsed = parse_vda_topic(topic)
        if parsed is None or parsed[1] not in self.robots:
            return None
        try:
            msg = json.loads(payload)
        except (ValueError, UnicodeDecodeError):
            return None
        if not isinstance(msg, dict):
            return None
        robot = self.robots[parsed[1]]
        if parsed[2] == "connection":
            return parsed[1], robot.update_connection(msg)
        if parsed[2] == "state":
            return parsed[1], robot.update_state(msg, wall_s)
        return None

    def online(self) -> list[str]:
        return [s for s, r in self.robots.items() if r.connection == "ONLINE"]

    def all_online(self) -> bool:
        return len(self.online()) == len(self.robots)

    def rtf(self) -> Optional[float]:
        samples = [v for v in (r.rtf() for r in self.robots.values()) if v is not None]
        return statistics.median(samples) if samples else None
