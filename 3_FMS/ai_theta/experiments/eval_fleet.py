# -*- coding: utf-8 -*-
# ============================================================
# 대수별 최적 θ 검증 — 탐색에 쓰지 않은 시드로 다시 잰다 (S15P21A106-142)
#
# BO 는 탐색 시드에서 유리한 θ 를 고른다. 그 시드로 성과를 보고하면 **시드 운을
# 성과로 보고**하게 된다. 실측(24대): 탐색 시드 +15.7% → 미사용 시드 +9.9%.
# 5.8%p 가 과적합이었다.
#
# 그래서 두 벌을 다 재고 나란히 남긴다. 발표·B트랙 전달에 쓰는 값은 **평가 시드**
# 쪽이고, 탐색 시드 값은 과적합 크기를 보이기 위한 참고다.
#
# 정체(STALL)도 결과다 — 극단 θ 가 교착을 만들면 계약 §3 대로 rc=1 이 되는데,
# 그 사실을 삼키면 "빠졌다"가 아니라 "없었다"로 읽힌다. 실패는 표에 남긴다.
#
# 사용 (컨테이너):
#   docker run ... python /work/ai_theta/experiments/eval_fleet.py \
#       --out /work/ai_theta/results
# ============================================================
import argparse
import csv
import json
import os
import statistics
import sys

_FMS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_WORKER = os.path.join(_FMS_ROOT, "infra", "worker")
for _p in (_FMS_ROOT, _WORKER):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from objective import SimFailed, run_once, write_theta  # noqa: E402

NEUTRAL = {
    "aisle_alt_gain": 1.0, "aisle_alt_boost": 1.0, "loop_gain": 1.0,
    "main_aisle_gain": 1.0, "junction_penalty": 1.0, "station_in": 1.0,
    "station_out": 1.0, "wait_cost": 1.0,
    "aisle_period": 1, "aisle_phase": 0, "loop_dir": 0,
}


def run_seeds(sim_engine, theta, robots, orders, gap, seeds, timeout_s):
    """(성공한 값 목록, 실패한 시드 목록). 정체도 결과이므로 삼키지 않는다."""
    path = write_theta(theta)
    values, failed = [], []
    try:
        for seed in seeds:
            try:
                summary = run_once(sim_engine, path, robots, orders, seed,
                                   aisle_block=1, tag="ev", order_gap=gap,
                                   timeout_s=timeout_s)
                values.append(summary["tasks_per_h"])
            except SimFailed:
                failed.append(seed)
    finally:
        os.unlink(path)
    return values, failed


def pct(new, old):
    return (new / old - 1) * 100 if old else float("nan")


def main(argv=None):
    p = argparse.ArgumentParser(description="대수별 θ 검증")
    p.add_argument("--sim-engine", default="/work/sim_engine", dest="sim_engine")
    p.add_argument("--theta-dir", default="/work/infra/out", dest="theta_dir")
    p.add_argument("--robots", default="8,12,16,20,24,28")
    p.add_argument("--orders", type=int, default=120)
    p.add_argument("--order-gap", type=float, default=15.0, dest="order_gap")
    p.add_argument("--train-seeds", default="42,43,44", dest="train_seeds")
    p.add_argument("--eval-seeds", default="7,11,23", dest="eval_seeds")
    p.add_argument("--timeout", type=int, default=600)
    p.add_argument("--out", default="")
    args = p.parse_args(argv)
    fleet = [int(x) for x in args.robots.split(",") if x.strip()]
    train = [int(x) for x in args.train_seeds.split(",") if x.strip()]
    evals = [int(x) for x in args.eval_seeds.split(",") if x.strip()]

    print(f"조건 주문 {args.orders} · 간격 {args.order_gap} · aisle_block 1 · 헤딩")
    print(f"탐색 시드 {train} / 평가 시드 {evals} (탐색에 쓰지 않음)\n")
    print(f"{'대수':>4}{'중립':>9}{'θ':>9}{'Δ':>8}{'Δ%(평가)':>10}"
          f"{'Δ%(탐색)':>10}  시드별 Δ / 비고")
    print("-" * 84)

    rows = []
    for robots in fleet:
        path = os.path.join(args.theta_dir, f"theta_wallA_r{robots}_g15.json")
        if not os.path.exists(path):
            print(f"{robots:>4}  θ 파일 없음 — {path}")
            continue
        theta = json.load(open(path, encoding="utf-8"))
        run = lambda th, sd: run_seeds(args.sim_engine, th, robots, args.orders,
                                       args.order_gap, sd, args.timeout)
        nh, nh_bad = run(NEUTRAL, evals)
        bh, bh_bad = run(theta, evals)
        nt, _ = run(NEUTRAL, train)
        bt, bt_bad = run(theta, train)

        note = []
        if nh_bad or bh_bad or bt_bad:
            note.append(f"정체 중립{nh_bad} θ평가{bh_bad} θ탐색{bt_bad}")
        if not nh or not bh:
            print(f"{robots:>4}  비교 불가 — {'; '.join(note)}")
            rows.append(dict(robots=robots, note="; ".join(note)))
            continue

        mn, mb = statistics.fmean(nh), statistics.fmean(bh)
        # 짝지은 비교: 같은 시드끼리 뺀다 (감도 실험과 같은 원칙)
        per_seed = [round(b - n, 1) for n, b in zip(nh, bh)] if len(nh) == len(bh) else []
        p_eval = pct(mb, mn)
        p_train = pct(statistics.fmean(bt), statistics.fmean(nt)) if bt and nt else float("nan")
        print(f"{robots:>4}{mn:>9.1f}{mb:>9.1f}{mb - mn:>+8.1f}{p_eval:>+9.1f}%"
              f"{p_train:>+9.1f}%  {per_seed} {'; '.join(note)}")
        rows.append(dict(robots=robots, neutral_eval=round(mn, 1), theta_eval=round(mb, 1),
                         delta=round(mb - mn, 1), pct_eval=round(p_eval, 1),
                         pct_train=round(p_train, 1),
                         per_seed=" ".join(str(x) for x in per_seed),
                         note="; ".join(note)))

    if args.out and rows:
        os.makedirs(args.out, exist_ok=True)
        fields = ["robots", "neutral_eval", "theta_eval", "delta", "pct_eval",
                  "pct_train", "per_seed", "note"]
        # 평가 시드를 파일명에 넣는다. 빼면 시드가 다른 실행이 같은 파일을
        # 덮어써서 "어느 시드로 잰 값인지" 파일만 보고는 알 수 없다
        # (감도 실험에서 aisle_block 을 빼고 같은 사고를 한 적이 있다).
        tag = "-".join(str(s) for s in evals)
        dst = os.path.join(args.out, f"theta_fleet_g{args.order_gap:g}_s{tag}.csv")
        with open(dst, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        print(f"\nCSV → {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
