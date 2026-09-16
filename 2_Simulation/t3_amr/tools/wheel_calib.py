# -*- coding: utf-8 -*-
"""바퀴 상수가 맞나 — 녹화에서 **실효값을 역산**한다 (S15P21A106-224).

왜 필요한가
-----------
`swivel_sweep` 의 접지비는 이렇게 계산한다.

    바퀴가 요구한 각속도  w_wheel = R (r - l) / L
    접지비 = 차체가 실제로 돈 각 / w_wheel 적분

그런데 `R`(0.08) 이나 `L`(0.5796) 이 틀리면 접지비가 통째로 어긋난다.
89 개 회전이 전부 0.88~0.95 로 **고르게** 나온 것이 실제 미끄러짐이 아니라
**상수 배율 오차**일 수 있다는 뜻이다. 그러면 결론이 뒤집힌다.

상수의 출처는 주석 두 줄뿐이다 (`pibt_scene.py:135`).

    WHEEL_RADIUS = 0.08     # iw_hub.usd 조인트 저작값
    WHEEL_BASE = 0.5796     # localPos0 = ±0.28963

저작값과 **실제로 구동 중인 로봇**이 다를 수 있다 — prim 에 스케일이 걸렸거나
`metersPerUnit` 이 다르면 그렇다. 그래서 USD 를 읽는 것과 별개로, 주행 기록에서
역산해 맞춰 본다.

어떻게 역산하나
---------------
    직진 구간  v_body = R (l + r) / 2          -> R 을 준다 (미끄러짐이 적다)
    회전 구간  w_body = R (r - l) / L          -> R 을 넣으면 L 을 준다

직진에서 R 을 먼저 잡는 이유는, 직진이 접지가 좋아 (명령·바퀴·실측이 세 자리까지
맞는다) **미끄러짐이 R 을 오염시키지 않기** 때문이다. 회전은 반대로 미끄러짐과
`L` 오차가 **같은 방향으로 섞인다** — 그래서 회전에서 나온 `L` 은 「미끄러짐이
없었다면 L 이 이만큼이어야 한다」는 상한으로 읽어야 한다.

★ 로봇별로 낸다. 한 대만 다르면 그 로봇의 에셋·prim 이 다른 것이고, 전부 같이
  다르면 상수가 틀린 것이다. 둘은 고치는 데가 다르다.

쓰는 법
-------
    source paths.sh
    python tools/wheel_calib.py $OUT/rec_s7_cmd.npz
"""
import math
import os
import sys

import numpy as np

R_CFG = float(os.environ.get("WHEEL_RADIUS", "0.08"))
L_CFG = float(os.environ.get("WHEEL_BASE", "0.5796"))
VMIN = float(os.environ.get("VMIN", "0.15"))        # 직진으로 볼 최소 속도
WMIN = float(os.environ.get("WMIN", "0.30"))        # 회전으로 볼 최소 각속도
YAW_TOL = math.radians(float(os.environ.get("YAW_TOL", "5")))


def wrap(a):
    return (a + np.pi) % (2.0 * np.pi) - np.pi


def slope(x, y):
    """원점을 지나는 최소제곱 기울기와 표본수."""
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    if len(x) < 30 or float(np.sum(x * x)) <= 1e-12:
        return float("nan"), len(x)
    return float(np.sum(x * y) / np.sum(x * x)), len(x)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args:
        raise SystemExit(__doc__)
    z = np.load(args[0], allow_pickle=True)
    if "joint" not in z.files:
        raise SystemExit("★ 관절이 없는 녹화입니다 — cmd/joint 를 넣은 뒤 주행한 "
                         "기록이 필요합니다.")
    t = np.asarray(z["t"], dtype=np.float64)
    pose = np.asarray(z["pose"], dtype=np.float64)
    jnt = np.asarray(z["joint"], dtype=np.float64)
    dof = [str(s) for s in np.asarray(z["dof_names"]).tolist()]

    def find(*keys, default=None):
        for n, nm in enumerate(dof):
            if all(k in nm.lower() for k in keys):
                return n
        return default
    li, ri = find("left", "wheel", default=0), find("right", "wheel", default=1)

    print(f"[wheel_calib] {os.path.basename(args[0])} · 로봇 {pose.shape[1]}대 · "
          f"{len(t):,} 프레임")
    print(f"   코드 상수  R={R_CFG}  L={L_CFG}   "
          f"(pibt_scene.py:135 — 「iw_hub.usd 조인트 저작값」)")
    print(f"   바퀴 관절  L={dof[li]}  R={dof[ri]}")

    # ★ 시간 창. **사고 구간을 빼고 다시 재는** 데 쓴다 -- 이상치 한 대의
    #   L 역산이 그 사고 자체 때문에 커진 것인지(순환) 원래 다른 것인지는
    #   구간을 빼 보면 갈린다.
    t0 = float(os.environ.get("T0", t[0]))
    t1 = float(os.environ.get("T1", t[-1]))
    if t0 > t[0] or t1 < t[-1]:
        print(f"   ★ 시간 창 {t0:.1f}~{t1:.1f}s 만 쓴다")
    win = (t[:-1] >= t0) & (t[:-1] <= t1)

    dt = np.diff(t)
    dt[dt <= 0] = np.nan
    rows = []
    for a in range(pose.shape[1]):
        x, y, yaw = pose[:, a, 0], pose[:, a, 1], pose[:, a, 2]
        vx, vy = np.diff(x) / dt, np.diff(y) / dt
        wb = wrap(np.diff(yaw)) / dt
        # 전진/후진 부호를 붙인 차체 속도
        vb = vx * np.cos(yaw[:-1]) + vy * np.sin(yaw[:-1])
        wl, wr = jnt[:-1, a, li], jnt[:-1, a, ri]

        # ── 직진: 두 바퀴가 같은 방향, 차체가 거의 안 돈다 ──────────────
        st = ((np.abs(vb) > VMIN) & (np.abs(wb) < 0.05)
              & (np.abs(wr - wl) < 0.3 * np.abs(wr + wl) + 1e-9))
        r_fit, n_st = slope((wl[st] + wr[st]) / 2.0, vb[st])

        # ── 회전: 두 바퀴가 반대 방향, 차체가 돈다 ──────────────────────
        tn = (np.abs(wb) > WMIN) & (np.abs(wl + wr) < 0.3 * np.abs(wr - wl) + 1e-9)
        # w_body = (R/L)(r - l)  ->  기울기가 R/L
        k_fit, n_tn = slope(wr[tn] - wl[tn], wb[tn])
        l_fit = (r_fit / k_fit) if (np.isfinite(k_fit) and abs(k_fit) > 1e-9
                                    and np.isfinite(r_fit)) else float("nan")
        rows.append((a, r_fit, n_st, l_fit, n_tn, k_fit))

    print(f"\n── 로봇별 실효값 ──")
    print(f"   {'로봇':>5}{'R 역산':>10}{'R 비':>8}{'직진표본':>10}"
          f"{'L 역산':>10}{'L 비':>8}{'회전표본':>10}")
    for a, r_fit, n_st, l_fit, n_tn, _k in rows:
        print(f"   a{a:<4}{r_fit:>10.4f}{r_fit / R_CFG:>8.3f}{n_st:>10,}"
              f"{l_fit:>10.4f}{l_fit / L_CFG:>8.3f}{n_tn:>10,}")

    rs = np.array([r[1] for r in rows], dtype=float)
    ls = np.array([r[3] for r in rows], dtype=float)
    rf, lf = rs[np.isfinite(rs)], ls[np.isfinite(ls)]
    print(f"\n── 판정 ──")
    if len(rf):
        print(f"   R  역산 중앙 {np.median(rf):.4f} · 흩어짐 {rf.std():.5f} · "
              f"코드 대비 {np.median(rf) / R_CFG:.3f}배")
    if len(lf):
        print(f"   L  역산 중앙 {np.median(lf):.4f} · 흩어짐 {lf.std():.5f} · "
              f"코드 대비 {np.median(lf) / L_CFG:.3f}배")

    print(f"\n   읽는 법")
    print(f"    · **R 비가 1 에서 벗어나면** 바퀴 반지름이 틀린 것이다. 직진은")
    print(f"      접지가 좋아 미끄러짐이 거의 안 섞이므로 이 값은 믿을 만하다.")
    print(f"    · **L 비**는 미끄러짐과 구분되지 않는다. 회전에서 차체가 덜 도는")
    print(f"      것은 (가) L 이 실제로 더 크거나 (나) 미끄러진 것인데, 회전")
    print(f"      데이터만으로는 못 가른다. 그래서 이 값은 「미끄러짐이 전혀")
    print(f"      없었다면 L 이 이만큼이어야 한다」는 **상한**이다.")
    print(f"    · ★ 흩어짐이 작고 비가 1 이 아니면 **상수가 틀린 것**이다 —")
    print(f"      12대가 같이 틀리는 것은 상수밖에 없다. 반대로 한 대만 다르면")
    print(f"      그 로봇의 prim·스케일을 봐야 한다.")
    print(f"    · L 비가 접지비 중앙(0.91)의 역수(1.10) 근처면, 접지비는")
    print(f"      미끄러짐이 아니라 **교정 오차**였다는 뜻이다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
