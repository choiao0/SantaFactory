# -*- coding: utf-8 -*-
"""정체가 **위상 잠금인가 단순 지연인가** 를 가른다 (S15P21A106-224).

판별 기준은 FMS 답신 14 §3 이 준 것이다:

    위상 잠금   두 로봇이 서로의 임시 예약에 번갈아 막혀
                **둘 다 non-busy 인 틱이 안 나온다** (FMS 시드 42 사례)
    단순 지연   한쪽은 계속 움직인다

그래서 정체 구간 동안 **로봇쌍의 `busy` 를 같이** 본다. `busy > 0` 은 다틱
동작(회전 5틱 · 전진 4틱)이 진행 중이라는 뜻이라, 둘 다 0 인 틱이 없다는 것은
**둘이 번갈아 돌고 있다**는 말이다.

쓰는 법
-------
    source paths.sh
    SEED=14 python tools/stall_kind.py

    SEED       볼 시드 (기본 14)
    STAG_MIN   정체로 볼 문턱 틱 (기본 100)
    RULE       앞 칸 규칙 (기본 4 — 주행과 같게 맞춘다)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.environ["W"], "path"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ★ 주행과 **같은 환경**을 스스로 맞춘다 (-224). 예전에는 독스트링이
#   `PIBT_FRONT_RULE=4` 를 앞에 붙이라고만 했다. 빠뜨리면 규칙 없이 계획이
#   서고, 그러면 **조용히 다른 계획**을 재게 된다 — `lag_budget` 이 실제로
#   그랬다 (태스크 완료가 주행 13 개인데 도구는 15 개였다). 위상 잠금을
#   가리는 도구가 다른 계획을 보고 있으면 결론이 통째로 무의미하다.
os.environ.setdefault("PIBT_FRONT_RULE", os.environ.get("RULE", "4"))

import pibt_scene                                            # noqa: E402

MAP = os.environ["MAP"]
N = int(os.environ.get("N", "12"))
PITCH = float(os.environ.get("PIBT_PITCH", "1.0"))
SEED = int(os.environ.get("SEED", "14"))
HORIZON = int(os.environ.get("HORIZON", "1260"))
GAP = int(os.environ.get("GAP", "60"))
STAG_MIN = int(os.environ.get("STAG_MIN", "100"))


def make_recorder(base):
    """틱마다 `busy` 와 `stag` 를 찍어 두는 커널."""

    class Recorder(base):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.trace = []          # [(busy dict, stag dict)]

        def step(self, *a, **kw):
            out = super().step(*a, **kw)
            self.trace.append((dict(self.busy),
                               {k: v for k, v in self.stag.stag.items()}))
            return out

    return Recorder


def main():
    from lifelong import Kernel, run_lifelong                # noqa: E402

    geom, free, starts, goals = pibt_scene.setup_lifelong(
        MAP, N, PITCH, SEED, "cross", verbose=False)
    zone = pibt_scene.charge_zone_cells(free, geom)

    holder = {}

    cls = make_recorder(Kernel)
    orig_init = cls.__init__

    def keep(self, *a, **kw):        # 만들어진 커널을 밖에서 잡는다
        orig_init(self, *a, **kw)
        holder["k"] = self
    cls.__init__ = keep

    history, _cells, li = run_lifelong(
        free, starts, goals, horizon=HORIZON, seed=SEED, order_gap=GAP,
        shifts=("in", "out", "out"), zone_cells=zone, order_end=None,
        kernel_cls=cls)

    K = holder["k"]
    trace = K.trace
    print(f"[stall_kind] 시드 {SEED} · {N}대 · {len(trace)}틱 기록")
    # ★ 어느 시스템을 잰 표인지 **표 자체로** 알 수 있어야 한다.
    print(f"             PIBT_FRONT_RULE={os.environ.get('PIBT_FRONT_RULE')} · "
          f"pitch {PITCH} · horizon {HORIZON} · order_gap {GAP}")
    print(f"             stag_max {li.get('stag_max')} · "
          f"100틱+ {li.get('stag_stuck')} · 태스크 {li.get('tasks_done')}")

    # --- 정체한 로봇과 그 구간 -------------------------------------------
    peak = {}                    # agent -> (최대 stag, 그 틱)
    for t, (_b, sg) in enumerate(trace):
        for a, v in sg.items():
            if v > peak.get(a, (0, 0))[0]:
                peak[a] = (v, t)
    bad = sorted(((v, t, a) for a, (v, t) in peak.items() if v >= STAG_MIN),
                 reverse=True)
    if not bad:
        print(f"\n  {STAG_MIN}틱 이상 정체한 로봇이 없다")
        return 0

    print(f"\n  {STAG_MIN}틱+ 정체 로봇 {len(bad)}대")
    for v, t, a in bad:
        print(f"    a{a:<3} 최대 {v:4d}틱  @t={t}  (구간 {t - v}~{t})")

    # --- ★ 판별 — 구간 동안 둘 다 non-busy 인 틱이 있나 ------------------
    print("\n  ═══ 판별 — FMS 답신 14 §3 기준 ═══")
    for v, t, a in bad[:3]:
        lo, hi = max(0, t - v), min(t, len(trace) - 1)
        print(f"\n  a{a} 구간 {lo}~{hi} ({hi - lo}틱)")
        # 그 구간에 같이 busy 였던 상대를 찾는다
        peers = {}
        for tt in range(lo, hi + 1):
            b = trace[tt][0]
            if b.get(a, 0) <= 0:
                continue
            for p, bv in b.items():
                if p != a and bv > 0:
                    peers[p] = peers.get(p, 0) + 1
        if not peers:
            print("    같이 busy 였던 상대가 없다 -> **단순 지연** "
                  "(혼자 못 가고 있다)")
            continue
        for p, n in sorted(peers.items(), key=lambda kv: -kv[1])[:3]:
            both_free = sum(
                1 for tt in range(lo, hi + 1)
                if trace[tt][0].get(a, 0) <= 0 and trace[tt][0].get(p, 0) <= 0)
            a_free = sum(1 for tt in range(lo, hi + 1)
                         if trace[tt][0].get(a, 0) <= 0)
            p_free = sum(1 for tt in range(lo, hi + 1)
                         if trace[tt][0].get(p, 0) <= 0)
            kind = ("★ 위상 잠금 의심" if both_free == 0
                    else "단순 지연 (둘 다 쉬는 틱이 있다)")
            print(f"    a{p:<3} 함께 busy {n:4d}틱 · "
                  f"a{a} 쉼 {a_free:4d} · a{p} 쉼 {p_free:4d} · "
                  f"**둘 다 쉼 {both_free:4d}**  -> {kind}")

    print("\n  읽는 법")
    print("   · **둘 다 쉼 0** 이면 서로의 임시 예약에 번갈아 막힌 것이다")
    print("     (FMS 시드 42 위상 잠금 사례와 같은 모양).")
    print("   · 한쪽이라도 계속 쉬고 있으면 그 로봇은 **안 막힌 것**이라")
    print("     원인이 다른 데 있다 — 목표 도달 불가나 배차 쪽을 본다.")
    print("   · `busy` 는 다틱 동작 진행 중이라는 뜻이지 **일을 한다**는")
    print("     뜻이 아니다. 제자리 회전을 반복해도 busy 다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
