# -*- coding: utf-8 -*-
"""기대 처리량 θ 가 처리량 θ 를 이기는가 — 시뮬로 검증한다 (S15P21A106-206).

`optimize_expected.py` 는 **대리 모델 위에서** 두 목적함수를 비교해 이렇게 냈다.

    목적            완주 확률   처리량비   기대 처리량
    처리량만          18.4 %     1.473      0.268
    처리량 x 완주율   89.6 %     1.319      1.182      <- 모델이 4.4배라고 말한다

그런데 저 숫자는 **모델이 모델을 채점한 것**이다. 같은 MLP 두 개로 θ 를 찾고 그 MLP 로
점수를 매겼으니, 모델이 틀린 방향으로 볼록하면 그대로 속는다. 여기서 **실제 시뮬**로 잰다.

## 무엇을 재는가 — 교착을 0 으로 세는 기대 처리량

앞선 대결 스크립트(`theta_open_value.py`, `theta_hybrid_value.py`)는 **둘 다 완주한 시드**만
짝지어 처리량을 비교했다. 그 규칙은 여기서 쓰면 안 된다 — 멈추는 θ 를 벌주는 것이 이 실험의
전부인데, 멈춘 런을 버리면 벌점이 사라진다(짝 부족으로 제외된 창고가 48~58개였던 이유다).

    기대 처리량 = 평균( 완주하면 tasks_per_h · 교착하면 0 )

이 값은 시드마다 항상 정의되므로 짝이 빠지지 않는다. 완주율과 완주 시 처리량도 따로 낸다 —
"완주율은 올랐는데 처리량을 얼마나 내줬나" 를 봐야 운영 판단이 된다.

## 팔 넷

    tp       처리량만 최적화한 θ          theta_expected_v36.csv 의 tp_* 열
    exp      기대 처리량으로 최적화한 θ    같은 CSV 의 exp_* 열 (= theta_pred_expected/*.json)
    expmean  **그 exp θ 들의 평균 하나**   맵마다 다르게 주지 않고 전부 같은 값을 쓴다
    common   창고 100개 θ 의 평균          theta_open/_hybrid/theta_common.json

`common` 은 지금까지 아무것도 이기지 못한 기준선이다. **exp 가 common 도 못 이기면**
기대 처리량 최적화 역시 값이 없다 — tp 와의 비교만으로는 그걸 못 가린다.

`expmean` 이 진짜 대조군이다. exp 가 common 을 이겨도 그것만으로는 두 가지가 안 갈린다.

    (a) 창고마다 다른 θ 를 준 효과        <- "창고별 예측이 된다"
    (b) 완주율을 목적에 넣은 효과          <- 창고와 무관한 공통 방향

`common` 은 **처리량만 보고 탐색한** θ 들의 평균이라 (b) 를 아예 안 갖고 있다. 그래서
exp − common 은 (a)+(b) 를 같이 잰다. `expmean` 은 (b) 는 갖고 (a) 만 없으므로
**exp − expmean 이 (a) 단독**이다. 이 차이가 묻히면 창고별 θ 는 필요 없고 "완주율을
고려한 고정 θ 하나" 면 된다 — 지금까지 이 프로젝트가 계속 만난 결론과 같은 모양이다.

연속 8축은 산술평균, 범주 3축은 최빈값으로 모은다.

## 시드 — 101 을 빼는 이유

`theta_stall_scan.py` 가 3,000런을 **전부 시드 101** 로 모았고 두 모델이 그걸로 학습했다.
101 로 채점하면 학습 시드를 다시 재는 것이다. 기본 시드는 {103,104,105,107,109} 로 두고,
101 은 `--with-train-seed` 로 따로 붙여 참고용으로만 본다.

`--timeout` 기본값이 400 인 것도 같은 이유다 — 학습 데이터의 '교착' 정의(스캔 때 쓴 값)와
채점의 정의가 같아야 한다.

## 남는 한계 — 30 맵은 in-sample 이다

θ 를 뽑은 맵 30개가 모델 학습에도 쓰인 맵이다. 그래서 이 실험이 답하는 것은
"**이 맵들에서** 곱으로 최적화한 θ 가 실제로 더 나은가" 까지다. 처음 보는 창고로의 일반화는
맵을 빼고 학습하는 LOO 판이 따로 필요하다. 결과가 이기면 그때 하면 된다.
"""
import argparse
import csv
import json
import os
import statistics as st
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from math import comb


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
SIM = os.path.join(FMS, "sim_engine")
SYNTH = os.path.join(FMS, "map", "synth")
OUT = os.path.join(FMS, "infra", "out")
sys.path.insert(0, SIM)
from map_loader import CELL_M          # noqa: E402
from pibt_core import MOVE_TICKS       # noqa: E402

SPEED, CAPACITY = 0.838, 6
DT = CELL_M / (SPEED * MOVE_TICKS)
# theta_stall_scan.py · optimize_expected.py 와 같은 축 목록이어야 한다
CONT = ["aisle_alt_gain", "aisle_alt_boost", "loop_gain", "main_aisle_gain",
        "junction_penalty", "station_in", "station_out", "wait_cost"]
CATS = ["aisle_period", "aisle_phase", "loop_dir"]
ARMS = ("tp", "exp", "expmean", "common", "mlpsamp", "xgb", "poly")
LABEL = {"tp": "처리량만", "exp": "기대 처리량(곱)",
         "expmean": "기대 θ 평균(고정)", "common": "공통 θ",
         # 모델 비교용 — 같은 후보 θ 10만 개를 세 모델에 주고 각자 1등을 고르게 한 것.
         # 최적화 방법을 통일해야 "모델 차이" 와 "최적화 차이" 가 갈린다
         # (exp 는 MLP+경사상승, mlpsamp 는 MLP+샘플링이라 둘 차이가 최적화 효과다).
         "mlpsamp": "MLP(샘플링)", "xgb": "XGBoost", "poly": "2차 다항"}
MIN_ROWS = 20                          # 이보다 적으면 결론을 내지 않는다 (계약 §5)


def orders_for(rate, orders_max=250, hours=1.0, floor=100):
    """theta_open_lhs.py · theta_stall_scan.py 와 **같은 식**이어야 한다."""
    return max(floor, min(orders_max, round(rate * hours)))


def sim(w, theta_path, seed, timeout):
    """완주하면 (1, 처리량), 못 하면 (0, 0.0). rc!=0 · 타임아웃 · SUMMARY 없음이 전부 교착."""
    rate = w["cap"] * w["load_frac"]
    cmd = [sys.executable, "sim_v2_tasks.py", "vf", str(int(w["fleet"])),
           str(orders_for(rate)), str(seed), "0",          # 마지막 0 = 랙 통로 개방
           "--order-gap=%.4f" % ((3600.0 / rate) / DT), "--capacity=%d" % CAPACITY,
           "--speed=%g" % SPEED, "--map-dir=" + os.path.join(SYNTH, w["name"]),
           "--theta=" + theta_path]
    env = dict(os.environ, SIM_NO_PLOT="1", PYTHONIOENCODING="utf-8",
               OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    try:
        p = subprocess.run(cmd, cwd=SIM, env=env, capture_output=True, text=True,
                           encoding="utf-8", timeout=timeout)
    except subprocess.TimeoutExpired:
        return 0, 0.0
    if p.returncode == 0:
        for line in (p.stdout or "").splitlines():
            if line.startswith("[SUMMARY] "):
                return 1, float(json.loads(line[10:])["tasks_per_h"])
    return 0, 0.0


def theta_from_row(row, prefix):
    """CSV 한 줄에서 tp_* / exp_* 열을 골라 θ 한 벌로 만든다."""
    th = {c: float(row[prefix + "_" + c]) for c in CONT}
    th.update({c: int(float(row[prefix + "_" + c])) for c in CATS})
    return th


def theta_mean(rows, prefix):
    """맵별 θ 를 하나로 모은다 — 연속은 산술평균, 범주는 최빈값."""
    th = {c: st.fmean(float(r[prefix + "_" + c]) for r in rows) for c in CONT}
    for c in CATS:
        v = [int(float(r[prefix + "_" + c])) for r in rows]
        th[c] = max(set(v), key=v.count)
    return th


def sign_p(win, n):
    """부호검정 양측 p — 다른 value 스크립트와 같은 식."""
    if n == 0:
        return 1.0
    return min(1.0, sum(comb(n, k) for k in range(max(win, n - win), n + 1)) / 2 ** n * 2)


def paired(rows, x, y, key):
    """맵 단위 짝비교 — (평균 차, 양수 개수, 동점 제외 n, p).

    부호검정은 **동점을 버린다**. 안 버리면 두 비교군이 모든 맵에서 똑같을 때(차이 0)
    '양수 0/30' 이 되어 p 가 1e-09 으로 찍힌다 — 완전히 같다는 결과가 강력한 차이로 뒤집힌다.
    """
    d = [r[key][x] - r[key][y] for r in rows]
    win = sum(1 for v in d if v > 0)
    n = sum(1 for v in d if v != 0)                  # 동점 제외
    return st.fmean(d), win, n, sign_p(win, n)


def main():
    p = argparse.ArgumentParser(description="기대 처리량 θ vs 처리량 θ vs 공통 θ (개방 조건)")
    p.add_argument("--jobs", type=int, default=40)
    p.add_argument("--csv", default=os.path.join(OUT, "theta_expected_v36.csv"),
                   help="optimize_expected.py 가 낸 표 (tp_* · exp_* 열)")
    p.add_argument("--design", default=os.path.join(OUT, "theta_open", "design.json"))
    p.add_argument("--common", default=os.path.join(OUT, "theta_open", "_hybrid",
                                                    "theta_common.json"))
    p.add_argument("--seeds", default="103,104,105,107,109",
                   help="평가 시드. 학습 시드 101 과 탐색 시드 42,43,44 는 뺀다 (계약 §5)")
    p.add_argument("--with-train-seed", action="store_true", dest="with_train",
                   help="학습 시드 101 을 참고용으로 같이 돌린다")
    p.add_argument("--timeout", type=int, default=400,
                   help="theta_stall_scan.py 가 쓴 값과 같아야 '교착' 정의가 같다")
    p.add_argument("--arms", default="tp,exp,expmean,common",
                   help="expmean 을 빼면 (a) 창고별 효과와 (b) 완주율 효과가 안 갈린다")
    p.add_argument("--limit", type=int, default=0, help="앞에서 N 창고만 (연습용)")
    p.add_argument("--work", default=os.path.join(OUT, "theta_expected_eval"))
    p.add_argument("--out", default=os.path.join(OUT, "theta_expected_value_v36.csv"))
    p.add_argument("--no-preflight", action="store_true", dest="no_preflight",
                   help="비교군마다 1런씩 먼저 확인하는 점검을 건너뛴다")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()

    arms = [x for x in a.arms.split(",") if x]
    bad = [x for x in arms if x not in ARMS]
    if bad:
        raise SystemExit("모르는 팔 %s — 쓸 수 있는 것은 %s" % (bad, list(ARMS)))
    seeds = [int(s) for s in a.seeds.split(",") if s.strip()]
    if a.with_train:
        seeds = seeds + [101]
    # θ 경로는 **반드시 절대경로**여야 한다 — 시뮬은 sim_engine 에서 돌아서 상대경로면 못 찾고,
    # 못 찾은 런은 조용히 '교착' 으로 세어져 그 비교군이 통째로 0 % 가 된다.
    a.work, a.common = os.path.abspath(a.work), os.path.abspath(a.common)

    design = {d["name"]: d for d in json.load(open(a.design, encoding="utf-8"))}
    table = list(csv.DictReader(open(a.csv, encoding="utf-8")))
    names = [r["map"] for r in table if r["map"] in design][:a.limit or None]
    if not names:
        raise SystemExit("%s 의 맵이 design.json 에 하나도 없다" % a.csv)
    pred = {r["map"]: r for r in table}

    os.makedirs(a.work, exist_ok=True)
    theta_path = {}
    for r in table:
        if r["map"] not in names:
            continue
        for arm in arms:
            if arm in ("common", "expmean"):
                continue
            f = os.path.join(a.work, "theta_%s_%s.json" % (arm, r["map"]))
            json.dump(theta_from_row(r, arm), open(f, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
            theta_path[(r["map"], arm)] = f
    if "expmean" in arms:
        # 맵별 exp θ 를 하나로 — (a) 창고별 효과만 빼고 (b) 완주율 효과는 그대로 둔 대조군
        fixed = theta_mean([r for r in table if r["map"] in names], "exp")
        f = os.path.join(a.work, "theta_expmean.json")
        json.dump(fixed, open(f, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        for n in names:
            theta_path[(n, "expmean")] = f
        print("기대 θ 평균: " + " · ".join("%s %.2f" % (k[:12], fixed[k]) for k in
                                           ("loop_gain", "junction_penalty",
                                            "wait_cost", "station_out")))
    if "common" in arms:
        if not os.path.exists(a.common):
            raise SystemExit("공통 θ 가 없다 (%s) — --arms tp,exp 로 돌리거나 경로를 줄 것"
                             % a.common)
        for n in names:
            theta_path[(n, "common")] = a.common

    jobs = [(n, arm, s) for n in names for arm in arms for s in seeds]
    print("창고 %d개 · 팔 %s · 평가 시드 %s%s"
          % (len(names), " · ".join(LABEL[x] for x in arms), seeds,
             "  (101 은 학습 시드 — 참고용)" if a.with_train else ""))
    print("런 %d개 · 동시 %d · 타임아웃 %d초 · 교착은 처리량 0 으로 센다"
          % (len(jobs), a.jobs, a.timeout))
    if a.dry_run:
        n, arm, s = jobs[0]
        print("  예시: " + " ".join(["python3", "sim_v2_tasks.py", "vf",
                                     str(design[n]["fleet"]), "...", str(s), "0",
                                     "--theta=" + theta_path[(n, arm)]]))
        return 0

    # 사전 점검 — 비교군마다 1런씩 먼저 돌린다. θ 파일을 못 찾는 실수(상대경로 등)는
    # 조용히 '교착' 으로 세어져 그 비교군이 통째로 0 % 로 나오므로, 여기서 먼저 잡는다.
    if not a.no_preflight:
        probe = [(names[0], arm, seeds[0]) for arm in arms]
        with ThreadPoolExecutor(max_workers=len(probe)) as pool:
            pre = list(pool.map(lambda j: sim(design[j[0]], theta_path[(j[0], j[1])],
                                              j[2], a.timeout), probe))
        print("  점검(%s · 시드 %d): %s"
              % (names[0], seeds[0],
                 " · ".join("%s %s" % (LABEL[j[1]], "OK" if v[0] else "교착/실패")
                            for j, v in zip(probe, pre))))
        if all(v[0] == 0 for v in pre):
            print("\n  **전 비교군이 실패했다.** θ 경로나 맵 설정을 확인할 것 — 정상적인 결과가 아니다.")
            print("  θ 폴더 %s" % a.work)
            return 1

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        got = list(pool.map(lambda j: sim(design[j[0]], theta_path[(j[0], j[1])],
                                          j[2], a.timeout), jobs))
    res = {j: v for j, v in zip(jobs, got)}
    print("  %.0f분" % ((time.time() - t0) / 60))

    rows = []
    for n in names:
        r = {"name": n, "exp_tp": {}, "rate": {}, "done": {}}
        for arm in arms:
            v = [res[(n, arm, s)] for s in seeds]
            r["exp_tp"][arm] = st.fmean(tp for _, tp in v)          # 교착 = 0
            r["done"][arm] = st.fmean(ok for ok, _ in v)
            fin = [tp for ok, tp in v if ok]
            r["rate"][arm] = st.fmean(fin) if fin else 0.0          # 완주 런만
        rows.append(r)

    print("\n=== 팔별 전체 (창고 %d · 시드 %d) ===" % (len(rows), len(seeds)))
    print("  %-18s%12s%14s%16s" % ("θ", "완주율", "완주시 처리량", "기대 처리량"))
    print("  " + "-" * 60)
    for arm in arms:
        fin = [r["rate"][arm] for r in rows if r["rate"][arm] > 0]
        print("  %-18s%11.1f%%%14.1f%16.1f"
              % (LABEL[arm], 100 * st.fmean(r["done"][arm] for r in rows),
                 st.fmean(fin) if fin else 0.0,
                 st.fmean(r["exp_tp"][arm] for r in rows)))

    if "tp" in arms and "exp" in arms:
        print("\n=== 모델이 예측한 완주 확률 vs 실측 (창고 평균) ===")
        print("  %-22s%14s%14s" % ("", "모델 예측", "실측"))
        for arm in ("tp", "exp"):
            mp = st.fmean(float(pred[r["name"]][arm + "_p"]) for r in rows)
            print("  %-22s%13.1f%%%13.1f%%"
                  % (LABEL[arm], 100 * mp, 100 * st.fmean(r["done"][arm] for r in rows)))

    print("\n=== 짝비교 (맵 단위 · 기대 처리량) ===")
    print("  %-30s%12s%10s%12s" % ("대결", "평균 차이%", "양수", "부호검정 p"))
    print("  " + "-" * 66)
    duels = [(x, y) for x, y in (("exp", "tp"), ("exp", "expmean"), ("exp", "common"),
                                 ("expmean", "common"), ("tp", "common"))
             if x in arms and y in arms]
    verdict = {}
    for x, y in duels:
        base = st.fmean(r["exp_tp"][y] for r in rows)
        m, win, n, pv = paired(rows, x, y, "exp_tp")
        verdict[(x, y)] = (100 * m / base if base else 0.0, win, n, pv)
        print("  %-30s%+11.2f%%%8d/%-3d%12.2e"
              % (LABEL[x] + " − " + LABEL[y], verdict[(x, y)][0], win, n, pv))

    print("\n=== 창고별 (기대 처리량 · 완주율) ===")
    print("  %-14s" % "창고" + "".join("%18s" % LABEL[x] for x in arms))
    for r in sorted(rows, key=lambda z: z["name"]):
        print("  %-14s" % r["name"]
              + "".join("%12.1f (%2.0f%%)" % (r["exp_tp"][x], 100 * r["done"][x])
                        for x in arms))

    with open(a.out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name"] + ["%s_%s" % (m, x) for x in arms
                               for m in ("done", "rate", "exp_tp")])
        for r in sorted(rows, key=lambda z: z["name"]):
            w.writerow([r["name"]] + ["%.4f" % r[m][x] for x in arms
                                      for m in ("done", "rate", "exp_tp")])
    print("\n  CSV %s · θ %s" % (a.out, a.work))

    if len(rows) < MIN_ROWS:
        print("\n  **표본 %d창고 — 결론을 내지 않는다.**" % len(rows))
        return 1
    if ("exp", "tp") not in verdict:
        return 0

    print("\n=== 판정 ===")
    m, win, n, pv = verdict[("exp", "tp")]
    dp = 100 * (st.fmean(r["done"]["exp"] for r in rows)
                - st.fmean(r["done"]["tp"] for r in rows))
    cm = verdict.get(("exp", "common"))
    em = verdict.get(("exp", "expmean"))

    # ① 목적함수 — 곱이 처리량 단독을 이기는가
    if m > 5 and pv < 0.05:
        print("  ① **곱으로 최적화할 값이 있다.** 기대 처리량 %+.1f%% (완주율 %+.1f%%p) · p=%.1e"
              % (m, dp, pv))
    elif abs(m) < 2 or pv > 0.2:
        print("  ① **곱이 처리량 단독을 못 이긴다.** 차이 %+.1f%% · p=%.1e" % (m, pv))
        print("     모델 위에서 본 이득은 대리 모델 둘이 서로를 채점한 값이었다.")
    else:
        print("  ① 방향은 있으나 크기가 애매하다 (%+.1f%% · p=%.1e)." % (m, pv))

    # ② 창고별인가 완주율인가 — expmean 이 있어야만 갈린다
    if em:
        gain_a = em[0]                                   # exp − expmean = (a) 단독
        print()
        if gain_a > 5 and em[3] < 0.05:
            print("  ② **창고별 θ 가 값을 낸다.** 같은 완주율 목적함수로 뽑은 θ 라도 맵마다 다르게")
            print("     주는 쪽이 고정 평균보다 %+.1f%% 낫다 (p=%.1e) — 이 프로젝트에서 처음이다."
                  % (gain_a, em[3]))
        elif abs(gain_a) < 3 or em[3] > 0.2:
            print("  ② **창고별로 다르게 줄 이유는 없다.** 맵별 θ 와 그 평균 하나가 같다"
                  "(%+.1f%% · p=%.1e)." % (gain_a, em[3]))
            print("     이득은 (a) 창고별 맞춤이 아니라 (b) 완주율을 목적에 넣은 데서 나왔다.")
            print("     고칠 것은 모델이 아니라 run_study.py 의 목적함수다.")
        else:
            print("  ② 창고별 효과가 경계다 (%+.1f%% · p=%.1e) — 크기를 보고 판단할 것."
                  % (gain_a, em[3]))
        if cm:
            print("     참고: exp−common %+.1f%% = (a)+(b) · exp−expmean %+.1f%% = (a) 단독"
                  % (cm[0], gain_a))
    elif cm:
        print()
        print("  ② expmean 비교군이 없어 (a) 창고별 효과와 (b) 완주율 효과가 안 갈린다.")
        print("     --arms tp,exp,expmean,common 으로 다시 돌릴 것.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
