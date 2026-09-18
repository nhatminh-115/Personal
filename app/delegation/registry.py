"""Registry for authorized specialist definitions in AURA."""

from typing import Dict, List, Optional
from app.delegation.types import SpecialistDefinition


class SpecialistRegistry:
    """Maintains definitions of authorized specialist agents."""

    def __init__(self) -> None:
        self._specialists: Dict[str, SpecialistDefinition] = {}
        # Register standard built-in specialists
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
                auto_approve_tools=["sandbox_shell_execute", "sandbox_python_execute"],
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
