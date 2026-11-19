from __future__ import annotations

import argparse
import os
from pathlib import Path

import boto3
from botocore.client import BaseClient


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def build_client(
    endpoint_url: str | None,
    region: str,
    access_key_id: str,
    secret_access_key: str,
    use_ssl: bool,
) -> BaseClient:
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        region_name=region,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        use_ssl=use_ssl,
    )


def normalize_prefix(prefix: str) -> str:
    return prefix.strip("/").rstrip("/")


def iter_local_files(root: Path) -> list[Path]:
    return [path for path in root.rglob("*") if path.is_file()]


def list_remote_sizes(client: BaseClient, bucket: str, prefix: str) -> dict[str, int]:
    sizes: dict[str, int] = {}
    continuation_token: str | None = None
    # Directory sync must exclude sibling names such as "models-backup".
    directory_prefix = f"{prefix}/" if prefix else ""
    while True:
        kwargs = {"Bucket": bucket, "Prefix": directory_prefix}
        if continuation_token:
            kwargs["ContinuationToken"] = continuation_token
        response = client.list_objects_v2(**kwargs)
        for entry in response.get("Contents", []):
            sizes[str(entry["Key"])] = int(entry["Size"])
        if not response.get("IsTruncated"):
            return sizes
        continuation_token = response.get("NextContinuationToken")


def upload_directory(client: BaseClient, bucket: str, prefix: str, local_root: Path) -> tuple[int, int]:
    remote_sizes = list_remote_sizes(client, bucket, prefix)
    uploaded = 0
    skipped = 0
    for file_path in iter_local_files(local_root):
        relative_path = file_path.relative_to(local_root).as_posix()
        key = "/".join(segment for segment in [prefix, relative_path] if segment)
        local_size = file_path.stat().st_size
        if remote_sizes.get(key) == local_size:
            skipped += 1
            continue
        client.upload_file(str(file_path), bucket, key)
        uploaded += 1
    return uploaded, skipped


def download_directory(client: BaseClient, bucket: str, prefix: str, local_root: Path) -> tuple[int, int]:
    remote_sizes = list_remote_sizes(client, bucket, prefix)
    downloaded = 0
    skipped = 0
    prefix_with_slash = f"{prefix}/" if prefix else ""
    for key, remote_size in remote_sizes.items():
        relative_path = (
            key[len(prefix_with_slash) :] if prefix_with_slash and key.startswith(prefix_with_slash) else key
        )
        if not relative_path:
            continue
        destination = local_root / relative_path
        if destination.exists() and destination.stat().st_size == remote_size:
            skipped += 1
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        client.download_file(bucket, key, str(destination))
        downloaded += 1
    return downloaded, skipped


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sync a local directory to or from an S3-compatible bucket.",
    )
    parser.add_argument("direction", choices=["upload", "download"])
    parser.add_argument(
        "--local-root",
        default=os.environ.get("SYNC_LOCAL_ROOT"),
        help="Directory to upload or hydrate.",
    )
    parser.add_argument("--bucket", default=os.environ.get("SYNC_S3_BUCKET"), help="Target bucket.")
    parser.add_argument("--prefix", default=os.environ.get("SYNC_S3_PREFIX", ""), help="Key prefix inside the bucket.")
    parser.add_argument("--endpoint-url", default=os.environ.get("SYNC_S3_ENDPOINT_URL"), help="S3 endpoint URL.")
    parser.add_argument("--region", default=os.environ.get("SYNC_S3_REGION", "auto"), help="S3 region.")
    parser.add_argument("--access-key-id", default=os.environ.get("SYNC_S3_ACCESS_KEY_ID"), help="S3 access key id.")
    parser.add_argument(
        "--secret-access-key",
        default=os.environ.get("SYNC_S3_SECRET_ACCESS_KEY"),
        help="S3 secret access key.",
    )
    parser.add_argument("--use-ssl", default=os.environ.get("SYNC_S3_USE_SSL", "false"), help="Whether to use SSL.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not args.local_root or not args.bucket or not args.access_key_id or not args.secret_access_key:
        raise SystemExit("local-root, bucket, access-key-id, and secret-access-key are required")

    local_root = Path(args.local_root).expanduser().resolve()
    local_root.mkdir(parents=True, exist_ok=True)
    prefix = normalize_prefix(args.prefix or "")
    client = build_client(
        endpoint_url=args.endpoint_url,
        region=args.region,
        access_key_id=args.access_key_id,
        secret_access_key=args.secret_access_key,
        use_ssl=parse_bool(args.use_ssl),
    )

    if args.direction == "upload":
        uploaded, skipped = upload_directory(client, args.bucket, prefix, local_root)
        print(f"uploaded={uploaded} skipped={skipped}")
    else:
        downloaded, skipped = download_directory(client, args.bucket, prefix, local_root)
        print(f"downloaded={downloaded} skipped={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
