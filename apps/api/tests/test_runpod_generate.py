from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "infra/scripts/runpod_generate.py"


@pytest.fixture
def generate_script(monkeypatch):
    spec = importlib.util.spec_from_file_location("runpod_generate", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "load_dotenv", lambda path: None)
    for name in ("REMOTE_GENERATE_TIMEOUT_SECONDS", "REMOTE_GENERATE_POLL_INTERVAL_SECONDS", "INPUT_IMAGE", "SEED"):
        monkeypatch.delenv(name, raising=False)
    return module


@pytest.mark.parametrize("option", ["--timeout-seconds", "--poll-interval-seconds"])
@pytest.mark.parametrize("value", ["0", "-1", "not-an-integer"])
def test_main_rejects_invalid_cli_timing_before_creating_job(generate_script, monkeypatch, capsys, option, value):
    def unexpected_request(*args, **kwargs):
        pytest.fail("Invalid timing must be rejected before creating a generation job")

    monkeypatch.setattr(generate_script, "request_json", unexpected_request)
    monkeypatch.setattr(
        generate_script.sys,
        "argv",
        ["runpod_generate.py", "--prompt", "A ceramic lamp", "--api-base-url", "http://unused.invalid", option, value],
    )
    with pytest.raises(SystemExit):
        generate_script.main()
    assert "positive integer" in capsys.readouterr().err


@pytest.mark.parametrize(
    "environment_name", ["REMOTE_GENERATE_TIMEOUT_SECONDS", "REMOTE_GENERATE_POLL_INTERVAL_SECONDS"]
)
@pytest.mark.parametrize("value", ["0", "-1", "not-an-integer", ""])
def test_main_rejects_invalid_environment_timing_before_creating_job(
    generate_script, monkeypatch, environment_name, value
):
    def unexpected_request(*args, **kwargs):
        pytest.fail("Invalid timing must be rejected before creating a generation job")

    monkeypatch.setattr(generate_script, "request_json", unexpected_request)
    monkeypatch.setenv(environment_name, value)
    monkeypatch.setattr(
        generate_script.sys,
        "argv",
        ["runpod_generate.py", "--prompt", "A ceramic lamp", "--api-base-url", "http://unused.invalid"],
    )
    with pytest.raises(SystemExit, match=f"{environment_name} must be a positive integer"):
        generate_script.main()


@pytest.mark.parametrize(
    ("environment", "options", "expected"),
    [
        ({}, [], (3600, 5)),
        (
            {"REMOTE_GENERATE_TIMEOUT_SECONDS": "120", "REMOTE_GENERATE_POLL_INTERVAL_SECONDS": "2"},
            [],
            (120, 2),
        ),
        (
            {"REMOTE_GENERATE_TIMEOUT_SECONDS": "invalid", "REMOTE_GENERATE_POLL_INTERVAL_SECONDS": "0"},
            ["--timeout-seconds", "1", "--poll-interval-seconds", "3"],
            (1, 3),
        ),
    ],
)
def test_timing_defaults_environment_and_cli_precedence(generate_script, monkeypatch, environment, options, expected):
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    args = generate_script.build_parser().parse_args(
        ["--prompt", "A ceramic lamp", "--api-base-url", "http://unused.invalid", *options]
    )
    _, settings = generate_script.resolve_settings(args)
    assert (settings["timeout_seconds"], settings["poll_interval_seconds"]) == expected


def test_main_creates_and_downloads_job_with_valid_timing(generate_script, monkeypatch, tmp_path):
    requests = []

    def request_json(base_url, method, path, payload=None):
        requests.append((method, path))
        return {
            "id": "job-1",
            "status": "succeeded",
            "progress_percent": 100,
            "progress_stage": "completed",
            "attempt_count": 1,
            "max_attempts": 3,
        }

    output = tmp_path / "result.png"
    monkeypatch.setattr(generate_script, "request_json", request_json)
    monkeypatch.setattr(generate_script, "request_bytes", lambda *args: ("image/png", b"test-image"))
    monkeypatch.setattr(
        generate_script.sys,
        "argv",
        [
            "runpod_generate.py",
            "--prompt", "A ceramic lamp",
            "--api-base-url", "http://unused.invalid",
            "--timeout-seconds", "10",
            "--poll-interval-seconds", "1",
            "--output", str(output),
            "--no-open",
        ],
    )
    assert generate_script.main() == 0
    assert requests == [("POST", "/v1/images"), ("GET", "/v1/images/job-1")]
    assert output.read_bytes() == b"test-image"
    assert output.with_suffix(".json").is_file()
