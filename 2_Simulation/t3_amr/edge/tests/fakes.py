"""edge 테스트 공용 가짜: publisher · recorder · uploader · 시나리오 헬퍼. 브로커·프로세스·Isaac 없이 상태기계를 민다.
"""
import json
from concurrent.futures import Future

from edge import runner as R
from edge import spb


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

    def named_with(self, kind, metric):
        """해당 메트릭을 담은 마지막 메시지 — 하트비트 NDATA 가 뒤에 섞여도 상태 전이 메시지를 집는다."""
        for t, d, *_ in reversed(self.msgs):
            if t.split("/")[2] == kind:
                named = spb.metrics_by_name(d)
                if metric in named:
                    return named
        return None

    def clear(self):
        self.msgs.clear()


class FakeRecorder:
    """Recorder 와 같은 인터페이스. 테스트가 플래그를 직접 민다."""

    def __init__(self, launch_error=None):
        self.launch_error = launch_error
        self.spec = None
        self.started = False
        self.stop_requested_at = None
        self._alive = False
        self.is_ready = False
        self.finished = False
        self.video = None
        self.exits_after_stop = True
        self.frames_removed = False
        self.sim_s = None                 # 시뮬 시각(초). None = 러너가 안 보고한다(Kit 경로)
        self.physics_doc = None           # 러너가 쓴 물리 지표(-275). None = 파일 없음

    def start(self, spec, now):
        if self.launch_error:
            raise self.launch_error
        self.spec, self.started, self._alive = spec, True, True

    def alive(self):
        return self._alive

    def dead(self):
        return self.started and self.stop_requested_at is None and not self._alive

    def ready(self):
        return self.is_ready

    def finished_normally(self):
        return self.finished

    def sim_time(self):
        return self.sim_s

    def physics(self):
        return self.physics_doc

    def request_stop(self, now):
        self.stop_requested_at = now

    def poll_stop(self, now):
        if self.exits_after_stop:
            self._alive = False
        return not self._alive

    def video_path(self):
        return self.video

    def fpv_video_path(self):
        """두 번째 시점 (-264). 기본은 None — 안 주면 종전 동작과 같다."""
        return getattr(self, "fpv_video", None)

    def pids(self):
        return [4242] if self._alive else []

    def isaac_count(self):
        return 1 if self._alive else 0

    def remove_frames(self):
        self.frames_removed = True
        return 3

    def die(self):
        self._alive = False


class ImmediateExecutor:
    """submit 을 그 자리에서 실행 — 상태기계 테스트를 결정적으로."""

    def submit(self, fn, *args, **kwargs):
        f = Future()
        try:
            f.set_result(fn(*args, **kwargs))
        except Exception as e:  # noqa: BLE001 — 테스트용
            f.set_exception(e)
        return f


class ManualExecutor:
    """submit 은 미완료 Future 를 돌려주고, 테스트가 complete()/fail() 로 끝낸다 — 업로드 진행 중 동작 검증용."""

    def __init__(self):
        self.pending = []

    def submit(self, fn, *args, **kwargs):
        f = Future()
        self.pending.append((f, fn, args))
        return f

    def complete(self, value):
        f, *_ = self.pending.pop(0)
        f.set_result(value)

    def fail(self, exc):
        f, *_ = self.pending.pop(0)
        f.set_exception(exc)


class FakeUploader:
    def __init__(self, fail=None):
        self.fail, self.calls = fail, []

    def upload(self, path, run_id):
        self.calls.append((path, run_id))
        if self.fail:
            raise self.fail
        return f"{run_id}/{path.rsplit('/', 1)[-1]}"      # 버킷 없는 객체 키 (-233)


def start_payload(run_id="verify_77_n3", n=3, timeout_s=900, **over):
    d = {"run_id": run_id, "scenario_pkg": "wallA_v6", "n_robots": n, "models": [], "ros_domain_id": 0,
         "timeout_s": timeout_s}
    d.update(over)
    return json.dumps(d)


def ncmd(**metrics):
    types = {R.CMD_START: spb.TEXT, R.CMD_STOP: spb.BOOLEAN, R.REBIRTH: spb.BOOLEAN}
    return spb.encode_cmd([(name, types[name], v) for name, v in metrics.items()])


class Harness:
    """Runner + 가짜 publisher/recorder/uploader/telemetry. 벽시계는 now 로 직접 민다."""

    def __init__(self, tmp_path, uploader=None, executor=None, **cfg):
        self.pub = FakePublisher()
        self.session = spb.EdgeSession(str(tmp_path / "bdseq"))
        self.session.new_session()
        self.rec = FakeRecorder()
        self.uploader = uploader if uploader is not None else FakeUploader()
        self.telemetry = {"ram": 100, "vram": 2000}
        self.gpu_error = None           # 문자열이면 Start 직전 GPU 프로브가 그 사유로 실패한다 (-241)
        self.gpu_lost = 0               # on_gpu_lost 호출 횟수
        self.runner = R.Runner(R.RunnerConfig(**cfg), self.session, lambda: self.rec, self.pub, self.uploader,
                               ram_mb=lambda pids: self.telemetry["ram"], vram_mb=lambda: self.telemetry["vram"],
                               executor=executor if executor is not None else ImmediateExecutor(),
                               gpu_probe=lambda: self.gpu_error, on_gpu_lost=self._on_gpu_lost)

    def _on_gpu_lost(self):
        self.gpu_lost += 1

    def connect(self, now=0.0):
        self.runner.on_connected(now)
        self.pub.clear()

    def start(self, now=1.0, **over):
        self.runner.on_ncmd(ncmd(**{R.CMD_START: start_payload(**over)}), now)

    def run_until_running(self, now=2.0, **over):
        self.start(now - 1.0, **over)
        self.rec.is_ready = True
        self.runner.tick(now)
        assert self.runner.state == R.RUNNING
        self.pub.clear()

    def stop(self, now):
        self.runner.on_ncmd(ncmd(**{R.CMD_STOP: True}), now)
