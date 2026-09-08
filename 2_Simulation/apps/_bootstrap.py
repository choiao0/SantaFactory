"""엔트리 공통 — 2_Simulation/ 을 sys.path 에 올린다 (python.sh <repo>/2_Simulation/apps/xxx.py 로 실행되므로)."""
import os
import sys

SIL_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
if SIL_ROOT not in sys.path:
    sys.path.insert(0, SIL_ROOT)
