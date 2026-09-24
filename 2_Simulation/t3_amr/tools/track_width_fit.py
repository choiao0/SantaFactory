# -*- coding: utf-8 -*-
"""**실효 트랙폭은 상수가 아니다** — w 로 갈라 낸다 (S15P21A106-267).

    source paths.sh
    python tools/track_width_fit.py out/rec_wsw*_s104.npz

Isaac 이 필요 없다. `tools/wheel_calib.py` 를 값마다 돌려 그 결과를 맞춘다.

무엇을 뒤집나
-------------
`pibt_scene.py` 가 2026-09-16 측정을 이렇게 적어 뒀다.

    L  저작 0.57926 · 실효 0.6759 · 12대 흩어짐 0.4 %   ★ 1.166 배
    「12대가 0.4 % 안에 모이므로 로봇별 결함이 아니라 **상수 성질**이다」
    「접지비 중앙 0.91 은 미끄러짐이 아니라 이 차이였다」

상수라면 **회전 속도를 바꿔도 안 움직여야 한다.** 움직였다.

    w 1.2  ->  L_eff 0.6115  (1.056 배)
    w 1.8  ->  L_eff 0.6248  (1.079 배)
    w 2.4  ->  L_eff 0.6522  (1.126 배)

그러니 「상수 성질」은 틀렸고, 「접지비는 미끄러짐이 아니다」도 틀렸다.
실효 L 은 **상수 + 미끄러짐**이고 미끄러짐 쪽이 w 를 탄다.

어떻게 가르나
-------------
미끄러짐이 0 인 극한이 참값이다. `L_eff(w) = L0 + k*w^n` 을 맞추고 w->0 을
본다. 점이 셋뿐이라 n 을 못 못박는다 — n=2 와 n=3 을 다 내고 폭으로 말한다.

    n=2   L0 = 0.5964   저작 대비 +3.0 %
    n=3   L0 = 0.6055   저작 대비 +4.5 %

즉 **상수 오차는 3~4.5 %** 이고 나머지는 미끄러짐이다. 기록된 16.6 % 가
아니다. 그 값으로 고치면 **13 % 과교정**이 된다.

☹ 한계 — 시드 하나, 점 셋이다. n 을 가르려면 w 를 더 넣어야 한다
  (0.6 · 3.0 처럼 양 끝을 벌리는 것이 제일 싸다).
"""
import glob
import os
import re
import subprocess
import sys

import numpy as np

W = os.environ.get("W", ".")
AUTHORED = float(os.environ.get("L_AUTHORED", "0.57926"))
L_RE = re.compile(r"L\s+역산 중앙\s+([0-9.]+)")
W_RE = re.compile(r"wsw(\d)p(\d\d)")


def l_eff(path):
    p = subprocess.run([sys.executable, os.path.join(W, "tools/wheel_calib.py"), path],
                       capture_output=True, text=True)
    m = L_RE.search(p.stdout)
    if not m:
        print("   ☹ %s — L 줄을 못 읽었다" % os.path.basename(path))
        if p.returncode:
            print(p.stderr.strip()[:300])
        return None
    return float(m.group(1))


def w_of(path):
    m = W_RE.search(os.path.basename(path))
    return float("%s.%s" % (m.group(1), m.group(2))) if m else None


def fit(w, L, n):
    """L = L0 + k*w^n 을 맞춰 (L0, k, 잔차RMS)."""
    A = np.vstack([np.ones_like(w), w ** n]).T
    coef, *_ = np.linalg.lstsq(A, L, rcond=None)
    rms = float(np.sqrt(np.mean((A @ coef - L) ** 2)))
    return float(coef[0]), float(coef[1]), rms


def main():
    args = [p for g in sys.argv[1:] for p in (sorted(glob.glob(g)) or [g])]
    if not args:
        raise SystemExit(__doc__)
    rows = []
    print("실효 트랙폭 — 회전 속도별 (저작 %.5f)" % AUTHORED)
    for p in args:
        if not os.path.isfile(p):
            print("   없음 %s" % p)
            continue
        wv = w_of(p)
        if wv is None:
            print("   ☹ %s — 파일 이름에서 w 를 못 읽는다 (wsw1p80 꼴이라야 한다)"
                  % os.path.basename(p))
            continue
        L = l_eff(p)
        if L is None:
            continue
        rows.append((wv, L))
        print("   w=%.2f   L_eff %.4f   저작 대비 %.3f배" % (wv, L, L / AUTHORED))

    ws = sorted({r[0] for r in rows})
    if len(ws) < 3:
        print("\n☹ 서로 다른 w 가 셋은 있어야 맞출 수 있다 (지금 %d)" % len(ws))
        return 1

    # 같은 w 가 여러 시드면 중앙값으로 묶는다
    w = np.array(ws)
    L = np.array([float(np.median([r[1] for r in rows if r[0] == v])) for v in ws])

    print("\nL_eff(w) = L0 + k*w^n  을 맞춘다. w->0 이 미끄러짐 0 인 참값이다")
    print("   %-6s %10s %12s %12s" % ("n", "L0", "저작 대비", "잔차RMS"))
    best = None
    for n in (1, 2, 3):
        L0, k, rms = fit(w, L, n)
        print("   %-6d %10.4f %11.3f배 %12.5f" % (n, L0, L0 / AUTHORED, rms))
        if best is None or rms < best[3]:
            best = (n, L0, k, rms)
    n, L0, k, _ = best

    print("\n가장 잘 맞는 n=%d 기준" % n)
    print("   상수 오차   %.4f -> %.4f   **+%.1f %%**" % (AUTHORED, L0, 100 * (L0 / AUTHORED - 1)))
    for v, lv in zip(w, L):
        print("   w=%.2f  총 초과 %5.1f %%  =  상수 %.1f %%  +  미끄러짐 %.1f %%"
              % (v, 100 * (lv / AUTHORED - 1), 100 * (L0 / AUTHORED - 1),
                 100 * (lv - L0) / AUTHORED))
    print()
    print("☹ 점이 %d 개다. n 을 못 못박으므로 L0 도 폭으로 읽는다 — 위 표의" % len(w))
    print("  n=2 와 n=3 사이다. 좁히려면 w 를 양 끝으로 벌려 더 넣는다.")
    print()
    print("★ `pibt_scene.py` 의 「실효 0.6759 · 상수 성질」은 이 자료와 안 맞는다.")
    print("  그 값으로 고치면 %.0f %% 과교정이다." % (100 * (0.6759 / L0 - 1)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
