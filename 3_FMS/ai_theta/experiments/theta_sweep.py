# -*- coding: utf-8 -*-
"""합성 창고 θ 일괄 탐색 (계약 v3.6).

창고 하나 = 프로세스 하나다. objective.evaluate 가 시드를 **순차로** 돌아
(objective.py:118) study 안에는 병렬이 없다 — 코어를 다 쓰려면 창고끼리 던져야 한다.

부하는 대수에 비례해 준다. 권장 대수가 이미 칸당 밀도를 맞춘 값(free÷81)이라
부하까지 맞춰야 창고 사이에 **기하 차이만** 남는다. 고정 900건/h 를 13대 창고에
주면 포화해서 θ 가 뭘 해도 같은 값이 나온다.

대상은 README 표의 θ 열이 O 인 85개다. 나머지 27개는 권장 대수가 12~24 밖이라
-138 실효 판정 자체가 안 선다.

## --aisle-block 이 이 실험의 핵심 손잡이다

기본값 1(랙 사이 통로 = 피커 전용, 로봇 통행 금지)에서는 **로봇이 다니는 공간이
바깥 사각 링 하나**다. 합성 창고가 바꾸는 세 인자(통로 개수·간격·길이)는 전부
로봇이 못 들어가는 랙 블록 안이라, AMR 관점에서는 **링의 둘레만 늘었다 줄었다 한다**
(실측: r6p5l17 통행칸 1050 ↔ r16p8l29 2601 인데 모양은 둘 다 두께 고정 사각 링).
링에서 A→B 는 시계/반시계 둘뿐이라 θ 가 고를 것이 거의 없다.

`--aisle-block 0` 을 주면 랙 사이 통로가 열려 통로 6개짜리와 16개짜리가 **진짜로 다른
경로망**이 된다. 그래야 "창고 기하가 θ 를 바꾸는가" 를 지형 차이로 물을 수 있다.
운영 조건은 1 이므로 그렇게 뽑은 θ 를 쓰지는 않는다 — **원인을 가르는 실험**이다.

통로를 열면 `aisle_*` 4개가 살아난다. aisle_block=1 에서는 from_theta 의 통로 rank
구간이 차단 구간과 겹쳐 비트 단위로 무효라 중립 고정하지만(계약 §5), 열면 일을 한다.
그래서 탐색 축이 7개 → 11개가 되고, 같은 trial 수면 더 성기게 훑는다(--trials 를 올릴 것).
"""
import argparse
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor


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
SYNTH = os.path.join(FMS, "map", "synth")
WORKER = os.path.join(FMS, "infra", "worker")

# -194 기준 조건. 대수만 창고마다 다르고 부하는 그 대수에 맞춰 환산한다.
REF_ROBOTS, REF_ARRIVAL_S = 20, 4.0                      # 20대 · 900건/h
SPEED, CAPACITY, SEEDS = 0.838, 6, "42,43,44"
# aisle_block=1 에서 무효라 중립 고정하는 4개 (계약 §5). 통로를 열면 비운다.
DEAD_WHEN_BLOCKED = "aisle_alt_gain,aisle_alt_boost,aisle_period,aisle_phase"

ROW = re.compile(r"^\|\s*.(r\d+p\d+l\d+).\s*\|")


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


def tag(name, fleet, block):
    """study 이름. 통로를 연 실행은 _open 을 붙여 섞이지 않게 한다."""
    return "synth_%s_r%d_c6_v36%s" % (name, fleet, "" if block else "_open")


def command(name, fleet, out_dir, trials, orders, block):
    arrival = REF_ARRIVAL_S * REF_ROBOTS / fleet         # 대수당 부하를 고정한다
    return [sys.executable, "run_study.py",
            "--study", tag(name, fleet, block),
            "--map-dir", os.path.join(SYNTH, name),
            "--robots", str(fleet), "--orders", str(orders), "--trials", str(trials),
            "--seeds", SEEDS, "--capacity", str(CAPACITY), "--speed", "%g" % SPEED,
            "--arrival-s", "%.4f" % arrival,
            "--aisle-block", str(block),
            # 통로를 열면 aisle_* 4개가 살아난다 → 탐색 축 7 → 11
            "--exclude", DEAD_WHEN_BLOCKED if block else "",
            "--sim-engine", os.path.join(FMS, "sim_engine"), "--fms-root", FMS,
            "--out", os.path.join(out_dir, name)]


def run(job, out_dir, trials, orders, block):
    name, fleet = job[0], job[1]
    theta = os.path.join(out_dir, name, "theta_%s.json" % tag(name, fleet, block))
    if os.path.exists(theta):
        return name, 0.0, "건너뜀 (이미 있음)"
    env = dict(os.environ, SIM_NO_PLOT="1", PYTHONIOENCODING="utf-8",
               OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    env.pop("OPTUNA_STORAGE", None)                      # study 끼리 완전히 독립
    os.makedirs(os.path.join(out_dir, name), exist_ok=True)
    log = os.path.join(out_dir, name, "run.log")
    t = time.time()
    with open(log, "w", encoding="utf-8") as f:
        rc = subprocess.run(command(name, fleet, out_dir, trials, orders, block),
                            cwd=WORKER, env=env, stdout=f,
                            stderr=subprocess.STDOUT).returncode
    return name, time.time() - t, "OK" if rc == 0 else "실패 rc=%d → %s" % (rc, log)


def main():
    p = argparse.ArgumentParser(description="합성 창고 θ 일괄 탐색")
    p.add_argument("--jobs", type=int, default=64)
    p.add_argument("--trials", type=int, default=150,
                   help="통로를 열면(--aisle-block 0) 축이 11개라 200~250 권장")
    p.add_argument("--orders", type=int, default=250)
    p.add_argument("--aisle-block", type=int, default=1, choices=(0, 1), dest="aisle_block",
                   help="1=랙 통로 차단(운영 조건). 0=개방 — 기하가 θ 를 바꾸는지 가르는 실험")
    p.add_argument("--out", default=None, help="기본: infra/out/synth_v36[_open]")
    p.add_argument("--limit", type=int, default=0, help="앞에서 N 개만 (연습용)")
    p.add_argument("--all", action="store_true", help="θ 판정 불가 27개도 포함")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    if a.out is None:
        a.out = os.path.join(FMS, "infra", "out",
                             "synth_v36" if a.aisle_block else "synth_v36_open")

    jobs = [w for w in warehouses() if a.all or w[3]]
    # 대수 많은 창고가 느리다(런당 시뮬 시간이 길다). 긴 것을 먼저 던져야 꼬리가 짧다.
    jobs.sort(key=lambda w: -w[1])
    if a.limit:
        jobs = jobs[:a.limit]
    os.makedirs(a.out, exist_ok=True)
    print("창고 %d개 · 동시 %d · trial %d · 탐색축 %d개"
          % (len(jobs), a.jobs, a.trials, 7 if a.aisle_block else 11))
    print("랙 통로 %s · 출력 %s"
          % ("차단 (운영 조건)" if a.aisle_block else "**개방** (원인 판별 실험)", a.out))
    if a.dry_run:
        for w in jobs[:2]:
            print("  " + " ".join(command(w[0], w[1], a.out, a.trials, a.orders, a.aisle_block)))
        return 0

    t0, done = time.time(), 0
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        for name, el, msg in pool.map(
                lambda w: run(w, a.out, a.trials, a.orders, a.aisle_block), jobs):
            done += 1
            print("[%3d/%d] %-12s %5.1f분  %s   (경과 %.0f분)"
                  % (done, len(jobs), name, el / 60, msg, (time.time() - t0) / 60), flush=True)
    print("\n끝. 총 %.0f분" % ((time.time() - t0) / 60))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
