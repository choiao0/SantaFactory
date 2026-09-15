"""Sparkplug B 3.0 코덱 + Edge 세션(bdSeq · seq) — MQTT_CONTRACT §5.

순수 파이썬(paho 무관). 페이로드 = Eclipse Tahu `sparkplug_b.proto` 생성물(`sparkplug_b_pb2`).
BIRTH 는 이름·별칭·타입·초기값 전부, DATA 는 별칭(+이름)과 값만, DEATH 는 bdSeq 하나.
"""
from __future__ import annotations

import os
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from . import sparkplug_b_pb2 as pb

Payload = pb.Payload
DataType = pb.DataType

INT32, INT64, DOUBLE = DataType.Int32, DataType.Int64, DataType.Double
BOOLEAN, STRING, TEXT = DataType.Boolean, DataType.String, DataType.Text

SEQ_MOD = 256                      # seq · bdSeq 모두 0~255 순환
_FIELD = {INT32: "int_value", INT64: "long_value", DOUBLE: "double_value",
          BOOLEAN: "boolean_value", STRING: "string_value", TEXT: "string_value"}
_MASK = {INT32: 0xFFFF_FFFF, INT64: 0xFFFF_FFFF_FFFF_FFFF}   # 음수는 2의 보수(proto 필드가 unsigned)


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(frozen=True)
class MetricDef:
    """메트릭 사전 한 줄: 이름 · 타입 · 별칭. initial=None 이면 BIRTH 에 is_null 로 선언."""
    name: str
    dtype: int
    alias: int
    initial: Any = None


@dataclass(frozen=True)
class Metric:
    """디코드된 메트릭. DATA 는 별칭만 올 수 있어 name 이 None 일 수 있다. is_null 이면 value=None."""
    name: str | None
    alias: int | None
    value: Any


@dataclass(frozen=True)
class Decoded:
    timestamp: int
    seq: int | None
    metrics: tuple


def _set_value(m, dtype: int, value: Any) -> None:
    if value is None:
        m.is_null = True
        return
    if dtype in (INT32, INT64):
        value = int(value) & _MASK[dtype]
    elif dtype == DOUBLE:
        value = float(value)
    elif dtype == BOOLEAN:
        value = bool(value)
    else:
        value = str(value)
    setattr(m, _FIELD[dtype], value)


def _add(payload, d: MetricDef, value: Any, *, with_name: bool, with_type: bool, ts: int) -> None:
    m = payload.metrics.add()
    m.timestamp = ts
    m.alias = d.alias
    if with_name:
        m.name = d.name
    if with_type:
        m.datatype = d.dtype
    _set_value(m, d.dtype, value)


def encode_birth(seq: int, values: Iterable[tuple[MetricDef, Any]], ts: int | None = None) -> bytes:
    """NBIRTH · DBIRTH: 이름 + 별칭 + 타입 + 값(없으면 is_null). seq 필수(NBIRTH 는 0)."""
    ts = now_ms() if ts is None else ts
    p = Payload(timestamp=ts, seq=seq)
    for d, v in values:
        _add(p, d, v, with_name=True, with_type=True, ts=ts)
    return p.SerializeToString()


def encode_data(seq: int, values: Iterable[tuple[MetricDef, Any]], ts: int | None = None) -> bytes:
    """NDATA · DDATA: 바뀐 것만. 별칭 + 이름(디버그 편의) + 값, 타입 생략."""
    ts = now_ms() if ts is None else ts
    p = Payload(timestamp=ts, seq=seq)
    for d, v in values:
        _add(p, d, v, with_name=True, with_type=False, ts=ts)
    return p.SerializeToString()


def encode_death(bd_seq: int, ts: int | None = None) -> bytes:
    """NDEATH(유언): bdSeq 하나. seq 없음."""
    p = Payload(timestamp=now_ms() if ts is None else ts)
    m = p.metrics.add()
    m.name, m.datatype = "bdSeq", INT64
    m.long_value = int(bd_seq) % SEQ_MOD
    return p.SerializeToString()


def encode_ddeath(seq: int, ts: int | None = None) -> bytes:
    """DDEATH: seq 만 (메트릭 없음)."""
    return Payload(timestamp=now_ms() if ts is None else ts, seq=seq).SerializeToString()


def encode_cmd(values: Iterable[tuple[str, int, Any]], ts: int | None = None) -> bytes:
    """NCMD · DCMD (Host → Edge): (이름, 타입, 값). seq 없음."""
    p = Payload(timestamp=now_ms() if ts is None else ts)
    for name, dtype, v in values:
        m = p.metrics.add()
        m.name, m.datatype = name, dtype
        _set_value(m, dtype, v)
    return p.SerializeToString()


def _value_of(m) -> Any:
    if m.is_null:
        return None
    field = m.WhichOneof("value")
    return getattr(m, field) if field else None


def decode(payload: bytes) -> Decoded:
    p = Payload.FromString(payload)
    metrics = tuple(Metric(m.name if m.HasField("name") else None,
                           m.alias if m.HasField("alias") else None,
                           _value_of(m)) for m in p.metrics)
    return Decoded(p.timestamp, p.seq if p.HasField("seq") else None, metrics)


def metrics_by_name(d: Decoded) -> dict:
    return {m.name: m.value for m in d.metrics if m.name is not None}


class EdgeSession:
    """bdSeq(접속 회차, 파일에 보존해 재시작에도 이어짐) + seq(세션 안 발언 번호).

    접속마다 new_session() → bdSeq+1, seq=0. NDEATH 유언은 new_session() 뒤, connect 전에 건다.
    """

    def __init__(self, bdseq_path: str):
        self.path = bdseq_path
        self.bd_seq = self._load()
        self.seq = 0

    def _load(self) -> int:
        try:
            with open(self.path, encoding="ascii") as f:
                return int(f.read().strip()) % SEQ_MOD
        except (FileNotFoundError, ValueError):
            return SEQ_MOD - 1          # 첫 세션이 0 이 되도록

    def new_session(self) -> int:
        self.bd_seq = (self.bd_seq + 1) % SEQ_MOD
        self.seq = 0
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="ascii") as f:
            f.write(str(self.bd_seq))
        os.replace(tmp, self.path)
        return self.bd_seq

    def next_seq(self) -> int:
        """이번 메시지에 붙일 seq 를 돌려주고 다음 번호로 넘긴다."""
        s = self.seq
        self.seq = (self.seq + 1) % SEQ_MOD
        return s
