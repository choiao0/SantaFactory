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


# 이 도구는 (패치 × pitch × 시드) 표를 채우는 것이 목적이라, 한 칸이 실패해도
# 나머지 칸은 의미가 있다. 그래서 실패를 칸 글자로 바꿔 넣는다.
#
# 다만 **전 칸이 똑같이 죽는 설정 오류**까지 칸에 넣으면 같은 문구가 칸 수만큼
# 찍힐 뿐이다. 그것만 골라 그대로 올린다. 가르는 기준은 하나 —
# "시드나 pitch 에 따라 달라질 수 있는가".
#
#   [올린다] 시드·pitch 와 무관하다. 지도나 인자 자체가 틀렸다
#     pibt_scene   맵 파일을 찾을 수 없습니다
#                  pitch 는 0.1 m 의 배수여야 합니다
#                  어느 성분에도 스테이션이 없습니다
#
#   [칸에 넣는다] 칸마다 다를 수 있는 **결과**다. 표에 남아야 한다
#     계획기       PIBT(헤딩) 정체: N스텝 내 미도달 {...}
#     pibt_scene   도달 가능한 목표 스테이션이 없습니다   <- pitch 를 키우면 난다
#                  robot N: 시작 ... 에서 도달 가능한 목표가 없습니다  <- 시드별
#     battery      통행가능한 충전 도크가 없습니다 · 배터리 워치독 실패
#
# ★ 여기서는 앞의 도구들과 필터 방향이 **반대**다. 저쪽은 계획기 신호만
#   골라 잡았지만, 여기서 칸을 채우는 실패는 종류가 여럿이라 그럴 수 없다.
# ★ `RuntimeError` 는 그대로 잡는다 — `isaac_drive` 가 규칙 위반을 그것으로
#   알리고(14곳), 그게 바로 이 표가 보려는 결과다. 죽은 절이 아니다.
_SETUP_ERRORS = ("맵 파일", "0.1 m 의 배수", "어느 성분에도 스테이션")


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
        if any(k in str(e) for k in _SETUP_ERRORS):
            raise               # 전 칸이 똑같이 죽는다 — 한 번 죽는 편이 낫다
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
