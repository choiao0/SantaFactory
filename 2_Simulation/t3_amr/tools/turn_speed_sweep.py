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
import subprocess
import sys

W = os.environ["W"]
OUT = os.environ.get("OUT", os.path.join(W, "out"))
LOGS = os.environ.get("LOGS", os.path.join(W, "logs"))
WS = [float(x) for x in os.environ.get("W_LIST",
                                       os.environ.get("WSWEEP", "1.2,1.8,2.4")).split(",")]
N = os.environ.get("N", "13")
DRY = os.environ.get("DRY", "") not in ("", "0", "no")
PITCH = os.environ.get("PIBT_PITCH", "1.0")


def tag_of(w):
    return "wsw%s" % ("%.2f" % w).replace(".", "p")


def run_one(w):
    """한 값을 돌린다. (npz 경로, 로그 경로)."""
    tag = tag_of(w)
    npz = os.path.join(OUT, "rec_%s.npz" % tag)
    env = dict(os.environ)
    env["PIBT_W_EXEC"] = "%.4f" % w
    env["PIBT_RECORD"] = npz
    env["TAG"] = tag
    cmd = ["bash", os.path.join(W, "run_headless.sh"), N]
    print("\n" + "=" * 70)
    print("w_exec %.2f rad/s   ->  %s" % (w, npz))
    print("  PIBT_W_EXEC=%.4f PIBT_RECORD=%s TAG=%s bash run_headless.sh %s"
          % (w, npz, tag, N))
    if DRY:
        return npz, None
    log = os.path.join(LOGS, "hl_%s.log" % tag)
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


def pick(text, label):
    """`turn_error` 표에서 한 줄을 집어 (중앙, p95) 로 돌려준다."""
    for line in text.splitlines():
        if label in line:
            nums = [t for t in line.replace(label, "").split() if t.replace(".", "").isdigit()]
            if len(nums) >= 2:
                return float(nums[0]), float(nums[1])
    return None, None


def main():
    print("회전 속도 쓸기 — 대수 %s · pitch %s · w = %s"
          % (N, PITCH, ", ".join("%.2f" % w for w in WS)))
    print("계획값은 geom.w_max = 1.8 이다. 그보다 낮은 판은 완주 시간을 안 본다.")
    rows = []
    for w in WS:
        npz, _ = run_one(w)
        if DRY or npz is None:
            rows.append((w, None, None, None, None))
            continue
        text = measure(npz)
        e_med, e_p95 = pick(text, "종료 오차")
        m_med, m_p95 = pick(text, "구간 최대")
        rows.append((w, e_med, e_p95, m_med, m_p95))

    print("\n" + "=" * 70)
    print("%8s %10s %8s %10s %8s" % ("w_exec", "종료중앙", "종료p95", "구간중앙", "구간p95"))
    for w, a, b, c, d in rows:
        if a is None:
            print("%8.2f   (못 쟀다)" % w)
        else:
            print("%8.2f %10.1f %8.1f %10.1f %8.1f" % (w, a, b, c, d))
    print("\n읽는 법 — w 가 커질 때 이 숫자들이")
    print("  커지면   속도가 원인이다. 밀림은 w 를 내려 줄일 수 있다")
    print("  평평하면 속도가 아니다. 남은 후보는 외력 — 꼬리가 스치는 랙")
    print("  (기울기를 보려면 값이 최소 셋은 있어야 한다)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
