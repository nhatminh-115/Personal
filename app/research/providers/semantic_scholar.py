"""Semantic Scholar Academic Graph API research provider."""

import asyncio
import random
import time
from typing import Any, Dict, List, Optional
import httpx

from app.core.logging import logger
from app.core.settings import settings
from app.research.cache import research_cache
from app.research.dedup import compute_canonical_id, extract_arxiv_id, extract_doi
from app.research.document import FullTextStatus
from app.research.models import ResearchSource, SourceStatus
from app.research.provider import ResearchSourceProvider


class SemanticScholarResearchProvider(ResearchSourceProvider):
    """Integrates Semantic Scholar Academic Graph API for scholarly paper discovery and metadata."""

    BASE_URL = "https://api.semanticscholar.org/graph/v1"
    DEFAULT_FIELDS = "paperId,title,abstract,year,authors,venue,externalIds,url,openAccessPdf,publicationDate,citationCount"

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        max_retries: int = 3,
        cache: Optional[Any] = None,
    ) -> None:
        self.api_key = api_key or settings.SEMANTIC_SCHOLAR_API_KEY
        self.timeout_seconds = timeout_seconds or settings.RESEARCH_HTTP_TIMEOUT_SECONDS
        self.max_retries = max_retries
        self.cache = cache or research_cache

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "AURA-Research-Specialist/1.0",
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    async def _request_with_retry(
        self,
        client: httpx.AsyncClient,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Executes GET request with bounded exponential backoff and Retry-After handling."""
        headers = self._get_headers()
        url = f"{self.BASE_URL}/{endpoint.lstrip('/')}"
        start_time = time.time()
        retries = 0

        while retries <= self.max_retries:
            try:
                resp = await client.get(url, params=params, headers=headers)
                duration = time.time() - start_time

                # Success
                if resp.status_code == 200:
                    logger.debug(
                        f"Semantic Scholar [{endpoint}] status=200 duration={duration:.2f}s retries={retries}"
                    )
                    return resp.json()

                # Rate Limit (429) -> respect Retry-After
                if resp.status_code == 429:
                    retries += 1
                    if retries > self.max_retries:
                        logger.warning(f"Semantic Scholar rate limit exceeded after {retries} retries: {endpoint}")
                        return None

                    retry_after = resp.headers.get("Retry-After")
                    try:
                        wait_seconds = float(retry_after) if retry_after else (1.5 * (2 ** retries) + random.uniform(0.1, 0.5))
                    except ValueError:
                        wait_seconds = 2.0
                    wait_seconds = min(wait_seconds, 15.0)  # Bound maximum pause
                    logger.info(f"Semantic Scholar 429 received. Backing off {wait_seconds:.2f}s (retry {retries}/{self.max_retries})")
                    await asyncio.sleep(wait_seconds)
                    continue

                # Transient server errors (5xx)
                if resp.status_code >= 500:
                    retries += 1
                    if retries > self.max_retries:
                        logger.warning(f"Semantic Scholar 5xx error ({resp.status_code}) after {retries} retries: {endpoint}")
                        return None
                    wait_seconds = 1.0 * (2 ** retries) + random.uniform(0.1, 0.5)
                    logger.info(f"Semantic Scholar {resp.status_code} received. Backing off {wait_seconds:.2f}s")
                    await asyncio.sleep(wait_seconds)
                    continue

                # Unrecoverable client errors (400, 404, etc.) -> do not retry
                logger.info(f"Semantic Scholar unrecoverable client error {resp.status_code} on {endpoint}")
                return None

            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                retries += 1
                if retries > self.max_retries:
                    logger.warning(f"Semantic Scholar network error after {retries} retries on {endpoint}: {exc}")
                    return None
                wait_seconds = 1.0 * (2 ** retries) + random.uniform(0.1, 0.5)
                logger.info(f"Semantic Scholar network issue ({exc}). Retrying in {wait_seconds:.2f}s")
                await asyncio.sleep(wait_seconds)
            except Exception as e:
                logger.warning(f"Semantic Scholar unexpected error on {endpoint}: {e}")
                return None

        return None

    def _convert_s2_item(self, item: Dict[str, Any]) -> Optional[ResearchSource]:
        """Maps Semantic Scholar paper payload to canonical ResearchSource."""
        if not item or not isinstance(item, dict):
            return None

        paper_id = item.get("paperId") or ""
        title = (item.get("title") or "").strip()
        if not title:
            return None

        external_ids = item.get("externalIds") or {}
        doi = external_ids.get("DOI")
        arxiv_raw = external_ids.get("ArXiv")
        arxiv_id = extract_arxiv_id(arxiv_raw) if arxiv_raw else None

        raw_url = item.get("url") or (f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else None)
        canonical_id = compute_canonical_id(
            title=title,
            url=raw_url,
            metadata={"doi": doi, "arxiv_id": arxiv_id},
        )

        # Parse authors
        authors = []
        for a in item.get("authors") or []:
            if isinstance(a, dict) and a.get("name"):
                authors.append(a["name"].strip())

        abstract = (item.get("abstract") or "").strip() or None
        sections = {}
        if abstract:
            sections["abstract"] = abstract

        open_access_info = item.get("openAccessPdf") or {}
        pdf_url = open_access_info.get("url") if isinstance(open_access_info, dict) else None

        if arxiv_id and not pdf_url:
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

        full_text_status = FullTextStatus.AVAILABLE.value if pdf_url else FullTextStatus.ABSTRACT_ONLY.value

        metadata: Dict[str, Any] = {
            "provider": "semantic_scholar",
            "semantic_scholar_id": paper_id,
            "doi": doi,
            "arxiv_id": arxiv_id,
            "external_ids": external_ids,
            "open_access_pdf": pdf_url,
            "pdf_url": pdf_url,
            "citation_count": item.get("citationCount", 0),
            "publication_date": item.get("publicationDate"),
            "full_text_status": full_text_status,
            "retrieved_timestamp": time.time(),
            "fixture": False,
        }

        aliases = [paper_id] if paper_id else []
        if arxiv_id:
            aliases.append(f"arxiv:{arxiv_id}")
            aliases.append(f"https://arxiv.org/abs/{arxiv_id}")
        if doi:
            aliases.append(f"doi:{doi}")

        source = ResearchSource(
            source_id=f"s2_{paper_id[:12]}" if paper_id else f"src_{canonical_id[:12]}",
            canonical_id=canonical_id,
            title=title,
            authors=authors,
            year=item.get("year"),
            url=item.get("url"),
            venue=item.get("venue"),
            abstract=abstract,
            sections=sections,
            status=SourceStatus.CANDIDATE,
            relevance_score=0.85,
            aliases=aliases,
            metadata=metadata,
        )

        self.cache.put_paper(source)
        return source

    async def search(self, query: str, search_type: str = "broad", max_results: int = 5) -> List[ResearchSource]:
        """Search papers on Semantic Scholar."""
        query = query.strip()
        if not query:
            return []

        params = {
            "query": query,
            "limit": min(max_results * 2, 20),  # Request extra to filter invalid entries
            "fields": self.DEFAULT_FIELDS,
        }

        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True, verify=False) as client:
            resp_data = await self._request_with_retry(client, "paper/search", params=params)

        if not resp_data or "data" not in resp_data:
            return []

        results: List[ResearchSource] = []
        for raw_item in resp_data.get("data", []):
            converted = self._convert_s2_item(raw_item)
            if converted:
                results.append(converted)
                if len(results) >= max_results:
                    break

        return results

    async def fetch_source(self, source_id: str) -> Optional[ResearchSource]:
        """Fetch full paper details from Semantic Scholar by paper ID or canonical ID."""
        source_id = source_id.strip()
        # Check cache first
        cached = self.cache.get_paper(source_id)
        if cached:
            return cached

        # If it's a prefixed ID like s2_<hash>
        target_id = source_id
        if target_id.startswith("s2_"):
            target_id = target_id[3:]

        params = {"fields": self.DEFAULT_FIELDS}
        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True, verify=False) as client:
            resp_data = await self._request_with_retry(client, f"paper/{target_id}", params=params)

        if not resp_data:
            return None

        return self._convert_s2_item(resp_data)

    async def fetch_section(self, source_id: str, section_name: str) -> Optional[str]:
        """Fetch section text. For Semantic Scholar, only abstract is directly in metadata."""
        src = await self.fetch_source(source_id)
        if not src:
            return None
        return src.sections.get(section_name.lower())
