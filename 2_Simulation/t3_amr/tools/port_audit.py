# -*- coding: utf-8 -*-
"""포팅 대조 — `path/lifelong.py` 가 상류 `3_FMS/sim_engine` 와 갈렸는지 본다.

    python tools/port_audit.py

왜 필요한가
-----------
`pibt_core_v2.py` 는 상류를 **직접 import** 하므로 갈릴 수 없다. 그런데
`lifelong.py`(정책·배차·주문·교대·복귀)는 **다시 쓴 것**이라 조용히 갈린다.
실제로 갈렸다.

    2026-09-21  동승 여섯 줄이 통째로 빠져 있었다 (core.py:297)
    2026-09-22  SERVICE_TICKS 가 3 이었다 (상류 4) · assigned 를 안 적었다
                · 동승자의 to_name·assigned 를 안 덮었다

둘 다 **머리말의 「FMS 와 다른 것」 목록에 없는** 차이였다. 즉 의도가 아니라
누락이었다. 사람이 눈으로 보는 것으로는 안 걸린다 — 그래서 이 파일이 있다.

읽는 법
-------
`☹` 는 전부 확인 대상이다. 의도된 차이라면 `lifelong.py` 머리말의
[FMS 와 다른 것] 에 **적혀 있어야** 한다. 적혀 있지 않으면 누락이다.

Isaac 도 numpy 도 필요 없다. 몇 초면 끝난다.
"""
import io
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))

UP = os.path.join(HERE, "..", "..", "..", "3_FMS", "sim_engine") + os.sep
MY = os.path.join(HERE, "..") + os.sep

def rd(p):
    return io.open(p, encoding="utf-8").read()

core = rd(UP + "kernel/core.py")
states = rd(UP + "kernel/states.py")
ostream = rd(UP + "order_stream.py")
sim_cli = rd(UP + "sim_v2_tasks.py")          # CLI 가 넣는 **실제** 값이 여기 있다
# 계획 틱[s] — 궤적의 dt_s 와 같아야 한다. pitch / (v_max x MOVE_TICKS).
TICK_S = 1.0 / (0.9 * 4)
ll = rd(MY + "path/lifelong.py")
sw = rd(MY + "switches.sh")

rows = []
def chk(name, up, mine, ok=None):
    ok = (up == mine) if ok is None else ok
    rows.append((ok, name, up, mine))

# 1 서비스 틱
#   ★★ **dataclass 기본값을 보면 안 된다** (2026-09-22, FMS-43 이 알려 줬다).
#      `core.py:54  service_steps: int = 4` 는 기본값이고 CLI 가 **항상 덮는다**
#      (`sim_v2_tasks.py:380`).  실제 값은
#
#          round(SERVICE_TIME_S / dt) = round((40/11) / 0.2778) = 13
#
#      이 도구의 초판이 그 기본값(4)을 보고 「4/4 일치」로 통과시켰다. 값이
#      틀린 채로 **✓ 가 찍히는 것**이 제일 나쁘다 — 그래서 여기서 계산한다.
_svc_s = eval(re.search(r"SERVICE_TIME_S = ([0-9./ ]+)", sim_cli).group(1))
_up_svc = int(round(_svc_s / TICK_S))
chk("service_steps (CLI 환산) / SERVICE_TICKS",
    "%d  (=%.4fs/%.4fs · dataclass 기본 %s 는 무시)"
    % (_up_svc, _svc_s, TICK_S,
       re.search(r"service_steps: int = (\d+)", core).group(1)),
    re.search(r"^SERVICE_TICKS = (\d+)", ll, re.M).group(1),
    ok=(str(_up_svc) == re.search(r"^SERVICE_TICKS = (\d+)", ll, re.M).group(1)))
# 2 hd_after
chk("hd_after / HD_AFTER",
    re.search(r"hd_after: int = (\d+)", core).group(1),
    re.search(r'PIBT_HD_AFTER", "(\d+)"', ll).group(1))
# 3 주문 분포
chk("k_line_p",
    re.search(r"k_line_p=\(([^)]+)\)", ostream).group(1).replace(" ", ""),
    re.search(r"k_line_p=\(([^)]+)\)", ll).group(1).replace(" ", ""))
# 4 capacity 기본 (상류 코드기본 1 · 운영 6 · r13 데이터 6)
chk("capacity  (상류=코드기본 / 우리=switches)",
    re.search(r"capacity: int = (\d+)", core).group(1) + "  (운영 6)",
    re.search(r'PIBT_CAPACITY:-(\d+)', sw).group(1),
    ok=(re.search(r'PIBT_CAPACITY:-(\d+)', sw).group(1) == "6"))
chk("svc_per_tote",
    re.search(r"svc_per_tote: int = (\d+)", core).group(1) + "  (운영 18)",
    re.search(r'PIBT_SVC_PER_TOTE:-(\d+)', sw).group(1),
    ok=(re.search(r'PIBT_SVC_PER_TOTE:-(\d+)', sw).group(1) == "18"))
# 5 배차 본문 요소
for name, pat_up, pat_my in [
    ("eligible = IDLE|FREED", r"rb\[.state.\] in \(IDLE, FREED\)", r'r\["state"\] in \(IDLE, FREED\)'),
    ("동승 이미 실림 skip",   r"if task not in self\.waiting",      r"if task not in self\.waiting"),
    ("맨해튼 최근접",          r"abs\(robots\[i\]\[.pos.\]\[0\] - fr\)", r"abs\(self\.states\[i\]\[0\] - fr\)"),
    ("assigned 기록",          r'task\["assigned"\] = t',            r'task\["assigned"\] = t'),
    ("eligible.remove",        r"eligible\.remove\(rid\)",           r"elig\.remove\(a\)"),
    ("제자리 즉시 도킹",        r'if rb\["pos"\] == rb\["goal"\]',    r'if self\.states\[a\]\[:2\] == r\["goal"\]'),
    ("riders: 같은 frm",       r'tk\["frm"\] == task\["frm"\]',      r'tk\["frm"\] == task\["frm"\]'),
    ("riders: to 덮기",        r'tk\["to"\], tk\["to_name"\] = ',    r'tk\["to"\] = task\["to"\]'),
    ("riders: to_name 덮기",   r'tk\["to_name"\]',                   r'tk\["to_name"\] = task\["to_name"\]'),
    ("riders: assigned",       r'tk\["assigned"\] = t',              r'tk\["assigned"\] = t'),
]:
    u = bool(re.search(pat_up, core)); m = bool(re.search(pat_my, ll))
    chk(name, "있음" if u else "없음", "있음" if m else "없음", ok=(u == m))
# 6 RANK
chk("RANK TO_CHARGE",
    re.search(r"TO_CHARGE: (\d+)", states).group(1),
    re.search(r"TO_CHARGE: (\d+)", ll).group(1))

print("═" * 72)
bad = 0
for ok, name, up, mine in rows:
    mark = "  ✓" if ok else "  ☹"
    if not ok:
        bad += 1
    print("%s %-34s 상류 %-14s 우리 %s" % (mark, name, up, mine))
print("═" * 72)
print("불일치 %d / %d" % (bad, len(rows)))


# 7 서비스 길이 모델 대 **실측** — 궤적이 있을 때만.
#   `docs/` 는 .gitignore 라 저장소에 없다. 없으면 건너뛴다 (그게 정상이다).
TRAJ = os.path.join(MY, "docs", "모음", "r13_peak10", "trajectories.json")
if not os.path.exists(TRAJ):
    print("\n서비스 길이  ☹ 건너뜀 — 궤적이 없다 (%s)" % TRAJ)
else:
    d = json.load(io.open(TRAJ, encoding="utf-8"))
    ss = int(re.search(r"^SERVICE_TICKS = (\d+)", ll, re.M).group(1))
    cap = int(re.search(r'PIBT_CAPACITY:-(\d+)', sw).group(1))
    per = int(re.search(r'PIBT_SVC_PER_TOTE:-(\d+)', sw).group(1))
    model = ss + cap * per
    # 실측 — service 라벨의 연속 구간 최빈값
    import collections
    runs = collections.Counter()
    for acts in d["actions"].values():
        n = 0
        for _t, kind in acts:
            if kind == "service":
                n += 1
            else:
                if n:
                    runs[n] += 1
                n = 0
        if n:
            runs[n] += 1
    obs = runs.most_common(1)[0][0]
    print("\n서비스 길이  모델 %d틱 (%.2f s)  =  %d + %d x %d"
          % (model, model * d["dt_s"], ss, cap, per))
    print("             실측 %d틱 (%.2f s)   차 %+d틱 (%+.1f %%)"
          % (obs, obs * d["dt_s"], model - obs, 100.0 * (model - obs) / obs))
    if model != obs:
        print("             ☹ `%d + %d*per = %d` 를 만족하는 정수 per 가 없다."
              % (ss, cap, obs))
        print("                틱 해상도 차이인지 라벨 경계인지 **안 밝혔다** — FMS 에 물을 것.")
