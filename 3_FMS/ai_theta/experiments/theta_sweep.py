# -*- coding: utf-8 -*-
"""합성 창고 θ 일괄 탐색 (계약 v3.6).

창고 하나 = 프로세스 하나다. objective.evaluate 가 시드를 **순차로** 돌아
(objective.py:118) study 안에는 병렬이 없다 — 코어를 다 쓰려면 창고끼리 던져야 한다.

부하는 대수에 비례해 준다. 권장 대수가 이미 칸당 밀도를 맞춘 값(free÷81)이라
부하까지 맞춰야 창고 사이에 **기하 차이만** 남는다. 고정 900건/h 를 13대 창고에
주면 포화해서 θ 가 뭘 해도 같은 값이 나온다.

대상은 README 표의 θ 열이 O 인 85개다. 나머지 27개는 권장 대수가 12~24 밖이라
-138 실효 판정 자체가 안 선다.
"""
import argparse
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
FMS = os.path.abspath(os.path.join(HERE, "..", ".."))   # ai_theta/experiments → 3_FMS          # …/3_FMS
SYNTH = os.path.join(FMS, "map", "synth")
WORKER = os.path.join(FMS, "infra", "worker")

# -194 기준 조건. 대수만 창고마다 다르고 부하는 그 대수에 맞춰 환산한다.
REF_ROBOTS, REF_ARRIVAL_S = 20, 4.0                      # 20대 · 900건/h
SPEED, CAPACITY, SEEDS = 0.838, 6, "42,43,44"

ROW = re.compile(r"^\|\s*`(r\d+p\d+l\d+)`\s*\|")


def warehouses():
    """README 표를 읽는다 — 표도 생성물이라 여기서 다시 세면 어긋난다."""
    out = []
    with open(os.path.join(SYNTH, "README.md"), encoding="utf-8") as f:
        for line in f:
            if not ROW.match(line):
                continue
            col = [c.strip() for c in line.strip().strip("|").split("|")]
            name, fleet, zone, judge = col[0].strip("`"), int(col[6]), int(col[7]), col[8]
            out.append((name, fleet, zone, judge == "O"))
    return out


def command(name, fleet, out_dir, trials, orders):
    arrival = REF_ARRIVAL_S * REF_ROBOTS / fleet         # 대수당 부하를 고정한다
    return [sys.executable, "run_study.py",
            "--study", f"synth_{name}_r{fleet}_c6_v36",
            "--map-dir", os.path.join(SYNTH, name),
            "--robots", str(fleet), "--orders", str(orders), "--trials", str(trials),
            "--seeds", SEEDS, "--capacity", str(CAPACITY), "--speed", f"{SPEED:g}",
            "--arrival-s", f"{arrival:.4f}",
            "--sim-engine", os.path.join(FMS, "sim_engine"), "--fms-root", FMS,
            "--out", os.path.join(out_dir, name)]


def run(job, out_dir, trials, orders):
    name, fleet = job[0], job[1]
    theta = os.path.join(out_dir, name, f"theta_synth_{name}_r{fleet}_c6_v36.json")
    if os.path.exists(theta):
        return name, 0.0, "건너뜀 (이미 있음)"
    env = dict(os.environ, SIM_NO_PLOT="1", PYTHONIOENCODING="utf-8",
               OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    env.pop("OPTUNA_STORAGE", None)                      # study 끼리 완전히 독립
    os.makedirs(os.path.join(out_dir, name), exist_ok=True)
    log = os.path.join(out_dir, name, "run.log")
    t = time.time()
    with open(log, "w", encoding="utf-8") as f:
        rc = subprocess.run(command(name, fleet, out_dir, trials, orders), cwd=WORKER,
                            env=env, stdout=f, stderr=subprocess.STDOUT).returncode
    return name, time.time() - t, "OK" if rc == 0 else f"실패 rc={rc} → {log}"


def main():
    p = argparse.ArgumentParser(description="합성 창고 θ 일괄 탐색")
    p.add_argument("--jobs", type=int, default=64)
    p.add_argument("--trials", type=int, default=150)
    p.add_argument("--orders", type=int, default=250)
    p.add_argument("--out", default=os.path.join(FMS, "infra", "out", "synth_v36"))
    p.add_argument("--limit", type=int, default=0, help="앞에서 N 개만 (연습용)")
    p.add_argument("--all", action="store_true", help="θ 판정 불가 27개도 포함")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()

    jobs = [w for w in warehouses() if a.all or w[3]]
    jobs.sort(key=lambda w: w[1])                        # 대수 적은 = 느린 창고 먼저
    if a.limit:
        jobs = jobs[:a.limit]
    os.makedirs(a.out, exist_ok=True)
    print(f"창고 {len(jobs)}개 · 동시 {a.jobs} · trial {a.trials} · 주문 {a.orders}")
    print(f"출력 {a.out}")
    if a.dry_run:
        for w in jobs[:3]:
            print("  " + " ".join(command(w[0], w[1], a.out, a.trials, a.orders)))
        return 0

    t0, done = time.time(), 0
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        for name, el, msg in pool.map(lambda w: run(w, a.out, a.trials, a.orders), jobs):
            done += 1
            print(f"[{done:3d}/{len(jobs)}] {name:12s} {el/60:5.1f}분  {msg}"
                  f"   (경과 {(time.time()-t0)/60:.0f}분)", flush=True)
    print(f"\n끝. 총 {(time.time()-t0)/60:.0f}분")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
