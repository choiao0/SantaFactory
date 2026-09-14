# -*- coding: utf-8 -*-
"""앞 2칸을 hard 로 넣으면 pitch 1.0 의 ADG 순환이 풀리는가.

FMS 가 `pibt/geometry.py` 를 고치기 전에 **우리 프로세스 안에서** 그 함수를
바꿔치기해 확인한다. 저쪽 작업을 기다리지 않고 요청이 맞는지 먼저 검증한다.

세 가지를 같은 시드로 비교한다.

    base    현행 3칸                 -> pitch 1.0 에서 순환 (기지: 2026-09-14)
    swing5  swing_cells 만 5칸       -> 우리가 부탁하려는 최소 변경
    both    swing_cells + turn_ok    -> 통행 검사까지 앞 칸 포함

`swing5` 만으로 되면 FMS 요청이 함수 하나로 끝난다. `both` 가 필요하면
`turn_ok` 도 고쳐야 하고, 그건 거리맵(hgraph.py:28)까지 바뀌는 더 큰 변경이다.

경로는 `pibt_scene.py --plan --lifelong` 과 **같은 것**을 쓴다
(`plan_and_build_lifelong`). 순환이 났던 것이 이 경로이므로 oneshot 으로
바꿔 재면 안 된다.

    source paths.sh
    python tools/try_swing5.py
    PITCHES=1.0,1.1,1.2 SEEDS=1,2,4 python tools/try_swing5.py
"""
import os
import sys
import types

sys.path.insert(0, os.path.join(os.environ["W"], "path"))
import pibt_core_v2                      # noqa: F401  sim_engine 을 sys.path 에 올린다
import isaac_drive as D                  # noqa: E402
import pibt_scene                        # noqa: E402
import metrics                           # noqa: E402,F401

import pibt.geometry as geo              # noqa: E402  저쪽 원본 모듈

MAP = os.environ["MAP"]
N = int(os.environ.get("N", "12"))
HORIZON = int(os.environ.get("HORIZON", "315"))
GAP = int(os.environ.get("GAP", "15"))
PITCHES = [float(x) for x in os.environ.get("PITCHES", "1.0,1.2").split(",")]
SEEDS = [int(x) for x in os.environ.get("SEEDS", "1,2,4").split(",")]

_ORIG_SWING = geo.swing_cells
_ORIG_TURN = geo.turn_ok


def _front(r, c, h):
    d = geo.DIRS[h]
    return (r + d[0], c + d[1])


def swing5(r, c, h, h2):
    """뒤 3칸 + 앞 2칸 — FMS 에 부탁하려는 반환값."""
    return set(_ORIG_SWING(r, c, h, h2)) | {_front(r, c, h), _front(r, c, h2)}


def turn_ok5(free, r, c, h, h2):
    """현행 검사 + 앞 2칸도 통행 가능해야 회전 허용."""
    if not _ORIG_TURN(free, r, c, h, h2):
        return False
    return all(geo._inb(free, x) for x in (_front(r, c, h), _front(r, c, h2)))


def _rebind(name, new, old):
    """`from .geometry import <name>` 한 모듈의 **복사본**까지 전부 바꾼다.

    ★ `geo.<name>` 만 바꾸면 소용없다. `pibt/heading.py` 는 import 시점에
      자기 전역으로 복사해 갔고, 호출은 그 복사본을 쓴다. 이걸 놓치면
      "패치했는데 결과가 그대로" 가 된다.
    """
    hit = []
    for mod in list(sys.modules.values()):
        if isinstance(mod, types.ModuleType) and getattr(mod, name, None) is old:
            setattr(mod, name, new)
            hit.append(mod.__name__)
    return hit


def plan_once(pitch, seed):
    """`pibt_scene.py --plan --lifelong --battery` 와 같은 경로."""
    import importlib
    os.environ["PIBT_PITCH"] = str(pitch)
    importlib.reload(pibt_scene)          # CHARGE_ZONE 이 import 시점에 굳는다
    try:
        geom, free, starts, goals = pibt_scene.setup_lifelong(
            MAP, N, pitch, seed, "cross", verbose=False)
        zone = pibt_scene.charge_zone_cells(free, geom)
        adg, order, history, info = D.plan_and_build_lifelong(
            free, starts, goals, geom, horizon=HORIZON, seed=seed,
            order_gap=GAP, battery=True, dispatch="fms", zone_cells=zone,
            order_end=None, docks=pibt_scene.charge_docks(free, geom))
        if adg.topological_order() is None:
            return "ADG 순환(빌드 통과)"
        tp = info.get("throughput", info.get("done", "?"))
        return f"OK 액션 {len(adg.actions)} 처리량 {tp}"
    except RuntimeError as e:
        return f"RuntimeError: {str(e)[:30]}"
    except SystemExit as e:
        return f"SystemExit: {str(e)[:30]}"


def main():
    print(f"대수 {N}  시드 {SEEDS}  pitch {PITCHES}  horizon {HORIZON}\n")
    for label, sw, to in (("base   (현행 3칸)", None, None),
                          ("swing5 (앞2칸)", swing5, None),
                          ("both   (+turn_ok)", swing5, turn_ok5)):
        geo.swing_cells, geo.turn_ok = _ORIG_SWING, _ORIG_TURN
        _rebind("swing_cells", _ORIG_SWING, swing5)
        _rebind("turn_ok", _ORIG_TURN, turn_ok5)
        if sw:
            geo.swing_cells = sw
            print(f"[patch] swing_cells -> {_rebind('swing_cells', sw, _ORIG_SWING)}")
        if to:
            geo.turn_ok = to
            print(f"[patch] turn_ok     -> {_rebind('turn_ok', to, _ORIG_TURN)}")
        cells = sorted((sw or _ORIG_SWING)(5, 5, 1, 0))
        print(f"  {label:<20} 회전 예약 {len(cells)}칸 {cells}")
        for p in PITCHES:
            for s in SEEDS:
                print(f"    pitch {p:.2f}  seed {s} : {plan_once(p, s)}", flush=True)
        print()


if __name__ == "__main__":
    main()
