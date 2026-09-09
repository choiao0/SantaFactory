"""sim_runner 테스트 공용 가짜: Popen · publisher · 시나리오 헬퍼."""
import json

from sim_runner import procs as P
from sim_runner import runner as R
from sim_runner import spb


class FakePopen:
    _next_pid = 5000

    def __init__(self, argv, **kw):
        FakePopen._next_pid += 1
        self.argv, self.kw, self.pid, self.rc, self.signals = argv, kw, FakePopen._next_pid, None, []

    def poll(self):
        return self.rc

    def send_signal(self, sig):
        self.signals.append(sig)


class FakePublisher:
    def __init__(self):
        self.msgs = []      # (topic, Decoded, qos, retain)

    def publish(self, topic, payload, qos=0, retain=False):
        self.msgs.append((topic, spb.decode(payload), qos, retain))

    def kinds(self):
        return [t.split("/")[2] for t, *_ in self.msgs]

    def last(self, kind):
        return next((d for t, d, *_ in reversed(self.msgs) if t.split("/")[2] == kind), None)

    def named(self, kind):
        d = self.last(kind)
        return spb.metrics_by_name(d) if d else None

    def clear(self):
        self.msgs.clear()


def start_payload(run_id="run-1", n=2, timeout_s=600, **over):
    d = {"run_id": run_id, "scenario_pkg": "pkg", "n_robots": n, "models": [], "ros_domain_id": 0,
         "timeout_s": timeout_s}
    d.update(over)
    return json.dumps(d)


def ncmd(**metrics):
    types = {R.CMD_START: spb.TEXT, R.CMD_STOP: spb.BOOLEAN, R.REBIRTH: spb.BOOLEAN}
    return spb.encode_cmd([(name, types[name], v) for name, v in metrics.items()])


def vda_connection(serial, state="ONLINE", mfr="idealworks"):
    return f"uagv/v2/{mfr}/{serial}/connection", json.dumps({"connectionState": state}).encode()


def vda_state(serial, x=0.0, y=0.0, theta=0.0, battery=100.0, node="", ts="2026-09-08T10:00:00.000Z"):
    msg = {"timestamp": ts, "lastNodeId": node, "agvPosition": {"x": x, "y": y, "theta": theta},
           "batteryState": {"batteryCharge": battery}}
    return f"uagv/v2/idealworks/{serial}/state", json.dumps(msg).encode()


class Harness:
    """Runner + 가짜 publisher/procs/telemetry. 벽시계는 now 로 직접 민다."""

    def __init__(self, tmp_path, fake=True, **cfg):
        self.spawned = []
        self.pub = FakePublisher()
        self.session = spb.EdgeSession(str(tmp_path / "bdseq"))
        self.session.new_session()
        env = P.LaunchEnv("broker", 1883, "pw", isaac_cmd="isaac", isaac_warmup_s=0)
        self.runs_dir = str(tmp_path / "runs")
        self.telemetry = {"ram": 100, "vram": 2000}
        self.runner = R.Runner(R.RunnerConfig(**cfg), self.session, lambda: self._procs(env, fake), self.pub,
                               ram_mb=lambda pids: self.telemetry["ram"], vram_mb=lambda: self.telemetry["vram"])

    def _procs(self, env, fake):
        def spawn(argv, **kw):
            p = FakePopen(argv, **kw)
            self.spawned.append(p)
            return p
        return P.ProcessManager(env, fake=fake, spawn=spawn, send=lambda proc, sig: proc.signals.append(sig),
                                runs_dir=self.runs_dir)

    def connect(self, now=0.0):
        self.runner.on_connected(now)
        self.pub.clear()

    def start(self, now=0.0, **kw):
        self.runner.on_ncmd(ncmd(**{R.CMD_START: start_payload(**kw)}), now)

    def all_online(self, serials=("amr01", "amr02")):
        for s in serials:
            self.runner.on_vda(*vda_connection(s), 0.0)

    def all_ready(self, serials=("amr01", "amr02")):
        """ONLINE + 포즈 한 번 (실모드에선 Isaac odom 이 와야 생기는 조건)."""
        for s in serials:
            self.runner.on_vda(*vda_connection(s), 0.0)
            self.runner.on_vda(*vda_state(s), 0.0)

    def run_until_running(self, now=1.0, serials=("amr01", "amr02")):
        self.start(now=0.0, n=len(serials))
        self.all_ready(serials)
        self.runner.tick(now)
        assert self.runner.state == R.RUNNING
        self.pub.clear()

    def exit_all(self, rc=0):
        for p in self.spawned:
            p.rc = rc
