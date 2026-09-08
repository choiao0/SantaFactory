"""sim_runner.telemetry — RAM 트리 합 · nvidia-smi 파싱."""
import os
import subprocess

from sim_runner import telemetry as T


def test_ram_mb_counts_own_process_and_skips_missing_pids():
    assert T.ram_mb([os.getpid()]) > 0
    assert T.ram_mb([999_999_999]) == 0


def test_vram_mb_sums_gpus_from_nvidia_smi_output():
    fake = lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="1234\n567\n", stderr="")

    assert T.vram_mb(run=fake) == 1801


def test_vram_mb_is_none_when_nvidia_smi_missing_or_failing():
    def missing(*a, **k):
        raise FileNotFoundError("nvidia-smi")

    failing = lambda *a, **k: subprocess.CompletedProcess(a, 1, stdout="", stderr="err")
    garbage = lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="N/A\n", stderr="")

    assert T.vram_mb(run=missing) is None
    assert T.vram_mb(run=failing) is None
    assert T.vram_mb(run=garbage) is None
