# -*- coding: utf-8 -*-
"""어댑터 공용 — 기존 CLI 를 그대로 부르는 얇은 껍데기."""
import os
import subprocess
import sys

from . import MAKE_PATH, ROOT, default_map


# 계획 스크립트가 있을 수 있는 폴더. 배치가 두 가지다 —
#   amr/make_path/   계획기 본체 (로컬 원본)
#   path/            실행·계획 모듈 (서버 재구성 후 배치. pibt_scene 등이 여기 있다)
# 어느 쪽에 있든 돌아가야 한다. 러너(live_*.py)가 BASE 와 BASE/path 를 모두 보는
# 것과 같은 이유다 — 한쪽만 보면 배치가 바뀔 때 조용히 깨진다 (2026-09-07).
SCRIPT_DIRS = (MAKE_PATH, os.path.join(ROOT, "path"))


def script_dir(name):
    """스크립트가 실제로 있는 폴더. 없으면 MAKE_PATH."""
    for d in SCRIPT_DIRS:
        if os.path.isfile(os.path.join(d, name)):
            return d
    return MAKE_PATH


def run(argv, cwd=None):
    """계획기 CLI 를 그대로 실행한다. 실패하면 예외."""
    cwd = cwd or script_dir(argv[0])
    cmd = [sys.executable] + argv
    print("  $ " + " ".join(cmd))
    r = subprocess.run(cmd, cwd=cwd, text=True, encoding="utf-8",
                       errors="replace", capture_output=True)
    out = (r.stdout or "") + (r.stderr or "")
    for ln in out.splitlines():
        print("    " + ln)
    if r.returncode != 0:
        raise SystemExit(f"실패 (exit {r.returncode})")
    return out


def verify_traj(traj, map_dir=None):
    """validate.py 3항목. 통과면 True."""
    out = run(["validate.py", "--traj", traj,
               "--file1", map_dir or default_map()])
    return "NG" not in out and "실패" not in out


def rel(*p):
    return os.path.join(ROOT, *p)


# ============================================================
# 서버 명령 조립 — **공통은 여기 한 곳에만 둔다.**
#
# 계획기마다 복사해 두었더니 `LIVE_LITE` 하나 빼는 데 파일 3개를 고쳐야 했다
# (2026-09-06). 계획기 모듈은 **자기만 다른 것**(환경변수·러너·USD 이름)만
# 선언하고, 기동 방식은 여기서 결정한다.
# ============================================================
import os as _os

# ── 스트리밍 on/off (patch_stream.py) ───────────────────────────────
# `--no-window` 라서 창은 애초에 없는데, streaming experience 는 창 유무와
# 무관하게 매 프레임 WebRTC 용 프레임을 만든다. 측정할 때는 아무도 안 본다.
#
#   실측 2026-09-07 (12대 · seed 1 · robot_first)
#     streaming   50.51 ms/스텝  0.330x  완주 36.9분
#     headless    27.03 ms/스텝  0.617x  완주 19.7분
#   started/completed 가 t=10·20·30s 에서 완전히 일치한다 -> 물리는 안 바뀐다.
#   (+ LIVE_LITE 24그룹 숨김 21.08 ms, + 솔버 32/1 로 16.64 ms = 1.00x)
#
#   STREAM=0 bash run.sh --planner pibt_h    측정용. 화면·녹화는 안 된다
#   bash run.sh --planner pibt_h             시연용
#
# ★ 모듈 임포트 시점에 읽는다 -> python 이 뜨기 전에 정해져야 한다.
#   `run.sh` 가 환경을 물려주므로 위 형태로 전달된다. CLI 인자로는 못 만든다
#   (run.sh 는 영상 조립 trap 때문에 **exec 를 쓰지 않는다** — 2026-09-08 정정.
#    결론은 같지만 근거가 틀려 있었다)
#   (LAUNCH 가 main.py 의 argparse 보다 먼저 평가된다).
_STREAM = _os.environ.get("STREAM", "1") not in ("0", "", "false", "False")

LAUNCH = ("isaacsim isaacsim.exp.full.streaming --no-window" if _STREAM
          else "isaacsim isaacsim.exp.base.python --no-window")

# ── 스트리밍 포트 ───────────────────────────────────────────────────
# 기본은 Isaac 기본값 그대로다 (사내망 jupyter04 는 이 줄이 생기기 전과 동일).
#
# ★ 포트를 **바꿔서** 내보내는 클라우드가 있다 (2026-09-13 Brev 실측).
#   Brev 는 공개 포트를 제가 정한다 — 49100 을 열어 달라고 해도 밖에서는
#   57980 으로 뚫린다. WebRTC 는 SDP/ICE 후보에 **포트 번호가 그대로 실려서**
#   나가므로, 서버가 47998 을 알리면 클라이언트는 47998 로 쏘고 닫힌 포트에
#   부딪힌다 — 시그널링은 붙는데 화면만 안 나오는 그 증상이다.
#   Brev 쪽 **Destination Port 는 편집이 되므로** 공개 포트에 맞춰 놓고,
#   Isaac 도 같은 번호로 띄우면 번호가 끝까지 보존된다.
#
#   ★ `$VAR` 가 아니라 여기서 읽는다. `expand()`(=expandvars)는 정의가 없으면
#     `$SIGNAL_PORT` 를 **글자 그대로 넘긴다** — paths.sh 없이 부르면 Kit 이
#     포트를 파싱하다 죽는다. `_STREAM` 과 같은 방식으로 파이썬에서 받는다.
_SIGNAL_PORT = _os.environ.get("SIGNAL_PORT", "49100")    # TCP 시그널링
_STREAM_PORT = _os.environ.get("STREAM_PORT", "47998")    # UDP 미디어

# 모든 계획기에 붙는 플래그. 스트리밍·GPU 지정은 계획기와 무관하다.
_GPU_FLAG = "--/renderer/activeGpu=$GPU --/renderer/multiGpu/enabled=false"
_LS = "--/exts/omni.kit.livestream.app/primaryStream"
COMMON_FLAGS = ((
    "%s/publicIp=$LAN_IP" % _LS,
    "%s/signalPort=%s" % (_LS, _SIGNAL_PORT),
    "%s/streamPort=%s" % (_LS, _STREAM_PORT),
    _GPU_FLAG,
) if _STREAM else (
    _GPU_FLAG,
))

BUILDER = "runners/build_amr_scene_v2.py"


def server_paths(sub, usd, n=12):
    """서버 경로 3종. `cmds` 와 `run` 이 **같은 계산**을 쓰게 한다.

    expand=False 면 `$PLAN/...` 문자열 그대로(명령 출력용),
    True 면 환경변수를 펼친 실제 경로(실행용).
    """
    return {"traj":   "$PLAN/%s/fleet_%02d/trajectories.json" % (sub, n),
            "starts": "$PLAN/%s/fleet_%02d/starts.json" % (sub, n),
            "usd":    "$STAGE/%s" % usd}


def expand(v):
    return os.path.expandvars(v)


SHELF_USD = "$W/robots/shelf/amr_shelf.usd"


def scene_cmd(sub, usd, n=12):
    """씬 빌드 명령.

    계획기마다 다른 것은 `$PLAN` 하위 폴더명(SUB)과 결과 USD 이름(USD)뿐이다.
    `$SCENE`·`$ROBOT` 을 변수로 쓰는 것이 중요하다 — 상대경로를 주면 CWD 가 아니라
    **출력 USD 폴더 기준**으로 풀려 창고도 로봇도 없는 씬이 나온다 (2026-09-06 재발).

    ★ **선반을 여기서 넘긴다** (2026-09-14). 예전에는 안 넘겼다. 그런데
      `main.py:128` 은 계획이 USD 보다 새로우면 **자동으로 씬을 다시 짓고**,
      그 경로가 이 함수다. 즉 계획을 새로 세운 다음 `run.sh` 를 돌리면
      선반이 조용히 사라진다 — 오류도 경고도 없이 그림만 달라진다.
      실제로 당했다: `run.sh` 로 완주 기록을 만든 뒤 `run_onboard.sh` 를
      돌렸더니 선반 없이 AMR 만 달렸다.
      `run_webrtc.sh` 는 이걸 알고 **씬을 따로 지어** 우회하고 있었다
      (`run_webrtc.sh:169` 주석). 우회를 지우고 여기서 고친다 — 그래야
      `run.sh`·`run_record.sh`·`run_onboard.sh` 전부 같은 씬을 얻는다.

      에셋이 없으면(로컬·미생성) 예전처럼 로봇만 세운다. 선반은 git 제외라
      서버에서 `warehouse/scene/build_amr_shelf.py` 로 만든다.
    """
    P = server_paths(sub, usd, n)
    cmd = ["python %s --n %d \\" % (BUILDER, n),
           "    --warehouse $SCENE \\",
           "    --robot     $ROBOT \\",
           "    --traj      %s \\" % P["traj"],
           "    --starts    %s \\" % P["starts"]]
    if os.path.exists(expand(SHELF_USD)):
        cmd.append("    --shelf     %s \\" % SHELF_USD)
    cmd.append("    --out       %s" % P["usd"])
    return cmd


class Launch(object):
    """서버 기동 정의.

    **명령을 찍는 것(`cmds`)과 실제로 실행하는 것(`run`)이 같은 데이터를 쓴다.**
    예전에는 실행용 셸 스크립트가 계획기 표를 따로 들고 있어서, 계획기를 하나
    추가하면 두 곳을 고쳐야 했다 (2026-09-06). 표는 계획기 모듈에만 둔다.
    """

    def __init__(self, runner, env, flags=(), notes=()):
        self.runner = runner            # runners/ 의 --exec 스크립트
        self.env = list(env)            # [(이름, 값)] — 값에 $VAR 를 써도 된다
        self.flags = list(flags)        # 계획기 전용 Kit 플래그
        self.notes = list(notes)

    def lines(self):
        """붙여넣을 수 있는 셸 명령."""
        out = ["# " + t for t in self.notes]
        out += ["%s=%s \\" % (k, v) for k, v in self.env]
        out.append(LAUNCH + " \\")
        out += ["    " + f + " \\" for f in list(COMMON_FLAGS) + list(self.flags)]
        out.append("    --exec $W/runners/%s" % self.runner)
        return out

    def argv(self):
        """(환경변수 dict, argv) — os.execvpe 로 바로 넘길 수 있는 형태."""
        env = {k: expand(v) for k, v in self.env}
        args = LAUNCH.split()
        for f in list(COMMON_FLAGS) + list(self.flags):
            args += [expand(x) for x in f.split()]
        args += ["--exec", expand("$W/runners/%s" % self.runner)]
        return env, args
