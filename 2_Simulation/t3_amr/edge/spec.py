"""NCMD `Run Control/Start` JSON → RunSpec (MQTT_CONTRACT §5.3). 순수 파싱·검증, I/O 없음.

host-orch 가 보내는 필드: run_id · scenario_pkg · n_robots · models[] · ros_domain_id · timeout_s(= window_s + 300)
· scenario · scenario_sha256.
t3_amr 에는 ROS 도메인도 로봇 시리얼도 필요 없어 받기만 하고 쓰지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

MAX_ROBOTS = 64
DEFAULT_TIMEOUT_S = 3600.0
START_MARGIN_S = 300.0                      # host-orch: timeout_s = window_s + START_MARGIN_S (SIM_VERIFY_CONTRACT §2)
MIN_WINDOW_S = 60.0
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")   # run_id: 파일명 · 토픽 · RUN_TAG 에 들어간다
MAX_SCENARIO_BYTES = 512 * 1024              # MQTT 패킷 상한 1 MB(계약 §0) 아래


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
    def window_s(self) -> float:
        """녹화 창(초). Start 에는 window_s 가 없고 timeout_s = window_s + 300 이라 거기서 되돌린다.
        scenario.window_s 가 오면 그 값이 이긴다. host-orch 가 창 끝에 Stop 을 보내므로 이 값은 상한일 뿐이다."""
        w = (self.scenario or {}).get("window_s")
        if isinstance(w, (int, float)) and not isinstance(w, bool) and w > 0:
            return float(w)
        return max(MIN_WINDOW_S, self.timeout_s - START_MARGIN_S)


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
