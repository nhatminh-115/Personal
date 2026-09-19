"""Registry for authorized specialist definitions in AURA."""

from typing import Dict, List, Optional
from app.delegation.types import SpecialistDefinition


class SpecialistRegistry:
    """Maintains definitions of authorized specialist agents."""

    def __init__(self) -> None:
        self._specialists: Dict[str, SpecialistDefinition] = {}
        self.register(
            SpecialistDefinition(
                name="coding",
                description="Specialist for inspecting code, running test suites in sandbox, diagnosing failures, modifying files, and validating fixes.",
                system_prompt_template=(
                    "You are AURA's dedicated Coding Specialist. "
                    "Your mission is to inspect the codebase, run tests, diagnose failures, "
                    "edit the appropriate files, re-run tests to verify the fix, and return a clear summary."
                ),
                allowed_tools=[
                    "read_workspace_file",
                    "write_workspace_file",
                    "list_workspace_files",
                    "sandbox_shell_execute",
                    "sandbox_python_execute",
                ],
                max_steps=10,
                timeout_seconds=120.0,
                preferred_model_capabilities=["code", "reasoning"],
            )
        )
        self.register(
            SpecialistDefinition(
                name="research",
                description=(
                    "Specialist for conducting literature reviews, prior art exploration, document inspection, "
                    "evidence extraction, citation tracking, and structured research synthesis."
                ),
                system_prompt_template=(
                    "You are AURA's dedicated Research Specialist. "
                    "Your mission is to rigorously investigate technical questions, discover prior art, "
                    "inspect full-text paper methods, extract verifiable evidence, and produce structured, evidence-backed syntheses.\n"
                    "Guidelines:\n"
                    "1. Issue search queries exploring mechanisms, related methods, and terminology.\n"
                    "2. Read full-text sections (especially Methods and Limitations) of closest candidate sources.\n"
                    "3. Extract concrete evidence with source and locator details.\n"
                    "4. Distinguish source-supported facts from specialist inference and hypotheses.\n"
                    "5. Store validated, high-value findings into project memory with citation references.\n"
                    "6. Return a comprehensive, evidence-backed conclusion with no fabricated citations."
                ),
                allowed_tools=[
                    "research_search",
                    "read_document_section",
                    "extract_evidence",
                    "record_research_claim",
                    "save_research_finding",
                    "read_workspace_file",
                ],
                max_steps=15,
                timeout_seconds=180.0,
                preferred_model_capabilities=["reasoning", "research", "long_context"],
            )
        )

    def register(self, definition: SpecialistDefinition) -> None:
        """Register a specialist definition."""
        self._specialists[definition.name] = definition

    def get(self, name: str) -> Optional[SpecialistDefinition]:
        """Retrieve specialist definition by name."""
        return self._specialists.get(name)

    def list_specialists(self) -> List[SpecialistDefinition]:
        """Return list of all registered specialist definitions."""
        return list(self._specialists.values())


# Global singleton specialist registry
specialist_registry = SpecialistRegistry()
