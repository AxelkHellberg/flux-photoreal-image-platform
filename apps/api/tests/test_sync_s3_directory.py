from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[3] / "infra" / "scripts" / "sync_s3_directory.py"
_SPEC = importlib.util.spec_from_file_location("sync_s3_directory", _SCRIPT)
sync = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sync)


class FakeS3Client:
    """Model S3's string-prefix filtering and paginated object listings locally."""

    def __init__(self, objects: dict[str, bytes] | None = None, page_size: int = 1):
        self.objects = dict(objects or {})
        self.page_size = page_size
        self.listings: list[dict] = []
        self.uploaded: list[str] = []
        self.downloaded: list[str] = []

    def list_objects_v2(self, **kwargs):
        self.listings.append(kwargs)
        keys = sorted(key for key in self.objects if key.startswith(kwargs["Prefix"]))
        start = int(kwargs.get("ContinuationToken", "0"))
        page = keys[start : start + self.page_size]
        end = start + len(page)
        response = {
            "Contents": [{"Key": key, "Size": len(self.objects[key])} for key in page],
            "IsTruncated": end < len(keys),
        }
        if response["IsTruncated"]:
            response["NextContinuationToken"] = str(end)
        return response

    def upload_file(self, filename: str, bucket: str, key: str) -> None:
        self.uploaded.append(key)
        self.objects[key] = Path(filename).read_bytes()

    def download_file(self, bucket: str, key: str, filename: str) -> None:
        self.downloaded.append(key)
        Path(filename).write_bytes(self.objects[key])


@pytest.mark.parametrize("raw_prefix", ["cache", "/cache/", "cache/nested", "/cache/nested/"])
def test_download_excludes_sibling_prefixes_and_paginates(tmp_path, raw_prefix):
    prefix = sync.normalize_prefix(raw_prefix)
    client = FakeS3Client(
        {
            f"{prefix}/": b"",
            f"{prefix}/config.json": b"config",
            f"{prefix}/weights/model.bin": b"weights",
            f"{prefix}-backup/other.bin": b"backup",
            f"{prefix}2/other.bin": b"other",
        }
    )

    assert sync.download_directory(client, "test-bucket", prefix, tmp_path) == (2, 0)

    assert {path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*") if path.is_file()} == {
        "config.json", "weights/model.bin"
    }
    assert (tmp_path / "config.json").read_bytes() == b"config"
    assert (tmp_path / "weights/model.bin").read_bytes() == b"weights"
    assert len(client.listings) == 3
    assert [request.get("ContinuationToken") for request in client.listings] == [None, "1", "2"]
    assert sync.download_directory(client, "test-bucket", prefix, tmp_path) == (0, 2)


@pytest.mark.parametrize("raw_prefix", ["", "/", "cache", "/cache/", "cache/nested"])
def test_upload_download_round_trip_and_size_skips(tmp_path, raw_prefix):
    prefix = sync.normalize_prefix(raw_prefix)
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    (source / "weights").mkdir()
    (source / "config.json").write_bytes(b"config")
    (source / "weights" / "model.bin").write_bytes(b"weights")
    client = FakeS3Client()

    assert sync.upload_directory(client, "test-bucket", prefix, source) == (2, 0)
    assert sync.upload_directory(client, "test-bucket", prefix, source) == (0, 2)
    assert sync.download_directory(client, "test-bucket", prefix, destination) == (2, 0)

    assert (destination / "config.json").read_bytes() == b"config"
    assert (destination / "weights" / "model.bin").read_bytes() == b"weights"
    assert len(client.uploaded) == 2
    assert len(client.downloaded) == 2


def test_empty_directory_listing_needs_no_transfer(tmp_path):
    client = FakeS3Client({"cache-backup/model.bin": b"weights"})

    assert sync.download_directory(client, "test-bucket", "cache", tmp_path) == (0, 0)
    assert client.downloaded == []
    assert list(tmp_path.iterdir()) == []
