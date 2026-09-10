"""fms_core/spb.py · sparkplug_b_pb2.py 는 2_Simulation/sim_runner 의 바이트 단위 복사본이어야 한다 (host_orch 와 같은 규칙)."""
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


@pytest.mark.parametrize("name", ["spb.py", "sparkplug_b_pb2.py"])
def test_codec_copies_are_identical(name):
    ours = os.path.join(ROOT, "3_FMS", "fms_core", name)
    theirs = os.path.join(ROOT, "2_Simulation", "sim_runner", name)
    if not os.path.exists(theirs):
        pytest.skip("2_Simulation not in this checkout")
    assert open(ours, "rb").read() == open(theirs, "rb").read(), f"{name} drifted — copy from 2_Simulation/sim_runner"
