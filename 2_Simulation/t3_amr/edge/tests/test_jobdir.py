"""edge.jobdir — 폴더 입구. 집는 순서 · 쓰는 중 보호 · 바쁠 때 보류 · 실패 격리."""
import json
import os

from edge import jobdir as J
from edge.spec import RunSpec


def _job(run_id="r1", n=12, **scenario):
    d = {"run_id": run_id, "n_robots": n, "timeout_s": 1200}
    if scenario:
        d["scenario"] = scenario
    return json.dumps(d)


def _put(root, name, text, mtime):
    p = os.path.join(root, J.INBOX, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    os.utime(p, (mtime, mtime))
    return p


def _mk(tmp_path, submitted, idle=True):
    root = str(tmp_path)
    J.ensure_dirs(root)
    jd = J.JobDir(J.JobDirConfig(root, settle_s=1.0),
                  submit=lambda text, now: submitted.append(text),
                  is_idle=lambda: idle)
    return root, jd


def test_picks_oldest_first_and_moves_to_started(tmp_path):
    sub = []
    root, jd = _mk(tmp_path, sub)
    _put(root, "b.json", _job("second"), mtime=200.0)
    _put(root, "a.json", _job("first"), mtime=100.0)

    dst = jd.poll(now=1000.0)

    assert sub and RunSpec.from_json(sub[0]).run_id == "first"
    assert os.path.dirname(dst).endswith(J.STARTED) and "first" in os.path.basename(dst)
    # 한 틱에 하나만 집는다 — 나머지는 inbox 에 남는다
    assert os.listdir(os.path.join(root, J.INBOX)) == ["b.json"]


def test_leaves_file_when_busy(tmp_path):
    sub = []
    root, jd = _mk(tmp_path, sub, idle=False)
    _put(root, "a.json", _job(), mtime=100.0)

    assert jd.poll(now=1000.0) is None
    assert not sub
    assert os.listdir(os.path.join(root, J.INBOX)) == ["a.json"]     # 큐를 쌓지 않는다


def test_skips_a_file_that_may_still_be_written(tmp_path):
    sub = []
    root, jd = _mk(tmp_path, sub)
    _put(root, "a.json", _job(), mtime=999.5)                        # settle_s=1.0 안쪽

    assert jd.poll(now=1000.0) is None and not sub
    assert jd.poll(now=1001.0) is not None and sub                   # 가라앉으면 집는다


def test_bad_json_goes_to_failed_with_reason(tmp_path):
    sub = []
    root, jd = _mk(tmp_path, sub)
    _put(root, "a.json", "{not json", mtime=100.0)

    dst = jd.poll(now=1000.0)

    assert not sub
    assert os.path.dirname(dst).endswith(J.FAILED)
    err = json.load(open(os.path.splitext(dst)[0] + ".err", encoding="utf-8"))
    assert "JSON" in err["error"]


def test_contract_violation_is_rejected_by_the_same_parser(tmp_path):
    """폴더 입구가 파싱을 따로 하지 않는다는 것의 확인 — n_robots 0 은 spec 이 막는다."""
    sub = []
    root, jd = _mk(tmp_path, sub)
    _put(root, "a.json", json.dumps({"run_id": "r", "n_robots": 0}), mtime=100.0)

    dst = jd.poll(now=1000.0)

    assert not sub and os.path.dirname(dst).endswith(J.FAILED)


def test_moved_files_do_not_overwrite_each_other(tmp_path):
    sub = []
    root, jd = _mk(tmp_path, sub)
    _put(root, "a.json", _job("same"), mtime=100.0)
    jd.poll(now=1000.0)
    _put(root, "b.json", _job("same"), mtime=101.0)
    jd.poll(now=1000.0)

    assert len(os.listdir(os.path.join(root, J.STARTED))) == 2
