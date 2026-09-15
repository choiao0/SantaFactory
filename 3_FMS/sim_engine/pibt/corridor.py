# -*- coding: utf-8 -*-
"""폭 1 통로 모델 (S15P21A106-79 B4 §3.1) — 정면 대치 예방(구간 방향 잠금)의 자원 단위.

통로 칸 = 통행 가능 칸 중 진행 축에 수직인 두 이웃이 모두 막힌 칸(세로 통로: 좌우가 랙/벽, 가로 통로: 상하).
구간(segment) = 같은 축의 통로 칸이 이어진 묶음. 양 끝 바로 밖의 통행 칸이 입구(portal). 막힌 끝은 None(막다른 통로).
폭 2 이상은 통로가 아니다(옆이 비어 있어 비켜 줄 수 있다). 맵이 바뀌지 않으므로 시작 시 1회 계산(마스크처럼).
"""
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Segment:
    sid: int
    axis: int              # 0 = 세로(행 방향으로 이어짐, 로봇은 N/S 로 지남), 1 = 가로(열 방향, E/W)
    cells: tuple           # 축 순서(행 또는 열 오름차순)
    portal_a: tuple        # cells[0] 바깥 통행 칸 (없으면 None)
    portal_b: tuple        # cells[-1] 바깥 통행 칸 (없으면 None)

    def __len__(self):
        return len(self.cells)


def _blocked(free, r, c):
    return not (0 <= r < free.shape[0] and 0 <= c < free.shape[1] and free[r, c])


def corridor_cells(free):
    """(vertical bool[H,W], horizontal bool[H,W]). 세로 통로 칸 = 좌우 막힘, 가로 통로 칸 = 상하 막힘."""
    f = np.asarray(free, dtype=bool)
    pad = np.pad(f, 1, constant_values=False)
    left, right = pad[1:-1, :-2], pad[1:-1, 2:]
    up, down = pad[:-2, 1:-1], pad[2:, 1:-1]
    vert = f & ~left & ~right
    horiz = f & ~up & ~down
    return vert, horiz


def find_segments(free):
    """(seg_id int16[H,W] (−1 = 통로 아님), [Segment]). 같은 칸이 세로·가로 둘 다면(고립 칸) 세로로 둔다."""
    f = np.asarray(free, dtype=bool)
    vert, horiz = corridor_cells(f)
    seg_id = np.full(f.shape, -1, dtype=np.int16)
    segments = []
    H, W = f.shape
    for axis, mask, (dr, dc) in ((0, vert, (1, 0)), (1, horiz, (0, 1))):
        for r in range(H):
            for c in range(W):
                if not mask[r, c] or seg_id[r, c] >= 0:
                    continue
                if 0 <= r - dr < H and 0 <= c - dc < W and mask[r - dr, c - dc] and seg_id[r - dr, c - dc] >= 0:
                    continue                                  # 이미 앞 칸에서 시작한 구간에 포함됨
                cells = []
                rr, cc = r, c
                while 0 <= rr < H and 0 <= cc < W and mask[rr, cc] and seg_id[rr, cc] < 0:
                    cells.append((rr, cc))
                    seg_id[rr, cc] = len(segments)
                    rr, cc = rr + dr, cc + dc
                a = (cells[0][0] - dr, cells[0][1] - dc)
                b = (cells[-1][0] + dr, cells[-1][1] + dc)
                segments.append(Segment(len(segments), axis, tuple(cells),
                                        None if _blocked(f, *a) else a,
                                        None if _blocked(f, *b) else b))
    return seg_id, segments


def summarize(segments):
    """(구간 수, 길이 히스토그램 dict, 막다른 구간 수) — 실제 맵 확인용."""
    hist = {}
    dead = 0
    for s in segments:
        hist[len(s)] = hist.get(len(s), 0) + 1
        dead += (s.portal_a is None) + (s.portal_b is None)
    return len(segments), dict(sorted(hist.items())), dead


if __name__ == "__main__":                                   # 실제 맵: python -m pibt.corridor
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from map_loader import load_map
    free = load_map()[0]
    _, segs = find_segments(free)
    n, hist, dead = summarize(segs)
    print(f"segments={n} length_hist={hist} dead_ends={dead}")
    for s in segs:
        if len(s) >= 5:
            print(f"  #{s.sid} axis={s.axis} len={len(s)} {s.cells[0]}..{s.cells[-1]} portals={s.portal_a},{s.portal_b}")
