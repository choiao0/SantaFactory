# -*- coding: utf-8 -*-
"""soft_hold 보존 (물리 팀 답신 11 §1, 2026-09-16, S15P21A106-160 MR 에 동반).

회전 중인 로봇 X 의 soft 칸은 커널이 매 틱 soft_hold={cell: X} 로 미리 주입한다(다틱 회전 보호).
같은 틱에 다른 로봇 A 의 회전 후보가 그 칸을 soft 로 예약(_reserve: soft_next[cell] = A 로 덮어씀)했다가
밀기에 실패해 _release 하면, 옛 코드는 "내 것이면 삭제"만 해서 X 의 보호가 사라졌다 → 제3 로봇 축이 들어와
Isaac 에서 차체 접촉(pitch 1.0 5시드 중 2판). 고침: 주입 원본(soft_base)을 기억해 되돌린다.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pibt.heading import _PIBTStepH  # noqa: E402


def _step(soft_hold):
    free = np.ones((9, 9), dtype=bool)
    states = {1: (4, 4, 0), 2: (2, 6, 1)}
    dists = {a: np.zeros((9, 9, 4)) for a in states}
    return _PIBTStepH(states, dists, np.ones((9, 9, 4)), np.ones((9, 9)), free, 1.25,
                      {}, {}, None, 0, (), None, None, soft_hold)


def test_release_restores_preinjected_soft_hold():
    cell = (3, 5)
    ps = _step({cell: 1})                                  # 로봇 1 이 회전 중 — 커널이 주입한 soft 칸
    assert ps.soft_next[cell] == 1
    ps._reserve(2, (2, 6, 2), frozenset({(2, 6), (3, 6)}), soft=frozenset({cell}))   # 로봇 2 의 회전 후보가 같은 칸을 soft 로 덮어씀
    assert ps.soft_next[cell] == 2                          # 덮어쓰기 자체는 무해 (제3자에겐 누구든 막힘)
    ps._release(2)                                          # 밀기 실패 → 되돌림
    assert ps.soft_next.get(cell) == 1, "주입한 soft_hold 가 release 로 지워졌다 — 회전 중 로봇의 보호 상실"


def test_release_deletes_own_soft_when_no_base():
    cell = (3, 5)
    ps = _step({})
    ps._reserve(2, (2, 6, 2), frozenset({(2, 6), (3, 6)}), soft=frozenset({cell}))
    ps._release(2)
    assert cell not in ps.soft_next
