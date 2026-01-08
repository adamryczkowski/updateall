"""Base repository interface.

This module defines the abstract base class for all repositories,
providing a consistent interface for CRUD operations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Generic, TypeVar

if TYPE_CHECKING:
    from uuid import UUID

    import duckdb

T = TypeVar("T")


class BaseRepository(ABC, Generic[T]):
    """Abstract base class for repositories.

    Provides a consistent interface for CRUD operations on database entities.
    Each concrete repository implements these methods for a specific entity type.

    Type Parameters:
        T: The entity type this repository manages.

    Attributes:
        _conn: The DuckDB connection used for database operations.
    """

    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        """Initialize the repository.

        Args:
            connection: DuckDB connection for database operations.
        """
        self._conn = connection

    @abstractmethod
    def create(self, entity: T) -> T:
        """Create a new entity in the database.

        Args:
            entity: Entity to create.

        Returns:
            Created entity with any generated fields populated
            (e.g., created_at timestamp).
        """
        ...

    @abstractmethod
    def get_by_id(self, entity_id: UUID) -> T | None:
        """Retrieve an entity by its unique identifier.

        Args:
            entity_id: The unique identifier of the entity.

        Returns:
            The entity if found, None otherwise.
        """
        ...

    @abstractmethod
    def update(self, entity: T) -> T:
        """Update an existing entity in the database.

        Args:
            entity: Entity with updated values. The entity's ID
                   must match an existing record.

        Returns:
            The updated entity.

        Raises:
            ValueError: If the entity does not exist.
        """
        ...

    @abstractmethod
    def delete(self, entity_id: UUID) -> bool:
        """Delete an entity by its unique identifier.

        Args:
            entity_id: The unique identifier of the entity to delete.

        Returns:
            True if the entity was deleted, False if it was not found.
        """
        ...
