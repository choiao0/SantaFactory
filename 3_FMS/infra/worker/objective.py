# -*- coding: utf-8 -*-
# ============================================================
# θ 하나를 시뮬로 채점한다 (S15P21A106-127)
#
# sim_v2_tasks.py 를 별도 프로세스로 호출한다. import 하지 않는 이유:
#   - sim_v2 는 최상위에서 argv 를 읽고 틱 루프를 도는 스크립트다
#   - 극단 θ 는 시뮬을 정체시킬 수 있어(θ 스키마 합의안 참고) wall-clock
#     timeout 으로 프로세스째 끊을 수단이 필요하다
#
# 목적함수를 여기에 박지 않는다. KPI 전체를 돌려주고 무엇을 최소화할지는
# 호출자가 고른다. 2026-09-03 실측에서 처리량 차이(0.03)가 seed 산포(17.7)에
# 묻혀 목적함수를 확정할 수 없었다 — 주문 도착률이 병목이라 로봇이 서로
# 방해하지 않기 때문이다. 그 병목은 --order-gap 으로 풀렸고(SIM_RUN_CONTRACT
# §1·§5), 목적함수 확정은 θ 감도 실험(S15P21A106-138)에서 한다.
#
# 호출 규약의 단일 출처: 3_FMS/contracts/SIM_RUN_CONTRACT.md (v2).
# 여기 없는 인자·SUMMARY 키에 의존하지 않는다.
# ============================================================
import json
import os
import statistics
import subprocess
import sys
import tempfile

# 시뮬 1회 상한. 정체(sim_v2 워치독은 1500틱 무진전에서 SystemExit)가 걸려도
# 프로세스가 안 죽는 경우를 대비한 바깥 울타리.
DEFAULT_TIMEOUT_S = 300

# 시뮬 1회 실측은 SIM_RUN_CONTRACT §4 표를 볼 것. 성능 최적화(-136) 후
# 24대·120주문·간격15 가 7.6 s 다(최적화 전 46 s). 예산은 헤딩 기준으로 잡는다.
SUMMARY_MARK = "[SUMMARY]"


class SimFailed(RuntimeError):
    """시뮬이 비정상 종료했거나 시간을 넘겼다."""


def tick_seconds(speed, sim_engine_dir):
    """이 속도에서 헤딩 모델의 틱 하나가 몇 초인가 (계약 v3.6 = CELL_M / (speed x MOVE_TICKS)).

    **시뮬과 같은 상수를 읽는다.** 여기 숫자를 또 적으면 틱 모델이 바뀔 때 워커만 옛 값을
    쓰게 되고, 그러면 워커가 의도한 초가 시뮬에서 다른 초가 된다 — v3.3 의 CELL_M / speed
    를 v4 에 그대로 쓰면 --horizon 이 4배 짧아진다(6h 요청이 1.5h 로 돈다).
    계약 §5-1 이 "틱 단위 인자는 호출자가 환산" 이라고 그 책임을 이쪽에 둔 지점이다.

    θ 탐색 워커(run_study)와 견적 워커(estimate_worker)가 같이 쓴다.
    """
    if sim_engine_dir not in sys.path:
        sys.path.insert(0, sim_engine_dir)
    from map_loader import CELL_M
    from pibt_core import MOVE_TICKS
    return CELL_M / (speed * MOVE_TICKS)


def run_once(sim_engine_dir, theta_path, n_robots, n_orders, seed,
             aisle_block=1, flow="main", tag="bo", timeout_s=DEFAULT_TIMEOUT_S,
             cell=False, order_gap=None, extra_args=()):
    """sim_v2 를 한 번 돌리고 [SUMMARY] dict 를 돌려준다.

    인자·플래그는 SIM_RUN_CONTRACT.md v2 §1 을 따른다. 기본값은 같은 문서
    §5 의 "θ 탐색 권장 조건"(헤딩 = v2 기본, aisle_block=1)에 맞춰 두었다 —
    호출자가 아무것도 지정하지 않아도 계약이 권장하는 조건이 나온다.
    """
    cmd = [sys.executable, "sim_v2_tasks.py", tag,
           str(n_robots), str(n_orders), str(seed), str(aisle_block),
           f"--flow={flow}"]
    # theta_path=None 이면 --theta 를 붙이지 않는다 = uniform 비용(기준선).
    # 중립 θ 가 기준선을 재현하는지 확인하려면 두 실행이 모두 필요하다.
    if theta_path is not None:
        cmd.append(f"--theta={theta_path}")
    # 계약 v2: 헤딩이 기본이고 칸 모델이 --cell opt-in 이다. v1 의 --heading 은
    # 무시되므로 "안 넘기면 칸"이 아니다 — 넘기지 않는 것으로 칸을 얻던 v1 호출은
    # 조용히 헤딩으로 돌아간다. 그래서 플래그를 heading 이 아니라 cell 로 뒤집었다.
    if cell:
        cmd.append("--cell")
    if order_gap is not None:
        cmd.append(f"--order-gap={order_gap}")
    cmd.extend(extra_args)
    env = dict(os.environ, SIM_NO_PLOT="1", PYTHONIOENCODING="utf-8")
    try:
        proc = subprocess.run(cmd, cwd=sim_engine_dir, env=env, timeout=timeout_s,
                              capture_output=True, text=True, encoding="utf-8")
    except subprocess.TimeoutExpired as exc:
        raise SimFailed(f"시뮬 {timeout_s}s 초과 (seed={seed})") from exc
    if proc.returncode != 0:
        tail = (proc.stdout or "")[-600:] + (proc.stderr or "")[-600:]
        raise SimFailed(f"시뮬 실패 rc={proc.returncode} (seed={seed})\n{tail}")
    for line in proc.stdout.splitlines():
        if SUMMARY_MARK in line:
            return json.loads(line.split(SUMMARY_MARK, 1)[1])
    raise SimFailed(f"{SUMMARY_MARK} 를 못 찾음 (seed={seed})")


def write_theta(theta, directory=None):
    """θ dict 를 sim_v2 --theta 가 읽을 json 파일로. 경로를 돌려준다."""
    fd, path = tempfile.mkstemp(prefix="theta_", suffix=".json", dir=directory)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(theta, f)
    return path


def evaluate(theta, sim_engine_dir, n_robots, n_orders, seeds,
             timeout_s=DEFAULT_TIMEOUT_S, **run_kwargs):
    """θ 를 seed 여러 개로 돌려 KPI 평균·산포를 돌려준다.

    seed 하나로 θ 를 고르면 **seed 운을 최적화한다.** 2026-09-03 실측에서
    처리량 seed 산포가 17.7 이었는데 중립 θ 대비 극단 θ 의 차이는 0.03 이었다.
    시뮬이 확률적이므로 반복 평균이 필수다.

    반환 {"mean": {...}, "spread": {...}, "runs": [...]}
    """
    if not seeds:
        raise ValueError("seed 가 최소 하나 필요하다")
    path = write_theta(theta)
    try:
        runs = [run_once(sim_engine_dir, path, n_robots, n_orders, s,
                         timeout_s=timeout_s, **run_kwargs) for s in seeds]
    finally:
        os.unlink(path)

    keys = [k for k, v in runs[0].items() if isinstance(v, (int, float))]
    mean = {k: statistics.fmean(r[k] for r in runs) for k in keys}
    spread = {k: max(r[k] for r in runs) - min(r[k] for r in runs) for k in keys}
    return {"mean": mean, "spread": spread, "runs": runs}
