"""edge/spb.py · sparkplug_b_pb2.py 는 3_FMS/host_orch 의 바이트 단위 복사본이어야 한다 (참조 구현 = host_orch).

fms_core 도 같은 규칙으로 host_orch 를 본다(3_FMS/fms_core/tests/test_spb_copy.py). 여기가 세 번째 사본이다.
ruff 가 이 파일을 건드리지 않도록 pyproject 에서 제외했다.
"""
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))


@pytest.mark.parametrize("name", ["spb.py", "sparkplug_b_pb2.py"])
def test_codec_copies_are_identical(name):
    ours = os.path.join(ROOT, "2_Simulation", "t3_amr", "edge", name)
    theirs = os.path.join(ROOT, "3_FMS", "host_orch", name)
    with open(ours, "rb") as a, open(theirs, "rb") as b:
        assert a.read() == b.read(), f"{name} drifted — copy from 3_FMS/host_orch/{name}"
