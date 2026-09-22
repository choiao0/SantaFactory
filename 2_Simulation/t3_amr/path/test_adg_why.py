# -*- coding: utf-8 -*-
"""`[adg-why]` 의 ③ADG선행 이 **자기 / 남** 으로 갈리는가. Isaac 없이 돈다.

왜
--
2.77배(FMS 계획 600.0s -> 우리 실행 1661.7s)가 어디서 오는지를 가르려는데,
`_why` 가 ③ 을 한 칸으로만 세고 있었다. 그런데 그 한 칸에는 성격이 다른
둘이 섞여 있다:

    자기   같은 로봇의 **앞 액션**(type 1) 을 기다린다 — 순서 그 자체다
    남     **다른 로봇**의 액션을 기다린다            — 이건 경합이다

SADG(Switchable ADG)가 뒤집을 수 있는 것은 **남**뿐이다. 자기 사슬은
재배치 대상이 아니다. 둘을 합쳐 두면 「대기가 크다 -> SADG 가 답이다」로
잘못 읽힌다 — 이 파일은 그 오독을 막으려고 있다.

세우는 판
---------
    A0 --type1--> A1        agent 0 의 사슬
    B0 --type1--> B1        agent 1 의 사슬
    A0 --type2--> B1        남의 간선

    아무것도 done 이 아닌 상태에서
      A1 은 A0(자기) 만 기다린다          -> ③자기
      B1 은 B0(자기) + A0(남) 을 기다린다 -> ③남

  ★ `B1` 처럼 **남이 하나라도 끼면 남으로 센다.** SADG 후보인지를 보는
    것이므로, 자기 간선이 같이 있다고 후보에서 빼면 과소평가가 된다.

검사 넷
-------
    [1] 자기 / 남 분류
    [2] 남 간선이 끝나면 '자기' 로 내려가는가
    [3] **면제**(waive)된 남 간선을 남으로 세지 않는가
    [4] 네 칸 보고가 죽지 않는가 (분모 · SADG 한 줄 포함)

쓰는 법
-------
    python path/test_adg_why.py            # 종료 코드 0 = 전부 통과
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pibt_core_v2 as _pc                                  # noqa: E402,F401
import isaac_drive as D                                     # noqa: E402

VERBOSE = "-v" in sys.argv or "--verbose" in sys.argv


def mk(uid, agent, idx):
    """칸 하나짜리 MOVE. 이 검사는 기하를 안 보므로 최소로 만든다."""
    return D.Action(agent=agent, idx=idx, kind=D.MOVE, tick=idx,
                    frm=(0, uid, 0), to=(0, uid + 1, 0),
                    cells=frozenset({(0, uid)}), uid=uid)


def build():
    A0, A1 = mk(0, 0, 0), mk(1, 0, 1)
    B0, B1 = mk(2, 1, 0), mk(3, 1, 1)
    adg = D.ADG(chains=[[A0, A1], [B0, B1]], actions=[A0, A1, B0, B1],
                preds={0: set(), 1: {0}, 2: set(), 3: {2, 0}},
                succs={0: {1, 3}, 1: set(), 2: {3}, 3: set()},
                type1=2, type2=1)
    rt = D.AdgRuntime(adg, tick_s=1.0)
    rt._why_on = True
    rt.clock = 10.0
    return rt, A1, B1


def main():
    bad = []

    # [1] 분류 --------------------------------------------------------
    rt, A1, B1 = build()
    if rt.can_start(A1) or rt.can_start(B1):
        bad.append("[1] 둘 다 선행이 남아 있으므로 못 시작해야 한다")
    if VERBOSE:
        print("  _why =", dict(rt._why))
    if rt._why.get(0) != [0, 0, 1, 0]:
        bad.append("[1] agent0 은 ③자기 여야 한다: %s" % (rt._why.get(0),))
    if rt._why.get(1) != [0, 0, 0, 1]:
        bad.append("[1] agent1 은 ③남 이어야 한다: %s" % (rt._why.get(1),))

    # [2] 남이 끝나면 자기로 --------------------------------------------
    rt.done.add(0)                       # A0 완료
    rt._why.clear()
    rt.can_start(B1)
    if rt._why.get(1) != [0, 0, 1, 0]:
        bad.append("[2] 남이 풀린 뒤엔 ③자기 여야 한다: %s" % (rt._why.get(1),))

    # [3] 면제도 '해소' 다 ----------------------------------------------
    rt, _, B1 = build()
    rt.waive(0, 3)                       # 남 간선만 면제
    rt.can_start(B1)
    if rt._why.get(1) != [0, 0, 1, 0]:
        bad.append("[3] 면제된 남 간선을 남으로 세면 안 된다: %s"
                   % (rt._why.get(1),))

    # [4] 보고가 서는가 --------------------------------------------------
    rt, _, _ = build()
    rt._why_steps = 100
    rt._why = {0: [1, 2, 3, 4], 1: [0, 0, 5, 6]}
    try:
        rt.why_report()
    except Exception as e:                                   # noqa: BLE001
        bad.append("[4] why_report 가 죽는다: %r" % (e,))

    if bad:
        print()
        for b in bad:
            print("  ★", b)
        return 1
    print("  통과 — 분류 · 해소 · 면제 · 보고")
    return 0


if __name__ == "__main__":
    sys.exit(main())
