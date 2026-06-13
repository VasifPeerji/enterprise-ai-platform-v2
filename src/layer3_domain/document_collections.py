"""
In-process document collection management for grounded RAG.

This module gives the platform a practical `upload once -> query many times`
workflow while keeping storage/indexing abstractions swappable later.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Iterable, Optional

from pydantic import BaseModel, Field

from src.database.services.document_collection_service import GroundedDocumentCollectionRepository
from src.database.session import get_async_session_maker
from src.layer1_intelligence import pdf_render
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
_ILLEGAL_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


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
    ) -> None:
        self.parsing_service = parsing_service or DocumentParsingService()
        self._collections: dict[str, DocumentCollection] = {}
        self._lock = RLock()
        self._json_store_dir = Path("D:/College/enterprise-ai-platform/.runtime/grounded_collections")
        self._json_store_dir.mkdir(parents=True, exist_ok=True)

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
        self._save_original_assets(collection_id, asset_list)
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
        asset_list = list(assets)
        documents = self.parsing_service.parse_many(asset_list)
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
        self._clear_original_files(collection_id)
        self._save_original_assets(collection_id, asset_list)
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
        answer_model_id: Optional[str] = None,
    ) -> RAGResponse:
        collection = await self._ensure_collection_loaded(collection_id, tenant_id)
        self._assert_tenant(collection, tenant_id)
        effective_generation_mode = generation_mode or collection.generation_mode
        self._set_answer_generation_mode(collection, effective_generation_mode)
        response = await collection.rag_service.answer_query(
            query=query,
            tenant_id=tenant_id,
            domain=domain or collection.domain,
            top_k=top_k,
            answer_model_id=answer_model_id,
        )
        self._enrich_proofs_with_original_page(collection_id, response)
        return response

    async def analyze_query(
        self,
        *,
        collection_id: str,
        query: str,
        tenant_id: str,
        domain: Optional[str] = None,
        top_k: int = 6,
    ) -> dict:
        collection = await self._ensure_collection_loaded(collection_id, tenant_id)
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
        self._enrich_proofs_with_original_page(collection_id, response)
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
            collection = await self._ensure_collection_loaded(collection_id, tenant_id)
            self._assert_tenant(collection, tenant_id)
        except CollectionNotFoundError:
            return

        with self._lock:
            self._collections.pop(collection_id, None)

        json_path = self._json_path(collection_id)
        if json_path.exists():
            json_path.unlink()

        self._clear_original_files(collection_id)

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

    async def _ensure_collection_loaded(self, collection_id: str, tenant_id: str) -> DocumentCollection:
        try:
            return self._get_collection(collection_id)
        except CollectionNotFoundError:
            return await self.hydrate_collection(collection_id, tenant_id=tenant_id)

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

    async def hydrate_collection(
        self, collection_id: str, tenant_id: str | None = None
    ) -> DocumentCollection:
        collection: Optional[DocumentCollection] = None
        documents: list[IngestedDocument] = []
        try:
            async with get_async_session_maker()() as session:
                collection_record, documents = await GroundedDocumentCollectionRepository.load_collection(
                    session,
                    collection_key=collection_id,
                    tenant_key=tenant_id,
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
            # Never load another tenant's persisted collection into the shared
            # cache: a cross-tenant request must look exactly like not-found, so
            # it can neither read nor warm another tenant's documents. When
            # tenant_id is None (direct rehydration, not a tenant-scoped
            # request) the check is skipped.
            if tenant_id is not None and payload.get("tenant_id") != tenant_id:
                raise CollectionNotFoundError(collection_id)
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

    # ------------------------------------------------------------------
    # Original-page rendering support (PyMuPDF). The raw PDF bytes are kept at
    # ingest so a page can be rendered to an image and citation snippets located
    # on it as highlight rectangles, even after a restart re-hydrates the
    # collection from the document JSON (which carries no original bytes).
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_component(name: str) -> str:
        cleaned = _ILLEGAL_FILENAME_RE.sub("_", name or "").strip()
        return cleaned or "unnamed"

    def _original_files_dir(self, collection_id: str) -> Path:
        return self._json_store_dir / "_files" / self._safe_component(collection_id)

    def _original_pdf_path(self, collection_id: str, document_id: str) -> Path:
        return self._original_files_dir(collection_id) / f"{self._safe_component(document_id)}.pdf"

    @staticmethod
    def _is_pdf_asset(asset: RawDocumentAsset) -> bool:
        if asset.source_type == "pdf":
            return True
        if (asset.mime_type or "").endswith("pdf"):
            return True
        return bool(asset.content_bytes[:5] == b"%PDF-")

    def _save_original_assets(self, collection_id: str, assets: Iterable[RawDocumentAsset]) -> None:
        pdf_assets = [a for a in assets if a.content_bytes and self._is_pdf_asset(a)]
        if not pdf_assets:
            return
        files_dir = self._original_files_dir(collection_id)
        files_dir.mkdir(parents=True, exist_ok=True)
        for asset in pdf_assets:
            try:
                self._original_pdf_path(collection_id, asset.document_id).write_bytes(asset.content_bytes)
            except Exception as exc:
                logger.warning(
                    "grounded_collection_original_pdf_save_failed",
                    collection_id=collection_id,
                    document_id=asset.document_id,
                    error=str(exc),
                    layer="layer3_domain",
                )

    def _clear_original_files(self, collection_id: str) -> None:
        shutil.rmtree(self._original_files_dir(collection_id), ignore_errors=True)

    def _load_original_pdf(self, collection_id: str, document_id: str) -> Optional[bytes]:
        path = self._original_pdf_path(collection_id, document_id)
        if not path.exists():
            return None
        try:
            return path.read_bytes()
        except Exception:
            return None

    def _enrich_proofs_with_original_page(self, collection_id: str, response: RAGResponse) -> None:
        """Attach original-page highlight rectangles to each page proof.

        For every page proof whose source PDF we still have on disk, mark that a
        rendered page image is available and locate each highlight's text on the
        page as normalized rectangles. Best-effort: any failure leaves the text
        proof untouched.
        """
        page_proofs = getattr(response, "page_proofs", None)
        if not page_proofs or not pdf_render.is_available():
            return
        bytes_by_document: dict[str, Optional[bytes]] = {}
        for proof in page_proofs:
            document_id = proof.document_id
            if document_id not in bytes_by_document:
                bytes_by_document[document_id] = self._load_original_pdf(collection_id, document_id)
            pdf_bytes = bytes_by_document[document_id]
            if not pdf_bytes:
                continue
            proof.has_page_image = True
            for highlight in proof.highlights:
                if highlight.rects:
                    continue
                rects = pdf_render.locate_highlight_rects(
                    pdf_bytes, proof.page_number, [highlight.text]
                )
                if rects:
                    highlight.rects = rects

    async def render_page_image(
        self,
        *,
        collection_id: str,
        document_key: str,
        page_number: int,
        tenant_id: str,
        dpi: int = 150,
    ) -> Optional[bytes]:
        """Render a stored collection PDF page to PNG bytes (tenant-checked)."""
        collection = await self._ensure_collection_loaded(collection_id, tenant_id)
        self._assert_tenant(collection, tenant_id)
        pdf_bytes = self._load_original_pdf(collection_id, document_key)
        if not pdf_bytes:
            return None
        return pdf_render.render_page_to_png(pdf_bytes, page_number, dpi=dpi)


_document_collection_service: Optional[DocumentCollectionService] = None


def get_document_collection_service() -> DocumentCollectionService:
    global _document_collection_service
    if _document_collection_service is None:
        _document_collection_service = DocumentCollectionService()
    return _document_collection_service
