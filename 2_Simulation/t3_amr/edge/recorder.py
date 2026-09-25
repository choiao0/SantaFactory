"""녹화 런 하나 = `run_record.sh` 프로세스 하나. 명령·환경 조립은 순수 함수, 기동·시그널은 주입 가능(테스트).

run_record.sh(t3_amr) 의 규약:
  RUN_TAG    → 산출물 이름: $OUT/demo_<TAG>.mp4 · $OUT/shots_<TAG>/ · $LOGS/record_<TAG>.log
  PIBT_N     → 로봇 대수. 계획 폴더 plan/traj_pibt_h/fleet_NN 이 없으면 REPLAN=1 로 만들어야 한다
  PIBT_SEED · PIBT_MODE · PIBT_HORIZON → live_pibt.py (lifelong 발주, 창 길이)
  SIGINT     → trap 이 Kit 자손을 정리하고 프레임을 mp4 로 조립한 뒤 종료한다 (끊어도 그 시점까지 영상이 나온다)
  "캡처 ON"·"촬영 ON" 로그 / 프레임 파일 → 촬영 시작,  "post_quit"·"전원 완주"·"주행 종료" → 스스로 끝남
  "[hl] sim <초>s" 로그 → 시뮬 시각 (헤드리스 경로만. host-orch 가 창을 이 값으로 끊는다)
"""
from __future__ import annotations

import glob
import json
import logging
import math
import os
import re
import shutil
import signal
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .spec import RunSpec, canonical_json, decode_trajectory

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
# 촬영이 켜졌다는 표시. ★ 경로마다 말이 다르다 — Kit 경로(`live_pibt.py:486`)는
# 「캡처 ON」, 헤드리스 경로(`headless_pibt.py:226,242`)는 「촬영 ON」이다.
# 하나만 보면 헤드리스 판이 `ready()` 를 영영 못 넘고 ready_timeout 에 걸린다.
READY_MARKERS = ("캡처 ON", "촬영 ON")
# 스스로 잘 끝났다는 표시. 위와 같은 이유로 경로마다 다르다 —
# Kit 은 `post_quit`(`live_pibt.py:565`)·「전원 완주」(:961), 헤드리스는
# 「주행 종료」(`headless_pibt.py:369`)다. 헤드리스 판이 전원 완주하거나 계획
# 지평을 다 쓰고 끝나면 이 줄만 남으므로 반드시 들어가야 한다 — 빠지면
# `_tick_running` 이 `recorder died` 로 정상 종료를 실패 처리한다.
FINISHED_MARKERS = ("post_quit", "전원 완주", "주행 종료")
# 시뮬 시각 보고 줄 — `headless_pibt.py:343` 의 형식. 뒤에서 이만큼만 읽는다.
SIM_TIME_RE = re.compile(r"\[hl\]\s+sim\s+([0-9]+(?:\.[0-9]+)?)s")
# 구간 재생(-275)이면 같은 줄 끝에 `| 창 <초>s`(워밍업을 뺀 시각)가 붙는다. 있으면 그걸 쓴다 —
# host-orch 가 끊는 창은 워밍업 뒤 10분이다.
WINDOW_TIME_RE = re.compile(r"\|\s*창\s+([0-9]+(?:\.[0-9]+)?)s")
SIM_TIME_TAIL_BYTES = 64 * 1024
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


def physics_path(cfg: RecorderConfig, run_id: str) -> str:
    """러너가 물리 지표를 쓰는 자리 (`headless_pibt.py` 의 `PIBT_PHYSICS_OUT`)."""
    return os.path.join(cfg.out_dir, f"physics_{run_id}.json")


def environment(cfg: RecorderConfig, spec: RunSpec, base: dict | None = None,
                scenario_path: str | None = None, plan_exists: bool | None = None,
                traj_path: str | None = None, slice_meta: dict | None = None) -> dict:
    """자식 환경. base 는 기본 os.environ. 계획 폴더가 없으면 REPLAN=1 로 run_record.sh 가 먼저 계획을 만든다.

    `traj_path` 는 인라인 궤적(`scenario.trajectory_gz_b64`)을 푼 파일, `slice_meta` 는 그 `slice`
    블록이다 (-275). 경로 궤적(`scenario.trajectory`)보다 이쪽이 이긴다.
    """
    e = dict(os.environ if base is None else base)
    traj = traj_path or spec.trajectory
    if plan_exists is None:
        plan_exists = os.path.isdir(plan_dir(cfg.t3amr_dir, spec.n_robots, cfg.planner))
    e.update({
        RUN_ENV_MARK: spec.run_id,
        "RUN_TAG": spec.run_id,
        "PIBT_N": str(spec.n_robots),
        "PIBT_MODE": "lifelong",
        "PIBT_HORIZON": str(horizon_ticks(spec.window_s, cfg.tick_s)),
        # ★ 궤적을 주면 계획을 **안 한다** — 그러면 계획 폴더도 필요 없다.
        "REPLAN": "0" if (plan_exists or traj) else "1",
        "STRICT": "1",
        "WATCH_SEC": str(int(cfg.watch_s)),
        "VIDEO": "1",
        # ── 촬영 경로 (2026-09-22) ─────────────────────────────────────
        # ★ 서비스는 **헤드리스로 촬영한다.** Kit `--exec` 경로는 매 스텝
        #   렌더하고 그린 것의 95 %를 버린다 — 실시간의 0.36배다. 헤드리스는
        #   저장할 스텝에만 그려 1.64배가 나온다 (13대·seed 101 실측,
        #   프레임 2,031장 실패 0). 창 600 s 가 GPU 7~8분에 끝난다.
        "HEADLESS": "1",
        # 준비 단계 프레임 상한. 기본 12,000 은 헤드리스에서 **4초**라
        # 준비(계획·probe·재정렬, 30~80 s)를 못 넘긴다 — `run_headless.sh:57`
        # 이 같은 이유로 같은 값을 쓴다.
        "PIBT_HL_SETUP_CAP": "400000",
        # ☹ `PIBT_HL_MAX_SIM`(러너가 스스로 멈추는 시뮬 초 상한)은 **주지 않는다.**
        #
        #   창을 끊는 주체는 **host-orch 하나**다 — 위 `HORIZON_MARGIN_S` 주석이
        #   정해 둔 그대로다. host-orch 는 `Runner/SimTime`(아래 `sim_time()` 이
        #   읽어 `edge/runner.py` 가 싣는다)을 보고 **시뮬 초**로 창을 끊는다
        #   (`orchestrator._window_filled`).
        #
        #   여기에 러너 자신의 시뮬 초 상한을 같이 걸면 시계가 둘이 되고, 러너가
        #   먼저 멈추면 host-orch 가 그것을 「런이 스스로 끝났다」= FAILED 로
        #   적는다. 폭주 방지는 이미 벽시계 `spec.timeout_s` 가 한다
        #   (`runner._tick_running`) — 시계를 하나 더 들일 이유가 없다.
        # ★★ 접촉으로 판을 죽이지 않는다 (`live_pibt.py` 차체 접촉 분기).
        #   검증이 낼 답은 「실패」가 아니라 「몇 번 닿았다」다. 1.0 m 통로에서
        #   제어 허용 오차(50 mm)가 설계 여유(41.3 mm)보다 크므로 접촉은
        #   확률 문제이고, 죽이면 그 뒤 구간을 영영 못 본다.
        "PIBT_CONTACT_ABORT": "0",
        # ★★ 물리 지표 파일 (-275) — 러너가 10초마다·끝날 때 쓰고, 엣지가 업로드 뒤 읽어
        #   `Runner/Physics` 로 host-orch 에 넘긴다.
        "PIBT_PHYSICS_OUT": physics_path(cfg, spec.run_id),
    })
    # ★★ 창을 끊는 것은 host-orch 다 — 동작이 먼저 다 끝나도 Stop 까지 서서 기다린다 (-275).
    #   안 그러면 「전원 완주」로 스스로 내려가 host-orch 가 FAILED(창 미달)로 적는다.
    e.setdefault("PIBT_HOLD_UNTIL_STOP", "1")
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
    # ★ 궤적이 오면 계획 단계를 통째로 건너뛴다 (`live_pibt.py:1084`).
    #   주문(`SIM_SCENARIO_PATH`)보다 **이쪽이 이긴다** — 궤적에는 배정 결과가
    #   이미 들어 있어 주문 스트림을 쓸 자리가 없다.
    if traj:
        e["PIBT_TRAJ"] = traj
        # ★ 궤적만 넘기면 안 돈다. 셋이 세트다 (2026-09-22 실측).
        #   ① 궤적의 칸 번호는 **FMS 격자(107x116)** 기준이다. 안 주면 우리
        #      격자(106x115)로 읽어 칸이 딴 자리를 가리킨다 — live_pibt 가
        #      「스폰이 궤적 첫 틱과 다르다」로 운다.
        #   ② `run_record.sh` 의 `PIBT_FRONT_RULE` 기본이 4인데 이 궤적은
        #      4칸에서 **ADG 순환**이 난다. 틱 순위가 그걸 편다.
        #   호출자가 준 값이 있으면 그쪽이 이긴다 — 실험용 구멍을 남긴다.
        e.setdefault("PIBT_FMS_GRID", "1")
        e.setdefault("PIBT_ADG_RANK", "1")
        # ★ 씬·계획 폴더를 **런마다 따로** (-275). run_record.sh 가 궤적 첫 틱으로 계획 폴더를
        #   만들고 씬을 짓는데, 공용 plan/·stage/ 에 남으면 다음 자체 계획 판이 그 스폰 자리를
        #   재사용한다(paths.sh 주석). `start()` 가 비우고 시작한다.
        run_dir = os.path.join(cfg.runs_dir, spec.run_id)
        e.setdefault("T3AMR_PLAN", os.path.join(run_dir, "plan"))
        e.setdefault("T3AMR_STAGE", os.path.join(run_dir, "stage"))
    if slice_meta:
        # ★★ DES 피크 구간 (-275) — **DES 와 같은 발자국(앞 2칸)** 으로 몬다. 4칸은 DES 가
        #   안 잡은 칸을 더 잡아 없던 대기를 만든다(`fms_traj.build` 독스트링). 검증은 DES 의
        #   판을 그대로 물리에 올려 접촉·지연을 드러내는 것이라 2칸이 뜻에 맞다.
        #   엣지 환경에 PIBT_FRONT_RULE 이 있으면 그쪽이 이긴다(4칸 비교 실험용).
        e.setdefault("PIBT_FRONT_RULE", "2")
        # ★ 회전 관문 (-244) — 칸이 겹쳐도 **차체 틈**이 넉넉하면 돌고(GEO), 막혀도 20 s 만 기다린다.
        #   기본(칸만 보고 90 s)은 인계 회전 한 건이 90 s 서면 뒤가 줄줄이 밀렸다. 피크 10대 두 구간 실측:
        #   창 동작 시작 83.3→88.5 % · 54.7→76.3 %, 지연 p50 40→32 s · 253→107 s, 접촉 0 · 최소 간격 0.31 m.
        e.setdefault("PIBT_TURN_BODY_GEO", "1")
        e.setdefault("PIBT_TURN_BODY_MAX", "20")
        # 실행 속도를 DES 순항 속도에 맞춘다. DES 는 적재 무게로 속도를 바꿀 수 있다.
        sp = slice_meta.get("speed_mps")
        if isinstance(sp, (int, float)) and not isinstance(sp, bool) and sp > 0:
            e.setdefault("PIBT_V_EXEC", f"{float(sp):g}")
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

    def fpv_video_path(self) -> str | None:
        """두 번째 시점 (-264). **이름만** 다르다 — `demo_<run_id>_fpv.mp4`.

        백엔드는 상단 객체 키에서 `_fpv` 를 계산해 MinIO 에 실제로 있는지
        확인한 뒤 화면에 버튼을 띄운다. 그래서 결과 페이로드(artifacts)도
        NDATA 메트릭도 안 바뀐다. **이름이 어긋나면 오류 없이 버튼만 안 생긴다.**

        없으면 None 이다 — 측면은 **선택**이고, 없다고 런을 실패로 보지 않는다.
        """
        p = os.path.join(self.cfg.out_dir, f"demo_{self.tag()}_fpv.mp4")
        return p if self.spec and os.path.isfile(p) and os.path.getsize(p) > 0 else None

    def fpv_shots_dir(self) -> str:
        """두 번째 시점의 프레임 폴더 — `run_record.sh:116` 의 `shots_<TAG>_fpv`."""
        return os.path.join(self.cfg.out_dir, f"shots_{self.tag()}_fpv")

    def remove_frames(self) -> int:
        """프레임 폴더를 통째로 지운다 — mp4 가 **올라간 뒤에만** 부른다(-241).

        ★ 상단과 측면을 **둘 다** 지운다 (-264). 측면이 생기면서 한 런의
          프레임이 두 배가 됐는데(13대 10분 판에서 상단만 14 GB) 청소가
          상단에만 걸려 있었다.

        지운 파일 수(두 폴더 합)를 돌려주고, 없으면 0.
        """
        if not self.spec:
            return 0
        n = 0
        for d in (self.shots_dir(), self.fpv_shots_dir()):
            if not os.path.isdir(d):
                continue
            n += sum(len(files) for _, _, files in os.walk(d))
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

    def write_trajectory(self, spec: RunSpec) -> tuple:
        """인라인 궤적을 `runs/<run_id>/traj.json` 으로 푼다 (-275). (경로, slice) · 없으면 (None, None).

        형식이 틀리면 ValueError — 런을 띄우기 전에 실패로 돌려보낸다.
        """
        if not spec.trajectory_b64:
            return None, None
        body, sl = decode_trajectory(spec.trajectory_b64)
        d = os.path.join(self.cfg.runs_dir, spec.run_id)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "traj.json")
        with open(path, "wb") as f:
            f.write(body)
        return path, sl

    def physics_path(self) -> str:
        return physics_path(self.cfg, self.tag())

    def physics(self) -> dict | None:
        """러너가 쓴 물리 지표(`physics_report.summarize`). 없거나 못 읽으면 None."""
        if not self.spec:
            return None
        try:
            with open(self.physics_path(), encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, ValueError):
            return None
        return doc if isinstance(doc, dict) else None

    def _rotate_logs(self, spec: RunSpec) -> None:
        """같은 run_id 의 **지난 로그를 밀어낸다** (-275).

        ☹ run_id 는 다시 쓰인다(DB 를 새로 만들면 verify_18 이 또 온다, 재검증도 같은 id).
          로그를 이어 쓰면 지난 판의 「촬영 ON」·`[hl] sim` 줄이 새 판의 판정에 섞인다 —
          09-24 verify_18 이 시작 0.2 초 만에 RUNNING 이 된 것이 그것이다. 지난 판의
          시뮬 시각이 읽히면 host-orch 가 창을 엉뚱하게 끊을 수도 있다.
        지난 것은 `.prev` 한 벌만 남긴다(진단용). 지난 물리 지표 파일은 지운다.
        """
        for p in (self.record_log(), os.path.join(self.cfg.logs_dir, f"edge_{spec.run_id}.log")):
            if os.path.exists(p):
                os.replace(p, p + ".prev")
        try:
            os.remove(self.physics_path())
        except FileNotFoundError:
            pass

    # ---- 수명 -----------------------------------------------------------------
    def start(self, spec: RunSpec, now: float) -> None:
        self.spec = spec
        os.makedirs(self.cfg.logs_dir, exist_ok=True)
        self._rotate_logs(spec)
        traj_path, sl = self.write_trajectory(spec)
        if traj_path:
            log.info("run %s: DES 구간 재생 — t0 %s s · 워밍업 %s s + 창 %s s -> %s", spec.run_id,
                     (sl or {}).get("t0_s"), (sl or {}).get("warmup_s"), (sl or {}).get("window_s"),
                     traj_path)
        elif spec.trajectory:
            log.info("run %s: 궤적 재생 (경로) — %s", spec.run_id, spec.trajectory)
        elif spec.orders is not None:
            n = len(spec.orders.get("outbound") or []) if isinstance(spec.orders, dict) else 0
            log.info("run %s: 백엔드 주문 %d건 — 러너가 JsonOrderStream 으로 읽어 스스로 계획한다 "
                     "(포장대는 러너 난수, DES 와 같은 판은 아니다)", spec.run_id, n)
        env = environment(self.cfg, spec, scenario_path=self.write_scenario(spec),
                          traj_path=traj_path, slice_meta=sl)
        if env.get("PIBT_TRAJ"):
            # 같은 run_id 의 지난 구간이 지은 계획·씬을 비운다 — 폴더가 있으면 run_record 가 재사용한다
            for key in ("T3AMR_PLAN", "T3AMR_STAGE"):
                d = env.get(key)
                if d and os.path.abspath(d).startswith(os.path.abspath(self.cfg.runs_dir) + os.sep):
                    shutil.rmtree(d, ignore_errors=True)
                    os.makedirs(d, exist_ok=True)
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

    def sim_time(self) -> float | None:
        """지금까지 돈 **시뮬 시각**(초). 못 읽으면 None.

        ★ 왜 로그를 파나 — 시뮬 시각은 Isaac 프로세스 안에만 있고, 엣지와
        그 프로세스 사이의 채널은 이 로그뿐이다 (`_log_has` 가 쓰는 것과 같은
        typescript). 헤드리스 러너가 `PIBT_HL_REPORT` 스텝마다 한 줄 찍는다
        (`headless_pibt.py:343`) — 기본 600스텝 = 시뮬 10초마다다.

            [hl] sim    123.4s | 벽시계    75.2s | 배속  1.64x (순간 ...

        마지막 줄을 쓴다. 파일 끝에서만 읽으므로 런이 길어져도 비용이 일정하다.
        Kit(`--exec live_pibt.py`) 경로는 이 줄을 안 찍는다 — 그 경로에서는
        None 이 나오고, host-orch 가 예전처럼 벽시계로 창을 끊는다.
        """
        try:
            with open(self.record_log(), "rb") as f:
                f.seek(0, os.SEEK_END)
                back = min(f.tell(), SIM_TIME_TAIL_BYTES)
                f.seek(-back, os.SEEK_END)
                tail = f.read().decode("utf-8", "replace")
        except OSError:
            return None
        lines = [ln for ln in tail.splitlines() if SIM_TIME_RE.search(ln)]
        if not lines:
            return None
        last = lines[-1]
        # 구간 재생이면 워밍업을 뺀 **창 시각**을 쓴다 (-275) — host-orch 는 창 10분을 센다.
        w = WINDOW_TIME_RE.search(last)
        return float(w.group(1)) if w else float(SIM_TIME_RE.search(last).group(1))

    def ready(self) -> bool:
        """촬영이 실제로 켜졌나 = RUNNING 조건."""
        return self.frames() > 0 or self._log_has(READY_MARKERS)

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
