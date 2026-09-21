# -*- coding: utf-8 -*-
"""금지 조합표 (S15P21A106-251): 물리 팀 t3-33 §1 의 20개를 생성기로 재현한다.
기종 치수·pitch·여유 중 하나라도 바뀌면 여기서 걸린다 — 표가 그 셋의 함수라서."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "checks"))

from ban_table import banned, build_table  # noqa: E402

# t3-33 §1 그대로 — 우리가 독립 유도해 한 항목도 안 달랐다 (FMS-36 §1)
THEIRS = {
    +1: {((-1, 1), 2), ((0, 1), 0), ((0, 1), 2), ((0, 1), 3), ((1, -1), 3),
         ((1, 0), 1), ((1, 0), 2), ((1, 0), 3), ((1, 1), 0), ((1, 1), 1)},
    -1: {((-1, -1), 2), ((0, -1), 0), ((0, -1), 1), ((0, -1), 2), ((1, -1), 0),
         ((1, -1), 3), ((1, 0), 1), ((1, 0), 2), ((1, 0), 3), ((1, 1), 1)},
}


def test_matches_physics_team_table():
    t = build_table(1.0, 0.05)
    assert t[+1] == THEIRS[+1]
    assert t[-1] == THEIRS[-1]


def test_mirror_symmetry():
    """좌·우는 거울상 — (dr, dc, h) -> (dr, -dc, -h mod 4)."""
    t = build_table(1.0, 0.05)
    mirrored = {((dr, -dc), (-h) % 4) for (dr, dc), h in t[+1]}
    assert mirrored == t[-1]


def test_pitch_1_2_is_empty():
    """코 반경 0.5587 < 반칸 0.60 — 코가 자기 칸에 머무니 조합이 없다."""
    assert sum(len(v) for v in build_table(1.2, 0.05).values()) == 0


def test_zero_margin_is_empty():
    """여유 0 이면 합법 배치는 기하적으로 안 겹친다(최소 틈 41.3 mm). 표는 제어 오차의 함수다."""
    assert sum(len(v) for v in build_table(1.0, 0.0).values()) == 0


def test_sampling_is_not_the_issue():
    """t3-33 은 「표본이 성기면 놓친다」고 경고했지만 이 표는 13등분으로도 같다 (FMS-36 §1)."""
    assert build_table(1.0, 0.05, steps=13) == build_table(1.0, 0.05, steps=91)


def test_banned_judgement():
    """A 가 (5,5) h0 에서 좌회전하는데 B 가 바로 앞 (6,5) h1 에 있으면 금지 — 표의 (1,0)h1."""
    t = build_table()
    assert banned(t, (5, 5, 0), (5, 5, 1), [(6, 5, 1)])
    assert not banned(t, (5, 5, 0), (5, 5, 1), [(9, 9, 1)])     # 멀면 무관
    assert not banned(t, (5, 5, 0), (6, 5, 0), [(6, 5, 1)])     # 회전이 아니면 판정 안 함
