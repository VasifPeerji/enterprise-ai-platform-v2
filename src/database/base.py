"""
📁 File: src/database/base.py
Layer: Database (Infrastructure)
Purpose: Base model with common fields for all tables
Depends on: sqlmodel
Used by: All database models

Provides:
- Common timestamp fields (created_at, updated_at)
- UUID primary keys
- Soft delete support
"""

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


class TimestampMixin(SQLModel):
    """Mixin for created_at and updated_at timestamps."""
    
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        nullable=False,
        description="Timestamp when record was created",
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        nullable=False,
        description="Timestamp when record was last updated",
        sa_column_kwargs={"onupdate": datetime.utcnow},
    )


class SoftDeleteMixin(SQLModel):
    """Mixin for soft delete support."""
    
    deleted_at: Optional[datetime] = Field(
        default=None,
        nullable=True,
        description="Timestamp when record was soft deleted",
    )
    
    @property
    def is_deleted(self) -> bool:
        """Check if record is soft deleted."""
        return self.deleted_at is not None
    
    def soft_delete(self) -> None:
        """Mark record as deleted."""
        self.deleted_at = datetime.utcnow()
    
    def restore(self) -> None:
        """Restore soft deleted record."""
        self.deleted_at = None


class BaseDBModel(TimestampMixin, SoftDeleteMixin):
    """
    Base model for all database tables.
    
    Provides:
    - UUID primary key
    - created_at, updated_at timestamps
    - Soft delete support
    """
    
    id: UUID = Field(
        default_factory=uuid4,
        primary_key=True,
        nullable=False,
        description="Unique identifier (UUID)",
    )
