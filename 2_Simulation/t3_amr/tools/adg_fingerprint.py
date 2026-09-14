# -*- coding: utf-8 -*-
"""ADG 기준 지문 — 축 규칙 변경 전후가 **비트 단위로 같은지** 확인한다.

설계서 `docs/2026-09-14_ADG_축규칙_구조변경_설계.md` §7 항목 1 이 요구하는
회귀 검사다. 스위치가 꺼져 있으면 `soft = ∅` → `hard == cells` → 간선이
오늘과 완전히 같아야 한다.

    ★ 코드를 한 줄이라도 고치기 **전에** 기준을 떠 둬야 한다.
      고친 뒤에 뜨면 비교할 대상이 없다.

    python tools/adg_fingerprint.py --save      기준 저장 (변경 전 1회)
    python tools/adg_fingerprint.py             현재와 기준 비교

★ `hash()` 를 쓰지 않는다. 파이썬 내장 해시는 문자열이 섞이면
  `PYTHONHASHSEED` 때문에 **프로세스마다 값이 다르다.** `Action.kind` 가
  문자열이라 그대로 걸린다. `hashlib` 로 정규 직렬화를 해시한다.
"""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.environ["W"], "path"))
import pibt_core_v2                      # noqa: F401
from pibt_core import TURN_TICKS, run_h  # noqa: E402
import isaac_drive as D                  # noqa: E402
import pibt_scene                        # noqa: E402

MAP = os.environ["MAP"]
N = int(os.environ.get("N", "12"))
PITCH = float(os.environ.get("PIBT_PITCH", "1.2"))
SEEDS = [int(x) for x in os.environ.get("SEEDS", "1,2,4").split(",")]
MODE = os.environ.get("MODE", "lifelong")        # lifelong | oneshot
# [patch_ticks] 우리 경로(step_h)에서 전진은 1틱, 회전만 TURN_TICKS(5)틱이다.
#   -194 이후 같은 일에 드는 틱이 1.3~1.6배 늘었다(회전 빈도에 따라).
#   지평은 그대로 두고 기준 지문을 다시 떴다 — 이 값은 비교 기준일 뿐이라
#   절대량이 중요하지 않다.
HORIZON = int(os.environ.get("HORIZON", "315"))
GAP = int(os.environ.get("GAP", "15"))
OUT = os.path.join(os.environ["W"], "tools", "adg_fingerprint.json")


def _sha(items) -> str:
    """정규 직렬화 -> sha256. 순서에 안 흔들리게 정렬해서 넣는다."""
    h = hashlib.sha256()
    for s in sorted(items):
        h.update(s.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


def build(seed):
    if MODE == "lifelong":
        geom, free, starts, goals = pibt_scene.setup_lifelong(
            MAP, N, PITCH, seed, "cross", verbose=False)
        zone = pibt_scene.charge_zone_cells(free, geom)
        adg, order, history, info = D.plan_and_build_lifelong(
            free, starts, goals, geom, horizon=HORIZON, seed=seed,
            order_gap=GAP, battery=True, dispatch="fms", zone_cells=zone,
            order_end=None, docks=pibt_scene.charge_docks(free, geom))
        return adg
    geom, free, starts, goals = pibt_scene.setup(MAP, N, PITCH, seed, "cross")
    history, _ = run_h(free, starts, goals, max_steps=300)
    chains, order, _ = D.extract_actions(history, geom)
    return D.build_adg(chains)


def fingerprint(adg) -> dict:
    acts = [f"{a.agent}|{a.tick}|{a.kind}|{a.frm}|{a.to}|{sorted(a.cells)}"
            for a in adg.actions]
    # uid 는 생성 순서에 달린 값이라 지문에 쓰지 않는다. (agent, idx) 로 식별한다.
    uid2 = {a.uid: (a.agent, a.idx) for a in adg.actions}
    edges = [f"{uid2[p]}->{uid2[n]}"
             for p in adg.succs for n in adg.succs[p]]
    return {
        "actions": len(adg.actions),
        "type1": adg.type1,
        "type2": adg.type2,
        "acyclic": adg.topological_order() is not None,
        "actions_sig": _sha(acts),
        "edges_sig": _sha(edges),
    }


def main():
    save = "--save" in sys.argv
    cur = {}
    print(f"모드 {MODE}  대수 {N}  pitch {PITCH}  시드 {SEEDS}")
    print(f"지평 {HORIZON}틱 · 주기 {GAP}틱   (전진 1틱 · 회전 {TURN_TICKS}틱)\n")
    print(f"{'시드':>5}{'액션':>8}{'type1':>8}{'type2':>8}{'비순환':>8}"
          f"{'actions_sig':>18}{'edges_sig':>18}")
    for s in SEEDS:
        fp = fingerprint(build(s))
        cur[str(s)] = fp
        print(f"{s:>5}{fp['actions']:>8}{fp['type1']:>8}{fp['type2']:>8}"
              f"{str(fp['acyclic']):>8}{fp['actions_sig']:>18}{fp['edges_sig']:>18}")

    meta = {"mode": MODE, "n": N, "pitch": PITCH, "horizon": HORIZON,
            "gap": GAP, "seeds": SEEDS, "fp": cur}

    if save:
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1, sort_keys=True)
        print(f"\n기준 저장: {OUT}")
        print("★ 이 파일은 **코드를 고치기 전** 상태다. 커밋해 둘 것.")
        return 0

    if not os.path.exists(OUT):
        raise SystemExit(f"★ 기준이 없습니다. 먼저 --save 로 떠 두세요: {OUT}")
    with open(OUT, encoding="utf-8") as f:
        base = json.load(f)

    for k in ("mode", "n", "pitch", "horizon", "gap", "seeds"):
        if base.get(k) != meta[k]:
            raise SystemExit(f"★ 설정이 기준과 다릅니다: {k} "
                             f"{base.get(k)} != {meta[k]}")

    bad = 0
    print()
    for s in SEEDS:
        b, c = base["fp"].get(str(s)), cur[str(s)]
        if b is None:
            print(f"  seed {s}: 기준에 없음"); bad += 1; continue
        diff = [k for k in c if b.get(k) != c[k]]
        if diff:
            bad += 1
            print(f"  seed {s} ★ 다름: {diff}")
            for k in diff:
                print(f"      {k:<12} 기준 {b.get(k)}  ->  현재 {c[k]}")
        else:
            print(f"  seed {s}   동일")
    if bad:
        raise SystemExit(f"\n★ {bad}개 시드가 기준과 다릅니다 — "
                         f"스위치가 꺼진 상태에서는 완전히 같아야 합니다.")
    print("\n전부 동일 — §7 항목 1 통과.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
