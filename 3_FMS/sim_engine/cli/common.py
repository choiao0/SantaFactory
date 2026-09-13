# -*- coding: utf-8 -*-
"""CLI 셸 공통 상수 — report / export_isaac / plot 이 함께 쓴다 (순환 import 방지용 분리)."""
import os

from map_loader import CELL_M

OUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # sim_engine/
SPEED = 1.0                 # --speed 기본값 (m/s). 실행 값은 parse_args 가 a.speed·a.dt 로 든다 (-116, 계약 v3.3)
DT = CELL_M / SPEED         # 기본 틱 길이[초] — 인자 없는 호출의 환산 기준 (비트 동일 보장)
