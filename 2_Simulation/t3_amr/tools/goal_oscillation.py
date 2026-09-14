# -*- coding: utf-8 -*-
"""목표 앞 왕복 정체 재현 — `run_h` 가 목표에 닿았다가 도로 나온다.

증상 (2026-09-14, develop 머지 후)
---------------------------------
로봇이 목표에서 **한 칸 거리**를 무한히 왕복한다. 전진하면 목표인데
`blocked_by={}` 로 아무도 막지 않는다.

    agent1 최근: [(38,59,0), (37,59,0), (38,59,0), (37,59,0), ...]
    agent1 (37,59,0)  goal=(38,59)  dist=1.0
       fwd  -> (38,59,0)  dist=0.0  blocked_by={}
       wait -> (37,59,0)  dist=1.0  blocked_by={}

max_steps 를 480 -> 4000 으로 8배 늘려도 그대로다. **느린 것이 아니라
갇힌 것**이다. 정체 틱이 338 -> 3858 로 늘 뿐 상태가 안 바뀐다.

머지 전에는 같은 시드가 완주했다. 틱 단위 변경과도 무관하다 —
`TICKS_PER_CELL` 을 반영해 480스텝(= 옛 120스텝)으로 맞춘 뒤에도 같다.

무엇을 의심하나
---------------
목표 칸을 쥔 로봇이 지나가는 로봇에게 밀려났다가 돌아오기를 반복하는
라이브락으로 보인다. PIBT 는 `age`(목표 미도달 연속 틱) 로 우선순위를
올려 이런 교착을 푸는데, 그 승급이 안 먹는 것 같다 — 3858틱을 기다려도
못 들어간다.

    ★ 진단 출력의 `blocked_by={}` 는 **그 로봇 시점**이다. 미는 쪽은
      우선순위 상속으로 오므로 여기 안 찍힌다.

쓰는 법
-------
    source paths.sh
    PITCH=1.2 python tools/goal_oscillation.py
    PITCH=1.2 SEEDS=1,4 STEPS=480,4000 python tools/goal_oscillation.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.environ["W"], "path"))
import pibt_core_v2                      # noqa: F401
from pibt_core import run_h              # noqa: E402
import pibt_scene                        # noqa: E402

MAP = os.environ["MAP"]
PITCH = float(os.environ.get("PITCH", "1.2"))
N = int(os.environ.get("N", "12"))
SEEDS = [int(x) for x in os.environ.get("SEEDS", "1,2,4").split(",")]
STEPS = [int(x) for x in os.environ.get("STEPS", "480,960,2000,4000").split(",")]


def main():
    print(f"목표 앞 왕복 정체 — pitch {PITCH} · {N}대 · cross")
    print("각 시드에서 max_steps 를 키워 가며: 느린 것인가 갇힌 것인가\n")
    bad = 0
    for seed in SEEDS:
        geom, free, starts, goals = pibt_scene.setup(MAP, N, PITCH, seed, "cross")
        cells = []
        for ms in STEPS:
            try:
                hist, _ = run_h(free, starts, goals, max_steps=ms)
                cells.append(f"{ms}: 완주 {len(hist)}틱")
                break
            except SystemExit as e:
                m = str(e)
                who = m.split("미도달")[-1].strip() if "미도달" in m else m[:30]
                cells.append(f"{ms}: 정체 {who}")
        else:
            bad += 1
        print(f"  seed {seed:>3}   " + "   ".join(cells))
    print()
    if bad:
        print(f"★ {bad}개 시드가 최대 스텝까지 못 간다. 같은 로봇이 같은 칸에서")
        print("  막히면 지평 문제가 아니라 라이브락이다 — 진단 출력의")
        print("  `fwd -> ... dist=0.0 blocked_by={}` 줄을 볼 것.")
    else:
        print("전부 완주.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
