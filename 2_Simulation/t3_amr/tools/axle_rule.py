# -*- coding: utf-8 -*-
"""FMS 「앞 칸 축 규칙」 검증 (2026-09-14 답신 §3 확인 2건).

FMS 제안: 앞 2칸을 **hard(몸 금지)** 가 아니라 **soft(축 금지)** 로 둔다.
닿는 경우는 "앞 칸에 상대의 **축**이 있을 때" 뿐이라는 주장이다.

    hard(A) = 축 + rear(h) + swing_cells 3칸      상대 **몸**이 못 들어옴
    soft(A) = front(h), front(h2)                 상대 **축**만 못 들어옴

이 도구가 답하는 것

    확인 1   현행 규칙에서 닿은 8쌍이 전부 "B 의 축 ∈ soft(A)" 또는 그 역인가
             하나라도 아니면 규칙이 불완전하다
    확인 2   축 규칙으로 거른 뒤 동시회전 합법쌍 수와 접촉 수
             FMS 예상: 접촉 0, 합법쌍 258(5칸 hard)보다 많음

세 규칙을 같은 기준으로 비교한다.

    현행       hard 4칸만                    -> 1.0 에서 접촉 8쌍
    5칸 hard   앞 2칸도 몸 금지 (우리 제안)   -> 접촉 0, 합법쌍 258
    축 규칙    앞 2칸은 축만 금지 (FMS 제안)  -> ?

    source paths.sh
    python tools/axle_rule.py
    PITCHES=1.0,1.1,1.2 SAMPLES=48 python tools/axle_rule.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.environ["W"], "path"))
import pibt_core_v2                      # noqa: F401
from pibt_core import DIRS, occupied, swing_cells   # noqa: E402
from isaac_drive import YAW, wrap        # noqa: E402
from pibt_scene import make_geom         # noqa: E402

PITCHES = [float(x) for x in os.environ.get("PITCHES", "1.0,1.1,1.2").split(",")]
S = int(os.environ.get("SAMPLES", "32"))
R0 = C0 = 5


def front(r, c, h):
    d = DIRS[h]
    return (r + d[0], c + d[1])


def hard(r, c, h0, h1):
    """몸이 못 들어오는 칸 — 지금과 같다."""
    return {(r, c)} | set(swing_cells(r, c, h0, h1)) | set(occupied((r, c, h0)))


def soft(r, c, h0, h1):
    """축만 못 들어오는 칸 — FMS 제안 (앞 2칸)."""
    return {front(r, c, h0), front(r, c, h1)}


def soft3(r, c, h0, h1):
    """앞 2칸 + 그 사이 대각 — FMS 답신3 §2 대안.

    코는 옛 헤딩 앞에서 새 헤딩 앞으로 **사분면을 가로질러** 지나간다.
    그 사분면 쪽 대각 칸이 실제로 코가 스치는 자리다.
    """
    d1, d2 = DIRS[h0], DIRS[h1]
    return soft(r, c, h0, h1) | {(r + d1[0] + d2[0], c + d1[1] + d2[1])}


def body(r, c, h0, h1):
    """제자리 회전하는 로봇이 양 끝 자세에서 차지하는 칸(축+뒤)."""
    return set(occupied((r, c, h0))) | set(occupied((r, c, h1)))


def poses(g, r, c, h0, h1):
    x, y = g.cell_center((r, c))
    a0 = YAW[g.phys_heading(h0)]
    a1 = a0 + wrap(YAW[g.phys_heading(h1)] - a0)
    return [(x, y, a0 + (a1 - a0) * i / S) for i in range(S + 1)]


def legal(kind, A, B):
    """A·B 가 동시에 돌아도 되는가. A, B = (r, c, h0, h1)."""
    ha, hb = hard(*A), hard(*B)
    if body(*B) & ha or body(*A) & hb:
        return False                                  # 몸끼리 — 어느 규칙이든 금지
    if kind == "현행":
        return True
    if kind == "5칸 hard":
        return not ((body(*B) | {(B[0], B[1])}) & soft(*A)
                    or (body(*A) | {(A[0], A[1])}) & soft(*B))
    sf = soft3 if kind == "축+대각" else soft
    # 축 규칙 — 상대의 **축**만 본다
    return not ((B[0], B[1]) in sf(*A) or (A[0], A[1]) in sf(*B))


def candidates():
    """B 후보 — A 둘레 7x7 칸 × 8가지 90° 회전."""
    return [(R0 + dr, C0 + dc, h0, h1)
            for dr in range(-3, 4) for dc in range(-3, 4)
            for h0 in range(4) for h1 in ((h0 + 1) % 4, (h0 - 1) % 4)]


def min_gaps(g, pa, cand):
    """B 마다 A 와의 **최소 차체거리** — 두 회전을 훑어 가장 가까운 순간."""
    return {B: min(g.body_gap(u, v) for u in pa for v in poses(g, *B))
            for B in cand}


def report_rule(kind, A, cand, gaps):
    """규칙 하나 — 합법쌍·접촉·최악 쌍을 찍고 **접촉한 쌍**을 돌려준다."""
    ok = [B for B in cand if legal(kind, A, B)]
    hit = [B for B in ok if gaps[B] <= 0.0]
    worst = min(ok, key=lambda B: gaps[B]) if ok else None
    best = gaps[worst] if worst else float("nan")
    at = (f"  최악 B=축({worst[0]},{worst[1]}) h {worst[2]}->{worst[3]}"
          if worst else "")
    print(f"   {kind:<10} 합법쌍 {len(ok):4d}   접촉 {len(hit):3d}   "
          f"최소 차체거리 {best*1000:+8.1f} mm{at}")
    return hit


def check1(A, hit):
    """확인 1 — 닿은 쌍이 전부 "상대 축 ∈ soft" 로 설명되는가.

    하나라도 설명이 안 되면 축 규칙은 불완전하다 — 규칙 밖에서 닿는다.
    """
    print(f"      ↓ 확인 1 — 닿은 {len(hit)}쌍의 축이 soft(A) 안에 있나")
    inside = 0
    for B in hit:
        ax = (B[0], B[1])
        a_in_b = (R0, C0) in soft(*B)
        b_in_a = ax in soft(*A)
        inside += bool(a_in_b or b_in_a)
        print(f"        B=축{ax} h {B[2]}->{B[3]}   "
              f"B축∈soft(A) {str(b_in_a):<5}  A축∈soft(B) {str(a_in_b):<5}"
              f"   {'OK' if (a_in_b or b_in_a) else '★규칙 밖'}")
    print(f"        -> {inside}/{len(hit)} 쌍이 축 규칙으로 설명된다")


def one_pitch(p):
    """pitch 하나에서 네 규칙을 같은 후보·같은 거리표로 비교한다."""
    g = make_geom(p)
    A = (R0, C0, 1, 0)
    cand = candidates()
    gaps = min_gaps(g, poses(g, *A), cand)

    print(f"── pitch {p:.2f} " + "─" * 54)
    print(f"   A = 축({R0},{C0})  h 1->0   "
          f"soft {sorted(soft(*A))}   soft3 {sorted(soft3(*A))}")
    for kind in ("현행", "5칸 hard", "축 규칙", "축+대각"):
        hit = report_rule(kind, A, cand, gaps)
        # 확인 1 은 **현행에서 실제로 닿은 쌍**에만 묻는다. 그게 규칙이
        # 설명해야 할 대상이기 때문이다.
        if kind == "현행" and hit:
            check1(A, hit)
    print()


def main():
    print("FMS 「앞 칸 축 규칙」 검증 —  hard=몸 금지 · soft=축 금지\n")
    for p in PITCHES:
        one_pitch(p)
    print("확인 1 이 전부 OK 이고 확인 2 에서 축 규칙의 접촉이 0 이면 FMS 제안이 맞다.")
    print("합법쌍이 5칸 hard 보다 많으면 그만큼 동시성을 덜 잃는다.")


if __name__ == "__main__":
    main()
