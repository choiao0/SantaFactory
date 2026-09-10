"""3_FMS/ 를 import 경로에 올린다 (`import host_orch`)."""
import os
import sys

FMS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if FMS not in sys.path:
    sys.path.insert(0, FMS)
