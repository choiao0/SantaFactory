# -*- coding: utf-8 -*-
"""STALL 진단 — 대치(standoff, -79) 상태기계 관점 (D2, 2026-09-15).

    cd 3_FMS/sim_engine
    SIM_NO_PLOT=1 PYTHONPATH=. python checks/diag_hd.py base 6 40 42 1 --footprint=exact,front [--at=<틱>] [--events=N]

sim_v2_tasks 와 같은 인자로 돌리다 StallError 가 나면(또는 --at 틱에 이르면) 기본 STALL 덤프 뒤에
  1) 로봇별 대치 필드 hd_peer/hd_role/hd_until/hd_swapped · stag · busy · swing/swing_soft
  2) 대치 쌍마다 지는 쪽의 forbid(칸)·forbid_axle(축) 집합과, 그 제약 아래 후보 하나하나가 왜 막히는지(사유)
  3) 대치 이벤트 통계(standoff/swap 수, 쌍별 횟수)와 최근 N건
을 찍는다. 저장소 코드는 건드리지 않는다(읽기 전용 진단).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import Counter  # noqa: E402

from fms_kernel import StallError  # noqa: E402
from pibt.geometry import occupied, turn_ok  # noqa: E402
from pibt.heading import _action_kind, candidates_h  # noqa: E402
from pibt.liveness import wait_bias  # noqa: E402
from sim_v2_tasks import build, parse_args  # noqa: E402


class _Stop(Exception):
    pass


def _run(kernel, stream, horizon, at):
    """sim_v2_tasks.run_ticks 와 같은 틱 루프 — 멈춘 틱 t 를 알아야 해서 여기서 돈다."""
    t = 0
    try:
        while (stream.outstanding > 0) if horizon is None else (t < horizon):
            if at is not None and t >= at:
                raise _Stop()
            for task in stream.arrivals(t):
                kernel.submit_task(task)
            kernel.dispatch(t)
            if horizon is None and stream.outstanding == 0:
                break
            kernel.move(t)
            t += 1
    except StallError as e:
        print(str(e))
        return t, "STALL"
    except _Stop:
        return t, "AT"
    return t, "DONE"


def _reasons(kernel, rid, s, cand, forbid, forbid_axle, occ_now, axle_now, soft_hold):
    """후보 하나가 이번 틱 왜 못 뽑히는지 — resolve() 의 검사 순서를 흉내 (예약 순서 효과는 제외, 현 점유 기준)."""
    s2, cells, soft = cand
    why = []
    if s2 == s:
        cells = frozenset(occupied(s)) | set(kernel.robots[rid]["swing"])
    blk = {c: occ_now[c] for c in cells if occ_now.get(c, rid) != rid}
    if blk:
        why.append(f"몸/스윙 점유 {blk}")
    fb = cells & forbid.get(rid, frozenset())
    if fb:
        why.append(f"forbid {sorted(fb)}")
    fa = forbid_axle.get(rid, frozenset())
    if s2[:2] in fa:
        why.append(f"forbid_axle {s2[:2]}")
    if soft_hold.get(s2[:2], rid) != rid:
        why.append(f"축 자리가 soft_hold(robot{soft_hold[s2[:2]]})")
    sb = {c: axle_now[c] for c in soft if axle_now.get(c, rid) != rid}
    if sb:
        why.append(f"soft 칸에 상대 축 {sb}")
    if s2[:2] == s[:2] and s2[2] != s[2] and not turn_ok(kernel.free, s[0], s[1], s[2], s2[2]):
        why.append("turn_ok False")
    return why


def diag(kernel, t, n_events, robots_only=()):
    robots, rids = kernel.robots, kernel.rids
    states = {rid: (robots[rid]["pos"][0], robots[rid]["pos"][1], robots[rid]["h"]) for rid in rids}
    extra = {rid: robots[rid]["swing"] for rid in rids if robots[rid]["busy"] > 0}
    soft_hold = {cell: rid for rid in rids if robots[rid]["busy"] > 0 for cell in robots[rid]["swing_soft"]}
    dists = kernel._dists_h(t, states, extra)
    forbid, forbid_axle = kernel._standoff_forbid(states, dists)
    occ_now = {c: rid for rid in rids for c in set(occupied(states[rid])) | set(extra.get(rid, ()))}
    axle_now = {states[rid][:2]: rid for rid in rids}

    print(f"\n[DIAG t={t}] hd_after={kernel.cfg.hd_after} hd_timeout={kernel.cfg.hd_timeout} "
          f"standoffs={kernel.standoffs} swaps={kernel.standoff_swaps}")
    if robots_only:
        patient = kernel._patient(states, dists, extra, soft_hold)
        print("  --- 지정 로봇 후보 (점수 = 액션비용 + dist, 대기엔 bias 가산) ---")
        for rid in robots_only:
            rb, s = robots[rid], states[rid]
            b = 0.0 if rid in patient else wait_bias(kernel._stag.get(rid))
            print(f"  robot{rid} {s} {rb['state']} goal={rb['goal']} stag={kernel._stag.get(rid)} busy={rb['busy']} "
                  f"hd={rb['hd_role']}/{rb['hd_peer']} bias={b:.0f}{' (인내)' if rid in patient else ''} "
                  f"swing={sorted(rb['swing'])} soft={sorted(rb['swing_soft'])}")
            for cand in candidates_h(s, dists[rid], kernel.edge_cost, kernel.wait_cost, kernel.free, kernel.turn_cost, b):
                why = _reasons(kernel, rid, s, cand, forbid, forbid_axle, occ_now, axle_now, soft_hold)
                d = dists[rid][cand[0]]
                kind = _action_kind(s, cand[0])
                print(f"       {kind:4s} -> {cand[0]} dist={d:.1f} {'OK' if not why else '✗ ' + '; '.join(why)}")
    print("  --- 로봇 (미도달 또는 대치 중) ---")
    for rid in rids:
        rb = robots[rid]
        if rb["pos"] == rb["goal"] and rb["hd_peer"] is None:
            continue
        print(f"  robot{rid} {states[rid]} {rb['state']} goal={rb['goal']} stag={kernel._stag.get(rid)} busy={rb['busy']} "
              f"hd_peer={rb['hd_peer']} role={rb['hd_role']} until={rb['hd_until']} swapped={rb['hd_swapped']} "
              f"swing={sorted(rb['swing'])} soft={sorted(rb['swing_soft'])} bias={wait_bias(kernel._stag.get(rid)):.0f}")

    print("  --- 대치 쌍 ---")
    seen = set()
    for rid in rids:
        rb = robots[rid]
        peer = rb["hd_peer"]
        if peer is None or frozenset((rid, peer)) in seen:
            continue
        seen.add(frozenset((rid, peer)))
        w, l = (rid, peer) if rb["hd_role"] == "W" else (peer, rid)
        print(f"  W=robot{w} {states[w]}  L=robot{l} {states[l]}  until={rb['hd_until']} (남은 {rb['hd_until'] - t}틱)")
        hard, soft = kernel._wish_cells(w, states, dists)
        print(f"    W wish hard={sorted(hard)} soft={sorted(soft)}")
        print(f"    L forbid={sorted(forbid.get(l, ()))}  forbid_axle={sorted(forbid_axle.get(l, ()))}")
        for who in (l, w):
            s = states[who]
            cands = candidates_h(s, dists[who], kernel.edge_cost, kernel.wait_cost, kernel.free, kernel.turn_cost)
            legal = 0
            print(f"    {'L' if who == l else 'W'} robot{who} 후보 (dist={dists[who][s]:.1f}):")
            for cand in cands:
                why = _reasons(kernel, who, s, cand, forbid, forbid_axle, occ_now, axle_now, soft_hold)
                legal += not why
                print(f"       {_action_kind(s, cand[0]):4s} -> {cand[0]} dist={dists[who][cand[0]]:.1f} "
                      f"{'OK' if not why else '✗ ' + '; '.join(why)}")
            if legal == 0:
                print(f"       ⚠ robot{who}: 제약 아래 합법 후보 0 (대기 포함) → 제자리 고정")
    if not seen:
        print("  (대치 쌍 없음)")

    print("  --- 대치 이벤트 ---")
    ev = kernel.yield_events
    by_action = Counter(e["action"] for e in ev)
    by_pair = Counter(frozenset((e["yielder"], e["peer"])) for e in ev)
    print(f"  총 {len(ev)}건 {dict(by_action)}; 쌍 {len(by_pair)}개, 최다 {[(sorted(p), n) for p, n in by_pair.most_common(5)]}")
    for e in ev[-n_events:]:
        print(f"   t={e['t']:>6} {e['action']:<8} L=robot{e['yielder']} W=robot{e['peer']}")


def main(argv):
    at = next((int(f.split("=", 1)[1]) for f in argv if f.startswith("--at=")), None)
    n_events = next((int(f.split("=", 1)[1]) for f in argv if f.startswith("--events=")), 20)
    robots_only = next((tuple(int(x) for x in f.split("=", 1)[1].split(",")) for f in argv if f.startswith("--robots=")), ())
    argv = [f for f in argv if not f.startswith(("--at=", "--events=", "--robots="))]
    a = parse_args(argv)
    kernel, stream, ctx = build(a)
    for w in a.warnings:
        print(w)
    t, how = _run(kernel, stream, a.horizon, at)
    print(f"[RUN] {how} t={t} done={len(kernel.tasks_done)}")
    if how == "DONE":
        ev = kernel.yield_events
        by_action = Counter(e["action"] for e in ev)
        by_pair = Counter(frozenset((e["yielder"], e["peer"])) for e in ev)
        print(f"  대치 이벤트 총 {len(ev)}건 {dict(by_action)}; 쌍 {len(by_pair)}개, "
              f"최다 {[(sorted(p), n) for p, n in by_pair.most_common(5)]}")
        for e in ev[-n_events:]:
            print(f"   t={e['t']:>6} {e['action']:<8} L=robot{e['yielder']} W=robot{e['peer']}")
        return
    diag(kernel, t, n_events, robots_only)


if __name__ == "__main__":
    main(sys.argv[1:])
