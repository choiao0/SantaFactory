# -*- coding: utf-8 -*-
"""기록(npz)에서 **멈춤의 정체**를 프레임 단위로 가른다.

"이어달리기를 넣었는데 영상에서는 여전히 서다 가다 한다" 를 판별하기 위한
도구다. 멈춤에는 종류가 있고, 이어달리기가 없앨 수 있는 것은 하나뿐이다.

    회전       제자리 선회. v=0 이지만 yaw 가 돈다. **이어달리기와 무관** —
               회전 앞에서는 반드시 선다 (선속도를 들고 돌면 칸을 벗어난다)
    대기       v=0 이고 yaw 도 안 돈다. ADG 선행 대기. **이어달리기와 무관**
    감속       0 < v < 0.5. 칸 경계를 지나는 중이거나 출발/도착
    순항       v >= 0.5

이어달리기가 지우는 것은 **"칸마다 v=0 으로 떨어지는 것"** 뿐이다. 회전과
대기가 대부분이면 영상은 여전히 서다 가다 한다 — 그게 정상이다.

    source paths.sh
    python tools/motion_profile.py $OUT/rec_full.npz $OUT/rec_carry.npz
    AMR=6 python tools/motion_profile.py $OUT/rec_carry.npz
"""
import os
import sys

import numpy as np

V_STOP = 0.05        # m/s 이하면 정지로 본다
W_TURN = 0.10        # rad/s 이상이면 회전 중
V_CRUISE = 0.50      # m/s 이상이면 순항


def wrap(a):
    return (a + np.pi) % (2.0 * np.pi) - np.pi


def profile(path, amr=None):
    z = np.load(path, allow_pickle=True)
    t = z["t"].astype(np.float64)
    p = z["pose"].astype(np.float64)              # (T, N, 3)
    dt = np.diff(t)
    dt[dt <= 0] = np.nan
    dx = np.diff(p[:, :, 0], axis=0)
    dy = np.diff(p[:, :, 1], axis=0)
    dyaw = wrap(np.diff(p[:, :, 2], axis=0))
    v = np.hypot(dx, dy) / dt[:, None]
    w = np.abs(dyaw) / dt[:, None]

    sel = slice(None) if amr is None else slice(amr, amr + 1)
    v, w, = v[:, sel], w[:, sel]
    n = v.size
    stop = v < V_STOP
    turn = stop & (w >= W_TURN)
    wait = stop & (w < W_TURN)
    slow = (~stop) & (v < V_CRUISE)
    cru = v >= V_CRUISE

    # 멈춤 '사건' 수 — 연속된 정지 구간의 개수
    def events(mask):
        m = mask.astype(np.int8)
        return int(np.sum((m[1:] == 1) & (m[:-1] == 0)) + m[0].sum())

    return dict(
        name=os.path.basename(path), dur=float(t[-1]), frames=len(t),
        turn=turn.sum() / n, wait=wait.sum() / n,
        slow=slow.sum() / n, cru=cru.sum() / n,
        v_mean=float(np.nanmean(v)), v_p95=float(np.nanpercentile(v, 95)),
        n_turn=events(turn), n_wait=events(wait),
        dist=float(np.nansum(np.hypot(dx, dy)[:, sel])))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args:
        raise SystemExit(__doc__)
    amr = os.environ.get("AMR")
    amr = int(amr) if amr else None
    tag = f"amr_{amr}" if amr is not None else "전체"
    print(f"대상 {tag}   정지 {V_STOP} m/s · 회전 {W_TURN} rad/s · 순항 {V_CRUISE} m/s\n")
    print(f"{'기록':<16}{'길이':>8}{'거리':>9}{'회전':>8}{'대기':>8}"
          f"{'감속':>8}{'순항':>8}{'평균v':>8}{'p95 v':>8}{'회전수':>7}{'대기수':>7}")
    for f in args:
        r = profile(f, amr)
        print(f"{r['name']:<16}{r['dur']:7.1f}s{r['dist']:8.1f}m"
              f"{r['turn']*100:7.1f}%{r['wait']*100:7.1f}%"
              f"{r['slow']*100:7.1f}%{r['cru']*100:7.1f}%"
              f"{r['v_mean']:8.3f}{r['v_p95']:8.3f}"
              f"{r['n_turn']:7d}{r['n_wait']:7d}")
    print("\n이어달리기가 줄이는 것은 **감속** 구간이 v=0 으로 떨어지는 일이다.")
    print("회전·대기는 못 줄인다 — 회전 앞에서는 반드시 서야 하고, 대기는 ADG 다.")


if __name__ == "__main__":
    main()
