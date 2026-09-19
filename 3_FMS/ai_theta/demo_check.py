# -*- coding: utf-8 -*-
"""예측 θ 를 로컬에서 바로 확인한다 — 시연용 (S15P21A106-206).

맵 이름을 주면 **그 자리에서** θ 를 예측하고(0.1초), 고정 θ 와 나란히 시뮬에 넣어 비교한다.
서버도 도커도 필요 없다 — `sim_engine/` 이 로컬에서 그냥 돈다.

    python ai_theta/demo_check.py r14p7l17
    python ai_theta/demo_check.py r14p7l17 r13p5l17 --seeds 5 --jobs 10

## 무엇을 비교하나

    예측 θ   모델이 맵 특징을 보고 뽑은 값        (0.1초)
    고정 θ   theta_wallA_r20_c6_v36.json        (지금 운영이 쓰는 값)

**교착은 처리량 0 으로 센다.** 멈춘 런을 빼고 비교하면 "안 멈추는 것" 이 목적인 실험에서
벌점이 사라진다. 지표는 `기대 처리량 = 완주율 x 완주시 처리량` 이다.

## 조건

개방(`aisle_block=0`) — 모델이 그 조건에서 학습했다. 운영(차단)에는 완주 데이터가 없어
아직 쓸 수 없다. 평가 시드는 {103,104,105,107,109} 로 학습 시드 101 과 분리한다.

## 타임아웃

완주 런이 7~18초라 120초면 넉넉하다. 교착 런은 거기서 끊고 '멈춤' 으로 센다 — 어차피
멈출 런이라 결과가 같고, 시연 중에 400초를 기다릴 수는 없다.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
FMS = os.path.abspath(os.path.join(HERE, ".."))
SIM = os.path.join(FMS, "sim_engine")
SYNTH = os.path.join(FMS, "map", "synth")
OUT = os.path.join(FMS, "infra", "out")
FIXED = os.path.join(OUT, "theta_wallA_r20_c6_v36.json")
MODEL = os.path.join(HERE, "model", "theta_model.joblib")
SEEDS = [103, 104, 105, 107, 109]
SPEED, CAPACITY = 0.838, 6

sys.path.insert(0, SIM)
sys.path.insert(0, HERE)
from map_loader import CELL_M          # noqa: E402
from pibt_core import MOVE_TICKS       # noqa: E402
import predict as theta_predict        # noqa: E402

DT = CELL_M / (SPEED * MOVE_TICKS)


def orders_for(rate, orders_max=250, hours=1.0, floor=100):
    """학습 데이터를 만든 식과 같아야 한다 — 주문 수가 다르면 다른 조건이다."""
    return max(floor, min(orders_max, round(rate * hours)))


def sim(w, theta_path, seed, timeout):
    rate = float(w["cap"]) * float(w["load_frac"])
    cmd = [sys.executable, "sim_v2_tasks.py", "vf", str(int(w["fleet"])),
           str(orders_for(rate)), str(seed), "0",          # 마지막 0 = 랙 통로 개방
           "--order-gap=%.4f" % ((3600.0 / rate) / DT), "--capacity=%d" % CAPACITY,
           "--speed=%g" % SPEED, "--map-dir=" + os.path.join(SYNTH, w["name"]),
           "--theta=" + os.path.abspath(theta_path)]
    env = dict(os.environ, SIM_NO_PLOT="1", PYTHONIOENCODING="utf-8",
               OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    try:
        p = subprocess.run(cmd, cwd=SIM, env=env, capture_output=True, text=True,
                           encoding="utf-8", timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    if p.returncode == 0:
        for line in (p.stdout or "").splitlines():
            if line.startswith("[SUMMARY] "):
                return json.loads(line[10:])["tasks_per_h"]
    return None


def main():
    p = argparse.ArgumentParser(description="예측 θ vs 고정 θ 로컬 확인")
    p.add_argument("maps", nargs="+", help="합성 창고 이름 (예: r14p7l17)")
    p.add_argument("--seeds", type=int, default=5)
    p.add_argument("--jobs", type=int, default=10)
    p.add_argument("--timeout", type=int, default=120)
    p.add_argument("--model", default=MODEL)
    p.add_argument("--load-frac", type=float, default=1.0, dest="load_frac")
    a = p.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    design = theta_predict._design()
    work = os.path.join(OUT, "theta_demo")
    os.makedirs(work, exist_ok=True)

    plan = []
    for name in a.maps:
        w = design.get(name)
        if w is None:
            print("%s — 설계표에 없다. 건너뛴다" % name)
            continue
        w = dict(w, load_frac=a.load_frac)
        t0 = time.time()
        feat = theta_predict.features_from_name(name, fleet=w["fleet"],
                                                load_frac=a.load_frac)
        th = theta_predict.predict(feat, model_path=a.model)
        dt = time.time() - t0
        if th is None:
            print("%s — 예측 실패" % name)
            continue
        path = theta_predict.write_theta(th, os.path.join(work, name))
        print("%-12s 예측 %.2f초 · 모델이 본 완주확률 %.0f%%"
              % (name, dt, 100 * th["_pred_complete"]))
        print("             loop_gain %.2f · wait_cost %.2f · loop_dir %d"
              % (th["loop_gain"], th["wait_cost"], th["loop_dir"]))
        plan.append((w, path))

    if not plan:
        return 1
    seeds = SEEDS[:a.seeds]
    jobs = [(w, lab, th, s) for w, pred in plan
            for lab, th in (("예측 θ", pred), ("고정 θ", FIXED)) for s in seeds]
    print("\n런 %d개 · 동시 %d · 시드 %s · 개방 조건 · 타임아웃 %d초"
          % (len(jobs), a.jobs, seeds, a.timeout))

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        res = list(pool.map(lambda j: sim(j[0], j[2], j[3], a.timeout), jobs))
    print("  %.0f초" % (time.time() - t0))

    print("\n%-12s%10s%12s%14s%12s" % ("창고", "θ", "완주율", "완주시 처리량", "기대 처리량"))
    print("-" * 62)
    tot = {}
    for w, _ in plan:
        for lab in ("예측 θ", "고정 θ"):
            v = [r for (jw, jl, _, _), r in zip(jobs, res)
                 if jw["name"] == w["name"] and jl == lab]
            okv = [x for x in v if x is not None]
            rate = len(okv) / len(v)
            mean = sum(okv) / len(okv) if okv else 0.0
            exp = rate * mean
            tot.setdefault(lab, []).append(exp)
            print("%-12s%10s%11.0f%%%14.1f%12.1f"
                  % (w["name"] if lab == "예측 θ" else "", lab, 100 * rate, mean, exp))
    print("-" * 62)
    pe, fx = sum(tot["예측 θ"]) / len(plan), sum(tot["고정 θ"]) / len(plan)
    print("%-12s%10s%25s%12.1f" % ("평균", "예측 θ", "", pe))
    print("%-12s%10s%25s%12.1f" % ("", "고정 θ", "", fx))
    if fx > 0:
        print("\n  기대 처리량 %+.1f%%" % (100 * (pe - fx) / fx))
    print("  * 창고 %d개짜리 표본이다 — 홀드아웃 20창고 실측은 +40.9%% (15/20, p=0.041)"
          % len(plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
