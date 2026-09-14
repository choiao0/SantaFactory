# -*- coding: utf-8 -*-
"""목표 앞 왕복 정체 — 재현과 수정안 검증.

증상 (2026-09-14, develop 머지 후)
---------------------------------
로봇이 목표 칸에 도착한 다음 틱에 **스스로 나온다.** 그리고 돌아온다.
아무도 막고 있지 않다.

    agent0 최근: [(58,24,2), (57,24,2), (58,24,2), (57,24,2), ...]
    agent0 (57,24,2)  goal=(58,24)  dist=3.0  bias=20
       rev  -> (58,24,2)  dist=0.0  blocked_by={}
       wait -> (57,24,2)  dist=3.0  blocked_by={}

`max_steps` 를 480 -> 4000 으로 8배 늘려도 같은 로봇이 같은 칸에서 막힌다.
정체 틱만 338 -> 3858 로 늘 뿐이다. 느린 것이 아니라 갇힌 것이다.

원인
----
`candidates_h` 에서 **대기** 후보에만 정체 벌점 `bias` 가 더해지는데,
로봇이 **목표에 도착해 있어도** 붙는다.

    scored.append((wait_cost[r, c] + bias + dist[r, c, h], ...))   # 대기

`bias = wait_bias(stag)` 는 정체가 쌓이면 상한 20 까지 오른다. 그러면

    목표 (dist=0)    대기 ~ 1 + 20 + 0 = 21   vs  전진 ~ 1 + 3 = 4   -> 나간다
    옆 칸 (dist=3)   대기 ~ 1 + 20 + 3 = 24   vs  후진 ~ 3 + 0 = 3   -> 돌아온다

거리가 안 줄어드니 `stag` 이 계속 쌓이고 `bias` 는 상한에 붙은 채 안 풀린다.
(`dist` 가 1 이 아니라 3 인 것은 목표가 뒤쪽이라 `REVERSE_FACTOR=3.0` 이
걸리기 때문이다.)

수정안 — 한 줄
-------------
목표에 서 있는 로봇에게 "그만 기다리고 움직여라" 벌점을 주면 안 된다.
거기 있는 것이 정답이다.

    if dist[r, c, h] >= 0:
        b = 0.0 if dist[r, c, h] == 0 else bias       # <- 목표면 면제
        scored.append((wait_cost[r, c] + b + dist[r, c, h], ...))

★ 상수 조정으로는 못 고친다. `WAIT_ESC_GRACE`/`REPLAN_AFTER` 를 4배·8배로
  올려도 3/6 이 그대로 막히고, 8배에서는 멀쩡하던 시드가 새로 깨진다 —
  벌점을 키우면 이 정체가 늦게 오는 대신 원래 깨야 할 진동을 못 깬다.
  두 실패 모드가 상수를 반대 방향으로 당긴다.

쓰는 법
-------
    source paths.sh
    PITCH=1.0 python tools/goal_oscillation.py          재현만
    PITCH=1.0 FIX=1 python tools/goal_oscillation.py    수정안까지 비교
"""
import io
import os
import sys

sys.path.insert(0, os.path.join(os.environ["W"], "path"))
import pibt_core_v2                      # noqa: F401
import pibt.heading as HD                # noqa: E402
import pibt_scene                        # noqa: E402

MAP = os.environ["MAP"]
PITCH = float(os.environ.get("PITCH", "1.2"))
N = int(os.environ.get("N", "12"))
SEEDS = [int(x) for x in os.environ.get("SEEDS", "1,2,3,4,5,6").split(",")]
STEPS = int(os.environ.get("STEPS", "2000"))
FIX = os.environ.get("FIX", "") not in ("", "0")

_ORIG = HD.candidates_h


def _goal_exempt(s, dist, edge_cost, wait_cost, free, turn_cost, bias=0.0):
    """수정안 — 목표 상태(dist == 0)면 대기 벌점을 뺀다."""
    r, c, h = s
    if dist[r, c, h] == 0:
        bias = 0.0
    return _ORIG(s, dist, edge_cost, wait_cost, free, turn_cost, bias)


def _quiet(fn, *a, **kw):
    """시나리오·진단 출력이 길어 삼킨다."""
    buf, old = io.StringIO(), sys.stdout
    sys.stdout = buf
    try:
        return fn(*a, **kw)
    finally:
        sys.stdout = old


def trial(scen, patched):
    HD.candidates_h = _goal_exempt if patched else _ORIG
    out = []
    for s in SEEDS:
        _, free, starts, goals = scen[s]
        try:
            hist, _ = _quiet(HD.run_h, free, starts, goals, max_steps=STEPS)
            out.append(f"완주 {len(hist)}")
        except SystemExit:
            out.append("정체")
    HD.candidates_h = _ORIG
    return out


def main():
    scen = {s: _quiet(pibt_scene.setup, MAP, N, PITCH, s, "cross") for s in SEEDS}
    print(f"목표 앞 왕복 정체 — pitch {PITCH} · {N}대 · cross · max_steps {STEPS}")
    print()
    head = f"{'':<24}" + "".join(f"{'seed ' + str(s):>12}" for s in SEEDS)
    print(head)

    now = trial(scen, False)
    print(f"{'현재':<24}" + "".join(f"{r:>12}" for r in now))
    bad = sum(r == "정체" for r in now)

    if FIX:
        fixed = trial(scen, True)
        print(f"{'목표 면제 (수정안)':<24}" + "".join(f"{r:>12}" for r in fixed))
        print()
        still = sum(r == "정체" for r in fixed)
        same = sum(1 for a, b in zip(now, fixed) if a == b and a != "정체")
        print(f"  정체 {bad} -> {still}")
        print(f"  멀쩡하던 시드 중 {same}개가 **틱 수까지 동일** — "
              f"망가진 경우에만 바뀐다")
        return 1 if still else 0

    print()
    if bad:
        print(f"★ {bad}개 시드가 {STEPS}스텝까지 못 간다. 같은 로봇이 같은 칸에서")
        print("  막히면 지평 문제가 아니라 라이브락이다. FIX=1 로 수정안을 본다.")
    else:
        print("전부 완주.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
