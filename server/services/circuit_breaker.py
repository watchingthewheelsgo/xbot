"""
CircuitBreaker - Prevents cascading failures by stopping requests to failing services.

States:
- CLOSED: Normal operation, requests pass through
- OPEN: Service is failing, requests are blocked
- HALF_OPEN: Testing if service has recovered

Transitions:
- CLOSED → OPEN: When failure_threshold is reached
- OPEN → HALF_OPEN: After reset_timeout expires
- HALF_OPEN → CLOSED: On successful request
- HALF_OPEN → OPEN: On failed request
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from loguru import logger


class CircuitState(str, Enum):
    """Circuit breaker states."""

    CLOSED = "CLOSED"  # Normal operation
    OPEN = "OPEN"  # Blocking requests
    HALF_OPEN = "HALF_OPEN"  # Testing recovery


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""

    failure_threshold: int = 3  # Failures before opening
    reset_timeout: timedelta = timedelta(seconds=30)  # Time before half-open
    half_open_max_requests: int = 1  # Requests allowed in half-open state
    success_threshold: int = 1  # Successes needed to close from half-open


class CircuitBreaker:
    """
    Circuit breaker implementation for a single service.

    Usage:
        cb = CircuitBreaker("my_service")

        if not cb.can_request():
            raise CircuitOpenError(...)

        try:
            result = await make_request()
            cb.record_success()
            return result
        except Exception:
            cb.record_failure()
            raise
    """

    def __init__(
        self,
        service_id: str,
        config: CircuitBreakerConfig | None = None,
    ):
        self.service_id = service_id
        self.config = config or CircuitBreakerConfig()

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: datetime | None = None
        self._opened_at: datetime | None = None
        self._half_open_requests = 0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        """Get current state, checking for automatic transitions."""
        if self._state == CircuitState.OPEN:
            # Check if we should transition to half-open
            if (
                self._opened_at
                and datetime.now() >= self._opened_at + self.config.reset_timeout
            ):
                self._state = CircuitState.HALF_OPEN
                self._half_open_requests = 0
                self._success_count = 0
                logger.info(
                    f"Circuit breaker '{self.service_id}' transitioned to HALF_OPEN"
                )
        return self._state

    def can_request(self) -> bool:
        """Check if a request is allowed."""
        current_state = self.state

        if current_state == CircuitState.CLOSED:
            return True

        if current_state == CircuitState.OPEN:
            return False

        # HALF_OPEN: Allow limited requests
        if current_state == CircuitState.HALF_OPEN:
            return self._half_open_requests < self.config.half_open_max_requests

        return False

    def record_success(self) -> None:
        """Record a successful request."""
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.config.success_threshold:
                self._close()
        elif self._state == CircuitState.CLOSED:
            # Reset failure count on success
            self._failure_count = 0

    def record_failure(self) -> None:
        """Record a failed request."""
        self._failure_count += 1
        self._last_failure_time = datetime.now()

        if self._state == CircuitState.HALF_OPEN:
            # Any failure in half-open reopens the circuit
            self._open()
        elif self._state == CircuitState.CLOSED:
            if self._failure_count >= self.config.failure_threshold:
                self._open()

    def _open(self) -> None:
        """Transition to OPEN state."""
        self._state = CircuitState.OPEN
        self._opened_at = datetime.now()
        logger.warning(
            f"Circuit breaker '{self.service_id}' OPENED after {self._failure_count} failures"
        )

    def _close(self) -> None:
        """Transition to CLOSED state."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._opened_at = None
        self._half_open_requests = 0
        logger.info(f"Circuit breaker '{self.service_id}' CLOSED (recovered)")

    def reset(self) -> None:
        """Manually reset the circuit breaker."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._opened_at = None
        self._half_open_requests = 0
        self._last_failure_time = None
        logger.info(f"Circuit breaker '{self.service_id}' manually reset")

    def get_time_until_reset(self) -> float | None:
        """Get seconds until circuit transitions to half-open."""
        if self._state != CircuitState.OPEN or not self._opened_at:
            return None

        reset_at = self._opened_at + self.config.reset_timeout
        remaining = (reset_at - datetime.now()).total_seconds()
        return max(0, remaining)

    def get_status(self) -> dict[str, Any]:
        """Get current status as dictionary."""
        return {
            "service_id": self.service_id,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "last_failure": (
                self._last_failure_time.isoformat() if self._last_failure_time else None
            ),
            "opened_at": (self._opened_at.isoformat() if self._opened_at else None),
            "time_until_reset": self.get_time_until_reset(),
        }


class CircuitBreakerRegistry:
    """
    Registry for managing multiple circuit breakers.

    Usage:
        registry = CircuitBreakerRegistry()
        cb = registry.get("my_service")
    """

    def __init__(self, default_config: CircuitBreakerConfig | None = None):
        self._breakers: dict[str, CircuitBreaker] = {}
        self._default_config = default_config or CircuitBreakerConfig()
        self._lock = asyncio.Lock()

    def get(
        self,
        service_id: str,
        config: CircuitBreakerConfig | None = None,
    ) -> CircuitBreaker:
        """Get or create a circuit breaker for a service."""
        if service_id not in self._breakers:
            self._breakers[service_id] = CircuitBreaker(
                service_id,
                config or self._default_config,
            )
        return self._breakers[service_id]

    def get_all_status(self) -> dict[str, dict[str, Any]]:
        """Get status of all circuit breakers."""
        return {
            service_id: cb.get_status() for service_id, cb in self._breakers.items()
        }

    def reset_all(self) -> None:
        """Reset all circuit breakers."""
        for cb in self._breakers.values():
            cb.reset()
        logger.info(f"Reset {len(self._breakers)} circuit breakers")

    def reset(self, service_id: str) -> bool:
        """Reset a specific circuit breaker."""
        if service_id in self._breakers:
            self._breakers[service_id].reset()
            return True
        return False

    def get_open_circuits(self) -> list[str]:
        """Get list of services with open circuits."""
        return [
            service_id
            for service_id, cb in self._breakers.items()
            if cb.state == CircuitState.OPEN
        ]
