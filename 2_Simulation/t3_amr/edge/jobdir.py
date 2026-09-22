"""폴더로 들어온 Start JSON → Runner. **MQTT 가 없을 때 쓰는 두 번째 입구다.**

왜 있나
-------
GPU 서버가 백엔드에 아직 안 붙어 있어도 «대수·창·주문·시드» 를 받아 돌려야 한다.
그런데 그 값들을 받는 길은 이미 있다 — `spec.RunSpec`. 없는 것은 **입구 하나**뿐이다.

    입구 ①  MQTT NCMD Start  ──┐
                               ├──▶ RunSpec ──▶ Runner.handle_start
    입구 ②  <root>/inbox/*.json ─┘   ← 이 파일

★ **파싱을 여기서 새로 하지 않는다.** `RunSpec.from_json` 을 그대로 부른다.
  따로 짜면 두 입구가 갈라지고, 나중에 백엔드를 붙였을 때 "폴더로는 되는데
  MQTT 로는 안 되는" 판이 생긴다. 그러면 폴더로 낸 결과가 증거가 못 된다.
  덤으로 `scenario_sha256` 검증과 `run_id` 정규식도 공짜로 따라온다.

폴더 구조
---------
    <root>/inbox/     여기에 넣는다.  *.json
    <root>/started/   집어간 것 (덮어쓰지 않는다)
    <root>/failed/    JSON 이 깨졌거나 계약 위반. 같은 이름의 .err 에 사유

넣는 쪽 규약
------------
**다 쓴 뒤에 rename 으로 넣는 것이 가장 안전하다.** 그게 안 되면 `settle_s`(기본
1초)가 보호한다 — 마지막 수정이 그보다 최근인 파일은 이번 틱에 안 집는다.
쓰는 도중에 읽어 «깨진 JSON» 으로 `failed/` 에 처박는 사고를 막는 장치다.

한 번에 하나
------------
러너가 IDLE·ERROR 일 때만 집는다. 바쁘면 **파일을 그대로 둔다** — 큐를 쌓지
않는다. Start 를 밀어 넣어 봐야 `handle_start` 가 busy 로 거절하고, 그러면
그 요청은 조용히 사라진다. 남겨 두면 다음 틱에 다시 본다.

쓰는 법
-------
    python -m edge --job-dir /var/lib/t3amr/jobs   (MQTT 와 같이 켜도 된다)

    cat > /tmp/j.json <<'EOF'
    {"run_id": "local_001", "n_robots": 12, "timeout_s": 1200,
     "scenario": {"seed": 104, "window_s": 900, "outbound_gap_s": 50.0}}
    EOF
    mv /tmp/j.json /var/lib/t3amr/jobs/inbox/      # rename 으로 넣는다
"""
from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass

from .spec import RunSpec

log = logging.getLogger(__name__)

INBOX, STARTED, FAILED = "inbox", "started", "failed"
DEFAULT_SETTLE_S = 1.0
MAX_BYTES = 1024 * 1024          # spec 의 scenario 상한(512 KB)보다 넉넉히. 그 위는 읽지 않는다


def ensure_dirs(root: str) -> None:
    for sub in (INBOX, STARTED, FAILED):
        os.makedirs(os.path.join(root, sub), exist_ok=True)


def pending(root: str, now: float, settle_s: float = DEFAULT_SETTLE_S) -> list:
    """집을 수 있는 파일들 — **오래된 것부터.** 아직 쓰는 중일 수 있는 것은 뺀다.

    순수 함수다(테스트에서 now 를 준다). 정렬은 (mtime, 이름) 이라 같은 초에
    여러 개가 들어와도 순서가 정해진다 — 무엇이 먼저 돌지가 매번 달라지면
    재현이 안 된다.
    """
    box = os.path.join(root, INBOX)
    try:
        names = os.listdir(box)
    except OSError:
        return []
    out = []
    for name in names:
        if not name.endswith(".json"):
            continue
        p = os.path.join(box, name)
        try:
            st = os.stat(p)
        except OSError:               # 그새 사라졌다 — 다음 틱에 다시 본다
            continue
        if not os.path.isfile(p):
            continue
        if now - st.st_mtime < settle_s:
            continue                  # 아직 쓰는 중일 수 있다
        out.append((st.st_mtime, name, p))
    out.sort()
    return [p for _, _, p in out]


def _move(src: str, dst_dir: str, run_id: str, now: float) -> str:
    """`started/`·`failed/` 로 옮긴다. 이름이 겹치면 뒤에 숫자를 붙인다 — 덮어쓰지 않는다."""
    os.makedirs(dst_dir, exist_ok=True)
    stem = run_id or os.path.splitext(os.path.basename(src))[0]
    base = "%s_%s" % (time.strftime("%Y%m%d_%H%M%S", time.localtime(now)), stem)
    dst = os.path.join(dst_dir, base + ".json")
    k = 1
    while os.path.exists(dst):
        dst = os.path.join(dst_dir, "%s.%d.json" % (base, k))
        k += 1
    os.replace(src, dst)
    return dst


@dataclass(frozen=True)
class JobDirConfig:
    root: str
    settle_s: float = DEFAULT_SETTLE_S


class JobDir(object):
    """틱마다 `poll(now)` 한 번. 집었으면 옮긴 경로를, 아니면 None 을 돌려준다.

    `submit` 은 보통 `runner.handle_start`, `is_idle` 은 `lambda: runner.state
    in (IDLE, ERROR)` 다. 둘 다 주입이라 테스트가 Isaac 도 MQTT 도 안 쓴다.
    """

    def __init__(self, cfg: JobDirConfig, submit: Callable, is_idle: Callable) -> None:
        self.cfg = cfg
        self.submit = submit
        self.is_idle = is_idle
        ensure_dirs(cfg.root)
        log.info("job dir watching %s (settle %.1fs)", os.path.join(cfg.root, INBOX), cfg.settle_s)

    # ── 한 틱 ────────────────────────────────────────────────────────────
    def poll(self, now: float) -> str | None:
        if not self.is_idle():
            return None                      # 바쁘면 **그대로 둔다**. 큐를 쌓지 않는다
        for path in pending(self.cfg.root, now, self.cfg.settle_s):
            return self._take(path, now)
        return None

    def _take(self, path: str, now: float) -> str | None:
        try:
            size = os.path.getsize(path)
            if size > MAX_BYTES:
                return self._fail(path, "", now, "too large: %d B > %d" % (size, MAX_BYTES))
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            log.warning("job %s unreadable: %s", os.path.basename(path), e)
            return None                      # 못 읽었을 뿐이다. 다음 틱에 다시 본다
        except UnicodeDecodeError as e:
            return self._fail(path, "", now, "not UTF-8: %s" % e)

        # ★ 먼저 검증한다 — 깨진 것을 started/ 로 옮겨 놓으면 사유가 남지 않는다.
        try:
            spec = RunSpec.from_json(text)
        except ValueError as e:
            return self._fail(path, "", now, str(e))

        # ★ 옮기고 나서 제출한다. 반대로 하면 제출 직후 죽었을 때 **같은 판을
        #   다시 집는다.** 옮겨 두면 최악이어도 한 번 건너뛸 뿐이다.
        dst = _move(path, os.path.join(self.cfg.root, STARTED), spec.run_id, now)
        log.info("job %s → Start (n=%d, window %.0fs, seed %s)",
                 spec.run_id, spec.n_robots, spec.window_s, spec.seed)
        try:
            self.submit(text, now)
        except Exception:                    # noqa: BLE001 — 한 건 때문에 데몬이 죽으면 안 된다
            log.exception("job %s: submit failed", spec.run_id)
        return dst

    def _fail(self, path: str, run_id: str, now: float, why: str) -> str:
        log.error("job %s rejected: %s", os.path.basename(path), why)
        dst = _move(path, os.path.join(self.cfg.root, FAILED), run_id, now)
        try:
            with open(os.path.splitext(dst)[0] + ".err", "w", encoding="utf-8") as f:
                f.write(json.dumps({"file": os.path.basename(path), "error": why,
                                    "at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now))},
                                   ensure_ascii=False, indent=2) + "\n")
        except OSError as e:
            log.warning("could not write .err for %s: %s", os.path.basename(dst), e)
        return dst
