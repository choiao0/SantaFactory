# -*- coding: utf-8 -*-
"""`soft_hold` 전/후를 **같은 판에서** 재는 일회용 프로브 (S15P21A106-211).

`swing_overlap.py` 는 위반 건수를 내지만 `soft_clash` 와 처리량을 안 찍는다.
`soft_hold` 를 켜면 계획이 바뀌므로 **대가**를 같이 봐야 판정이 된다 —
위반 0 과 완주를 같이 봐야 통과다 (작업서 §5-1).

쓰는 법
-------
    source paths.sh
    PIBT_FRONT_RULE=4 PIBT_PITCH=1.0 SEEDS=2,5 python3 tools/soft_probe.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.environ["W"], "path"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pibt_scene                                            # noqa: E402
from swing_overlap import scan_guard                         # noqa: E402

MAP = os.environ["MAP"]
N = int(os.environ.get("N", "12"))
PITCH = float(os.environ.get("PIBT_PITCH", "1.0"))
SEEDS = [int(x) for x in os.environ.get("SEEDS", "2,5").split(",")]
HORIZON = int(os.environ.get("HORIZON", "1260"))
GAP = int(os.environ.get("GAP", "60"))


def run(seed):
    from lifelong import run_lifelong                        # noqa: E402
    geom, free, starts, goals = pibt_scene.setup_lifelong(
        MAP, N, PITCH, seed, "cross", verbose=False)
    zone = pibt_scene.charge_zone_cells(free, geom)
    history, _cells, li = run_lifelong(
        free, starts, goals, horizon=HORIZON, seed=seed, order_gap=GAP,
        shifts=("in", "out", "out"), zone_cells=zone, order_end=None)
    ghits, gkinds = scan_guard(geom, history)
    return dict(seed=seed, ghits=len(ghits), gkinds=gkinds,
                tasks=li.get("tasks_done"), waiting=li.get("waiting"),
                clash=li.get("soft_clash", "-"), ticks=len(history) - 1,
                hits=ghits)


def main():
    print(f"[soft_probe] pitch {PITCH} · {N}대 · {HORIZON}틱 · gap {GAP}")
    print(f"             PIBT_FRONT_RULE={os.environ.get('PIBT_FRONT_RULE', '(안 줌)')}")
    print()
    print(f"  {'시드':>4}  {'위반':>5}  {'태스크':>6}  {'대기':>4}  {'soft_clash':>10}")
    rows = []
    for s in SEEDS:
        r = run(s)
        rows.append(r)
        print(f"  {r['seed']:>4}  {r['ghits']:>5}  {r['tasks']:>6}  "
              f"{r['waiting']:>4}  {str(r['clash']):>10}")
    print()
    for r in rows:
        if not r["ghits"]:
            continue
        print(f"  시드 {r['seed']} 남은 위반 {r['ghits']}건 — {r['gkinds']}")
        for row in r["hits"][:8]:
            print(f"      {row}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
