# -*- coding: utf-8 -*-
"""**접촉이 난 프레임의 격자 상태를 뽑는다** — 단위 테스트 초기 배치용.

왜
--
2026-09-15 다중 시드 주행에서 5판 중 2판이 차체 접촉으로 중단됐다
(s2 t=279.4 쌍 0-5 · s5 t=401.9 쌍 1-7, 둘 다 간격 0.000 m). 두 건 다
**한 대가 회전 중이고 상대는 축 0.4 mm 로 서 있었다** — 제어 오차가 아니라
회전 중 예약이 비어 있었다는 뜻이다 (`soft_hold` 미전달).

`test_soft_hold.py` 의 `[C]` 는 원래 「뚫려 있나」를 증명하는 시험이었는데,
실주행에서 이미 뚫린 것을 봤으므로 **그 배치를 재현하는** 시험이 된다.
그러려면 접촉 프레임의 `(r, c, h)` 가 필요하다. 이 도구가 그걸 낸다.

무엇을 내나
-----------
    · 간격이 가장 작았던 프레임과 그 앞 몇 틱
    · 프레임마다 **모든** 로봇의 (r, c, h) — 붙여 넣으면 바로 초기 배치다
    · 회전 중인 로봇의 실제 요잉과, 그 회전이 어느 헤딩에서 어느 헤딩으로
      가는 중인지 (h0 -> h1) 추정

★ 헤딩은 **연속 yaw 를 4방향으로 반올림**한 값이다. 회전 중이면 중간 각도라
  반올림이 어느 쪽으로든 갈 수 있다. 그래서 회전 중 로봇은 `h` 하나가 아니라
  `h0 -> h1` 을 같이 낸다 — 테스트에 쓸 것은 **회전 시작 헤딩 h0** 이다.

쓰는 법
-------
    source paths.sh
    PITCH=1.0 python tools/contact_frame.py $OUT/rec_s2.npz
    PITCH=1.0 python tools/contact_frame.py $OUT/rec_s5.npz --back 40

    --pair 0-5   그 쌍만 본다 (기본: 간격 최소인 쌍)
    --back N     최소 프레임에서 N 프레임 앞까지 거슬러 찍는다 (기본 20)
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tail_yaw import (FRONT, PITCH, REAR, WIDTH, W_TURN,   # noqa: E402
                      closest_frames, corners, sat_gap)

DIRS = ((-1, 0), (0, 1), (1, 0), (0, -1))    # pibt.geometry 와 같은 순서
# isaac_drive.RobotGeom.heading_offset. 0 또는 2 만 유효하고 현행은 2 다.
HEADING_OFFSET = int(os.environ.get("HEADING_OFFSET", "2"))


def load_npz(path):
    """`np.load` + **`$OUT` 이 비어서 `/` 로 간 경우**를 이름 붙여 잡는다.

    `PITCH=1.0 python tools/x.py $OUT/rec_s2.npz` 를 `source paths.sh` 안 한
    셸에서 돌리면 `$OUT` 이 빈 문자열이라 경로가 `/rec_s2.npz` 가 된다.
    2026-09-15 하루에 세 번 걸렸다 (기록 때 한 번은 20분짜리 주행을 기록
    없이 돌렸다). `FileNotFoundError: '/rec_s2.npz'` 만 봐서는 원인이 안
    보이므로 여기서 이름을 붙인다. `live_pibt._rec_setup` 도 같은 안내를 한다.
    """
    if not os.path.exists(path):
        hint = ""
        if os.path.dirname(path) == os.sep:
            hint = ("\n  ★ 경로가 '/' 에서 시작합니다 — `$OUT` 이 비어서 그리 간"
                    " 것이 흔합니다.\n"
                    "     `source paths.sh` 를 **이 셸에서** 먼저 하거나"
                    " 절대경로를 주세요.\n"
                    "     (`run_record.sh` 는 자식 셸에서 source 하므로 부모"
                    " 셸의 $OUT 은 안 채워집니다)")
        raise SystemExit(f"[contact_frame] 없는 파일: {path!r}{hint}")
    return np.load(path, allow_pickle=True)


def cell_of(x, y, pitch):
    """world (x, y) -> 격자 (r, c). origin = pitch/2 규약 (칸 **중심**)."""
    return int(round(y / pitch - 0.5)), int(round(x / pitch - 0.5))


def heading_of(yaw):
    """연속 yaw -> **물리** 헤딩 0..3 (`DIRS` 색인).

    `DIRS = ((-1,0), (0,1), (1,0), (0,-1))` 이므로 0=북 · 1=동 · 2=남 · 3=서.
    world 에서 x 가 열, y 가 행이라 **yaw 0 = +x = 동 = h1** 이다.
    그래서 `round(yaw / (pi/2))` 에 **+1** 을 해야 맞는다 — 안 하면 전부
    한 칸씩 돌아간 헤딩이 나온다 (합성 검증에서 걸렀다).
    """
    return (int(round(yaw / (np.pi / 2.0))) + 1) % 4


def to_plan(h_phys):
    """물리 헤딩 -> **계획기** 헤딩.

    `isaac_drive.RobotGeom.heading_offset = 2` 라 `h_phys = (h_plan + 2) % 4`
    다. 뒤집으면 `h_plan = (h_phys - 2) % 4` — 2 는 자기 역원이라 같은 식이다.
    **테스트 초기 배치에 쓸 것은 이쪽**이다. `step_h` 는 계획기 헤딩을 받는다.
    """
    return (h_phys + HEADING_OFFSET) % 4


def turning(w_row, k):
    return bool(w_row is not None and abs(w_row[k]) > W_TURN)


def dump(P, W, t, f, agents):
    """프레임 f 의 전 로봇 상태 한 줄씩."""
    w_row = W[f] if f < len(W) else None
    print(f"   t={t[f]:8.2f}s  frame={f}")
    for k in agents:
        x, y, yw = P[f, k]
        r, c = cell_of(x, y, PITCH)
        turn = turning(w_row, k)
        mark = " ★회전" if turn else ""
        # 회전 중이면 h 하나로 못 쓴다 — 앞뒤 프레임에서 시작·도착 헤딩을 본다.
        if turn:
            f0 = max(0, f - 60)
            f1 = min(len(P) - 1, f + 60)
            h0, h1 = heading_of(P[f0, k, 2]), heading_of(P[f1, k, 2])
            hs = f"h {to_plan(h0)}->{to_plan(h1)}"
        else:
            hs = f"h {to_plan(heading_of(yw))}    "
        print(f"     a{k:<3} ({r:>3},{c:>3})  {hs}"
              f"  yaw {yw:+7.3f}  xy ({x:7.3f},{y:7.3f}){mark}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("npz")
    ap.add_argument("--pair", default=None, help="예: 0-5. 기본은 최소 간격 쌍")
    ap.add_argument("--back", type=int, default=20, help="최소 프레임 앞으로 몇 프레임")
    a = ap.parse_args()

    z = load_npz(a.npz)
    t = np.asarray(z["t"], dtype=np.float64)
    P = np.asarray(z["pose"], dtype=np.float64)
    n = P.shape[1]
    dt = float(np.median(np.diff(t)))
    W = np.abs(np.diff(np.unwrap(P[:, :, 2], axis=0), axis=0)) / dt

    print(f"[in] {a.npz}  {len(t)} 프레임 · {n}대 · {t[-1]:.1f} s · pitch {PITCH}")
    print(f"     차체 뒤 {REAR} + 앞 {FRONT} · 폭 {WIDTH}")

    if a.pair:
        i, j = (int(v) for v in a.pair.split("-"))
        pairs = [(i, j)]
    else:
        pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]

    rows = closest_frames(P, pairs)
    if not rows:
        print("   후보 프레임이 없다 — 두 대가 한 번도 안 가까웠다")
        return 1
    gap, f_min, i, j = rows[0]
    print(f"\n══ 최소 간격 {gap * 1000:.1f} mm  ·  t={t[f_min]:.2f}s  ·  쌍 {i}-{j} ══")

    # --- 그 쌍만 시간순으로 ------------------------------------------------
    #   접촉은 한 순간이 아니라 접근의 끝이다. 어느 틱에 예약이 뚫렸는지
    #   보려면 다가오는 과정을 봐야 한다.
    print(f"\n   [1] 쌍 {i}-{j} 접근 과정 (간격 mm)")
    ci = corners(P[:, i, 0], P[:, i, 1], P[:, i, 2])
    cj = corners(P[:, j, 0], P[:, j, 1], P[:, j, 2])
    step = max(1, a.back // 10)
    for f in range(max(0, f_min - a.back), f_min + 1, step):
        g = sat_gap(ci[f], cj[f]) * 1000.0
        ri, ci_ = cell_of(P[f, i, 0], P[f, i, 1], PITCH)
        rj, cj_ = cell_of(P[f, j, 0], P[f, j, 1], PITCH)
        wi = "회전" if turning(W[f] if f < len(W) else None, i) else "  "
        wj = "회전" if turning(W[f] if f < len(W) else None, j) else "  "
        print(f"     t={t[f]:8.2f}  간격 {g:7.1f}   "
              f"a{i}({ri:>3},{ci_:>3}){wi}  a{j}({rj:>3},{cj_:>3}){wj}")

    # --- 전 로봇 상태 -------------------------------------------------------
    #   [C] 의 초기 배치로 쓰려면 둘만으로는 부족하다. 다른 로봇이 막고
    #   있었을 수도 있어서다. 접촉 순간과 그 앞 한 틱을 통째로 낸다.
    print(f"\n   [2] 전 로봇 상태 — `[C]` 초기 배치용")
    tick_frames = int(round((PITCH / (0.90 * 4)) / dt))     # 1틱 = 몇 프레임인가
    for f in (max(0, f_min - 5 * tick_frames), max(0, f_min - tick_frames), f_min):
        dump(P, W, t, f, range(n))
        print()

    print("   ★ 회전 중 로봇의 `h` 는 중간 각도라 반올림이 흔들린다.")
    print("     테스트에 쓸 것은 `h0->h1` 의 **h0**(회전 시작 헤딩)이다.")
    print(f"   ★ 1틱 = {tick_frames} 프레임 (tick_s {PITCH / (0.90 * 4):.4f} s"
          f" / dt {dt:.4f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
