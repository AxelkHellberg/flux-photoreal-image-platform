from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from image_platform_shared.config import Settings
from image_platform_shared.storage import (
    LocalFilesystemStorageBackend,
    S3CompatibleStorageBackend,
    StorageObjectNotFoundError,
)


def test_missing_local_object_has_storage_not_found_error(tmp_path):
    storage = LocalFilesystemStorageBackend(str(tmp_path))

    with pytest.raises(StorageObjectNotFoundError):
        storage.get_bytes("images/missing/result.png")


def test_local_read_permission_errors_are_preserved(monkeypatch, tmp_path):
    error = PermissionError("Storage directory is unreadable")

    def read_bytes(path):
        raise error

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    storage = LocalFilesystemStorageBackend(str(tmp_path))

    with pytest.raises(PermissionError) as caught:
        storage.get_bytes("images/result.png")

    assert caught.value is error


def s3_storage(monkeypatch, get_object):
    client = SimpleNamespace(get_object=get_object)
    monkeypatch.setattr("image_platform_shared.storage.boto3.client", lambda *args, **kwargs: client)
    return S3CompatibleStorageBackend(Settings(s3_bucket="results"))


@pytest.mark.parametrize("code", ["NoSuchKey", "NotFound", "404"])
def test_missing_s3_object_has_storage_not_found_error(monkeypatch, code):
    error = ClientError({"Error": {"Code": code}}, "GetObject")

    def get_object(**kwargs):
        assert kwargs == {"Bucket": "results", "Key": "images/missing/result.png"}
        raise error

    storage = s3_storage(monkeypatch, get_object)

    with pytest.raises(StorageObjectNotFoundError) as caught:
        storage.get_bytes("images/missing/result.png")

    assert caught.value.__cause__ is error


@pytest.mark.parametrize("code", ["AccessDenied", "NoSuchBucket", "SlowDown"])
def test_other_s3_errors_are_preserved(monkeypatch, code):
    error = ClientError({"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": 404}}, "GetObject")

    def get_object(**kwargs):
        raise error

    storage = s3_storage(monkeypatch, get_object)

    with pytest.raises(ClientError) as caught:
        storage.get_bytes("images/result.png")

    assert caught.value is error


def test_s3_connection_errors_are_preserved(monkeypatch):
    error = EndpointConnectionError(endpoint_url="https://storage.invalid")

    def get_object(**kwargs):
        raise error

    storage = s3_storage(monkeypatch, get_object)

    with pytest.raises(EndpointConnectionError) as caught:
        storage.get_bytes("images/result.png")

    assert caught.value is error


def test_s3_object_bytes_are_returned(monkeypatch):
    storage = s3_storage(monkeypatch, lambda **kwargs: {"Body": BytesIO(b"png-bytes")})

    assert storage.get_bytes("images/result.png") == b"png-bytes"
