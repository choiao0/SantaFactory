"""VDA 5050 2.0.0 마스터 쪽 — 로봇별 order 스티칭 · instantActions · state/connection 거울 (MQTT_CONTRACT §4).

order 규약(1_Robot/amr_agent vda5050/order.py 가 수용자): 노드 sequenceId 짝수 · 엣지 홀수, 갱신은 마지막 base 노드에서 시작,
같은 orderUpdateId 재발행은 무시(오류 없음), 낮으면 orderUpdateError. 런당 로봇당 orderId 하나, 틱마다 노드 하나를
released 로 덧붙인다(orderUpdateId = k = 지금까지 보낸 노드 번호). 도착 = state.lastNodeId == n_k (orderUpdateId ≥ k).
재발행 규칙(§4.3 결정 10): 보낸 뒤 state 2건이 와도 orderUpdateId 가 안 오르면 같은 order 재발행, 10건이면 로봇 오류.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from .world import wrap

VERSION = "2.0.0"
DEV_XY_M, DEV_THETA_RAD = 0.1, 0.087           # allowedDeviation — 에이전트 stop 허용(0.05 m · 0.03 rad)의 상한일 뿐
CONNECTION_STATES = ("ONLINE", "OFFLINE", "CONNECTIONBROKEN")
RESEND_AFTER_STATES, ERROR_AFTER_STATES = 2, 10


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_vda_topic(topic: str) -> Optional[tuple]:
    """'uagv/v2/{manufacturer}/{serial}/{name}' → (manufacturer, serial, name), 아니면 None."""
    parts = topic.split("/")
    if len(parts) != 5 or parts[0] != "uagv" or parts[1] != "v2":
        return None
    return parts[2], parts[3], parts[4]


def vda_topic(manufacturer: str, serial: str, name: str) -> str:
    return f"uagv/v2/{manufacturer}/{serial}/{name}"


def _float(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


@dataclass(frozen=True)
class NodeRef:
    node_id: str
    seq: int
    x: float
    y: float
    theta: float


@dataclass
class RobotLink:
    """로봇 하나의 VDA 상태 + order 빌더. 관측(state/connection)과 발송(order/instantActions)을 같이 든다."""
    serial: str
    manufacturer: str
    order_id: str
    map_id: str = ""
    header_id: int = 0
    action_seq: int = 0
    # 발송 쪽
    k: int = -1                         # 마지막으로 보낸 노드 번호 (n_k) — -1 = 아직 order 없음
    last_node: Optional[NodeRef] = None
    last_msg: Optional[dict] = None     # 재발행용 마지막 order 본문
    pending: Optional[int] = None       # 도착을 기다리는 노드 번호 k
    sent_at: float = 0.0                # 이 노드를 처음 보낸 시각 — 재발행해도 안 바뀐다 (도착 상한의 기준)
    states_since_send: int = 0          # 이 노드를 보낸 뒤 온 state 수 — 재발행해도 안 바뀐다 (10건 → 오류의 기준)
    resends: int = 0
    resent_at: int = 0                  # 마지막 재발행 때의 states_since_send
    # 관측 쪽
    connection: str = ""
    x: Optional[float] = None
    y: Optional[float] = None
    yaw: Optional[float] = None
    order_update_id: int = -1
    last_node_id: str = ""
    errors: list = field(default_factory=list)
    last_state_at: float = 0.0
    state_count: int = 0

    # ---- 관측 ------------------------------------------------------------------
    @property
    def has_pose(self) -> bool:
        return self.x is not None and self.y is not None and self.yaw is not None

    @property
    def online(self) -> bool:
        return self.connection == "ONLINE"

    def on_connection(self, msg: dict) -> None:
        st = msg.get("connectionState")
        if st in CONNECTION_STATES:
            self.connection = st

    def on_state(self, msg: dict, now: float) -> None:
        pos = msg.get("agvPosition")
        if isinstance(pos, dict):
            x, y, th = _float(pos.get("x")), _float(pos.get("y")), _float(pos.get("theta"))
            if x is not None and y is not None:
                self.x, self.y = x, y
            if th is not None:
                self.yaw = th
            if isinstance(pos.get("mapId"), str) and pos["mapId"]:
                self.map_id = pos["mapId"]
        node = msg.get("lastNodeId")
        if isinstance(node, str):
            self.last_node_id = node
        if msg.get("orderId") == self.order_id:
            upd = msg.get("orderUpdateId")
            if isinstance(upd, int) and not isinstance(upd, bool):
                self.order_update_id = upd
        errs = msg.get("errors")
        self.errors = [e for e in errs if isinstance(e, dict)] if isinstance(errs, list) else []
        self.last_state_at, self.state_count = now, self.state_count + 1
        if self.pending is not None:
            self.states_since_send += 1

    def fatal_error(self) -> Optional[str]:
        """에이전트 오류 중 런을 접어야 하는 것: FATAL(primitiveError) 또는 우리 order 를 거절한 orderError/orderUpdateError."""
        for e in self.errors:
            level, kind = str(e.get("errorLevel", "")).upper(), str(e.get("errorType", ""))
            if level == "FATAL" or kind in ("orderError", "orderUpdateError"):
                return f"{kind}: {e.get('errorDescription', '')}"[:200]
        return None

    # ---- 도착 · 재발행 판정 -------------------------------------------------------
    @property
    def reflected(self) -> bool:
        return self.pending is None or self.order_update_id >= self.pending

    @property
    def arrived(self) -> bool:
        return self.pending is not None and self.reflected and self.last_node_id == f"n{self.pending}"

    def settle(self) -> None:
        """도착 확인 뒤 대기 해제."""
        self.pending, self.states_since_send, self.resent_at = None, 0, 0

    def resend_due(self) -> bool:
        """마지막 (재)발행 뒤 state 2건이 왔는데도 미반영. 카운터는 계속 올라가 10건에서 unreflected_error 가 잡는다."""
        return (self.pending is not None and not self.reflected
                and self.states_since_send - self.resent_at >= RESEND_AFTER_STATES)

    def unreflected_error(self) -> bool:
        return self.pending is not None and not self.reflected and self.states_since_send >= ERROR_AFTER_STATES

    # ---- 발송 ------------------------------------------------------------------
    def _header(self) -> dict:
        self.header_id += 1
        return {"headerId": self.header_id, "timestamp": now_iso(), "version": VERSION,
                "manufacturer": self.manufacturer, "serialNumber": self.serial}

    @staticmethod
    def _node_dict(n: NodeRef, map_id: str) -> dict:
        return {"nodeId": n.node_id, "sequenceId": n.seq, "released": True,
                "nodePosition": {"x": n.x, "y": n.y, "theta": n.theta, "mapId": map_id,
                                 "allowedDeviationXY": DEV_XY_M, "allowedDeviationTheta": DEV_THETA_RAD},
                "actions": []}

    def initial_order(self, x: float, y: float, yaw: float, now: float) -> dict:
        """orderUpdateId 0: 로봇의 현재 포즈가 n0 (에이전트는 첫 노드가 0.5 m 안이어야 받는다). 도착 대기 없음."""
        theta = round(yaw / (math.pi / 2)) * (math.pi / 2)
        self.k, self.last_node = 0, NodeRef("n0", 0, x, y, wrap(theta))
        msg = {**self._header(), "orderId": self.order_id, "orderUpdateId": 0,
               "nodes": [self._node_dict(self.last_node, self.map_id)], "edges": []}
        self.last_msg, self.pending, self.sent_at = msg, None, now
        self.states_since_send, self.resends, self.resent_at = 0, 0, 0
        return msg

    def next_order(self, x: float, y: float, theta: float, reverse: bool, now: float) -> dict:
        """orderUpdateId k+1: [n_k(마지막 base), n_{k+1}] + e_k. 회전(같은 좌표)은 length 0, 후진은 orientation π."""
        assert self.last_node is not None, "initial_order first"
        prev, k1 = self.last_node, self.k + 1
        node = NodeRef(f"n{k1}", 2 * k1, x, y, theta)
        length = math.hypot(x - prev.x, y - prev.y)
        edge = {"edgeId": f"e{self.k}", "sequenceId": 2 * self.k + 1, "released": True,
                "startNodeId": prev.node_id, "endNodeId": node.node_id, "orientationType": "TANGENTIAL",
                "length": round(length, 3), "actions": []}
        if reverse:
            edge["orientation"] = math.pi
        msg = {**self._header(), "orderId": self.order_id, "orderUpdateId": k1,
               "nodes": [self._node_dict(prev, self.map_id), self._node_dict(node, self.map_id)], "edges": [edge]}
        self.k, self.last_node, self.last_msg = k1, node, msg
        self.pending, self.sent_at = k1, now
        self.states_since_send, self.resends, self.resent_at = 0, 0, 0
        return msg

    def resend(self, now: float) -> dict:
        """같은 orderUpdateId 재발행 (에이전트는 duplicate 로 무시하고 state 만 다시 낸다). sent_at · states_since_send 는 그대로 —
        재발행이 도착 상한(ack_timeout)과 10건 오류를 미루면 안 된다 (리뷰 2026-09-09)."""
        assert self.last_msg is not None
        msg = {**self.last_msg, **self._header()}
        self.last_msg, self.resends, self.resent_at = msg, self.resends + 1, self.states_since_send
        return msg

    def cancel_order(self) -> dict:
        self.action_seq += 1
        return {**self._header(), "actions": [{"actionType": "cancelOrder", "actionId": f"cancel-{self.action_seq}",
                                               "blockingType": "HARD"}]}


class Fleet:
    """serial → RobotLink. MQTT 토픽을 로봇에 배분한다. 모르는 serial 은 무시."""

    def __init__(self, robots: list, order_prefix: str):
        self.robots: dict = {serial: RobotLink(serial, mfr, f"{order_prefix}-{serial}") for serial, mfr in robots}

    def handle(self, topic: str, payload: bytes) -> Optional[tuple]:
        """(serial, 'state'|'connection', msg) 또는 None. JSON 이 아니면 None."""
        parsed = parse_vda_topic(topic)
        if parsed is None or parsed[1] not in self.robots or parsed[2] not in ("state", "connection"):
            return None
        try:
            msg = json.loads(payload)
        except (ValueError, UnicodeDecodeError):
            return None
        if not isinstance(msg, dict):
            return None
        return parsed[1], parsed[2], msg

    def all_ready(self) -> bool:
        return all(r.online and r.has_pose for r in self.robots.values())

    def online(self) -> int:
        return sum(1 for r in self.robots.values() if r.online)

    def pending(self) -> list:
        return [r for r in self.robots.values() if r.pending is not None]
