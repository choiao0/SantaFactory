"""host_orch/spb.py · sparkplug_b_pb2.py 가 Sparkplug 코덱의 참조 구현이다 — fms_core 사본과 바이트 단위로 같아야 한다.

원본이던 2_Simulation/sim_runner 는 -219(2026-09-15)로 삭제됐다. 바꾸면 fms_core 쪽도 같이 바꾼다.
"""
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


@pytest.mark.parametrize("name", ["spb.py", "sparkplug_b_pb2.py"])
def test_codec_copies_are_identical(name):
    ours = os.path.join(ROOT, "3_FMS", "host_orch", name)
    theirs = os.path.join(ROOT, "3_FMS", "fms_core", name)
    assert open(ours, "rb").read() == open(theirs, "rb").read(), f"{name} drifted — keep fms_core/{name} identical"
