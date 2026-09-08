# -*- coding: utf-8 -*-
"""CLI 셸 공통 상수 — report / export_isaac / plot 이 함께 쓴다 (순환 import 방지용 분리)."""
import os

from map_loader import CELL_M

OUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # sim_engine/
SPEED = 1.0
DT = CELL_M / SPEED
