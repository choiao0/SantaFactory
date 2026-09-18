# -*- coding: utf-8 -*-
"""후진이 **실제로 몇 배 느린가** — `REVERSE_FACTOR 3.0` 을 녹화로 검산한다 (S15P21A106-240).

왜 이 수가 결론을 가르나
------------------------
회전 스윕 마스크를 켜면 계획이 이렇게 바뀐다 (시드 103, 같은 주문).

    move     92,418 -> 85,270   (-7,148)
    reverse   9,353 -> 16,513   (+7,160)
    칸 이동 총수 101,771 -> 101,783        <- **경로는 안 길어졌다**

칸 수가 같으니 대가는 **전부 후진 배율에서 나온다.**

    3.0 배면   주행비용 +11.9 %   ->  pitch 1.0(2칸)이 1.2 에 진다
    1.2 배면   주행비용  +2 % 대   ->  1.0 유지

그런데 `REVERSE_FACTOR = 3.0` 은 **측정값이 아니라 우리가 건 정책**이다.

    # isaac_drive.update()  비-TURN 가지
    v_cap = self.v_exec * (1.0 if sign > 0 else 1.0 / REVERSE_FACTOR)
    #   감속 계수는 **물리적** 후진에 붙인다 (센서가 없는 방향이므로)

순항 상한을 0.9 -> 0.3 m/s 로 깎아 둔 것이다. 그러나 **1칸은 순항에 도달하지도
못한다** — 가감속이 지배한다. 그래서 「상한이 3배」와 「1칸이 3배 걸린다」는
다른 말이고, 계획 비용에 들어가야 하는 것은 뒤쪽이다.

무엇을 재나
-----------
    ① 실효 속도    움직이는 프레임만 모아  이동거리 / 시간.  방향별로 따로
                   가감속이 통째로 들어가므로 **칸당 시간의 역수**와 같은 뜻이다
    ② 순항 p95     상한 0.9 / 0.3 이 실제로 걸리는지 확인 (정책이 먹고 있나)
    ③ 칸당 시간    칸 전환 사이의 실제 경과. 대기가 섞인 구간은 빼고 센다

    source paths.sh
    PITCH=1.0 python tools/reverse_cost.py $OUT/rec_carry.npz
    PITCH=1.0 python tools/reverse_cost.py $OUT/*.npz          # 여러 개 합산

☹ 한계 — 녹화가 **그 조건에서 뜬 것**이어야 한다. `v_exec`·`a_exec`·pitch 가
  다르면 비율도 달라진다. 머리에 그 값들을 같이 찍으니 확인하고 읽을 것.
"""
import os
import sys

import numpy as np

V_STOP = 0.05         # m/s 이하면 정지로 본다 (motion_profile 과 같은 값)
W_TURN = 0.10         # rad/s 이상이면 회전 중 — 병진 통계에서 뺀다
PITCH = float(os.environ.get("PITCH") or os.environ.get("PIBT_PITCH") or 1.0)


def wrap(a):
    return (a + np.pi) % (2.0 * np.pi) - np.pi


def load(path):
    if not os.path.exists(path):
        raise SystemExit(f"[reverse_cost] 없는 파일: {path!r}  "
                         "($OUT 이 비었으면 `source paths.sh` 부터)")
    z = np.load(path, allow_pickle=True)
    return z["t"].astype(np.float64), z["pose"].astype(np.float64)


def segments(t, p):
    """프레임별 (부호 있는 속도, 각속도, 이동거리, dt). 회전 프레임은 뺀다."""
    dt = np.diff(t)
    ok = dt > 0
    dx = np.diff(p[:, :, 0], axis=0)
    dy = np.diff(p[:, :, 1], axis=0)
    dyaw = wrap(np.diff(p[:, :, 2], axis=0))
    # 헤딩은 구간 **시작** 것을 쓴다 (끝을 쓰면 회전 중에 부호가 흔들린다)
    hx, hy = np.cos(p[:-1, :, 2]), np.sin(p[:-1, :, 2])
    d = np.hypot(dx, dy)
    sgn = np.sign(dx * hx + dy * hy)          # +1 전진 · -1 후진
    v = np.where(ok[:, None], d / dt[:, None], np.nan) * sgn
    w = np.where(ok[:, None], np.abs(dyaw) / dt[:, None], np.nan)
    return v, w, d, np.repeat(dt[:, None], p.shape[1], axis=1)


def main():
    paths = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not paths:
        raise SystemExit("쓰기: PITCH=1.0 python tools/reverse_cost.py <rec.npz> [...]")

    tot = {"전진": [0.0, 0.0], "후진": [0.0, 0.0]}      # [거리, 시간]
    sp = {"전진": [], "후진": []}
    print(f"  pitch {PITCH} · 정지선 {V_STOP} m/s · 회전선 {W_TURN} rad/s")
    for path in paths:
        t, p = load(path)
        v, w, d, dt = segments(t, p)
        spin = (w > W_TURN)                    # 회전 중 프레임은 병진에서 뺀다
        move = np.isfinite(v) & (np.abs(v) > V_STOP) & ~spin
        for name, m in (("전진", move & (v > 0)), ("후진", move & (v < 0))):
            tot[name][0] += float(d[m].sum())
            tot[name][1] += float(dt[m].sum())
            sp[name].append(np.abs(v[m]))
        print(f"  {os.path.basename(path):28} 프레임 {len(t):,} · 로봇 {p.shape[1]}대"
              f" · {t[-1] - t[0]:.0f}s")

    print("\n  ① 실효 속도 (움직이는 프레임만 · 가감속 포함)")
    print("     {:>6} {:>12} {:>10} {:>12} {:>10}".format(
        "", "이동거리", "시간", "실효속도", "칸당"))
    eff = {}
    for name in ("전진", "후진"):
        dist, sec = tot[name]
        if sec <= 0:
            print(f"     {name:>6}   표본 없음")
            continue
        eff[name] = dist / sec
        print(f"     {name:>6} {dist:10.1f} m {sec:9.1f} s "
              f"{eff[name]:10.3f} m/s {PITCH / eff[name]:9.3f} s")

    print("\n  ② 속도 분포 — 정책 상한이 실제로 걸리나")
    for name in ("전진", "후진"):
        a = np.concatenate(sp[name]) if sp[name] and len(sp[name][0]) else None
        if a is None or a.size == 0:
            continue
        q = np.percentile(a, [50, 90, 95, 99])
        print(f"     {name:>6}  중앙 {q[0]:.3f} · p90 {q[1]:.3f} · "
              f"p95 {q[2]:.3f} · p99 {q[3]:.3f} m/s   (n={a.size:,})")

    print("\n  ── 판정 ──")
    if len(eff) < 2:
        print("  ☹ 한쪽 표본이 없다 — 후진이 없는 녹화다. 다른 판이 필요하다")
        return
    r = eff["전진"] / eff["후진"]
    print(f"  실효 배율 = 전진 / 후진 = **{r:.2f} 배**   "
          f"(코드의 REVERSE_FACTOR = 3.0)")
    print()
    if r >= 2.5:
        print("  -> 3배가 대체로 맞다. 회전 금지의 주행비용 +11.9 % 가 **진짜**이고,")
        print("     그러면 pitch 1.0(2칸)이 1.2 에 진다. 2칸 재검토가 필요하다.")
    elif r <= 1.5:
        print("  -> 3배는 **과하다.** 1칸은 순항에 못 가서 가감속이 지배한다.")
        print("     계획 비용 모델이 후진을 과대평가하고 있고, +11.9 % 도 과대다.")
        print("     `REVERSE_FACTOR` 를 **계획 비용**과 **속도 상한**으로 갈라야 한다 —")
        print("     지금은 한 상수가 둘을 겸한다.")
    else:
        print("  -> 중간이다. 3.0 을 이 값으로 바꾸고 +11.9 % 를 다시 계산해야 한다.")
    print()
    print("  ☹ 이 수는 녹화가 뜬 조건(v_exec·a_exec·pitch)에 매인다.")
    print("     `이어달리기`가 켜진 판이면 전진이 안 서고 이어져 **전진이 더 빨라 보인다** —")
    print("     그건 실제 이득이지만, 후진에는 안 실리는 이득이라 배율을 키운다.")


if __name__ == "__main__":
    main()
