# -*- coding: utf-8 -*-
"""대리 모델 학습 세트 조립 — (맵, θ) → 처리량 (S15P21A106-206).

## 방향을 뒤집는다

여태 실패한 것은 `맵 → θ` 였다. 레이블인 θ 가 유일하지 않아서다 — 같은 맵을 다시 탐색하면
다른 θ 가 나오고 그 둘의 처리량이 같다(탐색 노이즈 63 %).

여기서는 **`(맵, θ) → 처리량`** 을 배운다. 레이블이 처리량이라 유일하고, 노이즈는 시드
산포뿐이다. θ 를 출력이 아니라 **입력**으로 넣는 것이 핵심이고, 그러면 학습이 끝난 뒤
**모델 위에서 θ 를 최적화**해 맵별 θ 를 얻을 수 있다(`optimize_theta.py`).

덤으로 데이터가 92배가 된다. 직접 회귀는 맵당 '최적 θ' 한 줄만 쓰지만, 대리 모델은 탐색
도중 나온 **나쁜 θ 까지 전부** 쓴다 — 나쁜 결과도 응답면을 그리는 정보다.

## 두 조건을 따로 만든다

    차단(운영)  study 85  · trial 9,249 · θ 7축  · 주문 250건 고정
    개방        study 208 · trial 7,205 · θ 11축 · 상대부하 가변

합치면 `load_frac` 열이 `aisle_block` 과 거의 같은 값이 돼(차단은 전부 고정) 모델이 둘을
구분하지 못한다. 그래서 조건별로 나눠 각자의 특징만 쓴다.

## 처리량은 study 안에서 z 정규화한다

맵마다 처리량 스케일이 다르다(작은 창고 400, 큰 창고 900). 절대값으로 섞으면 **맵 효과가
θ 효과를 덮는다.** study 안에서 z 로 바꾸면 맵 차이가 사라지고 θ 효과만 남는다.
원래 값(`tasks_per_h`)과 study 평균·표준편차도 같이 남겨 되돌릴 수 있게 한다.
"""
import argparse
import ast
import csv
import glob
import json
import os
import re
import sys

import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
FMS = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(FMS, "infra", "out")

LINE = re.compile(r"Trial (\d+) finished with value: ([\d.]+) and parameters: (\{.*?\})\.")
# 개방 study 폴더명: open_<맵>_r<대수>_L<부하>_s<샘플러시드> — 맵 하나에 study 2개(반복)
OPEN_DIR = re.compile(r"^open_(r\d+p\d+l\d+)_r\d+_L\d+_s\d+$")

BLOCKED_FEATS = ["aisles", "pitch", "length", "free", "fleet"]
OPEN_FEATS = BLOCKED_FEATS + ["load_frac"]
BLOCKED_AXES = ["loop_gain", "main_aisle_gain", "junction_penalty",
                "station_in", "station_out", "wait_cost", "loop_dir"]
OPEN_AXES = ["aisle_alt_gain", "aisle_alt_boost"] + BLOCKED_AXES[:-1] + \
            ["aisle_period", "aisle_phase", "loop_dir"]


def read_study(log):
    rows = []
    with open(log, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = LINE.search(line)
            if m:
                rows.append((int(m.group(1)), float(m.group(2)),
                             ast.literal_eval(m.group(3))))
    return rows


def assemble(studies, feats, axes, out_path, min_trials=10):
    """study 단위로 z 정규화해 한 장의 표로 만든다."""
    recs, dropped = [], 0
    for study_id, map_name, mf, rows in studies:
        if len(rows) < min_trials:
            dropped += 1
            continue
        v = np.array([r[1] for r in rows], float)
        mu, sd = float(v.mean()), float(v.std())
        if sd == 0:
            dropped += 1
            continue
        for n, val, th in rows:
            if any(a not in th for a in axes):
                continue
            r = {"study": study_id, "map": map_name, "trial": n,
                 "tasks_per_h": val, "z": (val - mu) / sd,
                 "study_mean": round(mu, 3), "study_sd": round(sd, 4)}
            r.update({k: mf[k] for k in feats})
            r.update({a: th[a] for a in axes})
            recs.append(r)
    cols = ["study", "map", "trial"] + feats + axes + \
           ["tasks_per_h", "z", "study_mean", "study_sd"]
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(recs)
    return recs, dropped


def build_blocked(out_dir):
    """차단(운영) — 맵 특징은 synth_sweep_v2.csv 에서 이름으로 붙인다."""
    feat = {r["name"]: {k: float(r[k]) for k in BLOCKED_FEATS}
            for r in csv.DictReader(open(os.path.join(OUT, "synth_sweep_v2.csv"),
                                         encoding="utf-8"))}
    studies = []
    for log in sorted(glob.glob(os.path.join(OUT, "synth_v36", "*", "run.log"))):
        name = os.path.basename(os.path.dirname(log))
        if name in feat:
            studies.append((name, name, feat[name], read_study(log)))
    return assemble(studies, BLOCKED_FEATS, BLOCKED_AXES,
                    os.path.join(out_dir, "surrogate_blocked.csv"))


def build_open(out_dir):
    """개방 — 맵 특징은 design.json. 맵 하나에 study 2개(반복)라 study 단위로 정규화한다."""
    design = {d["name"]: d for d in json.load(
        open(os.path.join(OUT, "theta_open", "design.json"), encoding="utf-8"))}
    studies = []
    for log in sorted(glob.glob(os.path.join(OUT, "theta_open", "*", "run.log"))):
        d = os.path.basename(os.path.dirname(log))
        m = OPEN_DIR.match(d)
        if not m or m.group(1) not in design:
            continue
        name = m.group(1)
        mf = {k: float(design[name][k]) for k in OPEN_FEATS}
        studies.append((d, name, mf, read_study(log)))
    return assemble(studies, OPEN_FEATS, OPEN_AXES,
                    os.path.join(out_dir, "surrogate_open.csv"))


def main():
    p = argparse.ArgumentParser(description="대리 모델 학습 세트 조립")
    p.add_argument("--out", default=OUT)
    a = p.parse_args()

    for lab, fn, feats, axes in (("차단 (운영)", build_blocked, BLOCKED_FEATS, BLOCKED_AXES),
                                 ("개방", build_open, OPEN_FEATS, OPEN_AXES)):
        recs, dropped = fn(a.out)
        if not recs:
            print("%s — 데이터 없음" % lab)
            continue
        maps = {r["map"] for r in recs}
        studies = {r["study"] for r in recs}
        z = np.array([r["z"] for r in recs])
        tp = np.array([r["tasks_per_h"] for r in recs])
        print("=== %s ===" % lab)
        print("  %d행 · 맵 %d개 · study %d개 (짧아서 버린 study %d개)"
              % (len(recs), len(maps), len(studies), dropped))
        print("  입력 %d차원 = 맵 특징 %d + θ %d축" % (len(feats) + len(axes), len(feats), len(axes)))
        print("  처리량 %.0f ~ %.0f (평균 %.0f) · z 는 study 안에서 표준화"
              % (tp.min(), tp.max(), tp.mean()))
        print("  z 범위 %.2f ~ %.2f" % (z.min(), z.max()))
        print()
    print("→ %s 에 surrogate_blocked.csv · surrogate_open.csv" % a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
