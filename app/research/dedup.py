"""Canonical source deduplication and identification for research literature."""

import hashlib
import re
from typing import Any, Dict, List, Optional
from app.research.models import ResearchSource


def normalize_title(title: str) -> str:
    """Normalize paper or document title for fuzzy and exact deduplication."""
    if not title:
        return ""
    # Lowercase
    text = title.lower()
    # Replace non-alphanumeric characters with spaces
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    # Collapse multiple whitespaces
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_arxiv_id(text: str) -> Optional[str]:
    """Extract standard arXiv identifier from title, URL, or metadata string."""
    if not text:
        return None
    # Pattern for new arXiv identifiers: YYMM.NNNNN(vN)? or old: arch-ive/YYMMNNN
    match = re.search(r"(\d{4}\.\d{4,5}(?:v\d+)?)|([a-z\-]+(?:\.[a-z]{2})?/\d{7}(?:v\d+)?)", text, re.IGNORECASE)
    if match:
        raw_id = match.group(0).lower()
        # Strip version suffix (e.g. v1, v2) for canonical identity
        return re.sub(r"v\d+$", "", raw_id)
    return None


def extract_doi(text: str) -> Optional[str]:
    """Extract DOI string from text or URL."""
    if not text:
        return None
    match = re.search(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", text)
    if match:
        doi = match.group(0).strip(".;() ").lower()
        return doi
    return None


def compute_canonical_id(
    title: str,
    url: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """Compute deterministic canonical identifier for a research source.
    Priority: DOI > arXiv ID > normalized URL > normalized title hash.
    """
    meta = metadata or {}
    candidates = [
        meta.get("doi"),
        url,
        meta.get("arxiv_id"),
        title,
    ]

    # 1. Try DOI
    for cand in candidates:
        if cand:
            doi = extract_doi(str(cand))
            if doi:
                return f"doi:{doi}"

    # 2. Try arXiv ID
    for cand in candidates:
        if cand:
            arx = extract_arxiv_id(str(cand))
            if arx:
                return f"arxiv:{arx}"

    # 3. Try Canonical URL (if clean publisher / paper link)
    if url:
        clean_url = url.split("?")[0].rstrip("/").lower()
        # If url has recognizable document paths
        if any(d in clean_url for d in ["arxiv.org", "openreview.net", "acm.org", "ieee.org", "semanticscholar.org"]):
            return f"url:{clean_url}"

    # 4. Fallback to Normalized Title Hash
    norm = normalize_title(title)
    if norm:
        title_hash = hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]
        return f"title:{title_hash}"

    return f"unknown:{hashlib.sha256(str(title).encode('utf-8')).hexdigest()[:16]}"


class SourceDeduplicator:
    """Detects and merges duplicate candidate research sources across multiple engines."""

    @staticmethod
    def deduplicate(
        new_sources: List[ResearchSource],
        existing_sources: Dict[str, ResearchSource],
    ) -> List[ResearchSource]:
        """Deduplicate incoming sources against existing sources and each other.
        Updates existing sources in-place with merged aliases and richer content.
        Returns the list of genuinely distinct new sources.
        """
        # Map canonical_id -> ResearchSource in existing collection
        canonical_map: Dict[str, ResearchSource] = {
            s.canonical_id: s for s in existing_sources.values() if s.canonical_id
        }
        # Also map normalized titles for fallback match
        title_map: Dict[str, ResearchSource] = {
            normalize_title(s.title): s for s in existing_sources.values() if normalize_title(s.title)
        }

        distinct_new: List[ResearchSource] = []

        for candidate in new_sources:
            norm_title = normalize_title(candidate.title)
            # Ensure candidate has canonical_id
            if not candidate.canonical_id:
                candidate.canonical_id = compute_canonical_id(candidate.title, candidate.url, candidate.metadata)

            existing_match: Optional[ResearchSource] = None
            if candidate.canonical_id in canonical_map:
                existing_match = canonical_map[candidate.canonical_id]
            elif norm_title and norm_title in title_map:
                existing_match = title_map[norm_title]

            if existing_match:
                # Merge candidate into existing match
                if candidate.url and candidate.url != existing_match.url and candidate.url not in existing_match.aliases:
                    existing_match.aliases.append(candidate.url)
                for alias in candidate.aliases:
                    if alias not in existing_match.aliases and alias != existing_match.url:
                        existing_match.aliases.append(alias)
                # Merge sections
                for sec_name, sec_content in candidate.sections.items():
                    if sec_name not in existing_match.sections or len(sec_content) > len(existing_match.sections[sec_name]):
                        existing_match.sections[sec_name] = sec_content
                # Update abstract if richer
                if candidate.abstract and (not existing_match.abstract or len(candidate.abstract) > len(existing_match.abstract)):
                    existing_match.abstract = candidate.abstract
                # Merge authors
                if candidate.authors:
                    for author in candidate.authors:
                        if author not in existing_match.authors:
                            existing_match.authors.append(author)
                # Merge metadata
                if candidate.metadata:
                    for k, v in candidate.metadata.items():
                        if k not in existing_match.metadata:
                            existing_match.metadata[k] = v
                if candidate.year and not existing_match.year:
                    existing_match.year = candidate.year
            else:
                # Genuinely new distinct source
                canonical_map[candidate.canonical_id] = candidate
                if norm_title:
                    title_map[norm_title] = candidate
                existing_sources[candidate.source_id] = candidate
                distinct_new.append(candidate)

        return distinct_new
