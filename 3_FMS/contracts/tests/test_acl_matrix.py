"""ACL 행렬 — 3_FMS/infra/emqx/acl.conf 의 허용·거부 칸을 살아 있는 브로커에 대고 고정한다 (MQTT_CONTRACT.md §3).

  cd 3_FMS && python3 -m pytest contracts/tests/test_acl_matrix.py -q

브로커 주소·계정 비밀번호는 infra/emqx/.env (MQTT_HOST · MQTT_PORT · MQTT_PW_*) 에서 읽고, 같은 이름의 환경변수가
있으면 그것이 우선한다. MQTT_ENV_FILE 로 다른 env 파일을 줄 수 있다. 브로커에 붙지 못하면 전부 skip.
거부 판정 = 브로커가 연결을 끊는다 (emqx.conf authorization.deny_action = disconnect) 그리고 관측자(host-orch)에게
아무것도 오지 않는다. 허용 판정 = PUBACK/SUBACK 정상 + 관측자 수신 + 연결 유지.
"""
from __future__ import annotations

import os
import queue
import socket
import threading
import uuid
from pathlib import Path

import pytest

mqtt = pytest.importorskip("paho.mqtt.client")

ROOT = Path(__file__).resolve().parents[2]  # 3_FMS/
ENV_FILE = Path(os.environ.get("MQTT_ENV_FILE", ROOT / "infra" / "emqx" / ".env"))
WAIT_S = 3.0          # CONNACK · SUBACK · PUBACK · 관측 수신 대기
QUIET_S = 1.0         # 거부 칸에서 "아무것도 안 온다" 를 확인하는 시간
MFR = "idealworks"


def _load_env() -> dict:
    cfg = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip().strip('"').strip("'")
    cfg.update({k: v for k, v in os.environ.items() if k.startswith("MQTT_")})
    return cfg


CFG = _load_env()
HOST, PORT = CFG.get("MQTT_HOST", "localhost"), int(CFG.get("MQTT_PORT", "1883"))
PW = {"amr": CFG.get("MQTT_PW_AMR"), "fms-core": CFG.get("MQTT_PW_FMS_CORE"),
      "sim-runner-gpu01": CFG.get("MQTT_PW_SIM_RUNNER"), "host-orch": CFG.get("MQTT_PW_HOST_ORCH"),
      "sim-wms": CFG.get("MQTT_PW_SIM_WMS")}


def pw_of(user: str) -> str:
    return PW["amr"] if user.startswith("amr") else PW[user]


def _broker_reachable() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=1.0):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _broker_reachable() or any(v is None for v in PW.values()),
    reason=f"브로커 {HOST}:{PORT} 없음 또는 {ENV_FILE} 의 MQTT_PW_* 미설정")


class Cli:
    """paho 2.x · MQTT 3.1.1 · clean session. 판정에 쓰는 이벤트만 모은다."""

    def __init__(self, user, password=None, will=None, keepalive=5):
        self.user = user
        cid = f"aclmx-{user or 'anon'}-{uuid.uuid4().hex[:6]}"
        self.c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cid,
                             protocol=mqtt.MQTTv311, clean_session=True)
        if user is not None:
            self.c.username_pw_set(user, password)
        if will:
            self.c.will_set(*will)
        self.conn_rc = None
        self.connected, self.disconnected = threading.Event(), threading.Event()
        self.msgs, self.subacks, self.pubacks = queue.Queue(), queue.Queue(), queue.Queue()
        self.c.on_connect = self._on_connect
        self.c.on_disconnect = self._on_disconnect
        self.c.on_message = lambda _c, _u, m: self.msgs.put(m)
        self.c.on_subscribe = lambda _c, _u, _mid, rcs, _p=None: self.subacks.put(list(rcs))
        self.c.on_publish = lambda _c, _u, mid, _rc=None, _p=None: self.pubacks.put(mid)
        self.c.reconnect_delay_set(60, 60)  # 끊긴 뒤 자동 재접속이 판정을 흐리지 않게
        self.c.connect_async(HOST, PORT, keepalive)
        self.c.loop_start()

    def _on_connect(self, _c, _u, _f, rc, _p=None):
        self.conn_rc = rc
        self.connected.set()

    def _on_disconnect(self, _c, _u, _f, rc, _p=None):
        self.disconnected.set()

    def connack(self):
        assert self.connected.wait(WAIT_S), f"{self.user}: CONNACK 없음"
        return self.conn_rc

    def sub(self, topic, qos=1):
        self.c.subscribe(topic, qos)
        try:
            return self.subacks.get(timeout=WAIT_S)
        except queue.Empty:
            return None

    def pub(self, topic, payload, qos=1, retain=False) -> bool:
        """True = PUBACK 수신 (브로커가 받았다)."""
        self.c.publish(topic, payload, qos=qos, retain=retain)
        try:
            self.pubacks.get(timeout=WAIT_S)
            return True
        except queue.Empty:
            return False

    def recv(self, timeout=WAIT_S):
        try:
            return self.msgs.get(timeout=timeout)
        except queue.Empty:
            return None

    def kicked(self, timeout=WAIT_S) -> bool:
        return self.disconnected.wait(timeout)

    def close(self):
        self.c.loop_stop()
        self.c.disconnect()

    def abrupt(self):
        """DISCONNECT 없이 소켓만 닫는다 → 브로커가 유언(LWT)을 내야 한다."""
        try:
            self.c.socket().close()
        finally:
            self.c.loop_stop()


def login(user, password=None, **kw) -> Cli:
    c = Cli(user, password if password is not None else pw_of(user), **kw)
    rc = c.connack()
    assert rc == 0, f"{user}: 접속 거부 {rc}"
    return c


@pytest.fixture
def observer():
    """host-orch 로 세 레인을 전부 구독한 관측 창."""
    o = login("host-orch")
    for t in ("uagv/v2/+/+/#", "spBv1.0/#", "biz/v1/#"):
        rcs = o.sub(t, 1)
        assert rcs and rcs[0] < 128, f"관측자 구독 실패 {t}: {rcs}"
    yield o
    o.close()


def clear_retained(topic: str, user: str):
    c = login(user)
    c.pub(topic, b"", qos=1, retain=True)
    c.close()


# ── 접속 ───────────────────────────────────────────────────────────────────────
def test_anonymous_rejected():
    c = Cli(None)
    rc = c.connack()
    c.close()
    assert rc != 0, "익명 접속이 허용됐다"


def test_wrong_password_rejected():
    c = Cli("amr01", "definitely-wrong")
    rc = c.connack()
    c.close()
    assert rc != 0


# ── 행렬: (사용자, 동작, 토픽, retain, 허용?) — MQTT_CONTRACT §3 표와 1:1 ───────
A = f"uagv/v2/{MFR}/amr01"
B = f"uagv/v2/{MFR}/amr02"
MATRIX = [
    # 에이전트 amr01
    ("amr01", "pub", f"{A}/state", False, True),
    ("amr01", "pub", f"{A}/visualization", False, True),
    ("amr01", "pub", f"{A}/connection", True, True),
    ("amr01", "pub", f"{A}/factsheet", True, True),
    ("amr01", "pub", f"{A}/state", True, False),                       # retained state 금지
    ("amr01", "pub", f"{B}/state", False, False),                      # 남의 시리얼
    ("amr01", "pub", "spBv1.0/santa/NDATA/sim-runner-gpu01", False, False),
    ("amr01", "pub", "biz/v1/event", False, False),
    ("amr01", "sub", f"{A}/order", None, True),
    ("amr01", "sub", f"{A}/instantActions", None, True),
    ("amr01", "sub", f"{B}/order", None, False),
    ("amr01", "sub", "uagv/v2/+/+/state", None, False),
    # fms-core
    ("fms-core", "pub", f"{A}/order", False, True),
    ("fms-core", "pub", f"{A}/instantActions", False, True),
    ("fms-core", "pub", f"{A}/order", True, False),                    # order 는 retained 금지
    ("fms-core", "pub", "biz/v1/event", False, True),
    ("fms-core", "pub", "biz/v1/order", False, False),                 # 주문은 WMS 만 낸다
    ("fms-core", "pub", "spBv1.0/santa/NBIRTH/fms-core", False, True),
    ("fms-core", "pub", "spBv1.0/santa/NCMD/sim-runner-gpu01", False, False),
    ("fms-core", "sub", "uagv/v2/+/+/state", None, True),
    ("fms-core", "sub", "uagv/v2/+/+/factsheet", None, True),
    ("fms-core", "sub", "biz/v1/order", None, True),
    ("fms-core", "sub", "spBv1.0/santa/NCMD/fms-core", None, True),
    ("fms-core", "sub", "spBv1.0/#", None, False),
    # sim-runner
    ("sim-runner-gpu01", "pub", "spBv1.0/santa/NBIRTH/sim-runner-gpu01", False, True),
    ("sim-runner-gpu01", "pub", "spBv1.0/santa/DDATA/sim-runner-gpu01/amr01", False, True),
    ("sim-runner-gpu01", "pub", f"{A}/order", False, False),
    ("sim-runner-gpu01", "pub", "spBv1.0/santa/NCMD/sim-runner-gpu01", False, False),
    ("sim-runner-gpu01", "sub", "spBv1.0/santa/NCMD/sim-runner-gpu01", None, True),
    ("sim-runner-gpu01", "sub", "uagv/v2/+/+/state", None, True),
    ("sim-runner-gpu01", "sub", "biz/v1/#", None, False),
    # host-orch
    ("host-orch", "pub", "spBv1.0/STATE/host-orch", True, True),
    ("host-orch", "pub", "spBv1.0/santa/NCMD/sim-runner-gpu01", False, True),
    ("host-orch", "pub", "spBv1.0/santa/NCMD/sim-runner-gpu01", True, False),
    ("host-orch", "pub", f"{A}/order", False, False),
    ("host-orch", "pub", "biz/v1/order", False, False),
    ("host-orch", "sub", "spBv1.0/#", None, True),
    ("host-orch", "sub", "biz/v1/#", None, True),
    ("host-orch", "sub", "uagv/v2/+/+/#", None, True),
    # sim-wms
    ("sim-wms", "pub", "biz/v1/order", False, True),
    ("sim-wms", "pub", "biz/v1/order", True, False),
    ("sim-wms", "pub", "biz/v1/event", False, False),
    ("sim-wms", "sub", "biz/v1/event", None, True),
    ("sim-wms", "sub", "spBv1.0/#", None, False),
    ("sim-wms", "sub", "uagv/v2/+/+/state", None, False),
]
IDS = [f"{u}-{a}-{t}{'-retained' if r else ''}-{'allow' if e else 'deny'}" for u, a, t, r, e in MATRIX]


@pytest.mark.parametrize("user,action,topic,retain,allowed", MATRIX, ids=IDS)
def test_acl_matrix(observer, user, action, topic, retain, allowed):
    c = login(user)
    try:
        if action == "pub":
            payload = f"aclmx {uuid.uuid4().hex}".encode()
            acked = c.pub(topic, payload, qos=1, retain=bool(retain))
            if allowed:
                assert acked, "PUBACK 없음"
                seen = observer.recv()
                assert seen is not None and seen.payload == payload, "관측자가 못 받았다"
                assert not c.kicked(0.5), "허용 칸인데 연결이 끊겼다"
                if retain:
                    clear_retained(topic, user)
            else:
                assert c.kicked(), "거부 칸인데 연결이 유지된다 (deny_action = disconnect 확인)"
                assert observer.recv(QUIET_S) is None, "거부됐는데 관측자에게 도착했다"
        else:
            rcs = c.sub(topic, 1)
            if allowed:
                assert rcs and rcs[0] < 128, f"SUBACK 실패 {rcs}"
                assert not c.kicked(0.5), "허용 칸인데 연결이 끊겼다"
            else:
                assert c.kicked() or (rcs and rcs[0] >= 128), f"거부돼야 하는데 SUBACK {rcs} 이고 연결 유지"
    finally:
        c.close()


# ── retained · LWT · QoS 상한 ─────────────────────────────────────────────────
def test_retained_connection_reaches_late_subscriber():
    a = login("amr01")
    payload = b'{"connectionState":"ONLINE","serialNumber":"amr01"}'
    assert a.pub(f"{A}/connection", payload, qos=1, retain=True)
    a.close()
    late = login("fms-core")
    try:
        assert late.sub("uagv/v2/+/+/connection", 1)[0] < 128
        m = late.recv()
        assert m is not None and m.payload == payload and m.retain, "늦은 구독자가 retained 를 못 받았다"
    finally:
        late.close()
        clear_retained(f"{A}/connection", "amr01")


def test_lwt_connectionbroken_on_abrupt_close(observer):
    will = (f"{A}/connection", b'{"connectionState":"CONNECTIONBROKEN"}', 1, True)
    a = login("amr01", will=will, keepalive=5)
    a.abrupt()
    try:
        got = None
        for _ in range(3):  # 관측자 큐에 다른 잔여물이 있어도 유언을 찾는다
            m = observer.recv()
            if m is not None and m.topic == will[0] and b"CONNECTIONBROKEN" in m.payload:
                got = m
                break
        assert got is not None, "소켓 단절 뒤 CONNECTIONBROKEN 유언이 오지 않았다"
    finally:
        clear_retained(f"{A}/connection", "amr01")


def test_qos2_publish_rejected():
    a = login("amr01")
    try:
        acked = a.pub(f"{A}/state", b"{}", qos=2)
        assert not acked or a.kicked(), "QoS 2 발행이 통과했다 (mqtt.max_qos_allowed = 1)"
    finally:
        a.close()
