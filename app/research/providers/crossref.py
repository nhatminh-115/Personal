"""Crossref REST API provider for scholarly bibliographic metadata."""

import asyncio
import re
import time
from typing import Any, Dict, List, Optional

import httpx

from app.core.settings import settings
from app.research.cache import research_cache
from app.research.dedup import compute_canonical_id, extract_doi
from app.research.models import ResearchSource, SourceStatus
from app.research.provider import ResearchProviderUnavailable, ResearchSourceProvider, retry_after_seconds


class CrossrefResearchProvider(ResearchSourceProvider):
    """Search Crossref works without retrieving abstracts or full text."""

    API_URL = "https://api.crossref.org/works"

    def __init__(
        self,
        timeout_seconds: Optional[float] = None,
        cache: Optional[Any] = None,
        max_retries: int = 2,
    ) -> None:
        self.timeout_seconds = timeout_seconds or settings.RESEARCH_HTTP_TIMEOUT_SECONDS
        self.cache = cache or research_cache
        self.max_retries = max(0, max_retries)

    async def _get_json(self, url: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Fetch JSON with bounded retries for transient Crossref failures."""
        retries = 0
        while retries <= self.max_retries:
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout_seconds, follow_redirects=False, verify=True
                ) as client:
                    response = await client.get(url, params=params, headers={
                        "Accept": "application/json",
                        "User-Agent": "AURA-Research-Specialist/1.0",
                    })
                if response.status_code == 200:
                    payload = response.json()
                    if isinstance(payload, dict):
                        return payload
                    raise ResearchProviderUnavailable("Crossref", "returned an invalid response")
                if response.status_code == 404:
                    return None
                if response.status_code == 429 or response.status_code >= 500:
                    retries += 1
                    reason = "rate limited" if response.status_code == 429 else "temporarily unavailable"
                    if retries > self.max_retries:
                        raise ResearchProviderUnavailable("Crossref", reason)
                    delay = retry_after_seconds(
                        response.headers.get("Retry-After") if response.status_code == 429 else None,
                        default=min(1.5 * (2 ** (retries - 1)), 8.0),
                        maximum=15.0,
                    )
                    await asyncio.sleep(delay)
                    continue
                if response.status_code >= 400:
                    raise ResearchProviderUnavailable(
                        "Crossref", f"rejected the request (HTTP {response.status_code})"
                    )
                raise ResearchProviderUnavailable("Crossref", "returned an invalid response")
            except ResearchProviderUnavailable:
                raise
            except httpx.TransportError:
                retries += 1
                if retries > self.max_retries:
                    raise ResearchProviderUnavailable("Crossref", "temporarily unavailable") from None
                await asyncio.sleep(min(1.0 * (2 ** (retries - 1)), 8.0))
            except (ValueError, TypeError):
                raise ResearchProviderUnavailable("Crossref", "returned an unreadable response") from None
        return None

    @staticmethod
    def _convert_item(item: Dict[str, Any]) -> Optional[ResearchSource]:
        if not isinstance(item, dict):
            return None
        title_value = item.get("title")
        title = title_value[0].strip() if isinstance(title_value, list) and title_value and isinstance(title_value[0], str) else ""
        if not title:
            return None

        doi = extract_doi(str(item.get("DOI") or ""))
        canonical_id = compute_canonical_id(title=title, metadata={"doi": doi})
        authors = []
        for author in item.get("author") or []:
            if not isinstance(author, dict):
                continue
            name = " ".join(str(author.get(part, "")).strip() for part in ("given", "family") if author.get(part))
            if name:
                authors.append(name)

        published = item.get("published-print") or item.get("published-online") or item.get("created") or {}
        date_parts = published.get("date-parts") if isinstance(published, dict) else None
        year = None
        if isinstance(date_parts, list) and date_parts and isinstance(date_parts[0], list) and date_parts[0]:
            value = date_parts[0][0]
            year = value if isinstance(value, int) else None

        url = f"https://doi.org/{doi}" if doi else None
        container = item.get("container-title")
        venue = container[0].strip() if isinstance(container, list) and container and isinstance(container[0], str) else None
        aliases = [f"doi:{doi}"] if doi else []
        if url:
            aliases.append(url)
        metadata = {
            "provider": "crossref",
            "doi": doi,
            "type": item.get("type"),
            "publisher": item.get("publisher"),
            "retrieved_timestamp": time.time(),
            "fixture": False,
        }
        return ResearchSource(
            source_id=f"crossref_{re.sub(r'[^a-z0-9]+', '_', doi)}" if doi else f"crossref_{canonical_id[-12:]}",
            canonical_id=canonical_id,
            title=title,
            authors=authors,
            year=year,
            url=url,
            venue=venue,
            status=SourceStatus.CANDIDATE,
            relevance_score=0.5,
            aliases=aliases,
            metadata=metadata,
        )

    async def search(self, query: str, search_type: str = "broad", max_results: int = 5) -> List[ResearchSource]:
        query = query.strip()
        if not query or max_results <= 0:
            return []
        params = {"query.bibliographic": query, "rows": min(max_results * 2, 20), "select": "DOI,title,author,published-print,published-online,created,container-title,type,publisher"}
        payload = await self._get_json(self.API_URL, params=params)

        message = payload.get("message") if isinstance(payload, dict) else None
        items = message.get("items") if isinstance(message, dict) else None
        if not isinstance(items, list):
            raise ResearchProviderUnavailable("Crossref", "returned an invalid search response")

        results = []
        for item in items:
            source = self._convert_item(item)
            if source is not None:
                self.cache.put_paper(source)
                results.append(source)
                if len(results) >= max_results:
                    break
        if items and not results:
            raise ResearchProviderUnavailable("Crossref", "returned no readable works in its search response")
        return results

    async def fetch_source(self, source_id: str) -> Optional[ResearchSource]:
        cached = self.cache.get_paper(source_id.strip())
        if cached:
            return cached
        doi = extract_doi(source_id)
        if not doi:
            return None
        payload = await self._get_json(f"{self.API_URL}/{doi}")
        if payload is None:
            return None

        message = payload.get("message") if isinstance(payload, dict) else None
        source = self._convert_item(message) if isinstance(message, dict) else None
        if source:
            self.cache.put_paper(source)
        return source

    async def fetch_section(self, source_id: str, section_name: str) -> Optional[str]:
        """Crossref is a bibliographic metadata source and does not supply section text."""
        return None
