# Troubleshooting

## Job is stuck in `queued`
- Check Redis connectivity between the API and the worker.
- Verify the worker is running and can claim jobs.
- Confirm `IMAGE_GENERATOR_BACKEND=flux` in the real worker environment.
- On the first real FLUX boot, `queued` can be expected for several minutes while the model cache hydrates and the pipeline loads.

## Job keeps returning to `queued`
- The worker is likely losing heartbeats or failing before completion.
- Inspect worker logs and reaper logs.
- Check that the SSH reverse tunnel is still up:
  - `make local-worker-tunnel-status`
- Increase `HEARTBEAT_TIMEOUT_SECONDS` only if the environment is genuinely slow.

## Job is stuck in `running` at the same percentage
- Check whether `last_progress_at` is moving. A worker can keep sending heartbeats even when generation is hung.
- Tune `PROGRESS_TIMEOUT_SECONDS` instead of only increasing the heartbeat timeout.
- Inspect worker logs for VRAM pressure or Hugging Face download stalls.

## Result download fails
- Confirm the object exists in MinIO/S3/R2 for the `storage_key` stored in the job.
- Verify the API has the correct S3 credentials and endpoint.

## Remote worker cannot start FLUX
- Validate `HF_TOKEN` and confirm the account has access to `black-forest-labs/FLUX.1-Krea-dev`.
- Check that `MODEL_CACHE_DIR` is writable.
- If you use R2/S3 for model cache, verify `CHECKPOINT_S3_*` points to the correct bucket and prefix.
- Confirm CUDA, PyTorch, diffusers, transformers, and accelerate compatibility on the pod image.

## Worker fails with CUDA OOM
- Lower the requested resolution by switching aspect ratio or reducing dimensions in the shared config.
- Keep `FLUX_ENABLE_MODEL_CPU_OFFLOAD=true`.
- Use a larger GPU if you need more margin for photoreal generations.
