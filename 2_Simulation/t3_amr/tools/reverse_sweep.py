# -*- coding: utf-8 -*-
"""`REVERSE_FACTOR` 를 흔들어 **180° 가 사라지는지** 계획 층에서만 잰다.

무엇을 묻나
-----------
뒤쪽으로 N칸 갈 때 계획이 고를 수 있는 두 가지:

    후진 N칸        = N × REVERSE_FACTOR
    180° + 전진 N칸 = 2 × TURN_COST + N          (TURN_COST 1.25 → 2.5)

    후진이 이기는 조건은  N × RF < 2×TURN_COST + N  ⟺  **N < 2.5 / (RF − 1)**

    RF 3.0 :  N < 1.25  → 1칸일 때만 후진. 2칸 이상이면 180°.
    RF 1.5 :  N < 5     → 5칸 이상 이동에는 **여전히 180°** 를 쓴다.
    RF 1.0 :  분모가 0  → 항상 후진. 180° 를 고를 이유가 없다.

    ★ 분기점은 RF 한 값이 아니라 **이동 거리에 걸린다.** 「RF 2.5 아래면
      180° 가 사라진다」는 N=1 에만 맞는 얘기다 (2026-09-15 정정).

그리고 후진은 `core.py` 에서 **전진과 같은 `MOVE_TICKS`(4틱)** 다. RF 는
비용(선택)만 바꾸고 소요 틱은 안 바꾼다. 그래서 180° 10틱이 통째로 빠진다.

왜 「물리 전진 비율」을 같이 내나
--------------------------------
센서가 앞을 보므로 물리 후진으로 달린 거리는 **시야 없는 주행**이다. RF 를
바꾸면 180° 횟수만이 아니라 이 비율도 같이 움직이니 한 표에서 봐야 한다.

    pibt `move`     = 물리 **전진** 칸      (heading_offset = 0)
    pibt `reverse`  = 물리 **후진** 칸

★ 2026-09-16 정정. 초판은 `heading_offset = 2` 로 보고 **반대로** 적었다.
  `pibt_scene.GEOM_KW` 가 0 으로 덮어쓰므로 그쪽이 진실이다. 그 탓에
  「주행의 94.7 % 가 센서 없는 방향」이라는 정반대 결론을 냈고, 답신 11 의
  `REVERSE_FACTOR` 3.0 -> 1.0 제안이 그 위에 서 있었다. 실제로는 **RF 3.0
  에서 물리 전진이 92.4 %** 이고, 1.0 으로 내리면 41.8 % 로 **나빠진다.**

왜 설정마다 별도 프로세스인가
-----------------------------
`HGraph` 의 거리장은 비용에서 나온다. 한 프로세스에서 RF 를 바꿔 가며 돌리면
앞서 계산된 거리장을 재사용해 **옛 비용으로 짠 경로**가 나올 수 있다. 자식
프로세스에 `PIBT_REVERSE_FACTOR` 를 주고 처음부터 세우면 그 위험이 없고,
실제로 쓰게 될 경로(로더의 환경변수 오버라이드)를 그대로 시험하는 셈이 된다.

★ 이 도구가 내는 값은 **FMS 기본값이 아니다.** `geometry.py` 는 FMS 소스라
  우리가 못 고친다. 숫자를 들고 합의하러 가는 것이 목적이고, 합의 전에
  기본값을 바꾸면 두 트랙의 경로가 조용히 갈린다.

쓰는 법
-------
    source paths.sh
    python tools/reverse_sweep.py                      # 기본/3.0/1.0, 시드 1,2,4
    RF=3.0,2.0,1.5,1.0 SEEDS=1 python tools/reverse_sweep.py

    RF=off 로 두면 **순환 진단 도구**가 된다 — 후진 비용을 안 건드린 채
    격자·지평·배터리만 흔들 수 있다:

        PIBT_PITCH=1.2 BATTERY=1 RF=off python tools/reverse_sweep.py
        PIBT_PITCH=1.0 BATTERY=0 RF=off python tools/reverse_sweep.py
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.environ["W"], "path"))

MAP = os.environ["MAP"]
N = int(os.environ.get("N", "12"))
PITCH = float(os.environ.get("PIBT_PITCH", "1.0"))
# ★ 기본이 1,2,4 인 것은 `adg_fingerprint.py` 를 베낀 탓이다. **주행 기본은 9 다**
#   (`runners/live_pibt.py:164` PIBT_SEED 기본값). 그걸 확인 안 하고 1,2,4 로
#   돌렸다가 pitch 1.0 에서 3시드 전부 ADG 순환이 나서, 주행은 되는데 계획만
#   죽는 것처럼 보였다 (2026-09-15). 순환은 **시드를 탄다** — 한 시드로
#   「이 격자는 된다/안 된다」를 말하면 안 된다.
SEEDS = [int(x) for x in os.environ.get("SEEDS", "9,1,2,4").split(",")]
# 틱 정합 뒤 값 (-211). adg_fingerprint.py 와 같은 이유로 둘을 같이 움직인다.
HORIZON = int(os.environ.get("HORIZON", "1260"))
GAP = int(os.environ.get("GAP", "60"))
# ★ 실제 주행은 배터리를 **안 켠다** (`amr/path/pibt_h.py:90` BATTERY=False →
#   `plan()` 이 PIBT_BATTERY 기본을 "0" 으로 두어 `--battery` 를 안 붙인다).
#   처음 스윕을 True 로 박아 두고 「pitch 말고는 다 같다」고 적었는데, 그건
#   adg_fingerprint 와 비교했을 때만 맞았다. 주행과는 이것도 달랐다.
#   순환 원인을 가르려면 이 축이 켜고 끌 수 있어야 한다.
BATTERY = os.environ.get("BATTERY", "1") not in ("0", "", "no", "off")
# ★ 이것도 박아 두면 안 된다 (2026-09-15). 계획 산출물 `scene.json` 에
#   `"dispatch": "robot_first"` 가 찍힌 판이 있다. 배차가 다르면 태스크 배정이
#   달라지고 경로가 통째로 달라진다 — 순환 여부를 가를 수 있는 축이다.
DISPATCH = os.environ.get("PIBT_DISPATCH", "fms")
# ★ 이 값은 여기서 안 쓰지만 **반드시 찍는다** (2026-09-15). `pibt_scene.front_rule`
#   은 이 변수가 없으면 `geo.configure()` 를 아예 안 불러 앞 칸 규칙이 꺼진 채
#   돈다. 그런데 실제 주행은 `run_record.sh:187` 이 기본을 `4` 로 내보내 **켜고**
#   돈다. 그걸 모르고 돌렸다가 pitch 1.0 12시드 전부 순환을 보고 격자 탓을 했다.
#   결과를 읽을 때 규칙 상태를 모르면 그 오독이 반복된다.
FRONT_RULE = os.environ.get("PIBT_FRONT_RULE", "(안 줌 → 규칙 꺼짐)")

# `off` 는 환경변수를 **안 주는** 기준 판이다 (= 로더가 한 줄도 안 돈다 = FMS 기본).
# 기본 목록에 넣어 두는 이유: 오버라이드 경로 자체가 무해한지 매 판 같이 보이려고.
RFS = [None if x.strip().lower() in ("off", "기본", "none") else float(x)
       for x in os.environ.get("RF", "off,3.0,1.0").split(",")]


# --------------------------------------------------------------------------
# 자식 — 한 (RF, seed) 을 계획하고 JSON 한 줄을 낸다
# --------------------------------------------------------------------------
def child(seed):
    import pibt_core_v2                                   # noqa: F401
    import isaac_drive as D                               # noqa: E402
    import metrics                                        # noqa: E402
    import pibt_scene                                     # noqa: E402

    geom, free, starts, goals = pibt_scene.setup_lifelong(
        MAP, N, PITCH, seed, "cross", verbose=False)
    zone = pibt_scene.charge_zone_cells(free, geom)
    # ★ 순환은 **실패가 아니라 관측값**이다 (2026-09-15). 스윕을 처음 돌렸을 때
    #   12판 중 11판이 여기서 죽었는데, 부모가 그걸 삼켜서 표에는 "전부 실패"
    #   한 줄만 남았다. 순환이 RF 에 따라 달라지는지가 이 도구의 답 중 하나이므로
    #   세어서 표에 남긴다.
    try:
        adg, _order, _history, info = D.plan_and_build_lifelong(
            free, starts, goals, geom, horizon=HORIZON, seed=seed,
            order_gap=GAP, battery=BATTERY, dispatch=DISPATCH, zone_cells=zone,
            # `docks` 는 battery 일 때만 쓰이지만, 주행 경로(pibt_scene:793 ·
            # live_pibt:903)가 거는 게이팅을 그대로 둔다. 인자 하나라도
            # 다르면 "주행과 같은 조건" 이라고 말할 수 없다.
            order_end=None,
            docks=pibt_scene.charge_docks(free, geom) if BATTERY else ())
    except RuntimeError as e:
        if "순환" not in str(e):
            raise
        return {"seed": seed, "error": "cycle"}

    kinds = {}
    for a in adg.actions:
        kinds[a.kind] = kinds.get(a.kind, 0) + 1

    # 180° = 같은 칸에서 이어진 TURN 두 번, 머리 방향이 정확히 반대로.
    #   `(끝 heading - 시작 heading) % 4 == 2` 가 그 조건이다.
    by_agent = {}
    for a in adg.actions:
        by_agent.setdefault(a.agent, []).append(a)
    n180 = 0
    for acts in by_agent.values():
        acts.sort(key=lambda x: x.idx)
        for p, q in zip(acts, acts[1:]):
            if p.kind != D.TURN or q.kind != D.TURN:
                continue
            if p.to != q.frm or p.frm[:2] != q.to[:2]:     # 안 이어졌거나 제자리가 아님
                continue
            if (q.to[2] - p.frm[2]) % 4 == 2:
                n180 += 1

    # ★ makespan 은 `max(tick)` 이 아니라 **임계 경로**다. ADG 는 순서 제약이라
    #   마지막 동작의 시작 틱이 실제 완료 시각이 아니다. FMS 처리량 비교도
    #   이 값을 쓴다 (isaac_drive 가 info["throughput"] 을 이걸로 낸다).
    #   단위는 **초**다 (틱이 아니다).
    makespan = float(metrics.critical_path(adg, geom))

    # ★ 2026-09-16 정정 — 라벨이 **뒤집혀 있었다.**
    #   `pibt_scene.GEOM_KW` 의 `heading_offset` 은 **0** 이다
    #   (`RobotGeom` 의 dataclass 기본값 2 를 덮어쓴다). 기하가 그걸
    #   뒷받침한다: front_len 0.39 < rear_len 1.11 이라 **구동축이 앞**이고
    #   차체가 뒤로 뻗는데, 그게 정확히 pibt 의
    #   `occupied = {pos, pos - DIRS[h]}` 와 같은 모양이다.
    #
    #       heading_offset = 0  ->  pibt move    = 물리 **전진**
    #                               pibt reverse = 물리 **후진**
    #
    #   초판은 `isaac_drive.py` §PIBT_NOTE(= offset 2 인 경우의 설명)를 보고
    #   반대로 적었고, 그 탓에 「주행의 94.7 % 가 센서 없는 방향」이라는
    #   정반대 결론이 나왔다. 실제로는 RF 3.0 에서 물리 전진이 92.4 % 다.
    #   `contact_frame.py` 가 걸렸던 것과 **같은 덫**이다.
    fwd = kinds.get(D.MOVE, 0)           # pibt 전진 = 물리 전진
    bwd = kinds.get(D.REVERSE, 0)        # pibt 후진 = 물리 후진
    li = info.get("lifelong", {}) if isinstance(info, dict) else {}
    return {
        "seed": seed,
        "actions": len(adg.actions),
        # `move`/`reverse` 는 **pibt 어휘**다 (물리 방향이 아니다).
        "move": fwd, "turn": kinds.get(D.TURN, 0),
        "reverse": bwd, "wait": kinds.get(D.WAIT, 0),
        "n180": n180,
        "makespan": makespan,
        "phys_fwd_pct": (100.0 * fwd / (fwd + bwd)) if (fwd + bwd) else float("nan"),
        "tasks": int(li.get("tasks_done", -1)),
        # FMS 와 맞대는 단위. 임계 경로 기준이라 `realized` 쪽이다.
        "tph": float((info.get("throughput") or {}).get(
            "tasks_per_h_realized", float("nan"))),
    }


# --------------------------------------------------------------------------
# 부모 — 설정마다 자식을 띄우고 표로 묶는다
# --------------------------------------------------------------------------
def run_one(rf, seed):
    """`rf` 가 None 이면 환경변수를 **안 준다** = 로더가 한 줄도 안 돈다 = FMS 기본.

    기준 판이 따로 필요한 이유: `RF=3.0` 은 값이 기본과 같지만 오버라이드
    경로를 **거친다.** 둘 다 같은 결과여야 오버라이드가 무해하다고 말할 수 있다.
    """
    env = dict(os.environ)
    if rf is None:
        env.pop("PIBT_REVERSE_FACTOR", None)
    else:
        env["PIBT_REVERSE_FACTOR"] = repr(rf)
    p = subprocess.run([sys.executable, os.path.abspath(__file__), "--child", str(seed)],
                       env=env, capture_output=True, text=True)
    for line in reversed(p.stdout.splitlines()):
        if line.startswith("{"):
            return json.loads(line)
    sys.stderr.write(f"\n[reverse_sweep] RF={rf} seed={seed} — 계획이 죽었다\n")
    sys.stderr.write((p.stderr or "")[-1500:] + "\n")
    return {"seed": seed, "error": "crash"}


def ok(rows):
    return [r for r in rows if r and "error" not in r]


def mean(rows, key):
    v = [r[key] for r in ok(rows)]
    return sum(v) / len(v) if v else float("nan")


def main():
    if "--child" in sys.argv:
        print(json.dumps(child(int(sys.argv[sys.argv.index("--child") + 1]))))
        return 0

    print(f"REVERSE_FACTOR 스윕 — n {N} · pitch {PITCH} · 지평 {HORIZON}틱"
          f" · 주기 {GAP} · 배터리 {'켬' if BATTERY else '끔'}"
          f" · 배차 {DISPATCH} · 시드 {SEEDS}")
    print(f"  앞 칸 규칙 PIBT_FRONT_RULE={FRONT_RULE}"
          "   ← 주행(run_record.sh)은 4 로 돈다")
    print("  ★ FMS 기본은 3.0 이다. 나머지는 **합의 전 실험값**이다.")

    table = {}
    for rf in RFS:
        rows = []
        for seed in SEEDS:
            sys.stderr.write(f"  ... RF={rf} seed={seed}\n")
            rows.append(run_one(rf, seed))
        table[rf] = rows

    def label(rf):
        return "기본" if rf is None else f"{rf:.1f}"

    print()
    print(f"  {'RF':>5}{'성공':>6}{'순환':>6}{'180도':>7}{'회전':>7}{'물리전진':>10}"
          f"{'전진칸':>8}{'후진칸':>8}{'임계경로':>10}{'태스크':>8}{'tasks/h':>9}")
    for rf in RFS:
        rows = table.get(rf) or []
        good = ok(rows)
        ncyc = sum(1 for r in rows if r and r.get("error") == "cycle")
        head = f"  {label(rf):>5}{len(good):>6}{ncyc:>6}"
        if not good:
            print(head + "   (성공 판 없음 — 평균을 낼 수 없다)")
            continue
        print(head + f"{mean(rows, 'n180'):>7.1f}{mean(rows, 'turn'):>7.1f}"
              f"{mean(rows, 'phys_fwd_pct'):>9.1f}%{mean(rows, 'move'):>8.0f}"
              f"{mean(rows, 'reverse'):>8.0f}{mean(rows, 'makespan'):>9.1f}s"
              f"{mean(rows, 'tasks'):>8.1f}{mean(rows, 'tph'):>9.1f}")
    print(f"  (시드 {len(SEEDS)}개 중 **성공 판만** 평균 · 임계경로 초 ·")
    print("   물리전진 = pibt move/(move+reverse), heading_offset=0 기준)")
    print("   ★ 「후진칸」·「전진칸」 열은 **pibt 어휘**다 — heading_offset 0 에서")
    print("     pibt move 가 물리 전진이므로 「전진칸」열이 물리 전진 칸수다.")
    print("  ★ 「순환」은 도구 실패가 아니라 관측값이다. RF 와 무관하게 전 열에서")
    print("    나면 원인은 RF 가 아니라 그 격자·지평 조합이다.")

    base = ok(table.get(3.0) or [])
    if base:
        print()
        print("  FMS 기본값(3.0) 대비")
        for rf in RFS:
            rows = ok(table.get(rf) or [])
            if not rows or rf == 3.0:
                continue
            d180 = mean(rows, "n180") - mean(base, "n180")
            dms = mean(rows, "makespan") - mean(base, "makespan")
            dfw = mean(rows, "phys_fwd_pct") - mean(base, "phys_fwd_pct")
            dtp = mean(rows, "tph") - mean(base, "tph")
            print(f"    RF {label(rf):<5} 180도 {d180:+6.1f}회 ·"
                  f" 임계경로 {dms:+7.1f}s · 물리전진 {dfw:+5.1f}%p ·"
                  f" tasks/h {dtp:+6.1f}")
    print()
    print("* 임계경로가 안 늘고 180도가 0 이면, 후진 전환의 대가는 틱이 아니라")
    print("  **시야**다 — 그리고 그 시야를 실제로 잃는다. RF 3.0 에서 물리 전진이")
    print("  92.4 % 인데 1.0 으로 내리면 41.8 % 가 된다. 180도 감소(17->3)는")
    print("  전체 로봇·틱의 0.76 % 뿐이라 이 손해를 못 갚는다. (2026-09-16 정정)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
