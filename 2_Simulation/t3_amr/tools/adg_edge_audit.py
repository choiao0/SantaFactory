# -*- coding: utf-8 -*-
"""ADG 규칙 ② 간선이 **중복인가** (S15P21A106-224).

무엇이 문제인가
---------------
`tools/plan_scale.py` 로 재니 6시간 판(77,760틱·24대)이 못 돈다.

    계획   +0.81 지수   선형
    추출   +0.88        선형
    ADG    +2.56        ☠ 제곱
    -> 외삽 5.8억 간선 · 14.8 GB · 19분

터지는 곳은 규칙 ② 하나다.

    규칙 ①  for p, n in zip(users, users[1:])      인접 쌍만  -> 선형
    규칙 ②  for p: for s in p.guard: for q in by_axle[s]      전부 쌍  -> 제곱

6시간이면 한 칸을 수천 번 지나므로 `by_axle[s]` 가 길어지고, 거기에 모든 p 를
곱한다.

중복이라는 근거
---------------
축 칸은 `hard` 에도 들어간다 (`hard = cells - soft`, `soft = guard & cells`
인데 자기 축은 자기 guard 에 없다). 그러면 **규칙 ① 이 그 칸의 사용자를 이미
시간순 사슬로 묶어 둔다.**

    q1 -> q2 -> q3 (규칙 ①)

여기에 p 가 q1 보다 앞서야 한다면 `p -> q1` 하나로 `p ~> q2, q3` 가 따라온다.
**나머지 N-1 개는 전이로 이미 성립하는 중복 간선이다.**

이 도구는 그 전제를 **실제 데이터로** 확인한다. 전제가 깨지면(축 칸이 hard 에
없거나, 사슬이 안 이어지거나) 최적화는 못 한다.

    ★ `build_adg` 를 고치지 않는다. 재기만 한다.

쓰는 법
-------
    source paths.sh
    PITCH=1.0 N=24 SEED=103 LADDER=1260,2520,5040 python tools/adg_edge_audit.py
"""
import bisect
import os
import sys

sys.path.insert(0, os.path.join(os.environ["W"], "path"))

os.environ.setdefault("PIBT_FRONT_RULE", "4")
os.environ.setdefault("ADG_WHY", "0")

import pibt_scene                                            # noqa: E402
import isaac_drive as idr                                    # noqa: E402

PITCH = float(os.environ.get("PITCH", os.environ.get("PIBT_PITCH", "1.0")))
N = int(os.environ.get("N", "24"))
SEED = int(os.environ.get("SEED", "103"))
GAP = int(os.environ.get("GAP", "60"))
SHIFTS = tuple(os.environ.get("SHIFTS", "out").split(","))


def audit(horizon):
    geom, free, starts, goals = pibt_scene.setup_lifelong(
        os.environ["MAP"], N, PITCH, SEED, verbose=False)
    zone = pibt_scene.charge_zone_cells(free, geom)
    from lifelong import run_lifelong
    history, _c, _i = run_lifelong(
        free, starts, goals, horizon=horizon, seed=SEED, order_gap=GAP,
        shifts=SHIFTS, zone_cells=zone, order_end=None, verbose=False)
    chains, _order, _st = idr.extract_actions(history, geom)
    actions = [a for ch in chains for a in ch]

    by_hard, by_axle = {}, {}
    for a in actions:
        for c in a.hard:
            by_hard.setdefault(c, []).append(a)
        for c in a.axle:
            by_axle.setdefault(c, []).append(a)

    # ── 전제 1 — 축 칸 사용자가 전부 hard 사용자인가 ──────────────────────
    bad_cells, bad_pairs = 0, 0
    for s, qs in by_axle.items():
        hs = set(id(x) for x in by_hard.get(s, ()))
        miss = [q for q in qs if id(q) not in hs]
        if miss:
            bad_cells += 1
            bad_pairs += len(miss)

    # ── 전제 2 — 지금 규칙 ② 가 만드는 간선 수 vs 인접만 쓸 때 ────────────
    key = idr._key
    order_cache = {}
    for s, qs in by_axle.items():
        qs2 = sorted(qs, key=lambda a: key(a, s))
        order_cache[s] = (qs2, [key(a, s) for a in qs2])

    now_pairs = 0        # 지금: p x |by_axle[s]|
    slim_pairs = 0       # 제안: p 당 앞뒤 각 1 개
    for p in actions:
        for s in p.guard:
            qs2, ks = order_cache.get(s, ((), ()))
            if not qs2:
                continue
            now_pairs += len(qs2)
            kp = key(p, s)
            i = bisect.bisect_left(ks, kp)
            # 바로 앞 · 바로 뒤 각각 하나 (자기 자신은 축 사용자가 아니다)
            slim_pairs += (1 if i > 0 else 0) + (1 if i < len(qs2) else 0)

    tops = sorted(((len(v), s) for s, v in by_axle.items()), reverse=True)[:5]
    return {"horizon": horizon, "actions": len(actions),
            "now": now_pairs, "slim": slim_pairs,
            "bad_cells": bad_cells, "bad_pairs": bad_pairs,
            "cells": len(by_axle), "tops": tops}


def main():
    ladder = [int(v) for v in
              os.environ.get("LADDER", "1260,2520,5040").split(",")]
    print(f"[adg_edge_audit] pitch {PITCH} · {N}대 · 시드 {SEED} · "
          f"PIBT_FRONT_RULE={os.environ.get('PIBT_FRONT_RULE')}")
    print(f"\n   {'틱':>8}{'액션':>9}{'축칸':>8}"
          f"{'지금 ②쌍':>13}{'인접만':>11}{'줄어듦':>9}"
          f"{'전제깨짐':>10}")
    rows = []
    for h in ladder:
        r = audit(h)
        rows.append(r)
        cut = (1.0 - r["slim"] / r["now"]) * 100 if r["now"] else 0.0
        print(f"   {r['horizon']:>8,}{r['actions']:>9,}{r['cells']:>8,}"
              f"{r['now']:>13,}{r['slim']:>11,}{cut:>8.1f}%"
              f"{r['bad_pairs']:>10,}", flush=True)

    last = rows[-1]
    print(f"\n── 전제 검사 ──")
    if last["bad_pairs"] == 0:
        print(f"   ★ 축 칸 사용자가 **전부** hard 사용자다 "
              f"({last['cells']:,} 칸 전수).")
        print(f"     -> 규칙 ① 이 그 칸의 사용자를 시간순 사슬로 묶는다.")
        print(f"     -> p -> q1 하나면 q2, q3 … 는 **전이로 따라온다.**")
        print(f"        나머지는 중복 간선이고, 빼도 도달 관계가 안 변한다.")
    else:
        print(f"   ☠ 축 칸 사용자 {last['bad_pairs']:,} 개가 hard 에 없다 "
              f"({last['bad_cells']:,} 칸).")
        print(f"     -> 사슬이 안 이어지므로 **이 최적화는 못 한다.**")

    print(f"\n── 한 칸을 가장 많이 쓴 곳 (마지막 사다리) ──")
    for cnt, s in last["tops"]:
        print(f"   {str(s):<14} {cnt:,} 개 액션의 축이 지나간다")
    print(f"\n   ※ 이 수가 호라이즌에 비례해 늘고, 규칙 ② 는 여기에 p 를")
    print(f"     곱한다. 그래서 제곱이 된다.")
    print(f"\n   ★ `build_adg` 는 건드리지 않았다. 재기만 했다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
