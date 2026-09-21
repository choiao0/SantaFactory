"""녹화 런 하나 = `run_record.sh` 프로세스 하나. 명령·환경 조립은 순수 함수, 기동·시그널은 주입 가능(테스트).

run_record.sh(t3_amr) 의 규약:
  RUN_TAG    → 산출물 이름: $OUT/demo_<TAG>.mp4 · $OUT/shots_<TAG>/ · $LOGS/record_<TAG>.log
  PIBT_N     → 로봇 대수. 계획 폴더 plan/traj_pibt_h/fleet_NN 이 없으면 REPLAN=1 로 만들어야 한다
  PIBT_SEED · PIBT_MODE · PIBT_HORIZON → live_pibt.py (lifelong 발주, 창 길이)
  SIGINT     → trap 이 Kit 자손을 정리하고 프레임을 mp4 로 조립한 뒤 종료한다 (끊어도 그 시점까지 영상이 나온다)
  "캡처 ON" 로그 / 프레임 파일 → 촬영 시작,  "post_quit" · "전원 완주" → 스스로 끝남
"""
from __future__ import annotations

import glob
import logging
import math
import os
import shutil
import signal
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .spec import RunSpec, canonical_json

RUN_ENV_MARK = "SIM_RUN_ID"                  # 자식 환경 표식 — 데몬 재시작 때 남은 런 프로세스를 찾는다
log = logging.getLogger(__name__)

DEFAULT_PLANNER = "pibt_h"
# 계획 틱 길이 — path/metrics.tick_seconds 와 같은 식:
#   pitch / (v_max × MOVE_TICKS) = 1.2 / (0.9 × 4) ≈ 0.333 s (211 틱 모델).
#   215 는 옛 값 4/3(315틱 = 420 s, 211 이전)을 썼다 → 창 300 s 에 270틱만 계획해
#   시뮬 ≈ 90 s 에 "전원 완주"로 끝났다 (2026-09-16 컨테이너 실측: 400틱 = 시뮬 116 s).
#   엣지는 numpy 없이 돌아야 해서 metrics 를 import 하지 않고 상수를 둔다.
#   격자(PIBT_PITCH)·v_max·MOVE_TICKS 가 바뀌면 여기와 T3AMR_TICK_S(edge.py --tick-s)를 같이 본다.
# ★★ 2026-09-21 정정 — **기본이 1.2 였는데 자식은 1.0 으로 돌고 있었다.**
#   `run_record.sh:124` 가 `export PIBT_PITCH="${PIBT_PITCH:-1.0}"` 다. 그런데
#   여기는 1.2 로 환산했으므로 틱이 0.333 s 로 잡혔고, 실제(1.0)는 0.278 s 다.
#   결과는 **창이 20 % 짧게 계획되는 것**이다 — 창 600 s 에 1,980틱을 세우는데
#   2,376틱이 맞다. 그러면 창이 끝나기 전에 「전원 완주」로 판이 끝난다.
#   바로 위 주석이 기록한 215 사고(창 300 s 에 270틱)와 **같은 종류**다.
#
#   그래서 상수를 박지 않고 `PIBT_PITCH` 를 본다. 엣지 환경에 그 값이 있으면
#   `environment()` 가 os.environ 을 통째로 물려주므로 **자식도 같은 값**을 쓴다.
#   없으면 run_record.sh 와 같은 1.0 으로 맞춘다 — 양쪽 기본값이 갈리면 안 된다.
PLAN_PITCH_DEFAULT_M = 1.0                   # run_record.sh:124 의 기본값과 **같아야 한다**
PLAN_V_MAX_MPS = 0.9                         # isaac_drive.RobotGeom.v_max
MOVE_TICKS = 4                               # 3_FMS/sim_engine pibt.geometry.MOVE_TICKS — 전진 1칸 = 4틱 (-211)


def plan_pitch_m(env: dict | None = None) -> float:
    """계획 격자(m). `PIBT_PITCH` 가 있으면 그것, 없으면 run_record.sh 와 같은 기본값."""
    raw = ((os.environ if env is None else env).get("PIBT_PITCH") or "").strip()
    try:
        v = float(raw)
    except ValueError:
        return PLAN_PITCH_DEFAULT_M
    return v if v > 0 else PLAN_PITCH_DEFAULT_M


def tick_seconds(env: dict | None = None) -> float:
    """계획 틱 길이[s] = pitch / (v_max × MOVE_TICKS). `path/metrics.tick_seconds` 와 같은 식."""
    return plan_pitch_m(env) / (PLAN_V_MAX_MPS * MOVE_TICKS)


PLAN_PITCH_M = plan_pitch_m()                # 기록·로그용 (읽는 시점의 실제 값)
DEFAULT_TICK_S = tick_seconds()
HORIZON_MARGIN_S = 60.0                      # 창보다 조금 길게 계획 — 창 끝은 host-orch Stop 이 자른다
READY_MARKER = "캡처 ON"
FINISHED_MARKERS = ("post_quit", "전원 완주")
INT_GRACE_S = 240.0                          # SIGINT 뒤 조립(ffmpeg) 대기 — 프레임 수천 장이면 1 분 넘게 걸린다
TERM_GRACE_S = 5.0


def killpg_or_pid(proc: Any, sig: int) -> None:
    try:
        os.killpg(proc.pid, sig)
    except ProcessLookupError:
        pass
    except PermissionError:
        proc.send_signal(sig)


def plan_dir(t3amr_dir: str, n_robots: int, planner: str = DEFAULT_PLANNER) -> str:
    """run_record.sh 가 요구하는 대수별 계획 폴더 (0 패딩: fleet_03)."""
    return os.path.join(t3amr_dir, "plan", f"traj_{planner}", f"fleet_{n_robots:02d}")


def horizon_ticks(window_s: float, tick_s: float = DEFAULT_TICK_S) -> int:
    return int(math.ceil((window_s + HORIZON_MARGIN_S) / tick_s))


@dataclass(frozen=True)
class RecorderConfig:
    t3amr_dir: str
    out_dir: str
    logs_dir: str
    runs_dir: str
    planner: str = DEFAULT_PLANNER
    tick_s: float = DEFAULT_TICK_S
    watch_s: float = 420.0                   # run_record.sh WATCH_SEC — 이 안에 촬영이 안 켜지면 스스로 끊는다


def command(cfg: RecorderConfig) -> list:
    return ["bash", os.path.join(cfg.t3amr_dir, "run_record.sh"), "--planner", cfg.planner]


def environment(cfg: RecorderConfig, spec: RunSpec, base: dict | None = None,
                scenario_path: str | None = None, plan_exists: bool | None = None) -> dict:
    """자식 환경. base 는 기본 os.environ. 계획 폴더가 없으면 REPLAN=1 로 run_record.sh 가 먼저 계획을 만든다."""
    e = dict(os.environ if base is None else base)
    if plan_exists is None:
        plan_exists = os.path.isdir(plan_dir(cfg.t3amr_dir, spec.n_robots, cfg.planner))
    e.update({
        RUN_ENV_MARK: spec.run_id,
        "RUN_TAG": spec.run_id,
        "PIBT_N": str(spec.n_robots),
        "PIBT_MODE": "lifelong",
        "PIBT_HORIZON": str(horizon_ticks(spec.window_s, cfg.tick_s)),
        "REPLAN": "0" if plan_exists else "1",
        "STRICT": "1",
        "WATCH_SEC": str(int(cfg.watch_s)),
        "VIDEO": "1",
    })
    if spec.seed is not None:
        e["PIBT_SEED"] = str(spec.seed)
    # 주문 — 계약 §2 의 `scenario.outbound_gap_s`(초)를 계획 틱으로 옮긴다.
    #   `PIBT_ORDER_GAP` 은 **틱 단위**다 (live_pibt.py:211 "-211: 틱 단위라 x4").
    #   초로 넘기면 pitch 1.0 에서 3.6배 촘촘한 주문이 되어 판이 전혀 달라진다.
    #   ☹ `scenario.orders`(목록)는 아직 못 넘긴다 — spec.RunSpec.orders 참조.
    if spec.order_gap_s is not None:
        e["PIBT_ORDER_GAP"] = str(max(1, int(round(spec.order_gap_s / cfg.tick_s))))
    if scenario_path:
        e["SIM_SCENARIO_PATH"] = scenario_path
        e["SIM_SCENARIO_SHA256"] = spec.scenario_sha256 or ""
    return e


class Recorder:
    """run_record.sh 프로세스 하나의 수명. request_stop() 뒤 poll_stop(now) 를 tick 마다 불러 사다리가 진행된다."""

    def __init__(self, cfg: RecorderConfig, spawn: Callable = subprocess.Popen,
                 send: Callable[[Any, int], None] = killpg_or_pid):
        self.cfg, self.spawn, self.send = cfg, spawn, send
        self.spec: RunSpec | None = None
        self.proc: Any = None
        self.stop_t: float | None = None
        self.step = 0

    # ---- 경로 -----------------------------------------------------------------
    def tag(self) -> str:
        return self.spec.run_id if self.spec else ""

    def record_log(self) -> str:
        return os.path.join(self.cfg.logs_dir, f"record_{self.tag()}.log")

    def shots_dir(self) -> str:
        return os.path.join(self.cfg.out_dir, f"shots_{self.tag()}")

    def video_path(self) -> str | None:
        p = os.path.join(self.cfg.out_dir, f"demo_{self.tag()}.mp4")
        return p if self.spec and os.path.isfile(p) and os.path.getsize(p) > 0 else None

    def remove_frames(self) -> int:
        """shots_<TAG>/ 를 통째로 지운다 — mp4 가 올라간 뒤에만 부른다(-241). 지운 파일 수를 돌려주고, 없으면 0."""
        d = self.shots_dir()
        if not self.spec or not os.path.isdir(d):
            return 0
        n = sum(len(files) for _, _, files in os.walk(d))
        shutil.rmtree(d, ignore_errors=True)
        return n

    def write_scenario(self, spec: RunSpec) -> str | None:
        if spec.scenario is None:
            return None
        d = os.path.join(self.cfg.runs_dir, spec.run_id)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "scenario.json")
        with open(path, "wb") as f:
            f.write(canonical_json(spec.scenario))
        return path

    # ---- 수명 -----------------------------------------------------------------
    def start(self, spec: RunSpec, now: float) -> None:
        self.spec = spec
        if spec.orders is not None:
            # 조용히 버리지 않는다 — 백엔드가 목록을 보냈는데 우리가 간격으로만
            # 재생하면 **다른 판**이 돈다. 결과를 견적과 맞대기 전에 알아야 한다.
            n = len(spec.orders.get("outbound") or []) if isinstance(spec.orders, dict) else 0
            log.warning("run %s: scenario.orders(출고 %d건) 를 **쓰지 않는다** — "
                        "rack_id→스테이션 이름 규칙이 없다. outbound_gap_s 간격으로만 재생한다",
                        spec.run_id, n)
        env = environment(self.cfg, spec, scenario_path=self.write_scenario(spec))
        os.makedirs(self.cfg.logs_dir, exist_ok=True)
        with open(os.path.join(self.cfg.logs_dir, f"edge_{spec.run_id}.log"), "ab") as out:   # 자식이 fd 를 물려받는다
            self.proc = self.spawn(command(self.cfg), cwd=self.cfg.t3amr_dir, env=env, start_new_session=True,
                                   stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def dead(self) -> bool:
        """정지 요청 전에 죽었나."""
        return self.proc is not None and self.stop_t is None and not self.alive()

    def _log_has(self, markers) -> bool:
        try:
            with open(self.record_log(), "rb") as f:
                data = f.read()
        except OSError:
            return False
        return any(m.encode("utf-8") in data for m in markers)

    def frames(self) -> int:
        return len(glob.glob(os.path.join(self.shots_dir(), "f_*.*")))

    def ready(self) -> bool:
        """촬영이 실제로 켜졌나 = RUNNING 조건."""
        return self.frames() > 0 or self._log_has((READY_MARKER,))

    def finished_normally(self) -> bool:
        return self._log_has(FINISHED_MARKERS)

    def request_stop(self, now: float) -> None:
        """SIGINT 를 run_record.sh 에만 보낸다 — trap 이 Kit 정리와 mp4 조립을 맡는다. 그 뒤는 TERM·KILL(그룹)."""
        if self.proc is None:
            return
        self.stop_t, self.step = now, 1
        if self.alive():
            self.proc.send_signal(signal.SIGINT)

    def poll_stop(self, now: float) -> bool:
        """유예가 지나면 다음 칸. 죽었으면 True."""
        if not self.alive():
            return True
        if self.stop_t is None:
            return False
        ladder = ((signal.SIGTERM, INT_GRACE_S), (signal.SIGKILL, INT_GRACE_S + TERM_GRACE_S))
        for k, (sig, after) in enumerate(ladder, start=2):
            if self.step < k and now - self.stop_t >= after:
                self.send(self.proc, sig)
                self.step = k
        return False

    def pids(self) -> list:
        return [self.proc.pid] if self.alive() else []

    def isaac_count(self) -> int:
        return 1 if self.alive() else 0
