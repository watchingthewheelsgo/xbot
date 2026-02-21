"""
Service layer exceptions.
"""


class ServiceError(Exception):
    """Base exception for service layer errors."""

    def __init__(self, message: str, service_id: str | None = None):
        self.service_id = service_id
        super().__init__(message)


class CacheError(ServiceError):
    """Cache operation failed."""

    pass


class CircuitOpenError(ServiceError):
    """Circuit breaker is open, request blocked."""

    def __init__(self, service_id: str, reset_after_seconds: float):
        self.reset_after_seconds = reset_after_seconds
        super().__init__(
            f"Circuit breaker open for service '{service_id}', "
            f"retry after {reset_after_seconds:.1f}s",
            service_id=service_id,
        )


class RequestTimeoutError(ServiceError):
    """Request timed out."""

    def __init__(self, service_id: str, timeout: float):
        self.timeout = timeout
        super().__init__(
            f"Request to service '{service_id}' timed out after {timeout}s",
            service_id=service_id,
        )


class RateLimitError(ServiceError):
    """Rate limit exceeded."""

    def __init__(self, service_id: str, retry_after: float | None = None):
        self.retry_after = retry_after
        msg = f"Rate limit exceeded for service '{service_id}'"
        if retry_after:
            msg += f", retry after {retry_after}s"
        super().__init__(msg, service_id=service_id)


class ServiceUnavailableError(ServiceError):
    """Service is temporarily unavailable."""

    pass
