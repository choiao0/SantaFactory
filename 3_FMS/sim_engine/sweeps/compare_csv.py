# -*- coding: utf-8 -*-
"""두 결과 CSV 를 같은 조건 행끼리 짝지어 변화율을 낸다 (S15P21A106-79 D3, 2026-09-15).

    python sweeps/compare_csv.py results/load_sweep_v36.csv results/load_sweep_front_v38.csv [--key=tasks_per_h] [--rows]

행 짝짓기 키 = 두 CSV 에 모두 있는 열 중 {name, load, engine, variant, n_robots, seed, order_gap}. 헤딩 행만 비교하려면
두 번째 CSV 에 그 행만 있으면 된다(짝이 없는 행은 건너뛴다). 출력: 행 수·평균·중앙·범위·STALL 수, --rows 면 행별 표.
results/README.md 의 "v3 → v3.5" 식 비교 표를 만드는 데 쓴다."""
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import is_stall  # noqa: E402

KEYS = ("name", "load", "engine", "variant", "n_robots", "seed", "order_gap")


def read_csv(path):
    """숫자로 바뀌는 열만 float — 문자열 열(footprint·robot_dims·shifts …)은 그대로 (_common.read_csv 는 열 이름을 알아야 한다)."""
    import csv
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            for k, v in r.items():
                try:
                    r[k] = float(v) if v != "" else v
                except ValueError:
                    pass
            rows.append(r)
    return rows


def _key(row, cols):
    return tuple(str(row.get(c, "")) for c in cols)


def compare(base_path, new_path, metric="tasks_per_h", show_rows=False):
    base, new = read_csv(base_path), read_csv(new_path)
    cols = [c for c in KEYS if base and new and c in base[0] and c in new[0]]
    b = {_key(r, cols): r for r in base}
    pairs, stall_b, stall_n = [], 0, 0
    for r in new:
        k = _key(r, cols)
        if k not in b:
            continue
        rb = b[k]
        sb, sn = is_stall(rb), is_stall(r)
        stall_b += sb
        stall_n += sn
        if sb or sn or r.get(metric, "") == "" or rb.get(metric, "") == "":
            pairs.append((k, rb.get(metric, ""), r.get(metric, ""), None, sb, sn))
            continue
        pairs.append((k, rb[metric], r[metric], r[metric] / rb[metric] - 1, sb, sn))
    deltas = [p[3] for p in pairs if p[3] is not None]
    print(f"{os.path.basename(base_path)} → {os.path.basename(new_path)}  키={cols}  지표={metric}")
    print(f"  짝 {len(pairs)}행 (비교 가능 {len(deltas)}) · STALL {stall_b} → {stall_n}")
    if deltas:
        print(f"  평균 {statistics.mean(deltas) * 100:+.1f} %  중앙 {statistics.median(deltas) * 100:+.1f} %  "
              f"범위 {min(deltas) * 100:+.1f} ~ {max(deltas) * 100:+.1f} %")
    if show_rows:
        for k, vb, vn, d, sb, sn in pairs:
            tag = " ".join(f"{c}={v}" for c, v in zip(cols, k))
            ds = "STALL" if sn else ("(기준 STALL)" if sb else f"{d * 100:+.1f} %")
            print(f"    {tag:<48} {str(vb):>8} → {str(vn):>8}  {ds}")
    return pairs


def main(argv):
    paths = [a for a in argv if not a.startswith("--")]
    metric = next((a.split("=", 1)[1] for a in argv if a.startswith("--key=")), "tasks_per_h")
    assert len(paths) == 2, __doc__
    compare(paths[0], paths[1], metric, "--rows" in argv)


if __name__ == "__main__":
    main(sys.argv[1:])
