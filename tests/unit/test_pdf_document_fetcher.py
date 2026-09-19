"""Unit tests for ResearchDocumentFetcher and local PDF section extraction."""

import io
import pytest
import pypdf
from app.research.document import (
    FullTextStatus,
    ResearchDocumentFetcher,
    SectionExtractionResult,
)


def create_sample_pdf_bytes() -> bytes:
    """Helper to dynamically generate a small 4-page PDF with realistic scholarly sections."""
    writer = pypdf.PdfWriter()

    # Page 1: Abstract
    p1 = writer.add_blank_page(width=612, height=792)
    # Note: pypdf blank pages don't have text by default unless drawn or annotated.
    # To create extractable text without reportlab, we can write raw PDF stream content.
    return b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R 4 0 R 5 0 R] /Count 3 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 6 0 R /Resources << /Font << /F1 9 0 R >> >> >>
endobj
4 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 7 0 R /Resources << /Font << /F1 9 0 R >> >> >>
endobj
5 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 8 0 R /Resources << /Font << /F1 9 0 R >> >> >>
endobj
6 0 obj
<< /Length 120 >>
stream
BT
/F1 12 Tf
72 700 Td
(Abstract) Tj
0 -20 Td
(This paper presents a recurrent memory architecture for LLMs that compresses state.) Tj
ET
endstream
endobj
7 0 obj
<< /Length 140 >>
stream
BT
/F1 12 Tf
72 700 Td
(1. Introduction) Tj
0 -20 Td
(Ever-growing KV cache causes severe GPU memory pressure during inference.) Tj
ET
endstream
endobj
8 0 obj
<< /Length 170 >>
stream
BT
/F1 12 Tf
72 700 Td
(3. Methods) Tj
0 -20 Td
(We maintain a compact internal hidden state updated via recurrent state-space equations.) Tj
0 -20 Td
(State management is transactional and bounded in memory.) Tj
ET
endstream
endobj
9 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 10
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000127 00000 n 
0000000244 00000 n 
0000000361 00000 n 
0000000478 00000 n 
0000000650 00000 n 
0000000842 00000 n 
0000001064 00000 n 
trailer
<< /Size 10 /Root 1 0 R >>
startxref
1137
%%EOF"""


def test_pdf_parsing_extracts_pages_and_sections():
    """Verify pypdf extracts text pages and correctly detects sections with page provenance."""
    fetcher = ResearchDocumentFetcher()
    raw_pdf = create_sample_pdf_bytes()

    parsed = fetcher.parse_pdf_bytes(raw_pdf, doc_url="https://arxiv.org/pdf/2401.9999.pdf", canonical_id="arxiv:2401.9999")

    assert parsed.status == FullTextStatus.AVAILABLE
    assert parsed.total_pages == 3
    assert 1 in parsed.pages
    assert 2 in parsed.pages
    assert 3 in parsed.pages

    # Check section detection
    assert "abstract" in parsed.sections
    assert "introduction" in parsed.sections
    assert "methods" in parsed.sections

    # Check page provenance
    methods_sec = parsed.sections["methods"]
    assert methods_sec.start_page == 3
    assert methods_sec.end_page == 3
    assert "recurrent state-space" in methods_sec.content

    # Check grounding quote
    quote = "We maintain a compact internal hidden state updated via recurrent state-space equations."
    assert quote.lower() in methods_sec.content.lower()


def test_missing_section_handling():
    """Verify that an absent section is not hallucinated."""
    fetcher = ResearchDocumentFetcher()
    raw_pdf = create_sample_pdf_bytes()

    parsed = fetcher.parse_pdf_bytes(raw_pdf, doc_url="https://arxiv.org/pdf/2401.9999.pdf")
    # 'experiments' and 'limitations' sections were not in this sample PDF
    assert "experiments" not in parsed.sections
    assert "limitations" not in parsed.sections


def test_pdf_security_blocks_file_protocol():
    """Ensure file:// and local filesystem paths are blocked."""
    fetcher = ResearchDocumentFetcher()
    with pytest.raises(ValueError, match="Only HTTP/HTTPS external retrieval is permitted"):
        fetcher._validate_url("file:///etc/passwd")

    with pytest.raises(ValueError, match="Only HTTP/HTTPS external retrieval is permitted"):
        fetcher._validate_url("C:\\Windows\\System32\\calc.exe")


def test_pdf_parsing_handles_corrupt_bytes():
    """Ensure malformed or non-PDF bytes result in PARSE_FAILED rather than an uncaught exception."""
    fetcher = ResearchDocumentFetcher()
    parsed = fetcher.parse_pdf_bytes(b"NOT A REAL PDF CONTENT AT ALL", doc_url="https://example.com/bad.pdf")
    assert parsed.status == FullTextStatus.PARSE_FAILED
    assert "Corrupt or invalid PDF format" in (parsed.error_message or "")


def test_pdf_resource_limits_max_pages():
    """Ensure parser respects max_pages boundary constraint."""
    fetcher = ResearchDocumentFetcher(max_pages=2)
    raw_pdf = create_sample_pdf_bytes()  # Has 3 pages

    parsed = fetcher.parse_pdf_bytes(raw_pdf, doc_url="https://arxiv.org/pdf/2401.9999.pdf")
    assert len(parsed.pages) == 2
    assert 3 not in parsed.pages
