# -*- coding: utf-8 -*-
"""**스위블이 회전을 방해하는가** — 녹화의 모든 회전에 대고 본다 (S15P21A106-224).

왜 분포가 필요한가
------------------
agent6 이 `turn(46,50,3)->(46,50,0)` 에서 축이 321 mm 밀려 영구 교착했다.
캐스터가 옛 방향에 갇혀 차체를 끌었다는 것이 후보인데, **그 회전 하나만
봐서는 판정이 안 된다.**

    a6 만 스위블이 안 돌고 나머지는 돌았다   ->  원인이다
    모든 회전에서 스위블이 안 돈다           ->  상시 조건이다. 방아쇠는 딴 것

그래서 녹화의 **모든 회전**을 뽑아 둘을 같이 잰다.

    스위블 비   스위블 적분각 / 차체 회전각      1 이면 같이 돈 것
    축 밀림     회전 구간의 축 이동 mm           예산 105 mm

그리고 **둘이 붙어 다니는지** 본다. 스위블 비가 낮은 회전에서만 밀림이 크면
인과가 선다. 무관하면 캐스터는 범인이 아니다.

회전을 어떻게 자르나
--------------------
각속도 문턱을 쓰지 않는다 — 그 방식은 같은 사건을 318 mm -> 119 mm 로
축소해 보이게 했다 (느린 구간이 잘려 나갔다). 대신 **축 정렬 평지**를 찾는다.

    yaw 가 90도 배수에서 NEAR_DEG 안에 있는 구간 = 평지
    헤딩이 다른 두 평지 사이 = 회전 한 번

쓰는 법
-------
    source paths.sh
    PITCH=1.0 python tools/swivel_sweep.py $OUT/rec_s7_cmd.npz

    NEAR_DEG   평지로 볼 각 오차 (기본 3도)
    MIN_DEG    회전으로 볼 최소 각 (기본 45도)
    BUDGET_MM  밀림 예산 (기본 105 — why_deadlock 이 낸 값)
"""
import math
import os
import sys

import numpy as np

PITCH = float(os.environ.get("PITCH", os.environ.get("PIBT_PITCH", "1.0")))
NEAR = math.radians(float(os.environ.get("NEAR_DEG", "3")))
MIN_DEG = float(os.environ.get("MIN_DEG", "45"))
BUDGET = float(os.environ.get("BUDGET_MM", "105"))
LOW = float(os.environ.get("LOW_RATIO", "0.25"))     # 「안 돌았다」 문턱


def wrap(a):
    return (a + np.pi) % (2.0 * np.pi) - np.pi


def plateaus(yaw):
    """축 정렬 평지 [(시작, 끝, 헤딩지수)] — 각속도 문턱을 안 쓴다."""
    q = np.round(yaw / (np.pi / 2.0)).astype(int)
    ok = np.abs(wrap(q * (np.pi / 2.0) - yaw)) < NEAR
    out, i = [], 0
    n = len(yaw)
    while i < n:
        if not ok[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and ok[j + 1] and q[j + 1] == q[i]:
            j += 1
        out.append((i, j, int(q[i] % 4)))
        i = j + 1
    return out


def turns(t, yaw):
    """헤딩이 다른 두 평지 사이 = 회전 하나."""
    ps = plateaus(yaw)
    out = []
    for (a0, a1, qa), (b0, b1, qb) in zip(ps, ps[1:]):
        if qa == qb:
            continue
        deg = math.degrees(abs(wrap(yaw[b0] - yaw[a1])))
        if deg < MIN_DEG:
            continue
        out.append((a1, b0, deg))
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args:
        raise SystemExit(__doc__)
    path = args[0]
    z = np.load(path, allow_pickle=True)
    t = np.asarray(z["t"], dtype=np.float64)
    pose = np.asarray(z["pose"], dtype=np.float64)
    if "joint" not in z.files:
        raise SystemExit("★ 이 녹화에는 관절이 없습니다 — `cmd`/`joint` 를 넣은 "
                         "뒤 다시 주행한 녹화가 필요합니다.")
    jnt = np.asarray(z["joint"], dtype=np.float64)
    dof = [str(s) for s in np.asarray(z["dof_names"]).tolist()]
    sw = [i for i, n in enumerate(dof) if "swivel" in n.lower()]
    if not sw:
        raise SystemExit(f"★ 스위블 관절이 없습니다: {dof}")

    print(f"[swivel_sweep] {os.path.basename(path)} · 로봇 {pose.shape[1]}대 · "
          f"{len(t):,} 프레임 · {t[0]:.1f}~{t[-1]:.1f}s")
    print(f"   DOF {len(dof)} · 스위블 {[dof[i] for i in sw]}")
    print(f"   평지 {math.degrees(NEAR):.0f}도 · 최소 회전 {MIN_DEG:.0f}도 · "
          f"예산 {BUDGET:.0f}mm")

    rows = []
    for a in range(pose.shape[1]):
        x, y, yaw = pose[:, a, 0], pose[:, a, 1], pose[:, a, 2]
        for i, j, deg in turns(t, np.unwrap(yaw)):
            dtv = np.diff(t[i:j + 1])
            ratios = []
            for s in sw:
                v = jnt[i:j + 1, a, s]
                turned = math.degrees(abs(np.sum(v[:-1] * dtv)))
                ratios.append(turned / deg if deg > 1e-6 else float("nan"))
            slide = math.hypot(x[j] - x[i], y[j] - y[i]) * 1000.0
            rows.append({"a": a, "i": i, "j": j, "deg": deg,
                         "ratio": float(np.mean(ratios)), "slide": slide,
                         "t0": t[i], "dur": t[j] - t[i]})

    if not rows:
        raise SystemExit("★ 회전을 못 찾았습니다 — NEAR_DEG/MIN_DEG 를 보세요.")

    ratio = np.array([r["ratio"] for r in rows])
    slide = np.array([r["slide"] for r in rows])
    print(f"\n── 회전 {len(rows)}개 ──")
    for lab, v, unit in (("스위블 비", ratio, ""), ("축 밀림", slide, "mm")):
        print(f"   {lab:<10} 중앙 {np.median(v):7.2f}  p95 {np.percentile(v, 95):7.2f}"
              f"  최대 {v.max():7.2f}{unit}")
    print(f"   예산 {BUDGET:.0f}mm 초과 회전 {(slide > BUDGET).sum()}개 / {len(rows)}")

    # ── ★ 인과 — 스위블이 안 돈 회전에서만 밀리는가 ──────────────────────
    lo = ratio < LOW
    print(f"\n── ★ 인과 — 스위블 비 {LOW} 미만 vs 이상 ──")
    print(f"   {'구분':<16}{'회전수':>8}{'밀림 중앙':>11}{'밀림 최대':>11}"
          f"{'예산초과':>10}")
    for lab, m in ((f"안 돎 (<{LOW})", lo), (f"돎 (>={LOW})", ~lo)):
        if not m.any():
            print(f"   {lab:<16}{0:>8}          —          —         —")
            continue
        print(f"   {lab:<16}{int(m.sum()):>8}{np.median(slide[m]):>10.1f}mm"
              f"{slide[m].max():>10.1f}mm{int((slide[m] > BUDGET).sum()):>10}")
    if lo.any() and (~lo).any():
        print(f"\n   두 무리의 밀림 중앙값 차이 "
              f"{np.median(slide[lo]) - np.median(slide[~lo]):+.1f} mm")
    good = np.isfinite(ratio) & np.isfinite(slide)
    if good.sum() > 2 and np.std(ratio[good]) > 1e-9:
        c = float(np.corrcoef(ratio[good], slide[good])[0, 1])
        print(f"   스위블 비 ↔ 밀림 상관 {c:+.2f}  "
              + ("(음이면 안 돌수록 많이 밀린다 = 인과에 부합)"
                 if c < 0 else "(양수 — 인과 방향과 반대다)"))

    # ── 최악 회전들 ──────────────────────────────────────────────────────
    print(f"\n── 밀림 상위 8 ──")
    print(f"   {'로봇':>5}{'t0':>9}{'지속':>8}{'회전각':>9}"
          f"{'스위블 비':>11}{'밀림':>10}")
    for r in sorted(rows, key=lambda r: -r["slide"])[:8]:
        mark = "   <- 예산 초과" if r["slide"] > BUDGET else ""
        print(f"   a{r['a']:<4}{r['t0']:>9.2f}{r['dur']:>7.2f}s"
              f"{r['deg']:>8.1f}도{r['ratio']:>11.2f}{r['slide']:>9.1f}mm{mark}")

    print(f"\n   읽는 법")
    print(f"    · **밀림 상위가 스위블 비 낮은 쪽에 몰리면** 캐스터가 원인이다.")
    print(f"    · 스위블 비가 전부 고르게 낮으면 상시 조건이라 방아쇠가 딴 데")
    print(f"      있다 — 그때는 밀린 회전만의 다른 공통점을 찾아야 한다.")
    print(f"    · 상관은 참고다. 회전 수가 적고 밀림이 꼬리 분포라 중앙값")
    print(f"      비교와 **상위 목록**이 더 믿을 만하다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
