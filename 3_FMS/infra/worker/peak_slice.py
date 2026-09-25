# -*- coding: utf-8 -*-
"""견적 run 마다 DES **피크 10분**을 잘라 `sim.result` 에 싣는다 (S15P21A106-244).

물리 검증은 DES 6시간 전체가 아니라 가장 바쁜 10분을 Isaac 에서 실제 시간으로 다시 돌린다. 각 로봇은 그
순간의 자리에서 출발해야 하므로, 워커가 DES 를 돌린 **그 자리에서** 매 틱 궤적으로 구간을 떼어 둔다 — 백엔드가
검증 요청에 `scenario.trajectory_gz_b64` 로 그대로 실어 보내고, 러너(`t3_amr/path/fms_traj`)가 읽는다.

형식은 275 의 오프라인 도구 `2_Simulation/t3_amr/tools/des_slice.py` 와 같은 **slice format 1** 이다. 그 도구는
러너 쪽 폴더라 워커 이미지에 들어가지 않아 같은 순수 함수를 여기 둔다 — 한쪽을 고치면 다른 쪽도 고친다
(양쪽 테스트가 같은 합성 궤적으로 같은 값을 본다).

    [t0 − 워밍업, t0 + 창 + 꼬리]   t0 = 창 안 완료 태스크가 가장 많은 10분(같으면 이른 쪽)

☹ 워밍업을 두는 이유: DES 는 여러 틱 동작의 자리를 **첫 틱에** 바꾼다. t0 에 딱 자르면 움직이던 로봇이 앞선
  자리에 선다. 꼬리는 물리가 늦을 때 창 끝 뒤 계획까지 있어야 「다 끝나서 멈춘」 것과 「밀린」 것이 갈린다.
"""
import base64
import bisect
import gzip
import json

DEFAULT_WINDOW_S = 600.0
DEFAULT_WARMUP_S = 60.0
DEFAULT_TAIL_S = 60.0
DEFAULT_STEP_S = 10.0
# 러너(edge/spec.MAX_SCENARIO_BYTES 900 KiB)가 받는 시나리오 안에 들어가야 한다. 10대 약 300 KiB, 15대 약 440 KiB.
MAX_B64_BYTES = 800 * 1024


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
    """창 [k0, kwin) 에서 DES 가 **시작한** 동작 수 — 전진·회전·후진 (자리·헤딩이 바뀐 틱)."""
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
    """전체 내보내기 dict → 구간 dict(slice format 1). 모든 로봇이 구간 첫 틱에 한 줄씩 있어야 한다."""
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
    """(원문 바이트, gzip 바이트, gzip+base64 문자열)."""
    raw = json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    gz = gzip.compress(raw, 9)
    return raw, gz, base64.b64encode(gz).decode("ascii")


def peak_slice(raw, source=None, speed_mps=None, window_s=DEFAULT_WINDOW_S, warmup_s=DEFAULT_WARMUP_S,
               tail_s=DEFAULT_TAIL_S, step_s=DEFAULT_STEP_S):
    """전체 내보내기 → `sim.result.verify_slice`. 못 만들면 `gz_b64` 없이 `error` 만 — 견적은 그대로 끝난다.

    메타(t0·창·창 안 DES 작업량)는 백엔드가 화면·비교에 쓰고, gz_b64 는 검증 요청에 그대로 싣는다.
    """
    out = {"format": 1, "source": source}
    try:
        dt = float(raw["dt_s"])
        horizon = max(_tick(rows[-1][0], dt) for rows in raw["robots"].values() if rows) * dt
        done = [int(t["completed"]) * dt for t in raw.get("tasks") or [] if t.get("completed") is not None]
        t0, n = pick_peak(done, horizon - tail_s, window_s, warmup_s, step_s)
        doc = cut(raw, t0, warmup_s, window_s, tail_s, speed_mps=speed_mps, source=source,
                  peak={"metric": "tasks_done", "value": n, "step_s": step_s})
    except (KeyError, ValueError) as e:
        out["error"] = str(e)
        return out
    _, _, b64 = encode(doc)
    s = doc["slice"]
    out.update(t0_s=s["t0_s"], t_start_s=s["t_start_s"], t_end_s=s["t_end_s"], warmup_s=s["warmup_s"],
               window_s=s["window_s"], n_robots=len(doc["robots"]), b64_bytes=len(b64), **s["des_window"])
    if len(b64) > MAX_B64_BYTES:
        out["error"] = f"slice too large: {len(b64)} > {MAX_B64_BYTES} bytes"
        return out
    out["gz_b64"] = b64
    return out
