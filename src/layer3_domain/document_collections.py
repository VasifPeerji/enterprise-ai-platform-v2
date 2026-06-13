"""
In-process document collection management for grounded RAG.

This module gives the platform a practical `upload once -> query many times`
workflow while keeping storage/indexing abstractions swappable later.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Iterable, Optional

from pydantic import BaseModel, Field

from src.database.services.document_collection_service import GroundedDocumentCollectionRepository
from src.database.session import get_async_session_maker
from src.layer1_intelligence.rag_service import (
    GatewayAnswerGenerator,
    GroundedRAGService,
    HeuristicAnswerGenerator,
    RAGResponse,
)
from src.layer3_domain.document_models import IngestedDocument
from src.layer3_domain.document_parsing import DocumentParsingService, RawDocumentAsset
from src.shared.errors import DomainError
from src.shared.logger import get_logger

logger = get_logger(__name__)
DEFAULT_GENERATION_MODE = "gateway"


class CollectionNotFoundError(DomainError):
    """Requested document collection does not exist."""

    def __init__(self, collection_id: str) -> None:
        super().__init__(
            message=f"Document collection '{collection_id}' not found",
            error_code="DOCUMENT_COLLECTION_NOT_FOUND",
            details={"collection_id": collection_id},
        )
        self.status_code = 404


class DocumentCollectionSummary(BaseModel):
    """Serializable collection metadata."""

    collection_id: str = Field(...)
    tenant_id: str = Field(...)
    domain: str = Field(...)
    generation_mode: str = Field(...)
    document_count: int = Field(..., ge=0)
    page_count: int = Field(..., ge=0)
    document_ids: list[str] = Field(default_factory=list)
    titles: list[str] = Field(default_factory=list)


@dataclass
class DocumentCollection:
    collection_id: str
    tenant_id: str
    domain: str
    generation_mode: str
    rag_service: GroundedRAGService
    documents: list[IngestedDocument] = field(default_factory=list)

    def summary(self) -> DocumentCollectionSummary:
        return DocumentCollectionSummary(
            collection_id=self.collection_id,
            tenant_id=self.tenant_id,
            domain=self.domain,
            generation_mode=self.generation_mode,
            document_count=len(self.documents),
            page_count=sum(len(document.pages) for document in self.documents),
            document_ids=[document.document_id for document in self.documents],
            titles=[document.title for document in self.documents],
        )


class DocumentCollectionService:
    """Manage persistent in-process grounded-document collections."""

    def __init__(
        self,
        *,
        parsing_service: Optional[DocumentParsingService] = None,
        rag_service_factory: Optional[callable] = None,
    ) -> None:
        self.parsing_service = parsing_service or DocumentParsingService()
        self.rag_service_factory = rag_service_factory or self._default_rag_service_factory
        self._collections: dict[str, DocumentCollection] = {}
        self._lock = RLock()
        self._json_store_dir = Path("D:/College/enterprise-ai-platform/.runtime/grounded_collections")
        self._json_store_dir.mkdir(parents=True, exist_ok=True)

    def _default_rag_service_factory(
        self,
        *,
        domain: str,
        generation_mode: str,
        top_k: int,
    ) -> GroundedRAGService:
        if generation_mode == "gateway":
            return GroundedRAGService.for_production_like_runtime(
                domain=domain,
                top_k=top_k,
                namespace=f"collection::{domain}",
                use_gateway_answer=True,
            )
        return GroundedRAGService.for_production_like_runtime(
            domain=domain,
            top_k=top_k,
            namespace=f"collection::{domain}",
            use_gateway_answer=False,
        )

    async def ingest_assets(
        self,
        *,
        collection_id: str,
        tenant_id: str,
        domain: str,
        assets: Iterable[RawDocumentAsset],
        generation_mode: str = DEFAULT_GENERATION_MODE,
        top_k: int = 6,
    ) -> DocumentCollectionSummary:
        asset_list = list(assets)
        documents = self.parsing_service.parse_many(asset_list)

        with self._lock:
            collection = self._collections.get(collection_id)
            if collection is None:
                rag_service = self._default_rag_service(
                    domain=domain,
                    generation_mode=generation_mode,
                    top_k=top_k,
                    namespace=collection_id,
                )
                collection = DocumentCollection(
                    collection_id=collection_id,
                    tenant_id=tenant_id,
                    domain=domain,
                    generation_mode=generation_mode,
                    rag_service=rag_service,
                )
                self._collections[collection_id] = collection
            else:
                if collection.tenant_id != tenant_id:
                    raise DomainError(
                        message="Collection tenant mismatch",
                        error_code="DOCUMENT_COLLECTION_TENANT_MISMATCH",
                        details={
                            "collection_id": collection_id,
                            "expected_tenant_id": collection.tenant_id,
                            "received_tenant_id": tenant_id,
                        },
                    )

        await collection.rag_service.index_documents(documents)
        collection.documents.extend(documents)
        await self._persist_collection(collection)

        logger.info(
            "document_collection_ingested",
            collection_id=collection_id,
            tenant_id=tenant_id,
            domain=domain,
            document_count=len(documents),
            total_documents=len(collection.documents),
            layer="layer3_domain",
        )
        return collection.summary()

    async def replace_assets(
        self,
        *,
        collection_id: str,
        tenant_id: str,
        domain: str,
        assets: Iterable[RawDocumentAsset],
        generation_mode: str = DEFAULT_GENERATION_MODE,
        top_k: int = 6,
    ) -> DocumentCollectionSummary:
        documents = self.parsing_service.parse_many(list(assets))
        collection = DocumentCollection(
            collection_id=collection_id,
            tenant_id=tenant_id,
            domain=domain,
            generation_mode=generation_mode,
            rag_service=self._default_rag_service(
                domain=domain,
                generation_mode=generation_mode,
                top_k=top_k,
                namespace=collection_id,
            ),
            documents=[],
        )
        await collection.rag_service.index_documents(documents)
        collection.documents = list(documents)
        with self._lock:
            self._collections[collection_id] = collection
        await self._persist_collection(collection)
        return collection.summary()

    async def answer_query(
        self,
        *,
        collection_id: str,
        query: str,
        tenant_id: str,
        domain: Optional[str] = None,
        top_k: int = 6,
        generation_mode: Optional[str] = None,
    ) -> RAGResponse:
        collection = await self._ensure_collection_loaded(collection_id)
        self._assert_tenant(collection, tenant_id)
        effective_generation_mode = generation_mode or collection.generation_mode
        self._set_answer_generation_mode(collection, effective_generation_mode)
        return await collection.rag_service.answer_query(
            query=query,
            tenant_id=tenant_id,
            domain=domain or collection.domain,
            top_k=top_k,
        )

    async def analyze_query(
        self,
        *,
        collection_id: str,
        query: str,
        tenant_id: str,
        domain: Optional[str] = None,
        top_k: int = 6,
    ) -> dict:
        collection = await self._ensure_collection_loaded(collection_id)
        self._assert_tenant(collection, tenant_id)
        # Analyze must never raise NoRelevantContextError (the UI wants to see
        # whatever retrieval produced, even below the answer gate), but it must
        # also not mutate the collection's shared service config. The previous
        # implementation overwrote the config in place, which left
        # raise_on_no_context=False wired in for every later /answer call on the
        # same collection. Pass the override per-call instead.
        response = await collection.rag_service.answer_query(
            query=query,
            tenant_id=tenant_id,
            domain=domain or collection.domain,
            top_k=top_k,
            raise_on_no_context=False,
        )
        return {
            "retrieval_count": response.retrieval_count,
            "citations": response.citations,
            "page_proofs": response.page_proofs,
            "evidence_groups": response.evidence_groups,
            "context_blocks": response.context_blocks,
        }

    def get_collection(self, collection_id: str, tenant_id: str) -> DocumentCollectionSummary:
        collection = self._get_collection(collection_id)
        self._assert_tenant(collection, tenant_id)
        return collection.summary()

    async def list_collections(self, tenant_id: str) -> list[DocumentCollectionSummary]:
        summaries: dict[str, DocumentCollectionSummary] = {}

        with self._lock:
            for collection in self._collections.values():
                if collection.tenant_id == tenant_id:
                    summaries[collection.collection_id] = collection.summary()

        for json_path in self._json_store_dir.glob("*.json"):
            try:
                payload = json.loads(json_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if payload.get("tenant_id") != tenant_id:
                continue
            collection_id = payload["collection_id"]
            if collection_id not in summaries:
                documents = [IngestedDocument.model_validate(doc) for doc in payload.get("documents", [])]
                summaries[collection_id] = DocumentCollectionSummary(
                    collection_id=collection_id,
                    tenant_id=payload["tenant_id"],
                    domain=payload["domain"],
                    generation_mode=payload["generation_mode"],
                    document_count=len(documents),
                    page_count=sum(len(doc.pages) for doc in documents),
                    document_ids=[doc.document_id for doc in documents],
                    titles=[doc.title for doc in documents],
                )

        try:
            async with get_async_session_maker()() as session:
                persisted = await GroundedDocumentCollectionRepository.list_collections(
                    session,
                    tenant_key=tenant_id,
                )
            for record in persisted:
                if record.collection_key not in summaries:
                    summaries[record.collection_key] = DocumentCollectionSummary(
                        collection_id=record.collection_key,
                        tenant_id=record.tenant_key,
                        domain=record.domain,
                        generation_mode=record.generation_mode,
                        document_count=record.document_count,
                        page_count=record.page_count,
                        document_ids=[],
                        titles=[],
                    )
        except Exception as exc:
            logger.warning(
                "grounded_collection_db_list_failed_using_local_state",
                tenant_id=tenant_id,
                error=str(exc),
                layer="layer3_domain",
            )

        return sorted(summaries.values(), key=lambda item: item.collection_id)

    async def delete_collection(self, collection_id: str, tenant_id: str) -> None:
        try:
            collection = await self._ensure_collection_loaded(collection_id)
            self._assert_tenant(collection, tenant_id)
        except CollectionNotFoundError:
            return

        with self._lock:
            self._collections.pop(collection_id, None)

        json_path = self._json_path(collection_id)
        if json_path.exists():
            json_path.unlink()

        try:
            async with get_async_session_maker()() as session:
                await GroundedDocumentCollectionRepository.delete_collection(
                    session,
                    collection_key=collection_id,
                )
        except Exception as exc:
            logger.warning(
                "grounded_collection_db_delete_failed_after_local_delete",
                collection_id=collection_id,
                error=str(exc),
                layer="layer3_domain",
            )

    def _get_collection(self, collection_id: str) -> DocumentCollection:
        with self._lock:
            collection = self._collections.get(collection_id)
        if collection is None:
            raise CollectionNotFoundError(collection_id)
        return collection

    async def _ensure_collection_loaded(self, collection_id: str) -> DocumentCollection:
        try:
            return self._get_collection(collection_id)
        except CollectionNotFoundError:
            return await self.hydrate_collection(collection_id)

    def _assert_tenant(self, collection: DocumentCollection, tenant_id: str) -> None:
        if collection.tenant_id != tenant_id:
            raise DomainError(
                message="Collection tenant mismatch",
                error_code="DOCUMENT_COLLECTION_TENANT_MISMATCH",
                details={
                    "collection_id": collection.collection_id,
                    "expected_tenant_id": collection.tenant_id,
                    "received_tenant_id": tenant_id,
                },
            )

    def _default_rag_service(
        self,
        *,
        domain: str,
        generation_mode: str,
        top_k: int,
        namespace: str,
    ) -> GroundedRAGService:
        if generation_mode == "gateway":
            return GroundedRAGService.for_production_like_runtime(
                domain=domain,
                top_k=top_k,
                namespace=namespace,
                use_gateway_answer=True,
            )
        return GroundedRAGService.for_production_like_runtime(
            domain=domain,
            top_k=top_k,
            namespace=namespace,
            use_gateway_answer=False,
        )

    def _set_answer_generation_mode(
        self,
        collection: DocumentCollection,
        generation_mode: str,
    ) -> None:
        if generation_mode == "gateway":
            if not isinstance(collection.rag_service.answer_generator, GatewayAnswerGenerator):
                collection.rag_service.answer_generator = GatewayAnswerGenerator()
            return
        if generation_mode == "heuristic":
            if not isinstance(collection.rag_service.answer_generator, HeuristicAnswerGenerator):
                collection.rag_service.answer_generator = HeuristicAnswerGenerator()
            return
        raise DomainError(
            message="Unsupported grounded answer generation mode",
            error_code="DOCUMENT_COLLECTION_GENERATION_MODE_INVALID",
            details={"generation_mode": generation_mode},
        )

    async def _persist_collection(self, collection: DocumentCollection) -> None:
        try:
            async with get_async_session_maker()() as session:
                await GroundedDocumentCollectionRepository.upsert_collection(
                    session,
                    collection_key=collection.collection_id,
                    tenant_key=collection.tenant_id,
                    domain=collection.domain,
                    generation_mode=collection.generation_mode,
                    document_count=len(collection.documents),
                    page_count=sum(len(document.pages) for document in collection.documents),
                )
                await GroundedDocumentCollectionRepository.replace_documents(
                    session,
                    collection_key=collection.collection_id,
                    tenant_key=collection.tenant_id,
                    documents=collection.documents,
                )
        except Exception as exc:
            logger.warning(
                "grounded_collection_db_persist_failed_falling_back_to_json",
                collection_id=collection.collection_id,
                error=str(exc),
                layer="layer3_domain",
            )

        payload = {
            "collection_id": collection.collection_id,
            "tenant_id": collection.tenant_id,
            "domain": collection.domain,
            "generation_mode": collection.generation_mode,
            "documents": [document.model_dump(mode="json") for document in collection.documents],
        }
        self._json_path(collection.collection_id).write_text(
            json.dumps(payload, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )

    async def hydrate_collection(self, collection_id: str) -> DocumentCollection:
        collection: Optional[DocumentCollection] = None
        documents: list[IngestedDocument] = []
        try:
            async with get_async_session_maker()() as session:
                collection_record, documents = await GroundedDocumentCollectionRepository.load_collection(
                    session,
                    collection_key=collection_id,
                )
            if collection_record is not None:
                collection = DocumentCollection(
                    collection_id=collection_record.collection_key,
                    tenant_id=collection_record.tenant_key,
                    domain=collection_record.domain,
                    generation_mode=collection_record.generation_mode,
                    rag_service=self._default_rag_service(
                        domain=collection_record.domain,
                        generation_mode=collection_record.generation_mode,
                        top_k=6,
                        namespace=collection_id,
                    ),
                    documents=documents,
                )
        except Exception as exc:
            logger.warning(
                "grounded_collection_db_hydrate_failed_trying_json_fallback",
                collection_id=collection_id,
                error=str(exc),
                layer="layer3_domain",
            )

        if collection is None:
            json_path = self._json_path(collection_id)
            if not json_path.exists():
                raise CollectionNotFoundError(collection_id)
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            documents = [IngestedDocument.model_validate(document) for document in payload["documents"]]
            collection = DocumentCollection(
                collection_id=payload["collection_id"],
                tenant_id=payload["tenant_id"],
                domain=payload["domain"],
                generation_mode=payload["generation_mode"],
                rag_service=self._default_rag_service(
                    domain=payload["domain"],
                    generation_mode=payload["generation_mode"],
                    top_k=6,
                    namespace=collection_id,
                ),
                documents=documents,
            )

        await collection.rag_service.index_documents(documents)
        with self._lock:
            self._collections[collection_id] = collection
        return collection

    def _json_path(self, collection_id: str) -> Path:
        safe_name = collection_id.replace("/", "_").replace("\\", "_")
        return self._json_store_dir / f"{safe_name}.json"


_document_collection_service: Optional[DocumentCollectionService] = None


def get_document_collection_service() -> DocumentCollectionService:
    global _document_collection_service
    if _document_collection_service is None:
        _document_collection_service = DocumentCollectionService()
    return _document_collection_service
