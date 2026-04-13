from __future__ import annotations

import os
import time

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_TESTS") != "1",
    reason="RUN_INTEGRATION_TESTS=1 is required to hit the live stack.",
)


def test_live_stack_roundtrip():
    base_url = os.environ.get("PUBLIC_API_BASE_URL", "http://localhost:8000")
    client = httpx.Client(base_url=base_url, timeout=30.0)
    response = client.post(
        "/v1/images",
        json={
            "prompt": "A geometric fruit bowl on a limestone slab",
            "negative_prompt": "artifact",
            "aspect_ratio": "1:1",
            "mode": "photoreal",
            "seed": 13579,
            "auto_enhance_prompt": False,
        },
    )
    response.raise_for_status()
    job_id = response.json()["id"]

    deadline = time.time() + 90
    while time.time() < deadline:
        current = client.get(f"/v1/images/{job_id}").json()
        if current["status"] == "succeeded":
            image = client.get(f"/v1/images/{job_id}/result")
            image.raise_for_status()
            assert image.headers["content-type"] == "image/png"
            return
        if current["status"] == "failed":
            raise AssertionError(current["error_message"])
        time.sleep(3)

    raise AssertionError("Timed out waiting for stack integration test")
