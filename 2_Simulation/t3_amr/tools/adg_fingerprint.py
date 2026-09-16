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
from pibt_core import MOVE_TICKS, TURN_TICKS, run_h  # noqa: E402
import isaac_drive as D                  # noqa: E402
import pibt_scene                        # noqa: E402

MAP = os.environ["MAP"]
N = int(os.environ.get("N", "12"))
# ★ 1.2 -> 1.0 (-224). 기준선은 2026-09-15(`5bd83ef`)부터 pitch 1.0 인데
#   기본값만 1.2 로 남아 있어, 맨손으로 돌리면 **설정 불일치로 죽는다.**
#   그 커밋 본문도 「옛 기준은 pitch 1.2 판이라 설정 불일치로 비교 자체가 안
#   됐다」고 적고 있다 — 기본값을 안 옮겨서 같은 함정이 남아 있었다.
PITCH = float(os.environ.get("PIBT_PITCH", "1.0"))
SEEDS = [int(x) for x in os.environ.get("SEEDS", "1,2,4").split(",")]
MODE = os.environ.get("MODE", "lifelong")        # lifelong | oneshot
# [patch_ticks] ★ 2026-09-15 (-211) 정정. 이 주석이 「우리 경로(step_h)에서
#   전진은 1틱」이라고 적고 있었는데 이제 아니다 — `lifelong` 을 커널 틱
#   모델로 맞추면서 전진도 MOVE_TICKS(4) 틱이 됐다.
#
#   그래서 지평·주기도 4배다 (315/15 -> 1260/60). 계획 초는 그대로 350 s 다.
#   둘 다 안 바꾸면 이 도구가 **4배 짧은 구간**의 지문을 뜨게 된다.
HORIZON = int(os.environ.get("HORIZON", "1260"))
GAP = int(os.environ.get("GAP", "60"))
# 기준 파일. 설정이 다르면 **다른 파일**에 떠야 한다 — 4칸 켠 기준과 끈 기준은
# 간선 수가 달라 한 파일에 못 담는다 (-224).
#
#   ★ 기준선의 전제는 `PIBT_FRONT_RULE=4` 다. 이건 셸 환경변수라 여기서
#     기본값을 못 준다 (`pibt_scene` 이 직접 읽는다). 안 주고 돌리면 4칸이
#     꺼져 `guard` 가 비고, 그러면 ADG 규칙 ② 가 아예 안 돌아 **전혀 다른
#     간선 수**가 나온다. 아래 `_collect` 가 머리말에 그 값을 찍는다.
OUT = os.environ.get("FP_OUT") or os.path.join(
    os.environ["W"], "tools", "adg_fingerprint.json")


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
        # ★ 간선을 바꾸는 스위치는 **지문에 같이 적는다** (-224).
        #   `PIBT_ADG_SLIM` 은 규칙 ② 를 인접 쌍만 걸게 해서 간선을 84~90 %
        #   줄인다 (도달 관계·실행 시각은 동일, `tools/adg_edge_audit.py`).
        #   적어 두지 않으면 나중에 `edges_sig` 가 달라졌을 때 「규칙이
        #   깨졌나」와 「스위치가 달랐나」를 못 가른다.
        # ★ 기본값을 `build_adg` 와 **같게** 둬야 한다 (거기가 "1" 이다).
        #   "0" 으로 두면 환경변수를 안 줬을 때 실제로는 slim 으로 지었는데
        #   기록은 「안 썼다」가 되어, 지문이 거짓말을 한다. 2026-09-16 에
        #   실제로 그렇게 적혔다.
        "slim": os.environ.get("PIBT_ADG_SLIM", "1"),
        "front_rule": os.environ.get("PIBT_FRONT_RULE", ""),
    }


# 종료 코드 — CI 가 이걸로 판단한다.
#   0  통과 (지문 동일, 또는 --save 성공)
#   1  **지문이 다르다** — 규칙이 꺼진 상태에서는 나면 안 되는 값이다
#   2  쓰기 오류 (기준 없음 · 설정 불일치)
EXIT_OK, EXIT_DIFF, EXIT_USAGE = 0, 1, 2


def _collect():
    """시드를 전부 돌려 지문을 찍고 (지문표, 설정) 을 돌려준다."""
    print(f"모드 {MODE}  대수 {N}  pitch {PITCH}  시드 {SEEDS}")
    # ★ 간선을 바꾸는 둘은 **머리말에 찍는다.** 표만 보고 「왜 값이 다르지」를
    #   묻게 두면 안 된다 — 2026-09-16 에 설정이 다른 기준선을 덮었다.
    _fr = os.environ.get("PIBT_FRONT_RULE", "")
    print(f"PIBT_FRONT_RULE={_fr or '(안 줌 — 4칸 꺼짐)'}  "
          f"PIBT_ADG_SLIM={os.environ.get('PIBT_ADG_SLIM', '1')}")
    if not _fr:
        print("★ 4칸이 꺼져 있다. 기준선이 4칸 켠 것이면 값이 안 맞는다 —\n"
              "  `PIBT_FRONT_RULE=4` 를 주고 다시 돌릴 것.")
    print(f"지평 {HORIZON}틱 · 주기 {GAP}틱   "
          f"(전진 {MOVE_TICKS}틱 · 회전 {TURN_TICKS}틱)\n")
    print(f"{'시드':>5}{'액션':>8}{'type1':>8}{'type2':>8}{'비순환':>8}"
          f"{'actions_sig':>18}{'edges_sig':>18}")
    cur = {}
    for s in SEEDS:
        fp = fingerprint(build(s))
        cur[str(s)] = fp
        print(f"{s:>5}{fp['actions']:>8}{fp['type1']:>8}{fp['type2']:>8}"
              f"{str(fp['acyclic']):>8}{fp['actions_sig']:>18}{fp['edges_sig']:>18}")
    return cur, {"mode": MODE, "n": N, "pitch": PITCH, "horizon": HORIZON,
                 "gap": GAP, "seeds": SEEDS, "fp": cur}


def _save(meta):
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"\n기준 저장: {OUT}")
    print("  ☠ **덮어썼다면 되돌릴 수 있는지 먼저 보라** — `git diff` 에서")
    print("    `actions` 나 `actions_sig` 가 달라졌으면 그 기준선은 **다른")
    print("    설정**에서 뜬 것이라 덮으면 안 되는 파일이었다는 뜻이다.")
    print("    (2026-09-16 에 pitch 1.0·4칸 켠 기준선을 1.2·꺼짐으로 덮었다.")
    print("     `git checkout` 으로 되돌리고 `FP_OUT` 으로 새 파일에 떴다.)")
    print(f"★ 지금 **설정도 같이 저장됐다** — slim={os.environ.get('PIBT_ADG_SLIM', '1')} · "
          f"front_rule={os.environ.get('PIBT_FRONT_RULE', '') or '(꺼짐)'}")
    print("  기준은 「코드를 고치기 전」이 아니라 **이 설정에서의 값**이다.")
    print("  `git diff` 로 무엇이 달라졌는지 보고 커밋할 것.")
    if not os.environ.get("PIBT_FRONT_RULE"):
        print("\n  ※ 4칸 규칙이 꺼져 있어 `guard` 가 전부 비고, 그러면 ADG")
        print("    규칙 ② 가 한 번도 안 돈다 — `PIBT_ADG_SLIM` 이 이 기준선에")
        print("    **영향을 줄 수 없다.** slim 을 지키려면 4칸을 켠 기준이 따로")
        print("    필요하다:")
        print("      PIBT_FRONT_RULE=4 PIBT_PITCH=1.0 \\")
        print("        FP_OUT=$W/tools/adg_fingerprint_front4.json \\")
        print("        python tools/adg_fingerprint.py --save")
    return EXIT_OK


def _load_base(meta):
    """기준을 읽고 설정이 같은지 본다. 못 쓰면 (None, 종료코드)."""
    if not os.path.exists(OUT):
        print(f"★ 기준이 없습니다. 먼저 --save 로 떠 두세요: {OUT}")
        return None, EXIT_USAGE
    with open(OUT, encoding="utf-8") as f:
        base = json.load(f)
    for k in ("mode", "n", "pitch", "horizon", "gap", "seeds"):
        if base.get(k) != meta[k]:
            print(f"★ 설정이 기준과 다릅니다: {k} {base.get(k)} != {meta[k]}")
            return None, EXIT_USAGE
    return base, EXIT_OK


def _compare(base, cur):
    """시드별로 대조하고 다른 개수를 돌려준다."""
    bad = 0
    print()
    for s in SEEDS:
        b, c = base["fp"].get(str(s)), cur[str(s)]
        if b is None:
            print(f"  seed {s}: 기준에 없음")
            bad += 1
            continue
        diff = [k for k in c if b.get(k) != c[k]]
        if not diff:
            print(f"  seed {s}   동일")
            continue
        bad += 1
        print(f"  seed {s} ★ 다름: {diff}")
        for k in diff:
            print(f"      {k:<12} 기준 {b.get(k)}  ->  현재 {c[k]}")
    return bad


def main():
    cur, meta = _collect()
    if "--save" in sys.argv:
        return _save(meta)

    base, rc = _load_base(meta)
    if base is None:
        return rc

    bad = _compare(base, cur)
    if bad:
        print(f"\n★ {bad}개 시드가 기준과 다릅니다 — "
              f"스위치가 꺼진 상태에서는 완전히 같아야 합니다.")
        return EXIT_DIFF
    print("\n전부 동일 — §7 항목 1 통과.")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
