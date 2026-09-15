# -*- coding: utf-8 -*-
"""적재량 → 속도 단일 함수 (S15P21A106-116).

세 팀(1차 SimPy · FMS 견적 · 물리 t3_amr)이 **같은 숫자**를 쓰기 위한 한 곳이다. 순수 파이썬(numpy 없음)이라
어느 쪽에서든 그대로 import 한다. 앵커(공차·적재·상한)는 상수가 아니라 인자다 — 어느 값을 쓸지는
팀 합의(정격 2.2 / 운영 1.5·1.0 / 계획 0.9, 물리 팀 답신 2026-09-13 §2-4)가 정하고, 여기서는 정하지 않는다.

    v(load) = v_empty − (v_empty − v_full) × clamp(load / max_load, 0, 1)
    그 뒤 v_min(최저 보장)·v_cap(계획 상한) 으로 자른다.

지금 쓰는 법(팀 결정 2026-09-11): 사용자가 준 **평균 적재량**으로 한 번 불러 run 내내 고정 속도로 쓴다.
나중 쓰는 법: 품목별 무게가 오면 같은 함수를 왕복마다 부른다. 함수는 같고 부르는 쪽만 다르다.
"""


def speed_for_load(load_kg, *, v_empty, v_full, max_load_kg, v_min=None, v_cap=None):
    """적재 무게(kg) → 속도(m/s). 무게 0 = v_empty, 최대 적재 이상 = v_full 인 선형 감속.

    v_min: 결과의 하한(최저 속도 보장). None 이면 하한 없음(= v_full 이 자연 하한).
    v_cap: 결과의 상한(예: 계획 속도 0.9). None 이면 상한 없음.
    잘못된 앵커(음수·0, v_full > v_empty, 하한 > 상한)는 ValueError — 조용히 이상한 속도를 내지 않는다.
    """
    if v_empty <= 0 or v_full <= 0 or max_load_kg <= 0:
        raise ValueError(f"v_empty·v_full·max_load_kg 는 양수: {v_empty}, {v_full}, {max_load_kg}")
    if v_full > v_empty:
        raise ValueError(f"적재 속도가 공차 속도보다 빠를 수 없다: v_full {v_full} > v_empty {v_empty}")
    if load_kg < 0:
        raise ValueError(f"적재 무게는 0 이상: {load_kg}")
    if v_min is not None and v_cap is not None and v_min > v_cap:
        raise ValueError(f"하한이 상한보다 크다: v_min {v_min} > v_cap {v_cap}")
    frac = min(1.0, load_kg / max_load_kg)
    v = v_empty - (v_empty - v_full) * frac
    if v_min is not None:
        v = max(v, v_min)
    if v_cap is not None:
        v = min(v, v_cap)
    return float(v)
