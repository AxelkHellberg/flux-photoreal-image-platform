from __future__ import annotations

import redis


class ImageJobQueue:
    def __init__(self, redis_url: str, queue_name: str):
        self.queue_name = queue_name
        self.client = redis.Redis.from_url(redis_url, decode_responses=True)

    def enqueue(self, job_id: str) -> None:
        self.client.lpush(self.queue_name, job_id)

    def blocking_pop(self, timeout: int) -> str | None:
        result = self.client.brpop(self.queue_name, timeout=timeout)
        if result is None:
            return None
        _, job_id = result
        return str(job_id)

    def ping(self) -> bool:
        return bool(self.client.ping())

    def close(self) -> None:
        self.client.close()
