# -*- coding: utf-8 -*-
"""A 가 쓰려는 칸을 **그 시점 누가 잡고 있었나** (S15P21A106-240).

`recover_design.py` 가 「A 는 예약을 벗어나지 않고는 못 한다 — 기하가 그렇다」로
끝났다. 그래서 물음이 바뀌었다:

    전   A 가 칸을 벗어나나          -> 예, 반드시
    후   **벗어나는 그 칸이 비어 있나**

이 도구는 그중 **① 그 시점 실측**만 답한다. 시드 7 · A6#86 교착 순간에
워치독이 찍은 12대 액션을 그대로 넣고, 각자의 `swept_cells` 를 A 가 쓸 칸과
맞댄다.

☹ **이 한 판으로는 답이 안 난다.** 여기서 비어 있어도 다른 배치에서는 남의
  예약일 수 있고, A 는 1/939 짜리 사고 대책이라 언제 어디서 발동할지 모른다.
  그래서 ② 구조적 보장(누가 그 칸을 예약할 수 있나)이 따로 필요하다.
  이 도구는 ①만 하고, ②는 안 한다.

    python tools/recover_occupancy.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.environ["W"], "path"))
import pibt_core_v2                                    # noqa: F401,E402
import isaac_drive as D                                # noqa: E402

GEOM = D.RobotGeom(pitch=1.0, rear_len=1.11, front_len=0.39, width=0.80,
                   heading_offset=0)

# 시드 7 · A6#86 교착 순간의 워치독 덤프 (logs/hist_s7.log)
#   (에이전트, 상태, 액션, frm, to, 막는 선행)
DUMP = [
    (0,  "대기",  "A0#75  move",    (41, 44, 0), (42, 44, 0), "[11]"),
    (1,  "실행중", "A1#102 move",    (69, 96, 1), (69, 97, 1), ""),
    (2,  "실행중", "A2#80  move",    (64, 100, 2), (63, 100, 2), ""),
    (3,  "대기",  "A3#99  reverse", (46, 48, 3), (46, 49, 3), "[6]"),
    (4,  "실행중", "A4#108 move",    (68, 45, 3), (68, 44, 3), ""),
    (5,  "대기",  "A5#158 turn",    (46, 24, 2), (46, 24, 1), "[3]"),
    (6,  "실행중", "A6#86  reverse", (46, 50, 0), (45, 50, 0), "★ 교착 당사자"),
    (7,  "실행중", "A7#112 move",    (44, 69, 3), (44, 68, 3), ""),
    (8,  "실행중", "A8#166 reverse", (45, 46, 1), (45, 45, 1), ""),
    (9,  "실행중", "A9#170 move",    (68, 37, 3), (68, 36, 3), ""),
    (10, "대기",  "A10#149 move",   (53, 28, 2), (52, 28, 2), "[6]"),
    (11, "대기",  "A11#152 turn",   (43, 45, 2), (43, 45, 1), "[6]"),
]

# A 가 쓰려는 칸 (recover_design.py 실측)
WANT = {
    (46, 49): "물러날 때 — 이미 넘친 49 열의 연장",
    (44, 51): "기동 중 — **반대편**. 없던 자리다",
}
ALREADY = {(44, 49), (45, 49)}     # 멈춘 자세가 이미 쓰고 있다 (A 와 무관)


def main():
    a6 = next(r for r in DUMP if r[0] == 6)
    mine = GEOM.swept_cells(a6[3], a6[4])
    print(f"  A6#86  {a6[3]} -> {a6[4]}   swept {sorted(mine)}")
    print(f"  멈춘 자세가 이미 쓰는 칸 {sorted(ALREADY)}  (A 와 무관)")
    print(f"  A 가 **더** 쓰려는 칸 {sorted(WANT)}\n")

    print("  {:>3} {:>5} {:<16} {:<34} {}".format(
        "id", "상태", "액션", "swept", "A 가 쓸 칸과 겹침"))
    hits = {c: [] for c in WANT}
    for rid, st, lab, frm, to, blk in DUMP:
        if rid == 6:
            sw = mine
        elif frm[:2] == to[:2]:                     # 제자리 회전
            sw = frozenset(D.occupied(frm)) | frozenset(D.occupied(to))
        else:
            sw = GEOM.swept_cells(frm, to)
        ov = sorted(set(sw) & set(WANT))
        for c in ov:
            hits[c].append((rid, st, lab, blk))
        mark = f"★ {ov}" if ov else "-"
        print(f"  {rid:>3} {st:>5} {lab:<16} {str(sorted(sw)):<34} {mark}"
              + (f"   선행 {blk}" if blk and rid != 6 else ""))

    print()
    print("  ── ① 그 시점 실측 ──")
    for c, why in WANT.items():
        who = hits[c]
        if not who:
            print(f"  {c}  **비어 있다**   ({why})")
        else:
            for rid, st, lab, blk in who:
                gate = ("**A6#86 을 기다린다** — 교착이면 정의상 대기 중"
                        if "[6]" in blk else
                        "☹ **무관한 제3자**" if st == "실행중" else
                        f"다른 선행 {blk} 을 기다린다")
                print(f"  {c}  ☹ agent{rid} ({st}) {lab} 이 쓴다   ({why})")
                print(f"           -> {gate}")
    print()
    print("  ── 한계 ──")
    print("  이건 **한 판의 한 시점**이다. 비어 있어도 다른 배치에서는 남의")
    print("  예약일 수 있고, A 는 1/939 짜리 사고 대책이라 어디서 터질지 모른다.")
    print("  ② 「누가 그 칸을 예약할 수 있나」는 이 도구가 답하지 않는다.")


if __name__ == "__main__":
    main()
