# -*- coding: utf-8 -*-
# ============================================================
# θ 감도 실험 — 실효 파라미터 식별 (S15P21A106-138)
#
# θ 실험 로드맵 1단계. 묻는 것은 하나다:
#
#   "θ 11개 중 실제로 처리량을 움직이는 것은 몇 개인가?"
#
# 움직이지 않는 파라미터를 탐색 공간에 두면 BO 는 평평한 축을 헤매고, AI 는
# "서로 다른 라벨이 같은 결과를 내는" 모순을 학습한다. 그래서 탐색·학습보다
# 이 실험이 먼저다.
#
# 방법 — theta_fixtures.py 와 같은 격리 원칙: 중립 θ 에서 **한 번에 하나만** 바꾼다.
#   연속 8개: 계약 범위의 하한·상한 (범위 밖은 GuidanceTheta.validate 가 막는다)
#   범주 3개: 기본값이 아닌 값 전부 (period 2·3, phase 1, loop_dir 1)
#   기준: 중립 θ, 그리고 --theta 없는 uniform 실행
#
# ⚠️ 이 실험이 "효과 없음"이라 말할 수 없는 것
#   1. 배타 선점 — 상위 그룹이 선점한 간선에서는 하위 규칙이 아예 적용되지 않는다
#      (station_spur > loop > intersection_entry > aisle_interior). 격리해도 안 보이는
#      효과가 있다. theta_fixtures.py 의 "격리의 한계" 참고.
#   2. 상호작용 — 단독으로 0이어도 다른 θ 와 함께면 움직일 수 있다. 1차 효과만 본다.
#   따라서 Δ≈0 은 "탐색 우선순위가 낮다"이지 "빼도 된다"가 아니다. 축소는 BO 결과와
#   함께 판단한다.
#
# 판정 기준 — **짝지은(paired) 비교**. 모든 케이스가 같은 시드를 쓰므로 베이스와
# 같은 시드끼리 뺀다. 시드가 만든 변동은 양쪽에 똑같이 실려 상쇄되고 파라미터가
# 만든 차이만 남는다. 시드마다 부호가 같고(방향 일관) 그 평균이 시드별 차이의
# 폭보다 크면 실효로 본다.
#
# 케이스 전체의 최대 산포를 하나의 문턱으로 쓰면 안 된다 — 실측에서 wait_cost 의
# Δ+47.7(자기 산포 15.5)이 무관한 station_in 의 산포 49.4 에 밀려 "잡음"으로
# 깎였다. 40주문·간격 50 에서 θ 효과 0.03 vs 산포 17.7 로 목적함수를 못 정했던
# 것이 이 실험을 하는 이유다(objective.py 주석, 고부하 판정 §2).
#
# 사용 (컨테이너):
#   docker compose run --rm worker \
#       python /work/ai_theta/experiments/theta_sensitivity.py --out /work/ai_theta/results
# 빠른 예비 조사(칸 모델, 40배 빠름 — 결론용 아님):
#   ... theta_sensitivity.py --no-heading --orders 40 --seeds 42,43
# ============================================================
import argparse
import csv
import os
import statistics
import sys
import time
from dataclasses import replace

_FMS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_WORKER = os.path.join(_FMS_ROOT, "infra", "worker")
for _p in (_FMS_ROOT, _WORKER):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from contracts.guidance_types import (GuidanceTheta,          # noqa: E402
                                      THETA_CATEGORICAL_VALUES,
                                      THETA_CONTINUOUS_RANGES)
from objective import SimFailed, run_once, write_theta        # noqa: E402

# CSV·표에 남길 KPI. 목적함수 후보를 한 번에 비교하려고 처리량 말고도 담는다 —
# 처리량이 평평해도 리드타임이 움직이면 목적함수를 바꿔야 한다.
METRICS = ("tasks_per_h", "lead_mean_s", "lead_p90_s", "makespan_steps",
           "queue_mean_s", "drive_mean_s", "conflict_wait", "turns_per_task")
PRIMARY = "tasks_per_h"


def theta_dict(theta):
    """GuidanceTheta → sim_v2 --theta 가 읽는 dict (범주형은 정수)."""
    return {name: getattr(theta, name) for name in
            list(THETA_CONTINUOUS_RANGES) + list(THETA_CATEGORICAL_VALUES)}


# 범주형 θ 를 켜 주는 연속 θ — 중립 위에서 범주형만 바꾸면 효과가 나올 수 없다.
# aisle_period·aisle_phase 는 "어느 방향을 선호할지"만 정하는데 순방향 할인과
# 역주행 벌금이 둘 다 1.0 이면 어느 방향이든 비용이 같다. loop_dir 도 마찬가지로
# loop_gain 이 1.0 이면 무효다. theta_fixtures.py 가 _AISLE_ONEWAY 를 깔고
# 범주형을 검증하는 것과 같은 이유다. 그래서 범주형은 **자기 짝을 켠 베이스** 위에서
# 재고, Δ 도 중립이 아니라 그 베이스와 비교한다.
ENABLERS = {
    "aisle_period": ("aisle_oneway", dict(aisle_alt_gain=3.5, aisle_alt_boost=0.5)),
    "aisle_phase": ("aisle_oneway", dict(aisle_alt_gain=3.5, aisle_alt_boost=0.5)),
    "loop_dir": ("loop_gain=3", dict(loop_gain=3.0)),
}


def build_cases():
    """(라벨, 파라미터, 값, θ dict 또는 None, 비교 기준 라벨) 목록.

    θ dict None = uniform(--theta 없음). 비교 기준은 보통 중립이지만, 범주형은
    자기를 켜 주는 연속 θ 를 깐 베이스와 비교해야 의미가 있다.
    """
    neutral = GuidanceTheta.neutral()
    cases = [("uniform", "-", "-", None, "neutral"),
             ("neutral", "-", "-", theta_dict(neutral), "neutral")]
    for name, (lo, hi) in THETA_CONTINUOUS_RANGES.items():
        for value in (lo, hi):
            if value == getattr(neutral, name):
                continue          # 중립과 같은 끝은 중복이라 건너뛴다
            theta = replace(neutral, **{name: value}).validate()
            cases.append((f"{name}={value:g}", name, value,
                          theta_dict(theta), "neutral"))
    # 범주형 베이스 — 통로 교번을 켠 것. loop 베이스는 loop_gain=3 케이스가 겸한다.
    oneway = replace(neutral, **ENABLERS["aisle_period"][1]).validate()
    cases.append(("aisle_oneway", "aisle_alt_gain+boost", "3.5/0.5",
                  theta_dict(oneway), "neutral"))
    for name, values in THETA_CATEGORICAL_VALUES.items():
        base_label, enabler = ENABLERS[name]
        base = replace(neutral, **enabler)
        for value in values:
            if value == getattr(neutral, name):
                continue          # 베이스가 이미 기본값이므로 중복
            theta = replace(base, **{name: value}).validate()
            cases.append((f"{name}={value}", name, value,
                          theta_dict(theta), base_label))
    return cases


def evaluate_case(theta, args, seeds):
    """한 케이스를 시드별로 돌려 KPI 평균·산포·**시드별 원값**을 돌려준다.

    시드별 원값을 남기는 이유: 모든 케이스가 같은 시드를 쓰므로 베이스와
    **짝지어(paired)** 비교할 수 있다. 시드가 만든 변동이 양쪽에 똑같이 실리므로
    차이를 내면 상쇄되고, 파라미터가 만든 차이만 남는다. 케이스별 평균만 남기면
    이 정보가 사라져 "시드 산포에 묻혔다"는 과도한 판정을 하게 된다.
    """
    path = write_theta(theta) if theta is not None else None
    per_seed, failures = {}, []
    try:
        for seed in seeds:
            try:
                per_seed[seed] = run_once(args.sim_engine, path, args.robots,
                                          args.orders, seed, tag="sens",
                                          aisle_block=args.aisle_block,
                                          heading=args.heading,
                                          order_gap=args.order_gap,
                                          timeout_s=args.timeout)
            except SimFailed as exc:
                failures.append(f"seed {seed}: {str(exc).splitlines()[0]}")
    finally:
        if path is not None:
            os.unlink(path)
    if not per_seed:
        return None, failures
    stats = {"n_ok": len(per_seed), "_per_seed": per_seed}
    for key in METRICS:
        values = [r[key] for r in per_seed.values() if key in r]
        if not values:
            continue
        stats[f"mean_{key}"] = statistics.fmean(values)
        stats[f"spread_{key}"] = max(values) - min(values)
        stats[f"seeds_{key}"] = "|".join(f"{r[key]:g}" for r in per_seed.values())
    return stats, failures


def main(argv=None):
    p = argparse.ArgumentParser(description="θ 감도 실험")
    p.add_argument("--sim-engine", default="/work/sim_engine", dest="sim_engine")
    p.add_argument("--robots", type=int, default=24)
    p.add_argument("--orders", type=int, default=120)
    p.add_argument("--order-gap", type=float, default=15.0, dest="order_gap")
    p.add_argument("--aisle-block", type=int, default=1, dest="aisle_block")
    p.add_argument("--heading", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--seeds", default="42,43,44")
    p.add_argument("--timeout", type=int, default=600)
    p.add_argument("--out", default="", help="CSV 저장 디렉토리")
    args = p.parse_args(argv)
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]

    cases = build_cases()
    model = "헤딩" if args.heading else "칸"
    print(f"θ 감도 실험 — {model} 모델 · 로봇 {args.robots} · 주문 {args.orders} · "
          f"간격 {args.order_gap} · aisle_block {args.aisle_block} · 시드 {seeds}")
    print(f"케이스 {len(cases)}개 × 시드 {len(seeds)}개 = {len(cases) * len(seeds)} 런\n")

    rows, t0 = [], time.perf_counter()
    for i, (label, param, value, theta, base_label) in enumerate(cases, 1):
        stats, failures = evaluate_case(theta, args, seeds)
        elapsed = time.perf_counter() - t0
        common = {"case": label, "param": param, "value": value, "base": base_label}
        if stats is None:
            print(f"[{i:>2}/{len(cases)}] {label:<28} 전 시드 실패 — {failures}")
            rows.append({**common, "n_ok": 0})
            continue
        print(f"[{i:>2}/{len(cases)}] {label:<28} "
              f"{PRIMARY} {stats['mean_' + PRIMARY]:8.1f} "
              f"(산포 {stats['spread_' + PRIMARY]:5.1f})  {elapsed / 60:.0f}분 경과"
              + (f"  ⚠ {len(failures)}개 실패" if failures else ""))
        rows.append({**common, **stats})

    report(rows, seeds, args)
    if args.out:
        save_csv(rows, args, seeds)
    return 0


def report(rows, seeds, args):
    """Δ(각자의 베이스 대비)를 시드 산포와 나란히 놓고 실효/무효를 가른다."""
    print("\n" + "=" * 100)
    by_case = {r["case"]: r for r in rows if r.get("n_ok")}
    neutral = by_case.get("neutral")
    if neutral is None:
        print("중립 θ 실행이 실패해 비교 기준이 없다.")
        return
    ref = neutral[f"mean_{PRIMARY}"]
    # 참고값으로만 남긴다. 판정은 짝지은 차이로 하므로 이 값은 쓰지 않는다 —
    # 케이스 전체의 최대 산포를 문턱으로 쓰면 다른 케이스의 시드 운이 이 케이스의
    # 판정을 깎는다(실측에서 wait_cost Δ+47.7 이 station_in 의 산포 49.4 에 밀렸다).
    noise = max(r.get(f"spread_{PRIMARY}", 0.0) for r in rows if r.get("n_ok"))
    print(f"기준: 중립 θ {PRIMARY} = {ref:.1f} (참고: 케이스 최대 시드 산포 {noise:.1f})")
    print("판정: 같은 시드끼리 짝지어 뺀 차이가 시드마다 부호가 같고, "
          "그 평균이 시드별 차이의 폭보다 크면 실효")
    print("범주형은 자기를 켜 주는 연속 θ 를 깐 베이스와 비교한다 (base 열)\n")
    print(f"{'케이스':<28}{'base':<14}{'Δ tasks/h':>11}{'Δ%':>8}"
          f"{'Δ폭':>8}{'Δ 리드평균':>12}  판정")
    print("-" * 100)

    def paired(r, key=PRIMARY):
        """베이스와 같은 시드끼리 뺀 차이 목록. 시드 변동이 상쇄된다."""
        base = by_case.get(r.get("base", "neutral"))
        if base is None or "_per_seed" not in base or "_per_seed" not in r:
            return None
        shared = sorted(set(base["_per_seed"]) & set(r["_per_seed"]))
        if not shared:
            return None
        return [r["_per_seed"][s][key] - base["_per_seed"][s][key] for s in shared]

    effective = []
    ranked = [r for r in rows if r.get("n_ok") and r["case"] != "neutral"]
    ranked.sort(key=lambda r: -abs(statistics.fmean(paired(r) or [0.0])))
    for r in ranked:
        diffs = paired(r)
        if diffs is None:
            continue
        mean_d = statistics.fmean(diffs)
        spread_d = max(diffs) - min(diffs)
        lead_d = statistics.fmean(paired(r, "lead_mean_s") or [0.0])
        base_mean = by_case[r.get("base", "neutral")][f"mean_{PRIMARY}"]
        # 판정: 시드마다 부호가 같고(일관된 방향), 평균 차이가 시드별 차이의
        # 폭보다 크면 파라미터가 만든 것으로 본다. 부호가 갈리면 시드 운이다.
        same_sign = all(d > 0 for d in diffs) or all(d < 0 for d in diffs)
        signal = same_sign and abs(mean_d) > spread_d
        if signal and r["case"] != "uniform":
            effective.append(r["param"])
        verdict = "실효" if signal else ("방향만 일관" if same_sign else "잡음")
        print(f"{r['case']:<28}{r.get('base', '-'):<14}{mean_d:>+11.1f}"
              f"{mean_d / base_mean * 100:>+7.1f}%{spread_d:>8.1f}"
              f"{lead_d:>+12.1f}  {verdict}")

    uni = by_case.get("uniform")
    if uni:
        gap = uni[f"mean_{PRIMARY}"] - ref
        ok = abs(gap) < 1e-9
        print(f"\n중립 θ vs uniform 차이 {gap:+.1f} — "
              f"{'일치 ✅' if ok else '★불일치 — θ 스키마 합의안 §중립 θ 위반'}")

    names = sorted(set(effective))
    print(f"\n실효 θ {len(names)}개: {', '.join(names) if names else '없음'}")
    all_theta = set(THETA_CONTINUOUS_RANGES) | set(THETA_CATEGORICAL_VALUES)
    dead = sorted(all_theta - set(names))
    print(f"잡음 이하 {len(dead)}개: {', '.join(dead) if dead else '없음'}")
    print("\n※ 잡음 이하 = 이 조건에서 1차 효과가 안 보인다는 뜻이지 "
          "'빼도 된다'가 아니다 (배타 선점·상호작용). 축소는 BO 결과와 함께 판단.")
    if not names:
        print("→ 이 조건에서는 θ 가 처리량을 움직이지 않는다. 부하·목적함수를 "
              "다시 잡아야 한다 (order_gap 25·28대, 리드타임 계열 지표).")


def save_csv(rows, args, seeds):
    os.makedirs(args.out, exist_ok=True)
    # aisle_block 을 빼면 조건이 다른 실행이 같은 파일을 덮어쓴다 (실측 사고).
    name = (f"theta_sensitivity_r{args.robots}_o{args.orders}"
            f"_g{args.order_gap:g}_blk{args.aisle_block}"
            f"{'_h' if args.heading else '_cell'}.csv")
    path = os.path.join(args.out, name)
    # seeds_* 는 시드별 원값(| 구분). 짝지은 재분석을 CSV 만으로 다시 할 수 있게
    # 남긴다 — 평균만 남기면 판정 기준을 바꿀 때마다 시뮬을 다시 돌려야 한다.
    fields = ["case", "base", "param", "value", "n_ok"] + \
             [f"{stat}_{m}" for m in METRICS
              for stat in ("mean", "spread", "seeds")]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"\nCSV → {path}")


if __name__ == "__main__":
    sys.exit(main())
