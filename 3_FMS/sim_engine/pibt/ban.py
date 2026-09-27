# -*- coding: utf-8 -*-
# ============================================================
# 금지 조합표 — 회전 중 두 차체가 겹치는 (상대 위치, 상대 헤딩) 조합 (S15P21A106-251, 커널 편입 -277)
#
# 물리 팀 t3-33 §1 의 생성기를 그대로 옮긴 것. 맵을 안 보고 **기종 치수 · pitch · 여유**만 받는다.
# 우리가 독립으로 돌려 그쪽 20개와 한 항목도 안 다른 것을 확인했다(tests/test_ban_table.py).
# -277 에서 checks/ban_table.py 에서 여기로 옮겼다 — 커널(geometry.configure(ban=True))이 쓴다.
#
# 규약
#   A      회전하는 로봇. A 의 헤딩을 0(+r) 으로 놓은 상대 좌표계
#   셀     (dr, dc) = B 의 축 칸 − A 의 축 칸 을 A 의 헤딩만큼 되돌린 것
#   헤딩   h = (B 의 헤딩 − A 의 헤딩) mod 4
#   방향   +1 = 회전 좌(h -> h+1) · −1 = 회전 우(h -> h−1)
#   읽기   B 가 그 자리에 있으면 A 는 그 방향으로 회전하면 안 된다
#
# ☹ 이 표는 「기하적으로 불가능한 배치」가 아니라 **「제어 오차(tol.pos 50 mm × 2)를 감당 못 하는 배치」**다.
#   여유 0 이면 0개(합법 배치의 최소 틈 41.3 mm > 0), 여유 0.05 면 20개. tol.pos 가 바뀌면 표도 바뀐다.
#   pitch 1.2 면 0개(코가 자기 칸에 머문다: 0.5587 < 0.60).
# ============================================================
import math

FRONT, REAR, HALF_W = 0.39, 1.11, 0.40      # 기종 카드 (앞, 뒤, 폭/2) — map_loader.ROBOT_DIMS 와 같다
DIRS = [(1, 0), (0, 1), (-1, 0), (0, -1)]


def corners(cx, cy, th, m, front=FRONT, rear=REAR, hw=HALF_W):
    """여유 m 만큼 부풀린 차체 사각형의 네 모서리."""
    c, s = math.cos(th), math.sin(th)
    return [(cx + ax * c - ay * s, cy + ax * s + ay * c)
            for ax, ay in ((front + m, hw + m), (front + m, -hw - m),
                           (-rear - m, -hw - m), (-rear - m, hw + m))]


def overlap(A, B):
    """볼록 사각형 둘의 겹침 — 분리축 정리(SAT). 점 표본으로 재면 얇은 겹침을 최대 50 mm 덜 센다."""
    for poly in (A, B):
        for i in range(4):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % 4]
            ax, ay = -(y2 - y1), (x2 - x1)
            pa = [ax * x + ay * y for x, y in A]
            pb = [ax * x + ay * y for x, y in B]
            if max(pa) < min(pb) or max(pb) < min(pa):
                return False
    return True


def rear_cell(p, h):
    return (p[0] - DIRS[h][0], p[1] - DIRS[h][1])


def build_table(pitch=1.0, margin=0.05, dims=(FRONT, REAR, HALF_W), steps=91, span=3):
    """{+1: {((dr, dc), hb), ...}, -1: {...}} — 좌·우 회전별 금지 조합.
    계획기가 **이미 예약하는 칸**(A 의 축·뒤·스윙 3칸)에 걸리는 배치는 뺀다 — 새 규칙이 아니므로."""
    front, rear, hw = dims
    out, h0 = {}, 0
    for sgn in (+1, -1):
        h1 = (h0 + sgn) % 4
        a, b = rear_cell((0, 0), h0), rear_cell((0, 0), h1)
        reserved = {(0, 0), a, b, (a[0] + b[0], a[1] + b[1])}
        hit = set()
        for dr in range(-span, span + 1):
            for dc in range(-span, span + 1):
                for hb in range(4):
                    if {(dr, dc), rear_cell((dr, dc), hb)} & reserved:
                        continue
                    B = corners(dr * pitch, dc * pitch, hb * math.pi / 2, margin, front, rear, hw)
                    if any(overlap(corners(0, 0, sgn * k * (math.pi / 2) / (steps - 1), margin, front, rear, hw), B)
                           for k in range(steps)):
                        hit.add(((dr, dc), hb))
        out[sgn] = hit
    return out


def banned(tab, s0, s1, others):
    """s0 -> s1 회전이 표에 걸리나. s = (r, c, h). others = 다른 로봇들의 (r, c, h). 회전이 아니면 False."""
    if s1[:2] != s0[:2] or s1[2] == s0[2]:
        return False
    sgn = 1 if (s1[2] - s0[2]) % 4 == 1 else -1
    c, s = DIRS[s0[2]]
    for q in others:
        dr, dc = q[0] - s0[0], q[1] - s0[1]
        if ((dr * c + dc * s, -dr * s + dc * c), (q[2] - s0[2]) % 4) in tab[sgn]:
            return True
    return False


def absolute_states(tab, r, c, h, h2):
    """(r, c) 에서 h -> h2 회전에 대해 **남이 있으면 안 되는** 절대 상태 (r', c', h') 집합.
    banned() 의 역변환 — 상대 칸 (x, y) 를 A 의 헤딩 (cos, sin) = DIRS[h] 만큼 돌려 되돌린다."""
    if h2 == h:
        return frozenset()
    sgn = 1 if (h2 - h) % 4 == 1 else -1
    co, si = DIRS[h]
    return frozenset((r + x * co - y * si, c + x * si + y * co, (hb + h) % 4)
                     for (x, y), hb in tab[sgn])
