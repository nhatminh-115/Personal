"""Provider-neutral abstract interface for research literature retrieval."""

from abc import ABC, abstractmethod
from typing import List, Optional
from app.research.models import ResearchSource


class ResearchSourceProvider(ABC):
    """Abstract interface for external or deterministic research literature providers."""

    @abstractmethod
    def search(self, query: str, search_type: str = "broad", max_results: int = 5) -> List[ResearchSource]:
        """Search literature and return candidate research sources."""
        pass

    @abstractmethod
    def fetch_source(self, source_id: str) -> Optional[ResearchSource]:
        """Fetch a specific research source by identifier."""
        pass

    @abstractmethod
    def fetch_section(self, source_id: str, section_name: str) -> Optional[str]:
        """Fetch the text content of a specific paper section."""
        pass
