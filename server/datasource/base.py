"""
Base data source interface.
"""

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from pydantic import BaseModel

from server.services.client import ServiceClient

T = TypeVar("T", bound=BaseModel)


class BaseDataSource(ABC, Generic[T]):
    """
    Abstract base class for all data sources.

    All data sources should:
    - Use ServiceClient for HTTP requests (with caching, circuit breaker, etc.)
    - Return Pydantic models
    - Handle errors gracefully
    """

    def __init__(self, client: ServiceClient | None = None):
        from server.services.client import get_service_client

        self.client = client or get_service_client()

    @property
    @abstractmethod
    def service_id(self) -> str:
        """Unique identifier for this data source."""
        ...

    @abstractmethod
    async def fetch(self) -> list[T]:
        """Fetch data from the source."""
        ...

    @abstractmethod
    def is_configured(self) -> bool:
        """Check if the data source is properly configured."""
        ...
