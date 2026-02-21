"""
CacheManager - Async-compatible cache with TTL and stale-while-revalidate support.

Features:
- Memory-based L1 cache with LRU eviction
- TTL (Time To Live) for cache entries
- Stale-while-revalidate pattern for better availability
- Thread-safe async operations
"""

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Generic, TypeVar

from loguru import logger

T = TypeVar("T")


@dataclass
class CacheEntry(Generic[T]):
    """A single cache entry with metadata."""

    data: T
    timestamp: datetime
    ttl: timedelta
    stale_until: datetime

    def is_expired(self) -> bool:
        """Check if entry is past its TTL."""
        return datetime.now() > self.timestamp + self.ttl

    def is_stale(self) -> bool:
        """Check if entry is stale but still usable."""
        now = datetime.now()
        return now > self.timestamp + self.ttl and now <= self.stale_until

    def is_valid(self) -> bool:
        """Check if entry is still valid (not past stale period)."""
        return datetime.now() <= self.stale_until


@dataclass
class CacheResult(Generic[T]):
    """Result from cache lookup."""

    data: T
    from_cache: str  # 'memory' | 'stale'
    is_stale: bool


class CacheManager:
    """
    Async-compatible cache manager with TTL and stale-while-revalidate.

    Usage:
        cache = CacheManager(prefix="myservice_", max_size=100)

        # Try to get from cache
        result = await cache.get("my_key")
        if result:
            return result.data

        # Fetch fresh data and cache it
        data = await fetch_data()
        await cache.set("my_key", data, ttl=timedelta(minutes=5))
    """

    def __init__(
        self,
        prefix: str = "xbot_",
        max_size: int = 100,
        default_ttl: timedelta = timedelta(minutes=5),
        stale_while_revalidate: bool = True,
        debug: bool = False,
    ):
        self._memory: dict[str, CacheEntry[Any]] = {}
        self._prefix = prefix
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._stale_while_revalidate = stale_while_revalidate
        self._debug = debug
        self._lock = asyncio.Lock()
        self._stats = CacheStats()

    def generate_key(self, url: str, params: dict[str, Any] | None = None) -> str:
        """Generate a cache key from URL and params."""
        if params:
            sorted_params = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
            full_key = f"{url}?{sorted_params}"
        else:
            full_key = url

        # Hash long keys
        if len(full_key) > 200:
            hash_val = hashlib.md5(full_key.encode()).hexdigest()[:16]
            return f"{self._prefix}{hash_val}"

        return f"{self._prefix}{full_key}"

    async def get(self, key: str) -> CacheResult[Any] | None:
        """
        Get value from cache.

        Returns CacheResult if found and valid, None otherwise.
        """
        async with self._lock:
            if key not in self._memory:
                self._stats.misses += 1
                self._log(f"MISS: {key[:50]}...")
                return None

            entry = self._memory[key]

            if not entry.is_valid():
                # Entry is completely expired
                del self._memory[key]
                self._stats.misses += 1
                self._log(f"EXPIRED: {key[:50]}...")
                return None

            is_stale = entry.is_stale()

            if is_stale:
                self._stats.stale_hits += 1
                self._log(f"STALE HIT: {key[:50]}...")
            else:
                self._stats.hits += 1
                self._log(f"HIT: {key[:50]}...")

            return CacheResult(
                data=entry.data,
                from_cache="memory",
                is_stale=is_stale,
            )

    async def set(
        self,
        key: str,
        data: Any,
        ttl: timedelta | None = None,
        stale_while_revalidate: bool | None = None,
    ) -> None:
        """
        Set value in cache.

        Args:
            key: Cache key
            data: Data to cache
            ttl: Time to live (uses default if not specified)
            stale_while_revalidate: Allow stale data (uses default if not specified)
        """
        ttl = ttl or self._default_ttl
        use_stale = (
            stale_while_revalidate
            if stale_while_revalidate is not None
            else self._stale_while_revalidate
        )

        now = datetime.now()
        stale_until = now + ttl * 2 if use_stale else now + ttl

        entry = CacheEntry(
            data=data,
            timestamp=now,
            ttl=ttl,
            stale_until=stale_until,
        )

        async with self._lock:
            # LRU eviction if at capacity
            if len(self._memory) >= self._max_size and key not in self._memory:
                await self._evict_oldest()

            self._memory[key] = entry
            self._log(f"SET: {key[:50]}... (TTL: {ttl.total_seconds()}s)")

    async def delete(self, key: str) -> bool:
        """Delete a specific key from cache."""
        async with self._lock:
            if key in self._memory:
                del self._memory[key]
                self._log(f"DELETE: {key[:50]}...")
                return True
            return False

    async def invalidate(self, pattern: str) -> int:
        """
        Invalidate all keys matching a pattern.

        Args:
            pattern: Substring to match in keys

        Returns:
            Number of entries invalidated
        """
        async with self._lock:
            keys_to_delete = [k for k in self._memory if pattern in k]
            for key in keys_to_delete:
                del self._memory[key]

            if keys_to_delete:
                self._log(
                    f"INVALIDATE: {len(keys_to_delete)} entries matching '{pattern}'"
                )

            return len(keys_to_delete)

    async def clear(self) -> None:
        """Clear all cache entries."""
        async with self._lock:
            count = len(self._memory)
            self._memory.clear()
            self._log(f"CLEAR: {count} entries removed")

    async def cleanup_expired(self) -> int:
        """Remove all expired entries. Returns count of removed entries."""
        async with self._lock:
            expired_keys = [k for k, v in self._memory.items() if not v.is_valid()]
            for key in expired_keys:
                del self._memory[key]

            if expired_keys:
                self._log(f"CLEANUP: {len(expired_keys)} expired entries removed")

            return len(expired_keys)

    async def _evict_oldest(self) -> None:
        """Evict the oldest entry (LRU)."""
        if not self._memory:
            return

        # Find oldest by timestamp
        oldest_key = min(
            self._memory.keys(),
            key=lambda k: self._memory[k].timestamp,
        )
        del self._memory[oldest_key]
        self._stats.evictions += 1
        self._log(f"EVICT: {oldest_key[:50]}...")

    def get_stats(self) -> "CacheStats":
        """Get cache statistics."""
        self._stats.size = len(self._memory)
        self._stats.max_size = self._max_size
        return self._stats

    def _log(self, message: str) -> None:
        """Log debug message if debug mode is enabled."""
        if self._debug:
            logger.debug(f"[CacheManager] {message}")


@dataclass
class CacheStats:
    """Cache statistics."""

    hits: int = 0
    misses: int = 0
    stale_hits: int = 0
    evictions: int = 0
    size: int = 0
    max_size: int = 0

    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        total = self.hits + self.stale_hits + self.misses
        if total == 0:
            return 0.0
        return (self.hits + self.stale_hits) / total

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "stale_hits": self.stale_hits,
            "evictions": self.evictions,
            "size": self.size,
            "max_size": self.max_size,
            "hit_rate": f"{self.hit_rate:.2%}",
        }
