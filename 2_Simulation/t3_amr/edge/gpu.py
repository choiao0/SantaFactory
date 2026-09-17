"""Start 직전 GPU 프로브 (-241).

왜: docker(systemd cgroup 드라이버, cgroup v2)는 systemd daemon-reload — unattended-upgrade 가 흔히 부른다 — 가 오면
상주 컨테이너의 device cgroup 을 다시 적용하는데, nvidia 훅이 넣어 준 /dev/nvidia* 허용은 그때 사라진다. 컨테이너는
살아 있고 장치 파일도 보이지만 열리지 않아 NVML 이 999(Unknown Error), Vulkan 이 INCOMPATIBLE_DRIVER 를 낸다
(2026-09-17 새벽 실측). 그 상태로 Kit 을 띄우면 렌더러만 죽어 프레임 0 장으로 ready_timeout(420 s)을 다 태운 뒤에야
실패했다.

처방은 둘이다. compose `devices:` 로 장치를 docker 자신의 목록에 올려 재적용에서 살아남게 하고(deploy/compose.yml),
여기서는 Start 마다 nvidia-smi 로 한 번 확인해 안 되면 Kit 을 띄우지 않고 즉시 ERROR 로 보고한 뒤 프로세스를 내린다 —
restart 정책이 다시 띄우면 nvidia 훅이 장치를 다시 넣고, host-orch 는 NDEATH 로 런을 바로 접어 BE 가 재시도할 수 있다.
"""
from __future__ import annotations

import subprocess
from collections.abc import Callable

NVIDIA_SMI_PROBE = ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"]
PROBE_TIMEOUT_S = 15.0


def probe(run: Callable = subprocess.run, timeout_s: float = PROBE_TIMEOUT_S) -> str | None:
    """GPU 를 쓸 수 있으면 None, 아니면 사유 문자열 (LastError 에 그대로 실린다)."""
    try:
        out = run(NVIDIA_SMI_PROBE, capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return f"nvidia-smi timed out after {timeout_s:g}s"
    except (OSError, subprocess.SubprocessError) as e:
        return f"nvidia-smi not runnable: {e}"
    if out.returncode != 0:
        lines = [ln for ln in ((out.stderr or "") + (out.stdout or "")).splitlines() if ln.strip()]
        return f"nvidia-smi rc={out.returncode}: {lines[-1].strip() if lines else 'no output'}"
    if not (out.stdout or "").strip():
        return "nvidia-smi listed no GPU"
    return None
