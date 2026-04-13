SHELL := /bin/zsh

.PHONY: install install-python install-web dev api worker reaper test lint fmt compose-up compose-down migrate smoke remote-generate deploy-worker local-stack-up local-stack-down local-worker-tunnel-start local-worker-tunnel-stop local-worker-tunnel-status deploy-worker-local

install: install-python install-web

install-python:
	uv sync --all-packages --all-groups

install-web:
	pnpm install

dev:
	docker compose up --build

api:
	uv run --package image-platform-api uvicorn image_platform_api.main:app --reload --host 0.0.0.0 --port 8000

worker:
	uv run --package image-platform-worker python -m image_platform_worker.main

reaper:
	uv run --package image-platform-api python -m image_platform_api.reaper

migrate:
	uv run --package image-platform-api alembic -c apps/api/alembic.ini upgrade head

test:
	uv run --all-groups pytest

lint:
	uv run --all-groups ruff check .
	pnpm --filter @image-platform/web lint

fmt:
	uv run --all-groups ruff format .

compose-up:
	docker compose up --build -d

compose-down:
	docker compose down -v

local-stack-up:
	docker compose -f docker-compose.local.yml up --build -d

local-stack-down:
	docker compose -f docker-compose.local.yml down

smoke:
	uv run --package image-platform-api python infra/scripts/smoke_test.py

remote-generate:
	uv run python infra/scripts/runpod_generate.py

deploy-worker:
	bash infra/scripts/deploy-worker.sh

local-worker-tunnel-start:
	bash infra/scripts/local_worker_tunnel.sh start

local-worker-tunnel-stop:
	bash infra/scripts/local_worker_tunnel.sh stop

local-worker-tunnel-status:
	bash infra/scripts/local_worker_tunnel.sh status

deploy-worker-local:
	bash infra/scripts/deploy-worker-local.sh
