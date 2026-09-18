# -*- coding: utf-8 -*-
"""**회전이 왜 가끔 2배 걸리나** — 「회전각 × 중간에 멈췄나 × 가로 오차」.

왜 이 도구가 필요한가
---------------------
틱 정합 뒤 `rec_v16` 에서 회전 지속의 **중앙값은 그대로인데 p90 만**
1.60 → 2.76 s 로 길어졌다 (LOCAL_속도측정_결과 §10-4). 계획은 회전 1회에
`TURN_TICKS(5) × tick_s` = 1.389 s 를 준다. 2.76 s 는 그 **2배**다.
시간표를 실제로 밀어내는 것은 이 꼬리다.

§10-4 는 원인을 「중간에 멈췄다 다시 도는 회전이 있을 것」이라고 적고
**확인 안 했다**고 명시했다. 그런데 후보가 하나 더 있고, 이쪽이 더 단순하다:

    180° 회전은 `candidates_h` 가 ±90°만 만들기 때문에 **90° 두 번**이다.
    두 번이 끊김 없이 이어지면 각속도가 안 떨어져 검출기는 그것을
    **회전 1회**로 센다. 지속은 당연히 2배 (2 × 1.37 = 2.74 s) 가 된다.

    그리고 틱 정합은 `turn_cost` 를 5.0 → 1.25 로 낮춰 회전을 싸게 만들었다.
    회전 횟수가 104 → 171 (+64 %) 로 늘었다. 180°가 늘었다면 꼬리도
    같이 늘어난다. **두 가설이 같은 관측을 설명한다.**

가르는 방법은 싱겁다 — **꼬리에 있는 구간들이 몇 도를 돌았는지 보면 된다.**
180°면 계획도 10틱을 주므로 시간표는 안 어긋난다. 90°인데 2.76 s 면
컨트롤러가 예산을 2배 쓰는 것이고, 그건 진짜 문제다.

    180° 때문  → 계획 문제. 시간표는 맞다. 후진 1칸(4틱)으로 바꾸면 10틱 절약.
    멈춤 때문  → 컨트롤러 문제. 회전 진입 자세를 고쳐야 한다.

분할이 둘인 이유
----------------
`turn_error.spin_segments`(=여기의 **기준 분할**) 는 각속도가 `W_MIN` 아래로
떨어지면 구간을 **끊는다.** 그래서 중간에 멈춘 90° 회전은 두 조각(예:
40° + 50°)으로 갈리고, `MIN_DEG=45` 에 걸려 **한 조각 또는 둘 다 버려진다.**
즉 §10-4 가 찾으려던 바로 그 회전이 표본에서 빠져 있었을 수 있다.

그래서 두 벌을 낸다:

    기준 분할   갭에서 끊는다. `turn_error` 와 같은 표본.
    병합 분할   짧고 제자리인 갭을 잇는다. 멈춤을 세려면 이쪽이 필요하다.

★ 2026-09-15 실측으로 알게 된 것 — **§10-4 의 p90 은 병합 쪽과 맞대야 한다.**
  180° 는 한가운데서 각속도가 1~2프레임 `W_MIN` 아래로 떨어지는데, 기준
  분할은 거기서 끊고 양쪽이 다 45° 를 넘으니 **90° 두 개로 센다.** 그래서
  기준 분할의 180°급은 어느 녹화에서나 0 이고 p90 도 늘 1.40 s 다.
  §10-4 의 1.60 → 2.76 은 `measure_turns.py`(n=102 → 152) 에서 나온 값인데
  그 도구는 갭을 잇고 있었다. 병합 분할이 1.57 → 2.45 로 같은 모양을 낸다.
  두 표를 다 찍는 것은 이 차이 자체를 보이기 위해서다.

병합 조건이 두 개인 이유: 갭이 짧아도 그 동안 로봇이 **이동**했으면 그건
멈춤이 아니라 「돌고 → 가고 → 또 돌고」다. 그래서 갭 중 축 이동이
`MAX_MOVE` 를 넘으면 병합하지 않는다.

`MAX_GAP` 을 얼마로 둘지는 애매하다 — 제어 리플로 잠깐 `W_MIN` 아래로
떨어진 것과, 계획이 두 회전 사이에 넣은 **1틱 대기**(pitch 1.0 에서 0.278 s)가
길이로는 비슷하다. 그래서 이 도구는 갭 길이를 **틱 단위로 히스토그램**으로
낸다. 0 근처에 몰려 있으면 리플이고, 틱의 정수배에 서면 계획 대기다.
값을 고르기 전에 그 표를 먼저 볼 것.

쓰는 법
-------
    source paths.sh
    PITCH=1.0 python tools/turn_stall.py $OUT/rec_v16.npz $OUT/rec_v22.npz

    PITCH 는 **녹화가 돌던 격자**다 (모르면 tools/cross_track.py --diag).
    TICK_S 를 주면 계획 예산선을 그 값으로 그린다. 기본은 pitch/(0.9×4).
"""
import os
import sys

import numpy as np

PITCH = float(os.environ.get("PITCH", os.environ.get("PIBT_PITCH", "1.2")))
V_PLAN = float(os.environ.get("PIBT_V_PLAN", "0.90"))
MOVE_TICKS = int(os.environ.get("MOVE_TICKS", "4"))
TURN_TICKS = int(os.environ.get("TURN_TICKS", "5"))
# 계획이 회전 1회에 주는 시간. 이 선을 넘는 회전이 시간표를 밀어낸다.
# ★ `os.environ.get("TICK_S", "0") or ...` 로 쓰면 안 된다 — "0" 은 참인 문자열이라
#   기본값이 영영 안 걸리고 예산이 통째로 0 이 된다 (합성 검증에서 걸렀다).
_TICK_S_ENV = os.environ.get("TICK_S", "").strip()
TICK_S = float(_TICK_S_ENV) if _TICK_S_ENV else PITCH / (V_PLAN * MOVE_TICKS)
TURN_BUDGET = TURN_TICKS * TICK_S

W_MIN = float(os.environ.get("W_MIN", "0.15"))        # rad/s — 회전 판정 (turn_error 와 동일)
MIN_DEG = float(os.environ.get("MIN_DEG", "45"))      # 이보다 작게 돌면 회전 아님
# ★ 0.80 s 는 너무 후하다 — 회전 사이의 **정상 대기**까지 삼켜서 90°×3 이
#   270° 한 번으로 뭉친다 (합성 검증). 제어 리플만 잇도록 짧게 잡는다.
MAX_GAP = float(os.environ.get("MAX_GAP", "0.35"))    # s — 이보다 짧은 정지는 회전 안의 멈춤
MAX_MOVE = float(os.environ.get("MAX_MOVE", "0.30"))  # m — 갭 중 이만큼 넘게 움직였으면 별개 동작

GRADE_TURNS = {"90도급": 1, "180도급": 2, "270도+": 3}   # 계획상 회전 횟수 = 예산 배수


def off_center(x, y, pitch):
    """축이 가장 가까운 칸 중심에서 벗어난 거리 (m). origin = pitch/2 규약."""
    o = pitch / 2.0
    dx = x - (o + np.round((x - o) / pitch) * pitch)
    dy = y - (o + np.round((y - o) / pitch) * pitch)
    return np.hypot(dx, dy)


def lateral(x, y, yaw, pitch):
    """칸 중심 오차의 **가로 성분** (m, 부호 있음 · + 는 진행 기준 왼쪽).

    옆 칸 여유를 실제로 먹는 것은 가로뿐이다 (turn_error.decompose 와 같은 분해).
    """
    o = pitch / 2.0
    ex = x - (o + np.round((x - o) / pitch) * pitch)
    ey = y - (o + np.round((y - o) / pitch) * pitch)
    return -ex * np.sin(yaw) + ey * np.cos(yaw)


def grade(deg):
    """회전각을 급으로. 180°급은 계획상 **회전 2회**(10틱)다."""
    if deg < 135.0:
        return "90도급"
    if deg < 225.0:
        return "180도급"
    return "270도+"


def runs(spin):
    """`spin` 이 True 인 연속 구간 [i, j) 목록."""
    out, i, n = [], 0, len(spin)
    while i < n:
        if not spin[i]:
            i += 1
            continue
        j = i
        while j < n and spin[j]:
            j += 1
        out.append((i, j))
        i = j
    return out


def merge(rs, t, x, y):
    """짧고 **제자리인** 갭으로 갈린 구간들을 하나로 합친다.

    낸다: (i, j, [갭 길이...]) — 갭 목록이 곧 「회전 중 멈춤」이다.
    병합을 끄려면 갭 목록이 늘 비는 셈이므로 `MAX_GAP=0` 을 주면 된다.
    """
    out = []
    for i, j in rs:
        if out:
            gi, gj = out[-1][1], i                 # 갭 프레임 [gi, gj)
            gap = float(t[gj] - t[gi])
            move = float(np.hypot(x[gj] - x[gi], y[gj] - y[gi]))
            if gap <= MAX_GAP and move <= MAX_MOVE:
                out[-1][1] = j
                out[-1][2].append(gap)
                continue
        out.append([i, j, []])
    return out


def _spin_mask(t, yaw):
    dt = np.diff(t)
    dt[dt <= 0] = np.nan
    return np.nan_to_num(np.abs(np.diff(yaw) / dt)) > W_MIN


def turns_of(t, x, y, yaw_raw, do_merge):
    """한 대의 회전 목록. 각 원소는 dict — 뒤의 표들이 전부 이걸 쓴다.

    `do_merge=False` 면 `turn_error.spin_segments` 와 같은 **기준 분할**이다.
    """
    yaw = np.unwrap(yaw_raw)
    rs = runs(_spin_mask(t, yaw))
    segs = merge(rs, t, x, y) if do_merge else [[i, j, []] for i, j in rs]
    err = off_center(x, y, PITCH) * 1000.0

    out = []
    for i, j, gaps in segs:
        deg = abs(float(np.degrees(yaw[j] - yaw[i])))
        if deg < MIN_DEG:
            continue
        out.append(dict(
            dur=float(t[j] - t[i]),
            deg=deg,
            grade=grade(deg),
            stalls=len(gaps),
            stall_s=float(sum(gaps)),
            gaps=list(gaps),
            lat0=abs(float(lateral(x[i], y[i], yaw[i], PITCH))) * 1000.0,
            peak=float(err[i:j + 1].max()),
        ))
    return out


def pct(v, q):
    v = np.asarray(v, dtype=float)
    return float(np.percentile(v, q)) if v.size else float("nan")


def dur_stats(rows):
    return np.array([r["dur"] for r in rows], dtype=float)


def _fmt(v, w=9, p=2):
    return f"{'-':>{w}}" if not np.isfinite(v) else f"{v:>{w}.{p}f}"


def sec_grades(rows, num, tag):
    """급별 지속 — 이 도구의 핵심 표.

    급마다 계획 예산이 다르다. 180°는 회전 2회라 예산도 2배(10틱)다.
    「계획초과」가 90°급에서 높으면 컨트롤러 문제, 180°급에서만 높으면
    그건 예산 안이라 시간표를 안 밀어낸다.
    """
    print()
    print(f"   [{num}] 회전각 급별 — {tag}")
    print(f"     {'':<9}{'n':>5}{'비율':>8}{'중앙':>8}{'p90':>8}{'최대':>8}"
          f"{'예산':>8}{'초과':>8}   s")
    for g in ("90도급", "180도급", "270도+"):
        sub = [r for r in rows if r["grade"] == g]
        if not sub:
            continue
        d = dur_stats(sub)
        budget = TURN_BUDGET * GRADE_TURNS[g]
        over = float((d > budget).mean()) * 100.0
        print(f"     {g:<9}{len(d):>5}{100.0 * len(d) / len(rows):>7.1f}%"
              f"{np.median(d):>8.2f}{pct(d, 90):>8.2f}{d.max():>8.2f}"
              f"{budget:>8.2f}{over:>7.0f}%")

    alld = dur_stats(rows)
    only90 = dur_stats([r for r in rows if r["grade"] == "90도급"])
    print()
    print(f"     ★ 전체 p90 {pct(alld, 90):.2f} s  ·  90°급만 p90"
          f" {pct(only90, 90):.2f} s  ·  90°급 예산 {TURN_BUDGET:.2f} s")
    if only90.size:
        # 「초과 60%」와 「예산 안」이 같이 찍혀 헷갈렸다. 중앙이 예산의 몇 배인지
        # 를 같이 낸다 — 초과 비율은 중앙이 예산에 붙어 있으면 쉽게 50% 를 넘는다.
        print(f"        90°급 중앙 {np.median(only90):.2f} s ="
              f" 예산의 {np.median(only90) / TURN_BUDGET:.2f}배")
    if not only90.size:
        print("        -> 90°급이 없다. 표본을 확인하라.")
    elif pct(alld, 90) - pct(only90, 90) > 0.2:
        print("        -> 꼬리는 상당 부분이 180°다. 회전이 느려진 게 아니라")
        print("           **두 번 도는 일이 잦아진 것**이고, 계획도 10틱을 준다.")
    elif pct(only90, 90) > TURN_BUDGET * 1.3:
        print("        -> 180°를 빼도 90°급 자체가 예산을 크게 넘는다.")
        print("           컨트롤러 문제다. [3][4] 로 멈춤 여부를 본다.")
    else:
        print("        -> 90°급은 예산 안이다. 꼬리는 급 구성이 만든 것이다.")


def sec_gaps(rows):
    """갭 길이 분포 — 제어 리플인가 계획 대기인가.

    0 근처에 몰려 있으면 리플이고, 틱의 정수배에 서면 계획이 넣은 대기다.
    `MAX_GAP` 을 정하기 전에 이 표를 먼저 본다.
    """
    gaps = np.array([g for r in rows for g in r["gaps"]], dtype=float)
    print()
    print(f"   [3] 병합된 갭 {len(gaps)}개의 길이 — 리플인가 계획 대기인가"
          f"   (1틱 = {TICK_S:.3f} s)")
    if not gaps.size:
        print("     갭이 없다 — 병합된 회전이 없다는 뜻이다 (MAX_GAP 확인)")
        return
    edges = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 1e9]
    for lo, hi in zip(edges, edges[1:]):
        k = int(((gaps >= lo * TICK_S) & (gaps < hi * TICK_S)).sum())
        if not k:
            continue
        nm = f"{lo:.2f}-{hi:.2f}틱" if hi < 1e8 else f"{lo:.2f}틱+"
        bar = "#" * int(round(40.0 * k / len(gaps)))
        print(f"     {nm:>12}  {k:>4}개 ({100.0 * k / len(gaps):4.1f}%)  {bar}")
    print(f"     갭 중앙 {np.median(gaps):.3f} s"
          f" = {np.median(gaps) / TICK_S:.2f}틱  ·  최대 {gaps.max():.3f} s")


def sec_stalls(rows):
    """멈춤 유무로 가른 표 — §10-4 의 가설을 직접 친다."""
    print()
    print("   [4] 회전 중 멈춤 (병합 분할) — §10-4 의 가설")
    print(f"     {'':<12}{'n':>5}{'중앙':>9}{'p90':>9}{'최대':>9}"
          f"{'시작가로':>11}{'p95':>8}")
    for label, keep in (("멈춤 없음", lambda r: r["stalls"] == 0),
                        ("멈춤 1회", lambda r: r["stalls"] == 1),
                        ("멈춤 2회+", lambda r: r["stalls"] >= 2)):
        sub = [r for r in rows if keep(r)]
        d = dur_stats(sub)
        lat = np.array([r["lat0"] for r in sub], dtype=float)
        print(f"     {label:<12}{len(sub):>5}{_fmt(np.median(d) if d.size else np.nan)}"
              f"{_fmt(pct(d, 90))}{_fmt(d.max() if d.size else np.nan)}"
              f"{_fmt(np.median(lat) if lat.size else np.nan, 11, 1)}"
              f"{_fmt(pct(lat, 95), 8, 1)}")
    print("     (지속 s · 시작가로 mm — 회전 시작 시점의 칸 중심 가로 오차)")

    st = [r for r in rows if r["stalls"] > 0]
    print()
    print(f"     멈춤이 있던 회전 {len(st)}회 ({100.0 * len(st) / len(rows):.1f}%)"
          f"  ·  멈춘 시간 합 {sum(r['stall_s'] for r in st):.1f} s")

    print()
    print("   [5] 급 × 멈춤  (n / 지속 p90 s)")
    print(f"     {'':<9}{'멈춤 없음':>17}{'멈춤 있음':>17}")
    for g in ("90도급", "180도급"):
        cells = []
        for want in (False, True):
            sub = [r["dur"] for r in rows
                   if r["grade"] == g and (r["stalls"] > 0) is want]
            cells.append(f"{len(sub):>4} / {pct(sub, 90):>6.2f}" if sub
                         else f"{0:>4} /      -")
        print(f"     {g:<9}{cells[0]:>17}{cells[1]:>17}")


def sec_lateral(rows):
    """시작 가로 오차 4분위 × 지속.

    ★ 값 경계로 나누면 동점이 많을 때 한 칸에 다 몰린다 (합성 검증에서 봤다).
      **순위로** 4등분한다.
    """
    print()
    print("   [6] 시작 가로 오차 vs 지속 — 틀어진 채 돌면 오래 걸리나")
    lat = np.array([r["lat0"] for r in rows], dtype=float)
    dur = dur_stats(rows)
    if lat.std() > 1e-9 and dur.std() > 1e-9:
        print(f"     상관계수 r = {float(np.corrcoef(lat, dur)[0, 1]):+.3f}"
              f"   (n={len(rows)})")
    # ★ 전체 r 은 **급에 교란된다** — 180°는 길고, 후진·접근 뒤라 시작이 더
    #   틀어져 있다. 그러면 「틀어지면 느려진다」가 아니라 「180°가 둘 다다」인데
    #   r 은 둘을 구별 못 한다. 급 안에서 다시 잰다. 인과가 있으면 여기서도 남는다.
    sub = [r for r in rows if r["grade"] == "90도급"]
    if len(sub) > 2:
        sl = np.array([r["lat0"] for r in sub], dtype=float)
        sd = dur_stats(sub)
        if sl.std() > 1e-9 and sd.std() > 1e-9:
            print(f"     90°급 안에서만 r = {float(np.corrcoef(sl, sd)[0, 1]):+.3f}"
                  f"   (n={len(sub)})  <- 급 교란을 뺀 값")
    order = np.argsort(lat, kind="stable")
    n = len(order)
    print(f"     {'':<12}{'n':>5}{'가로 중앙':>11}{'지속 중앙':>11}{'지속 p90':>11}")
    for qi, nm in enumerate(["가로 0-25%", "25-50%", "50-75%", "75-100%"]):
        idx = order[qi * n // 4:(qi + 1) * n // 4]
        if not len(idx):
            continue
        print(f"     {nm:<12}{len(idx):>5}{np.median(lat[idx]):>11.1f}"
              f"{np.median(dur[idx]):>11.2f}{pct(dur[idx], 90):>11.2f}")


def report(path, base, merged):
    name = os.path.basename(path)
    print()
    print(f"== {name} " + "=" * max(4, 62 - len(name)))
    if not base:
        print("   회전 구간을 못 찾았다 — W_MIN / MIN_DEG 를 확인하라")
        return
    bd, md = dur_stats(base), dur_stats(merged)

    print(f"   pitch {PITCH} · 틱 {TICK_S:.4f} s · 회전 1회 예산"
          f" {TURN_BUDGET:.3f} s ({TURN_TICKS}틱)")

    # --- 1. 두 분할 -------------------------------------------------------
    print()
    print("   [1] 분할 비교 — 기준 분할이 §10-4 와 같은 표본이다")
    print(f"     {'':<20}{'n':>5}{'중앙':>9}{'p90':>9}{'최대':>9}   s")
    print(f"     {'기준 (갭에서 끊음)':<20}{len(bd):>5}{np.median(bd):>9.2f}"
          f"{pct(bd, 90):>9.2f}{bd.max():>9.2f}")
    print(f"     {'병합 (제자리 갭 이음)':<20}{len(md):>5}{np.median(md):>9.2f}"
          f"{pct(md, 90):>9.2f}{md.max():>9.2f}")
    # ★ 개수 차로 판정하면 안 된다 — 조각 둘을 합치면 -1, 45° 미만이라
    #   버려지던 조각이 살아나면 +1 이라 **서로 상쇄돼 0 이 된다** (합성 검증에서
    #   기준 12 · 병합 12 인데 갭은 3개 병합된 경우를 봤다). 갭 수로 판정한다.
    ng = sum(r["stalls"] for r in merged)
    d = len(bd) - len(md)
    if not ng:
        print("     -> 병합된 갭이 없다. 회전이 갭으로 갈린 적이 없다는 뜻이다.")
    else:
        print(f"     -> 갭 {ng}개를 이었다 (개수는 {d:+d}). 기준 분할은 그만큼을"
              " 조각으로 세거나 45° 미만으로 버렸다 — §10-4 가 못 보던 표본이다.")

    # ★ 급별 표를 기준 분할에만 찍었더니 쓸모가 없었다 (실측 2026-09-15).
    #   180° 는 한가운데서 각속도가 1~2프레임 `W_MIN` 아래로 떨어지는데, 기준
    #   분할은 거기서 끊고 양쪽이 다 45° 를 넘으니 **90° 두 개로 센다** —
    #   그래서 기준 분할의 180°급은 어느 녹화에서나 0 이다. 병합 분할에서
    #   봐야 보인다. 둘 다 찍어서 그 차이 자체를 보여 준다.
    sec_grades(base, "2a", "기준 분할. 180°는 여기서 90° 두 개로 갈린다")
    sec_grades(merged, "2b", "병합 분할. §10-4 의 p90 과 맞대는 쪽")
    sec_gaps(merged)
    sec_stalls(merged)
    sec_lateral(merged)

    # --- 7. 가장 긴 회전 --------------------------------------------------
    print()
    print("   [7] 가장 오래 걸린 회전 8개 (병합 분할)")
    print(f"     {'지속':>7}{'각':>8}{'급':>10}{'멈춤':>6}{'멈춘시간':>10}"
          f"{'시작가로':>10}{'구간최대':>10}")
    for r in sorted(merged, key=lambda r: -r["dur"])[:8]:
        print(f"     {r['dur']:>7.2f}{r['deg']:>8.1f}{r['grade']:>10}"
              f"{r['stalls']:>6}{r['stall_s']:>10.2f}"
              f"{r['lat0']:>10.1f}{r['peak']:>10.1f}")
    print("     (지속·멈춘시간 s · 각 도 · 가로·구간최대 mm)")


def analyse(path):
    z = np.load(path, allow_pickle=True)
    t = np.asarray(z["t"], dtype=np.float64)
    pose = np.asarray(z["pose"], dtype=np.float64)
    base, merged = [], []
    for a in range(pose.shape[1]):
        x, y, yw = pose[:, a, 0], pose[:, a, 1], pose[:, a, 2]
        base.extend(turns_of(t, x, y, yw, do_merge=False))
        merged.extend(turns_of(t, x, y, yw, do_merge=True))
    return base, merged


def main():
    paths = [p for p in sys.argv[1:] if not p.startswith("-")]
    if not paths:
        raise SystemExit(__doc__)
    print(f"회전 꼬리 원인 — pitch {PITCH} · W_MIN {W_MIN} rad/s"
          f" · 갭 병합 {MAX_GAP:.2f} s / {MAX_MOVE:.2f} m")
    for p in paths:
        if not os.path.exists(p):
            print(f"\n* 없음: {p}")
            continue
        base, merged = analyse(p)
        report(p, base, merged)
    print()
    print("* 180°급이 꼬리를 만들면 계획도 10틱을 주므로 시간표는 안 어긋난다.")
    print("  그때 할 일은 컨트롤러가 아니라 **후진 1칸(4틱)으로 바꾸는 것**이다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
