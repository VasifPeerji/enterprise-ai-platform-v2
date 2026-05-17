import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.layer3_domain.document_parsing import (  # noqa: E402
    DocumentParsingService,
    PageDelimitedTextParser,
    RawDocumentAsset,
)
from src.shared.errors import DocumentParsingError  # noqa: E402


def test_page_delimited_text_parser_creates_multiple_pages():
    service = DocumentParsingService(parsers=[PageDelimitedTextParser()])
    asset = RawDocumentAsset(
        document_id="loan-doc",
        tenant_id="tenant-a",
        domain="lending",
        title="Loan Agreement Text Export",
        source_uri="/docs/loan.txt",
        source_type="text",
        mime_type="text/plain",
        content_bytes=(
            "Foreclosure charges are 2% of outstanding principal.\f"
            "Late payment fee is 500 rupees.\f"
            "Processing fee is collected at disbursal."
        ).encode("utf-8"),
        language="en",
    )

    document = service.parse_asset(asset)

    assert document.document_id == "loan-doc"
    assert len(document.pages) == 3
    assert document.pages[1].page_number == 2
    assert "Late payment fee" in document.pages[1].text


def test_page_delimited_text_parser_strips_blank_pages():
    service = DocumentParsingService(parsers=[PageDelimitedTextParser()])
    asset = RawDocumentAsset(
        document_id="loan-doc",
        tenant_id="tenant-a",
        domain="lending",
        title="Blanky",
        source_uri="/docs/blanky.txt",
        source_type="text",
        mime_type="text/plain",
        content_bytes="Page one\f \fPage three".encode("utf-8"),
        language="en",
    )

    document = service.parse_asset(asset)

    assert len(document.pages) == 2
    assert [page.page_number for page in document.pages] == [1, 3]


def test_document_parsing_service_raises_when_no_parser_matches():
    service = DocumentParsingService(parsers=[PageDelimitedTextParser()])
    asset = RawDocumentAsset(
        document_id="loan-doc",
        tenant_id="tenant-a",
        domain="lending",
        title="Binary Asset",
        source_uri="/docs/file.bin",
        source_type="binary",
        mime_type="application/octet-stream",
        content_bytes=b"\x01\x02\x03",
        language="en",
    )

    with pytest.raises(DocumentParsingError):
        service.parse_asset(asset)


def test_document_parsing_service_parse_many_keeps_document_order():
    service = DocumentParsingService(parsers=[PageDelimitedTextParser()])
    assets = [
        RawDocumentAsset(
            document_id="a",
            tenant_id="tenant-a",
            domain="lending",
            title="A",
            source_uri="/docs/a.txt",
            source_type="text",
            mime_type="text/plain",
            content_bytes="Alpha".encode("utf-8"),
            language="en",
        ),
        RawDocumentAsset(
            document_id="b",
            tenant_id="tenant-a",
            domain="lending",
            title="B",
            source_uri="/docs/b.txt",
            source_type="text",
            mime_type="text/plain",
            content_bytes="Beta".encode("utf-8"),
            language="en",
        ),
    ]

    documents = service.parse_many(assets)

    assert [document.document_id for document in documents] == ["a", "b"]
