# -*- coding: utf-8 -*-
"""**관측 지연 예산** — EMQX/ROS2 를 붙이기 전에 재 둔다 (S15P21A106-224).

왜 이 숫자가 먼저 필요한가
--------------------------
최종 구조는 EMQX 브로커와 ROS2 에이전트를 통과한다. 그러면 실행기가 보는
pose 가 **낡는다.** 그런데 `complete()` 가 바로 그 pose 로 판정한다:

    return not (body & action.released)          # isaac_drive.py

낡은 pose 로 「놓아줄 칸에서 빠져나왔다」고 하면, 아직 그 칸에 있는데 뒷차가
들어온다. 깨지는 것은 ADG 의 **순서** 보장이 아니라 **기하 여유**다.
ADG 는 「시간표가 아니라 순서」라 액션이 늦게 시작하는 것은 원래 견딘다.

여유가 얼마나 얇은지는 산수로 나온다.

    4칸 규칙 설계 여유   41.4 mm  /  v_max 0.9 m/s  =   46 ms
    도착 허용오차        50.0 mm  /  0.9            =   56 ms
    물리 스텝                                           16.7 ms

**설계 여유 전부가 로봇 이동 46 밀리초다.** 브로커 왕복과 같은 크기다.
그러니 붙이고 나서 접촉이 나면 「캐스터 때문인지 지연 때문인지」를 또 못
가린다. 붙이기 전에 재 둔다.

무엇을 재는가
-------------
`KinematicDriver.pose_lag` 로 관측 지연만 넣고 나머지는 고정한 채, 지연을
올려 가며 **어디서 깨지는지** 본다. Isaac 없이 돈다 (물리 없음, 적분만).

    접촉      contact_events        0 이어야 한다      <- 이게 기각선
    칸 공유   overlap_events        참고 (기하상 상시 발생)
    최소 간격 worst_gap             41.4 mm 아래로 가나
    완주      finished              교착 없이 끝나나

★ 여기서 깨지면 Isaac 에서도 깨진다. 반대는 보장 못 한다 — 물리가 없으니
  이 값은 **낙관적 상한**이다. 실제 예산은 이보다 작다.

쓰는 법
-------
    source paths.sh
    PITCH=1.0 N=12 SEED=7 python tools/lag_budget.py
    LAGS=0,33,50,67,83,100,133,200 python tools/lag_budget.py    # ms
    STOP_ON_BREAK=0   첫 깨짐 뒤에도 계속 돌린다

    SLIP/CLAG   구동기 쪽 미끄러짐·지연 (기본 0 — 지연만 보려고)
    SEEDS       시드 여러 개 "7,2,5"
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.environ["W"], "path"))

# ★ 주행과 **같은 환경**을 스스로 맞춘다 (-224). `run_record.sh:187` 이
#   `PIBT_FRONT_RULE=4` 를 기본으로 export 하는데, 도구에서 안 맞추면 4칸
#   규칙 없이 계획이 서고 그러면 **ADG 에 순환이 생긴다** (12/12 시드).
#   4칸 규칙의 남은 존재 이유가 바로 그 순환 방지다.
#
#   더 나쁜 경우는 순환이 안 나고 **조용히 다른 계획**을 재는 것이다.
#   실제로 그랬다 — 태스크 완료가 주행 13 개인데 도구는 15 개였다.
os.environ.setdefault("PIBT_FRONT_RULE", "4")
# 주기 진단은 끈다 — 판마다 수백 줄이 나와 결과 표를 덮는다. 여기서 볼 것은
# 「지연이 얼마까지 안전한가」 한 줄이고, 원인 분해는 `why_blocked.py` 몫이다.
os.environ.setdefault("ADG_WHY", "0")

import pibt_scene                                            # noqa: E402
import isaac_drive as idr                                    # noqa: E402

PITCH = float(os.environ.get("PITCH", os.environ.get("PIBT_PITCH", "1.0")))
N = int(os.environ.get("N", "12"))
HORIZON = int(os.environ.get("HORIZON", "1260"))
GAP = int(os.environ.get("GAP", "60"))
DT = 1.0 / float(os.environ.get("HZ", "60"))
SLIP = float(os.environ.get("SLIP", "0.0"))
CLAG = float(os.environ.get("CLAG", "0.0"))
LIMIT = int(os.environ.get("LIMIT", "400000"))
# 4칸 규칙 합법쌍 최소 여유. 이 아래로 가면 설계가 깨진 것이다.
DESIGN_GAP = float(os.environ.get("DESIGN_GAP", "0.0414"))
STOP_ON_BREAK = os.environ.get("STOP_ON_BREAK", "1") not in ("0", "", "false")


def build(seed):
    """계획 + ADG. 지연과 무관하므로 시드마다 한 번만 짓는다."""
    geom, free, starts, goals = pibt_scene.setup_lifelong(
        os.environ["MAP"], N, PITCH, seed, verbose=False)
    zone = pibt_scene.charge_zone_cells(free, geom)
    adg, order, history, _info = idr.plan_and_build_lifelong(
        free, starts, goals, geom, horizon=HORIZON, seed=seed,
        order_gap=GAP, zone_cells=zone, order_end=None)
    return geom, starts, adg, order, history


def run(geom, starts, adg, order, history, seed, pose_lag):
    drivers = idr.make_kinematic_drivers(geom, starts, seed=seed,
                                         slip=SLIP, lag=CLAG,
                                         pose_lag=pose_lag)
    # `release=True` 는 lifelong 경로다 (live_pibt 과 같게 맞춘다).
    f = idr.FleetController(geom, adg, drivers, order=order, release=True)
    f.starts = history[0]
    # 겹침 상세도 끈다 (쌍마다 첫 건이라도 판당 수십 줄이다). 판정에 쓰는
    # `worst_gap` 과 `contact_events` 는 그대로 집계된다 — 출력만 막는다.
    f._say = lambda *a, **k: None
    for _ in range(LIMIT):
        f.step(DT)
        for d in drivers.values():
            d.integrate(DT)
        if f.finished:
            break
    s = f.stats
    return {"contact": s.contact_events, "overlap": s.overlap_events,
            "gap": s.worst_gap, "done": f.finished,
            "acted": s.completed, "total": len(adg.actions),
            "t": s.sim_time}


def main():
    lags = [float(v) / 1000.0
            for v in os.environ.get("LAGS", "0,33,50,67,83,100,133,200").split(",")]
    seeds = [int(v) for v in os.environ.get(
        "SEEDS", os.environ.get("SEED", "7")).split(",")]

    print(f"[lag_budget] pitch {PITCH} · {N}대 · dt {DT * 1000:.1f}ms · "
          f"slip {SLIP} · 명령지연 {CLAG}")
    # ★ 어느 시스템을 잰 표인지 **표 자체로** 알 수 있어야 한다.
    print(f"   PIBT_FRONT_RULE={os.environ.get('PIBT_FRONT_RULE')} · "
          f"PIBT_SOFT_HOLD={os.environ.get('PIBT_SOFT_HOLD', '1')} · "
          f"horizon {HORIZON} · order_gap {GAP}")
    print(f"   설계 여유 {DESIGN_GAP * 1000:.1f} mm "
          f"= v_max 0.9 m/s 로 {DESIGN_GAP / 0.9 * 1000:.0f} ms 이동")
    print("   ★ 물리가 없어 이 값은 **낙관적 상한**이다. 실제 예산은 더 작다.")
    print(f"   ※ 실제 지연은 표본 간격 {DT * 1000:.1f}ms 로 **올림** 양자화된다 "
          f"(20 요청 -> 33.3 실현). 표의 **실현** 열로 판정한다.")

    worst_ok = {}
    for seed in seeds:
        print(f"\n── 시드 {seed} ──")
        try:
            geom, starts, adg, order, history = build(seed)
        except Exception as e:
            print(f"   ★ 계획 실패: {e!r}")
            if "순환" in str(e):
                print(f"     -> `PIBT_FRONT_RULE` 이 {os.environ.get('PIBT_FRONT_RULE')} "
                      f"이다. 4 가 아니면 그게 원인이다 — 4칸 규칙이 ADG")
                print(f"        순환을 막는다 (없으면 12/12 시드가 순환한다).")
            continue
        print(f"   액션 {len(adg.actions)} · 로봇 {len(starts)}")
        print(f"   {'요청':>7}{'실현':>8}{'접촉':>7}{'칸공유':>9}{'최소간격':>11}"
              f"{'완주':>7}{'액션':>13}{'시뮬':>9}")
        ok_upto = None
        for lag in lags:
            # 실현 지연은 표본 간격으로 올림된다 — 판정은 **실현값**으로 한다.
            real = 0.0 if lag <= 0 else math.ceil(lag / DT - 1e-9) * DT
            r = run(geom, starts, adg, order, history, seed, lag)
            safe = (r["contact"] == 0 and r["done"]
                    and r["gap"] >= DESIGN_GAP)
            if safe:
                ok_upto = real
            mark = "" if safe else "   <- 깨짐"
            print(f"   {lag * 1000:>6.0f}ms{real * 1000:>7.1f}ms"
                  f"{r['contact']:>7}{r['overlap']:>9}"
                  f"{r['gap'] * 1000:>10.1f}mm{'O' if r['done'] else 'X':>7}"
                  f"{r['acted']:>7}/{r['total']:<5}{r['t']:>8.1f}s{mark}",
                  flush=True)
            # 첫 깨짐에서 멈춘다 — 판 하나가 수십 초라 뒤를 다 돌 이유가 없다.
            # 더 보고 싶으면 `STOP_ON_BREAK=0`.
            if not safe and STOP_ON_BREAK:
                print(f"     (첫 깨짐에서 멈춘다. 뒤까지 보려면 STOP_ON_BREAK=0)")
                break
        worst_ok[seed] = ok_upto
        print(f"   ★ 시드 {seed} 안전 상한 "
              + (f"{ok_upto * 1000:.0f} ms" if ok_upto is not None else "**0 ms 도 안 됨**"))

    vals = [v for v in worst_ok.values() if v is not None]
    print(f"\n══ 예산 ══")
    if not vals or len(vals) < len(worst_ok):
        print("   ★ 어떤 시드는 지연 0 에서도 안 된다 — 지연 이전의 문제다.")
    if vals:
        b = min(vals)
        print(f"   모든 시드가 견딘 지연 = **{b * 1000:.0f} ms** "
              f"(시드별 {[f'{k}:{(v * 1000 if v else 0):.0f}' for k, v in worst_ok.items()]})")
        print(f"\n   이걸 어떻게 쓰나")
        print(f"    · 이 값이 **왕복 예산**이다. 발행 주기·QoS·큐 대기가 다 여기 든다.")
        print(f"    · 브로커 왕복이 이보다 크면 (v, w) 를 브로커 너머로 보내면 안 된다.")
        print(f"      경계를 **액션 단위**로 올린다 — FMS 는 「이 액션 시작」만 보내고")
        print(f"      제어 루프는 ROS2 에이전트 안에서 닫는다. 그러면 지연이 액션")
        print(f"      **시작 시각**에만 걸리고, 그건 ADG 가 원래 견디는 종류다.")
        print(f"    · 물리가 없는 값이라 실제로는 더 작다. Isaac 으로 한 번 더 잰다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
