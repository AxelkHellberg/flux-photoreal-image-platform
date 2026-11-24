from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

import boto3
from botocore.client import BaseClient
from botocore.exceptions import ClientError

from image_platform_shared.config import Settings


class StorageObjectNotFoundError(FileNotFoundError):
    """The requested object is absent from the storage backend."""


class StorageBackend(ABC):
    bucket_name: str | None

    @abstractmethod
    def ensure_ready(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def put_bytes(self, key: str, payload: bytes, content_type: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_bytes(self, key: str) -> bytes:
        raise NotImplementedError


class S3CompatibleStorageBackend(StorageBackend):
    def __init__(self, settings: Settings):
        self.bucket_name = settings.s3_bucket
        self.client: BaseClient = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            use_ssl=settings.s3_use_ssl,
        )

    def ensure_ready(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket_name)
        except ClientError:
            self.client.create_bucket(Bucket=self.bucket_name)

    def put_bytes(self, key: str, payload: bytes, content_type: str) -> None:
        self.client.put_object(
            Bucket=self.bucket_name,
            Key=key,
            Body=payload,
            ContentType=content_type,
        )

    def get_bytes(self, key: str) -> bytes:
        try:
            response = self.client.get_object(Bucket=self.bucket_name, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "NotFound", "404"}:
                raise StorageObjectNotFoundError(key) from exc
            raise
        return response["Body"].read()


class LocalFilesystemStorageBackend(StorageBackend):
    def __init__(self, root: str):
        self.root = Path(root)
        self.bucket_name = None

    def ensure_ready(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def put_bytes(self, key: str, payload: bytes, content_type: str) -> None:
        destination = self.root / key
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)

    def get_bytes(self, key: str) -> bytes:
        try:
            return (self.root / key).read_bytes()
        except FileNotFoundError as exc:
            raise StorageObjectNotFoundError(key) from exc


def create_storage_backend(settings: Settings) -> StorageBackend:
    if settings.storage_backend == "local":
        return LocalFilesystemStorageBackend(settings.local_storage_root)
    return S3CompatibleStorageBackend(settings)
