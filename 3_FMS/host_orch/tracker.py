"""Sparkplug B Primary Host 상태 추적 — 노드·디바이스 메트릭, seq/bdSeq 검사 (MQTT_CONTRACT §5.4 의 Host 쪽).

NBIRTH 로 노드 상태를 통째로 새로 만들고, N/D DATA 는 델타만 덮어쓴다. seq 가 끊기면 needs_rebirth 를 켜고
(발송은 orchestrator 가 한다), NDEATH 는 bdSeq 가 마지막 NBIRTH 와 같을 때만 인정한다. 순수 파이썬.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from . import spb

BDSEQ = "bdSeq"
SEQ_MOD = spb.SEQ_MOD
REBIRTH_MIN_INTERVAL_S = 5.0


@dataclass
class Device:
    id: str
    alive: bool = True
    metrics: dict = field(default_factory=dict)


@dataclass
class Node:
    id: str
    online: bool = False
    bd_seq: Optional[int] = None
    seq: Optional[int] = None
    metrics: dict = field(default_factory=dict)
    aliases: dict = field(default_factory=dict)
    devices: dict = field(default_factory=dict)
    last_seen: float = 0.0
    needs_rebirth: bool = False
    rebirth_requested_at: float = -1e9

    def get(self, name: str, default: Any = None) -> Any:
        return self.metrics.get(name, default)

    def alive_devices(self) -> list:
        return [d.id for d in self.devices.values() if d.alive]


@dataclass(frozen=True)
class Event:
    kind: str                      # nbirth ndeath ndata dbirth ddata ddeath seq_gap stale_death unknown_node
    node: str
    device: Optional[str] = None
    changed: tuple = ()


def parse_topic(topic: str, group: str) -> Optional[tuple]:
    """spBv1.0/{group}/{kind}/{node}[/{device}] → (kind, node, device)."""
    parts = topic.split("/")
    if len(parts) not in (4, 5) or parts[0] != "spBv1.0" or parts[1] != group:
        return None
    return parts[2], parts[3], parts[4] if len(parts) == 5 else None


class HostTracker:
    def __init__(self, group: str = "santa"):
        self.group = group
        self.nodes: dict = {}

    def node(self, node_id: str) -> Optional[Node]:
        return self.nodes.get(node_id)

    def handle(self, topic: str, payload: bytes, now: float) -> list:
        parsed = parse_topic(topic, self.group)
        if parsed is None or parsed[0] in ("NCMD", "DCMD"):
            return []
        kind, node_id, device = parsed
        try:
            d = spb.decode(payload)
        except Exception:  # noqa: BLE001 — 깨진 protobuf 는 무시
            return []
        if kind == "NBIRTH":
            return [self._nbirth(node_id, d, now)]
        if kind == "NDEATH":
            return [self._ndeath(node_id, d)]
        node = self.nodes.get(node_id)
        if node is None or not node.online:
            node = self.nodes.setdefault(node_id, Node(node_id))
            node.needs_rebirth = True
            return [Event("unknown_node", node_id)]
        events = self._check_seq(node, d.seq)
        node.last_seen = now
        if kind == "NDATA":
            events.append(Event("ndata", node_id, changed=self._apply(node, node.metrics, d)))
        elif kind == "DBIRTH" and device:
            dev = node.devices[device] = Device(device)
            events.append(Event("dbirth", node_id, device, self._apply(node, dev.metrics, d)))
        elif kind == "DDATA" and device:
            dev = node.devices.setdefault(device, Device(device))
            events.append(Event("ddata", node_id, device, self._apply(node, dev.metrics, d)))
        elif kind == "DDEATH" and device:
            if device in node.devices:
                node.devices[device].alive = False
            events.append(Event("ddeath", node_id, device))
        return events

    def _nbirth(self, node_id: str, d: spb.Decoded, now: float) -> Event:
        node = self.nodes.setdefault(node_id, Node(node_id))
        node.online, node.seq, node.last_seen, node.needs_rebirth = True, d.seq, now, False
        node.metrics, node.aliases, node.devices = {}, {}, {}
        self._apply(node, node.metrics, d)
        bd = node.metrics.get(BDSEQ)
        node.bd_seq = int(bd) % SEQ_MOD if isinstance(bd, int) else None
        return Event("nbirth", node_id)

    def _ndeath(self, node_id: str, d: spb.Decoded) -> Event:
        node = self.nodes.get(node_id)
        bd = spb.metrics_by_name(d).get(BDSEQ)
        if node is None or not node.online or bd != node.bd_seq:
            return Event("stale_death", node_id)
        node.online = False
        for dev in node.devices.values():
            dev.alive = False
        return Event("ndeath", node_id)

    def _check_seq(self, node: Node, seq: Optional[int]) -> list:
        if seq is None:
            return []
        expected = ((node.seq if node.seq is not None else -1) + 1) % SEQ_MOD
        node.seq = seq
        if seq == expected:
            return []
        node.needs_rebirth = True
        return [Event("seq_gap", node.id)]

    def _apply(self, node: Node, target: dict, d: spb.Decoded) -> tuple:
        changed = []
        for m in d.metrics:
            name = m.name if m.name is not None else node.aliases.get(m.alias, f"#{m.alias}")
            if m.name is not None and m.alias is not None:
                node.aliases[m.alias] = m.name
            target[name] = m.value
            changed.append(name)
        return tuple(changed)

    def rebirth_due(self, node_id: str, now: float) -> bool:
        """needs_rebirth 이고 최근 요청 뒤 REBIRTH_MIN_INTERVAL_S 지났으면 True 로 하고 시각을 기록."""
        node = self.nodes.get(node_id)
        if node is None or not node.needs_rebirth or now - node.rebirth_requested_at < REBIRTH_MIN_INTERVAL_S:
            return False
        node.rebirth_requested_at = now
        return True
