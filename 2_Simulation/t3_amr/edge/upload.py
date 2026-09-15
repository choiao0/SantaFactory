"""mp4 → MinIO(EC2) → 공개 URL. 클라이언트는 주입 가능(테스트). `minio` 는 여기서만, 늦게 import 한다.

URL 규약: <PUBLIC_MEDIA_BASE>/<bucket>/<run_id>/<파일명> — nginx `/media/` 가 MinIO(9002) 로 프록시한다.
버킷은 EC2 에서 미리 만들고 익명 읽기 정책을 준다(deploy/README.md). 없으면 여기서 만들되 정책은 못 건다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

CONTENT_TYPE = "video/mp4"
CONNECT_TIMEOUT_S = 10.0
READ_TIMEOUT_S = 120.0                  # 100 MB 급 mp4 도 tailnet 에서 이 안에 올라간다
RETRIES = 2


@dataclass(frozen=True)
class Uploader:
    endpoint: str
    access_key: str
    secret_key: str
    bucket: str
    public_base: str
    secure: bool = False

    @staticmethod
    def from_environ(env: dict | None = None) -> Uploader | None:
        """MINIO_ENDPOINT · MINIO_ACCESS_KEY · MINIO_SECRET_KEY 가 다 있어야 만든다. 없으면 None(업로드 없이 돈다)."""
        e = os.environ if env is None else env
        endpoint, access, secret = e.get("MINIO_ENDPOINT"), e.get("MINIO_ACCESS_KEY"), e.get("MINIO_SECRET_KEY")
        if not (endpoint and access and secret):
            return None
        return Uploader(endpoint, access, secret, e.get("MINIO_BUCKET") or "verify-videos",
                        e.get("PUBLIC_MEDIA_BASE") or f"http://{endpoint}",
                        (e.get("MINIO_SECURE") or "0") not in ("0", "", "false", "no"))

    def object_name(self, run_id: str, path: str) -> str:
        return f"{run_id}/{os.path.basename(path)}"

    def url(self, run_id: str, path: str) -> str:
        return f"{self.public_base.rstrip('/')}/{self.bucket}/{self.object_name(run_id, path)}"

    def client(self) -> Any:
        """타임아웃을 박은 MinIO 클라이언트 — 끝없이 매달리면 런이 STOPPING 에 갇힌다.
        컨테이너에만 있는 의존성이라 늦게 import 한다."""
        import urllib3
        from minio import Minio
        http = urllib3.PoolManager(timeout=urllib3.Timeout(connect=CONNECT_TIMEOUT_S, read=READ_TIMEOUT_S),
                                   retries=urllib3.Retry(total=RETRIES, backoff_factor=1.0))
        return Minio(self.endpoint, access_key=self.access_key, secret_key=self.secret_key, secure=self.secure,
                     http_client=http)

    def upload(self, path: str, run_id: str, client: Any = None) -> str:
        """올리고 공개 URL 을 돌려준다. 실패는 예외로 — 호출자가 LAST_ERROR 로 바꾼다."""
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            raise FileNotFoundError(f"video missing or empty: {path}")
        c = client if client is not None else self.client()
        if not c.bucket_exists(self.bucket):
            c.make_bucket(self.bucket)
        c.fput_object(self.bucket, self.object_name(run_id, path), path, content_type=CONTENT_TYPE)
        return self.url(run_id, path)
