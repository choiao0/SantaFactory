"""NCMD `Run Control/Start` JSON → RunSpec (MQTT_CONTRACT §5.3). 순수 파싱·검증, I/O 없음.

host-orch 가 보내는 필드: run_id · scenario_pkg · n_robots · models[] · ros_domain_id · timeout_s(= window_s + 300)
· scenario · scenario_sha256.
t3_amr 에는 ROS 도메인도 로봇 시리얼도 필요 없어 받기만 하고 쓰지 않는다.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import zlib
from dataclasses import dataclass
from typing import Any

MAX_ROBOTS = 64
DEFAULT_TIMEOUT_S = 3600.0
START_MARGIN_S = 300.0                      # host-orch: timeout_s = window_s + START_MARGIN_S (SIM_VERIFY_CONTRACT §2)
MIN_WINDOW_S = 60.0
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")   # run_id: 파일명 · 토픽 · RUN_TAG 에 들어간다
# MQTT 패킷 상한 1 MB(계약 §0) 아래. 512 KiB 였는데 DES 피크 구간(-275)을 인라인으로 실으면
# 10대 295 KiB · 15대 약 440 KiB 로 차고, 28대는 넘는다 → 900 KiB. host-orch 의 같은 상한도 맞춘다.
MAX_SCENARIO_BYTES = 900 * 1024
MAX_TRAJ_BYTES = 64 * 1024 * 1024            # 궤적 풀린 크기 상한 — gzip 폭탄을 막는다 (10대 구간 1.5 MB)


def canonical_json(obj: Any) -> bytes:
    """sha 계산·파일 저장용 정규형 (키 정렬, 공백 없음). host-orch 의 canonical_json 과 같은 규칙."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def scenario_sha256(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj)).hexdigest()


@dataclass(frozen=True)
class RunSpec:
    run_id: str
    n_robots: int
    scenario_pkg: str = ""
    timeout_s: float = DEFAULT_TIMEOUT_S
    scenario: dict | None = None
    scenario_sha256: str | None = None

    @staticmethod
    def from_json(text: str) -> RunSpec:
        try:
            d = json.loads(text)
        except ValueError as e:
            raise ValueError(f"Start payload is not JSON: {e}") from None
        if not isinstance(d, dict):
            raise ValueError("Start payload must be a JSON object")
        return RunSpec.from_dict(d)

    @staticmethod
    def from_dict(d: dict) -> RunSpec:
        run_id = d.get("run_id")
        if not isinstance(run_id, str) or not SAFE_ID.match(run_id.strip()):
            raise ValueError("run_id must match [A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
        n = d.get("n_robots")
        if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= MAX_ROBOTS:
            raise ValueError(f"n_robots must be an integer in 1..{MAX_ROBOTS}")
        timeout = d.get("timeout_s", DEFAULT_TIMEOUT_S)
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
            raise ValueError("timeout_s must be a positive number")
        scenario, sha = _scenario(d.get("scenario"), d.get("scenario_sha256"))
        return RunSpec(run_id.strip(), n, str(d.get("scenario_pkg", "") or ""), float(timeout), scenario, sha)

    @property
    def seed(self) -> int | None:
        """scenario.seed — 견적 평가 시드(백엔드 FIXED_SEED). 없으면 None → 러너 기본값."""
        s = (self.scenario or {}).get("seed")
        return s if isinstance(s, int) and not isinstance(s, bool) else None

    @property
    def trajectory(self) -> str | None:
        """scenario.trajectory — FMS 가 낸 궤적 JSON 경로. 있으면 **계획을 안 한다**.

        `$W` 기준 상대경로를 권한다 (`live_pibt.py:1086` 이 절대경로가 아니면
        `$W` 를 붙인다). 절대경로도 그대로 쓰인다.

        ☹ 이게 있으면 `recorder.environment()` 가 `REPLAN` 을 **0 으로 못 박는다.**
          계획 폴더가 없어도 안 만든다 — 어차피 안 쓰기 때문이다.
        """
        t = (self.scenario or {}).get("trajectory")
        t = t.strip() if isinstance(t, str) else ""
        return t or None

    @property
    def trajectory_b64(self) -> str | None:
        """scenario.trajectory_gz_b64 — DES 피크 구간 궤적을 **메시지에 통째로** 실은 것 (-275).

        gzip 한 JSON(`fms_traj` 가 읽는 형식 + `slice` 블록)의 base64. 경로(`trajectory`)는
        파일이 GPU 박스에 미리 있어야 하지만 이건 그럴 필요가 없다. 둘 다 오면 이쪽이 이긴다.
        푸는 것은 `decode_trajectory()` 다.
        """
        t = (self.scenario or {}).get("trajectory_gz_b64")
        t = t.strip() if isinstance(t, str) else ""
        return t or None

    @property
    def order_gap_s(self) -> float | None:
        """scenario.outbound_gap_s — 출고 주문 간격(초).

        계약 §2 에 「없으면 **출고 전용**」이라고 적혀 있다. 검증 런은 견적
        지평선 안의 출고 창 한 조각만 재생하므로 `inbound_gap_s` 는 안 본다.
        None 이면 러너 기본값(`PIBT_ORDER_GAP`, 60틱)이 그대로 쓰인다.
        """
        g = (self.scenario or {}).get("outbound_gap_s")
        if isinstance(g, (int, float)) and not isinstance(g, bool) and g > 0:
            return float(g)
        return None

    @property
    def orders(self) -> dict | None:
        """scenario.orders — 백엔드가 견적 생성 시 저장한 주문 목록.

        러너가 **읽는다** (-261): 엣지가 scenario 를 `runs/<run_id>/scenario.json` 에 쓰고
        `SIM_SCENARIO_PATH` 로 넘기면 `live_pibt` 가 `fms_stream.JsonOrderStream` 으로
        rack_id → 버퍼, 수량 → 토트로 바꿔 우리 계획기로 돌린다(포장대는 우리 난수).
        ☹ 궤적(`trajectory` · `trajectory_b64`)이 오면 **궤적이 이긴다** — 궤적에는 DES 의
          배정 결과가 이미 들어 있어 주문 목록을 쓸 자리가 없다.
        """
        o = (self.scenario or {}).get("orders")
        return o if isinstance(o, dict) else None

    @property
    def window_s(self) -> float:
        """녹화 창(초). Start 에는 window_s 가 없고 timeout_s = window_s + 300 이라 거기서 되돌린다.
        scenario.window_s 가 오면 그 값이 이긴다. host-orch 가 창 끝에 Stop 을 보내므로 이 값은 상한일 뿐이다."""
        w = (self.scenario or {}).get("window_s")
        if isinstance(w, (int, float)) and not isinstance(w, bool) and w > 0:
            return float(w)
        return max(MIN_WINDOW_S, self.timeout_s - START_MARGIN_S)


def decode_trajectory(b64: str) -> tuple:
    """`scenario.trajectory_gz_b64` → (풀린 JSON 바이트, slice 블록 dict 또는 None).

    형식만 본다 — 로봇·헤딩·틱 길이가 있는 JSON 객체인지. 칸 변환·전이 검사는 러너
    (`fms_traj.load_history`)가 한다. 풀린 크기가 `MAX_TRAJ_BYTES` 를 넘으면 멈춘다.
    """
    try:
        gz = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError) as e:
        raise ValueError(f"trajectory_gz_b64 is not base64: {e}") from None
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)             # gzip 머리
    try:
        body = d.decompress(gz, MAX_TRAJ_BYTES + 1)
    except zlib.error as e:
        raise ValueError(f"trajectory_gz_b64 is not gzip: {e}") from None
    if len(body) > MAX_TRAJ_BYTES or d.unconsumed_tail:
        raise ValueError(f"trajectory too large (> {MAX_TRAJ_BYTES} B unpacked)")
    try:
        doc = json.loads(body)
    except ValueError as e:
        raise ValueError(f"trajectory is not JSON: {e}") from None
    if not isinstance(doc, dict) or not all(k in doc for k in ("dt_s", "robots", "headings")):
        raise ValueError("trajectory must be an object with dt_s · robots · headings")
    sl = doc.get("slice")
    return body, (sl if isinstance(sl, dict) else None)


def _scenario(obj: Any, given_sha: Any) -> tuple:
    """scenario 는 dict, 정규형 512 KB 이하, scenario_sha256 이 오면 일치해야 한다(전송 중 변형 검출)."""
    if obj is None:
        return None, None
    if not isinstance(obj, dict):
        raise ValueError("scenario must be a JSON object")
    raw = canonical_json(obj)
    if len(raw) > MAX_SCENARIO_BYTES:
        raise ValueError(f"scenario too large: {len(raw)} B > {MAX_SCENARIO_BYTES}")
    sha = hashlib.sha256(raw).hexdigest()
    if given_sha is not None and given_sha != sha:
        raise ValueError("scenario_sha256 mismatch — payload altered in transit")
    return obj, sha
