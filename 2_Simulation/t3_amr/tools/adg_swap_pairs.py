# -*- coding: utf-8 -*-
"""ADG 고리의 원인을 **쌍 단위로** 센다 — 「고칠 수 있나」를 먼저 답한다 (S15P21A106-240).

무엇이 밝혀졌길래
-----------------
FMS 공식 궤적(v3.15 · 1시간 · `--footprint=exact`)이 우리 ADG 에서 **어느
발자국으로도 순환**이다. 고리를 뽑아 보니 길이 2 였다.

    A5  turn(69,34,1)->(69,34,0) @t12496   hard (68,33)(68,34)(69,33)(69,34)(69,35)(70,34)
    A10 turn(68,35,2)->(68,35,3) @t12496   hard (67,35)(68,34)(68,35)(68,36)(69,35)(69,36)
    공유 칸 **둘** — (68,34) · (69,35)

`_key(action, cell)` 의 가운데 필드가 **칸의 함수**다.

    return (action.tick, 0 if cell in occupied(action.frm) else 1, action.agent)

    칸 (68,34)  A5 (t,1,5) · A10 (t,1,10)  ->  5 먼저  ->  5→10
    칸 (69,35)  A5 (t,1,5) · A10 (t,**0**,10) ->  10 먼저 -> 10→5

**양방향 간선.** 주석의 「`(tick, sub, agent)` 가 전순서라 순환이 생길 수 없다」가
성립하지 않는다 — `sub` 이 칸마다 달라 전순서가 아니다.

고치는 길이 둘인데 먼저 답할 것이 있다
--------------------------------------
    가  쌍마다 방향을 **한 번만** 정한다.  보는 칸은 그대로
    나  hard 에서 코가 쓰는 앞 칸을 뺀다 (6 -> 4).  ☹ 물리에서 닿는다

「가」가 통하려면 **방향을 정할 수 있어야** 한다. `sub` 이 하던 일
(leave-before-enter — 그 칸을 이미 갖고 있던 쪽이 먼저)이 두 칸에서 **엇갈리면**
순차 실행으로는 원리적으로 못 편다. PIBT 는 한 틱에 다 같이 움직여 그걸
허용하지만 ADG 는 순서 그래프다.

이 도구가 그 수를 센다.

    ① 공유 칸이 둘 이상인 **같은 틱** 쌍
    ② 그중 `sub` 이 칸마다 갈리는 쌍            <- 지금 고리를 만드는 것
    ③ 그중 **leave-before-enter 가 엇갈리는** 쌍  <- **못 푸는 것**

    ③ 이 0 이면 「가」로 전부 풀린다.
    0 이 아니면 그 수가 FMS 편지의 새 항목이다 — 순차 실행으로 못 돌리는 계획이다.

쓰는 법
-------
    source paths.sh
    PIBT_FMS_GRID=1 python tools/adg_swap_pairs.py <trajectories.json>
    # 우리 계획으로 보려면 (궤적 없이)
    PIBT_SWING_HARD=1 SEEDS=2,5,9 python tools/adg_swap_pairs.py
"""
import collections
import os
import sys

sys.path.insert(0, os.path.join(os.environ["W"], "path"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pibt_core_v2 as _pc                              # noqa: E402  (sim_engine 을 경로에)
import isaac_drive as D                                 # noqa: E402
import pibt_scene as PS                                 # noqa: E402

PITCH = float(os.environ.get("PIBT_PITCH", "1.0"))


def analyse(chains, verbose=True):
    """같은 틱 · 공유 칸 2개 이상인 쌍을 훑어 ①②③ 을 센다."""
    actions = [a for ch in chains for a in ch]
    by_hard = collections.defaultdict(list)
    for a in actions:
        for c in a.hard:
            by_hard[c].append(a)

    # 쌍 -> 공유 칸 목록. **같은 틱**만 본다 (다른 틱이면 tick 이 순서를 정한다)
    shared = collections.defaultdict(list)
    for cell, users in by_hard.items():
        for i, p in enumerate(users):
            for q in users[i + 1:]:
                if p.agent == q.agent or p.tick != q.tick:
                    continue
                key = (p.uid, q.uid) if p.uid < q.uid else (q.uid, p.uid)
                shared[key].append(cell)

    by_uid = {a.uid: a for a in actions}
    multi, flipped, unfixable, ex = 0, 0, [], []
    for (u, v), cells in shared.items():
        if len(cells) < 2:
            continue
        multi += 1
        p, q = by_uid[u], by_uid[v]
        # 칸마다 누가 먼저인가 — `_key` 그대로 쓴다 (정의가 두 벌이 되면 안 된다)
        first = {c: (u if D._key(p, c) < D._key(q, c) else v) for c in cells}
        if len(set(first.values())) < 2:
            continue                                   # 방향이 일관 — 고리 안 난다
        flipped += 1
        # ③ **소유 쪽이 엇갈리나** — 어느 칸에서는 p 가 갖고 있고 다른 칸에서는 q 가
        own_p = [c for c in cells if c in D.occupied(p.frm)]
        own_q = [c for c in cells if c in D.occupied(q.frm)]
        if own_p and own_q:
            unfixable.append(((u, v), cells, own_p, own_q))
        elif len(ex) < 3:
            ex.append(((u, v), cells, own_p, own_q))

    if verbose:
        print(f"\n  같은 틱 · 공유 칸 2개 이상인 쌍      **{multi:,}**")
        print(f"  그중 칸마다 순서가 갈리는 쌍(고리)   **{flipped:,}**")
        print(f"  그중 **소유가 엇갈리는 쌍(못 품)**    **{len(unfixable):,}**")
        for (uv, cells, op, oq) in unfixable[:3]:
            a, b = by_uid[uv[0]], by_uid[uv[1]]
            print(f"     ☹☹ {a}  ·  {b}")
            print(f"        공유 {sorted(cells)}  A{a.agent} 소유 {op}  A{b.agent} 소유 {oq}")
        for (uv, cells, op, oq) in ex[:2]:
            a, b = by_uid[uv[0]], by_uid[uv[1]]
            print(f"     ★ 풀리는 예: {a}  ·  {b}")
            print(f"        공유 {sorted(cells)}  A{a.agent} 소유 {op}  A{b.agent} 소유 {oq}")
        print("\n  읽는 법")
        print("    셋째 줄이 **0** 이면 「가」(쌍마다 방향을 한 번만)로 전부 풀린다")
        print("    0 이 아니면 그 쌍들은 **동시 교대**라 순서 그래프로 못 편다 —")
        print("    PIBT 는 한 틱에 같이 움직여 허용하지만 ADG 는 순차다")
    return dict(multi=multi, flipped=flipped, unfixable=len(unfixable))


def main():
    if len(sys.argv) > 1:                              # 궤적에서
        import fms_traj as FT
        geom = PS.make_geom(PITCH)
        hist, meta = FT.load_history(sys.argv[1], verbose=True)
        chains, _o, _s = D.extract_actions(hist, geom)
        print(f"[adg_swap_pairs] 궤적 · 동작 {sum(len(c) for c in chains):,}개")
        analyse(chains)
        return 0

    import swing_overlap as SO                         # 우리 계획으로
    tot = collections.Counter()
    for seed in SO.SEEDS:
        import turn_pair_margin as TPM
        geom, hist, li = TPM.run_history(seed)
        chains, _o, _s = D.extract_actions(hist, geom)
        print(f"\n[adg_swap_pairs] seed {seed} · 동작 {sum(len(c) for c in chains):,}개")
        for k, v in analyse(chains).items():
            tot[k] += v
    print(f"\n  합계 {dict(tot)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
