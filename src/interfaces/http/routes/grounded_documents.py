"""
Grounded document QA endpoints.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Response, status
from fastapi import File, Form, UploadFile
from pydantic import BaseModel, Field

from src.layer1_intelligence.rag_service import (
    GroundedRAGService,
    RAGResponse,
    RAGServiceConfig,
)
from src.layer3_domain.document_collections import (
    CollectionNotFoundError,
    DocumentCollectionSummary,
    get_document_collection_service,
)
from src.layer3_domain.document_models import GroundedAnswerContext, IngestedDocument, RetrievalQuery
from src.layer3_domain.document_parsing import RawDocumentAsset
from src.layer3_domain.web_crawler import WebCrawler
from src.shared.config import get_settings
from src.shared.errors import DocumentParsingError, NoRelevantContextError
from src.shared.logger import get_logger

router = APIRouter(prefix="/grounded-documents", tags=["Grounded Documents"])
logger = get_logger(__name__)
collection_service = get_document_collection_service()


class GroundedDocumentsRequest(BaseModel):
    """Request payload for grounded document QA."""

    query: str = Field(..., min_length=1, description="Question to answer from provided documents")
    documents: list[IngestedDocument] = Field(..., min_length=1, description="Documents to ingest")
    tenant_id: str = Field(default="default", description="Tenant isolation key")
    domain: str = Field(default="general", description="Domain or subdomain label")
    top_k: int = Field(default=6, ge=1, le=20, description="Maximum evidence units to retrieve")
    generation_mode: str = Field(
        default="gateway",
        description="heuristic or gateway",
        pattern="^(heuristic|gateway)$",
    )
    no_context_policy: str = Field(
        default="raise",
        description="raise or graceful",
        pattern="^(raise|graceful)$",
    )


class GroundedDocumentsResponse(RAGResponse):
    """Grounded answer response with request metadata."""

    domain: str = Field(..., description="Domain used for retrieval")
    generation_mode: str = Field(..., description="Generation mode used")


class GroundedDocumentsAnalyzeResponse(BaseModel):
    """Analysis response without final answer generation."""

    retrieval_count: int = Field(..., ge=0)
    citations: list = Field(default_factory=list)
    page_proofs: list = Field(default_factory=list)
    evidence_groups: list = Field(default_factory=list)
    context_blocks: list[str] = Field(default_factory=list)


class GroundedCollectionQueryRequest(BaseModel):
    query: str = Field(..., min_length=1)
    tenant_id: str = Field(default="default")
    domain: Optional[str] = Field(default=None)
    top_k: int = Field(default=6, ge=1, le=20)
    generation_mode: str = Field(
        default="gateway",
        description="heuristic or gateway",
        pattern="^(heuristic|gateway)$",
    )


class GroundedCollectionAnswerResponse(GroundedDocumentsResponse):
    collection_id: str = Field(...)


class GroundedCollectionListResponse(BaseModel):
    collections: list[DocumentCollectionSummary] = Field(default_factory=list)


class CrawlRequest(BaseModel):
    """Ingest a company website into a grounded collection by crawling it."""

    start_url: str = Field(..., min_length=4, description="Page to start crawling from")
    tenant_id: str = Field(default="default")
    domain: str = Field(default="general")
    max_pages: int = Field(default=25, ge=1, le=500, description="Pages to fetch (clamped to server cap)")
    max_depth: int = Field(default=2, ge=0, le=10, description="Link-follow depth (clamped to server cap)")
    generation_mode: str = Field(default="gateway", pattern="^(heuristic|gateway)$")
    top_k: int = Field(default=6, ge=1, le=20)


class CrawlSummary(BaseModel):
    """Result of a crawl ingestion: the collection plus crawl statistics."""

    collection: DocumentCollectionSummary
    start_url: str
    pages_crawled: int
    pages_skipped: int
    thin_pages: int
    robots_blocked: int
    warnings: list[str] = Field(default_factory=list)


GroundedDocumentsRequest.model_rebuild()
GroundedDocumentsResponse.model_rebuild()
GroundedDocumentsAnalyzeResponse.model_rebuild()
GroundedCollectionQueryRequest.model_rebuild()
GroundedCollectionAnswerResponse.model_rebuild()
GroundedCollectionListResponse.model_rebuild()
CrawlSummary.model_rebuild()


def _document_parsing_detail(exc: DocumentParsingError) -> str:
    details = exc.details or {}
    reason = details.get("reason")
    if reason in {"pypdf_not_installed", "pdf_parser_not_installed"}:
        return (
            f"{exc.message}. PDF parsing dependencies are not installed in the active environment."
        )
    if reason == "no_extractable_text":
        return (
            f"{exc.message}. The PDF appears to have no extractable text. "
            "It may be scanned/image-only and would need OCR support."
        )
    inner_error = details.get("error")
    if inner_error:
        return f"{exc.message}. Parser detail: {inner_error}"
    return exc.message


def _build_service(request: GroundedDocumentsRequest) -> GroundedRAGService:
    service = GroundedRAGService.for_production_like_runtime(
        domain=request.domain,
        top_k=request.top_k,
        use_gateway_answer=request.generation_mode == "gateway",
    )
    service.config = RAGServiceConfig(
        top_k=request.top_k,
        rerank_top_k=request.top_k,
        min_results=1,
        domain=request.domain,
        raise_on_no_context=request.no_context_policy == "raise",
    )
    return service


@router.post(
    "/answer",
    response_model=GroundedDocumentsResponse,
    summary="Answer from grounded documents",
    description="Generate a grounded answer with citations and highlight spans from provided documents.",
)
async def answer_from_grounded_documents(
    request: GroundedDocumentsRequest,
) -> GroundedDocumentsResponse:
    logger.info(
        "grounded_documents_request_received",
        query_length=len(request.query),
        document_count=len(request.documents),
        generation_mode=request.generation_mode,
        domain=request.domain,
    )

    service = _build_service(request)

    try:
        await service.index_documents(request.documents)
        response = await service.answer_query(
            request.query,
            tenant_id=request.tenant_id,
            domain=request.domain,
            top_k=request.top_k,
        )
        return GroundedDocumentsResponse(
            **response.model_dump(),
            domain=request.domain,
            generation_mode=request.generation_mode,
        )
    except NoRelevantContextError as exc:
        logger.warning("grounded_documents_no_context", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.message,
        ) from exc
    except Exception as exc:
        logger.error("grounded_documents_failed", error=str(exc), error_type=type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Grounded document answering failed: {str(exc)}",
        ) from exc


@router.post(
    "/analyze",
    response_model=GroundedDocumentsAnalyzeResponse,
    summary="Analyze grounded retrieval",
    description="Retrieve and assemble grounded context without final answer generation.",
)
async def analyze_grounded_documents(
    request: GroundedDocumentsRequest,
) -> GroundedDocumentsAnalyzeResponse:
    service = _build_service(request)
    try:
        await service.index_documents(request.documents)
        retrieval_request = RetrievalQuery(
            query=request.query,
            tenant_id=request.tenant_id,
            domain=request.domain,
            top_k=request.top_k,
        )
        results = await service.index_service.search(retrieval_request)
        grounded_context: GroundedAnswerContext = service.assembler.assemble(
            query=request.query,
            results=results,
        )
        return GroundedDocumentsAnalyzeResponse(
            retrieval_count=len(results),
            citations=grounded_context.citations,
            page_proofs=grounded_context.page_proofs,
            evidence_groups=grounded_context.evidence_groups,
            context_blocks=grounded_context.context_blocks,
        )
    except Exception as exc:
        logger.error("grounded_documents_analysis_failed", error=str(exc), error_type=type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Grounded document analysis failed: {str(exc)}",
        ) from exc


@router.post(
    "/collections/upload",
    response_model=DocumentCollectionSummary,
    summary="Upload documents into a grounded collection",
    description="Upload one or more raw files, parse them, and index them into a reusable grounded collection.",
)
async def upload_grounded_documents(
    collection_id: str = Form(...),
    tenant_id: str = Form("default"),
    domain: str = Form("general"),
    generation_mode: str = Form("gateway"),
    top_k: int = Form(6),
    files: list[UploadFile] = File(...),
) -> DocumentCollectionSummary:
    assets: list[RawDocumentAsset] = []
    for index, file in enumerate(files):
        content = await file.read()
        if not content:
            continue
        source_type = "pdf" if (file.content_type or "").endswith("pdf") else "text"
        assets.append(
            RawDocumentAsset(
                document_id=f"{collection_id}:{index}:{file.filename or 'document'}",
                tenant_id=tenant_id,
                domain=domain,
                title=file.filename or f"document-{index + 1}",
                source_uri=file.filename or f"upload-{index + 1}",
                source_type=source_type,
                mime_type=file.content_type or "application/octet-stream",
                content_bytes=content,
            )
        )

    try:
        return await collection_service.ingest_assets(
            collection_id=collection_id,
            tenant_id=tenant_id,
            domain=domain,
            assets=assets,
            generation_mode=generation_mode,
            top_k=top_k,
        )
    except DocumentParsingError as exc:
        logger.warning(
            "grounded_collection_upload_parsing_failed",
            error=str(exc),
            details=exc.details,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_document_parsing_detail(exc),
        ) from exc
    except Exception as exc:
        logger.error("grounded_collection_upload_failed", error=str(exc), error_type=type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Grounded collection upload failed: {str(exc)}",
        ) from exc


@router.post(
    "/collections/{collection_id}/crawl",
    response_model=CrawlSummary,
    summary="Crawl a website into a grounded collection",
    description=(
        "Fetch a company's website (same-domain, depth- and page-capped, robots-aware), "
        "extract page text, and index it into a grounded collection. Each page keeps its "
        "URL as the citation source. Static/server-rendered sites only — JavaScript-rendered "
        "SPAs return little text and are reported in `warnings`."
    ),
)
async def crawl_into_collection(collection_id: str, request: CrawlRequest) -> CrawlSummary:
    settings = get_settings()
    max_pages = min(request.max_pages, settings.WIDGET_CRAWLER_MAX_PAGES)
    max_depth = min(request.max_depth, settings.WIDGET_CRAWLER_MAX_DEPTH)

    crawler = WebCrawler(max_pages=max_pages, max_depth=max_depth)
    try:
        result = await crawler.crawl(
            request.start_url,
            collection_id=collection_id,
            tenant_id=request.tenant_id,
            domain=request.domain,
        )
    except Exception as exc:
        logger.error("grounded_collection_crawl_failed", error=str(exc), error_type=type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Crawl failed: {exc}",
        ) from exc

    if not result.assets:
        reason = " ".join(result.warnings) or (
            "No readable text was found. The site may be JavaScript-rendered, empty, or "
            "disallowed by robots.txt."
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Crawl produced no ingestable pages. {reason}",
        )

    try:
        summary = await collection_service.ingest_assets(
            collection_id=collection_id,
            tenant_id=request.tenant_id,
            domain=request.domain,
            assets=result.assets,
            generation_mode=request.generation_mode,
            top_k=request.top_k,
        )
    except DocumentParsingError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_document_parsing_detail(exc),
        ) from exc

    return CrawlSummary(
        collection=summary,
        start_url=request.start_url,
        pages_crawled=result.pages_crawled,
        pages_skipped=result.pages_skipped,
        thin_pages=result.thin_pages,
        robots_blocked=result.robots_blocked,
        warnings=result.warnings,
    )


@router.get(
    "/collections",
    response_model=GroundedCollectionListResponse,
    summary="List grounded collections for a tenant",
)
async def list_grounded_collections(
    tenant_id: str = "default",
) -> GroundedCollectionListResponse:
    collections = await collection_service.list_collections(tenant_id)
    return GroundedCollectionListResponse(collections=collections)


@router.get(
    "/collections/{collection_id}",
    response_model=DocumentCollectionSummary,
    summary="Get grounded collection metadata",
)
async def get_grounded_collection(
    collection_id: str,
    tenant_id: str = "default",
) -> DocumentCollectionSummary:
    try:
        return collection_service.get_collection(collection_id, tenant_id)
    except CollectionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message) from exc


@router.put(
    "/collections/{collection_id}/replace",
    response_model=DocumentCollectionSummary,
    summary="Replace documents in a grounded collection",
)
async def replace_grounded_documents(
    collection_id: str,
    tenant_id: str = Form("default"),
    domain: str = Form("general"),
    generation_mode: str = Form("gateway"),
    top_k: int = Form(6),
    files: list[UploadFile] = File(...),
) -> DocumentCollectionSummary:
    assets: list[RawDocumentAsset] = []
    for index, file in enumerate(files):
        content = await file.read()
        if not content:
            continue
        source_type = "pdf" if (file.content_type or "").endswith("pdf") else "text"
        assets.append(
            RawDocumentAsset(
                document_id=f"{collection_id}:{index}:{file.filename or 'document'}",
                tenant_id=tenant_id,
                domain=domain,
                title=file.filename or f"document-{index + 1}",
                source_uri=file.filename or f"upload-{index + 1}",
                source_type=source_type,
                mime_type=file.content_type or "application/octet-stream",
                content_bytes=content,
            )
        )

    try:
        return await collection_service.replace_assets(
            collection_id=collection_id,
            tenant_id=tenant_id,
            domain=domain,
            assets=assets,
            generation_mode=generation_mode,
            top_k=top_k,
        )
    except DocumentParsingError as exc:
        logger.warning(
            "grounded_collection_replace_parsing_failed",
            error=str(exc),
            details=exc.details,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_document_parsing_detail(exc),
        ) from exc


@router.post(
    "/collections/{collection_id}/answer",
    response_model=GroundedCollectionAnswerResponse,
    summary="Answer using a persisted grounded collection",
)
async def answer_from_grounded_collection(
    collection_id: str,
    request: GroundedCollectionQueryRequest,
) -> GroundedCollectionAnswerResponse:
    try:
        response = await collection_service.answer_query(
            collection_id=collection_id,
            query=request.query,
            tenant_id=request.tenant_id,
            domain=request.domain,
            top_k=request.top_k,
            generation_mode=request.generation_mode,
        )
        summary = collection_service.get_collection(collection_id, request.tenant_id)
        return GroundedCollectionAnswerResponse(
            **response.model_dump(),
            collection_id=summary.collection_id,
            domain=summary.domain,
            generation_mode=request.generation_mode,
        )
    except CollectionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message) from exc
    except NoRelevantContextError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message) from exc


@router.post(
    "/collections/{collection_id}/analyze",
    summary="Analyze retrieval against a persisted grounded collection",
)
async def analyze_grounded_collection(
    collection_id: str,
    request: GroundedCollectionQueryRequest,
) -> GroundedDocumentsAnalyzeResponse:
    try:
        payload = await collection_service.analyze_query(
            collection_id=collection_id,
            query=request.query,
            tenant_id=request.tenant_id,
            domain=request.domain,
            top_k=request.top_k,
        )
        return GroundedDocumentsAnalyzeResponse(**payload)
    except CollectionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message) from exc


@router.get(
    "/collections/{collection_id}/page-image",
    response_class=Response,
    response_model=None,
    summary="Render an original PDF page image for a grounded collection",
    description=(
        "Return the rendered original page as PNG for a document in the "
        "collection, so the UI can overlay citation highlights on the exact "
        "source page instead of re-flowed extracted text."
    ),
    responses={200: {"content": {"image/png": {}}}},
)
async def get_grounded_collection_page_image(
    collection_id: str,
    document_key: str,
    page_number: int,
    tenant_id: str = "default",
    dpi: int = 150,
) -> Response:
    try:
        png = await collection_service.render_page_image(
            collection_id=collection_id,
            document_key=document_key,
            page_number=page_number,
            tenant_id=tenant_id,
            dpi=max(72, min(dpi, 300)),
        )
    except CollectionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message) from exc
    if png is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Original page image is not available for this document/page.",
        )
    return Response(content=png, media_type="image/png")


@router.delete(
    "/collections/{collection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    summary="Delete a grounded collection",
)
async def delete_grounded_collection(
    collection_id: str,
    tenant_id: str = "default",
) -> Response:
    await collection_service.delete_collection(collection_id, tenant_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
