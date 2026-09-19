# -*- coding: utf-8 -*-
"""창고 기하 → θ 상관, 랙 통로 차단 vs 개방 (S15P21A106-206).

**왜 두 조건을 나란히 보나.** 운영 조건(`aisle_block=1`)에서는 로봇이 랙 사이 통로에
못 들어가므로 다니는 공간이 **바깥 사각 링 하나**다. 합성 창고가 바꾸는 세 인자
(통로 개수·간격·길이)는 전부 그 링 안쪽 — 로봇이 못 가는 곳 — 이라, AMR 관점에서는
링 둘레만 늘었다 줄었다 한다. 링에서 A→B 는 시계/반시계 둘뿐이라 θ 가 고를 것이 없다.

그래서 "기하로 θ 를 예측 못 한다" 가 **지형이 단순해서인지, θ 파라미터화가 과해서인지**
구분이 안 됐다. `--aisle-block 0` 으로 통로를 열면 통로 6개짜리와 16개짜리가 진짜로 다른
경로망이 된다. 두 조건의 상관을 나란히 놓으면 갈린다:

  개방에서 |r| 이 크게 오른다   -> 지형 탓. 예측은 원리적으로 가능하나 운영 조건에선 무의미
  개방에서도 그대로            -> 파라미터화 탓. 결론이 강해진다

순위 상관(Spearman)을 같이 본다 — θ 는 clamp 가 걸린 유계 값이라 선형이 아닐 수 있다.
n=85 에서 |r| > 0.213 이 p<0.05.

대조군으로 **같은 기하 → 처리량** 상관을 찍는다. 도구가 둔한 것과 관계가 약한 것을
구분하려면 이게 있어야 한다 (차단 조건 실측: θ 는 R² 0.13, 처리량은 0.72).

사용:
    python theta_geometry_corr.py                       # 차단만 (synth_v36)
    python theta_geometry_corr.py --open                # 차단 + 개방 나란히
"""
import argparse
import csv
import glob
import json
import os
import re
import statistics as st

import numpy as np


def _fms_root(start):
    """3_FMS 를 찾아 올라간다 — 이 파일을 ai_theta/experiments 에 두든 infra 에 두든 같게 돈다."""
    d = start
    for _ in range(4):
        if all(os.path.isdir(os.path.join(d, x)) for x in ("sim_engine", os.path.join("map", "synth"))):
            return d
        d = os.path.dirname(d)
    raise SystemExit("3_FMS 를 못 찾았다 — sim_engine 과 map/synth 가 있는 폴더가 위에 없다")


HERE = os.path.dirname(os.path.abspath(__file__))
FMS = _fms_root(HERE)
OUT = os.path.join(FMS, "infra", "out")

# 탐색 축. 차단 조건에서는 aisle_* 4개가 비트 단위로 무효라 중립 고정이고(계약 §5),
# 개방 조건에서만 살아난다. 그래서 두 조건의 축 수가 다르다 — 표에서 구분해 찍는다.
CORE = ["loop_gain", "main_aisle_gain", "junction_penalty",
        "station_in", "station_out", "wait_cost"]
AISLE = ["aisle_alt_gain", "aisle_alt_boost"]          # 개방에서만 의미 (범주형 2개는 제외)
FEATS = [("aisles", "통로 수"), ("pitch", "중심 간격"), ("length", "통로 길이")]
NAME = re.compile(r"theta_synth_(r(\d+)p(\d+)l(\d+))_r(\d+)_c6_v36(_open)?\.json$")
CRIT = 0.213                                            # n=85, p=0.05


def load(dirname):
    """<OUT>/<dirname>/*/theta_*.json 을 전부 읽어 기하와 함께 돌려준다."""
    rows = []
    for p in sorted(glob.glob(os.path.join(OUT, dirname, "*", "theta_*.json"))):
        m = NAME.search(os.path.basename(p))
        if not m:
            continue
        rows.append({"name": m.group(1), "aisles": int(m.group(2)),
                     "pitch": int(m.group(3)), "length": int(m.group(4)),
                     **json.load(open(p, encoding="utf-8"))})
    return rows


def rank(x):
    return np.argsort(np.argsort(np.asarray(x, float))).astype(float)


def corr(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    if x.std() == 0 or y.std() == 0:
        return 0.0
    return float(np.corrcoef(x, y)[0, 1])


def best(rows, feat, ax):
    """Pearson·Spearman 중 절대값이 큰 쪽. θ 가 유계라 선형이 아닐 수 있다."""
    x, y = [r[feat] for r in rows], [r[ax] for r in rows]
    a, b = corr(x, y), corr(rank(x), rank(y))
    return a if abs(a) >= abs(b) else b


def table(sets):
    """sets: [(라벨, rows)]. 축 × 기하인자 표를 조건별로 나란히 찍는다."""
    axes = CORE + (AISLE if any(lab != "차단" for lab, _ in sets) else [])
    head = "  %-20s" % "θ 축" + "".join(
        "%22s" % ("%s — %s" % (f[1], lab)) if False else "" for f in FEATS for lab, _ in sets)
    del head
    for feat, title in FEATS:
        print("\n  %s" % title)
        print("  %-20s" % "θ 축" + "".join("%12s" % lab for lab, _ in sets))
        print("  " + "-" * (20 + 12 * len(sets)))
        for ax in axes:
            cells = []
            for lab, rows in sets:
                if not rows or ax not in rows[0]:
                    cells.append("%12s" % "—")
                    continue
                r = best(rows, feat, ax)
                cells.append("%11.3f%s" % (r, "*" if abs(r) > CRIT else " "))
            print("  %-20s" % ax + "".join(cells))


def throughput_control():
    """대조군: 같은 기하가 처리량은 얼마나 설명하는가 (차단 조건 실측)."""
    path = os.path.join(OUT, "synth_sweep_v2.csv")
    if not os.path.exists(path):
        return
    rows = [r for r in csv.DictReader(open(path, encoding="utf-8")) if r.get("fixed_mean")]
    if not rows:
        return
    print("\n=== 대조군: 같은 기하 → 대당 처리량 (차단 조건) ===")
    for feat, title in FEATS:
        x = [int(r[feat]) for r in rows]
        y = [float(r["fixed_mean"]) / int(r["fleet"]) for r in rows]
        r = best([{feat: a, "y": b} for a, b in zip(x, y)], feat, "y")
        print("  %-12s r=%7.3f  R²=%.2f %s" % (title, r, r * r, "*" if abs(r) > CRIT else ""))


def main():
    p = argparse.ArgumentParser(description="창고 기하 → θ 상관")
    p.add_argument("--open", action="store_true", dest="with_open",
                   help="랙 통로 개방 결과(synth_v36_open)도 같이 본다")
    p.add_argument("--blocked-dir", default="synth_v36")
    p.add_argument("--open-dir", default="synth_v36_open")
    a = p.parse_args()

    sets = [("차단", load(a.blocked_dir))]
    if a.with_open:
        sets.append(("개방", load(a.open_dir)))
    for lab, rows in sets:
        if not rows:
            raise SystemExit("%s 결과가 비었다 — theta_sweep.py 를 먼저 돌릴 것" % lab)
        print("%s: 창고 %d개" % (lab, len(rows)))

    print("\n=== θ 축 분포 ===")
    print("  %-20s" % "축" + "".join("%20s" % ("%s 평균±표준편차" % lab) for lab, _ in sets))
    print("  " + "-" * (20 + 20 * len(sets)))
    for ax in CORE + AISLE:
        cells = []
        for lab, rows in sets:
            if rows and ax in rows[0]:
                v = [r[ax] for r in rows]
                cells.append("%20s" % ("%.3f ± %.3f" % (st.fmean(v), st.stdev(v))))
            else:
                cells.append("%20s" % "—")
        print("  %-20s" % ax + "".join(cells))

    print("\n=== 기하 → θ 상관 (|r| > %.3f 이면 p<0.05, * 표시) ===" % CRIT)
    table(sets)
    throughput_control()

    print("\n=== 판정 ===")
    for lab, rows in sets:
        rs = [abs(best(rows, f, ax)) for f, _ in FEATS for ax in CORE if ax in rows[0]]
        hits = sum(1 for v in rs if v > CRIT)
        print("  %-4s 유의 %2d/%2d 조합 · 최대 |r| %.3f (R² %.2f)"
              % (lab, hits, len(rs), max(rs), max(rs) ** 2))
    if len(sets) == 2:
        mb = max(abs(best(sets[0][1], f, ax)) for f, _ in FEATS for ax in CORE)
        mo = max(abs(best(sets[1][1], f, ax)) for f, _ in FEATS for ax in CORE)
        print()
        if mo > mb * 1.5:
            print("  -> 통로를 열면 상관이 뚜렷해진다. 평탄한 골짜기는 **지형 탓**이었다.")
            print("     기하 → θ 는 원리적으로 가능하나, 운영 조건(차단)에서는 여전히 무의미하다.")
        elif mo < mb * 1.2:
            print("  -> 통로를 열어도 그대로다. 지형이 아니라 **θ 파라미터화·목적함수** 문제다.")
            print("     '기하로 θ 를 예측 못 한다' 가 지형에 무관하게 성립한다.")
        else:
            print("  -> 조금 오른다. 지형도 일부 기여하지만 그것만으로는 설명이 안 된다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
