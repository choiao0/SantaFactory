"""edge.gpu — Start 직전 GPU 프로브 (-241). nvidia-smi 를 가짜로 돌려 판정 문자열만 본다."""
import subprocess
from types import SimpleNamespace

from edge import gpu


def fake_run(rc=0, stdout="NVIDIA GeForce RTX 5080\n", stderr="", raise_exc=None):
    calls = []

    def run(argv, **kw):
        calls.append((argv, kw))
        if raise_exc:
            raise raise_exc
        return SimpleNamespace(returncode=rc, stdout=stdout, stderr=stderr)
    run.calls = calls
    return run


class TestProbe:
    def test_ok_when_nvidia_smi_lists_a_gpu(self):
        run = fake_run()

        assert gpu.probe(run) is None
        assert run.calls[0][0] == gpu.NVIDIA_SMI_PROBE and run.calls[0][1]["timeout"] == gpu.PROBE_TIMEOUT_S

    def test_nonzero_rc_reports_the_last_output_line(self):
        run = fake_run(rc=255, stdout="", stderr="Failed to initialize NVML: Unknown Error\n")

        assert gpu.probe(run) == "nvidia-smi rc=255: Failed to initialize NVML: Unknown Error"

    def test_missing_binary_and_timeout_are_reported_not_raised(self):
        assert "not runnable" in gpu.probe(fake_run(raise_exc=FileNotFoundError("nvidia-smi")))
        assert "timed out" in gpu.probe(fake_run(raise_exc=subprocess.TimeoutExpired("nvidia-smi", 15)))

    def test_no_gpu_listed_is_a_failure(self):
        assert gpu.probe(fake_run(stdout="\n")) == "nvidia-smi listed no GPU"
