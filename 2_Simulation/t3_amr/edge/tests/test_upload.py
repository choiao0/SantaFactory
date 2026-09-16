"""edge.upload — 환경에서 만들기 · 객체 키 규약 · 가짜 클라이언트로 업로드(쓰기 전용 계정 전제)."""
import pytest

from edge.upload import Uploader


class FakeMinio:
    """sim-runner 계정은 PutObject 뿐이다 — HEAD·make_bucket 을 부르면 실제로는 403 이라 여기서는 곧바로 실패시킨다."""

    def __init__(self):
        self.put = []

    def bucket_exists(self, b):
        raise AssertionError("write-only credentials cannot HEAD the bucket — upload() must not call bucket_exists")

    def make_bucket(self, b):
        raise AssertionError("the bucket is created by ops (deploy/README.md §3) — upload() must not create it")

    def fput_object(self, bucket, name, path, content_type=None):
        self.put.append((bucket, name, path, content_type))


def test_from_environ_requires_the_three_keys_and_defaults_the_rest():
    assert Uploader.from_environ({}) is None
    assert Uploader.from_environ({"MINIO_ENDPOINT": "h:9002", "MINIO_ACCESS_KEY": "a"}) is None
    u = Uploader.from_environ({"MINIO_ENDPOINT": "h:9002", "MINIO_ACCESS_KEY": "a", "MINIO_SECRET_KEY": "s"})
    assert u.bucket == "verify-videos" and u.secure is False
    u2 = Uploader.from_environ({"MINIO_ENDPOINT": "h:9002", "MINIO_ACCESS_KEY": "a", "MINIO_SECRET_KEY": "s",
                                "MINIO_BUCKET": "b", "MINIO_SECURE": "1"})
    assert u2.bucket == "b" and u2.secure is True


def test_upload_puts_object_under_run_id_and_returns_the_object_key(tmp_path):
    p = tmp_path / "demo_verify_77_n3.mp4"
    p.write_bytes(b"\x00" * 8)
    u = Uploader("h:9002", "a", "s", "verify-videos")
    c = FakeMinio()

    key = u.upload(str(p), "verify_77_n3", client=c)

    assert c.put == [("verify-videos", "verify_77_n3/demo_verify_77_n3.mp4", str(p), "video/mp4")]
    assert key == "verify-videos/verify_77_n3/demo_verify_77_n3.mp4"      # URL 이 아니다 — 백엔드가 서명한다(-233)


def test_upload_rejects_missing_or_empty_file(tmp_path):
    u = Uploader("h:9002", "a", "s", "verify-videos")
    with pytest.raises(FileNotFoundError):
        u.upload(str(tmp_path / "nope.mp4"), "r", client=FakeMinio())
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    with pytest.raises(FileNotFoundError):
        u.upload(str(empty), "r", client=FakeMinio())
