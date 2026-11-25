from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def slugify(text: str, max_length: int = 50) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if not normalized:
        return "image"
    return normalized[:max_length].strip("-") or "image"


def positive_seconds(value: str) -> int:
    try:
        seconds = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if seconds <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return seconds


def environment_seconds(name: str, default: int) -> int:
    try:
        return positive_seconds(os.environ.get(name, str(default)))
    except argparse.ArgumentTypeError as exc:
        raise SystemExit(f"{name} must be a positive integer") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create an image job against the remote API and download the PNG.")
    parser.add_argument("--prompt", help="Prompt for the generated image.")
    parser.add_argument("--negative-prompt", help="Negative prompt override.")
    parser.add_argument("--aspect-ratio", choices=["1:1", "16:9", "9:16", "4:5", "3:2"], help="Aspect ratio preset.")
    parser.add_argument("--mode", choices=["photoreal"], help="Generation mode.")
    parser.add_argument("--seed", type=int, help="Optional deterministic seed.")
    parser.add_argument("--input-image", help="Optional local image path for image-to-image generation.")
    parser.add_argument("--input-strength", type=float, help="Optional image-to-image strength override.")
    parser.add_argument("--api-base-url", help="Override the public API base URL.")
    parser.add_argument(
        "--auto-enhance-prompt",
        action="store_true",
        help="Enable prompt enhancement for this request.",
    )
    parser.add_argument(
        "--disable-auto-enhance-prompt",
        action="store_true",
        help="Force prompt enhancement off for this request.",
    )
    parser.add_argument("--output", help="Custom output path for the PNG.")
    parser.add_argument("--output-dir", help="Directory for generated images when --output is not provided.")
    parser.add_argument(
        "--timeout-seconds",
        type=positive_seconds,
        help="Positive seconds to wait for a terminal job state before failing.",
    )
    parser.add_argument(
        "--poll-interval-seconds", type=positive_seconds, help="Positive polling interval against the API."
    )
    parser.add_argument("--open", dest="open_result", action="store_true", help="Open the downloaded image.")
    parser.add_argument("--no-open", dest="open_result", action="store_false", help="Do not open the image.")
    parser.set_defaults(open_result=None)
    return parser


def resolve_settings(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    prompt = args.prompt or os.environ.get("PROMPT")
    if not prompt:
        raise SystemExit("PROMPT is required. Example: PROMPT='A surreal fox in a library' make remote-generate")

    auto_enhance_default = parse_bool(os.environ.get("AUTO_ENHANCE_PROMPT"), False)
    if args.auto_enhance_prompt:
        auto_enhance_prompt = True
    elif args.disable_auto_enhance_prompt:
        auto_enhance_prompt = False
    else:
        auto_enhance_prompt = auto_enhance_default

    api_base_url = (
        args.api_base_url
        or os.environ.get("REMOTE_GENERATE_API_BASE_URL")
        or os.environ.get("PUBLIC_API_BASE_URL")
        or os.environ.get("NEXT_PUBLIC_API_BASE_URL")
    )
    if not api_base_url:
        raise SystemExit("PUBLIC_API_BASE_URL or REMOTE_GENERATE_API_BASE_URL must be set in your environment or .env.")

    request_payload: dict[str, Any] = {
        "prompt": prompt,
        "negative_prompt": args.negative_prompt or os.environ.get("NEGATIVE_PROMPT", ""),
        "aspect_ratio": args.aspect_ratio or os.environ.get("ASPECT_RATIO", "1:1"),
        "mode": args.mode or os.environ.get("MODE", "photoreal"),
        "auto_enhance_prompt": auto_enhance_prompt,
    }

    seed_raw = args.seed if args.seed is not None else os.environ.get("SEED")
    if seed_raw not in {None, ""}:
        request_payload["seed"] = int(seed_raw)

    input_image_path = args.input_image or os.environ.get("INPUT_IMAGE")
    input_strength = args.input_strength if args.input_strength is not None else os.environ.get("INPUT_IMAGE_STRENGTH")
    if input_image_path:
        path = Path(input_image_path).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        payload = path.read_bytes()
        mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
        request_payload["input_image_base64"] = base64.b64encode(payload).decode("utf-8")
        request_payload["input_image_mime_type"] = mime_type
        if input_strength not in {None, ""}:
            request_payload["input_image_strength"] = float(input_strength)

    output_dir = Path(args.output_dir or os.environ.get("REMOTE_OUTPUT_DIR", "./outputs")).expanduser()
    timeout_seconds = (
        args.timeout_seconds
        if args.timeout_seconds is not None
        else environment_seconds("REMOTE_GENERATE_TIMEOUT_SECONDS", 3600)
    )
    poll_interval_seconds = (
        args.poll_interval_seconds
        if args.poll_interval_seconds is not None
        else environment_seconds("REMOTE_GENERATE_POLL_INTERVAL_SECONDS", 5)
    )
    open_default = parse_bool(os.environ.get("OPEN_GENERATED_IMAGE"), sys.platform == "darwin")
    open_result = args.open_result if args.open_result is not None else open_default

    settings = {
        "api_base_url": api_base_url.rstrip("/"),
        "output": args.output,
        "output_dir": output_dir,
        "timeout_seconds": timeout_seconds,
        "poll_interval_seconds": poll_interval_seconds,
        "open_result": open_result,
    }
    return request_payload, settings


def request_json(base_url: str, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(f"{base_url}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(detail or f"HTTP {exc.code} {method} {path}") from exc


def request_bytes(base_url: str, path: str) -> tuple[str, bytes]:
    request = urllib.request.Request(f"{base_url}{path}", method="GET")
    with urllib.request.urlopen(request, timeout=180) as response:
        return response.headers.get("Content-Type", "application/octet-stream"), response.read()


def resolve_output_path(payload: dict[str, Any], settings: dict[str, Any], metadata: dict[str, Any]) -> Path:
    if settings["output"]:
        output_path = Path(settings["output"]).expanduser()
        if not output_path.is_absolute():
            output_path = Path.cwd() / output_path
        if output_path.suffix.lower() != ".png":
            output_path = output_path.with_suffix(".png")
        return output_path

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    job_id = metadata.get("job", {}).get("id") or metadata.get("job_id", "job")
    filename = f"{timestamp}-{job_id[:8]}-{slugify(payload['prompt'])}.png"
    return Path.cwd() / settings["output_dir"] / filename


def poll_job(payload: dict[str, Any], settings: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    metadata: dict[str, Any] = {}
    job = request_json(settings["api_base_url"], "POST", "/v1/images", payload)
    job_id = job["id"]
    metadata["job_id"] = job_id
    print(f"job={job_id} created", flush=True)

    deadline = time.time() + settings["timeout_seconds"]
    last_marker: tuple[Any, ...] | None = None

    while time.time() < deadline:
        current = request_json(settings["api_base_url"], "GET", f"/v1/images/{job_id}")
        marker = (
            current.get("status"),
            current.get("progress_percent"),
            current.get("progress_stage"),
            current.get("attempt_count"),
        )
        if marker != last_marker:
            print(
                (
                    "job={id} status={status} progress={progress_percent} "
                    "stage={progress_stage} attempts={attempt_count}/{max_attempts}"
                ).format(**current),
                flush=True,
            )
            last_marker = marker

        if current.get("status") == "succeeded":
            content_type, image_bytes = request_bytes(settings["api_base_url"], f"/v1/images/{job_id}/result")
            metadata["job"] = current
            metadata["content_type"] = content_type
            metadata["image_size_bytes"] = len(image_bytes)
            return image_bytes, metadata

        if current.get("status") == "failed":
            message = current.get("error_message") or "remote generation failed"
            raise RuntimeError(message)

        time.sleep(settings["poll_interval_seconds"])

    raise TimeoutError(f"Timed out waiting for job {job_id} after {settings['timeout_seconds']} seconds")


def main() -> int:
    load_dotenv(Path.cwd() / ".env")
    parser = build_parser()
    args = parser.parse_args()
    payload, settings = resolve_settings(args)

    image_bytes, metadata = poll_job(payload, settings)
    output_path = resolve_output_path(payload, settings, metadata)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(image_bytes)

    metadata_path = output_path.with_suffix(".json")
    metadata_path.write_text(
        json.dumps(
            {
                "request": payload,
                "result": metadata,
                "saved_at": datetime.now().isoformat(),
                "output_path": str(output_path),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"saved {output_path}", flush=True)
    print(f"metadata {metadata_path}", flush=True)

    if settings["open_result"] and sys.platform == "darwin":
        subprocess.run(["open", str(output_path)], check=False)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
