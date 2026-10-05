"""Provider-neutral abstract interface for research literature retrieval."""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import math
from typing import List, Optional
from app.research.models import ResearchSource


class ResearchProviderUnavailable(RuntimeError):
    """A configured research source could not complete a request after bounded retries."""

    def __init__(self, provider: str, reason: str = "temporarily unavailable") -> None:
        self.provider = provider
        self.reason = reason
        super().__init__(f"{provider} is {reason}.")


class ResearchSearchUnavailable(RuntimeError):
    """No usable source list could be produced because one or more providers failed."""

    def __init__(self, failed_providers: list[str]) -> None:
        self.failed_providers = tuple(dict.fromkeys(failed_providers))
        providers = ", ".join(self.failed_providers)
        super().__init__(
            "No search results can be confirmed because these research providers "
            f"could not complete the search: {providers}. Check provider availability or configuration and retry."
        )


def retry_after_seconds(value: Optional[str], *, default: float, maximum: float) -> float:
    """Parse delta-seconds or an HTTP date and clamp the delay to a finite bound."""
    if not value:
        return default
    try:
        delay = float(value)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            delay = (retry_at - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return default
    if not math.isfinite(delay):
        return default
    return min(max(delay, 0.0), maximum)


class ResearchSourceProvider(ABC):
    """Abstract interface for external or deterministic research literature providers."""

    @abstractmethod
    async def search(self, query: str, search_type: str = "broad", max_results: int = 5) -> List[ResearchSource]:
        """Search literature and return candidate research sources."""
        pass

    @abstractmethod
    async def fetch_source(self, source_id: str) -> Optional[ResearchSource]:
        """Fetch a specific research source by identifier."""
        pass

    @abstractmethod
    async def fetch_section(self, source_id: str, section_name: str) -> Optional[str]:
        """Fetch the text content of a specific paper section."""
        pass
