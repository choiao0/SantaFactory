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
                stag_max=li.get("stag_max", "-"),
                stag_mean=li.get("stag_mean", "-"),
                stuck=li.get("stag_stuck", "-"),
                hits=ghits)


def main():
    print(f"[soft_probe] pitch {PITCH} · {N}대 · {HORIZON}틱 · gap {GAP}")
    print(f"             PIBT_FRONT_RULE={os.environ.get('PIBT_FRONT_RULE', '(안 줌)')}")
    print()
    print(f"  {'시드':>4}  {'위반':>5}  {'태스크':>6}  {'대기':>4}"
          f"  {'soft_clash':>10}  {'정체최대':>8}  {'정체평균':>8}  {'100틱+':>7}")
    rows = []
    for s in SEEDS:
        r = run(s)
        rows.append(r)
        sm = r["stag_mean"]
        print(f"  {r['seed']:>4}  {r['ghits']:>5}  {r['tasks']:>6}  "
              f"{r['waiting']:>4}  {str(r['clash']):>10}"
              f"  {str(r['stag_max']):>8}"
              f"  {sm if isinstance(sm, str) else format(sm, '.1f'):>8}"
              f"  {str(r['stuck']):>7}")
    print(f"  {'합/평':>4}  {sum(r['ghits'] for r in rows):>5}"
          f"  {sum(r['tasks'] for r in rows):>6}"
          f"  {sum(r['waiting'] for r in rows):>4}")
    print()
    # ★ 판정은 **둘 다** 봐야 한다 — 위반 0 만 보면 교착을 놓친다
    #   (FMS 답신 12 §3: 위상 잠금은 6대에서도 난다).
    bad = [r["seed"] for r in rows if r["ghits"]]
    stuck = [r["seed"] for r in rows
             if isinstance(r["stuck"], int) and r["stuck"]]
    print(f"  위반 있는 시드   {bad or '없음'}")
    print(f"  100틱+ 정체 시드 {stuck or '없음'}")
    if not bad and not stuck:
        print("  -> 계획 층 통과. 다음은 주행 검증이다 —")
        print("     ★ 위반 0 은 접촉 0 을 뜻하지 않는다. soft 규칙은 물리")
        print("       여유를 안 준다 — 합법 배치 최소 여유 41.4 mm 인데")
        print("       회전 중 이탈 구간 최대가 74.3 mm 다 (FMS 답신 12 §2).")
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
