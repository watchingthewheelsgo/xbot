"""
Service layer infrastructure - resilience patterns for external API calls.

Provides:
- CacheManager: Two-tier caching with TTL and stale-while-revalidate
- CircuitBreaker: Prevents cascading failures
- RequestDeduplicator: Prevents duplicate concurrent requests
- ServiceClient: Unified client combining all patterns
"""

from server.services.errors import (
    ServiceError,
    CacheError,
    CircuitOpenError,
    RequestTimeoutError,
)
from server.services.cache import CacheManager, CacheEntry, CacheResult
from server.services.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerRegistry,
    CircuitState,
)
from server.services.deduplicator import RequestDeduplicator
from server.services.client import ServiceClient, RequestResult

__all__ = [
    # Errors
    "ServiceError",
    "CacheError",
    "CircuitOpenError",
    "RequestTimeoutError",
    # Cache
    "CacheManager",
    "CacheEntry",
    "CacheResult",
    # Circuit Breaker
    "CircuitBreaker",
    "CircuitBreakerRegistry",
    "CircuitState",
    # Deduplicator
    "RequestDeduplicator",
    # Client
    "ServiceClient",
    "RequestResult",
]
