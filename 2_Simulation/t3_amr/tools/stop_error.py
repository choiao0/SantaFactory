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
    --hist        hypot 분포 · 부호 편향 · 접근 속도까지 (아래 [h1][h2][h3])
    --tol 0.05    Tolerance.pos [m]. [h1] 의 끊김선과 [h3] 의 _lim 에 쓴다
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
# ★ 감속 꼬리를 재는 문턱. 이 속도 아래로 떨어진 순간부터 정지까지를 잰다.
#   `tol.pos` 를 줄이면 이 구간이 길어진다 — 그 대가가 여기 찍힌다.
V_APPROACH = float(os.environ.get("V_APPROACH", "0.30"))  # m/s


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
    """멈춰 있던 구간 목록.

    낸다: (시작 세로, 끝 세로, 시작 가로, 지속, i, j, **hypot**, **접근 속도**)

    ★ `hypot` 과 접근 속도를 같이 내는 이유 (2026-09-16):
      도착 판정이 `hypot(dx, dy) <= tol.pos` 라 **세로 단독**으로는 `tol.pos`
      보다 작은 데서 끊긴다 — 가로 성분이 있으면 그만큼 더. 그런데 실측
      세로 p99 가 52.0 (s1) 로 50 을 넘는 판이 있다. 도착 판정 말고 다른
      것도 섞여 있다는 뜻이므로 `hypot` 자체를 봐야 한다.

      접근 속도는 `isaac_drive.py:1614` 의 `_lim = 2*tol.pos*60Hz` 와 대본다.
      `v_exec` 는 **순항** 속도고 도착 직전에는 감속하므로, 1.6 이 곧바로
      한계에 걸린다고 볼 수 없다. 실제로 몇 번 걸리는지는 세면 된다.
    """
    dt = np.diff(t)
    dt[dt <= 0] = np.nan
    v = np.nan_to_num(np.hypot(np.diff(x), np.diff(y)) / dt)
    w = np.nan_to_num(np.abs(np.diff(np.unwrap(yaw))) / dt)
    still = (v < V_MOVE) & (w < W_MOVE)
    o = PITCH / 2.0

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
                ex = x[i] - (o + round((x[i] - o) / PITCH) * PITCH)
                ey = y[i] - (o + round((y[i] - o) / PITCH) * PITCH)
                # 접근 속도 — 멈추기 직전 프레임. 구간 첫 프레임은 이미 정지다.
                v_in = float(v[i - 1]) if i > 0 else float("nan")
                # ★ 감속 꼬리 — `tol.pos` 를 줄인 대가를 재는 지표 (2026-09-16).
                #   완주 시간으로 재면 안 된다: 접촉으로 중단된 판(279 s)과
                #   완주한 판(600 s)은 길이가 달라 직접 비교가 안 되고, 고친
                #   판은 완주할 테니 애초에 짝이 안 맞는다. **정지 하나당**
                #   순항에서 떨어져 멈출 때까지 걸린 시간을 재면 판 길이와
                #   무관하게 비교된다.
                k = i - 1
                while k >= 0 and v[k] < V_APPROACH:
                    k -= 1
                settle = float(t[i] - t[k + 1]) if k + 1 < i else 0.0
                out.append((lon0 * 1000, lon1 * 1000, lat0 * 1000,
                            float(t[j] - t[i]), i, j,
                            math.hypot(ex, ey) * 1000, v_in, settle))
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


def hist(v, edges, names, total=None):
    """간단 막대 히스토그램."""
    v = np.asarray(v, dtype=float)
    n = total or len(v)
    for lo, hi, nm in zip(edges, edges[1:], names):
        k = int(((v >= lo) & (v < hi)).sum())
        bar = "#" * int(round(40.0 * k / max(1, n)))
        print(f"     {nm:>12}  {k:>5}회 ({100.0 * k / max(1, n):5.1f}%)  {bar}")


def _bias_verdict(lon0, tol_mm):
    """부호 분포가 **편향인가 게이트 서명인가**.

    ★ 부호 쏠림만 보면 「편향」으로 오독한다 (2026-09-16 실측에서 그랬다).
      갈라야 할 것은 **분포 모양**이다:

        양 끝 두 봉우리 + 중간이 빈다  -> `hypot <= tol` **게이트의 서명**.
           원에 들어가는 순간 멈추니 늘 가장자리에 서고, 부호는 접근 방향이
           정한다. 편향이 아니라 경계 효과이고, tol 을 줄이면 같이 안으로 온다.
        한 봉우리가 0 에서 벗어나 있다  -> 진짜 계통 편향. 따로 고쳐야 한다.

    ★ 이 판정을 못 해도 **[h3]·[h4] 는 봐야 한다.** 그래서 `sec_hist` 에서
      `return` 하지 않고 함수로 뺐다 (초판이 return 이라 뒤가 통째로 잘렸다).
    """
    if lon0.std() < 1.0:
        print(f"     퍼짐이 {lon0.std():.2f} mm 뿐이다 — 이 표본으로는 편향을 못 본다.")
        return
    pos = 100.0 * (lon0 > 0).mean()
    edge = float((np.abs(lon0) > 0.8 * tol_mm).mean()) * 100.0
    mid = float((np.abs(lon0) < 0.6 * tol_mm).mean()) * 100.0
    print(f"     양수 비율 {pos:.1f}%  ·  중앙 {np.median(lon0):+.1f} mm")
    print(f"     가장자리(|·|>{0.8 * tol_mm:.0f}) {edge:.1f}%  ·"
          f"  중간(|·|<{0.6 * tol_mm:.0f}) {mid:.1f}%")
    if edge > 70.0 and mid < 25.0:
        print("     -> **양 끝 두 봉우리 · 중간이 비었다.** 계통 편향이 아니라")
        print("        `hypot <= tol` **게이트의 서명**이다 — 원에 들어가는 순간")
        print("        멈추니 늘 가장자리에 서고 부호는 접근 방향이 정한다.")
        print("        따로 고칠 편향이 없다. **tol 을 줄이면 같이 안으로 온다.**")
    elif pos < 35 or pos > 65:
        print("     -> 한쪽으로 쏠렸는데 가장자리 집중은 아니다. 게이트로 설명이")
        print("        안 되는 몫이 있다 — **계통 편향**을 따로 봐야 한다.")
    else:
        print("     -> 부호가 갈린다. 크기(허용오차)가 지배한다.")


def sec_hist(rows, tol_pos):
    """[h1] hypot 이 허용오차에서 깨끗이 끊기나 · [h2] 부호 편향 · [h3] 접근 속도."""
    hyp = np.array([r[6] for r in rows])
    lon0 = np.array([r[0] for r in rows])
    vin = np.array([r[7] for r in rows])
    vin = vin[np.isfinite(vin)]
    tol_mm = tol_pos * 1000.0

    # --- [h1] 도착 판정이 정말 끊는가 ---------------------------------
    print()
    print(f"   [h1] `hypot(dx,dy)` 분포 — 도착 판정 `<= {tol_mm:.0f} mm` 가 끊나")
    e = [0, 10, 20, 30, 40, tol_mm, tol_mm + 10, 1e9]
    nm = ["0-10", "10-20", "20-30", "30-40", f"40-{tol_mm:.0f}",
          f"{tol_mm:.0f}-{tol_mm + 10:.0f}", f"{tol_mm + 10:.0f}+"]
    hist(hyp, e, nm)
    over = int((hyp > tol_mm).sum())
    print(f"     {tol_mm:.0f} mm 초과 {over}회 ({100.0 * over / len(hyp):.1f}%)"
          f"  ·  최대 {hyp.max():.1f} mm")
    if over > 0.05 * len(hyp):
        print("     -> ★ 초과가 적지 않다. 도착 판정 말고 다른 것도 섞여 있다")
        print("        (감속 오버슈트 · 다음 동작 전 밀림 등).")
    else:
        print("     -> 허용오차에서 깨끗이 끊긴다. 도착 판정이 지배한다.")

    # --- [h2] 부호 편향 -------------------------------------------------
    #   허용오차 **크기**만으로는 부호가 갈려야 한다. 한쪽으로 쏠려 있으면
    #   크기와 **별개인 계통 편향**이 있다는 뜻이고, 그쪽을 고치면
    #   `tol.pos` 를 덜 줄여도 되므로 속도 상한을 안 건드린다.
    print()
    print("   [h2] 부호 있는 세로 — 편향인가 (허용오차 크기와 별개 정보)")
    e = [-1e9, -tol_mm, -40, -20, 0, 20, 40, tol_mm, 1e9]
    nm = [f"<-{tol_mm:.0f}", f"-{tol_mm:.0f}~-40", "-40~-20", "-20~0",
          "0~20", "20~40", f"40~{tol_mm:.0f}", f">{tol_mm:.0f}"]
    hist(lon0, e, nm)
    _bias_verdict(lon0, tol_mm)

    # --- [h3] 접근 속도 vs 도착 판정 한계 --------------------------------
    print()
    print("   [h3] 멈추기 직전 속도 — `tol.pos` 를 줄일 여지가 있나")
    if not vin.size:
        print("     표본 없음")
        return
    print(f"     중앙 {np.median(vin):.3f}  p90 {np.percentile(vin, 90):.3f}"
          f"  p99 {np.percentile(vin, 99):.3f}  최대 {vin.max():.3f} m/s")
    print(f"     {'tol.pos':>9}{'_lim':>9}{'경고선':>9}{'경고선 초과':>12}")
    for tp in (0.050, 0.030, 0.020, 0.015, 0.010):
        lim = 2.0 * tp * 60.0
        warn = 0.5 * lim
        k = int((vin > warn).sum())
        print(f"     {tp * 1000:>7.0f}mm{lim:>9.2f}{warn:>9.2f}"
              f"{k:>7}회 ({100.0 * k / len(vin):4.1f}%)")
    tight = [tp for tp in (0.050, 0.030, 0.020, 0.015, 0.010)
             if not (vin > 0.5 * 2.0 * tp * 60.0).any()]
    if tight:
        print(f"     -> ★ {min(tight) * 1000:.0f} mm 까지 내려도 경고선에 한 번도"
              " 안 닿는다.")
        print("        도착 직전에는 감속하므로 **순항 속도(v_exec)와 무관**하다.")
        print("        `tol.pos` 를 줄이는 데 속도가 제약이 아니다.")
    print("     (`_lim = 2 x tol.pos x 60Hz` · 경고선은 그 절반 —")
    print("      isaac_drive.py:1614. **순항 속도가 아니라 이 속도**가 기준이다)")

    # --- [h4] 감속 꼬리 = tol.pos 를 줄인 **대가** -----------------------
    #   완주 시간으로 재면 안 된다. 접촉으로 중단된 판(279 s)과 완주한 판
    #   (600 s)은 길이가 달라 짝이 안 맞고, 고친 판은 완주할 테니 더 그렇다.
    #   정지 하나당 「순항에서 떨어져 멈출 때까지」를 재면 길이와 무관하다.
    st = np.array([r[8] for r in rows], dtype=float)
    print()
    print(f"   [h4] 감속 꼬리 — {V_APPROACH} m/s 아래로 떨어진 뒤 멈출 때까지")
    print(f"     중앙 {np.median(st):.3f}  p90 {np.percentile(st, 90):.3f}"
          f"  p99 {np.percentile(st, 99):.3f}  최대 {st.max():.3f} s")
    print(f"     정지 {len(st)}회 x 중앙 = {np.median(st) * len(st):.1f} 로봇·초")
    print("     (`tol.pos` 를 줄이면 이 값이 는다. **판 길이와 무관한 지표**라")
    print("      고친 판과 그대로 비교된다 — 완주 시간은 길이가 달라 못 쓴다)")


def trace(t, x, y, yaw, k, rows):
    """한 로봇의 정지 구간을 시간순으로 — [1] 을 눈으로 본다."""
    print(f"\n   [추적] agent{k} 의 정지 구간")
    print(f"     {'t0':>8}{'t1':>8}{'지속':>7}{'도착세로':>10}{'출발세로':>10}"
          f"{'밀림':>8}{'도착가로':>10}   mm")
    for lon0, lon1, lat0, dur, i, j, _hyp, _v, _s in rows:
        print(f"     {t[i]:>8.2f}{t[j]:>8.2f}{dur:>7.2f}"
              f"{lon0:>+10.1f}{lon1:>+10.1f}{lon1 - lon0:>+8.1f}{lat0:>+10.1f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("npz", nargs="+")
    ap.add_argument("--agent", type=int, default=None, help="이 로봇의 추적도 찍는다")
    ap.add_argument("--mark", type=float, default=47.0, help="퍼센타일을 볼 값 mm")
    ap.add_argument("--hist", action="store_true",
                    help="hypot 분포 · 부호 편향 · 접근 속도까지")
    ap.add_argument("--tol", type=float, default=0.05, help="Tolerance.pos [m]")
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
        if a.hist:
            sec_hist(allrows, a.tol)

    print()
    print("* 세로 + 는 진행 방향으로 지나침. 계통이면 중앙이 0 에서 멀다.")
    print("* 접촉 여유는 41.3 mm 다 (인접 행 · 한쪽 회전). 그 선과 대볼 것.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
