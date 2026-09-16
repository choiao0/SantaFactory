# -*- coding: utf-8 -*-
"""요잉 오차가 **일부러 유지되는 각도인지** 를 가른다 (S15P21A106-224).

왜 이걸 먼저 재는가
-------------------
꼬리 이탈이 예산 100 mm 를 넘는다 (실측 100.2~109.2). 손잡이는 하나뿐이다:

    w = K_CROSS*cross + K_HEAD*head          # isaac_drive.py:1519
        K_CROSS = 1.8,  K_HEAD = 2.2

그런데 `head` 이득만 올리면 안 될 수 있다. 직진 중 두 항은 **균형**을 이루고,
그렇다면 요잉 오차는 횡오차를 죽이려고 컨트롤러가 일부러 유지하는 각도다
(게 걸음). 그러면 요잉만 따로 못 줄이고 **비율**을 바꿔야 한다.

대수로 먼저 풀린다. `cross` 는 순수 횡오차가 아니다 --

    cross = along*sin(head) - q*cos(head)        q = 차선에서의 부호있는 이탈

이걸 w = 0 에 넣고 head 를 작다고 보면

    head  =  K_CROSS * q / (K_HEAD + K_CROSS * along)          ... (평형)

즉 **요잉은 횡이탈에 비례**하고, 비례상수는 목표까지 남은 거리에 따라 변한다
(순수추종과 같은 꼴). along -> 0 에서 K_CROSS/K_HEAD = 0.818 로 가장 커진다.

이 도구는 그 식이 **실제로 맞는지** 를 녹화로 확인한다.

    맞으면    요잉은 결과지 원인이 아니다. 손잡이는 **비율**과 q 다
    안 맞으면 과도구간이거나 w 포화다. 다른 손잡이를 찾아야 한다

꼬리는 `tail_yaw.py` 와 같은 정의를 쓴다 -- `|q| + rear_len*|sin(head)|`.

쓰는 법
-------
    source paths.sh
    PITCH=1.0 python tools/gain_balance.py $OUT/rec_s2_soft.npz

    PITCH     칸 간격 (기본 1.0)
    VMIN      직진으로 볼 최소 속도 m/s (기본 0.30)
    YAW_TOL   축 정렬 허용 오차 도 (기본 10)
    K_CROSS / K_HEAD   현재 이득 (기본 1.8 / 2.2)
"""
import math
import os
import sys

import numpy as np

PITCH = float(os.environ.get("PITCH", os.environ.get("PIBT_PITCH", "1.0")))
VMIN = float(os.environ.get("VMIN", "0.30"))
YAW_TOL = math.radians(float(os.environ.get("YAW_TOL", "10")))
K_CROSS = float(os.environ.get("K_CROSS", "1.8"))
K_HEAD = float(os.environ.get("K_HEAD", "2.2"))
# ★ 1.8 이다 (`pibt_scene.py` GEOM_KW · amr_driver_v2.OMEGA_MAX). 2.07 로
#   두면 **포화 프레임을 놓친다** — 컨트롤러는 1.8 에서 자르는데 도구는 2.07
#   까지 안 잘라서, 실제로 포화된 구간이 「포화 0%」로 보인다.
W_MAX = float(os.environ.get("W_MAX", "1.8"))
REAR = float(os.environ.get("REAR_LEN", "1.110"))
WIDTH = 0.800
BUDGET = (PITCH - WIDTH) / 2.0 * 1000.0          # 로봇당 예산 mm


def wrap(a):
    return (a + np.pi) % (2.0 * np.pi) - np.pi


def measure(path):
    """직진 프레임마다 q · head · along · cross 를 **부호까지** 뽑는다."""
    z = np.load(path, allow_pickle=True)
    t = np.asarray(z["t"], dtype=np.float64)
    pose = np.asarray(z["pose"], dtype=np.float64)
    if pose.ndim != 3 or pose.shape[2] < 3:
        raise SystemExit(f"★ pose 모양이 예상과 다릅니다: {pose.shape}")
    o = PITCH / 2.0                               # make_geom 과 같은 규약

    dt = np.diff(t)
    dt[dt <= 0] = np.nan

    keys = ("q", "head", "along", "cross", "w", "spd", "agent")
    out = {k: [] for k in keys}
    for a in range(pose.shape[1]):
        x, y, yaw = pose[:-1, a, 0], pose[:-1, a, 1], pose[:-1, a, 2]
        vx = np.diff(pose[:, a, 0]) / dt
        vy = np.diff(pose[:, a, 1]) / dt
        spd = np.hypot(vx, vy)

        # -- 목표 yaw 는 축 정렬이다. 직진 중이면 가장 가까운 90도 배수 --
        tyaw = np.round(yaw / (np.pi / 2.0)) * (np.pi / 2.0)
        head = wrap(tyaw - yaw)

        ok = (spd > VMIN) & np.isfinite(spd) & (np.abs(head) < YAW_TOL)
        if not ok.any():
            continue

        # -- 물리적 전진/후진. 액션 이름이 아니라 기하로 정한다 --
        sign = np.where(vx * np.cos(yaw) + vy * np.sin(yaw) >= 0.0, 1.0, -1.0)
        ux, uy = np.cos(tyaw) * sign, np.sin(tyaw) * sign      # 진행 축
        fx, fy = np.cos(yaw) * sign, np.sin(yaw) * sign        # 실제 진행 방향
        nx, ny = -uy, ux                                       # 좌측 법선

        horiz = np.abs(ux) >= np.abs(uy)
        perp = np.where(horiz, y, x)            # 차선을 가로지르는 좌표
        axis = np.where(horiz, x, y)            # 진행 축 좌표
        adir = np.where(horiz, ux, uy)          # +1 / -1
        lane = o + np.round((perp - o) / PITCH) * PITCH
        k = (axis - o) / PITCH
        nk = np.where(adir > 0, np.floor(k) + 1.0, np.ceil(k) - 1.0)
        taxis = o + nk * PITCH                  # 다음 칸 중심 (= 목표)

        tx = np.where(horiz, taxis, lane)
        ty = np.where(horiz, lane, taxis)
        dx, dy = tx - x, ty - y
        cross = fx * dy - fy * dx
        q = (x - tx) * nx + (y - ty) * ny       # 차선 기준 부호있는 이탈
        along = dx * ux + dy * uy
        w = np.clip(K_CROSS * cross + K_HEAD * head, -W_MAX, W_MAX)

        for key, arr in (("q", q), ("head", head), ("along", along),
                         ("cross", cross), ("w", w), ("spd", spd)):
            out[key].append(arr[ok])
        out["agent"].append(np.full(int(ok.sum()), a))

    if not out["q"]:
        raise SystemExit("★ 직진 프레임이 없습니다 -- VMIN/YAW_TOL 을 보세요.")
    return {k: np.concatenate(v) for k, v in out.items()}


def report(path, d):
    q, head, along = d["q"], d["head"], d["along"]
    cross, w = d["cross"], d["w"]
    name = os.path.basename(path)
    print(f"\n== {name} ==")
    print(f"   직진 프레임 {len(q):,} · pitch {PITCH} · "
          f"이득 K_CROSS {K_CROSS} · K_HEAD {K_HEAD}")

    # -- 1. cross 가 순수 횡오차가 아님을 보인다 --------------------------
    ident = along * np.sin(head) - q * np.cos(head)
    print("\n   [1] cross = along*sin(head) - q*cos(head) 검산")
    print(f"       최대 잔차 {np.abs(cross - ident).max() * 1000:.4f} mm"
          f"   (0 이어야 정의가 맞다)")

    # -- 2. 평형식이 맞는가 -----------------------------------------------
    pred = K_CROSS * q / (K_HEAD + K_CROSS * along)
    print("\n   [2] 평형식  head = K_CROSS*q / (K_HEAD + K_CROSS*along)")
    print(f"       {'along 구간':<14}{'프레임':>8}{'실측|head|':>12}"
          f"{'평형 예측':>11}{'실측/예측':>11}{'|w| 중앙':>10}")
    edges = [0.0, 0.2, 0.4, 0.6, 0.8, 1.01]
    for lo, hi in zip(edges, edges[1:]):
        m = (along >= lo) & (along < hi)
        if m.sum() < 50:
            continue
        big = m & (np.abs(q) > 0.005)    # q 가 0 근처면 비율이 0/0 이다
        r = (float(np.median(head[big] / pred[big]))
             if big.sum() > 20 else float("nan"))
        print(f"       {lo:.1f}-{hi:.1f} m{'':<6}{m.sum():>8,}"
              f"{np.degrees(np.median(np.abs(head[m]))):>11.3f}o"
              f"{np.degrees(np.median(np.abs(pred[m]))):>10.3f}o"
              f"{r:>11.2f}{np.median(np.abs(w[m])):>10.3f}")
    print(f"       w 포화(|w| >= {W_MAX}) 프레임 "
          f"{(np.abs(w) >= W_MAX - 1e-6).mean() * 100:.2f}%")
    big = np.abs(q) > 0.005
    ratio = float(np.median(head[big] / pred[big])) if big.sum() > 20 else float("nan")
    holds = abs(ratio - 1.0) <= 0.25
    print(f"       ★ 전체 실측/예측 {ratio:.2f}  ->  "
          + ("평형식이 선다" if holds else "평형식이 **안 선다**"))

    # -- 3. 꼬리를 q 몫과 요잉 몫으로 쪼갠다 ------------------------------
    tail = np.abs(q) * 1000.0 + REAR * np.abs(np.sin(head)) * 1000.0
    share = REAR * np.abs(np.sin(head)) * 1000.0
    print(f"\n   [3] 꼬리 이탈 = |q| + rear*|sin head|   (예산 {BUDGET:.0f} mm)")
    for lab, v in (("꼬리 전체", tail),
                   ("  축 몫 |q|", np.abs(q) * 1000.0),
                   ("  요잉 몫", share)):
        print(f"       {lab:<12} 중앙 {np.median(v):6.1f}  "
              f"p95 {np.percentile(v, 95):6.1f}  "
              f"p99 {np.percentile(v, 99):6.1f}  최대 {v.max():6.1f} mm")
    over = tail > BUDGET
    if over.any():
        print(f"       예산 초과 {over.mean() * 100:.2f}% · "
              f"그 프레임의 요잉 몫 비중 중앙 "
              f"{np.median(share[over] / tail[over]) * 100:.0f}%")
    else:
        print("       예산 초과 없음")

    # -- 4. 이득을 바꾸면 꼬리가 어떻게 되나 (q 불변 가정) ----------------
    print("\n   [4] 이득 후보별 꼬리 예측  ★ q 분포가 안 변한다는 가정")
    if not holds:
        print("       ☠ [2] 에서 평형식이 안 섰다. 아래 표는 **못 쓴다** --")
        print("         평형 head 를 깔고 계산하는데 그 전제가 깨졌다.")
    print(f"       {'K_CROSS':>8}{'K_HEAD':>8}{'비율':>7}"
          f"{'꼬리 p95':>10}{'최대':>9}{'예산초과':>10}")
    for kc, kh in ((K_CROSS, K_HEAD), (K_CROSS, 3.0), (K_CROSS, 4.0),
                   (2.7, 3.3), (3.6, 4.4)):
        h2 = kc * q / (kh + kc * along)
        t2 = np.abs(q) * 1000.0 + REAR * np.abs(np.sin(h2)) * 1000.0
        mark = "  <- 현재" if (kc, kh) == (K_CROSS, K_HEAD) else ""
        print(f"       {kc:>8.1f}{kh:>8.1f}{kc / kh:>7.2f}"
              f"{np.percentile(t2, 95):>10.1f}{t2.max():>9.1f}"
              f"{(t2 > BUDGET).mean() * 100:>9.2f}%{mark}")

    print("\n   읽는 법")
    print("    · [2] 의 **실측/예측이 1 에 가까우면** 요잉은 평형값이다.")
    print("      그러면 요잉만 따로 못 줄인다 -- 비율이나 q 를 건드려야 한다.")
    print("    · 1 에서 크게 벗어나면 과도구간이거나 w 포화다. 포화율을 본다.")
    print("    · [4] 는 **q 가 안 변한다는 가정**이라 참고값이다. 이득을 올리면")
    print("      q 수렴이 빨라져 실제로는 더 좋아지거나, 진동하면 더 나빠진다.")
    print("      그래서 스윕이 필요하고, 이 표는 그 **예상치**다.")
    print("    · 마지막 두 줄은 **비율을 유지한 채 둘 다 올린** 경우다. 요잉은")
    print("      그대로지만 q 수렴이 빨라진다 -- 표에는 그 이득이 안 잡힌다.")
    return 0


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args:
        raise SystemExit(__doc__)
    for p in args:
        report(p, measure(p))
    return 0


if __name__ == "__main__":
    sys.exit(main())
