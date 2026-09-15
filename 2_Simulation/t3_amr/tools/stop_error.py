# -*- coding: utf-8 -*-
"""**로봇이 멈춰 선 자리가 칸 중심에서 얼마나 벗어나나** — 세로(진행축) 오차.

왜
--
2026-09-15 접촉 두 건에서 **회전하는 쪽이 자기 진행축으로 46~48 mm 벗어난
채** 돌았고, 인접 행에서 그것이 순수 가로 손실이 되어 설계 여유 41.3 mm 를
넘겼다 (`2026-09-16_회전중_차체접촉_5판중2판.md` §3-4).

그 47 mm 에 대해 **답이 없는 질문이 셋**이다. 이 도구가 셋을 한 번에 답한다.

    [1] 언제 생기나   전진이 못 미쳐 멈춘 것인가, 서 있는 동안 밀린 것인가
    [2] §10-4 의 세로 계통 오차 -34.2 와 같은 것인가
                      그쪽은 **회전 종료** 자세, 이쪽은 **회전 시작 전** 정지다
    [3] 얼마나 흔한가  ★ 제일 중요하다

[3] 이 제일 중요한 이유: 세로 이탈이 **늘 47쯤이라면** 접촉은 5판 중 2판이
아니라 훨씬 자주 나야 한다. 안 났다는 것은 다른 조건이 같이 필요하다는 뜻
이고(상대가 인접 행 · 그 순간 회전 · 방향이 상대 쪽), 그러면 **47 만 고쳐도
배치가 바뀌면 또 난다.**

    46~48 이 꼬리(p99)면   -> 드문 사건. 47 을 줄이면 확실히 없어진다
    중앙 근처면            -> 늘 있는 값. 가르는 것은 배치 쪽이다

무엇을 재나
-----------
「멈춰 있던 구간」마다 두 값을 뽑는다.

    도착 이탈   구간 **시작** — 전진이 끝났을 때 얼마나 벗어나 있었나
    출발 이탈   구간 **끝**   — 다음 동작을 시작할 때
    밀림        둘의 차이     — 서 있는 동안 움직였나

★ 진행축 분해는 **축에 정렬돼 있을 때만** 유효하다. 헤딩이 격자축에서
  `AXIS_TOL` 이상 벗어난 구간은 버린다 (회전 중인 프레임이 섞이면 세로·가로가
  뒤섞여 830 mm 같은 값이 나온다 — `tail_yaw.frame_cells` 가 같은 이유로
  회전 프레임을 '회전' 으로만 찍는다).

쓰는 법
-------
    source paths.sh
    PITCH=1.0 python tools/stop_error.py $OUT/rec_s2.npz

    --agent 0     그 로봇의 시간축 추적을 같이 찍는다 ([1] 을 눈으로 본다)
    --mark 47     분포에서 이 값이 몇 퍼센타일인지 (기본 47)
"""
import argparse
import math
import os
import sys

import numpy as np

PITCH = float(os.environ.get("PITCH", os.environ.get("PIBT_PITCH", "1.2")))
V_MOVE = float(os.environ.get("V_MOVE", "0.05"))     # m/s — 이 위면 움직이는 중
W_MOVE = float(os.environ.get("W_MOVE", "0.15"))     # rad/s — 이 위면 도는 중
AXIS_TOL = float(os.environ.get("AXIS_TOL", "0.10"))  # rad — 격자축에서 6도
MIN_HOLD = float(os.environ.get("MIN_HOLD", "0.30"))  # s — 이보다 짧은 정지는 버린다


def load_npz(path):
    """`$OUT` 이 비어 `/` 로 간 경우를 이름 붙여 잡는다 (contact_frame 과 같은 이유)."""
    if not os.path.exists(path):
        hint = ""
        if os.path.dirname(path) == os.sep:
            hint = ("\n  ★ 경로가 '/' 에서 시작합니다 — `$OUT` 이 비어서 그리"
                    " 간 것이 흔합니다.\n"
                    "     `source paths.sh` 를 **이 셸에서** 먼저 하거나"
                    " 절대경로를 주세요.")
        raise SystemExit(f"[stop_error] 없는 파일: {path!r}{hint}")
    return np.load(path, allow_pickle=True)


def axis_offset(yaw):
    """격자축(0·90·180·270°)에서 얼마나 벗어났나 [rad]. 0 이면 정렬."""
    d = (yaw + math.pi / 4) % (math.pi / 2) - math.pi / 4
    return d


def decompose(x, y, yaw, pitch):
    """칸 중심 오차를 진행축 기준으로 -> (세로, 가로) m.

    세로 + 는 진행 방향으로 지나침, 가로 + 는 진행 기준 왼쪽.
    """
    o = pitch / 2.0
    ex = x - (o + round((x - o) / pitch) * pitch)
    ey = y - (o + round((y - o) / pitch) * pitch)
    c, s = math.cos(yaw), math.sin(yaw)
    return ex * c + ey * s, -ex * s + ey * c


def holds(t, x, y, yaw):
    """멈춰 있던 구간 목록 — (시작 세로, 끝 세로, 시작 가로, 지속, i, j)."""
    dt = np.diff(t)
    dt[dt <= 0] = np.nan
    v = np.nan_to_num(np.hypot(np.diff(x), np.diff(y)) / dt)
    w = np.nan_to_num(np.abs(np.diff(np.unwrap(yaw))) / dt)
    still = (v < V_MOVE) & (w < W_MOVE)

    out, i, n = [], 0, len(still)
    while i < n:
        if not still[i]:
            i += 1
            continue
        j = i
        while j < n and still[j]:
            j += 1
        if t[j] - t[i] >= MIN_HOLD:
            # 축에 정렬돼 있어야 세로·가로 분해가 성립한다.
            if abs(axis_offset(yaw[i])) < AXIS_TOL:
                lon0, lat0 = decompose(x[i], y[i], yaw[i], PITCH)
                lon1, _ = decompose(x[j], y[j], yaw[j], PITCH)
                out.append((lon0 * 1000, lon1 * 1000, lat0 * 1000,
                            float(t[j] - t[i]), i, j))
        i = j + 1
    return out


def pct_of(v, val):
    """`val` 이 |v| 분포에서 몇 퍼센타일인가."""
    a = np.abs(np.asarray(v, dtype=float))
    return 100.0 * float((a <= val).mean())


def report(path, rows, mark):
    lon0 = np.array([r[0] for r in rows])
    lon1 = np.array([r[1] for r in rows])
    lat0 = np.array([r[2] for r in rows])
    drift = lon1 - lon0

    print(f"\n   정지 구간 {len(rows)}개  (>= {MIN_HOLD} s · 축 정렬만)")
    print()
    print(f"   {'':<16}{'중앙':>9}{'p90':>9}{'p95':>9}{'p99':>9}{'최대':>9}   mm")
    for nm, a in (("도착 세로 |·|", np.abs(lon0)),
                  ("출발 세로 |·|", np.abs(lon1)),
                  ("도착 가로 |·|", np.abs(lat0)),
                  ("밀림 |·|", np.abs(drift))):
        print(f"   {nm:<16}{np.median(a):>9.1f}{np.percentile(a, 90):>9.1f}"
              f"{np.percentile(a, 95):>9.1f}{np.percentile(a, 99):>9.1f}"
              f"{a.max():>9.1f}")

    # --- [2] 계통인가 --------------------------------------------------
    #   무작위면 부호 있는 중앙이 0 근처여야 한다. 한쪽으로 치우쳐 있으면
    #   목표점이 틀린 것이고 **고칠 수 있다.**
    print()
    print("   [2] 부호 있는 세로 — 계통인가 (§10-4 의 -34.2 와 대볼 것)")
    print(f"     도착 중앙 {np.median(lon0):+7.1f}  평균 {lon0.mean():+7.1f}"
          f"  양수 비율 {100.0 * (lon0 > 0).mean():5.1f}%")
    print("     (세로 + 는 진행 방향으로 지나침)")

    # --- [3] 47 이 어디쯤인가 ------------------------------------------
    print()
    print(f"   [3] ★ {mark:.0f} mm 는 얼마나 흔한가")
    p = pct_of(lon0, mark)
    print(f"     도착 세로 |·| 분포에서 **{p:.1f} 퍼센타일**"
          f"   ({int(round((100 - p) / 100 * len(rows)))}개 / {len(rows)}개가 더 크다)")
    if p >= 99.0:
        print("     -> 꼬리다. 47 을 줄이면 이 배치는 확실히 없어진다.")
    elif p >= 90.0:
        print("     -> 드문 편이지만 꼬리라고 하긴 어렵다. 배치 조건도 같이 봐야 한다.")
    else:
        print("     -> ★ 흔한 값이다. 접촉을 가르는 것은 **배치** 쪽이고,")
        print("        47 만 고쳐도 배치가 바뀌면 또 난다.")

    # --- [1] 도착에서 생기나 서 있다 밀리나 ----------------------------
    print()
    print("   [1] 도착 시점에 이미 있었나, 서 있는 동안 밀렸나")
    big = [r for r in rows if abs(r[0]) >= mark * 0.8]
    print(f"     도착부터 {mark * 0.8:.0f} mm 이상이던 구간 {len(big)}개"
          f" ({100.0 * len(big) / len(rows):.1f}%)")
    print(f"     밀림 중앙 {np.median(np.abs(drift)):.1f} mm ·"
          f" p99 {np.percentile(np.abs(drift), 99):.1f} mm")
    # ★ `big` 이 비면 판정하면 안 된다. 「밀림이 작으니 도착 시점에 있던
    #   값」은 그런 구간이 실제로 있을 때만 하는 말이다 — 없으면 이 녹화에
    #   그 배치가 안 나온 것이고, 그 자체가 답이다.
    if not big:
        print(f"     -> 이 녹화에는 {mark * 0.8:.0f} mm 이상인 정지가 **없다.**")
        print("        접촉이 난 판과 안 난 판을 같이 돌려 비교할 것.")
    elif np.percentile(np.abs(drift), 99) < mark * 0.3:
        print(f"     -> 밀림이 작다. {mark:.0f} 은 **도착 시점에 이미 있던 값**이다")
        print("        (고칠 곳은 홀딩이 아니라 **정지 제어**).")
    else:
        print("     -> 밀림이 무시 못 할 크기다. 홀딩 쪽도 봐야 한다.")


def trace(t, x, y, yaw, k, rows):
    """한 로봇의 정지 구간을 시간순으로 — [1] 을 눈으로 본다."""
    print(f"\n   [추적] agent{k} 의 정지 구간")
    print(f"     {'t0':>8}{'t1':>8}{'지속':>7}{'도착세로':>10}{'출발세로':>10}"
          f"{'밀림':>8}{'도착가로':>10}   mm")
    for lon0, lon1, lat0, dur, i, j in rows:
        print(f"     {t[i]:>8.2f}{t[j]:>8.2f}{dur:>7.2f}"
              f"{lon0:>+10.1f}{lon1:>+10.1f}{lon1 - lon0:>+8.1f}{lat0:>+10.1f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("npz", nargs="+")
    ap.add_argument("--agent", type=int, default=None, help="이 로봇의 추적도 찍는다")
    ap.add_argument("--mark", type=float, default=47.0, help="퍼센타일을 볼 값 mm")
    a = ap.parse_args()

    print(f"정지 자리 세로(진행축) 오차 — pitch {PITCH}"
          f" · 정지 판정 v<{V_MOVE} w<{W_MOVE} · 축정렬 {AXIS_TOL} rad")

    for path in a.npz:
        z = load_npz(path)
        t = np.asarray(z["t"], dtype=np.float64)
        P = np.asarray(z["pose"], dtype=np.float64)
        print(f"\n══ {os.path.basename(path)} "
              f"{len(t)} 프레임 · {P.shape[1]}대 · {t[-1]:.1f} s " + "═" * 12)

        allrows = []
        for k in range(P.shape[1]):
            rows = holds(t, P[:, k, 0], P[:, k, 1], P[:, k, 2])
            allrows += rows
            if a.agent is not None and k == a.agent:
                trace(t, P[:, k, 0], P[:, k, 1], P[:, k, 2], k, rows)
        if not allrows:
            print("   정지 구간을 못 찾았다 — V_MOVE / MIN_HOLD 를 확인하라")
            continue
        report(path, allrows, a.mark)

    print()
    print("* 세로 + 는 진행 방향으로 지나침. 계통이면 중앙이 0 에서 멀다.")
    print("* 접촉 여유는 41.3 mm 다 (인접 행 · 한쪽 회전). 그 선과 대볼 것.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
