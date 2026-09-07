# -*- coding: utf-8 -*-
# ============================================================
# Fleet 스윕 공통 골격 (2026-09-07, S15P21A106-149)
#
# fleet_sweep_b0z.py / fleet_sweep_load.py 가 각자 들고 있던 "sim_v2 서브프로세스 실행 → [SUMMARY] 파싱 → STALL 행 처리 →
# CSV → 시드 평균 → matplotlib" 골격을 한 곳으로. 이번 이슈에서는 fleet_sweep_theta.py 만 이 모듈을 쓴다 — 기존 두 스윕은
# 동일성 검사 기준 CSV(b0z_sweep.csv·load_sweep.csv)를 만드는 스크립트라 코드 분리 이슈(계획 ⑥)에서 옮긴다.
#
# 시뮬 호출은 계약(contracts/SIM_RUN_CONTRACT.md v2.3)만 의존한다: CLI 위치 인자 + 플래그, [SUMMARY] JSON, 종료 코드 1 = STALL.
# ============================================================
import csv
import json
import os
import subprocess
import sys
import time

PY = sys.executable
ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ENGINE_DIR)
RES_DIR = os.path.join(ENGINE_DIR, "results")
SIM = os.path.join(ENGINE_DIR, "sim_v2_tasks.py")
ENV = dict(os.environ, SIM_NO_PLOT="1", PYTHONIOENCODING="utf-8")

# CSV 에서 float 로 바꾸지 않는 열 (문자열 열). 스윕별 추가 열은 read_csv(str_keys=...) 로.
STR_KEYS = frozenset({"engine", "variant", "flow", "load", "cond", "theta_file", "shifts"})


def env_list(name, default, cast=int):
    """SWEEP_SEEDS=101,103,104 식 환경변수 → 리스트. 없으면 default."""
    raw = os.environ.get(name)
    if not raw:
        return list(default)
    return [cast(x) for x in raw.split(",") if x.strip()]


def run_sim(tag, n_robots, n_orders, seed, aisle_block, extra=(), stall_dump_prefix="stall"):
    """sim_v2 한 번 실행 → SUMMARY dict (+ wall_s). STALL(exit 1)은 정보다 — stall=1 행으로 돌려주고 덤프를 results/ 에 남긴다.

    stall 행은 SUMMARY 키가 없으므로 호출자가 cond/load 같은 열을 덧붙인 뒤 CSV 로 쓴다 (빈 칸은 그래프에서 제외)."""
    t0 = time.perf_counter()
    cmd = [PY, SIM, tag, str(n_robots), str(n_orders), str(seed), str(aisle_block), *extra]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", env=ENV)
    wall = round(time.perf_counter() - t0, 1)
    line = next((ln for ln in r.stdout.splitlines() if ln.startswith("[SUMMARY]")), None)
    if line is not None:
        rec = json.loads(line[len("[SUMMARY] "):])
        rec["wall_s"] = wall
        return rec
    stall = next((ln for ln in r.stdout.splitlines() if ln.startswith("[STALL]")), None)
    assert stall, (f"실행 실패 {' '.join(cmd[2:])}:\n{r.stdout[-3000:]}\n{r.stderr[-2000:]}")
    suffix = "_".join(x.lstrip("-").replace("=", "").replace("/", "-").replace("\\", "-") for x in extra)[:60]
    dump = os.path.join(RES_DIR, f"{stall_dump_prefix}_r{n_robots}_o{n_orders}_s{seed}_{suffix}.txt")
    with open(dump, "w", encoding="utf-8") as f:
        f.write(" ".join(cmd) + "\n\n" + r.stdout + r.stderr)
    print(f"  [STALL] r={n_robots} seed={seed} {extra}: {stall[:70]} → {os.path.basename(dump)}", flush=True)
    return dict(variant=tag, n_robots=n_robots, n_orders=n_orders, seed=seed, aisle_block=aisle_block,
                stall=1, stall_t=int(stall.split("t=")[1].split(",")[0]), wall_s=wall)


def is_stall(row):
    return str(row.get("stall", "")) not in ("", "0", "0.0")


def read_csv(path, str_keys=STR_KEYS):
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            for k, v in r.items():
                if v != "" and k not in str_keys:
                    r[k] = float(v)
            rows.append(r)
    return rows


def write_csv(path, rows):
    fields = sorted({k for r in rows for k in r})
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def values(rows, key, **match):
    """match 열이 전부 일치하고 key 가 비어 있지 않은(STALL 아닌) 행의 key 값 목록."""
    out = []
    for r in rows:
        if not all(_match(r.get(k, ""), v) for k, v in match.items()):
            continue
        v = r.get(key, "")
        if v != "" and not is_stall(r):
            out.append(float(v))
    return out


def _match(a, b):
    """문자열이 같거나(load="L2"), 숫자로 같으면(n_robots 24 vs "24.0") 일치."""
    if str(a) == str(b):
        return True
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return False


def mean_series(rows, key, xs, xkey="n_robots", **match):
    """xs 각 값에서 match 행들의 key 시드 평균 (행 없으면 nan)."""
    import numpy as np
    return [float(np.mean(v)) if (v := values(rows, key, **{xkey: x}, **match)) else float("nan") for x in xs]


def spread_series(rows, key, xs, xkey="n_robots", **match):
    """xs 각 값에서 (min, max) — 시드 산포 밴드."""
    out = []
    for x in xs:
        v = values(rows, key, **{xkey: x}, **match)
        out.append((min(v), max(v)) if v else (float("nan"), float("nan")))
    return out


def setup_plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.family"] = "Malgun Gothic"
    plt.rcParams["axes.unicode_minus"] = False
    return plt


def out_paths(default_csv, stem_prefix):
    """SWEEP_OUT 규약: 기본 CSV 이름이면 접미 없음, 다른 이름이면 그 접미를 PNG 에도 붙인다 (load_sweep_eval → _eval)."""
    csv_name = os.path.basename(os.environ.get("SWEEP_OUT", default_csv))
    stem = os.path.splitext(csv_name)[0]
    tag = stem[len(stem_prefix):] if stem.startswith(stem_prefix) else "_" + stem
    return os.path.join(RES_DIR, csv_name), tag
