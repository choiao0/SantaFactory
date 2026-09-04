# -*- coding: utf-8 -*-
# ============================================================
# Optuna θ 탐색 워커 (S15P21A106-127)
#
# 창고 × 운영조건 하나 = study 하나. 워커를 여러 개 띄워 같은 study 에 붙이면
# 병렬로 탐색한다 (Postgres storage 가 조정한다).
#
# θ 탐색 범위는 contracts/guidance_types.py 를 **읽어서** 쓴다. 여기에 다시
# 적으면 계약과 어긋난다 — 122 에서 범위를 계약으로 승격한 이유가 그것이다.
# 범주형은 반드시 suggest_categorical 이다 (명세 §11-2: 소수로 뽑고 반올림 금지).
#
# 접속 URL 은 compose 가 넣어주는 OPTUNA_STORAGE 환경변수에서 읽는다. 자격증명을
# 인자나 소스에 적지 않는다 (.env 로 관리 — infra/.env.example 참고).
#
# 사용 (컨테이너 안, /work 마운트 기준):
#   python /opt/worker/run_study.py --study wallA_r10_o40 \
#       --robots 10 --orders 40 --seeds 42,43,44 --trials 50 \
#       --metric tasks_per_h --direction maximize --out /work/infra/out
# ============================================================
import argparse
import json
import os
import sys

import optuna

_WORKER_DIR = os.path.dirname(os.path.abspath(__file__))
if _WORKER_DIR not in sys.path:
    sys.path.insert(0, _WORKER_DIR)

from objective import SimFailed, evaluate  # noqa: E402

DEFAULT_SIM_ENGINE = "/work/sim_engine"
DEFAULT_FMS_ROOT = "/work"


def load_theta_space(fms_root):
    """계약에서 θ 탐색 범위를 읽어온다."""
    if fms_root not in sys.path:
        sys.path.insert(0, fms_root)
    from contracts.guidance_types import (THETA_CATEGORICAL_VALUES,
                                          THETA_CONTINUOUS_RANGES,
                                          THETA_SCHEMA_VERSION)
    return THETA_CONTINUOUS_RANGES, THETA_CATEGORICAL_VALUES, THETA_SCHEMA_VERSION


def suggest_theta(trial, continuous, categorical):
    theta = {name: trial.suggest_float(name, lo, hi)
             for name, (lo, hi) in continuous.items()}
    theta.update({name: trial.suggest_categorical(name, list(values))
                  for name, values in categorical.items()})
    return theta


def make_objective(args, continuous, categorical):
    def objective(trial):
        theta = suggest_theta(trial, continuous, categorical)
        try:
            result = evaluate(theta, args.sim_engine, args.robots, args.orders,
                              args.seeds, timeout_s=args.timeout,
                              aisle_block=args.aisle_block, flow=args.flow,
                              tag=f"bo{trial.number}")
        except SimFailed as exc:
            # 시뮬이 못 끝나는 θ 도 정보다 — 버리지 말고 기록하고 가지치기한다.
            trial.set_user_attr("sim_failed", str(exc))
            raise optuna.TrialPruned(str(exc)) from exc

        # 목적값 외 KPI 전부 보관. 목적함수를 나중에 바꿔도 재실행이 필요 없다.
        for key, value in result["mean"].items():
            trial.set_user_attr(f"mean_{key}", value)
        for key, value in result["spread"].items():
            trial.set_user_attr(f"spread_{key}", value)
        trial.set_user_attr("n_seeds", len(args.seeds))

        value = result["mean"][args.metric]
        spread = result["spread"][args.metric]
        # 산포가 목적값 자체보다 크면 그 trial 의 순위는 seed 운이다.
        if spread > abs(value) * args.noise_warn_ratio:
            print(f"  [주의] trial {trial.number}: {args.metric} 평균 {value:.3f} / "
                  f"seed 산포 {spread:.3f} — 신호가 잡음에 묻힐 수 있음")
        return value

    return objective


def dump_best(study, args, schema_version):
    """최적 θ 를 sim_v2 --theta 가 바로 읽는 형태로 저장한다."""
    if not args.out:
        return None
    os.makedirs(args.out, exist_ok=True)
    theta = dict(study.best_trial.params)
    for name in ("aisle_period", "aisle_phase", "loop_dir"):
        if name in theta:
            theta[name] = int(theta[name])

    theta_path = os.path.join(args.out, f"theta_{args.study}.json")
    with open(theta_path, "w", encoding="utf-8") as f:
        json.dump(theta, f, ensure_ascii=False, indent=1)

    meta = {
        "study": args.study,
        "theta_schema_version": schema_version,
        "condition": {"robots": args.robots, "orders": args.orders,
                      "seeds": args.seeds, "aisle_block": args.aisle_block,
                      "flow": args.flow},
        "objective": {"metric": args.metric, "direction": args.direction,
                      "value": study.best_value},
        "n_trials": len(study.trials),
        "best_trial": study.best_trial.number,
        "best_user_attrs": study.best_trial.user_attrs,
    }
    with open(os.path.join(args.out, f"meta_{args.study}.json"), "w",
              encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    return theta_path


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Optuna θ 탐색 워커")
    p.add_argument("--study", required=True, help="study 이름 = 창고×운영조건 식별자")
    p.add_argument("--storage", default=os.environ.get("OPTUNA_STORAGE"),
                   help="Postgres URL. 생략하면 메모리 (병렬·재현 불가)")
    p.add_argument("--trials", type=int, default=50)
    p.add_argument("--robots", type=int, required=True, help="운영조건 n_agents")
    p.add_argument("--orders", type=int, required=True, help="처리할 주문 건수")
    p.add_argument("--seeds", default="42,43,44",
                   help="쉼표 구분. 시뮬이 확률적이라 반복 평균이 필수")
    p.add_argument("--metric", default="tasks_per_h", help="[SUMMARY] 의 키")
    p.add_argument("--direction", default="maximize",
                   choices=("maximize", "minimize"))
    p.add_argument("--aisle-block", type=int, default=0, dest="aisle_block")
    p.add_argument("--flow", default="main", choices=("main", "v1compat"))
    p.add_argument("--timeout", type=int, default=300, help="시뮬 1회 상한(초)")
    p.add_argument("--noise-warn-ratio", type=float, default=0.05,
                   dest="noise_warn_ratio",
                   help="seed 산포가 목적값의 이 배율을 넘으면 경고")
    # 샘플러 seed 를 고정하면 워커마다 같은 후보를 낸다. 실측(워커 4개 × 5 trial)에서
    # seed=0 으로 파라미터 조합 20개 중 15개가 중복됐다. 병렬에서는 비워 둘 것.
    # 탐색 자체의 재현은 Postgres 에 남는 study 기록으로 한다.
    p.add_argument("--sampler-seed", type=int, default=None, dest="sampler_seed",
                   help="단일 워커 재현용. 병렬로 돌릴 때는 지정하지 말 것")
    p.add_argument("--sim-engine", default=DEFAULT_SIM_ENGINE, dest="sim_engine")
    p.add_argument("--fms-root", default=DEFAULT_FMS_ROOT, dest="fms_root")
    p.add_argument("--out", default="", help="최적 θ·메타 저장 디렉토리")
    args = p.parse_args(argv)
    args.seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    return args


def main(argv=None):
    args = parse_args(argv)
    continuous, categorical, schema_version = load_theta_space(args.fms_root)
    print(f"θ 스키마 v{schema_version} — 연속 {len(continuous)} + 범주 {len(categorical)}")
    print(f"study {args.study} / 로봇 {args.robots} · 주문 {args.orders} · "
          f"seed {args.seeds} / 목적 {args.direction} {args.metric}")

    study = optuna.create_study(
        study_name=args.study,
        storage=args.storage or None,
        direction=args.direction,
        load_if_exists=True,
        sampler=optuna.samplers.TPESampler(seed=args.sampler_seed),
    )
    study.optimize(make_objective(args, continuous, categorical),
                   n_trials=args.trials)

    print(f"\n완료 trial {len(study.trials)}개 / "
          f"최적 {args.metric} {study.best_value:.4f} (trial {study.best_trial.number})")
    path = dump_best(study, args, schema_version)
    if path:
        print(f"최적 θ → {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
