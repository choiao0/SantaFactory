# -*- coding: utf-8 -*-
"""개방 조건 θ 탐색 결과 → 학습 세트 조립 + 기하 상관 판정 (S15P21A106-206).

`theta_open_lhs.py` 가 남긴 것을 모은다.

    theta_open/design.json                       창고별 조건 (기하·대수·부하·용량)
    theta_open/<창고>_s<시드>/theta_open_*.json   반복별 θ 11축

둘을 합쳐 **학습 세트 CSV** 를 만들고, 그 자리에서 **기하 → θ 상관**을 판정한다.
시뮬을 다시 돌지 않는다 — 이미 있는 파일을 읽어 표로 만드는 것뿐이다.

## 무엇을 보는가

차단 조건(운영)에서는 로봇이 바깥 링만 써서 창고가 달라도 지형이 같았고, 기하가 θ 변동의
**13 %** 밖에 설명 못 했다(R² 0.13). 통로를 열면 창고마다 진짜 다른 경로망이 되므로 그 값이
올라야 한다. 안 오르면 지형이 아니라 **목적함수·파라미터화**가 원인이다.

**반복 2회의 평균을 레이블로 쓴다.** 앞선 재현성 측정에서 θ 변동의 63 % 가 탐색 노이즈였다.
2회 평균이면 노이즈 분산이 절반이 되어 모델 천장이 37 % → 54 % 로 오른다. 그리고 두 회차의
차이 자체가 **그 조건에서의 노이즈 추정치**라, 신호와 잡음을 갈라 볼 수 있다.

순위 상관(Spearman)을 같이 본다 — θ 는 clamp 가 걸린 유계 값이라 선형이 아닐 수 있다.
n 이 100 근처면 |r| > 0.20 이 대략 p<0.05 다.
"""
import argparse
import csv
import glob
import json
import os
import re
import statistics as st

import numpy as np

AXES = ["aisle_alt_gain", "aisle_alt_boost", "loop_gain", "main_aisle_gain",
        "junction_penalty", "station_in", "station_out", "wait_cost"]
CATS = ["aisle_period", "aisle_phase", "loop_dir"]
FEATS = [("aisles", "통로 수"), ("pitch", "중심 간격"), ("length", "통로 길이"),
         ("free", "통행 칸"), ("fleet", "대수"), ("load_frac", "상대 부하")]
NAME = re.compile(r"theta_open_(r\d+p\d+l\d+)_s(\d+)\.json$")


def rank(x):
    return np.argsort(np.argsort(np.asarray(x, float))).astype(float)


def corr(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    if x.std() == 0 or y.std() == 0:
        return 0.0
    return float(np.corrcoef(x, y)[0, 1])


def best(rows, feat, ax):
    """Pearson·Spearman 중 절대값이 큰 쪽 — θ 가 유계라 선형이 아닐 수 있다."""
    x, y = [r[feat] for r in rows], [r[ax] for r in rows]
    a, b = corr(x, y), corr(rank(x), rank(y))
    return a if abs(a) >= abs(b) else b


def main():
    p = argparse.ArgumentParser(description="개방 θ 결과 조립 + 상관 판정")
    p.add_argument("--dir", default="out/theta_open", help="theta_open 폴더")
    p.add_argument("--out", default="out/theta_open_lhs_v36.csv")
    a = p.parse_args()

    design = {d["name"]: d for d in json.load(open(os.path.join(a.dir, "design.json"),
                                                   encoding="utf-8"))}
    got = {}
    for f in sorted(glob.glob(os.path.join(a.dir, "*", "theta_open_*.json"))):
        m = NAME.search(os.path.basename(f))
        if m:
            got.setdefault(m.group(1), []).append(json.load(open(f, encoding="utf-8")))

    rows = []
    for name, ts in sorted(got.items()):
        if name not in design:
            continue
        r = dict(design[name])
        r["n_rep"] = len(ts)
        r.update({ax: round(st.fmean(t[ax] for t in ts), 5) for ax in AXES})
        r.update({c: st.mode([t[c] for t in ts]) for c in CATS})
        # 두 회차의 차이 = 그 조건에서의 탐색 노이즈 추정치
        if len(ts) >= 2:
            for ax in AXES:
                r["sd_" + ax] = round(st.stdev([t[ax] for t in ts]), 5)
        rows.append(r)

    with open(a.out, "w", encoding="utf-8", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=sorted({k for r in rows for k in r}),
                            extrasaction="ignore")
        wr.writeheader()
        wr.writerows(rows)

    n2 = [r for r in rows if r["n_rep"] >= 2]
    print("학습 세트 %d행 → %s" % (len(rows), a.out))
    print("  반복 2회 %d행 · 1회만 %d행 · 설계 %d창고 중"
          % (len(n2), len(rows) - len(n2), len(design)))
    missing = sorted(set(design) - set(got))
    if missing:
        print("  빠진 창고 %d개: %s" % (len(missing), ", ".join(missing[:8])))

    if len(n2) < 20:
        print("\n반복 2회 행이 너무 적어 판정 불가")
        return 1

    print("\n=== 탐색 노이즈 (반복 2회 차이) vs 창고간 산포 ===")
    print("  %-20s%12s%12s%9s" % ("축", "노이즈", "창고간", "신호/잡음"))
    print("  " + "-" * 54)
    live = []
    for ax in AXES:
        e = st.fmean(r["sd_" + ax] for r in n2)              # 반복 내 표준편차
        b = st.stdev([r[ax] for r in n2])                    # 창고 평균들의 산포
        sig2 = b * b - e * e / 2                             # 노이즈를 뺀 창고 신호
        sig = sig2 ** 0.5 if sig2 > 0 else 0.0
        ratio = sig / e if e else 0.0
        live.append((ax, ratio))
        print("  %-20s%12.3f%12.3f%9.2f%s" % (ax, e, b, ratio, " ★" if ratio > 1 else ""))

    print("\n=== 기하·조건 → θ 상관 (|r| > 0.20 이면 대략 p<0.05) ===")
    print("  %-20s" % "θ 축" + "".join("%12s" % t for _, t in FEATS))
    print("  " + "-" * (20 + 12 * len(FEATS)))
    rmax = 0.0
    for ax in AXES:
        cells = []
        for feat, _ in FEATS:
            r = best(n2, feat, ax)
            rmax = max(rmax, abs(r))
            cells.append("%11.3f%s" % (r, "*" if abs(r) > 0.20 else " "))
        print("  %-20s" % ax + "".join(cells))

    print("\n=== 판정 ===")
    print("  최대 |r| = %.3f  (R² = %.2f)" % (rmax, rmax ** 2))
    print("  차단 조건 기준선: 최대 |r| 0.362 (R² 0.13)")
    if rmax ** 2 >= 0.35:
        print("  -> 통로를 열자 상관이 뚜렷해졌다. **지형이 원인이었다.**")
        print("     기하 → θ 예측이 성립할 여지가 있다. 다음은 정면 대결(창고별 θ vs 공통 θ).")
    elif rmax ** 2 <= 0.18:
        print("  -> 통로를 열어도 그대로다. 지형이 아니라 **목적함수·파라미터화**가 원인이다.")
        print("     기하로 θ 를 예측할 수 없다는 결론이 지형에 무관하게 성립한다.")
    else:
        print("  -> 조금 올랐다. 지형도 일부 기여하지만 그것만으로는 설명이 안 된다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
