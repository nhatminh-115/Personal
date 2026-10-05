"""Document retrieval, secure PDF extraction, and conservative section detection for scholarly research."""

import asyncio
import io
import ipaddress
import re
import socket
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit
import httpx
from pydantic import BaseModel, Field
import pypdf

from app.core.logging import logger
from app.core.settings import settings
from app.research.cache import research_cache


class FullTextStatus(str, Enum):
    """Status of full-text retrieval and parsing for a scholarly document."""

    AVAILABLE = "available"
    ABSTRACT_ONLY = "abstract_only"
    UNAVAILABLE = "unavailable"
    FETCH_FAILED = "fetch_failed"
    PARSE_FAILED = "parse_failed"
    SECTION_NOT_DETECTED = "section_not_detected"


class SectionExtractionResult(BaseModel):
    """Extracted text of a specific scholarly section with page provenance."""

    section_name: str
    content: str
    start_page: int
    end_page: int
    status: str = "detected"


class ParsedDocument(BaseModel):
    """Structured representation of a parsed research document."""

    doc_url: str
    canonical_id: Optional[str] = None
    pages: Dict[int, str] = Field(default_factory=dict)
    full_text: str = ""
    sections: Dict[str, SectionExtractionResult] = Field(default_factory=dict)
    status: FullTextStatus = FullTextStatus.UNAVAILABLE
    total_pages: int = 0
    total_chars: int = 0
    error_message: Optional[str] = None


class ResearchDocumentFetcher:
    """Safely retrieves public PDFs and extracts structured text and section boundaries."""

    MAX_REDIRECTS = 5

    # Canonical scholarly section name mappings (pattern -> canonical_name)
    SECTION_PATTERNS: List[Tuple[re.Pattern, str]] = [
        (re.compile(r"^(?:(?:\d+\.?)?\s*)?(?:abstract|summary)\b", re.IGNORECASE), "abstract"),
        (re.compile(r"^(?:(?:\d+\.?)?\s*)?(?:introduction|overview)\b", re.IGNORECASE), "introduction"),
        (re.compile(r"^(?:(?:\d+\.?)?\s*)?(?:background|preliminaries)\b", re.IGNORECASE), "background"),
        (re.compile(r"^(?:(?:\d+\.?)?\s*)?(?:related\s+work|prior\s+work|literature\s+review)\b", re.IGNORECASE), "related_work"),
        (re.compile(r"^(?:(?:\d+\.?)?\s*)?(?:methodology|methods|method|proposed\s+method|our\s+approach|architecture|system\s+design)\b", re.IGNORECASE), "methods"),
        (re.compile(r"^(?:(?:\d+\.?)?\s*)?(?:experiments|experimental\s+setup|evaluation|empirical\s+evaluation)\b", re.IGNORECASE), "experiments"),
        (re.compile(r"^(?:(?:\d+\.?)?\s*)?(?:results|findings|empirical\s+results)\b", re.IGNORECASE), "results"),
        (re.compile(r"^(?:(?:\d+\.?)?\s*)?(?:discussion|analysis)\b", re.IGNORECASE), "discussion"),
        (re.compile(r"^(?:(?:\d+\.?)?\s*)?(?:limitations|broader\s+impact)\b", re.IGNORECASE), "limitations"),
        (re.compile(r"^(?:(?:\d+\.?)?\s*)?(?:conclusion|conclusions|concluding\s+remarks)\b", re.IGNORECASE), "conclusion"),
    ]

    def __init__(
        self,
        timeout_seconds: Optional[float] = None,
        max_bytes: Optional[int] = None,
        max_pages: Optional[int] = None,
        max_extracted_chars: Optional[int] = None,
        cache: Optional[Any] = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds or settings.RESEARCH_HTTP_TIMEOUT_SECONDS
        self.max_bytes = max_bytes or settings.RESEARCH_MAX_PDF_BYTES
        self.max_pages = max_pages or settings.RESEARCH_MAX_PDF_PAGES
        self.max_extracted_chars = max_extracted_chars or settings.RESEARCH_MAX_EXTRACTED_CHARS
        self.cache = cache or research_cache

    def _validate_url(self, url: str) -> None:
        """Reject unsafe URL syntax and literal private or reserved destinations."""
        try:
            parsed = urlsplit(url.strip())
            if parsed.scheme.lower() not in {"http", "https"}:
                raise ValueError
            if not parsed.hostname or parsed.username is not None or parsed.password is not None:
                raise ValueError
            _ = parsed.port  # Force validation of malformed ports.
            try:
                address = ipaddress.ip_address(parsed.hostname)
            except ValueError:
                return
            if not address.is_global:
                raise ValueError
        except ValueError as exc:
            raise ValueError(
                "Invalid document URL. Only public HTTP/HTTPS destinations are permitted."
            ) from exc

    async def _resolve_host_addresses(
        self, hostname: str, port: int
    ) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
        """Resolve a destination without blocking the event loop."""
        loop = asyncio.get_running_loop()
        results = await loop.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        addresses = set()
        for result in results:
            try:
                addresses.add(ipaddress.ip_address(result[4][0].split("%", 1)[0]))
            except ValueError:
                continue
        return addresses

    async def _validate_public_destination(self, url: str) -> None:
        """Reject hostnames resolving to loopback, private, link-local, or reserved IPs."""
        self._validate_url(url)
        parsed = urlsplit(url)
        hostname = parsed.hostname or ""
        try:
            ipaddress.ip_address(hostname)
            return  # Literal addresses were checked by _validate_url.
        except ValueError:
            pass

        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
        try:
            addresses = await self._resolve_host_addresses(hostname.encode("idna").decode("ascii"), port)
        except (OSError, UnicodeError) as exc:
            raise ValueError("Document host could not be resolved safely.") from exc
        if not addresses or any(not address.is_global for address in addresses):
            raise ValueError("Document host resolves to a non-public network address.")

    async def fetch_and_parse(self, doc_url: str, canonical_id: Optional[str] = None) -> ParsedDocument:
        """Download and extract scholarly text from a PDF with resource bounding."""
        doc_url = doc_url.strip()
        cache_key = f"{canonical_id or ''}:{doc_url}"
        cached = self.cache.get_document(cache_key)
        if cached:
            try:
                return ParsedDocument(**cached)
            except Exception:
                logger.debug("Cached research document could not be read; it will be fetched again.")

        try:
            self._validate_url(doc_url)
        except ValueError:
            return ParsedDocument(
                doc_url=doc_url,
                canonical_id=canonical_id,
                status=FullTextStatus.FETCH_FAILED,
                error_message="Invalid document URL. Only public HTTP/HTTPS destinations are permitted.",
            )

        # 1. Download PDF stream with byte bounds. Redirects are handled manually so
        # each destination is checked before issuing the next request.
        pdf_bytes = bytearray()
        current_url = doc_url
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=False) as client:
                for redirect_count in range(self.MAX_REDIRECTS + 1):
                    await self._validate_public_destination(current_url)
                    async with client.stream("GET", current_url) as response:
                        if response.is_redirect:
                            location = response.headers.get("location")
                            if not location or redirect_count >= self.MAX_REDIRECTS:
                                return ParsedDocument(
                                    doc_url=doc_url,
                                    canonical_id=canonical_id,
                                    status=FullTextStatus.FETCH_FAILED,
                                    error_message="Document redirect limit exceeded or redirect location was missing.",
                                )
                            current_url = urljoin(current_url, location)
                            continue

                        if response.status_code != 200:
                            return ParsedDocument(
                                doc_url=doc_url,
                                canonical_id=canonical_id,
                                status=FullTextStatus.FETCH_FAILED,
                                error_message=f"HTTP status {response.status_code} fetching document.",
                            )

                        async for chunk in response.aiter_bytes(chunk_size=65536):
                            pdf_bytes.extend(chunk)
                            if len(pdf_bytes) > self.max_bytes:
                                return ParsedDocument(
                                    doc_url=doc_url,
                                    canonical_id=canonical_id,
                                    status=FullTextStatus.FETCH_FAILED,
                                    error_message=f"Document exceeded maximum allowed size ({self.max_bytes} bytes).",
                                )
                        break
                else:
                    return ParsedDocument(
                        doc_url=doc_url,
                        canonical_id=canonical_id,
                        status=FullTextStatus.FETCH_FAILED,
                        error_message="Document redirect limit exceeded.",
                    )
        except ValueError:
            return ParsedDocument(
                doc_url=doc_url,
                canonical_id=canonical_id,
                status=FullTextStatus.FETCH_FAILED,
                error_message="Document destination could not be validated safely.",
            )
        except httpx.TimeoutException:
            return ParsedDocument(
                doc_url=doc_url,
                canonical_id=canonical_id,
                status=FullTextStatus.FETCH_FAILED,
                error_message=f"Document download timed out after {self.timeout_seconds}s.",
            )
        except Exception:
            return ParsedDocument(
                doc_url=doc_url,
                canonical_id=canonical_id,
                status=FullTextStatus.FETCH_FAILED,
                error_message="Document download failed due to a network or transport error.",
            )

        # 2. Parse PDF with pypdf
        return self.parse_pdf_bytes(bytes(pdf_bytes), doc_url=doc_url, canonical_id=canonical_id, cache_key=cache_key)

    def parse_pdf_bytes(
        self,
        raw_bytes: bytes,
        doc_url: str = "",
        canonical_id: Optional[str] = None,
        cache_key: Optional[str] = None,
    ) -> ParsedDocument:
        """Parse raw PDF bytes into pages, full text, and detected sections."""
        try:
            reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
        except Exception:
            return ParsedDocument(
                doc_url=doc_url,
                canonical_id=canonical_id,
                status=FullTextStatus.PARSE_FAILED,
                error_message="Corrupt or invalid PDF format.",
            )

        pages: Dict[int, str] = {}
        full_text_parts: List[str] = []
        total_chars = 0
        num_pages_to_read = min(len(reader.pages), self.max_pages)

        for p_idx in range(num_pages_to_read):
            page_num = p_idx + 1
            try:
                page_text = reader.pages[p_idx].extract_text() or ""
            except Exception:
                logger.warning("Could not extract text from PDF page %s.", page_num)
                page_text = ""

            # Check character bounds
            if total_chars + len(page_text) > self.max_extracted_chars:
                remaining = max(0, self.max_extracted_chars - total_chars)
                page_text = page_text[:remaining]
                pages[page_num] = page_text
                full_text_parts.append(page_text)
                total_chars += len(page_text)
                break

            pages[page_num] = page_text
            full_text_parts.append(page_text)
            total_chars += len(page_text)

        full_text = "\n\n".join(full_text_parts).strip()
        if not full_text:
            return ParsedDocument(
                doc_url=doc_url,
                canonical_id=canonical_id,
                status=FullTextStatus.PARSE_FAILED,
                total_pages=len(reader.pages),
                error_message="PDF contains no extractable text (may be image-only scan).",
            )

        # 3. Detect scholarly sections with page provenance
        detected_sections = self.detect_sections(pages)

        doc = ParsedDocument(
            doc_url=doc_url,
            canonical_id=canonical_id,
            pages=pages,
            full_text=full_text,
            sections=detected_sections,
            status=FullTextStatus.AVAILABLE,
            total_pages=len(reader.pages),
            total_chars=total_chars,
        )

        if cache_key or doc_url:
            key = cache_key or f"{canonical_id or ''}:{doc_url}"
            self.cache.put_document(key, doc.model_dump())

        return doc

    def detect_sections(self, pages: Dict[int, str]) -> Dict[str, SectionExtractionResult]:
        """Conservative scholarly section boundary detection across page boundaries."""
        # Collate all lines with page number
        annotated_lines: List[Tuple[int, str]] = []
        for page_num in sorted(pages.keys()):
            for line in pages[page_num].splitlines():
                stripped = line.strip()
                if stripped:
                    annotated_lines.append((page_num, stripped))

        # Identify section header positions
        header_positions: List[Tuple[int, int, str]] = []  # (line_idx, page_num, section_name)
        for idx, (p_num, line) in enumerate(annotated_lines):
            # Short lines typically serve as headers (<= 80 chars)
            if len(line) <= 80:
                for pattern, sec_name in self.SECTION_PATTERNS:
                    if pattern.match(line):
                        header_positions.append((idx, p_num, sec_name))
                        break

        sections: Dict[str, SectionExtractionResult] = {}
        for h_idx, (start_line, start_page, sec_name) in enumerate(header_positions):
            # End boundary is either next header or end of document
            if h_idx + 1 < len(header_positions):
                end_line = header_positions[h_idx + 1][0]
                end_page = header_positions[h_idx + 1][1]
            else:
                end_line = len(annotated_lines)
                end_page = annotated_lines[-1][0] if annotated_lines else start_page

            content_lines = [annotated_lines[i][1] for i in range(start_line + 1, end_line)]
            content = "\n".join(content_lines).strip()

            if content and sec_name not in sections:
                sections[sec_name] = SectionExtractionResult(
                    section_name=sec_name,
                    content=content,
                    start_page=start_page,
                    end_page=end_page,
                    status="detected",
                )

        return sections


# Global default document fetcher
document_fetcher = ResearchDocumentFetcher()
