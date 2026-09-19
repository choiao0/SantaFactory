# -*- coding: utf-8 -*-
"""θ → 처리량 응답 EDA — 어느 축이 실제로 처리량을 움직이는가 (S15P21A106-206).

## 왜 방향을 뒤집는가

여태 잰 것은 **기하 → θ** 였고 실패했다. 레이블인 θ 가 유일하지 않아서다 — 같은 창고를
다시 탐색하면 다른 θ 가 나오고 그 둘이 처리량은 같다(탐색 노이즈 63 %).

여기서는 **θ → 처리량**을 본다. 레이블이 처리량이라 유일하고, 노이즈는 시드 산포뿐이다.
답하는 질문도 다르다 — "θ 를 맞힐 수 있나" 가 아니라 **"θ 의 어느 축이 결과를 움직이나"** 다.
그 답은 예측 모델이 아니라 **스키마 축소**(`contracts/guidance_types.py`)의 근거가 된다.

## 데이터

`theta_open_lhs.py` 가 남긴 study 로그(`theta_open/*/run.log`)의 완료 trial 줄을 읽는다.
한 줄이 곧 (θ 11축, 그 θ 의 처리량) 한 쌍이다. 시뮬을 다시 돌지 않는다.

## 두 가지 함정

1. **창고마다 처리량 스케일이 다르다.** 절대값으로 섞으면 창고 효과가 θ 효과를 덮는다.
   그래서 **study 안에서 z 정규화**한 뒤 합친다 — 창고 차이가 사라지고 θ 효과만 남는다.
2. **TPE 는 무작위가 아니다.** 좋은 영역에 몰리므로 표본 범위가 좁아지고, 그러면 상관이
   실제보다 작게 나온다(range restriction). 그래서 **축별 범위 커버리지를 먼저 찍는다** —
   커버리지가 낮은 축의 상관은 과소평가로 읽어야 한다.

선형 상관만 보면 유계·비선형 관계를 놓치므로 **분위별 평균**(주효과)을 같이 낸다.
"""
import argparse
import ast
import glob
import os
import re
import sys

import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
FMS = os.path.abspath(os.path.join(HERE, "..", ".."))
RANGES = {"aisle_alt_gain": (1.0, 3.5), "aisle_alt_boost": (0.5, 1.0),
          "loop_gain": (1.0, 3.0), "main_aisle_gain": (0.5, 1.2),
          "junction_penalty": (1.0, 3.0), "station_in": (0.5, 1.0),
          "station_out": (1.0, 3.0), "wait_cost": (0.5, 3.0)}
AXES = list(RANGES)
CATS = ["aisle_period", "aisle_phase", "loop_dir"]
LINE = re.compile(r"Trial \d+ finished with value: ([\d.]+) and parameters: (\{.*?\})\.")


def read_trials(root):
    """study 로그에서 완료 trial 을 읽어 study 별로 묶는다."""
    studies = []
    for log in sorted(glob.glob(os.path.join(root, "*", "run.log"))):
        rows = []
        with open(log, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = LINE.search(line)
                if m:
                    rows.append((float(m.group(1)), ast.literal_eval(m.group(2))))
        if len(rows) >= 10:                 # 너무 짧은 study 는 정규화가 뜻이 없다
            studies.append(rows)
    return studies


def main():
    p = argparse.ArgumentParser(description="θ → 처리량 응답 EDA")
    p.add_argument("--dir", default=os.path.join(FMS, "infra", "out", "theta_open"))
    p.add_argument("--bins", type=int, default=5, help="분위 개수 (기본 5)")
    a = p.parse_args()

    studies = read_trials(a.dir)
    n_tr = sum(len(s) for s in studies)
    print("study %d개 · 완료 trial %d개" % (len(studies), n_tr))
    if not studies:
        return 1

    # study 안에서 z 정규화 — 창고 효과를 지우고 θ 효과만 남긴다
    X = {ax: [] for ax in AXES}
    C = {c: [] for c in CATS}
    z = []
    for rows in studies:
        v = np.array([r[0] for r in rows], float)
        sd = v.std()
        if sd == 0:
            continue
        zz = (v - v.mean()) / sd
        z.extend(zz.tolist())
        for ax in AXES:
            X[ax].extend(r[1].get(ax, np.nan) for r in rows)
        for c in CATS:
            C[c].extend(r[1].get(c, -1) for r in rows)
    z = np.array(z)
    print("  정규화 후 %d행 (study 안 z 점수 — 창고 차이 제거)" % len(z))

    print("\n=== 축별 범위 커버리지와 처리량 상관 ===")
    print("  커버리지가 낮으면 상관은 과소평가다 (TPE 가 좋은 쪽에 몰려서)")
    print("  %-20s%10s%10s%12s%12s" % ("θ 축", "탐색범위", "덮은 %", "상관 r", "설명력 R²"))
    print("  " + "-" * 64)
    res, live = [], []
    for ax in AXES:
        x = np.array(X[ax], float)
        ok = ~np.isnan(x)
        x, zz = x[ok], z[ok]
        lo, hi = RANGES[ax]
        if len(x) == 0 or x.std() == 0:
            # 차단 조건에서는 aisle_* 4개가 --exclude 로 고정돼 trial 에 아예 안 나온다
            print("  %-20s%10s%9s%12s%12s"
                  % (ax, "%.1f~%.1f" % (lo, hi), "-", "탐색안함", "-"))
            continue
        live.append(ax)
        cov = 100 * (x.max() - x.min()) / (hi - lo)
        r = float(np.corrcoef(x, zz)[0, 1]) if x.std() > 0 else 0.0
        res.append((ax, r))
        print("  %-20s%10s%9.0f%%%12.3f%12.3f"
              % (ax, "%.1f~%.1f" % (lo, hi), cov, r, r * r))

    print("\n=== 분위별 주효과 (처리량 z 평균 — 선형이 아닐 때를 위해) ===")
    print("  축을 %d분위로 갈라 각 칸의 처리량 z 평균. 폭이 클수록 그 축이 결과를 움직인다."
          % a.bins)
    print("  %-20s" % "θ 축" + "".join("%9s" % ("%d분위" % (i + 1)) for i in range(a.bins))
          + "%10s" % "최대-최소")
    print("  " + "-" * (20 + 9 * a.bins + 10))
    eff = []
    for ax in live:
        x = np.array(X[ax], float)
        ok = ~np.isnan(x)
        x, zz = x[ok], z[ok]
        qs = np.quantile(x, np.linspace(0, 1, a.bins + 1))
        cells = []
        for i in range(a.bins):
            sel = (x >= qs[i]) & (x <= qs[i + 1] if i == a.bins - 1 else x < qs[i + 1])
            cells.append(float(zz[sel].mean()) if sel.sum() else 0.0)
        span = max(cells) - min(cells)
        eff.append((ax, span))
        print("  %-20s" % ax + "".join("%9.3f" % c for c in cells) + "%10.3f" % span)

    print("\n=== 범주형 ===")
    print("  %-20s%12s%12s%12s%10s" % ("축", "값 0", "값 1", "값 2", "최대차"))
    print("  " + "-" * 68)
    for c in CATS:
        v = np.array(C[c], float)
        if len(v) == 0 or len(set(v.tolist())) <= 1:
            print("  %-20s%12s%12s%12s%10s" % (c, "-", "-", "-", "탐색안함"))
            continue
        cells = []
        for k in (0, 1, 2):
            sel = v == k
            cells.append(float(z[sel].mean()) if sel.sum() >= 20 else None)
        got = [x for x in cells if x is not None]
        span = (max(got) - min(got)) if len(got) >= 2 else 0.0
        print("  %-20s" % c + "".join("%12s" % ("%.3f" % x if x is not None else "-")
                                      for x in cells) + "%10.3f" % span)

    print("\n=== 판정 ===")
    eff.sort(key=lambda t: -t[1])
    tot = float(np.mean([abs(r) for _, r in res]))
    print("  주효과 큰 순: " + " > ".join("%s %.3f" % (a_, s) for a_, s in eff[:4]))
    print("  평균 |r| %.3f · 최대 |r| %.3f" % (tot, max(abs(r) for _, r in res)))
    print()
    if max(abs(r) for _, r in res) < 0.15:
        print("  어느 축도 처리량과 |r| 0.15 를 못 넘는다 — 처리량은 θ 에 거의 반응하지 않는다.")
        print("  평탄한 골짜기가 **축 단위로도** 확인된다. 주효과가 작은 축은 스키마에서 뺄 수 있다.")
    else:
        print("  반응하는 축이 있다. 주효과 큰 축만 남기고 스키마를 줄이면 골짜기가 좁아진다 —")
        print("  다만 스키마 변경은 기존 θ 를 전부 무효로 만든다(계약 변경, 별도 이슈).")
    print("\n  주의: trial 은 study 내 z 점수라 **창고 차이는 이미 제거**돼 있다.")
    print("  커버리지 %.0f%% 미만인 축의 상관은 과소평가로 읽을 것."
          % 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
