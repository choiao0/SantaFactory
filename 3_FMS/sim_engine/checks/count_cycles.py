# -*- coding: utf-8 -*-
"""한 틱 이동 그래프의 순환(동시 교대) 세기 — t3-35 §4 ⓐ·ⓒ 답용 (2026-09-21, 읽기 전용 진단).

    cd 3_FMS/sim_engine
    SIM_NO_PLOT=1 PYTHONPATH=. python checks/count_cycles.py x 24 0 101 1 <six 인자…>

간선 a→b = a 의 다음 축 칸이 b 의 현재 축 칸(b≠a). 각 로봇의 다음 축 칸은 하나라 함수 그래프이고,
순환 = 「서로가 서로의 칸을 동시에 필요로 하는 집합」. 길이 2 = 맞교환(heading.py:268 이 금지 — 0 이어야 한다),
길이 ≥3 = 회전 순환(표준 PIBT 가 허용하는 following). 틱마다 세어 길이별 합·최대 동시 수를 찍는다.
"""
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import kernel.core as kc                      # noqa: E402
from sim_v2_tasks import build, parse_args, run_ticks   # noqa: E402

LEN, PER_TICK = Counter(), Counter()          # 길이별 순환 수, 틱당 순환 수 분포
_orig = kc.step_h


def _count(states, new):
    axle = {s[:2]: a for a, s in states.items()}
    nxt = {}
    for a, s2 in new.items():
        if s2[:2] != states[a][:2]:
            b = axle.get(s2[:2])
            if b is not None and b != a:
                nxt[a] = b
    seen, n_tick = set(), 0
    for a in nxt:
        if a in seen:
            continue
        path, x = [], a
        while x in nxt and x not in seen and x not in path:
            path.append(x)
            x = nxt[x]
        if x in path:                              # 순환 발견
            k = len(path) - path.index(x)
            LEN[k] += 1
            n_tick += 1
        seen.update(path)
    PER_TICK[n_tick] += 1


def _wrapped(states, *a, **kw):
    new, cells, denied = _orig(states, *a, **kw)
    _count(states, new)
    return new, cells, denied


def main(argv):
    kc.step_h = _wrapped
    a = parse_args(argv)
    kernel, stream, ctx = build(a)
    t = run_ticks(kernel, stream, a.horizon)
    ticks = sum(PER_TICK.values())
    total = sum(LEN.values())
    print(f"[CYCLES] ticks={t} 순환 합={total} 길이별={dict(sorted(LEN.items()))} "
          f"순환 있는 틱={ticks - PER_TICK[0]} 틱당 최대={max(PER_TICK) if PER_TICK else 0} "
          f"시간당={total / (t * 0.2778 / 3600):.1f}")
    assert LEN[2] == 0, "길이 2 맞교환이 나왔다 — heading.py:268 규칙이 뚫렸다"


if __name__ == "__main__":
    main(sys.argv[1:])
