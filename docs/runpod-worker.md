# RunPod Worker Deployment

## Requirements
- RunPod pod with Linux, NVIDIA GPU, and enough VRAM for `FLUX.1-Krea-dev`.
- SSH enabled.
- Network path from the pod back to your local Mac over the SSH reverse tunnel.
- S3-compatible storage configured for generated images.
- Optional checkpoint bucket in R2/S3 if you want cold model cache persistence between pod lifecycles.
- Hugging Face access accepted for `black-forest-labs/FLUX.1-Krea-dev`.

## Recommended pod shape
- GPU: choose based on the quality level you need
- Disk: 200 GB minimum for reliable FLUX bootstrap
- OS: Ubuntu-based CUDA image
- App path: `/opt/image-platform` by default
- Runtime role: worker-only

The worker now runs a single pipeline:
- `black-forest-labs/FLUX.1-Krea-dev`
- loaded through `diffusers.FluxPipeline`
- `FluxImg2ImgPipeline` is used automatically when the request includes a reference image

## Deployment flow
1. Set `RUNPOD_HOST`, `RUNPOD_USER`, `RUNPOD_SSH_KEY_PATH`, and `RUNPOD_SSH_PORT`.
2. Start the local control plane on your Mac:
   - `make local-stack-up`
3. Start the reverse tunnel:
   - `make local-worker-tunnel-start`
4. Set the worker env in `.env`:
   - `DATABASE_URL`
   - `REDIS_URL`
   - `PUBLIC_API_BASE_URL`
   - `S3_*`
   - `HF_TOKEN`
   - optional `CHECKPOINT_S3_*`
5. Run:
   - `make deploy-worker`
6. Validate the remote service:
   - `supervisorctl status image-platform-worker`

## Notes
- The deploy script is RunPod-aware: it supports custom SSH ports and uses `/opt/image-platform` by default.
- The runtime process is supervised by `supervisord`.
- The model is downloaded with `huggingface_hub.snapshot_download`.
- If `CHECKPOINT_S3_*` is configured, the deploy script hydrates the local `MODEL_CACHE_DIR` from object storage first and uploads it again after a successful refresh.
- `HF_TOKEN` is mandatory for the real worker because the model is gated.
- The worker uses a single public mode, `photoreal`.
- The worker keeps the FLUX pipeline resident across jobs while the process stays alive.
- CPU offload is enabled by default for better compatibility on rented GPUs.
