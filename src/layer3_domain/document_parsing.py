"""
Raw document parsing into normalized IngestedDocument objects.

The goal is to keep parsing modular:
- parser selection by source type / mime type
- page-aware normalized output
- easy extension to OCR, table extraction, and richer PDF tooling later
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path
from typing import Protocol, Sequence

from pydantic import BaseModel, Field

from src.layer3_domain.document_models import IngestedDocument, IngestedPage
from src.layer3_domain.medical_document_structure import build_medical_page_metadata
from src.shared.errors import DocumentParsingError
from src.shared.logger import get_logger

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover - optional dependency/runtime behavior
    PdfReader = None

try:
    import pdfplumber
except Exception:  # pragma: no cover - optional dependency/runtime behavior
    pdfplumber = None

logger = get_logger(__name__)


class RawDocumentAsset(BaseModel):
    """Raw source asset before normalization into IngestedDocument."""

    document_id: str = Field(..., description="Unique document ID")
    tenant_id: str = Field(default="default", description="Tenant isolation key")
    domain: str = Field(default="general", description="Domain or subdomain label")
    title: str = Field(..., description="Human-readable document title")
    source_uri: str = Field(..., description="Source path or URI")
    source_type: str = Field(default="pdf", description="pdf|text|json|table|web|api")
    mime_type: str = Field(default="application/pdf", description="Declared mime type")
    content_bytes: bytes = Field(..., description="Raw file or payload bytes")
    language: str = Field(default="en", description="Primary source language")
    metadata: dict[str, str] = Field(default_factory=dict, description="Source metadata")


@dataclass(frozen=True)
class ParserContext:
    """Context for parser execution."""

    page_delimiter: str = "\f"
    default_encoding: str = "utf-8"


class DocumentParser(Protocol):
    """Parser contract for raw source assets."""

    def supports(self, asset: RawDocumentAsset) -> bool:
        """Whether this parser can handle the asset."""

    def parse(self, asset: RawDocumentAsset, context: ParserContext) -> IngestedDocument:
        """Parse raw bytes into a normalized document."""


def _clean_text(text: str) -> str:
    cleaned = "\n".join(
        line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    )
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"([•*-])(?=\S)", r"\1 ", cleaned)
    cleaned = re.sub(r"([a-z])([A-Z][a-z])", r"\1 \2", cleaned)
    return cleaned.strip()


class PageDelimitedTextParser:
    """
    Text parser for deterministic local ingestion and test fixtures.

    Pages are separated by form-feed by default. This gives us a stable
    raw-to-page flow even when binary PDF parsing is unavailable.
    """

    def supports(self, asset: RawDocumentAsset) -> bool:
        return asset.source_type == "text" or asset.mime_type.startswith("text/")

    def parse(self, asset: RawDocumentAsset, context: ParserContext) -> IngestedDocument:
        try:
            decoded = asset.content_bytes.decode(context.default_encoding)
        except UnicodeDecodeError as exc:
            raise DocumentParsingError(
                source_name=asset.title,
                details={"mime_type": asset.mime_type, "error": str(exc)},
            ) from exc

        raw_pages = [part for part in decoded.split(context.page_delimiter)]
        pages = [
            self._build_page(asset, index + 1, _clean_text(text))
            for index, text in enumerate(raw_pages)
            if _clean_text(text)
        ]
        if not pages:
            raise DocumentParsingError(
                source_name=asset.title,
                details={"reason": "no_nonempty_pages", "mime_type": asset.mime_type},
            )
        return IngestedDocument(
            document_id=asset.document_id,
            tenant_id=asset.tenant_id,
            domain=asset.domain,
            title=asset.title,
            source_uri=asset.source_uri,
            source_type=asset.source_type,
            language=asset.language,
            pages=pages,
            metadata=asset.metadata,
        )

    def _build_page(
        self,
        asset: RawDocumentAsset,
        page_number: int,
        text: str,
    ) -> IngestedPage:
        page_metadata = {**asset.metadata, **build_medical_page_metadata(asset.title, text)}
        return IngestedPage(
            document_id=asset.document_id,
            tenant_id=asset.tenant_id,
            domain=asset.domain,
            title=asset.title,
            source_uri=asset.source_uri,
            source_type=asset.source_type,
            page_number=page_number,
            text=text,
            section_title=page_metadata.get("section_name"),
            language=asset.language,
            metadata=page_metadata,
        )


class PyPDFDocumentParser:
    """Page-preserving PDF text parser, preferring pdfplumber when available."""

    def supports(self, asset: RawDocumentAsset) -> bool:
        return asset.source_type == "pdf" or asset.mime_type == "application/pdf"

    def parse(self, asset: RawDocumentAsset, context: ParserContext) -> IngestedDocument:
        if pdfplumber is None and PdfReader is None:
            raise DocumentParsingError(
                source_name=asset.title,
                details={"reason": "pdf_parser_not_installed", "mime_type": asset.mime_type},
            )

        import io

        try:
            pages: list[IngestedPage] = []
            if pdfplumber is not None:
                with pdfplumber.open(io.BytesIO(asset.content_bytes)) as pdf:
                    for index, page in enumerate(pdf.pages):
                        extracted = _clean_text(page.extract_text(x_tolerance=1, y_tolerance=3) or "")
                        if extracted:
                            pages.append(self._build_page(asset, index + 1, extracted))
            else:
                reader = PdfReader(io.BytesIO(asset.content_bytes))
                for index, page in enumerate(reader.pages):
                    extracted = _clean_text(page.extract_text() or "")
                    if extracted:
                        pages.append(self._build_page(asset, index + 1, extracted))
        except Exception as exc:
            raise DocumentParsingError(
                source_name=asset.title,
                details={"mime_type": asset.mime_type, "error": str(exc)},
            ) from exc

        if not pages:
            raise DocumentParsingError(
                source_name=asset.title,
                details={"reason": "no_extractable_text", "mime_type": asset.mime_type},
            )

        return IngestedDocument(
            document_id=asset.document_id,
            tenant_id=asset.tenant_id,
            domain=asset.domain,
            title=asset.title,
            source_uri=asset.source_uri,
            source_type=asset.source_type,
            language=asset.language,
            pages=pages,
            metadata=asset.metadata,
        )

    def _build_page(
        self,
        asset: RawDocumentAsset,
        page_number: int,
        text: str,
    ) -> IngestedPage:
        page_metadata = {**asset.metadata, **build_medical_page_metadata(asset.title, text)}
        return IngestedPage(
            document_id=asset.document_id,
            tenant_id=asset.tenant_id,
            domain=asset.domain,
            title=asset.title,
            source_uri=asset.source_uri,
            source_type=asset.source_type,
            page_number=page_number,
            text=text,
            section_title=page_metadata.get("section_name"),
            language=asset.language,
            metadata=page_metadata,
        )


class DocumentParsingService:
    """Select and run the best available parser for a raw document asset."""

    def __init__(
        self,
        parsers: Sequence[DocumentParser] | None = None,
        context: ParserContext | None = None,
    ) -> None:
        self.parsers = list(parsers or [PyPDFDocumentParser(), PageDelimitedTextParser()])
        self.context = context or ParserContext()

    def parse_asset(self, asset: RawDocumentAsset) -> IngestedDocument:
        for parser in self.parsers:
            if parser.supports(asset):
                document = parser.parse(asset, self.context)
                logger.info(
                    "document_parsed",
                    document_id=document.document_id,
                    title=document.title,
                    page_count=len(document.pages),
                    source_type=document.source_type,
                    layer="layer3_domain",
                )
                return document

        raise DocumentParsingError(
            source_name=asset.title,
            details={"reason": "no_parser_available", "mime_type": asset.mime_type},
        )

    def parse_many(self, assets: Sequence[RawDocumentAsset]) -> list[IngestedDocument]:
        return [self.parse_asset(asset) for asset in assets]
