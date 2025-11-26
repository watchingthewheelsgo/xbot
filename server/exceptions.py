"""
Custom exceptions and error handlers
"""

from fastapi import HTTPException, status


class ValidationError(HTTPException):
    """Validation error exception"""

    def __init__(self, detail: str = "Validation error"):
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail
        )


class NotFoundError(HTTPException):
    """Not found error exception"""

    def __init__(self, detail: str = "Resource not found"):
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


class ConflictError(HTTPException):
    """Conflict error exception"""

    def __init__(self, detail: str = "Resource conflict"):
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)


class UnauthorizedError(HTTPException):
    """Unauthorized error exception"""

    def __init__(self, detail: str = "Unauthorized"):
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


class TokenLimitExceeded(Exception):
    """Token limit exceeded exception"""

    def __init__(self, detail: str = "Token limit exceeded"):
        super().__init__({"detail": detail})
