# -*- coding: utf-8 -*-
"""**회전을 빨리 돌리면 더 밀리나** — 회전 속도를 쓸어 본다 (S15P21A106-267).

    source paths.sh
    python tools/turn_speed_sweep.py                    # 1.2 / 1.8 / 2.4
    W=0.9,1.8,2.7,3.6 N=13 python tools/turn_speed_sweep.py
    W=1.8 DRY=1 python tools/turn_speed_sweep.py        # 명령만 찍고 안 돈다

왜 이 도구가 있나
-----------------
`A3#253 turn(46,68,3)->(46,68,0)` 이 90도를 돌고 축이 **363.4 mm** 밀렸다.
원인을 찾을 때 계단 입력을 의심해 각가속 램프로 A/B 했고 —

    W_ACCEL 0 -> 20   363.4 -> 375.5 mm     **안 변했다**

여기서 멈췄다. 그런데 `W_ACCEL` 은 w 가 **얼마나 빨리 오르는지**만 막는다.
**얼마나 큰지**(w_max)는 그때도 지금도 한 번도 안 건드렸다 — `GEOM_KW` 에
1.8 로 박혀 있었기 때문이다. 그래서 「빠르면 더 밀리나」는 닫힌 가설이
아니라 **안 물어본 질문**이다. `PIBT_W_EXEC` 를 내고 이 도구로 묻는다.

★★ 반드시 **Isaac 물리**로 돌려야 한다 — 기구학 판으로는 답이 안 나온다
------------------------------------------------------------------------
`tools/speed_sweep.py` 는 `make_kinematic_drivers` 로 돌아서 GPU 가 필요
없다. 그 싼 길을 여기 쓰면 **틀린 답이 나온다.** 기구학 드라이버의 미끄러짐은

    self.gain = 1.0 - slip * rng.random()        # 로봇마다 한 번 뽑는 상수
    v, w = self._v * self.gain, self._w * self.gain

이다. 속도에 **안 딸린 고정 배율**이라, w 를 아무리 올려도 종료 오차는
(1-gain)*theta 로 같다. 기울기 0 이 나오고 그건 물리가 아니라 모델의
가정일 뿐이다. 마찰 한도를 넘는지는 PhysX 만 안다.

그래서 이 도구는 값마다 `run_headless.sh` 를 **실제로 돌리고**, 나온 NPZ 를
`tools/turn_error.py` 에 먹인다. 판당 GPU 시간이 든다 — 그게 이 질문의 값이다.

무엇을 보나
-----------
    종료 오차   회전이 끝난 뒤 축이 칸 중심에서 벗어난 거리
    구간 최대   회전하는 **동안**의 최대 이탈 (몸이 쓸고 가는 건 이때다)

    w 가 커질수록 이 둘이 **커지면**  -> 속도가 원인이다. w 를 내리면 된다
    평평하면                          -> 속도가 아니다. 남은 후보는 외력이고,
                                         제일 싼 것이 꼬리(r=1.18 m)가 스치는
                                         랙이다 (`tools/turn_sweep_check.py`)

☹ 내리는 쪽은 **TURN_TICKS=5 를 깨뜨린다** (FMS 와 공유하는 틱이다). 그러니
  w 를 내린 판에서 **완주 시간**을 결론으로 쓰면 안 된다. 이탈량만 본다.
  `FleetController` 가 그 경우 ★ 경고를 찍는다.
"""
import os
import re
import subprocess
import sys

W = os.environ["W"]
OUT = os.environ.get("OUT", os.path.join(W, "out"))
LOGS = os.environ.get("LOGS", os.path.join(W, "logs"))
WS = [float(x) for x in os.environ.get("W_LIST",
                                       os.environ.get("WSWEEP", "1.2,1.8,2.4")).split(",")]
N = os.environ.get("N", "13")
DRY = os.environ.get("DRY", "") not in ("", "0", "no")
# ★ NPZ 가 이미 있으면 **안 돌리고 다시 재기만** 한다. 표에 열을 하나 더하려고
#   72분을 또 태울 이유가 없다 — 측정은 `turn_error` 가 NPZ 에서 하는 것이라
#   런과 분리돼 있다.
REUSE = os.environ.get("REUSE", "") not in ("", "0", "no")
PITCH = os.environ.get("PIBT_PITCH", "1.0")

# ★ 시뮬 상한을 **기본으로 건다** (`PIBT_HL_MAX_SIM`). 안 걸면 완주까지 가는데
#   13대 판이 시뮬 2,287 초라 RTF 1.0 에서 값당 38분, 세 값이면 2시간이다.
#   우리가 원하는 것은 완주가 아니라 **회전의 분포**다.
#
#   회전 밀도는 기존 녹화에서 나온다 — 463.8 시뮬초 x 12대에 회전 89건,
#   즉 초당 0.19건이다. 300 초면 약 57건이라 중앙값·p95 를 내기에 족하다.
#   더 촘촘한 꼬리(p99)가 필요하면 MAX_SIM 을 올린다.
MAX_SIM = float(os.environ.get("MAX_SIM", "300"))
TURNS_PER_SIM_S = 89.0 / 463.8          # 실측 밀도 (12대 기준)

# ★ 시드는 `PIBT_SEED` 다 — `SEED` 가 아니다 (run_headless.sh:55, 기본 104).
#   처음에 `for s in 1 2 3; do SEED=$s ...` 를 건넸는데 그러면 **무시된다.**
#   같은 판을 세 번 돌리고 「시드 셋을 봤다」고 결론낼 뻔했다. 게다가 태그에
#   시드가 없어 NPZ 를 서로 덮어썼다. 그래서 루프를 도구 안으로 들인다.
SEEDS = [int(x) for x in os.environ.get("SEEDS",
                                        os.environ.get("PIBT_SEED", "104")).split(",")]


def tag_of(w, seed):
    return "wsw%s_s%d" % (("%.2f" % w).replace(".", "p"), seed)


def run_one(w, seed):
    """한 조합을 돌린다. (npz 경로, 로그 경로)."""
    tag = tag_of(w, seed)
    npz = os.path.join(OUT, "rec_%s.npz" % tag)
    env = dict(os.environ)
    env["PIBT_W_EXEC"] = "%.4f" % w
    env["PIBT_RECORD"] = npz
    env["TAG"] = tag
    env["PIBT_SEED"] = str(seed)
    if MAX_SIM > 0:
        env["PIBT_HL_MAX_SIM"] = "%.0f" % MAX_SIM
    cmd = ["bash", os.path.join(W, "run_headless.sh"), N]
    print("\n" + "=" * 70)
    print("w_exec %.2f rad/s · 시드 %d   ->  %s" % (w, seed, npz))
    print("  PIBT_W_EXEC=%.4f PIBT_SEED=%d PIBT_RECORD=%s TAG=%s "
          "bash run_headless.sh %s" % (w, seed, npz, tag, N))
    if DRY:
        return npz, None
    log = os.path.join(LOGS, "hl_%s.log" % tag)
    if REUSE and os.path.isfile(npz):
        print("  · 이미 있다 — 안 돌리고 다시 잰다 (REUSE=1)")
        return npz, log
    rc = subprocess.call(cmd, env=env)
    if rc != 0:
        print("  ★ 런이 실패했다 (rc=%d). 로그: %s" % (rc, log))
        return None, log
    if not os.path.isfile(npz):
        print("  ★ NPZ 가 안 생겼다: %s" % npz)
        print("    PIBT_RECORD 를 러너가 읽는지 확인할 것 "
              "(runners/headless_pibt.py 의 녹화 분기)")
        return None, log
    return npz, log


def measure(npz):
    """`turn_error.py` 를 그대로 쓴다 — 재구현하지 않는다."""
    env = dict(os.environ)
    env["PITCH"] = PITCH
    p = subprocess.run([sys.executable, os.path.join(W, "tools/turn_error.py"), npz],
                       env=env, capture_output=True, text=True)
    print(p.stdout)
    if p.returncode != 0:
        print(p.stderr)
    return p.stdout


def nums(line, label=""):
    return [float(t) for t in line.replace(label, "").split()
            if t.replace(".", "").replace("-", "").isdigit()]


def pick(text, label):
    """`turn_error` 표에서 한 줄을 집어 (중앙, p95) 로 돌려준다."""
    for line in text.splitlines():
        if label in line:
            n = nums(line, label)
            if len(n) >= 2:
                return n[0], n[1]
    return None, None


def pick_safety(text):
    """★ **여유를 실제로 먹는 숫자**를 따로 집는다 (2026-09-24).

    처음 낸 요약표는 「종료 오차」와 「구간 최대」만 실었다. 둘 다 **거리의
    크기**라 옆 칸 판정에 그대로 안 들어간다 — 옆 칸 여유를 먹는 것은
    **가로 성분**뿐이다. `turn_error` 는 그걸 이미 구별해 내고 있는데
    (「규칙별 여유 — 가로 성분만」) 요약에서 떨어뜨렸다. 판단이 걸린 줄이
    표에 없으면 표를 보고도 틀린 결론을 낸다.

    같이 집는 것 — 회전 **횟수**. w 마다 교통이 달라져 같은 회전 집합이
    아니다. 표본 수가 안 보이면 22.5 와 25.2 의 차이를 못 읽는다.
    """
    n_turn = lat_max = margin = dur = None
    for line in text.splitlines():
        m = re.search(r"회전\s+(\d+)회", line)
        if m and n_turn is None:
            n_turn = int(m.group(1))
        # ★ 회전 **지속 시간**. 안전이 아니라 **일정** 쪽 숫자다 — TURN_TICKS=5
        #   (=1.389 s) 를 넘기는지가 여기서 갈린다. 처음 요약에서 빠뜨렸다.
        #   식으로 내던 값(w=2.4 에 1.45 s)과 실측(1.27 s)이 다르다. 제어가
        #   `clamp(3*err, ±w)` 라 끝에서 저절로 줄고, 회전각도 87도지 90도가
        #   아니다. 그러니 **실측을 싣는다.**
        m = re.search(r"지속\s*중앙\s*([0-9.]+)\s*s", line)
        if m and dur is None:
            dur = float(m.group(1))
        if "가로 (옆)" in line:
            n = nums(line, "가로 (옆)")
            if len(n) >= 3:
                lat_max = n[2]
        # ★★ 여유를 **직접 계산한다** (2026-09-24 수정).
        #   예전에는 「남는 여유」 뒤의 숫자를 집었다. 그런데 규칙을 **넘으면**
        #   turn_error 가 그 자리에 숫자 대신 `★ 초과` 를 찍는다. 그래서
        #   w=3.0 에서 요약표가 `?` 로 나왔다 — 하필 **유일하게 위험한 줄**을
        #   「모름」으로 보여준 것이다. 반대로 읽히는 실패다.
        #
        #   줄에 두 숫자가 다 있다:  가로 최대x2  /  여유  ->  (남는 여유)
        #   빼면 넘든 안 넘든 같은 식으로 나온다. 음수가 곧 초과다.
        if "앞2" in line and "가로" in line:
            n = nums(line)
            if len(n) >= 2:
                margin = n[1] - n[0]
    return n_turn, lat_max, margin, dur


def main():
    print("회전 속도 쓸기 — 대수 %s · pitch %s · w = %s"
          % (N, PITCH, ", ".join("%.2f" % w for w in WS)))
    print("계획값은 geom.w_max = 1.8 이다. 그보다 낮은 판은 완주 시간을 안 본다.")
    print("시드 %s" % ", ".join(str(s) for s in SEEDS))
    n_run = len(WS) * len(SEEDS)
    if MAX_SIM > 0:
        # 준비 40 초(스테이지 1,923 박스 로딩·probe·시작 재정렬) + Isaac 부팅·계획.
        # RTF 는 jupyter04 실측 약 1.0 이고 촬영이 없으니 그보다 조금 낫다.
        per = MAX_SIM / 1.0 / 60.0 + 3.0
        print("시뮬 상한 %.0f 초 (판당 회전 약 %.0f건 예상) · 판당 대략 %.0f분 · "
              "%d판 = 대략 %.0f분"
              % (MAX_SIM, MAX_SIM * TURNS_PER_SIM_S, per, n_run, per * n_run))
        print("  ☹ 어림이다. RTF 1.0 과 준비 3분을 가정했다 — 첫 판이 끝나면 맞춰 볼 것.")
    else:
        print("☹ MAX_SIM=0 — 완주까지 간다. 13대 판은 판당 40분 가까이 걸린다.")
    rows = []
    for w in WS:
        for seed in SEEDS:
            npz, _ = run_one(w, seed)
            if DRY or npz is None:
                rows.append((w, seed, None, None, None, None, None, None, None, None))
                continue
            text = measure(npz)
            e_med, e_p95 = pick(text, "종료 오차")
            m_med, m_p95 = pick(text, "구간 최대")
            n_turn, lat_max, margin, dur = pick_safety(text)
            rows.append((w, seed, e_med, e_p95, m_med, m_p95,
                         n_turn, lat_max, margin, dur))

    print("\n" + "=" * 84)
    print("%7s %6s %6s %9s %8s %9s %8s %9s %10s %9s"
          % ("w_exec", "시드", "회전수", "종료중앙", "종료p95", "구간중앙",
             "구간p95", "가로최대", "앞2 남은여유", "지속중앙"))
    for w, seed, a, b, c, d, n, lat, mg, du in rows:
        if a is None:
            print("%7.2f %6d   (못 쟀다)" % (w, seed))
            continue
        tick = "" if du is None else ("  ★틱초과" if du > 1.389 else "")
        print("%7.2f %6d %6s %9.1f %8.1f %9.1f %8.1f %9s %10s %9s%s"
              % (w, seed, "?" if n is None else n, a, b, c, d,
                 "?" if lat is None else "%.1f" % lat,
                 "?" if mg is None else ("%.1f ★초과" % mg if mg < 0
                                         else "%.1f" % mg),
                 "?" if du is None else "%.2f s" % du, tick))
    print("   (지속중앙은 일정 쪽이다 — 계획 5틱 = 1.389 s 를 넘으면 ★)")

    if len(SEEDS) > 1:
        print("\n시드 평균 — w 마다")
        print("%7s %6s %9s %8s %9s %8s %9s"
              % ("w_exec", "판", "종료중앙", "종료p95", "구간중앙", "구간p95", "가로최대"))
        for w in WS:
            got = [r for r in rows if r[0] == w and r[2] is not None]
            if not got:
                print("%7.2f      0   (못 쟀다)" % w)
                continue
            def avg(i):
                v = [r[i] for r in got if r[i] is not None]
                return sum(v) / len(v) if v else float("nan")
            print("%7.2f %6d %9.1f %8.1f %9.1f %8.1f %9.1f"
                  % (w, len(got), avg(2), avg(3), avg(4), avg(5), avg(7)))
        print("   ☹ **p95 의 평균은 합친 p95 가 아니다.** 꼬리를 제대로 합치려면")
        print("     판마다의 회전을 한 통에 넣고 다시 분위수를 내야 한다. 여기서는")
        print("     추세를 보는 용도로만 쓴다 — 판별은 위의 시드별 줄로 한다.")
    print("   (mm. 회전수가 판마다 다르면 같은 회전 집합이 아니다 — 교통이 달라진다)")
    print("\n읽는 법 — w 가 커질 때")
    print("  ★ 판단은 **가로최대**로 한다. 종료·구간은 거리의 크기라 옆 칸")
    print("    여유에 그대로 안 들어간다. 옆 칸을 먹는 것은 가로 성분뿐이다.")
    print("  커지면   속도가 원인이다. w 를 내려 줄일 수 있다")
    print("  평평하면 속도가 아니다. 남은 후보는 외력 — 꼬리가 스치는 랙")
    print("  「앞2 남은여유」가 0 에 가까우면 그 w 는 쓰면 안 된다")
    print("\n☹ 이 표는 **평상시 분포**다. A3#253 의 363 mm 같은 한 건은 여기")
    print("  안 들어온다 (최대가 수십 mm 대다). 기울기가 보여도 그 사건이")
    print("  설명된 것은 아니다 — 둘은 다른 물음이다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
