"""pytest 6 호환 — 2_Simulation/ 을 import 경로에 올린다 (pyproject 의 pythonpath 는 pytest 7+ 전용).
에이전트(amr_agent)는 1_Robot/ 으로 갔다 — 그 테스트는 1_Robot/amr_agent 에서 따로 돈다."""
import os
import sys

SIL = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p in (SIL,):
    if p not in sys.path:
        sys.path.insert(0, p)
