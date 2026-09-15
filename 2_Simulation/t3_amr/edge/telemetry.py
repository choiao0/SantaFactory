"""Runner/RamMB · VramMB 표본 — psutil 프로세스 트리 RSS 합, nvidia-smi 사용량 합. 실패는 None."""
from __future__ import annotations

import subprocess
from typing import Callable, Iterable, Optional

import psutil

NVIDIA_SMI = ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"]
MB = 1024 * 1024


def ram_mb(pids: Iterable[int]) -> int:
    """pid 들과 그 자손의 RSS 합(MB). 사라진 프로세스는 건너뛴다."""
    total = 0
    for pid in pids:
        try:
            p = psutil.Process(pid)
            procs = [p] + p.children(recursive=True)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        for q in procs:
            try:
                total += q.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    return total // MB


def vram_mb(run: Callable = subprocess.run) -> Optional[int]:
    """모든 GPU 의 사용 VRAM 합(MB). nvidia-smi 가 없거나 실패하면 None."""
    try:
        out = run(NVIDIA_SMI, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    try:
        return sum(int(float(line)) for line in out.stdout.split() if line.strip())
    except ValueError:
        return None
