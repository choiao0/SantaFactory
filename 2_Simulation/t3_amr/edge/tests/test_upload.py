"""edge.upload — 환경에서 만들기 · 객체 이름/URL 규약 · 가짜 클라이언트로 업로드."""
import pytest

from edge.upload import Uploader


class FakeMinio:
    def __init__(self, exists=True):
        self.exists, self.made, self.put = exists, [], []

    def bucket_exists(self, b):
        return self.exists

    def make_bucket(self, b):
        self.made.append(b)
        self.exists = True

    def fput_object(self, bucket, name, path, content_type=None):
        self.put.append((bucket, name, path, content_type))


def test_from_environ_requires_the_three_keys_and_defaults_the_rest():
    assert Uploader.from_environ({}) is None
    assert Uploader.from_environ({"MINIO_ENDPOINT": "h:9002", "MINIO_ACCESS_KEY": "a"}) is None
    u = Uploader.from_environ({"MINIO_ENDPOINT": "h:9002", "MINIO_ACCESS_KEY": "a", "MINIO_SECRET_KEY": "s"})
    assert u.bucket == "verify-videos" and u.public_base == "http://h:9002" and u.secure is False
    u2 = Uploader.from_environ({"MINIO_ENDPOINT": "h:9002", "MINIO_ACCESS_KEY": "a", "MINIO_SECRET_KEY": "s",
                                "MINIO_BUCKET": "b", "PUBLIC_MEDIA_BASE": "https://x/media/", "MINIO_SECURE": "1"})
    assert u2.bucket == "b" and u2.public_base == "https://x/media/" and u2.secure is True


def test_upload_puts_object_under_run_id_and_returns_public_url(tmp_path):
    p = tmp_path / "demo_verify_77_n3.mp4"
    p.write_bytes(b"\x00" * 8)
    u = Uploader("h:9002", "a", "s", "verify-videos", "https://x/media/")
    c = FakeMinio(exists=False)

    url = u.upload(str(p), "verify_77_n3", client=c)

    assert c.made == ["verify-videos"]
    assert c.put == [("verify-videos", "verify_77_n3/demo_verify_77_n3.mp4", str(p), "video/mp4")]
    assert url == "https://x/media/verify-videos/verify_77_n3/demo_verify_77_n3.mp4"


def test_upload_rejects_missing_or_empty_file(tmp_path):
    u = Uploader("h:9002", "a", "s", "verify-videos", "https://x/media")
    with pytest.raises(FileNotFoundError):
        u.upload(str(tmp_path / "nope.mp4"), "r", client=FakeMinio())
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    with pytest.raises(FileNotFoundError):
        u.upload(str(empty), "r", client=FakeMinio())
