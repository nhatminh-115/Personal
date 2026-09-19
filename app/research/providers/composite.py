"""Composite research provider orchestrating Semantic Scholar and arXiv with deduplication and PDF extraction."""

import asyncio
from typing import Any, Dict, List, Optional

from app.core.logging import logger
from app.research.cache import research_cache
from app.research.dedup import SourceDeduplicator, extract_arxiv_id
from app.research.document import FullTextStatus, document_fetcher
from app.research.models import ResearchSource
from app.research.provider import ResearchSourceProvider
from app.research.providers.arxiv import ArxivResearchProvider
from app.research.providers.semantic_scholar import SemanticScholarResearchProvider


class CompositeResearchProvider(ResearchSourceProvider):
    """Combines Semantic Scholar discovery and arXiv enrichment into a unified provider."""

    def __init__(
        self,
        s2_provider: Optional[SemanticScholarResearchProvider] = None,
        arxiv_provider: Optional[ArxivResearchProvider] = None,
        fetcher: Optional[Any] = None,
        cache: Optional[Any] = None,
    ) -> None:
        self.s2_provider = s2_provider or SemanticScholarResearchProvider()
        self.arxiv_provider = arxiv_provider or ArxivResearchProvider()
        self.fetcher = fetcher or document_fetcher
        self.cache = cache or research_cache

    async def search(self, query: str, search_type: str = "broad", max_results: int = 5) -> List[ResearchSource]:
        """Search across scholarly providers, enrich arXiv identifiers, and deduplicate."""
        # 1. Primary discovery via Semantic Scholar
        s2_sources: List[ResearchSource] = []
        try:
            s2_sources = await self.s2_provider.search(query, search_type=search_type, max_results=max_results)
        except Exception as e:
            logger.warning(f"Semantic Scholar search failed: {e}")

        # 2. Enrich arXiv-identified papers concurrently and fetch supplementary arXiv papers if needed
        supplementary_arxiv: List[ResearchSource] = []
        enrichment_tasks = []

        for src in s2_sources:
            arxiv_id = src.metadata.get("arxiv_id") or extract_arxiv_id(src.canonical_id)
            if arxiv_id:
                enrichment_tasks.append(self._enrich_from_arxiv(src, arxiv_id))

        if enrichment_tasks:
            await asyncio.gather(*enrichment_tasks, return_exceptions=True)

        # If Semantic Scholar returned few results, query arXiv directly
        if len(s2_sources) < max_results:
            try:
                supplementary_arxiv = await self.arxiv_provider.search(
                    query, search_type=search_type, max_results=max_results
                )
            except Exception as e:
                logger.warning(f"Direct arXiv search failed: {e}")

        # 3. Deduplicate and merge identities through SourceDeduplicator
        combined = s2_sources + supplementary_arxiv
        merged_sources_dict: Dict[str, ResearchSource] = {}
        SourceDeduplicator.deduplicate(combined, existing_sources=merged_sources_dict)

        # Normalize provider tracking
        results = list(merged_sources_dict.values())
        for s in results:
            provs = s.metadata.get("providers") or []
            orig_p = s.metadata.get("provider")
            if orig_p and orig_p not in provs:
                provs.append(orig_p)
            s.metadata["providers"] = provs
            s.metadata["fixture"] = False

        results.sort(key=lambda x: x.relevance_score, reverse=True)
        return results[:max_results]

    async def _enrich_from_arxiv(self, source: ResearchSource, arxiv_id: str) -> None:
        """Enrich a Semantic Scholar source with authoritative arXiv metadata and PDF linkage."""
        try:
            arxiv_src = await self.arxiv_provider.fetch_source(arxiv_id)
            if arxiv_src:
                # Merge PDF URL
                pdf_url = arxiv_src.metadata.get("pdf_url")
                if pdf_url:
                    source.metadata["pdf_url"] = pdf_url
                    source.metadata["open_access_pdf"] = pdf_url
                    source.metadata["full_text_status"] = FullTextStatus.AVAILABLE.value

                # Merge categories and authors
                if arxiv_src.metadata.get("categories"):
                    source.metadata["categories"] = arxiv_src.metadata["categories"]
                if arxiv_src.authors and len(arxiv_src.authors) > len(source.authors):
                    source.authors = arxiv_src.authors

                # Merge aliases
                for al in arxiv_src.aliases:
                    if al not in source.aliases:
                        source.aliases.append(al)

                provs = source.metadata.get("providers", ["semantic_scholar"])
                if "arxiv" not in provs:
                    provs.append("arxiv")
                source.metadata["providers"] = provs
        except Exception as e:
            logger.debug(f"arXiv enrichment failed for '{arxiv_id}': {e}")

    async def fetch_source(self, source_id: str) -> Optional[ResearchSource]:
        """Fetch source by identifier from appropriate provider."""
        source_id = source_id.strip()
        cached = self.cache.get_paper(source_id)
        if cached:
            return cached

        if "arxiv" in source_id.lower():
            src = await self.arxiv_provider.fetch_source(source_id)
            if src:
                return src

        # Fallback to Semantic Scholar
        src = await self.s2_provider.fetch_source(source_id)
        if src:
            return src

        # Secondary fallback to arXiv
        return await self.arxiv_provider.fetch_source(source_id)

    async def fetch_section(self, source_id: str, section_name: str) -> Optional[str]:
        """Fetch section text. If unavailable in metadata, attempts PDF full-text extraction."""
        src = await self.fetch_source(source_id)
        if not src:
            return None

        sec_name = section_name.strip().lower()
        if sec_name in src.sections:
            return src.sections[sec_name]

        # Check for extractable PDF
        pdf_url = src.metadata.get("pdf_url") or src.metadata.get("open_access_pdf")
        if not pdf_url and src.canonical_id.startswith("arxiv:"):
            norm_id = extract_arxiv_id(src.canonical_id)
            if norm_id:
                pdf_url = f"https://arxiv.org/pdf/{norm_id}.pdf"

        if not pdf_url:
            src.metadata["full_text_status"] = FullTextStatus.UNAVAILABLE.value
            return None

        # Retrieve and parse full-text PDF
        parsed_doc = await self.fetcher.fetch_and_parse(pdf_url, canonical_id=src.canonical_id)
        if parsed_doc.status == FullTextStatus.AVAILABLE:
            src.metadata["full_text_status"] = FullTextStatus.AVAILABLE.value
            for s_name, s_res in parsed_doc.sections.items():
                src.sections[s_name] = s_res.content
            self.cache.put_paper(src)
            return src.sections.get(sec_name)
        else:
            src.metadata["full_text_status"] = parsed_doc.status.value
            logger.info(f"Full-text extraction failed for '{src.title}': {parsed_doc.error_message}")
            return None
