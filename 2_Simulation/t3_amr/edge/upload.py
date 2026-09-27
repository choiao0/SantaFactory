"""mp4 → MinIO(EC2) → **객체 키**. 클라이언트는 주입 가능(테스트). `minio` 는 여기서만, 늦게 import 한다.

돌려주는 값은 URL 이 아니라 객체 키 `<run_id>/<파일명>` 이다 (-233). 버킷 이름은 붙이지 않는다 —
버킷 `verify-videos` 는 양쪽 설정(MINIO_BUCKET)이고, BE 서명기(4_Web VerifyVideoPresigner, -89)가
URL 아닌 값을 통째로 키로 읽기 때문이다. 버킷은 비공개라 키만 알아서는 못 열고, 백엔드가 조회 시점에
읽기 전용 계정으로 서명 URL 을 만든다(3_FMS/contracts/SIM_VERIFY_CONTRACT.md §7).
버킷과 계정은 EC2 에서 미리 만든다(deploy/README.md §3). 이 코드가 쓰는 `sim-runner` 계정은 PutObject 만 있어서
bucket_exists(HEAD) 도 stat 도 403 이다 — 그래서 여기서는 올리기만 하고 아무것도 조회하지 않는다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

CONTENT_TYPE = "video/mp4"
CONNECT_TIMEOUT_S = 10.0
READ_TIMEOUT_S = 120.0                  # 100 MB 급 mp4 도 tailnet 에서 이 안에 올라간다
RETRIES = 2
# minio-py 는 멀티파트를 병렬(기본 3)로 올린다 — 풀이 1 이면 파트마다 "Connection pool is full, discarding
# connection" 경고를 찍는다 (2026-09-16 verify_4, -237).
POOL_SIZE = 8


@dataclass(frozen=True)
class Uploader:
    endpoint: str
    access_key: str
    secret_key: str
    bucket: str
    secure: bool = False

    @staticmethod
    def from_environ(env: dict | None = None) -> Uploader | None:
        """MINIO_ENDPOINT · MINIO_ACCESS_KEY · MINIO_SECRET_KEY 가 다 있어야 만든다. 없으면 None(업로드 없이 돈다)."""
        e = os.environ if env is None else env
        endpoint, access, secret = e.get("MINIO_ENDPOINT"), e.get("MINIO_ACCESS_KEY"), e.get("MINIO_SECRET_KEY")
        if not (endpoint and access and secret):
            return None
        return Uploader(endpoint, access, secret, e.get("MINIO_BUCKET") or "verify-videos",
                        (e.get("MINIO_SECURE") or "0") not in ("0", "", "false", "no"))

    def object_name(self, run_id: str, path: str) -> str:
        return f"{run_id}/{os.path.basename(path)}"

    def object_key(self, run_id: str, path: str) -> str:
        """Runner/VideoUrl 에 싣는 값 = 버킷 없는 S3 객체 키. 백엔드는 자기 설정의 버킷과 이 키로 서명한다(-89)."""
        return self.object_name(run_id, path)

    def client(self) -> Any:
        """타임아웃을 박은 MinIO 클라이언트 — 끝없이 매달리면 런이 STOPPING 에 갇힌다.
        컨테이너에만 있는 의존성이라 늦게 import 한다."""
        import urllib3
        from minio import Minio
        http = urllib3.PoolManager(maxsize=POOL_SIZE,
                                   timeout=urllib3.Timeout(connect=CONNECT_TIMEOUT_S, read=READ_TIMEOUT_S),
                                   retries=urllib3.Retry(total=RETRIES, backoff_factor=1.0))
        return Minio(self.endpoint, access_key=self.access_key, secret_key=self.secret_key, secure=self.secure,
                     http_client=http)

    def upload(self, path: str, run_id: str, client: Any = None) -> str:
        """올리고 객체 키를 돌려준다. 실패는 예외로 — 호출자가 LAST_ERROR 로 바꾼다.
        버킷 존재 확인·생성은 하지 않는다(쓰기 전용 계정은 HEAD 가 403).
        버킷이 없으면 fput 이 NoSuchBucket 으로 죽는다 — 버킷은 운영이 미리 만든다."""
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            raise FileNotFoundError(f"video missing or empty: {path}")
        c = client if client is not None else self.client()
        c.fput_object(self.bucket, self.object_name(run_id, path), path, content_type=CONTENT_TYPE)
        return self.object_key(run_id, path)
