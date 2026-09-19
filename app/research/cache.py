"""Conservative local cache for external scholarly metadata, downloaded documents, and parsed sections.

Maintains strict architectural separation:
- Research Cache: caches retrievable external raw artifacts (metadata, PDF text, detected sections).
- Project Memory: stores validated domain findings and grounded claims.
"""

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional
from app.core.logging import logger
from app.research.models import ResearchSource


class ResearchCache:
    """Local caching layer for external research providers to prevent redundant network I/O."""

    def __init__(self, cache_dir: Optional[Path] = None) -> None:
        self.cache_dir = cache_dir or Path("./.research_cache").resolve()
        self._memory_papers: Dict[str, ResearchSource] = {}
        self._memory_docs: Dict[str, Dict[str, Any]] = {}
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning(f"Could not initialize disk research cache directory '{self.cache_dir}': {e}")

    def _hash_key(self, key: str) -> str:
        return hashlib.sha256(key.strip().lower().encode("utf-8")).hexdigest()

    def get_paper(self, canonical_id: str) -> Optional[ResearchSource]:
        """Retrieve cached paper metadata by canonical identifier."""
        if not canonical_id:
            return None
        norm_id = canonical_id.strip().lower()
        if norm_id in self._memory_papers:
            return self._memory_papers[norm_id].model_copy(deep=True)

        disk_file = self.cache_dir / f"paper_{self._hash_key(norm_id)}.json"
        if disk_file.exists():
            try:
                data = json.loads(disk_file.read_text(encoding="utf-8"))
                source = ResearchSource(**data)
                self._memory_papers[norm_id] = source
                return source.model_copy(deep=True)
            except Exception as e:
                logger.warning(f"Failed to read disk cache for paper '{canonical_id}': {e}")
        return None

    def put_paper(self, source: ResearchSource) -> None:
        """Store paper metadata in cache."""
        if not source or not source.canonical_id:
            return
        norm_id = source.canonical_id.strip().lower()
        self._memory_papers[norm_id] = source.model_copy(deep=True)
        if source.source_id:
            self._memory_papers[source.source_id.strip().lower()] = source.model_copy(deep=True)

        disk_file = self.cache_dir / f"paper_{self._hash_key(norm_id)}.json"
        try:
            disk_file.write_text(source.model_dump_json(indent=2), encoding="utf-8")
        except Exception as e:
            logger.debug(f"Failed writing disk cache for paper '{source.canonical_id}': {e}")

    def get_document(self, doc_url_or_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve cached parsed document text, pages, and section extractions."""
        if not doc_url_or_id:
            return None
        norm_key = doc_url_or_id.strip()
        if norm_key in self._memory_docs:
            return dict(self._memory_docs[norm_key])

        disk_file = self.cache_dir / f"doc_{self._hash_key(norm_key)}.json"
        if disk_file.exists():
            try:
                data = json.loads(disk_file.read_text(encoding="utf-8"))
                self._memory_docs[norm_key] = data
                return dict(data)
            except Exception as e:
                logger.warning(f"Failed reading document cache for '{doc_url_or_id}': {e}")
        return None

    def put_document(self, doc_url_or_id: str, doc_data: Dict[str, Any]) -> None:
        """Store parsed document text and sections in cache."""
        if not doc_url_or_id:
            return
        norm_key = doc_url_or_id.strip()
        self._memory_docs[norm_key] = dict(doc_data)

        disk_file = self.cache_dir / f"doc_{self._hash_key(norm_key)}.json"
        try:
            disk_file.write_text(json.dumps(doc_data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.debug(f"Failed writing document cache for '{doc_url_or_id}': {e}")

    def clear(self) -> None:
        """Clear all in-memory cached entries."""
        self._memory_papers.clear()
        self._memory_docs.clear()


# Default singleton cache
research_cache = ResearchCache()
