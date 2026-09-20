# -*- coding: utf-8 -*-
"""도면에서 기하 특징을 잰다 — 이름이 아니라 격자에서 (S15P21A106-206).

## 왜 필요한가

θ 예측 모델의 입력은 `aisles` · `pitch` · `length` · `free` 인데, 앞의 셋을 지금은 합성 창고
**이름**(`r11p5l17`)에서 정규식으로 읽는다. 그건 생성 파라미터라 **공식 맵에도, 실제 고객
도면에도 없다.** 그래서 모델을 공식 맵에 못 태운다.

여기서는 **격자만 보고 잰다.** 맵 파일은 읽기만 하고 아무것도 바꾸지 않는다.

## 어떻게 재나 — 차단/개방 차이가 곧 랙 사이 통로다

    free(개방)  로봇이 갈 수 있는 칸 전부
    free(차단)  랙 사이 통로를 피커 전용으로 막은 뒤 남는 칸 (바깥 링)
    차이        = 랙 사이 통로 칸  <- 이게 우리가 세려는 것

그 차이 칸들을 4-이웃으로 묶으면 덩어리 하나가 통로 하나다.

    aisles   덩어리 수
    length   덩어리의 긴 쪽 길이 (중앙값)
    pitch    이웃한 통로 중심 사이 거리 (중앙값)

## 검증이 공짜다

합성 창고 110개는 **정답을 이름이 들고 있다**(`r11p5l17` = 통로 11 · 간격 5 · 길이 17).
추출기가 그 값을 되찾으면 맞는 것이다. `--check` 로 전수 대조한다.

## 한계

규칙적인 랙 배치를 전제한다. 랙 블록이 여럿이거나 통로 간격이 들쭉날쭉하면 `pitch` 가
단일 값으로 정의되지 않는다 — 그때는 중앙값이 대표값일 뿐이다. 실제 도면에서 이 가정이
깨지는지는 도면을 받아봐야 안다.
"""
import argparse
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FMS = os.path.abspath(os.path.join(HERE, ".."))
SIM = os.path.join(FMS, "sim_engine")
SYNTH = os.path.join(FMS, "map", "synth")
if SIM not in sys.path:
    sys.path.insert(0, SIM)


def _components(mask):
    """True 칸들을 4-이웃으로 묶는다. 반환: 덩어리별 (행들, 열들)."""
    H, W = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    out = []
    for r0 in range(H):
        for c0 in range(W):
            if not mask[r0, c0] or seen[r0, c0]:
                continue
            stack, cells = [(r0, c0)], []
            seen[r0, c0] = True
            while stack:
                r, c = stack.pop()
                cells.append((r, c))
                for y, x in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
                    if 0 <= y < H and 0 <= x < W and mask[y, x] and not seen[y, x]:
                        seen[y, x] = True
                        stack.append((y, x))
            out.append(cells)
    return out


def extract(map_dir=None, min_cells=4):
    """맵 폴더 → {aisles, pitch, length, free}. 못 재면 None.

    `map_dir=None` 이면 공식 맵(3_FMS/map)을 읽는다.
    """
    from map_loader import load_map
    try:
        free_open = load_map(map_dir, aisle_block=False)[0]
        free_blk = load_map(map_dir, aisle_block=True)[0]
    except Exception:
        return None

    aisle_mask = free_open & ~free_blk          # 차단하면 사라지는 칸 = 랙 사이 통로
    comps = [c for c in _components(aisle_mask) if len(c) >= min_cells]
    if not comps:
        return None

    lengths, centers, vertical = [], [], 0
    for cells in comps:
        rr = np.array([r for r, _ in cells])
        cc = np.array([c for _, c in cells])
        h, w = rr.max() - rr.min() + 1, cc.max() - cc.min() + 1
        if h >= w:                              # 세로 통로
            vertical += 1
            lengths.append(h)
            centers.append(float(cc.mean()))
        else:                                   # 가로 통로
            lengths.append(w)
            centers.append(float(rr.mean()))

    centers = np.sort(np.array(centers))
    gaps = np.diff(centers)
    gaps = gaps[gaps > 0.5]                     # 같은 통로가 쪼개져 잡힌 것 제외
    return {"aisles": float(len(comps)),
            "length": float(np.median(lengths)),
            "pitch": float(np.median(gaps)) if len(gaps) else float("nan"),
            "free": float(free_open.sum()),
            "free_blocked": float(free_blk.sum()),
            "vertical": vertical, "horizontal": len(comps) - vertical}


def main():
    p = argparse.ArgumentParser(description="도면에서 기하 특징 추출")
    p.add_argument("map_dir", nargs="?", default=None,
                   help="맵 폴더 (생략하면 공식 맵)")
    p.add_argument("--check", action="store_true",
                   help="합성 창고 전수 대조 — 이름의 정답과 맞는지")
    a = p.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if a.check:
        import re
        pat = re.compile(r"^r(\d+)p(\d+)l(\d+)$")
        names = sorted(n for n in os.listdir(SYNTH) if pat.match(n))
        print("합성 창고 %d개 대조 — 이름이 정답이다" % len(names))
        print("  %-12s%18s%18s%8s" % ("창고", "정답(통로/간격/길이)", "측정", "일치"))
        print("  " + "-" * 58)
        ok = {"aisles": 0, "pitch": 0, "length": 0}
        bad = []
        for n in names:
            m = pat.match(n)
            want = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
            got = extract(os.path.join(SYNTH, n))
            if got is None:
                bad.append((n, want, None))
                continue
            g = (int(got["aisles"]), round(got["pitch"]), round(got["length"]))
            for k, i in (("aisles", 0), ("pitch", 1), ("length", 2)):
                ok[k] += (g[i] == want[i])
            if g != want:
                bad.append((n, want, g))
            if len(bad) <= 6 and g != want:
                print("  %-12s%18s%18s%8s" % (n, "%d/%d/%d" % want, "%d/%d/%d" % g, "X"))
        print("\n  통로 수 %d/%d · 간격 %d/%d · 길이 %d/%d 일치"
              % (ok["aisles"], len(names), ok["pitch"], len(names),
                 ok["length"], len(names)))
        print("  어긋난 창고 %d개" % len(bad))
        return 0 if len(bad) == 0 else 1

    f = extract(a.map_dir)
    label = a.map_dir or "공식 맵 (3_FMS/map)"
    if f is None:
        print("%s — 특징을 못 쟀다" % label)
        return 1
    print("=== %s ===" % label)
    print("  통로 수      %d  (세로 %d · 가로 %d)"
          % (f["aisles"], f["vertical"], f["horizontal"]))
    print("  중심 간격    %.1f m" % f["pitch"])
    print("  통로 길이    %.1f m" % f["length"])
    print("  통행 칸      %d (개방) · %d (차단)" % (f["free"], f["free_blocked"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
