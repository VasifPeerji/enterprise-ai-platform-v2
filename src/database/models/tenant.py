"""
📁 File: src/database/models/tenant.py
Layer: Database (Infrastructure)
Purpose: Tenant model for multi-tenancy
Depends on: src/database/base
Used by: User, Conversation, all tenant-scoped models

Tenant represents an organization/client using the platform.
All data is isolated by tenant_id.
"""

from typing import Optional

from sqlmodel import Field, SQLModel

from src.database.base import BaseDBModel


class TenantBase(SQLModel):
    """Base fields for Tenant."""
    
    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Tenant/organization name",
        index=True,
    )
    slug: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="URL-friendly identifier",
        unique=True,
        index=True,
        regex=r"^[a-z0-9-]+$",
    )
    is_active: bool = Field(
        default=True,
        description="Whether tenant is active",
    )
    
    # Billing & Limits
    monthly_budget_usd: Optional[float] = Field(
        default=None,
        description="Monthly AI cost budget in USD",
    )
    monthly_request_limit: Optional[int] = Field(
        default=None,
        description="Monthly request limit",
    )
    
    # Configuration
    allowed_models: Optional[str] = Field(
        default=None,
        description="Comma-separated list of allowed model IDs (null = all)",
    )
    default_model_id: Optional[str] = Field(
        default=None,
        description="Default model for this tenant",
    )
    enable_ollama: bool = Field(
        default=True,
        description="Allow Ollama models for cost savings",
    )
    
    # Contact
    contact_email: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Primary contact email",
    )
    contact_name: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Primary contact name",
    )
    
    # Metadata
    meta_json: Optional[str] = Field(
        default=None,
        alias="metadata",
        description="Additional metadata (JSON string)",
    )


class Tenant(BaseDBModel, TenantBase, table=True):
    """
    Tenant database model.
    
    Represents an organization/client using the platform.
    All other data is scoped to a tenant.
    """
    
    __tablename__ = "tenants"


class TenantCreate(TenantBase):
    """Schema for creating a new tenant."""
    pass


class TenantUpdate(SQLModel):
    """Schema for updating a tenant."""
    
    name: Optional[str] = None
    is_active: Optional[bool] = None
    monthly_budget_usd: Optional[float] = None
    monthly_request_limit: Optional[int] = None
    allowed_models: Optional[str] = None
    default_model_id: Optional[str] = None
    enable_ollama: Optional[bool] = None
    contact_email: Optional[str] = None
    contact_name: Optional[str] = None
    meta_json: Optional[str] = Field(default=None, alias="metadata")


class TenantRead(TenantBase):
    """Schema for reading a tenant."""
    
    id: str  # UUID as string for API
    created_at: str  # ISO format
    updated_at: str  # ISO format
