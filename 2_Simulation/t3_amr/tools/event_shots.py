# -*- coding: utf-8 -*-
"""런 로그의 **사건 장부**를 읽어 「어디를 다시 찍을지」로 바꾼다 (S15P21A106-267).

    python tools/event_shots.py logs/record_r13fpv.log
    python tools/event_shots.py logs/*.log --kind contact --pad 3

왜
--
런이 내는 것은 개수뿐이었다 — `contact_events=1`. 「몇 번」으로는 그 장면을 다시
못 찍는다. `isaac_drive` 가 사건마다 한 줄씩 남기게 했고(`[event] …`), 이 파일이
그것을 **촬영 명령**으로 옮긴다.

    [event] kind=contact t=338.6 x=46.20 y=50.83 a=5 b=12 gap=-0.004
      -> PIBT_SPOT=46.20,50.83 로 씬을 굽고, 시뮬 335.6~341.6 초를 느리게 찍는다

Isaac 도 numpy 도 안 쓴다 — 로그만 읽는다.

무엇이 장부에 남나
------------------
    contact   로봇끼리 차체가 닿았다 (칸은 안 겹쳤는데 몸이 닿는 그 사건)
    rack      차체가 랙을 파고들었다
    zone      피커 구역에 들어갔다 (FMS-42: 벽이 아니라 통행 규칙이다)

☹ 가속·감속·회전 슬립은 여기 안 남는다. 그것들은 **사건이 아니라 상시 성질**이라
  영상보다 `tools/{measure_seq,stop_error,turn_error}.py` 의 수치가 맞다.
"""
import argparse
import collections
import glob
import os
import re
import sys

EVENT = re.compile(r"\[event\]\s+(.*)$")
KV = re.compile(r"(\w+)=(-?[0-9.]+|\w+)")

KIND_KO = {"contact": "차체 접촉", "rack": "랙 걸침", "zone": "피커 구역 진입"}


def parse(paths):
    out = []
    for p in paths:
        try:
            with open(p, "rb") as f:
                text = f.read().decode("utf-8", "replace")
        except OSError as e:
            print(f"★ 못 읽음 {p}: {e}", file=sys.stderr)
            continue
        for line in text.splitlines():
            m = EVENT.search(line)
            if not m:
                continue
            d = {}
            for k, v in KV.findall(m.group(1)):
                try:
                    d[k] = float(v)
                except ValueError:
                    d[k] = v
            if "t" in d and "x" in d and "y" in d:
                d["_log"] = os.path.basename(p)
                out.append(d)
    out.sort(key=lambda e: e["t"])
    return out


def cluster(events, gap):
    """같은 자리·같은 종류가 잇달아 나면 **한 장면**으로 묶는다.

    60 Hz 에서 한 번 닿으면 여러 줄이 나온다. 촬영은 장면 단위라 그대로 두면
    같은 데를 여러 번 찍게 된다.
    """
    groups = []
    for e in events:
        for g in groups:
            if (g["kind"] == e["kind"] and e["t"] - g["t1"] <= gap
                    and abs(g["x"] - e["x"]) < 3.0 and abs(g["y"] - e["y"]) < 3.0):
                g["t1"] = e["t"]
                g["n"] += 1
                g["worst"] = max(g["worst"], abs(e.get("pen", 0.0)),
                                 abs(min(0.0, e.get("gap", 0.0))))
                break
        else:
            groups.append({"kind": e["kind"], "t0": e["t"], "t1": e["t"],
                           "x": e["x"], "y": e["y"], "n": 1,
                           "a": e.get("a"), "b": e.get("b"), "_log": e["_log"],
                           "worst": max(abs(e.get("pen", 0.0)),
                                        abs(min(0.0, e.get("gap", 0.0))))})
    return groups


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="+", help="런 로그 (glob 가능)")
    ap.add_argument("--kind", default="", help="contact|rack|zone 중 하나만")
    ap.add_argument("--gap", type=float, default=2.0, help="같은 장면으로 묶을 간격 [시뮬초]")
    ap.add_argument("--pad", type=float, default=3.0, help="앞뒤 여유 [시뮬초]")
    ap.add_argument("--top", type=int, default=10, help="깊은 것부터 이만큼만")
    a = ap.parse_args()

    paths = [p for g in a.logs for p in (glob.glob(g) or [g])]
    events = parse(paths)
    if not events:
        print("사건이 없습니다.")
        print("  · 이 런이 `[event]` 를 남기기 전 코드일 수 있습니다 (PIBT_EVENT_LOG=1 기본)")
        print("  · 또는 정말 접촉·침투가 0 입니다 — 그 자체가 결과입니다")
        return 1
    if a.kind:
        events = [e for e in events if e.get("kind") == a.kind]

    groups = cluster(events, a.gap)
    by_kind = collections.Counter(g["kind"] for g in groups)

    print("═" * 74)
    print("사건 %d줄 -> 장면 %d개   %s"
          % (len(events), len(groups),
             " · ".join(f"{KIND_KO.get(k, k)} {v}" for k, v in by_kind.most_common())))
    print("═" * 74)

    groups.sort(key=lambda g: (-g["worst"], g["t0"]))
    for i, g in enumerate(groups[:a.top], 1):
        who = f"agent{g['a']:.0f}" if g.get("a") is not None else "?"
        if g.get("b") is not None:
            who += f"+agent{g['b']:.0f}"
        print("\n[%d] %s  t=%.1f~%.1fs  (%.2f, %.2f)  %s  %d줄  최대 %.1f mm"
              % (i, KIND_KO.get(g["kind"], g["kind"]), g["t0"], g["t1"],
                 g["x"], g["y"], who, g["n"], g["worst"] * 1000))
        t0, t1 = max(0.0, g["t0"] - a.pad), g["t1"] + a.pad
        print("    씬 굽기 :  PIBT_SPOT=%.1f,%.1f PIBT_SPOT_D=6 bash run_record.sh 13 --rebuild"
              % (g["x"], g["y"]))
        print("    잘라내기:  python tools/event_shots.py --cut %s %.1f %.1f"
              % (g["kind"], t0, t1))
        print("    (프레임 파일명이 `f_<시뮬시각 0.01초>` 라 시각으로 바로 고른다)")

    if len(groups) > a.top:
        print("\n… %d개 더 (--top 으로 늘린다)" % (len(groups) - a.top))
    print()
    print("☹ 가속·감속·회전 슬립은 장부에 안 남는다 — 사건이 아니라 상시 성질이다.")
    print("  그쪽은 tools/{measure_seq,stop_error,turn_error}.py 의 수치로 낸다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
