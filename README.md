# FLUX Photoreal Image Platform

Production-minded image generation platform built around `black-forest-labs/FLUX.1-Krea-dev`.

This project demonstrates how to take a large gated diffusion model from "it runs on a notebook" to an operational product flow:

- typed API + queue + worker architecture
- resumable GPU worker on ephemeral RunPod pods
- object storage for outputs and optional cold model cache
- local control plane suitable for solo use or private internal tooling

It is designed as a backend/control-plane project that can support web, mobile, or internal creative tooling clients.

## Why this repo is worth showing

This repository is a strong portfolio piece if you want to show AI product engineering rather than just model experimentation.

It demonstrates:

- production-style job orchestration with Postgres + Redis
- GPU worker lifecycle management on rented infrastructure
- gated-model bootstrap through Hugging Face
- storage integration through S3-compatible object storage
- a real user-facing frontend for prompt submission, history, retries, and downloads
- operational safeguards such as lease tokens, heartbeats, progress timeout recovery, and bounded retries

## Stack

- `FastAPI` for the API and reaper
- `Next.js` for the web UI
- `Postgres` for job state
- `Redis` for queueing
- `diffusers` + `FluxPipeline` / `FluxImg2ImgPipeline`
- `RunPod` for ephemeral GPU workers
- `Cloudflare R2` or any S3-compatible storage for outputs and optional cold model cache

## Architecture

### Local control plane

- `apps/api`: FastAPI service and recovery reaper
- `apps/web`: Next.js App Router frontend
- `postgres`: job state and metadata
- `redis`: queue and dispatch

### Remote GPU plane

- `apps/worker`: supervised GPU worker process running on RunPod
- one real model only: `black-forest-labs/FLUX.1-Krea-dev`
- optional model cache hydration from `CHECKPOINT_S3_*`

### Storage

- generated outputs stored in `S3_*`
- optional cold model cache stored in `CHECKPOINT_S3_*`

## Job flow

1. The API validates the request and writes a row to Postgres.
2. The API pushes the job id into Redis.
3. The GPU worker claims the job with a lease token.
4. The worker loads or reuses the FLUX pipeline and generates the image.
5. The worker uploads the PNG result to object storage.
6. The API serves metadata and downloads the result back to the client.

## Public product contract

- single mode only: `photoreal`
- supported aspect ratios:
  - `1:1`
  - `16:9`
  - `9:16`
  - `4:5`
  - `3:2`

Default dimensions:

- `1:1 -> 1024x1024`
- `16:9 -> 1152x648`
- `9:16 -> 648x1152`
- `4:5 -> 1024x1280`
- `3:2 -> 1152x768`

Default internal generation parameters:

- `num_inference_steps=30`
- `guidance_scale=4.5`
- `torch dtype=bfloat16` when supported, otherwise `float16`
- `model CPU offload=true` by default on the real worker

## Model and licensing

The real worker uses:

- [black-forest-labs/FLUX.1-Krea-dev](https://huggingface.co/black-forest-labs/FLUX.1-Krea-dev)

Important:

- access is gated on Hugging Face
- you must accept the model terms before downloading
- you need a valid `HF_TOKEN`
- the model is under a non-commercial license

This repo assumes non-commercial usage for the model runtime.

## Repository layout

- `apps/api`: FastAPI API and reaper
- `apps/worker`: GPU worker
- `apps/web`: frontend
- `packages/shared/python`: shared backend primitives
- `packages/shared/typescript`: shared frontend client and types
- `infra/scripts`: deployment and operational scripts
- `docs`: focused operational docs

## Local development

1. Copy the environment file:

```bash
cp .env.example .env
```

2. Fill the required values in `.env`:

- `POSTGRES_PASSWORD`
- `HF_TOKEN` for the real worker
- `S3_*`
- optional `CHECKPOINT_S3_*`

3. Install dependencies:

```bash
make install
```

4. Start the local full stack with stub generation:

```bash
docker compose up --build
```

That default stack exposes:

- API: `http://localhost:18000`
- Web: `http://localhost:13000`
- MinIO console: `http://localhost:9003`

If you want the local control plane without a local worker, use:

```bash
make local-stack-up
```

## Shared client checks

Run the network-free shared API client tests with Node.js 22.6 or newer:

```bash
pnpm test:shared
```

The tests stub `fetch` and do not require the API, queue, storage, or a GPU worker.

## RunPod worker workflow

1. Create a RunPod pod with:

- Linux + NVIDIA GPU
- SSH enabled
- recommended secure pod
- `200 GB` or more of container disk for reliable FLUX bootstrap

2. Set in `.env`:

- `RUNPOD_HOST`
- `RUNPOD_USER`
- `RUNPOD_SSH_KEY_PATH`
- `RUNPOD_SSH_PORT`
- `HF_TOKEN`
- `S3_*`
- optional `CHECKPOINT_S3_*`

3. Start the local control plane:

```bash
make local-stack-up
```

4. Start the reverse tunnel from your Mac to the pod:

```bash
make local-worker-tunnel-start
```

5. Deploy the worker:

```bash
make deploy-worker
```

6. Check the worker:

```bash
make local-worker-tunnel-status
ssh -i "$RUNPOD_SSH_KEY_PATH" -p "$RUNPOD_SSH_PORT" "$RUNPOD_USER@$RUNPOD_HOST" "supervisorctl status image-platform-worker"
```

## Prefetch model weights

If you want to populate a local cache directory before remote deployment:

```bash
HF_TOKEN=... \
FLUX_MODEL_ID=black-forest-labs/FLUX.1-Krea-dev \
MODEL_CACHE_DIR=./models/flux1-krea-dev \
uv run python infra/scripts/download_flux_model.py
```

## Generate one test image

With the local control plane and remote worker running:

```bash
PROMPT='Photorealistic portrait of an adult fashion model, natural skin texture, 85mm lens, editorial photography' \
NEGATIVE_PROMPT='cgi, plastic skin, deformed hands, watermark, text' \
MODE=photoreal \
ASPECT_RATIO=4:5 \
make remote-generate
```

Optional request controls:

- `NEGATIVE_PROMPT`
- `ASPECT_RATIO`
- `SEED`
- `AUTO_ENHANCE_PROMPT`
- `OUTPUT`
- `OPEN_GENERATED_IMAGE`

### Image-to-image support

You can also provide a reference image:

```bash
INPUT_IMAGE='/absolute/path/to/reference.jpg' \
INPUT_IMAGE_STRENGTH=0.6 \
PROMPT='Photorealistic editorial portrait, natural skin texture, soft daylight' \
NEGATIVE_PROMPT='cgi, plastic skin, watermark, text' \
MODE=photoreal \
ASPECT_RATIO=4:5 \
make remote-generate
```

## Tear down after use

When you are done generating:

1. stop the reverse tunnel:

```bash
make local-worker-tunnel-stop
```

2. stop or delete the RunPod pod
3. stop the local stack if you do not need it:

```bash
make local-stack-down
```

If you delete the pod, you only lose the ephemeral worker. You keep the important state as long as:

- outputs are in object storage
- optional model cache is in `CHECKPOINT_S3_*`
- the repo remains local or in GitHub

## Operational docs

- [Architecture](./docs/architecture.md)
- [RunPod Worker](./docs/runpod-worker.md)
- [Troubleshooting](./docs/troubleshooting.md)

## Status

This project is intentionally scoped as a production-minded MVP:

- solid architecture and operational flow
- suitable for portfolio and technical discussion
- not intended as a hosted SaaS or polished public consumer product in its current state
