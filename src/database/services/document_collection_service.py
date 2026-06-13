"""
Persistence service for grounded document collections.
"""

from __future__ import annotations

import json
from typing import Iterable

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from src.database.models import GroundedDocumentCollection, StoredGroundedDocument
from src.layer3_domain.document_models import IngestedDocument
from src.shared.logger import get_logger

logger = get_logger(__name__)


class GroundedDocumentCollectionRepository:
    """CRUD + rebuild support for grounded document collections."""

    @staticmethod
    async def upsert_collection(
        session: AsyncSession,
        *,
        collection_key: str,
        tenant_key: str,
        domain: str,
        generation_mode: str,
        document_count: int,
        page_count: int,
    ) -> GroundedDocumentCollection:
        result = await session.execute(
            select(GroundedDocumentCollection).where(
                GroundedDocumentCollection.collection_key == collection_key,
                GroundedDocumentCollection.deleted_at.is_(None),
            )
        )
        record = result.scalar_one_or_none()
        if record is None:
            record = GroundedDocumentCollection(
                collection_key=collection_key,
                tenant_key=tenant_key,
                domain=domain,
                generation_mode=generation_mode,
                document_count=document_count,
                page_count=page_count,
            )
        else:
            record.tenant_key = tenant_key
            record.domain = domain
            record.generation_mode = generation_mode
            record.document_count = document_count
            record.page_count = page_count

        session.add(record)
        await session.commit()
        await session.refresh(record)
        return record

    @staticmethod
    async def replace_documents(
        session: AsyncSession,
        *,
        collection_key: str,
        tenant_key: str,
        documents: Iterable[IngestedDocument],
    ) -> None:
        existing = await session.execute(
            select(StoredGroundedDocument).where(
                StoredGroundedDocument.collection_key == collection_key,
                StoredGroundedDocument.deleted_at.is_(None),
            )
        )
        for row in existing.scalars().all():
            await session.delete(row)
        await session.flush()

        for document in documents:
            session.add(
                StoredGroundedDocument(
                    collection_key=collection_key,
                    tenant_key=tenant_key,
                    document_key=document.document_id,
                    title=document.title,
                    source_uri=document.source_uri,
                    source_type=document.source_type,
                    language=document.language,
                    page_count=len(document.pages),
                    content_json=document.model_dump_json(),
                )
            )

        await session.commit()
        logger.info(
            "grounded_collection_documents_replaced",
            collection_key=collection_key,
            tenant_key=tenant_key,
        )

    @staticmethod
    async def load_collection(
        session: AsyncSession,
        *,
        collection_key: str,
        tenant_key: str | None = None,
    ) -> tuple[GroundedDocumentCollection | None, list[IngestedDocument]]:
        conditions = [
            GroundedDocumentCollection.collection_key == collection_key,
            GroundedDocumentCollection.deleted_at.is_(None),
        ]
        if tenant_key is not None:
            # Scope the load to the requesting tenant so a cross-tenant id can
            # never hydrate another tenant's documents.
            conditions.append(GroundedDocumentCollection.tenant_key == tenant_key)
        collection_result = await session.execute(
            select(GroundedDocumentCollection).where(*conditions)
        )
        collection = collection_result.scalar_one_or_none()
        if collection is None:
            return None, []

        docs_result = await session.execute(
            select(StoredGroundedDocument).where(
                StoredGroundedDocument.collection_key == collection_key,
                StoredGroundedDocument.deleted_at.is_(None),
            )
        )
        stored_documents = docs_result.scalars().all()
        documents = [
            IngestedDocument.model_validate_json(record.content_json)
            for record in stored_documents
        ]
        return collection, documents

    @staticmethod
    async def list_collections(
        session: AsyncSession,
        *,
        tenant_key: str,
    ) -> list[GroundedDocumentCollection]:
        result = await session.execute(
            select(GroundedDocumentCollection).where(
                GroundedDocumentCollection.tenant_key == tenant_key,
                GroundedDocumentCollection.deleted_at.is_(None),
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def delete_collection(
        session: AsyncSession,
        *,
        collection_key: str,
    ) -> None:
        collection_result = await session.execute(
            select(GroundedDocumentCollection).where(
                GroundedDocumentCollection.collection_key == collection_key,
                GroundedDocumentCollection.deleted_at.is_(None),
            )
        )
        collection = collection_result.scalar_one_or_none()
        if collection is None:
            return

        docs_result = await session.execute(
            select(StoredGroundedDocument).where(
                StoredGroundedDocument.collection_key == collection_key,
                StoredGroundedDocument.deleted_at.is_(None),
            )
        )
        for row in docs_result.scalars().all():
            await session.delete(row)

        await session.delete(collection)
        await session.commit()
