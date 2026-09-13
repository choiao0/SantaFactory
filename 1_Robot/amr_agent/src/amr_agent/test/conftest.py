"""pytest 6 호환 — src/amr_agent 를 import 경로에 올린다 (pyproject 의 pythonpath 는 pytest 7+ 전용)."""
import os
import sys

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SRC not in sys.path:
    sys.path.insert(0, SRC)
