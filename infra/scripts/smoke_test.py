from __future__ import annotations

import os
import sys
import time

import httpx

API_BASE_URL = os.environ.get("PUBLIC_API_BASE_URL", "http://localhost:18000")
TIMEOUT_SECONDS = int(os.environ.get("SMOKE_TEST_TIMEOUT_SECONDS", "90"))
PROMPT = (
    "A cinematic still life of a brass camera on a terrazzo table, "
    "warm morning light, high detail."
)


def main() -> int:
    client = httpx.Client(base_url=API_BASE_URL, timeout=30.0)
    response = client.post(
        "/v1/images",
        json={
            "prompt": PROMPT,
            "negative_prompt": "blurry, distorted, extra limbs",
            "aspect_ratio": "1:1",
            "mode": "photoreal",
            "seed": 424242,
            "auto_enhance_prompt": False,
        },
    )
    response.raise_for_status()
    job = response.json()
    job_id = job["id"]
    deadline = time.time() + TIMEOUT_SECONDS

    while time.time() < deadline:
        job_response = client.get(f"/v1/images/{job_id}")
        job_response.raise_for_status()
        current = job_response.json()
        status_line = (
            f"job={job_id} status={current['status']} "
            f"progress={current['progress_percent']} stage={current['progress_stage']}"
        )
        print(status_line)
        if current["status"] == "succeeded":
            image_response = client.get(f"/v1/images/{job_id}/result")
            image_response.raise_for_status()
            if image_response.headers.get("content-type") != "image/png":
                raise RuntimeError("Smoke test downloaded an unexpected content type")
            print(f"Smoke test passed for job {job_id}")
            return 0
        if current["status"] == "failed":
            raise RuntimeError(f"Smoke test job failed: {current['error_message']}")
        time.sleep(3)

    raise TimeoutError(f"Smoke test timed out after {TIMEOUT_SECONDS} seconds")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"Smoke test failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
