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
# 시뮬 호출 규약은 contracts/SIM_RUN_CONTRACT.md v2 가 단일 출처다. 기본값은
# 그 문서 §5 "θ 탐색 권장 조건"(헤딩 = v2 기본 · order_gap 15 · aisle_block 1)에
# 맞춰 두었다 — 조건을 매번 손으로 적다가 빠뜨리면 기준선과 비교가 안 된다.
#
# 사용 (컨테이너 안, /work 마운트 기준):
#   python /opt/worker/run_study.py --study wallA_r24_g15 \
#       --robots 24 --orders 120 --seeds 42,43,44 --trials 50 \
#       --metric tasks_per_h --direction maximize --out /work/infra/out
#
# 합성 창고(S15P21A106-139)를 탐색하려면 --map-dir 를 준다. 대수는 창고마다 달라야 한다 —
# 크기가 다른 창고에 같은 대수를 넣으면 측정된 θ 차이가 기하 때문인지 혼잡도 때문인지
# 갈리지 않는다 (θ 는 막힐 때 일하는 규칙, 감도 실험 §0). 권장 대수는 map/synth/README.md 표.
#   python /opt/worker/run_study.py --study r11p6l21_r20_g15 \
#       --map-dir /work/map/synth/r11p6l21 --robots 20 --orders 120 ...
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

# 계약 §1: v1compat 은 A* 패리티 전용이라 θ 탐색에 쓰지 않는다. 선택지로
# 열어두면 언젠가 쓰이므로 아예 상수로 고정하고, 기록만 meta 에 남긴다.
FLOW = "main"

# 계약 §1: 공식 맵 wallA 의 충전 존 초기 배치 상한. 넘기면 시뮬이 assert 로 죽는데,
# 그때는 이미 컨테이너·DB 가 다 뜬 뒤다. 인자 파싱에서 먼저 끊는다.
# 합성 창고는 존 크기가 창고마다 달라(24~42대) 이 상수를 못 쓴다 — --map-dir 이 있으면
# 그 맵의 존에서 직접 센다 (charge_zone_capacity, S15P21A106-183).
MAX_ROBOTS = 28


def _relative_to(path, root):
    """`root` 아래면 상대 경로(슬래시), 아니면 절대 경로 그대로."""
    try:
        rel = os.path.relpath(path, os.path.abspath(root))
    except ValueError:                                  # 윈도우: 드라이브가 다르면
        return path
    return path if rel.startswith("..") else rel.replace(os.sep, "/")


def charge_zone_capacity(map_dir, sim_engine_dir, limit=MAX_ROBOTS * 4):
    """맵 세트의 충전 존이 간격 2 로 앉힐 수 있는 최대 로봇 수.

    시뮬과 같은 로더·같은 배치 규칙(map_loader.make_homes_zone)을 쓴다. 여기서 따로
    세면 워커가 통과시킨 대수를 시뮬이 거부하는 일이 생긴다.
    """
    if sim_engine_dir not in sys.path:
        sys.path.insert(0, sim_engine_dir)
    from map_loader import load_charge_zone, load_map, make_homes_zone
    free = load_map(map_dir, aisle_block=True)[0]
    zone = load_charge_zone(free, map_dir)
    if zone is None:
        return 0
    zone = zone & free
    cap = 0
    for n in range(2, limit + 1):
        try:
            make_homes_zone(free, zone, n)
        except AssertionError:
            break
        cap = n
    return cap


def load_theta_space(fms_root):
    """계약에서 θ 탐색 범위와 중립값을 읽어온다."""
    if fms_root not in sys.path:
        sys.path.insert(0, fms_root)
    from contracts.guidance_types import (GuidanceTheta,
                                          THETA_CATEGORICAL_VALUES,
                                          THETA_CONTINUOUS_RANGES,
                                          THETA_SCHEMA_VERSION)
    neutral = GuidanceTheta.neutral()
    neutral_values = {n: getattr(neutral, n) for n in
                      list(THETA_CONTINUOUS_RANGES) + list(THETA_CATEGORICAL_VALUES)}
    return (THETA_CONTINUOUS_RANGES, THETA_CATEGORICAL_VALUES,
            THETA_SCHEMA_VERSION, neutral_values)


def suggest_theta(trial, continuous, categorical, pinned):
    """θ 11개. pinned 에 있는 이름은 제안하지 않고 그 값으로 고정한다.

    θ 스키마는 11개를 다 요구하므로(계약 guidance_types) 제외한 파라미터도
    값은 있어야 한다. 중립값으로 고정해 "탐색하지 않음"과 "없음"을 구분한다 —
    Optuna 에 제안시키면 평평한 축을 헤매고, 빼 버리면 θ json 이 스키마를 어긴다.
    """
    theta = {name: pinned[name] if name in pinned
             else trial.suggest_float(name, lo, hi)
             for name, (lo, hi) in continuous.items()}
    theta.update({name: pinned[name] if name in pinned
                  else trial.suggest_categorical(name, list(values))
                  for name, values in categorical.items()})
    return theta


def make_objective(args, continuous, categorical):
    def objective(trial):
        theta = suggest_theta(trial, continuous, categorical, args.pinned)
        try:
            result = evaluate(theta, args.sim_engine, args.robots, args.orders,
                              args.seeds, timeout_s=args.timeout,
                              aisle_block=args.aisle_block, flow=FLOW,
                              cell=args.cell, order_gap=args.order_gap,
                              extra_args=args.extra_args,
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


def dump_best(study, args, schema_version, neutral_names):
    """최적 θ 를 sim_v2 --theta 가 바로 읽는 형태로 저장한다."""
    if not args.out:
        return None
    os.makedirs(args.out, exist_ok=True)
    # best_trial.params 에는 고정한 θ 가 없다. 스키마 11개를 채워야 한다.
    theta = {**args.pinned, **study.best_trial.params}
    for name in ("aisle_period", "aisle_phase", "loop_dir"):
        if name in theta:
            theta[name] = int(theta[name])

    theta_path = os.path.join(args.out, f"theta_{args.study}.json")
    with open(theta_path, "w", encoding="utf-8") as f:
        json.dump(theta, f, ensure_ascii=False, indent=1)

    meta = {
        "study": args.study,
        "theta_schema_version": schema_version,
        # 조건은 θ 를 재현하는 데 필요한 전부다 — 이 dict 로 계약 §6 호출을
        # 그대로 복원할 수 있어야 한다.
        # map_dir 은 어느 창고에서 뽑은 θ 인지다. 빠지면 그 θ 는 재현도 해석도 안 된다
        # (합성 창고 도입, S15P21A106-183). 공식 맵이면 키가 안 붙어 기존 meta 와 같다.
        "condition": {"robots": args.robots, "orders": args.orders,
                      "seeds": args.seeds, "aisle_block": args.aisle_block,
                      "flow": FLOW, "cell": args.cell,
                      "order_gap": args.order_gap,
                      **({"map_dir": args.map_ref} if args.map_ref else {})},
        # 어떤 축을 탐색했는지 남긴다. 고정한 θ 도 값은 theta json 에 들어가므로
        # 이 목록이 없으면 "탐색해서 중립이 나온 것"과 구분되지 않는다.
        "search_space": {"pinned_neutral": sorted(args.pinned),
                         "searched": sorted(set(neutral_names) - set(args.pinned))},
        "sim_run_contract": "v2",
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
    # 계약 §1: aisle_block=1(랙 사이 통로 = 피커 전용)이 기준선이다.
    p.add_argument("--aisle-block", type=int, default=1, choices=(0, 1),
                   dest="aisle_block", help="1=랙 통로 로봇 통행 금지(기준선)")
    # 계약 v2: 헤딩이 기본이고 칸 모델이 --cell opt-in 이다. --cell 은 예비
    # 조사처럼 값이 싼 실행에만 쓴다 — 본 탐색은 헤딩으로 한다(계약 §5).
    p.add_argument("--cell", action="store_true",
                   help="칸 모델(점로봇). 기본은 헤딩 PIBT")
    # 138 감도 실험: aisle 계열 4개는 aisle_block=1 에서 비트 단위로 무효다
    # (from_theta 의 통로 rank 구간이 통로차단 구간과 같다). 탐색 축으로 두면
    # 100% 낭비이므로 중립 고정이 기본이다. 통로를 여는 실험에서는 비운다.
    p.add_argument("--exclude", default="aisle_alt_gain,aisle_alt_boost,"
                                        "aisle_period,aisle_phase",
                   help="탐색에서 빼고 중립값으로 고정할 θ 이름(쉼표). 빈 문자열이면 전부 탐색")
    p.add_argument("--order-gap", type=float, default=15.0, dest="order_gap",
                   help="주문 도착 간격 평균[틱]. 기본 15(고부하) — "
                        "50은 수요 제약이라 θ 효과가 seed 산포에 묻힌다")
    p.add_argument("--timeout", type=int, default=300, help="시뮬 1회 상한(초)")
    p.add_argument("--noise-warn-ratio", type=float, default=0.05,
                   dest="noise_warn_ratio",
                   help="seed 산포가 목적값의 이 배율을 넘으면 경고")
    # 샘플러 seed 를 고정하면 워커마다 같은 후보를 낸다. 실측(워커 4개 × 5 trial)에서
    # seed=0 으로 파라미터 조합 20개 중 15개가 중복됐다. 병렬에서는 비워 둘 것.
    # 탐색 자체의 재현은 Postgres 에 남는 study 기록으로 한다.
    p.add_argument("--sampler-seed", type=int, default=None, dest="sampler_seed",
                   help="단일 워커 재현용. 병렬로 돌릴 때는 지정하지 말 것")
    # 합성 창고(S15P21A106-139)를 탐색 대상으로 쓸 때만. 생략 = 공식 맵 3_FMS/map.
    p.add_argument("--map-dir", default=None, dest="map_dir",
                   help="맵 세트 폴더. 합성 창고는 map/synth/<이름> "
                        "(권장 대수는 map/synth/README.md 표)")
    p.add_argument("--sim-engine", default=DEFAULT_SIM_ENGINE, dest="sim_engine")
    p.add_argument("--fms-root", default=DEFAULT_FMS_ROOT, dest="fms_root")
    p.add_argument("--out", default="", help="최적 θ·메타 저장 디렉토리")
    args = p.parse_args(argv)
    args.seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    if not args.seeds:
        p.error("--seeds 가 비었다. 시뮬은 확률적이라 시드 3개 이상을 권장한다")
    args.extra_args = ()
    args.map_ref = None
    if args.map_dir is None:
        cap, where = MAX_ROBOTS, "공식 맵 (계약 §1)"
    else:
        args.map_dir = os.path.abspath(args.map_dir)
        if not os.path.isdir(args.map_dir):
            p.error(f"--map-dir 폴더가 없다: {args.map_dir}")
        args.extra_args = (f"--map-dir={args.map_dir}",)
        # meta 에는 fms_root 기준 상대 경로를 적는다. 절대 경로를 박으면 다른 머신·컨테이너에서
        # 그 dict 로 호출을 복원할 수 없다 — meta 의 존재 이유가 그거다.
        args.map_ref = _relative_to(args.map_dir, args.fms_root)
        cap, where = charge_zone_capacity(args.map_dir, args.sim_engine), os.path.basename(args.map_dir)
    if args.robots > cap:
        p.error(f"--robots {args.robots} > 충전 존 용량 {cap} — {where}")
    args.exclude = [n.strip() for n in args.exclude.split(",") if n.strip()]
    return args


def main(argv=None):
    args = parse_args(argv)
    continuous, categorical, schema_version, neutral = load_theta_space(args.fms_root)
    unknown = [n for n in args.exclude if n not in neutral]
    if unknown:
        raise SystemExit(f"--exclude 에 스키마에 없는 이름: {unknown}")
    args.pinned = {n: neutral[n] for n in args.exclude}
    n_search = len(neutral) - len(args.pinned)
    print(f"θ 스키마 v{schema_version} — 연속 {len(continuous)} + 범주 {len(categorical)}")
    if args.pinned:
        print(f"탐색 {n_search}차원 / 중립 고정 {len(args.pinned)}개: "
              f"{', '.join(sorted(args.pinned))}")
    print(f"study {args.study} / 로봇 {args.robots} · 주문 {args.orders} · "
          f"seed {args.seeds} / 목적 {args.direction} {args.metric}")
    print(f"조건 flow={FLOW} · aisle_block={args.aisle_block} · "
          f"{'칸' if args.cell else '헤딩'} 모델 · order_gap={args.order_gap} "
          f"(SIM_RUN_CONTRACT v2)")
    print(f"맵 {os.path.basename(args.map_dir) if args.map_dir else '공식 맵 (3_FMS/map)'}")

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
    path = dump_best(study, args, schema_version, list(neutral))
    if path:
        print(f"최적 θ → {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
