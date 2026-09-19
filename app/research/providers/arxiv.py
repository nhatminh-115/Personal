"""Official arXiv API research provider with rate limiting and PDF linkage."""

import asyncio
import re
import time
from typing import Any, Callable, Dict, List, Optional
import xml.etree.ElementTree as ET
import httpx

from app.core.logging import logger
from app.core.settings import settings
from app.research.cache import research_cache
from app.research.dedup import extract_arxiv_id
from app.research.document import FullTextStatus, document_fetcher
from app.research.models import ResearchSource, SourceStatus
from app.research.provider import ResearchSourceProvider


class ArxivRateLimiter:
    """Enforces cooperative spacing between consecutive arXiv API requests."""

    def __init__(
        self,
        min_interval_seconds: float = 3.0,
        time_func: Callable[[], float] = time.time,
        sleep_func: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        self.min_interval = min_interval_seconds
        self.time_func = time_func
        self.sleep_func = sleep_func
        self._last_request_time = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until minimum interval has passed since previous request."""
        async with self._lock:
            now = self.time_func()
            elapsed = now - self._last_request_time
            if elapsed < self.min_interval:
                wait_time = self.min_interval - elapsed
                await self.sleep_func(wait_time)
            self._last_request_time = self.time_func()


class ArxivResearchProvider(ResearchSourceProvider):
    """Integrates official arXiv metadata API and document retrieval."""

    API_URL = "https://export.arxiv.org/api/query"
    ATOM_NS = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }

    def __init__(
        self,
        rate_limiter: Optional[ArxivRateLimiter] = None,
        timeout_seconds: Optional[float] = None,
        cache: Optional[Any] = None,
    ) -> None:
        self.rate_limiter = rate_limiter or ArxivRateLimiter(settings.ARXIV_MIN_REQUEST_INTERVAL_SECONDS)
        self.timeout_seconds = timeout_seconds or settings.RESEARCH_HTTP_TIMEOUT_SECONDS
        self.cache = cache or research_cache

    def _clean_text(self, text: Optional[str]) -> str:
        """Normalize line breaks and multiple whitespace."""
        if not text:
            return ""
        return re.sub(r"\s+", " ", text).strip()

    def _parse_entry(self, entry: ET.Element) -> Optional[ResearchSource]:
        """Convert an arXiv Atom <entry> XML element to a canonical ResearchSource."""
        id_elem = entry.find("atom:id", self.ATOM_NS)
        if id_elem is None or not id_elem.text:
            return None

        raw_id_text = id_elem.text.strip()
        norm_arxiv_id = extract_arxiv_id(raw_id_text)
        if not norm_arxiv_id:
            # Fallback to last path segment if extract_arxiv_id failed
            norm_arxiv_id = raw_id_text.split("/")[-1].split("v")[0]

        title_elem = entry.find("atom:title", self.ATOM_NS)
        title = self._clean_text(title_elem.text if title_elem is not None else "")
        if not title:
            return None

        summary_elem = entry.find("atom:summary", self.ATOM_NS)
        abstract = self._clean_text(summary_elem.text if summary_elem is not None else "")

        # Extract authors
        authors = []
        for author_elem in entry.findall("atom:author", self.ATOM_NS):
            name_elem = author_elem.find("atom:name", self.ATOM_NS)
            if name_elem is not None and name_elem.text:
                authors.append(name_elem.text.strip())

        # Extract publication year
        year = None
        pub_elem = entry.find("atom:published", self.ATOM_NS)
        if pub_elem is not None and pub_elem.text and len(pub_elem.text) >= 4:
            try:
                year = int(pub_elem.text[:4])
            except ValueError:
                pass

        # Extract links (abstract URL and direct PDF URL)
        pdf_url = None
        abs_url = f"https://arxiv.org/abs/{norm_arxiv_id}"
        for link in entry.findall("atom:link", self.ATOM_NS):
            if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
                pdf_url = link.attrib.get("href")
            elif link.attrib.get("rel") == "alternate":
                abs_url = link.attrib.get("href", abs_url)

        if not pdf_url:
            pdf_url = f"https://arxiv.org/pdf/{norm_arxiv_id}.pdf"

        # Extract categories
        categories = []
        for cat in entry.findall("atom:category", self.ATOM_NS):
            term = cat.attrib.get("term")
            if term:
                categories.append(term)

        canonical_id = f"arxiv:{norm_arxiv_id}"
        source_id = f"arxiv_{norm_arxiv_id.replace('.', '_')}"

        sections = {}
        if abstract:
            sections["abstract"] = abstract

        metadata: Dict[str, Any] = {
            "provider": "arxiv",
            "arxiv_id": norm_arxiv_id,
            "pdf_url": pdf_url,
            "open_access_pdf": pdf_url,
            "categories": categories,
            "published": pub_elem.text if pub_elem is not None else None,
            "full_text_status": FullTextStatus.AVAILABLE.value,
            "retrieved_timestamp": time.time(),
            "fixture": False,
        }

        aliases = [
            canonical_id,
            raw_id_text,
            abs_url,
            f"https://arxiv.org/abs/{norm_arxiv_id}",
            f"https://arxiv.org/pdf/{norm_arxiv_id}.pdf",
        ]

        source = ResearchSource(
            source_id=source_id,
            canonical_id=canonical_id,
            title=title,
            authors=authors,
            year=year,
            url=abs_url,
            venue="arXiv preprint",
            abstract=abstract,
            sections=sections,
            status=SourceStatus.CANDIDATE,
            relevance_score=0.88,
            aliases=aliases,
            metadata=metadata,
        )

        self.cache.put_paper(source)
        return source

    async def _execute_arxiv_request(self, params: Dict[str, Any]) -> Optional[str]:
        """Execute request against arXiv API with strict rate limiting and retries."""
        await self.rate_limiter.acquire()
        headers = {"User-Agent": "AURA-Research-Specialist/1.0 (academic; polite)"}

        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True) as client:
                    resp = await client.get(self.API_URL, params=params, headers=headers)
                    if resp.status_code == 200:
                        return resp.text
                    elif resp.status_code in (429, 503):
                        logger.warning(f"arXiv API {resp.status_code}. Backing off on attempt {attempt + 1}")
                        await asyncio.sleep(3.0 * (attempt + 1))
                    else:
                        logger.warning(f"arXiv API unrecoverable status {resp.status_code}")
                        return None
            except Exception as e:
                logger.warning(f"arXiv API connection error: {e}")
                await asyncio.sleep(2.0)

        return None

    async def search(self, query: str, search_type: str = "broad", max_results: int = 5) -> List[ResearchSource]:
        """Search arXiv by query terms."""
        query = query.strip()
        if not query:
            return []

        # Sanitize query for arXiv search_query syntax
        sanitized = re.sub(r"[^\w\s\-]", " ", query)
        terms = [t for t in sanitized.split() if len(t) > 1]
        formatted_query = f"all:{'+'.join(terms[:6])}"

        params = {
            "search_query": formatted_query,
            "start": 0,
            "max_results": max_results,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }

        xml_data = await self._execute_arxiv_request(params)
        if not xml_data:
            return []

        try:
            root = ET.fromstring(xml_data)
        except ET.ParseError as e:
            logger.warning(f"Failed parsing arXiv XML response: {e}")
            return []

        results: List[ResearchSource] = []
        for entry in root.findall("atom:entry", self.ATOM_NS):
            parsed = self._parse_entry(entry)
            if parsed:
                results.append(parsed)

        return results

    async def fetch_source(self, source_id: str) -> Optional[ResearchSource]:
        """Fetch an individual paper from arXiv by arXiv ID or canonical ID."""
        source_id = source_id.strip()
        cached = self.cache.get_paper(source_id)
        if cached:
            return cached

        norm_id = extract_arxiv_id(source_id) or source_id
        if norm_id.startswith("arxiv:"):
            norm_id = norm_id[6:]

        params = {
            "id_list": norm_id,
            "max_results": 1,
        }

        xml_data = await self._execute_arxiv_request(params)
        if not xml_data:
            return None

        try:
            root = ET.fromstring(xml_data)
            entry = root.find("atom:entry", self.ATOM_NS)
            if entry is not None:
                return self._parse_entry(entry)
        except ET.ParseError as e:
            logger.warning(f"Failed parsing arXiv entry for '{source_id}': {e}")

        return None

    async def fetch_section(self, source_id: str, section_name: str) -> Optional[str]:
        """Fetch section text. If not already in metadata, retrieves PDF and parses."""
        src = await self.fetch_source(source_id)
        if not src:
            return None

        sec_name = section_name.strip().lower()
        if sec_name in src.sections:
            return src.sections[sec_name]

        pdf_url = src.metadata.get("pdf_url") or src.metadata.get("open_access_pdf")
        if not pdf_url and src.canonical_id.startswith("arxiv:"):
            arxiv_num = src.canonical_id[6:]
            pdf_url = f"https://arxiv.org/pdf/{arxiv_num}.pdf"

        if not pdf_url:
            return None

        parsed_doc = await document_fetcher.fetch_and_parse(pdf_url, canonical_id=src.canonical_id)
        if parsed_doc.status == FullTextStatus.AVAILABLE:
            for s_name, s_res in parsed_doc.sections.items():
                src.sections[s_name] = s_res.content
            self.cache.put_paper(src)
            return src.sections.get(sec_name)

        return None
