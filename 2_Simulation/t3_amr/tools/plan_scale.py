# -*- coding: utf-8 -*-
"""**6시간 판을 우리 계획 층이 감당하나** (S15P21A106-224).

왜 먼저 재는가
--------------
FMS 재현 절차(2026-09-16)가 요구하는 판은 우리가 지금까지 돌린 것과 규모가
다르다.

    지금까지   1,260틱 · 12대   ->  계획 + ADG 가 1.4 초
    FMS 비교   77,760틱 · 24대   ->  틱 62배 · 로봇 2배

`build_adg` 는 칸 버킷이라 액션 수에 제곱은 아니다. 다만 규칙 ② 가

    for p in actions: for s in p.guard: for q in by_axle[s]

이라, **6시간 동안 같은 칸을 지나는 액션이 쌓이면** `by_axle[s]` 가 길어져
거기서 커진다. 얼마나 커지는지는 재 봐야 안다 -- 이게 「FMS 판을 돌릴 수
있나」를 정한다.

무엇을 재나
-----------
호라이즌 사다리를 올리며 **계획**과 **ADG 구축**을 따로 잰다. 둘의 증가
지수를 각각 뽑아 77,760틱으로 외삽한다. 액션 수·간선 수·메모리도 같이 낸다.

    지수 ~1.0   선형. 62배 판은 62배 시간
    지수 ~2.0   제곱. 62배 판은 3,800배 시간 -> 못 돌린다

쓰는 법
-------
    source paths.sh
    PITCH=1.0 N=24 python tools/plan_scale.py
    LADDER=1260,2520,5040,10080 N=24 python tools/plan_scale.py
"""
import math
import os
import resource
import sys
import time

sys.path.insert(0, os.path.join(os.environ["W"], "path"))

# 주행과 같은 환경으로 맞춘다 (lag_budget 에서 배운 것).
os.environ.setdefault("PIBT_FRONT_RULE", "4")
os.environ.setdefault("ADG_WHY", "0")

import pibt_scene                                            # noqa: E402
import isaac_drive as idr                                    # noqa: E402

PITCH = float(os.environ.get("PITCH", os.environ.get("PIBT_PITCH", "1.0")))
N = int(os.environ.get("N", "24"))
SEED = int(os.environ.get("SEED", "103"))
GAP = int(os.environ.get("GAP", "60"))
TARGET = int(os.environ.get("TARGET", "77760"))      # FMS 6h
SHIFTS = tuple(os.environ.get("SHIFTS", "out").split(","))


def rss_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def once(horizon):
    geom, free, starts, goals = pibt_scene.setup_lifelong(
        os.environ["MAP"], N, PITCH, SEED, verbose=False)
    zone = pibt_scene.charge_zone_cells(free, geom)

    # 계획과 ADG 를 **따로** 잰다 — 증가 지수가 다를 수 있고, 둘 중 하나만
    # 터지면 대책도 다르다.
    from lifelong import run_lifelong
    t0 = time.perf_counter()
    history, cells_hist, _info = run_lifelong(
        free, starts, goals, horizon=horizon, seed=SEED, order_gap=GAP,
        shifts=SHIFTS, zone_cells=zone, order_end=None, verbose=False)
    t_plan = time.perf_counter() - t0

    t0 = time.perf_counter()
    chains, order, _st = idr.extract_actions(history, geom)
    t_ext = time.perf_counter() - t0

    t0 = time.perf_counter()
    adg = idr.build_adg(chains)
    t_adg = time.perf_counter() - t0

    n_act = len(adg.actions)
    e1 = sum(len(v) for v in adg.preds.values())
    return {"horizon": horizon, "plan": t_plan, "ext": t_ext, "adg": t_adg,
            "actions": n_act, "edges": e1, "rss": rss_mb()}


def fit(xs, ys):
    """로그-로그 최소제곱 기울기 = 증가 지수."""
    lx = [math.log(x) for x in xs]
    ly = [math.log(max(y, 1e-9)) for y in ys]
    n = len(lx)
    mx, my = sum(lx) / n, sum(ly) / n
    den = sum((a - mx) ** 2 for a in lx)
    if den <= 1e-12:
        return float("nan")
    return sum((a - mx) * (b - my) for a, b in zip(lx, ly)) / den


def main():
    ladder = [int(v) for v in
              os.environ.get("LADDER", "1260,2520,5040,10080").split(",")]
    print(f"[plan_scale] pitch {PITCH} · {N}대 · 시드 {SEED} · "
          f"order_gap {GAP} · shifts {SHIFTS}")
    print(f"   PIBT_FRONT_RULE={os.environ.get('PIBT_FRONT_RULE')} · "
          f"목표 {TARGET:,}틱 (FMS 6h)")
    print(f"\n   {'틱':>8}{'계획s':>9}{'추출s':>8}{'ADGs':>8}{'합s':>9}"
          f"{'액션':>10}{'간선':>11}{'RSS MB':>10}")
    rows = []
    for h in ladder:
        try:
            r = once(h)
        except Exception as e:
            print(f"   {h:>8,}  ★ 실패: {e!r}")
            break
        rows.append(r)
        print(f"   {r['horizon']:>8,}{r['plan']:>9.2f}{r['ext']:>8.2f}"
              f"{r['adg']:>8.2f}{r['plan'] + r['ext'] + r['adg']:>9.2f}"
              f"{r['actions']:>10,}{r['edges']:>11,}{r['rss']:>10.0f}",
              flush=True)

    if len(rows) < 3:
        print("\n   ★ 사다리가 3칸 미만이라 외삽하지 않는다.")
        return 1

    xs = [r["horizon"] for r in rows]
    print(f"\n── 증가 지수 (로그-로그 기울기) ──")
    out = {}
    for key, lab in (("plan", "계획"), ("ext", "추출"), ("adg", "ADG 구축"),
                     ("actions", "액션 수"), ("edges", "간선 수")):
        k = fit(xs, [r[key] for r in rows])
        out[key] = k
        note = ""
        if key in ("plan", "ext", "adg"):
            note = ("   선형" if k < 1.25 else
                    "   ★ 초선형 — 주의" if k < 1.75 else
                    "   ☠ 제곱에 가깝다")
        print(f"   {lab:<10} {k:+.2f}{note}")

    print(f"\n── {TARGET:,}틱 외삽 ──")
    base = rows[-1]
    scale = TARGET / base["horizon"]
    tot = 0.0
    for key, lab in (("plan", "계획"), ("ext", "추출"), ("adg", "ADG 구축")):
        est = base[key] * scale ** out[key]
        tot += est
        print(f"   {lab:<10} {est:>10.0f}s = {est / 60:>6.1f}분")
    print(f"   {'합':<10} {tot:>10.0f}s = {tot / 60:>6.1f}분"
          f"  ({tot / 3600:.1f}시간)")
    for key, lab, unit in (("actions", "액션 수", ""), ("edges", "간선 수", ""),
                           ("rss", "RSS", " MB")):
        k = out.get(key, 1.0)
        print(f"   {lab:<10} {base[key] * scale ** k:>10,.0f}{unit}")

    print(f"\n   읽는 법")
    print(f"    · 합이 **10분 안쪽**이면 그냥 돌리면 된다.")
    print(f"    · 30분을 넘으면 구간을 잘라 돌리는 것을 생각한다 — FMS 는")
    print(f"      「커널이 결정적이라 짧은 런의 궤적은 긴 런의 앞부분과 정확히")
    print(f"      같다」고 했다. 포화 창이 6,480~38,880틱이므로 **38,880틱까지만**")
    print(f"      돌려도 §4-4 지표는 나온다 (6h 평균은 못 낸다).")
    print(f"    · 외삽은 마지막 칸 기준이라 사다리가 짧으면 오차가 크다.")
    print(f"      지수가 1.25 를 넘으면 사다리를 한 칸 더 올려 다시 본다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
