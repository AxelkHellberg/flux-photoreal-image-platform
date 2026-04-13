# Architecture

## Components
- `apps/api`: FastAPI REST service and reaper process.
- `apps/worker`: Redis-driven worker with heartbeat leases and a single FLUX generator.
- `apps/web`: Next.js App Router frontend.
- `packages/shared/python`: shared settings, models, queueing, storage, and generation adapters.
- `packages/shared/typescript`: shared client/types for the frontend.
- intended to serve as a backend/control plane for web or mobile creative clients.

## Runtime modes
- Local full stack: Docker Compose with Postgres, Redis, MinIO, API, stub worker, reaper, and web.
- Local control plane: Docker Compose with Postgres, Redis, API, reaper, and web, plus a remote RunPod worker connected by SSH reverse tunnel.
- Remote GPU mode: RunPod worker-only pod with S3-compatible storage and optional cold model cache bucket.

## Job flow
1. API creates a row in Postgres.
2. API pushes the job id into Redis.
3. Remote worker claims the job with a lease token.
4. Worker runs `FluxPipeline` or `FluxImg2ImgPipeline` for `black-forest-labs/FLUX.1-Krea-dev`.
5. Worker uploads the PNG to S3/R2.
6. API serves metadata and the result bytes.

## Recovery model
- Jobs start in `queued`.
- A worker claims a job by atomically moving it to `running`, incrementing `attempt_count`, and assigning a `lease_token`.
- Progress and heartbeats are only accepted when the lease token matches.
- `heartbeat_at` proves the worker process is alive.
- `last_progress_at` proves the job is still making forward progress.
- The reaper requeues jobs that lose heartbeat or stop progressing while attempts remain, or marks them `failed` once exhausted.
