"""fms_core/spb.py · sparkplug_b_pb2.py 는 host_orch 의 바이트 단위 복사본이어야 한다.

원본은 2_Simulation/sim_runner 였으나 -219(2026-09-15)로 삭제됐다 — 이제 host_orch 가 참조 구현이고 fms_core 가 사본이다.
"""
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


@pytest.mark.parametrize("name", ["spb.py", "sparkplug_b_pb2.py"])
def test_codec_copies_are_identical(name):
    ours = os.path.join(ROOT, "3_FMS", "fms_core", name)
    theirs = os.path.join(ROOT, "3_FMS", "host_orch", name)
    assert open(ours, "rb").read() == open(theirs, "rb").read(), f"{name} drifted — copy from 3_FMS/host_orch"
