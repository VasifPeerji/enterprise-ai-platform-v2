"""
📁 File: src/database/models/user.py
Layer: Database (Infrastructure)
Purpose: User model with authentication and RBAC
Depends on: src/database/base, src/database/models/tenant
Used by: Authentication, authorization, conversation tracking

User represents an individual who uses the platform.
Users belong to tenants and have roles.
"""

from enum import Enum
from typing import Optional
from uuid import UUID

from sqlmodel import Field, Relationship, SQLModel

from src.database.base import BaseDBModel


class UserRole(str, Enum):
    """User roles for RBAC."""
    
    ADMIN = "admin"  # Full access to tenant
    AGENT = "agent"  # Can use all features
    USER = "user"  # Standard user
    VIEWER = "viewer"  # Read-only access


class UserBase(SQLModel):
    """Base fields for User."""
    
    tenant_id: UUID = Field(
        ...,
        foreign_key="tenants.id",
        description="Tenant this user belongs to",
        index=True,
    )
    
    email: str = Field(
        ...,
        min_length=3,
        max_length=255,
        description="User email (unique per tenant)",
        index=True,
    )
    full_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="User's full name",
    )
    
    role: UserRole = Field(
        default=UserRole.USER,
        description="User role for RBAC",
        index=True,
    )
    
    is_active: bool = Field(
        default=True,
        description="Whether user account is active",
    )
    
    # Authentication
    hashed_password: str = Field(
        ...,
        description="Bcrypt hashed password",
    )
    
    # Preferences
    preferred_model_id: Optional[str] = Field(
        default=None,
        description="User's preferred model",
    )
    preferred_temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="User's preferred temperature",
    )
    
    # Usage Tracking
    total_requests: int = Field(
        default=0,
        description="Total number of requests made",
    )
    total_cost_usd: float = Field(
        default=0.0,
        description="Total cost incurred (USD)",
    )
    
    # Metadata
    meta_json: Optional[str] = Field(
        default=None,
        alias="metadata",
        description="Additional metadata (JSON string)",
    )


class User(BaseDBModel, UserBase, table=True):
    """
    User database model.
    
    Represents an individual user of the platform.
    Users are scoped to tenants and have roles.
    """
    
    __tablename__ = "users"
    
    # Ensure email is unique per tenant
    __table_args__ = (
        {"schema": None},
    )


class UserCreate(SQLModel):
    """Schema for creating a new user."""
    
    tenant_id: UUID
    email: str
    full_name: str
    password: str  # Plain password (will be hashed)
    role: UserRole = UserRole.USER
    preferred_model_id: Optional[str] = None


class UserUpdate(SQLModel):
    """Schema for updating a user."""
    
    full_name: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    preferred_model_id: Optional[str] = None
    preferred_temperature: Optional[float] = None
    meta_json: Optional[str] = Field(default=None, alias="metadata")


class UserRead(SQLModel):
    """Schema for reading a user (excludes password)."""
    
    id: str  # UUID as string
    tenant_id: str  # UUID as string
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    preferred_model_id: Optional[str]
    preferred_temperature: float
    total_requests: int
    total_cost_usd: float
    created_at: str  # ISO format
    updated_at: str  # ISO format
