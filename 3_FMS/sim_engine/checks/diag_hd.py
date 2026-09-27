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


class _Snap:
    """진단 시점의 커널 상태 한 벌 — 후보 차단 사유(_reasons)가 쓰는 표들을 한 번만 만든다."""

    def __init__(self, kernel, t):
        robots, rids = kernel.robots, kernel.rids
        self.kernel, self.t = kernel, t
        self.states = {rid: (robots[rid]["pos"][0], robots[rid]["pos"][1], robots[rid]["h"]) for rid in rids}
        self.extra = {rid: robots[rid]["swing"] for rid in rids if robots[rid]["busy"] > 0}
        self.soft_hold = {cell: rid for rid in rids if robots[rid]["busy"] > 0 for cell in robots[rid]["swing_soft"]}
        self.dists = kernel._dists_h(t, self.states, self.extra)
        self.forbid, self.forbid_axle = kernel._standoff_forbid(self.states, self.dists)
        self.occ_now = {c: rid for rid in rids for c in set(occupied(self.states[rid])) | set(self.extra.get(rid, ()))}
        self.axle_now = {self.states[rid][:2]: rid for rid in rids}

    def candidates(self, rid, bias=0.0):
        s = self.states[rid]
        k = self.kernel
        return candidates_h(s, self.dists[rid], k.edge_cost, k.wait_cost, k.free, k.turn_cost, bias)

    def reasons(self, rid, cand):
        return _reasons(self.kernel, rid, self.states[rid], cand, self.forbid, self.forbid_axle,
                        self.occ_now, self.axle_now, self.soft_hold)

    def print_candidates(self, rid, bias=0.0):
        """후보를 점수순으로 찍고 합법(차단 사유 없음) 후보 수를 돌려준다."""
        s, legal = self.states[rid], 0
        for cand in self.candidates(rid, bias):
            why = self.reasons(rid, cand)
            legal += not why
            verdict = "OK" if not why else "✗ " + "; ".join(why)
            print(f"       {_action_kind(s, cand[0]):4s} -> {cand[0]} dist={self.dists[rid][cand[0]]:.1f} {verdict}")
        return legal


def _robot_line(kernel, snap, rid):
    rb = kernel.robots[rid]
    return (f"robot{rid} {snap.states[rid]} {rb['state']} goal={rb['goal']} stag={kernel._stag.get(rid)} "
            f"busy={rb['busy']}")


def _print_selected(kernel, snap, robots_only):
    """--robots 로 지정한 로봇의 후보 — 실제 결정과 같은 bias(인내 포함)로."""
    patient = kernel._patient(snap.states, snap.dists, snap.extra, snap.soft_hold)
    print("  --- 지정 로봇 후보 (점수 = 액션비용 + dist, 대기엔 bias 가산) ---")
    for rid in robots_only:
        rb = kernel.robots[rid]
        b = 0.0 if rid in patient else wait_bias(kernel._stag.get(rid))
        note = " (인내)" if rid in patient else ""
        print(f"  {_robot_line(kernel, snap, rid)} hd={rb['hd_role']}/{rb['hd_peer']} bias={b:.0f}{note} "
              f"swing={sorted(rb['swing'])} soft={sorted(rb['swing_soft'])}")
        snap.print_candidates(rid, b)


def _print_unfinished(kernel, snap):
    print("  --- 로봇 (미도달 또는 대치 중) ---")
    for rid in kernel.rids:
        rb = kernel.robots[rid]
        if rb["pos"] == rb["goal"] and rb["hd_peer"] is None:
            continue
        print(f"  {_robot_line(kernel, snap, rid)} "
              f"hd_peer={rb['hd_peer']} role={rb['hd_role']} until={rb['hd_until']} swapped={rb['hd_swapped']} "
              f"swing={sorted(rb['swing'])} soft={sorted(rb['swing_soft'])} bias={wait_bias(kernel._stag.get(rid)):.0f}")


def _standoff_pairs(kernel):
    """(W, L, hd_until) — 쌍마다 한 번."""
    seen, out = set(), []
    for rid in kernel.rids:
        rb = kernel.robots[rid]
        peer = rb["hd_peer"]
        if peer is None or frozenset((rid, peer)) in seen:
            continue
        seen.add(frozenset((rid, peer)))
        w, l = (rid, peer) if rb["hd_role"] == "W" else (peer, rid)
        out.append((w, l, rb["hd_until"]))
    return out


def _print_pairs(kernel, snap):
    print("  --- 대치 쌍 ---")
    pairs = _standoff_pairs(kernel)
    for w, l, until in pairs:
        print(f"  W=robot{w} {snap.states[w]}  L=robot{l} {snap.states[l]}  until={until} (남은 {until - snap.t}틱)")
        hard, soft = kernel._wish_cells(w, snap.states, snap.dists)
        print(f"    W wish hard={sorted(hard)} soft={sorted(soft)}")
        print(f"    L forbid={sorted(snap.forbid.get(l, ()))}  forbid_axle={sorted(snap.forbid_axle.get(l, ()))}")
        for role, who in (("L", l), ("W", w)):
            print(f"    {role} robot{who} 후보 (dist={snap.dists[who][snap.states[who]]:.1f}):")
            if snap.print_candidates(who) == 0:
                print(f"       ⚠ robot{who}: 제약 아래 합법 후보 0 (대기 포함) → 제자리 고정")
    if not pairs:
        print("  (대치 쌍 없음)")


def _print_events(ev, n_events, head):
    by_action = Counter(e["action"] for e in ev)
    by_pair = Counter(frozenset((e["yielder"], e["peer"])) for e in ev)
    print(f"{head}{len(ev)}건 {dict(by_action)}; 쌍 {len(by_pair)}개, 최다 {[(sorted(p), n) for p, n in by_pair.most_common(5)]}")
    for e in ev[-n_events:]:
        print(f"   t={e['t']:>6} {e['action']:<8} L=robot{e['yielder']} W=robot{e['peer']}")


def diag(kernel, t, n_events, robots_only=()):
    snap = _Snap(kernel, t)
    print(f"\n[DIAG t={t}] hd_after={kernel.cfg.hd_after} hd_timeout={kernel.cfg.hd_timeout} "
          f"standoffs={kernel.standoffs} swaps={kernel.standoff_swaps}")
    if robots_only:
        _print_selected(kernel, snap, robots_only)
    _print_unfinished(kernel, snap)
    _print_pairs(kernel, snap)
    print("  --- 대치 이벤트 ---")
    _print_events(kernel.yield_events, n_events, "  총 ")


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
        _print_events(kernel.yield_events, n_events, "  대치 이벤트 총 ")
        return
    diag(kernel, t, n_events, robots_only)


if __name__ == "__main__":
    main(sys.argv[1:])
