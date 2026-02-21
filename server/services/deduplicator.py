"""
RequestDeduplicator - Prevents duplicate concurrent requests.

When multiple callers request the same resource simultaneously,
only one actual request is made and the result is shared.
"""

import asyncio
from typing import Any, Awaitable, Callable, TypeVar

from loguru import logger

T = TypeVar("T")


class RequestDeduplicator:
    """
    Deduplicates concurrent async requests.

    When multiple coroutines request the same key simultaneously,
    only one actual request is made. All callers await the same result.

    Usage:
        dedup = RequestDeduplicator()

        async def fetch_data(url: str):
            return await dedup.dedupe(
                key=url,
                request_fn=lambda: http_client.get(url)
            )
    """

    def __init__(self, debug: bool = False):
        self._in_flight: dict[str, asyncio.Task[Any]] = {}
        self._lock = asyncio.Lock()
        self._debug = debug
        self._stats = DeduplicatorStats()

    async def dedupe(
        self,
        key: str,
        request_fn: Callable[[], Awaitable[T]],
    ) -> T:
        """
        Execute request with deduplication.

        If a request with the same key is already in flight,
        wait for and return its result instead of making a new request.

        Args:
            key: Unique identifier for this request
            request_fn: Async function to execute if no duplicate exists

        Returns:
            Result from request_fn (either fresh or from in-flight request)
        """
        async with self._lock:
            if key in self._in_flight:
                # Request already in flight, wait for it
                self._stats.deduplicated += 1
                self._log(f"DEDUPE: Waiting for in-flight request: {key[:50]}...")
                task = self._in_flight[key]
            else:
                # Create new request
                self._stats.total += 1
                self._log(f"NEW: Starting request: {key[:50]}...")
                task = asyncio.create_task(self._execute_and_cleanup(key, request_fn))
                self._in_flight[key] = task

        try:
            return await task
        except Exception:
            # Re-raise the exception to all waiters
            raise

    async def _execute_and_cleanup(
        self,
        key: str,
        request_fn: Callable[[], Awaitable[T]],
    ) -> T:
        """Execute request and clean up when done."""
        try:
            result = await request_fn()
            return result
        finally:
            async with self._lock:
                self._in_flight.pop(key, None)
                self._log(f"DONE: Request completed: {key[:50]}...")

    async def cancel(self, key: str) -> bool:
        """Cancel an in-flight request."""
        async with self._lock:
            if key in self._in_flight:
                task = self._in_flight.pop(key)
                task.cancel()
                self._log(f"CANCEL: Request cancelled: {key[:50]}...")
                return True
            return False

    async def cancel_all(self) -> int:
        """Cancel all in-flight requests."""
        async with self._lock:
            count = len(self._in_flight)
            for key, task in self._in_flight.items():
                task.cancel()
            self._in_flight.clear()
            if count:
                self._log(f"CANCEL_ALL: {count} requests cancelled")
            return count

    def get_in_flight_count(self) -> int:
        """Get number of in-flight requests."""
        return len(self._in_flight)

    def get_in_flight_keys(self) -> list[str]:
        """Get keys of all in-flight requests."""
        return list(self._in_flight.keys())

    def get_stats(self) -> "DeduplicatorStats":
        """Get deduplication statistics."""
        self._stats.in_flight = len(self._in_flight)
        return self._stats

    def _log(self, message: str) -> None:
        """Log debug message if debug mode is enabled."""
        if self._debug:
            logger.debug(f"[Deduplicator] {message}")


class DeduplicatorStats:
    """Statistics for request deduplication."""

    def __init__(self):
        self.total: int = 0  # Total unique requests made
        self.deduplicated: int = 0  # Requests that were deduplicated
        self.in_flight: int = 0  # Current in-flight requests

    @property
    def dedup_rate(self) -> float:
        """Calculate deduplication rate."""
        total = self.total + self.deduplicated
        if total == 0:
            return 0.0
        return self.deduplicated / total

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_requests": self.total,
            "deduplicated": self.deduplicated,
            "in_flight": self.in_flight,
            "dedup_rate": f"{self.dedup_rate:.2%}",
        }
