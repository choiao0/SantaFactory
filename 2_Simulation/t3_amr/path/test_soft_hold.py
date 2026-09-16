# -*- coding: utf-8 -*-
"""4칸 규칙이 **다틱 회전 내내** 걸리는가 — `soft_hold` 검사. Isaac 없이 돈다.

왜
--
`lifelong` 이 `step_h` 에 `soft_hold` 를 안 넘겨서 4칸 규칙이 회전 5틱 중
**1틱만** 걸린다. `soft_next` 가 `_PIBTStepH` 인스턴스마다 새로 생기기
때문이다 (`heading.py:74`). 나머지 4틱은 무방비다.

실주행이 이미 이걸 보여 줬다 — `tools/swing_overlap.py --guard` 가
`guard ∩ 남의 축` 을 회전 5틱 창 내내 센 결과:

        1틱   2틱   3틱   4틱   5틱      총
  s2      0     2    10    22    26      60건
  s5      0     2     8    26    28      64건

**1틱째가 0건**이라 계획기의 검사(`_soft_blocked`)는 정상이고, 고칠 것은
**검사가 사는 기간**이다. 그리고 그 두 시드가 실제로 차체 접촉으로 중단된
판이다.

그래서 이 파일이 답하는 질문은 「진단이 맞나」가 **아니다.** 그건 이미
참이다. 이 파일은 **「그 배치가 구성 가능한가」**를 답한다 — `--guard` 는
이 시드에서 뚫렸다는 표본이고, 여기는 구조다.

검사 다섯
---------
    [C] soft_hold 를 안 주면 뚫리는가            현행 버그의 단위 재현
    [B] soft_hold 를 주면 [C] 의 진입이 막히는가  고치면 닫히는가
    [A] 틱 1 — B 가 이미 soft 칸에 있으면
    [D] 4칸에서만 거부되는 칸이 mA·mB 인가
    [E] 계획 -> ADG — 실행 층이 같은 것을 집행하는가

★ [A] 의 단언은 「A 가 회전 안 한다」가 **아니다.** `_make_room` 이 B 를
  밀어낼 수 있고 빈 격자면 대개 성공한다 — 그건 정상 동작이다. 단언은
  **「A 가 돌았다면 그 틱 끝에 A 의 soft 칸에 남의 축이 없다」**이다.

쓰는 법
-------
    python path/test_soft_hold.py          # 종료 코드 0 = 전부 통과
    python path/test_soft_hold.py -v       # 배치까지 찍는다
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np                                          # noqa: E402
import pibt_core_v2 as pc                                   # noqa: E402

VERBOSE = "-v" in sys.argv or "--verbose" in sys.argv

# ── 격자 규약 ─────────────────────────────────────────────────────────
#   DIRS = [(1,0), (0,1), (-1,0), (0,-1)]   0=N(+r) 1=E(+c) 2=S(-r) 3=W(-c)
#   `pibt.geometry` 의 것을 그대로 쓴다. 여기서 다시 적으면 상류가 바뀔 때
#   조용히 갈린다.
DIRS = pc.DIRS
TURN_TICKS = pc.TURN_TICKS


def blank(n=11):
    """빈 격자 — 가장자리만 막아 `valid_state` 가 경계에서 서게 한다."""
    free = np.zeros((n, n), bool)
    free[1:-1, 1:-1] = True
    return free


def costs(free):
    """균일 비용. `edge_cost` 는 (H,W,4), `wait_cost` 는 (H,W)."""
    H, W = free.shape
    return np.ones((H, W, 4)), np.ones((H, W))


def goal_map(free, goal_state, edge_cost):
    """`goal_state` 로 가는 거리장. B 에게 **soft 칸을 목표로** 줄 때 쓴다.

    ★ 이게 [C] 의 함정이다. B 에게 갈 이유를 안 주면 B 는 제자리에 머물고,
      「안 들어왔다」가 나온다. 그걸 「뚫리지 않는다」로 읽으면 전제를
      틀렸다고 오판한다 (작업서 §3 [C]).
    """
    return pc.dist_map_h(free, goal_state, edge_cost, pc.TURN_COST)


def stay(free, s):
    return pc.stay_map_h(free, s)


def configure_rule(front_diag):
    """4칸(`front_diag=True`) / 앞2(`False`) 로 규칙을 켠다.

    ★ `robot_dims` 를 **안 준다.** 주면 `configure` 가 pitch 게이팅
      (`front_needed`) 을 돌려 pitch 1.2 에서 규칙을 꺼 버린다. 여기서
      재는 것은 「규칙이 켜졌을 때의 동작」이므로 게이팅을 끼우면 안 된다.
    """
    pc.configure(turn_mask=None, front_swing=True, front_diag=front_diag)


# ── 배치 ──────────────────────────────────────────────────────────────
#   A 가 (r, c) 에서 h0 -> h1 로 돈다. 그 soft 칸 하나를 B 의 목표로 준다.
#   B 는 그 칸의 **축**을 노린다 — soft 는 몸이 아니라 축을 막는 규칙이다.
A, B = 0, 1


def scene(front_diag, cell_pick, n=11):
    """A 회전 + B 가 A 의 soft 칸 하나로 축을 옮기려는 배치를 만든다.

    반환 (free, edge_cost, wait_cost, s_a, h1, soft, target, s_b) 또는
    구성이 안 되면 None. `cell_pick(soft, s_a, h1)` 가 노릴 칸을 고른다.
    """
    free = blank(n)
    edge_cost, wait_cost = costs(free)
    r, c, h0, h1 = n // 2, n // 2, 0, 1                 # N -> E
    s_a = (r, c, h0)
    if not (pc.valid_state(free, s_a) and pc.valid_state(free, (r, c, h1))):
        return None
    soft = frozenset(pc.front_cells(r, c, h0, h1))
    if not soft:
        return None
    target = cell_pick(soft, s_a, h1)
    if target is None:
        return None

    # B 를 목표 칸의 **이웃**에 둔다 — 한 틱에 축이 목표로 들어가도록.
    # A 의 몸·스윙과 안 겹치는 자리를 고른다.
    blocked = set(pc.occupied(s_a)) | set(pc.swing_cells(r, c, h0, h1)) | soft
    for hb in range(4):
        dr, dc = DIRS[hb]
        br, bc = target[0] - dr, target[1] - dc          # 여기서 hb 로 전진하면 target
        s_b = (br, bc, hb)
        if not pc.valid_state(free, s_b):
            continue
        if set(pc.occupied(s_b)) & blocked:
            continue
        return free, edge_cost, wait_cost, s_a, h1, soft, target, s_b
    return None


def run_tick(free, edge_cost, wait_cost, s_a, h1, s_b, soft_hold, extra_a):
    """회전 **진행 중**인 A 와, soft 칸을 노리는 B 로 한 틱 돌린다.

    A 는 `busy > 0` 인 상태를 흉내 낸다 — `stay_map_h` 로 제자리에 묶고
    `extra` 에 스윙 칸을 실어 준다. `lifelong` 이 2~5틱째에 하는 것과 같다.
    """
    r, c, h0 = s_a
    states = {A: s_a, B: s_b}
    dists = {A: stay(free, s_a),
             B: goal_map(free, (s_b[0], s_b[1], s_b[2]), edge_cost)}
    # B 의 목표는 아래에서 바꿔 준다 (호출부가 dists[B] 를 덮어쓴다).
    return states, dists


def one_tick(free, edge_cost, wait_cost, states, dists, extra, soft_hold):
    """`step_h` 한 틱. 우선순위는 **A 가 먼저** — 회전 중이 늘 이긴다."""
    prio = [A, B]
    new, cells, _denied = pc.step_h(
        states, dists, edge_cost, wait_cost, free, prio, pc.TURN_COST,
        extra, None, None, 0, (), None, None, soft_hold)
    return new, cells


def build(front_diag, cell_pick, n=11):
    """[C][B] 공용 배치 — A 는 회전 **진행 중**, B 는 `target` 축을 노린다."""
    sc = scene(front_diag, cell_pick, n)
    if sc is None:
        return None
    free, edge_cost, wait_cost, s_a, h1, soft, target, s_b = sc
    r, c, h0 = s_a

    states = {A: s_a, B: s_b}
    # A: 회전 2~5틱째 = 제자리에 묶이고 스윙 칸을 쥔다 (lifelong 의 busy>0)
    extra = {A: frozenset(pc.swing_cells(r, c, h0, h1))}
    dists = {A: stay(free, s_a),
             B: goal_map(free, (target[0], target[1], s_b[2]), edge_cost)}
    hold = {cell: A for cell in soft}
    return dict(free=free, edge_cost=edge_cost, wait_cost=wait_cost,
                states=states, extra=extra, dists=dists, soft=soft,
                target=target, hold=hold, s_a=s_a, s_b=s_b, h1=h1)


def axle_in_soft(new, soft, me=B):
    """B 의 **축**이 soft 칸에 놓였나. soft 는 몸이 아니라 축을 막는다."""
    return new[me][:2] in soft


def show(tag, sc, new):
    if not VERBOSE:
        return
    print(f"      [{tag}] A {sc['s_a']} -> {new[A]}   B {sc['s_b']} -> {new[B]}")
    print(f"            soft {sorted(sc['soft'])}   목표 {sc['target']}")


# ── [C] soft_hold 를 안 주면 뚫리는가 ─────────────────────────────────
def test_C():
    """현행 버그의 단위 재현. **전제는 이미 실주행으로 참이다** (124건).

    그러니 실패하면 진단이 아니라 **테스트 구성**을 먼저 의심한다 —
    십중팔구 B 가 갈 이유(dists)를 못 받은 것이다.
    """
    configure_rule(front_diag=True)
    holes = []
    for name, pick in PICKS.items():
        sc = build(front_diag=True, cell_pick=pick)
        if sc is None:
            continue
        new, _ = one_tick(sc["free"], sc["edge_cost"], sc["wait_cost"],
                          sc["states"], sc["dists"], sc["extra"], None)
        show(f"C/{name}", sc, new)
        if axle_in_soft(new, sc["soft"]):
            holes.append(name)
    ok = bool(holes)
    print(f"  [C] soft_hold 없음 → 뚫린 칸 {holes or '없음'}")
    if not ok:
        print("      ★ 실패. 실주행은 124건이 뚫렸으므로 진단이 아니라")
        print("        테스트 구성을 의심할 것 — B 가 soft 칸을 목표로")
        print("        받았는지(dists), A 가 정말 busy 상태인지(extra).")
    return ok


# ── [B] soft_hold 를 주면 막히는가 ────────────────────────────────────
def test_B():
    """[C] 와 **같은 배치**에 `soft_hold` 만 채운다. 그것만이 차이다."""
    configure_rule(front_diag=True)
    leaks = []
    tested = []
    for name, pick in PICKS.items():
        sc = build(front_diag=True, cell_pick=pick)
        if sc is None:
            continue
        tested.append(name)
        new, _ = one_tick(sc["free"], sc["edge_cost"], sc["wait_cost"],
                          sc["states"], sc["dists"], sc["extra"], sc["hold"])
        show(f"B/{name}", sc, new)
        if axle_in_soft(new, sc["soft"]):
            leaks.append(name)
    ok = bool(tested) and not leaks
    print(f"  [B] soft_hold 있음 → 뚫린 칸 {leaks or '없음'}"
          f"   (검사 {len(tested)}칸)")
    return ok


# ── [A] 틱 1 — 회전을 **시작하는** 틱 ─────────────────────────────────
def test_A():
    """B 가 이미 soft 칸에 서 있을 때 A 가 회전을 시작하려 한다.

    ★ 단언은 「A 가 회전 안 한다」가 아니다. `_make_room` 이 B 를 밀어낼
      수 있고 빈 격자면 대개 성공한다 — 정상 동작이다.
      단언: **A 가 돌았다면 그 틱 끝에 A 의 soft 칸에 남의 축이 없다.**
    """
    configure_rule(front_diag=True)
    n = 11
    free = blank(n)
    edge_cost, wait_cost = costs(free)
    bad = []
    checked = 0
    for r in (n // 2,):
        for c in (n // 2,):
            for h0 in range(4):
                for h1 in ((h0 + 1) % 4, (h0 - 1) % 4):
                    if not pc.turn_ok(free, r, c, h0, h1):
                        continue
                    soft = frozenset(pc.front_cells(r, c, h0, h1))
                    body = set(pc.occupied((r, c, h0))) | set(
                        pc.swing_cells(r, c, h0, h1))
                    for cell in sorted(soft):
                        # B 를 그 soft 칸에 **축**으로 세운다
                        placed = None
                        for hb in range(4):
                            s_b = (cell[0], cell[1], hb)
                            if not pc.valid_state(free, s_b):
                                continue
                            if set(pc.occupied(s_b)) & body:
                                continue
                            placed = s_b
                            break
                        if placed is None:
                            continue
                        checked += 1
                        states = {A: (r, c, h0), B: placed}
                        dists = {A: goal_map(free, (r, c, h1), edge_cost),
                                 B: stay(free, placed)}
                        new, _ = one_tick(free, edge_cost, wait_cost, states,
                                          dists, {}, None)
                        turned = new[A] == (r, c, h1)
                        if turned and new[B][:2] in soft:
                            bad.append((h0, h1, cell, new[B]))
    ok = not bad and checked > 0
    print(f"  [A] 틱 1 — 회전했는데 soft 에 축이 남은 경우 {len(bad)}건"
          f"   (검사 {checked}개)")
    if bad and VERBOSE:
        for h0, h1, cell, sb in bad[:5]:
            print(f"      h{h0}->h{h1}  soft {cell}  B {sb}")
    return ok


# ── [D] 4칸에서만 거부되는 칸이 mA·mB 인가 ────────────────────────────
def test_D():
    """`front_diag` 를 끄고 켜며 soft 집합이 정확히 mA·mB 만큼 는지 본다.

    설계서 §2-3 의 「mA·mB 는 스윕 **밖**(0/8)」과 대조한다 — 그 두 칸이
    `extra`(hard) 로는 절대 안 덮이므로 **`soft_hold` 만이 막을 수 있다.**
    """
    n = 11
    free = blank(n)
    r, c = n // 2, n // 2
    bad = []
    outside = 0
    total = 0
    for h0 in range(4):
        for h1 in ((h0 + 1) % 4, (h0 - 1) % 4):
            configure_rule(front_diag=False)
            two = frozenset(pc.front_cells(r, c, h0, h1))
            configure_rule(front_diag=True)
            four = frozenset(pc.front_cells(r, c, h0, h1))
            d1, d2 = DIRS[h0], DIRS[h1]
            mA = (r + d1[0] - d2[0], c + d1[1] - d2[1])
            mB = (r - d1[0] + d2[0], c - d1[1] + d2[1])
            if four - two != {mA, mB}:
                bad.append((h0, h1, sorted(four - two), sorted({mA, mB})))
            swept = set(pc.swing_cells(r, c, h0, h1)) | set(
                pc.occupied((r, c, h0))) | set(pc.occupied((r, c, h1)))
            for m in (mA, mB):
                total += 1
                if m not in swept:
                    outside += 1
    ok = not bad and outside == total and total > 0
    print(f"  [D] 4칸 − 앞2 = mA·mB   어긋남 {len(bad)}건"
          f"   ·  스윕 밖 {outside}/{total}")
    if bad and VERBOSE:
        for h0, h1, got, want in bad[:4]:
            print(f"      h{h0}->h{h1}  얻음 {got}  기대 {want}")
    return ok


# ── [E] 계획 -> ADG — 실행 층이 같은 것을 집행하는가 ──────────────────
def test_E():
    """A 가 회전하고 B 가 그 soft 칸을 **지나는** history 로 ADG 를 만든다.

    ★ 이 검사의 성격이 2026-09-16 에 바뀌었다. 접촉 건의 B 는 `move` 액션을
      갖고 있었다 = **지나가는 B** 다. 그러면 `by_axle` 에 들어가므로 ADG
      규칙 ②(`p.guard x by_axle`)가 걸었어야 한다. 「걸렸어야 할 간선이 왜
      안 묶었나」를 여기서 묻는다.

    [A]~[D] 가 다 통과해도 이게 없으면 **실행은 그대로다** — 계획을 고쳐도
    실행 재배치로 같은 배치가 다시 생긴다. 층이 다르기 때문이다 (작업서 §1).
    """
    from isaac_drive import RobotGeom, build_adg, extract_actions   # noqa: E402

    configure_rule(front_diag=True)
    n = 11
    free = blank(n)
    r, c, h0, h1 = n // 2, n // 2, 0, 1
    soft = sorted(pc.front_cells(r, c, h0, h1))
    body = set(pc.occupied((r, c, h0))) | set(pc.swing_cells(r, c, h0, h1))

    # ADG 쪽 스위치를 계획기와 **같게** 맞춘다. 갈리면 `_check_front_swing`
    # 이 잡는다 — 그게 이 검사가 우연히 통과하는 걸 막아 준다.
    geom = RobotGeom(pitch=1.0, front_swing=True, front_diag=True,
                     heading_offset=0)

    results = []
    for target in soft:
        if target in body:
            continue
        # B 가 target 을 **지나가게** 한다: 밖 -> target -> 밖.
        hb = None
        for k in range(4):
            dr, dc = DIRS[k]
            cand = (target[0] - dr, target[1] - dc)
            nxt = (target[0] + dr, target[1] + dc)
            if not (pc.valid_state(free, (cand[0], cand[1], k))
                    and pc.valid_state(free, (nxt[0], nxt[1], k))):
                continue
            if set(pc.occupied((cand[0], cand[1], k))) & body:
                continue
            if set(pc.occupied((nxt[0], nxt[1], k))) & body:
                continue
            hb = k
            break
        if hb is None:
            continue
        dr, dc = DIRS[hb]
        b0 = (target[0] - dr, target[1] - dc, hb)
        b1 = (target[0], target[1], hb)
        b2 = (target[0] + dr, target[1] + dc, hb)

        history = [{A: (r, c, h0), B: b0},
                   {A: (r, c, h1), B: b1},     # A 회전 · B 축이 soft 칸으로
                   {A: (r, c, h1), B: b2}]
        chains, _order, _info = extract_actions(history, geom)
        adg = build_adg(chains, geom)

        edges = set()
        for uid, succ in adg.succs.items():
            for v in succ:
                edges.add((uid, v))
                edges.add((v, uid))          # 방향은 안 본다 — 묶였는지만

        # ★ 규칙 ② **만** 센다. 로봇 간 간선을 통째로 세면 규칙 ①(몸\łł)
        #   으로도 통과해 버려, 축 규칙이 꺼져 있어도 초록불이 된다.
        want = have = 0
        for pa in adg.actions:
            for qa in adg.actions:
                if pa.agent == qa.agent or not (pa.guard & qa.axle):
                    continue
                want += 1
                have += (pa.uid, qa.uid) in edges
        results.append((target, have, want))

    if not results:
        print("  [E] 배치를 못 만들었다 (soft 가 전부 몸과 겹친다)")
        return False

    missing = [t for t, have, want in results if want == 0 or have < want]
    ok = not missing
    got = "  ".join(f"{t}:{h}/{w}" for t, h, w in results)
    print(f"  [E] 계획 -> ADG   규칙 ② 간선 (건/기대)   {got}")
    if VERBOSE:
        for t, have, want in results:
            print(f"      soft {t}  guard∩상대축 {want}쌍  간선 {have}개")
    if missing:
        print(f"      ★ 규칙 ② 가 안 걸린 칸 {missing}")
        print("        계획을 고쳐도 **실행 재배치로 같은 일이 난다.**")
        print("        `lifelong` 수정만으로는 안 끝난다는 뜻이다.")
    return ok


# ── soft 칸 고르는 법 넷 ──────────────────────────────────────────────
def _pick(which):
    def f(soft, s_a, h1):
        r, c, h0 = s_a
        d1, d2 = DIRS[h0], DIRS[h1]
        table = {
            "f0": (r + d1[0], c + d1[1]),
            "f1": (r + d2[0], c + d2[1]),
            "mA": (r + d1[0] - d2[0], c + d1[1] - d2[1]),
            "mB": (r - d1[0] + d2[0], c - d1[1] + d2[1]),
        }
        cell = table[which]
        return cell if cell in soft else None
    return f


PICKS = {k: _pick(k) for k in ("f0", "f1", "mA", "mB")}


def main():
    print("soft_hold 검사 — 4칸 규칙이 회전 5틱 내내 걸리는가")
    print(f"  TURN_TICKS={TURN_TICKS}  (회전 1틱 + 진행 {TURN_TICKS - 1}틱)")
    print()
    results = [("C", test_C()), ("B", test_B()), ("A", test_A()),
               ("D", test_D()), ("E", test_E())]
    print()
    failed = [k for k, v in results if not v]
    if failed:
        print(f"★ 실패: {', '.join(failed)}")
        return 1
    print("전부 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
