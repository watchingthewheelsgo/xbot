"""
ServiceClient - Unified async HTTP client with resilience patterns.

Combines:
- CacheManager for response caching
- CircuitBreaker for failure protection
- RequestDeduplicator for concurrent request optimization
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Generic, TypeVar

import httpx
from loguru import logger

from server.services.cache import CacheManager
from server.services.circuit_breaker import (
    CircuitBreakerConfig,
    CircuitBreakerRegistry,
)
from server.services.deduplicator import RequestDeduplicator
from server.services.errors import CircuitOpenError, RequestTimeoutError, ServiceError

T = TypeVar("T")


@dataclass
class RequestResult(Generic[T]):
    """Result from a service request."""

    data: T
    from_cache: str | None = None  # 'memory' | 'stale' | None
    is_stale: bool = False
    service_id: str | None = None


@dataclass
class ServiceConfig:
    """Configuration for a specific service."""

    service_id: str
    base_url: str
    timeout: float = 30.0
    cache_ttl: timedelta = timedelta(minutes=5)
    use_cache: bool = True
    use_circuit_breaker: bool = True
    use_dedup: bool = True
    headers: dict[str, str] | None = None
    circuit_breaker_config: CircuitBreakerConfig | None = None


class ServiceClient:
    """
    Unified HTTP client with caching, circuit breaker, and deduplication.

    Usage:
        client = ServiceClient()

        # Simple request
        result = await client.request(
            service_id="coingecko",
            url="https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "bitcoin", "vs_currencies": "usd"}
        )

        # With custom config
        client.register_service(ServiceConfig(
            service_id="finnhub",
            base_url="https://finnhub.io/api/v1",
            timeout=15.0,
            cache_ttl=timedelta(minutes=1),
        ))
    """

    def __init__(
        self,
        default_timeout: float = 30.0,
        default_cache_ttl: timedelta = timedelta(minutes=5),
        cache_max_size: int = 100,
        debug: bool = False,
    ):
        self._default_timeout = default_timeout
        self._default_cache_ttl = default_cache_ttl
        self._debug = debug

        # Initialize components
        self._cache = CacheManager(
            prefix="svc_",
            max_size=cache_max_size,
            default_ttl=default_cache_ttl,
            debug=debug,
        )
        self._circuit_breakers = CircuitBreakerRegistry()
        self._deduplicator = RequestDeduplicator(debug=debug)

        # Service configurations
        self._services: dict[str, ServiceConfig] = {}

        # HTTP client (lazy initialization)
        self._http_client: httpx.AsyncClient | None = None

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._default_timeout),
                follow_redirects=True,
            )
        return self._http_client

    def register_service(self, config: ServiceConfig) -> None:
        """Register a service configuration."""
        self._services[config.service_id] = config
        logger.debug(f"Registered service: {config.service_id}")

    def get_service_config(self, service_id: str) -> ServiceConfig | None:
        """Get configuration for a service."""
        return self._services.get(service_id)

    async def request(
        self,
        service_id: str,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        method: str = "GET",
        json_data: dict[str, Any] | None = None,
        use_cache: bool | None = None,
        cache_ttl: timedelta | None = None,
        timeout: float | None = None,
    ) -> RequestResult[dict[str, Any]]:
        """
        Make an HTTP request with resilience patterns.

        Args:
            service_id: Identifier for the service (for circuit breaker)
            url: Full URL to request
            params: Query parameters
            headers: Additional headers
            method: HTTP method (GET, POST, etc.)
            json_data: JSON body for POST/PUT requests
            use_cache: Override cache usage (default: True for GET)
            cache_ttl: Override cache TTL
            timeout: Override request timeout

        Returns:
            RequestResult with response data

        Raises:
            CircuitOpenError: If circuit breaker is open
            RequestTimeoutError: If request times out
            ServiceError: For other service errors
        """
        # Get service config if registered
        config = self._services.get(service_id)

        # Determine settings
        should_cache = (
            use_cache
            if use_cache is not None
            else (config.use_cache if config else method == "GET")
        )
        ttl = cache_ttl or (config.cache_ttl if config else self._default_cache_ttl)
        req_timeout = timeout or (config.timeout if config else self._default_timeout)
        use_cb = config.use_circuit_breaker if config else True
        use_dedup = config.use_dedup if config else True

        # Merge headers
        req_headers = {}
        if config and config.headers:
            req_headers.update(config.headers)
        if headers:
            req_headers.update(headers)

        # Generate cache key
        cache_key = self._cache.generate_key(url, params)

        # Check cache first (for GET requests)
        if should_cache and method == "GET":
            cached = await self._cache.get(cache_key)
            if cached and not cached.is_stale:
                return RequestResult(
                    data=cached.data,
                    from_cache=cached.from_cache,
                    is_stale=False,
                    service_id=service_id,
                )

            # If stale, we'll try to refresh but can fall back to stale data
            stale_data = cached.data if cached and cached.is_stale else None
        else:
            stale_data = None

        # Check circuit breaker
        if use_cb:
            cb = self._circuit_breakers.get(service_id)
            if not cb.can_request():
                # Circuit is open
                if stale_data is not None:
                    # Return stale data if available
                    logger.warning(
                        f"Circuit open for {service_id}, returning stale data"
                    )
                    return RequestResult(
                        data=stale_data,
                        from_cache="stale",
                        is_stale=True,
                        service_id=service_id,
                    )
                raise CircuitOpenError(
                    service_id,
                    cb.get_time_until_reset() or 0,
                )

        # Make request (with deduplication for GET)
        async def do_request() -> dict[str, Any]:
            return await self._execute_request(
                url=url,
                params=params,
                headers=req_headers,
                method=method,
                json_data=json_data,
                timeout=req_timeout,
                service_id=service_id,
            )

        try:
            if use_dedup and method == "GET":
                data = await self._deduplicator.dedupe(cache_key, do_request)
            else:
                data = await do_request()

            # Record success
            if use_cb:
                self._circuit_breakers.get(service_id).record_success()

            # Cache the response
            if should_cache and method == "GET":
                await self._cache.set(cache_key, data, ttl)

            return RequestResult(
                data=data,
                from_cache=None,
                is_stale=False,
                service_id=service_id,
            )

        except Exception as e:
            # Record failure
            if use_cb:
                self._circuit_breakers.get(service_id).record_failure()

            # Return stale data if available
            if stale_data is not None:
                logger.warning(
                    f"Request to {service_id} failed, returning stale data: {e}"
                )
                return RequestResult(
                    data=stale_data,
                    from_cache="stale",
                    is_stale=True,
                    service_id=service_id,
                )

            raise

    async def _execute_request(
        self,
        url: str,
        params: dict[str, Any] | None,
        headers: dict[str, str],
        method: str,
        json_data: dict[str, Any] | None,
        timeout: float,
        service_id: str,
    ) -> dict[str, Any]:
        """Execute the actual HTTP request."""
        client = await self._get_http_client()

        try:
            response = await client.request(
                method=method,
                url=url,
                params=params,
                headers=headers,
                json=json_data,
                timeout=timeout,
            )
            response.raise_for_status()
            return response.json()

        except httpx.TimeoutException as e:
            raise RequestTimeoutError(service_id, timeout) from e

        except httpx.HTTPStatusError as e:
            raise ServiceError(
                f"HTTP {e.response.status_code}: {e.response.text[:200]}",
                service_id=service_id,
            ) from e

        except httpx.RequestError as e:
            raise ServiceError(str(e), service_id=service_id) from e

    async def close(self) -> None:
        """Close the HTTP client and cleanup resources."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

        await self._deduplicator.cancel_all()
        logger.debug("ServiceClient closed")

    async def __aenter__(self) -> "ServiceClient":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()

    # Health and status methods

    def get_health_status(self) -> dict[str, Any]:
        """Get health status of all services."""
        return {
            "cache": self._cache.get_stats().to_dict(),
            "circuit_breakers": self._circuit_breakers.get_all_status(),
            "deduplicator": self._deduplicator.get_stats().to_dict(),
            "open_circuits": self._circuit_breakers.get_open_circuits(),
        }

    def get_circuit_status(self, service_id: str) -> dict[str, Any] | None:
        """Get circuit breaker status for a specific service."""
        cb = self._circuit_breakers._breakers.get(service_id)
        return cb.get_status() if cb else None

    async def reset_circuit(self, service_id: str) -> bool:
        """Reset circuit breaker for a service."""
        return self._circuit_breakers.reset(service_id)

    async def clear_cache(self, pattern: str | None = None) -> int:
        """Clear cache entries, optionally matching a pattern."""
        if pattern:
            return await self._cache.invalidate(pattern)
        else:
            await self._cache.clear()
            return -1  # Indicates full clear


# Global client instance
_global_client: ServiceClient | None = None


def get_service_client() -> ServiceClient:
    """Get the global service client instance."""
    global _global_client
    if _global_client is None:
        _global_client = ServiceClient()
    return _global_client


async def close_service_client() -> None:
    """Close the global service client."""
    global _global_client
    if _global_client:
        await _global_client.close()
        _global_client = None
