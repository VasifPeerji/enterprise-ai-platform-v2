"""
Persistent grounded document collection models.
"""

from typing import Optional

from sqlmodel import Field, SQLModel

from src.database.base import BaseDBModel


class GroundedDocumentCollectionBase(SQLModel):
    """Base fields for persisted grounded collections."""

    collection_key: str = Field(
        ...,
        min_length=1,
        max_length=255,
        index=True,
        unique=True,
        description="Stable external collection identifier",
    )
    tenant_key: str = Field(
        ...,
        min_length=1,
        max_length=255,
        index=True,
        description="Tenant isolation key used by the grounded collection service",
    )
    domain: str = Field(
        default="general",
        max_length=255,
        description="Domain or subdomain label",
        index=True,
    )
    generation_mode: str = Field(
        default="heuristic",
        max_length=32,
        description="heuristic|gateway",
    )
    document_count: int = Field(default=0, ge=0)
    page_count: int = Field(default=0, ge=0)
    meta_json: Optional[str] = Field(
        default=None,
        alias="metadata",
        description="Additional metadata (JSON string)",
    )


class GroundedDocumentCollection(BaseDBModel, GroundedDocumentCollectionBase, table=True):
    __tablename__ = "grounded_document_collections"


class StoredGroundedDocumentBase(SQLModel):
    """Base fields for persisted normalized documents."""

    collection_key: str = Field(
        ...,
        foreign_key="grounded_document_collections.collection_key",
        index=True,
        description="Parent collection key",
    )
    tenant_key: str = Field(
        ...,
        min_length=1,
        max_length=255,
        index=True,
        description="Tenant isolation key",
    )
    document_key: str = Field(
        ...,
        min_length=1,
        max_length=255,
        index=True,
        description="Stable external document identifier",
    )
    title: str = Field(..., max_length=500)
    source_uri: str = Field(..., max_length=1024)
    source_type: str = Field(default="pdf", max_length=64)
    language: str = Field(default="en", max_length=32)
    page_count: int = Field(default=0, ge=0)
    content_json: str = Field(
        ...,
        description="Serialized IngestedDocument payload",
    )
    meta_json: Optional[str] = Field(
        default=None,
        alias="metadata",
        description="Additional metadata (JSON string)",
    )


class StoredGroundedDocument(BaseDBModel, StoredGroundedDocumentBase, table=True):
    __tablename__ = "stored_grounded_documents"
