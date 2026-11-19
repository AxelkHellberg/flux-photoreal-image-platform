from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
from botocore.exceptions import ClientError
from image_platform_shared.config import Settings
from image_platform_shared.storage import S3CompatibleStorageBackend


def storage_with_client(client: Mock) -> S3CompatibleStorageBackend:
    with patch("image_platform_shared.storage.boto3.client", return_value=client):
        return S3CompatibleStorageBackend(Settings(s3_bucket="test-images"))


def bucket_error(code: str, operation: str = "HeadBucket") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "Storage unavailable"}}, operation)


def test_ready_bucket_is_not_created_again():
    client = Mock()

    storage_with_client(client).ensure_ready()

    client.head_bucket.assert_called_once_with(Bucket="test-images")
    client.create_bucket.assert_not_called()


@pytest.mark.parametrize("code", ["404", "NoSuchBucket", "NotFound"])
def test_missing_bucket_is_created(code):
    client = Mock()
    client.head_bucket.side_effect = bucket_error(code)

    storage_with_client(client).ensure_ready()

    client.head_bucket.assert_called_once_with(Bucket="test-images")
    client.create_bucket.assert_called_once_with(Bucket="test-images")


@pytest.mark.parametrize("code", ["400", "403", "AccessDenied", "InvalidAccessKeyId", "500", "SlowDown"])
def test_head_bucket_errors_are_preserved_without_creating_bucket(code):
    client = Mock()
    error = bucket_error(code)
    client.head_bucket.side_effect = error

    with pytest.raises(ClientError) as raised:
        storage_with_client(client).ensure_ready()

    assert raised.value is error
    client.create_bucket.assert_not_called()


def test_bucket_creation_error_is_propagated():
    client = Mock()
    client.head_bucket.side_effect = bucket_error("404")
    error = bucket_error("AccessDenied", "CreateBucket")
    client.create_bucket.side_effect = error

    with pytest.raises(ClientError) as raised:
        storage_with_client(client).ensure_ready()

    assert raised.value is error
    client.create_bucket.assert_called_once_with(Bucket="test-images")
