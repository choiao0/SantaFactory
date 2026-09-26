# -*- coding: utf-8 -*-
"""DES 궤적에서 **피크 10분**을 잘라 물리 검증용 구간 파일로 만든다 (S15P21A106-275).

왜
--
물리 검증은 DES 6시간 전체가 아니라 **가장 바쁜 10분**을 본다. Isaac 은 그 10분을
실제 시간으로(시뮬 1초 = 현실 1초) 돌리고, 각 로봇은 **그 시점의 자리에서** 출발해야
한다. 이 도구가 전체 내보내기(`SIM_EXPORT_ISAAC=1` → `trajectories.json`)에서

    [t0 − 워밍업, t0 + 창 + 꼬리]

만 떼어 `slice` 블록을 붙인다. 받는 쪽은 `path/fms_traj.load_history` 다.

피크 기준 (`tasks_done`)
------------------------
창 안에서 **완료된 태스크 수**가 가장 많은 10분. `--step` 초 간격으로 창을 밀어 보고,
같으면 이른 쪽을 고른다. 태스크는 `completed` 틱으로 센다 — 로봇 번호는 없어도 된다.

    python tools/des_slice.py <export 폴더> -o slice.json.gz
    python tools/des_slice.py <export 폴더> --t0 3600 -o slice.json    # 시작을 직접 준다

☹ 워밍업을 두는 이유는 `fms_traj.SLICE_KEYS` 주석을 보라 (FMS 는 여러 틱 동작을
  첫 틱에 끝난 자리로 적는다 — t0 에 딱 자르면 움직이던 로봇이 앞선 자리에 선다).
☹ 꼬리(`--tail`)는 창 끝 뒤 계획을 조금 더 싣는다. 물리가 늦으면 창 끝에도 창 안
  동작이 남는데, 그 뒤 동작까지 있어야 「다 끝나서 멈춘」 것과 「밀린」 것이 갈린다.
"""
import argparse
import base64
import bisect
import gzip
import json
import os
import sys

DEFAULT_WINDOW_S = 600.0
DEFAULT_WARMUP_S = 60.0
DEFAULT_TAIL_S = 60.0
DEFAULT_STEP_S = 10.0


def pick_peak(completed_s, horizon_s, window_s=DEFAULT_WINDOW_S,
              warmup_s=DEFAULT_WARMUP_S, step_s=DEFAULT_STEP_S):
    """완료 시각 목록 → (t0, 창 안 완료 수). 창이 [t0, t0+window) 이고 t0 ≥ warmup.

    같은 값이면 **이른 창**. 후보가 없으면(지평이 창+워밍업보다 짧으면) ValueError.
    """
    last = horizon_s - window_s
    if last < warmup_s:
        raise ValueError(f"지평 {horizon_s:g}s 가 워밍업 {warmup_s:g}s + 창 {window_s:g}s 보다 짧다")
    done = sorted(completed_s)
    best_t0, best_n = None, -1
    t0 = warmup_s
    while t0 <= last + 1e-9:
        n = bisect.bisect_left(done, t0 + window_s) - bisect.bisect_left(done, t0)
        if n > best_n:
            best_t0, best_n = t0, n
        t0 += step_s
    return best_t0, best_n


def _tick(t_s, dt):
    return int(round(float(t_s) / dt))


def _window_work(robots, headings, actions, k0, kwin, dt):
    """창 [k0, kwin) 에서 DES 가 **시작한** 동작 수 — 전진·회전·후진.

    FMS 는 동작의 **첫 틱에** 자리를 바꾸므로, 자리(또는 헤딩)가 바뀐 틱 수가 곧
    시작한 동작 수다. 자리가 바뀌었으면 이동, 헤딩만 바뀌었으면 회전. 이동 중
    후진은 `actions` 에 `reverse` 로 따로 적혀 있어 거기서 센다.
    """
    moves = turns = reverses = 0
    for rid, rows in robots.items():
        hd = {_tick(t, dt): yaw for t, yaw in headings[rid]}
        prev = None
        for t_s, x, y in rows:
            k = _tick(t_s, dt)
            cur = (x, y, hd.get(k))
            if prev is not None and k0 <= k < kwin and cur != prev:
                if (x, y) != prev[:2]:
                    moves += 1
                elif cur[2] != prev[2]:
                    turns += 1
            prev = cur
        reverses += sum(1 for t_s, act in actions[rid]
                        if act == "reverse" and k0 <= _tick(t_s, dt) < kwin)
    return moves - reverses, turns, reverses


def cut(raw, t0_s, warmup_s=DEFAULT_WARMUP_S, window_s=DEFAULT_WINDOW_S,
        tail_s=DEFAULT_TAIL_S, speed_mps=None, source=None, peak=None):
    """전체 내보내기 dict → 구간 dict. 틱 경계에 맞춰 자른다.

    `t0_s` 는 가장 가까운 틱으로 맞춘다. 모든 로봇이 구간 첫 틱에 한 줄씩 있어야
    하므로(스폰 자리) 없으면 ValueError.
    """
    dt = float(raw["dt_s"])
    k0 = _tick(t0_s, dt)
    kw = _tick(warmup_s, dt)
    kwin = k0 + _tick(window_s, dt)
    ks, ke = k0 - kw, kwin + _tick(tail_s, dt)
    if ks < 0:
        raise ValueError(f"t0 {t0_s:g}s 가 워밍업 {warmup_s:g}s 보다 이르다")

    def keep(series):
        return [row for row in series if ks <= _tick(row[0], dt) <= ke]

    robots, headings, actions = {}, {}, {}
    for rid in raw["robots"]:
        robots[rid] = keep(raw["robots"][rid])
        headings[rid] = keep(raw["headings"].get(rid, []))
        actions[rid] = keep(raw.get("actions", {}).get(rid, []))
        if not robots[rid] or _tick(robots[rid][0][0], dt) != ks:
            raise ValueError(f"로봇 {rid} 가 구간 첫 틱({ks})에 없다 — 매 틱 내보내기인가")

    # 창에서 DES 가 한 일 — 물리 쪽 지표(완료 비율)의 분모다
    tasks = raw.get("tasks") or []
    done_in_window = sum(1 for t in tasks
                         if t.get("completed") is not None and k0 <= int(t["completed"]) < kwin)
    overlap = [t for t in tasks
               if t.get("assigned") is not None and int(t["assigned"]) <= ke
               and (t.get("completed") is None or int(t["completed"]) >= ks)]
    moves, turns, reverses = _window_work(robots, headings, actions, k0, kwin, dt)

    out = {k: raw[k] for k in ("dt_s", "model") if k in raw}
    out.update(robots=robots, headings=headings, actions=actions, tasks=overlap)
    out["slice"] = {
        "format": 1,
        "source": source,
        "t_start_s": round(ks * dt, 6),
        "t0_s": round(k0 * dt, 6),
        "t_end_s": round(ke * dt, 6),
        "warmup_s": round(kw * dt, 6),
        "window_s": round((kwin - k0) * dt, 6),
        "speed_mps": speed_mps,
        "peak": peak,
        "des_window": {"tasks_done": done_in_window, "moves": moves,
                       "turns": turns, "reverses": reverses},
    }
    return out


def encode(doc):
    """(원문 바이트, gzip 바이트, gzip+base64 문자열) — 크기를 보려고 셋 다 돌려준다."""
    raw = json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    gz = gzip.compress(raw, 9)
    return raw, gz, base64.b64encode(gz).decode("ascii")


def _speed_of(export_dir):
    try:
        with open(os.path.join(export_dir, "scene.json"), encoding="utf-8") as f:
            return (json.load(f).get("meta") or {}).get("speed_mps")
    except (OSError, ValueError):
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("export_dir", help="SIM_EXPORT_ISAAC 내보내기 폴더 (trajectories.json · scene.json)")
    ap.add_argument("-o", "--out", required=True, help="출력 경로 (.gz 로 끝나면 gzip)")
    ap.add_argument("--t0", type=float, default=None, help="창 시작(초). 없으면 피크를 찾는다")
    ap.add_argument("--window", type=float, default=DEFAULT_WINDOW_S)
    ap.add_argument("--warmup", type=float, default=DEFAULT_WARMUP_S)
    ap.add_argument("--tail", type=float, default=DEFAULT_TAIL_S)
    ap.add_argument("--step", type=float, default=DEFAULT_STEP_S)
    ap.add_argument("--source", default=None, help="출처 run_id (예: est_18_n10)")
    a = ap.parse_args(argv)

    with open(os.path.join(a.export_dir, "trajectories.json"), encoding="utf-8") as f:
        raw = json.load(f)
    dt = float(raw["dt_s"])
    horizon = max(_tick(rows[-1][0], dt) for rows in raw["robots"].values()) * dt
    peak = None
    t0 = a.t0
    if t0 is None:
        done = [int(t["completed"]) * dt for t in raw.get("tasks") or []
                if t.get("completed") is not None]
        t0, n = pick_peak(done, horizon - a.tail, a.window, a.warmup, a.step)
        peak = {"metric": "tasks_done", "value": n, "step_s": a.step}
        print(f"[slice] 피크 창 t0 = {t0:,.0f}s ({t0 / 3600:.2f}h) · 완료 태스크 {n}개 / {a.window:g}s")
    doc = cut(raw, t0, a.warmup, a.window, a.tail, speed_mps=_speed_of(a.export_dir),
              source=a.source, peak=peak)
    body, gz, b64 = encode(doc)
    with open(a.out, "wb") as f:
        f.write(gz if a.out.endswith(".gz") else body)
    s = doc["slice"]
    w = s["des_window"]
    print(f"[slice] {len(doc['robots'])}대 · DES {s['t_start_s']:,.1f}s ~ {s['t_end_s']:,.1f}s "
          f"(워밍업 {s['warmup_s']:g} + 창 {s['window_s']:g} + 꼬리 {a.tail:g})")
    print(f"[slice] 창 안 DES: 태스크 {w['tasks_done']} · 전진 {w['moves']} · "
          f"회전 {w['turns']} · 후진 {w['reverses']}")
    print(f"[slice] 크기: 원문 {len(body) / 1024:,.0f} KiB · gzip {len(gz) / 1024:,.0f} KiB · "
          f"gzip+b64 {len(b64) / 1024:,.0f} KiB -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
