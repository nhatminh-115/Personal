"""Factory for resolving the active research source provider based on runtime configuration."""

from typing import Optional

from app.core.logging import logger
from app.core.settings import settings
from app.research.corpus import DeterministicResearchProvider, corpus_engine
from app.research.provider import ResearchSourceProvider
from app.research.providers.composite import CompositeResearchProvider


def create_research_provider(mode: Optional[str] = None) -> ResearchSourceProvider:
    """Create and return the active ResearchSourceProvider.
    
    Modes:
    - 'deterministic': Offline indexed fixture corpus for deterministic testing & CI.
    - 'live': Real scholarly network provider combining Semantic Scholar and arXiv.
    """
    effective_mode = mode or getattr(settings, "RESEARCH_PROVIDER_MODE", "deterministic")
    if effective_mode == "live":
        logger.info("Initializing Live CompositeResearchProvider (Semantic Scholar + arXiv)")
        return CompositeResearchProvider()

    logger.debug("Using DeterministicResearchProvider (Offline Fixtures)")
    return corpus_engine


def get_default_research_provider() -> ResearchSourceProvider:
    """Convenience getter for the default configured research provider."""
    return create_research_provider()
