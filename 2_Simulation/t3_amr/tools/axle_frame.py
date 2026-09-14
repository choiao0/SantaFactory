# -*- coding: utf-8 -*-
"""제자리 회전에서 축이 왜 42 mm 움직이나 — (a) 진짜 밀림 vs (b) 프레임 오차.

무엇이 이상한가
---------------
회전 액션은 `(v=0, w)` 를 낸다. 순수 회전이다. 차동구동의 이론상 회전 중심은
구동축 중점이고 그 점은 **움직이지 않아야 한다.** 그런데 실측이

    회전 중 축의 칸 중심 이탈    중앙 41.8   p95 65.9   최대 74.3 mm

중앙값 42 mm 는 노이즈가 아니라 구조적인 무언가다. 원인은 둘이다.

    (a) 진짜로 축이 밀린다 — 캐스터 마찰, 바퀴 미끄러짐, PhysX 접촉 모델
    (b) 축을 읽는 프레임이 틀렸다 — `axle_in_prim` 오프셋이 delta 만큼
        어긋나 있으면, 로봇은 제자리에서 도는데 **읽히는 축은 반경 delta 의
        원을 그린다**

어떻게 가리나 — 새 실행이 필요 없다
-----------------------------------
(b) 라면 읽힌 축은 정확히 이 모델을 따른다.

    p(t) = C + R(yaw(t)) . delta          C 는 진짜 축 (고정), delta 는 body 프레임 상수

    x = Cx + cos(yaw) dx - sin(yaw) dy
    y = Cy + sin(yaw) dx + cos(yaw) dy

`C` 와 `delta` 에 대해 **선형**이므로 회전 구간마다 최소제곱으로 푼다.

    잔차가 작다            -> 궤적이 깨끗한 원. (b) 쪽
    delta 가 구간마다 같다   -> **결정적**. body 프레임 상수라야 그렇다
    잔차가 크거나 delta 가 흩어진다 -> (a) 쪽

    ★ delta 의 일관성이 핵심이다. 원 하나는 우연히 맞을 수 있지만, 서로 다른
      로봇의 서로 다른 회전이 **같은 body 프레임 벡터**를 내놓을 이유는
      프레임 오차밖에 없다.

왜 중요한가
-----------
(b) 라면 예산만 좋아지는 게 아니다. 같은 축 위치로 차체 사각형·점유 칸·
차체 간 거리를 전부 계산한다. 그게 delta 만큼 어긋난 자리에 그려지고 있었다는
뜻이고, 두 로봇 사이 거리 판정은 delta 방향이 다르면 **2 delta 까지** 틀린다.

    source paths.sh
    PITCH=1.2 python tools/axle_frame.py $OUT/rec_fast.npz
"""
import os
import sys

import numpy as np

PITCH = float(os.environ.get("PITCH", os.environ.get("PIBT_PITCH", "1.2")))
W_MIN = float(os.environ.get("W_MIN", "0.15"))     # rad/s
MIN_DEG = float(os.environ.get("MIN_DEG", "45"))
MIN_N = int(os.environ.get("MIN_N", "12"))          # 구간 최소 프레임


def segments(t, yaw):
    """회전 구간 [i, j] 인덱스 목록."""
    yaw = np.unwrap(yaw)
    dt = np.diff(t)
    dt[dt <= 0] = np.nan
    spin = np.nan_to_num(np.abs(np.diff(yaw) / dt)) > W_MIN
    out, i, n = [], 0, len(spin)
    while i < n:
        if not spin[i]:
            i += 1
            continue
        j = i
        while j < n and spin[j]:
            j += 1
        if abs(np.degrees(yaw[j] - yaw[i])) >= MIN_DEG and (j - i) >= MIN_N:
            out.append((i, j))
        i = j + 1
    return out


def fit(x, y, yaw):
    """p = C + R(yaw).delta 를 최소제곱으로. (delta, 잔차RMS, 설명력) 반환."""
    c, s = np.cos(yaw), np.sin(yaw)
    n = len(x)
    # [Cx, Cy, dx, dy]
    A = np.zeros((2 * n, 4))
    A[0::2, 0] = 1.0
    A[1::2, 1] = 1.0
    A[0::2, 2] = c
    A[0::2, 3] = -s
    A[1::2, 2] = s
    A[1::2, 3] = c
    b = np.empty(2 * n)
    b[0::2] = x
    b[1::2] = y
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    res = b - A @ sol
    rms = float(np.sqrt(np.mean(res ** 2)))
    # 비교 기준: delta 없이 중심만 (= 흩어짐 그 자체)
    b0 = b - np.repeat([[x.mean(), y.mean()]], n, axis=0).ravel()
    rms0 = float(np.sqrt(np.mean(b0 ** 2)))
    expl = 0.0 if rms0 <= 1e-12 else max(0.0, 1.0 - (rms / rms0) ** 2)
    return np.array([sol[2], sol[3]]), rms, rms0, expl


def main():
    paths = [p for p in sys.argv[1:] if not p.startswith("-")]
    if not paths:
        raise SystemExit(__doc__)
    for path in paths:
        if not os.path.exists(path):
            print(f"* 없음: {path}")
            continue
        z = np.load(path, allow_pickle=True)
        t = np.asarray(z["t"], dtype=np.float64)
        pose = np.asarray(z["pose"], dtype=np.float64)
        print()
        print("=" * 68)
        print(f"{os.path.basename(path)}   회전 프레임 모델 p = C + R(yaw).delta")
        print("=" * 68)

        rows = []
        for a in range(pose.shape[1]):
            x, y, yw = pose[:, a, 0], pose[:, a, 1], np.unwrap(pose[:, a, 2])
            for i, j in segments(t, pose[:, a, 2]):
                d, rms, rms0, expl = fit(x[i:j + 1], y[i:j + 1], yw[i:j + 1])
                rows.append((a, d, rms, rms0, expl))
        if not rows:
            print("  회전 구간 없음")
            continue

        D = np.array([r[1] for r in rows]) * 1000.0        # mm
        rms = np.array([r[2] for r in rows]) * 1000.0
        rms0 = np.array([r[3] for r in rows]) * 1000.0
        expl = np.array([r[4] for r in rows]) * 100.0

        print(f"  회전 {len(rows)}개  ·  로봇 {len({r[0] for r in rows})}대")
        print()
        print("  1) 원 모델이 궤적을 얼마나 설명하나")
        print(f"     delta 없이 흩어짐 (기준)   RMS 중앙 {np.median(rms0):7.1f} mm")
        print(f"     원 모델 잔차               RMS 중앙 {np.median(rms):7.1f} mm"
              f"   p95 {np.percentile(rms, 95):6.1f}")
        print(f"     설명력                     중앙 {np.median(expl):6.1f}%"
              f"   (구간별 최소 {expl.min():.1f}%)")
        print()
        print("  2) delta 가 구간마다 같은가  <- 결정적")
        print(f"     dx  중앙 {np.median(D[:, 0]):7.1f}  표준편차 {D[:, 0].std():6.1f} mm")
        print(f"     dy  중앙 {np.median(D[:, 1]):7.1f}  표준편차 {D[:, 1].std():6.1f} mm")
        mag = np.hypot(D[:, 0], D[:, 1])
        print(f"     |delta| 중앙 {np.median(mag):7.1f}  p95 {np.percentile(mag, 95):6.1f}"
              f"  최대 {mag.max():6.1f} mm")
        print()
        print("     로봇별 delta 중앙값 (body 프레임, x=전방)")
        for a in sorted({r[0] for r in rows}):
            sub = np.array([r[1] for r in rows if r[0] == a]) * 1000.0
            print(f"       agent{a:<3} n={len(sub):<3} "
                  f"dx {np.median(sub[:, 0]):7.1f}  dy {np.median(sub[:, 1]):7.1f}"
                  f"   |d| {np.median(np.hypot(sub[:, 0], sub[:, 1])):6.1f} mm")

        # ── 판정 ────────────────────────────────────────────────────────
        print()
        spread = float(np.hypot(D[:, 0].std(), D[:, 1].std()))
        med = float(np.median(mag))
        print("  3) 판정")
        ratio = spread / max(med, 1.0)
        print(f"     delta 흩어짐 {spread:.1f} mm  /  |delta| 중앙 {med:.1f} mm"
              f"  =  {ratio:.2f}        <- 이게 1차 기준")
        print(f"     설명력 중앙 {np.median(expl):.1f}%   (참고용 — 아래 단서)")
        print()
        # ★ 1차 기준은 **설명력이 아니라 delta 의 일관성**이다.
        #   90도 구간 하나만 보면 C 와 delta 가 부분적으로 겹쳐서, 단순한
        #   직선 밀림도 원 모델이 90% 넘게 "설명" 해 버린다. 합성 검증에서
        #   (a)·(b) 둘 다 설명력 90.1% 가 나왔다. 구분한 것은 흩어짐이었다
        #   ((b) 0.0 mm  vs  (a) 26.6 mm).
        if ratio < 0.30:
            print("     -> **(b) 프레임 오차** 쪽이다.")
            print("        서로 다른 로봇의 서로 다른 회전이 **같은 body 프레임")
            print("        벡터**를 내놓을 이유는 프레임 오차밖에 없다.")
            print(f"        axle_in_prim 에 약 ({np.median(D[:, 0]):.1f},"
                  f" {np.median(D[:, 1]):.1f}) mm 가 빠져 있다.")
            print("        ★ 차체 사각형·점유 칸·차체 간 거리가 전부 이 delta 를")
            print("          품고 있었다. 두 대 사이 판정은 2 delta 까지 틀린다.")
        elif ratio > 0.60:
            print("     -> **(a) 진짜 밀림** 쪽이다. delta 가 회전마다 다르다.")
            print("        74 mm 는 실제 예산 소모다. 1.0 재측정에서 더 커질 것을")
            print("        예상해야 한다 — 정지·출발이 늘면 마찰 사건도 는다.")
        else:
            print("     -> 섞여 있다. 일관된 성분과 흩어진 성분이 함께 있다.")
            print("        로봇별 delta 표를 보라. 로봇마다 다르면 프레임이 아니라")
            print("        개체차(질량 분포·초기 자세)일 수 있다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
