"""3_FMS/ 를 import 경로에 올린다 (`import fms_core`). 1_Robot/amr_agent 의 vda5050 패키지가 있으면 VDA 오라클 테스트에 쓴다."""
import os
import sys

FMS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(FMS)
T4_SRC = os.path.join(ROOT, "1_Robot", "amr_agent", "src", "amr_agent")
for p in (FMS, T4_SRC):
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)
