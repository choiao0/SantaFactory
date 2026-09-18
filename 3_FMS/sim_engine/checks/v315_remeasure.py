# -*- coding: utf-8 -*-
# ============================================================
# 계약 v3.15 재측정 — 후진 실행 틱 rev_ticks 를 켜기 전/후를 한 번에 뜬다 (S15P21A106-247)
#
# v3.15 가 바꾸는 것은 **하나**다: 후진 1칸이 전진과 같은 MOVE_TICKS 였던 것을
# REVERSE_FACTOR(3.0) 배 = 12틱 으로. speed 0.9 에서 정확히 0.300 m/s 이고
# 물리 팀 녹화의 후진 p99 와 같다 (t3-31 §2).
#
# 이 스크립트가 하는 일 셋:
#   1) 게이트   플래그 없이 돌려 **지금 기준값과 한 자리도 안 틀리는지** 본다.
#               여기서 틀리면 v3.15 와 무관한 회귀가 섞인 것이므로 **먼저 그걸 잡는다.**
#   2) 측정     플래그를 켜고 같은 판을 떠서 옛 값과 나란히 낸다.
#   3) 판정     v1compat·cell 은 칸 모델(헤딩 없음 = 후진 개념 없음)이라 **안 바뀌어야 한다.**
#               바뀌면 rev_ticks 가 새는 것이다.
#
# 사용 (3_FMS/sim_engine):
#   python checks/v315_remeasure.py                # 기준값 5개, 게이트 + 측정 (~1분)
#   python checks/v315_remeasure.py --gate         # 게이트만 (켜기 전 회귀 확인)
#   python checks/v315_remeasure.py --six          # + 운영 six 6런 (24·28대 × 시드 셋, 오래 걸림)
#   python checks/v315_remeasure.py --flags=--rev-ticks=12,--replan-max-extra=16
#                                                  # 켤 것이 바뀌면 여기만 고친다
# 종료 코드 0 = 게이트 통과, 1 = 게이트 실패(= 켜기 전에 고칠 것이 있다).
# ============================================================
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ENG = os.path.dirname(HERE)
ENV = dict(os.environ, SIM_NO_PLOT="1", MPLBACKEND="Agg", PYTHONIOENCODING="utf-8")

# v3.15 에서 켜는 것. 늘어나면 여기에 더한다.
V315_FLAGS = ["--rev-ticks=12"]

# 계약 §5 기준값 — (이름, 인자, 기대 makespan, 기대 tasks/h, 헤딩 모델인가)
# 헤딩이 아닌 둘(v1compat·cell)은 후진 개념이 없으므로 **켠 뒤에도 같아야 한다.**
BASELINES = [
    ("기본 exact",     ["base", "6", "40", "42", "1"],                         10533, 143.5, True),
    ("legacy",         ["base", "6", "40", "42", "1", "--footprint=legacy"],   10442, 144.8, True),
    ("exact,front",    ["base", "6", "40", "42", "1", "--footprint=exact,front"], 10590, 142.8, True),
    ("v1compat",       ["base", "6", "40", "42", "1", "--flow=v1compat"],       2317, 186.4, False),
    ("cell",           ["base", "6", "40", "42", "1", "--cell"],                2866, 131.9, False),
]


def run(args):
    """sim_v2_tasks 를 돌려 SUMMARY dict 를 준다. 실패하면 None."""
    cmd = [sys.executable, os.path.join(ENG, "sim_v2_tasks.py")] + args
    r = subprocess.run(cmd, cwd=ENG, capture_output=True, text=True, encoding="utf-8", env=ENV)
    ln = next((l for l in r.stdout.splitlines() if l.startswith("[SUMMARY]")), None)
    if ln is None:
        tail = (r.stdout + r.stderr).strip().splitlines()
        print("   !! 실패: %s" % (tail[-1][:140] if tail else "출력 없음"))
        return None
    return json.loads(ln[len("[SUMMARY] "):])


def kpi(d):
    return (None, None) if d is None else (d["makespan_steps"], round(d["tasks_per_h"], 1))


def main(argv):
    gate_only = "--gate" in argv
    with_six = "--six" in argv
    flags = next((a.split("=", 1)[1].split(",") for a in argv if a.startswith("--flags=")), V315_FLAGS)

    print("계약 v3.15 재측정 — 켜는 것: %s\n" % " ".join(flags))

    # ---- 1) 게이트 : 플래그 없이 = 지금과 같아야 한다 ----
    print("[1] 게이트 — 플래그 없이 돌려 기준값과 맞는가")
    with ThreadPoolExecutor(max_workers=5) as pool:
        before = list(pool.map(lambda b: run(b[1]), BASELINES))
    ok = True
    print("    %-14s %10s %9s   %10s %9s" % ("", "makespan", "tasks/h", "기대", "기대"))
    for (name, _a, e_mk, e_th, _h), d in zip(BASELINES, before):
        mk, th = kpi(d)
        hit = (mk == e_mk and th == e_th)
        ok &= hit
        print("    %-14s %10s %9s   %10d %9.1f   %s"
              % (name, mk, th, e_mk, e_th, "OK" if hit else "<<< 다르다"))
    if not ok:
        print("\n☹ 게이트 실패 — v3.15 와 무관한 회귀가 섞여 있다. **이것부터 잡는다.**")
        return 1
    print("    -> 통과. 지금 코드는 기준값과 비트 동일하다.\n")
    if gate_only:
        return 0

    # ---- 2) 측정 : 플래그를 켜고 ----
    print("[2] 측정 — %s 를 켜고 같은 판" % " ".join(flags))
    with ThreadPoolExecutor(max_workers=5) as pool:
        after = list(pool.map(lambda b: run(b[1] + flags), BASELINES))

    print("    %-14s %22s %22s %9s" % ("", "makespan (전 -> 후)", "tasks/h (전 -> 후)", "처리량"))
    leak = []
    for (name, _a, _e, _t, heading), b, a in zip(BASELINES, before, after):
        mk0, th0 = kpi(b)
        mk1, th1 = kpi(a)
        if mk1 is None:
            continue
        d = 100 * (th1 / th0 - 1)
        mark = ""
        if not heading:                       # 칸 모델은 후진이 없다 -> 안 바뀌어야 한다
            if (mk0, th0) != (mk1, th1):
                mark, _ = "<<< 새고 있다", leak.append(name)
            else:
                mark = "(칸 모델 — 불변 확인)"
        print("    %-14s %10s -> %-9s %10s -> %-9s %+8.1f%%  %s"
              % (name, mk0, mk1, th0, th1, d, mark))

    if leak:
        print("\n☹ **칸 모델이 바뀌었다** (%s) — rev_ticks 가 헤딩 밖으로 샌다. 켜기 전에 봐야 한다."
              % ", ".join(leak))

    print("\n    ★ 새 기준값 — 계약 §5 표와 검증 커맨드 주석을 이 값으로 고친다")
    for (name, a, _e, _t, _h), d in zip(BASELINES, after):
        mk, th = kpi(d)
        print("      %-14s %s   ->   %s / %s" % (name, " ".join(a[5:]) or "(기본)", mk, th))

    # ---- 3) 운영 six ----
    if with_six:
        print("\n[3] 운영 six 6런 — 24·28대 × 시드 101·103·104")
        od = os.environ.get("SET_ORDERS_DIR")
        if not od:
            print("    !! SET_ORDERS_DIR 가 없다. 주문 파일 폴더를 주고 다시 돌린다.")
        else:
            for tag, extra in (("v314_before", []), ("v315_after", flags)):
                cmd = [sys.executable, os.path.join(ENG, "sweeps", "run_set.py"),
                       "--set=six", "--jobs=6", "--tag=" + tag] + ["--extra=" + f for f in extra]
                print("    $ " + " ".join(cmd[1:]))
                subprocess.run(cmd, cwd=ENG, env=ENV)
            print("    -> results/set_v314_before.csv 와 set_v315_after.csv 를")
            print("       sweeps/compare_csv.py 로 맞댄다.")

    print("\n남은 것: 계약 문서 v3.14 -> v3.15 · 검증 커맨드 주석 · 워커/코어 이미지 재배포")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
