"""Cache + counters. Uses Redis when REDIS_URL is set and reachable, otherwise an in-memory fallback
(so the project also runs locally without Docker)."""

import json
import time

from . import config


class MemoryCache:
    kind = "memory"

    def __init__(self):
        self._d = {}

    def get(self, key):
        v = self._d.get(key)
        if not v:
            return None
        val, exp = v
        if exp and exp < time.time():
            self._d.pop(key, None)
            return None
        return val

    def set(self, key, val, ttl=300):
        self._d[key] = (val, time.time() + ttl if ttl else None)

    def incr(self, key, ttl=60):
        v = self.get(key) or 0
        exp = self._d[key][1] if key in self._d else time.time() + ttl
        self._d[key] = (v + 1, exp)
        return v + 1


class RedisCache:
    kind = "redis"

    def __init__(self, url):
        import redis

        self.r = redis.Redis.from_url(
            url, decode_responses=True, socket_connect_timeout=2
        )
        self.r.ping()

    def get(self, key):
        v = self.r.get(key)
        return json.loads(v) if v is not None else None

    def set(self, key, val, ttl=300):
        # ttl=0/None means "no expiry" (Redis rejects EX 0)
        self.r.set(key, json.dumps(val, default=str), ex=ttl if ttl else None)

    def incr(self, key, ttl=60):
        n = self.r.incr(key)
        if n == 1:
            self.r.expire(key, ttl)
        return n


def _make():
    if config.REDIS_URL:
        try:
            return RedisCache(config.REDIS_URL)
        except Exception as e:  # noqa
            print(f"[cache] Redis unavailable ({e}); using in-memory cache")
    return MemoryCache()


cache = _make()


def tenant_version(tenant_id: str) -> int:
    return cache.get(f"ver:{tenant_id}") or 0


def bump_version(tenant_id: str):
    """Invalidate all cached analytics for a tenant (called after upload/review/retrain)."""
    cache.set(f"ver:{tenant_id}", tenant_version(tenant_id) + 1, ttl=0)


def cached(tenant_id: str, name: str, fn, ttl=300):
    key = f"an:{tenant_id}:{tenant_version(tenant_id)}:{name}"
    hit = cache.get(key)
    if hit is not None:
        return hit
    val = fn()
    cache.set(key, val, ttl=ttl)
    return val
