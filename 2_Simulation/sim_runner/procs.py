"""런 프로세스 관리 — 에이전트 ×N (+ 실모드 Isaac). 명령 조립은 순수 함수, 기동·시그널은 주입 가능(테스트).

종료 사다리: SIGINT(ros2 launch 가 자식에 전파, 브리지가 OFFLINE 발행) → 유예 뒤 SIGTERM(그룹) → SIGKILL(그룹).
논블로킹: request_stop() 뒤 poll(now) 를 tick 마다 불러 단계가 진행된다.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import signal
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import psutil

DEFAULT_MANUFACTURER = "idealworks"
DEFAULT_MODEL = "iw_hub"
MAX_ROBOTS = 64
MAX_ROS_DOMAIN_ID = 232
DEFAULT_TIMEOUT_S = 3600.0
FAKE_SPACING_M = 3.0            # 가짜 로봇 초기 x 간격 (t4_agent README: fake_x:=3.0)
AGENT_GRACE_S = 5.0             # SIGINT 뒤 OFFLINE 발행 여유
ISAAC_GRACE_S = 20.0
TERM_GRACE_S = 3.0
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")   # run_id · serial: 로그 파일명 · 토픽에 들어간다
RUN_ENV_MARK = "SIM_RUN_ID"


@dataclass(frozen=True)
class RobotSpec:
    serial: str
    manufacturer: str = DEFAULT_MANUFACTURER
    model: str = DEFAULT_MODEL


@dataclass(frozen=True)
class RunSpec:
    """NCMD `Run Control/Start` JSON (MQTT_CONTRACT §5.3)."""
    run_id: str
    n_robots: int
    robots: tuple
    scenario_pkg: str = ""
    ros_domain_id: int = 0
    timeout_s: float = DEFAULT_TIMEOUT_S

    @staticmethod
    def from_json(text: str) -> "RunSpec":
        try:
            d = json.loads(text)
        except ValueError as e:
            raise ValueError(f"Start payload is not JSON: {e}") from None
        if not isinstance(d, dict):
            raise ValueError("Start payload must be a JSON object")
        return RunSpec.from_dict(d)

    @staticmethod
    def from_dict(d: dict) -> "RunSpec":
        run_id = d.get("run_id")
        if not isinstance(run_id, str) or not SAFE_ID.match(run_id.strip()):
            raise ValueError("run_id must match [A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
        n = d.get("n_robots")
        if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= MAX_ROBOTS:
            raise ValueError(f"n_robots must be an integer in 1..{MAX_ROBOTS}")
        domain = d.get("ros_domain_id", 0)
        if not isinstance(domain, int) or isinstance(domain, bool) or not 0 <= domain <= MAX_ROS_DOMAIN_ID:
            raise ValueError(f"ros_domain_id must be an integer in 0..{MAX_ROS_DOMAIN_ID}")
        timeout = d.get("timeout_s", DEFAULT_TIMEOUT_S)
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
            raise ValueError("timeout_s must be a positive number")
        return RunSpec(run_id.strip(), n, _robots(d.get("models"), n), str(d.get("scenario_pkg", "") or ""),
                       domain, float(timeout))


def _robots(models: Any, n: int) -> tuple:
    if not models:
        return tuple(RobotSpec(f"amr{i + 1:02d}") for i in range(n))
    if not isinstance(models, list) or len(models) != n:
        raise ValueError("models must list exactly n_robots entries")
    robots = []
    for m in models:
        serial = m.get("serial") if isinstance(m, dict) else None
        if not isinstance(serial, str) or not SAFE_ID.match(serial):
            raise ValueError("each models[] entry needs a serial matching [A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
        robots.append(RobotSpec(serial, str(m.get("manufacturer") or DEFAULT_MANUFACTURER),
                                str(m.get("model") or DEFAULT_MODEL)))
    if len({r.serial for r in robots}) != n:
        raise ValueError("models[] serials must be unique")
    return tuple(robots)


@dataclass(frozen=True)
class LaunchEnv:
    """브로커 · ROS 환경 · Isaac 명령 템플릿. isaac_cmd 는 셸 문자열, 환경변수 WSIM_N · ROS_DOMAIN_ID 를 받는다."""
    mqtt_host: str
    mqtt_port: int
    amr_password: str
    ros_setup: tuple = ()
    isaac_cmd: str = ""
    isaac_warmup_s: float = 90.0


def bash_wrap(setups: tuple, argv: list) -> list:
    """`bash -c 'source a && source b && exec <argv>'` — 데몬 환경과 무관하게 ROS 워크스페이스를 올린다."""
    parts = [f"source {shlex.quote(s)}" for s in setups] + ["exec " + shlex.join(argv)]
    return ["bash", "-c", " && ".join(parts)]


def agent_cmd(robot: RobotSpec, index: int, env: LaunchEnv, fake: bool) -> list:
    launch = ["ros2", "launch", "amr_agent", "agent.launch.py", f"serial:={robot.serial}",
              f"manufacturer:={robot.manufacturer}", f"model:={robot.model}",
              f"mqtt_host:={env.mqtt_host}", f"mqtt_port:={env.mqtt_port}",
              f"mqtt_username:={robot.serial}", f"mqtt_password:={env.amr_password}"]
    if fake:
        launch += ["fake_robot:=true", f"fake_x:={index * FAKE_SPACING_M:g}"]
    else:
        launch += ["pose_source:=odom", "use_sim_time:=true"]
    return bash_wrap(env.ros_setup, launch)


def isaac_cmd(env: LaunchEnv) -> list:
    return ["bash", "-c", env.isaac_cmd]


def run_env(spec: RunSpec, base: Optional[dict] = None) -> dict:
    e = dict(os.environ if base is None else base)
    e["ROS_DOMAIN_ID"] = str(spec.ros_domain_id)
    e["WSIM_N"] = str(spec.n_robots)
    e[RUN_ENV_MARK] = spec.run_id
    return e


def killpg_or_pid(proc: Any, sig: int) -> None:
    try:
        os.killpg(proc.pid, sig)
    except ProcessLookupError:
        pass
    except PermissionError:
        proc.send_signal(sig)


def _kill_pid_and_group(pid: int, sig: int) -> None:
    for fn in (os.killpg, os.kill):
        try:
            fn(pid, sig)
        except (ProcessLookupError, PermissionError):
            pass


def reap_stale(process_iter: Callable = psutil.process_iter, send: Callable[[int, int], None] = _kill_pid_and_group,
               me: Optional[int] = None) -> list:
    """지난 sim-runner 가 남긴 런 프로세스(환경에 SIM_RUN_ID) 를 그룹째 SIGKILL — 데몬 재시작 때 한 번.

    돌려주는 값: [(pid, run_id)]. 환경을 못 읽는 프로세스(남의 것)는 건너뛴다.
    """
    me = os.getpid() if me is None else me
    found = []
    for p in process_iter():
        try:
            run_id = p.environ().get(RUN_ENV_MARK)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        if run_id and p.pid != me:
            found.append((p.pid, run_id))
    for pid, _ in found:
        send(pid, signal.SIGKILL)
    return found


@dataclass
class Managed:
    """프로세스 하나 + 종료 사다리 진행 상태."""
    name: str
    proc: Any
    grace_s: float
    ladder: list = field(default_factory=list)      # [(signal, 다음 단계까지 유예)]
    stop_t: Optional[float] = None
    step: int = 0

    def alive(self) -> bool:
        return self.proc.poll() is None

    def request_stop(self, now: float, send: Callable[[Any, int], None]) -> None:
        """사다리 시작: SIGINT 를 즉시 launch 프로세스에 보낸다."""
        self.ladder = [(signal.SIGINT, self.grace_s), (signal.SIGTERM, TERM_GRACE_S), (signal.SIGKILL, TERM_GRACE_S)]
        self.stop_t, self.step = now, 0
        self._fire(now, send)

    def poll_stop(self, now: float, send: Callable[[Any, int], None]) -> bool:
        """직전 신호의 유예가 지나면 다음 칸(SIGTERM · SIGKILL, 그룹 대상). 죽었으면 True."""
        if not self.alive():
            return True
        if self.stop_t is None or self.step >= len(self.ladder):
            return False
        if now - self.stop_t >= self.ladder[self.step - 1][1]:
            self._fire(now, send)
        return False

    def _fire(self, now: float, send: Callable[[Any, int], None]) -> None:
        sig = self.ladder[self.step][0]
        if sig == signal.SIGINT:
            self.proc.send_signal(sig)
        else:
            send(self.proc, sig)
        self.stop_t, self.step = now, self.step + 1


class ProcessManager:
    """런 하나의 프로세스들. 실모드는 Isaac 먼저(예열 시간) → 에이전트, 정지는 에이전트 → Isaac."""

    def __init__(self, env: LaunchEnv, fake: bool, spawn: Callable = subprocess.Popen,
                 send: Callable[[Any, int], None] = killpg_or_pid, log_dir: Optional[str] = None):
        self.env, self.fake, self.spawn, self.send, self.log_dir = env, fake, spawn, send, log_dir
        self.agents: list[Managed] = []
        self.isaac: Optional[Managed] = None
        self.spec: Optional[RunSpec] = None
        self._isaac_started_at: Optional[float] = None

    def start(self, spec: RunSpec, now: float) -> None:
        self.spec = spec
        if self.fake:
            self._start_agents(spec)
            return
        if not self.env.isaac_cmd:
            raise RuntimeError("real mode needs --isaac-cmd")
        self.isaac = Managed("isaac", self._spawn("isaac", isaac_cmd(self.env), spec), ISAAC_GRACE_S)
        self._isaac_started_at = now

    def poll_start(self, now: float) -> None:
        """실모드: Isaac 예열이 끝나면 에이전트를 띄운다(한 번)."""
        if self.fake or self.agents or self.spec is None or self._isaac_started_at is None:
            return
        if now - self._isaac_started_at >= self.env.isaac_warmup_s:
            self._start_agents(self.spec)

    def _start_agents(self, spec: RunSpec) -> None:
        self.agents = [Managed(r.serial, self._spawn(r.serial, agent_cmd(r, i, self.env, self.fake), spec),
                               AGENT_GRACE_S) for i, r in enumerate(spec.robots)]

    def _spawn(self, name: str, argv: list, spec: RunSpec) -> Any:
        if not self.log_dir:
            return self.spawn(argv, env=run_env(spec), start_new_session=True, stdout=subprocess.DEVNULL,
                              stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        os.makedirs(self.log_dir, exist_ok=True)
        with open(os.path.join(self.log_dir, f"{spec.run_id}.{name}.log"), "ab") as out:   # 자식이 fd 를 물려받는다
            return self.spawn(argv, env=run_env(spec), start_new_session=True, stdout=out, stderr=subprocess.STDOUT,
                              stdin=subprocess.DEVNULL)

    def agents_started(self) -> bool:
        return bool(self.agents)

    def dead(self) -> list:
        """예기치 않게 죽은 프로세스 이름들(정지 요청 전 기준)."""
        managed = self.agents + ([self.isaac] if self.isaac else [])
        return [m.name for m in managed if m.stop_t is None and not m.alive()]

    def isaac_count(self) -> int:
        return 1 if self.isaac and self.isaac.alive() else 0

    def pids(self) -> list:
        return [m.proc.pid for m in self.agents + ([self.isaac] if self.isaac else []) if m.alive()]

    def request_stop(self, now: float) -> None:
        for m in self.agents:
            m.request_stop(now, self.send)
        if not self.agents and self.isaac:
            self.isaac.request_stop(now, self.send)

    def poll_stop(self, now: float) -> bool:
        """에이전트가 다 죽어야 Isaac 정지를 시작. 전부 죽었으면 True."""
        agents_done = all(m.poll_stop(now, self.send) for m in self.agents)
        if not agents_done:
            return False
        if self.isaac is None:
            return True
        if self.isaac.stop_t is None:
            self.isaac.request_stop(now, self.send)
        return self.isaac.poll_stop(now, self.send)

    def all_exited(self) -> bool:
        return not any(m.alive() for m in self.agents + ([self.isaac] if self.isaac else []))
