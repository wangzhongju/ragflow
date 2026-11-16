"""Immutable assets and run artifacts in the environment's object storage."""

from typing import Protocol

from datafactory.core.settings import Settings


class ObjectStore(Protocol):
    def put_object(self, key: str, data: bytes, mime: str) -> str: ...

    def get_object(self, key: str) -> tuple[bytes, str]: ...

    def put_asset(self, asset_id: str, data: bytes, mime: str) -> str: ...

    def get_asset(self, asset_id: str) -> tuple[bytes, str]: ...


class MemoryObjectStore:
    """Bytes kept in the process, keyed by asset id."""

    def __init__(self) -> None:
        self._objects: dict[str, tuple[bytes, str]] = {}

    def put_asset(self, asset_id: str, data: bytes, mime: str) -> str:
        """Store ``data`` unless the same asset id is already present. Returns the URI."""
        return self.put_object(_key(asset_id), data, mime)

    def get_asset(self, asset_id: str) -> tuple[bytes, str]:
        """The stored bytes and content type."""
        return self.get_object(_key(asset_id))

    def put_object(self, key: str, data: bytes, mime: str) -> str:
        existing = self._objects.setdefault(key, (data, mime))
        if existing != (data, mime):
            raise ValueError("Immutable object already exists with different content.")
        return f"memory://{key}"

    def get_object(self, key: str) -> tuple[bytes, str]:
        from datafactory.core.errors import NotFound

        if key not in self._objects:
            raise NotFound(f"Object {key} is not stored.")
        return self._objects[key]


class MinioObjectStore:
    """Assets in the environment's own bucket. The bucket name is guarded at startup."""

    def __init__(self, settings: Settings) -> None:
        from minio import Minio

        self._bucket = settings.minio_bucket
        self._client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )

    def put_asset(self, asset_id: str, data: bytes, mime: str) -> str:
        """Store ``data`` once. A repeated hash is not uploaded again."""
        return self.put_object(_key(asset_id), data, mime)

    def put_object(self, key: str, data: bytes, mime: str) -> str:
        """Keys include a content hash and never address mutable data."""
        import io

        from minio.error import S3Error

        self._ensure_bucket()
        try:
            self._client.stat_object(self._bucket, key)
        except S3Error as exc:
            if exc.code not in {"NoSuchKey", "NoSuchObject"}:
                raise
            self._client.put_object(self._bucket, key, io.BytesIO(data), len(data), content_type=mime)
        return f"s3://{self._bucket}/{key}"

    def get_asset(self, asset_id: str) -> tuple[bytes, str]:
        """Read one asset back."""
        return self.get_object(_key(asset_id))

    def get_object(self, key: str) -> tuple[bytes, str]:
        response = self._client.get_object(self._bucket, key)
        try:
            return response.read(), response.headers.get("Content-Type", "application/octet-stream")
        finally:
            response.close()
            response.release_conn()

    def _ensure_bucket(self) -> None:
        if not self._client.bucket_exists(self._bucket):
            self._client.make_bucket(self._bucket)


def _key(asset_id: str) -> str:
    digest = asset_id.removeprefix("sha256:")
    return f"assets/{digest[:2]}/{digest}"
