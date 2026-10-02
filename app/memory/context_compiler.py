"""Compile explicitly selected workspace graph objects into bounded model context."""

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ContextSelectionError
from app.db.models import WorkspaceEdgeModel, WorkspaceObjectModel, WorkspaceObjectProjectLinkModel


EXPANDABLE_CONTEXT_OBJECTS = {"context_bridge", "context_set", "conversation_branch", "conversation_turn"}
MAX_COMPILED_CONTEXT_CHARS = 40_000
MAX_COMPILED_OBJECTS = 200
# Model traits and AURA tool-provider capabilities share one workspace metadata
# field today. Split them before routing so tool namespaces are never required
# to appear in a model's capability list.
MODEL_ROUTING_CAPABILITIES = frozenset({"general", "code", "reasoning", "research", "fast", "local"})
CAPABILITY_ROUTING_FLAGS = {
    "tools": "requires_tools",
    "tool_calling": "requires_tools",
    "vision": "requires_vision",
    "structured_output": "requires_structured_output",
    "long_context": "requires_long_context",
}


def split_context_capabilities(capabilities: list[str]) -> tuple[list[str], list[str], dict[str, bool]]:
    """Separate model-routing constraints from abstract AURA tool capabilities."""
    model_capabilities: set[str] = set()
    tool_capabilities: set[str] = set()
    flags = {
        "requires_tools": False,
        "requires_vision": False,
        "requires_structured_output": False,
        "requires_long_context": False,
    }
    for capability in capabilities:
        if capability in CAPABILITY_ROUTING_FLAGS:
            flags[CAPABILITY_ROUTING_FLAGS[capability]] = True
        elif capability in MODEL_ROUTING_CAPABILITIES:
            model_capabilities.add(capability)
        else:
            tool_capabilities.add(capability)
    return sorted(model_capabilities), sorted(tool_capabilities), flags


PRIVACY_REQUIREMENT_ORDER = {"public": 0, "internal": 1, "confidential": 2, "local_only": 3}
BRIDGE_SECTION_LABELS = {
    "conclusions": "Conclusions",
    "observations": "Important observations",
    "failed": "Failed attempts",
    "artifacts": "Artifacts",
}


def stricter_privacy_requirement(current: str | None, required: str | None) -> str | None:
    """Return the stricter known policy without weakening an existing boundary."""
    if required is None:
        return current
    if current is None:
        return required
    if current not in PRIVACY_REQUIREMENT_ORDER or required not in PRIVACY_REQUIREMENT_ORDER:
        return current
    return max((current, required), key=PRIVACY_REQUIREMENT_ORDER.__getitem__)


class CompiledContextObject(BaseModel):
    object_id: str
    object_type: str
    selected_by_user: bool = False
    source_object_ids: list[str] = Field(default_factory=list)
    selected_sections: dict[str, bool | None] | None = None


class CompiledWorkspaceContext(BaseModel):
    project_name: str
    objects: list[CompiledContextObject] = Field(default_factory=list)
    estimated_tokens: int = 0
    prompt_text: str = ""
    privacy_requirement: str | None = None
    privacy_sources: list[dict[str, str]] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)
    requires_tools: bool = False
    requires_vision: bool = False
    requires_structured_output: bool = False
    requires_long_context: bool = False


class WorkspaceContextCompiler:
    """Resolve only requested objects and context-flow ancestry they explicitly include."""

    def __init__(self, db: AsyncSession, max_chars: int = MAX_COMPILED_CONTEXT_CHARS) -> None:
        self.db = db
        self.max_chars = max_chars

    async def compile(self, project_name: str, selected_ids: list[str]) -> CompiledWorkspaceContext:
        roots = list(dict.fromkeys(selected_ids))
        if not roots:
            return CompiledWorkspaceContext(project_name=project_name)
        if len(roots) > MAX_COMPILED_OBJECTS:
            raise ContextSelectionError(
                "Selected workspace context expands to too many linked objects. Narrow the selection and try again.",
                {"project_name": project_name, "object_limit": MAX_COMPILED_OBJECTS},
            )

        result = await self.db.execute(
            select(WorkspaceObjectModel).where(
                WorkspaceObjectModel.project_name == project_name,
                WorkspaceObjectModel.id.in_(roots),
            )
        )
        objects = {item.id: item for item in result.scalars()}
        linked_result = await self.db.execute(
            select(WorkspaceObjectModel)
            .join(WorkspaceObjectProjectLinkModel, WorkspaceObjectProjectLinkModel.object_id == WorkspaceObjectModel.id)
            .where(
                WorkspaceObjectModel.project_name.is_(None),
                WorkspaceObjectModel.object_type.in_({"manual_note", "file_reference", "study_session"}),
                WorkspaceObjectProjectLinkModel.project_name == project_name,
                WorkspaceObjectModel.id.in_(set(roots) - set(objects)),
            )
        )
        objects.update({item.id: item for item in linked_result.scalars()})
        if len(objects) != len(roots):
            raise ContextSelectionError(
                "One or more selected workspace objects were not found in this project.",
                {"project_name": project_name, "requested_count": len(roots)},
            )

        included = set(roots)
        linked_sources: dict[str, list[str]] = {}
        expandable = [object_id for object_id in roots if objects[object_id].object_type in EXPANDABLE_CONTEXT_OBJECTS]
        traversed_edges = 0
        while expandable:
            edge_result = await self.db.execute(
                select(WorkspaceEdgeModel)
                .where(
                    WorkspaceEdgeModel.project_name == project_name,
                    WorkspaceEdgeModel.edge_family == "context",
                    WorkspaceEdgeModel.target_object_id.in_(expandable),
                )
                .order_by(WorkspaceEdgeModel.created_at, WorkspaceEdgeModel.id)
                .limit(MAX_COMPILED_OBJECTS + 1)
            )
            edges = list(edge_result.scalars())
            traversed_edges += len(edges)
            if traversed_edges > MAX_COMPILED_OBJECTS:
                raise ContextSelectionError(
                    "Selected workspace context expands to too many linked objects. Narrow the selection and try again.",
                    {"project_name": project_name, "object_limit": MAX_COMPILED_OBJECTS},
                )
            candidate_ids = {edge.source_object_id for edge in edges if edge.source_object_id not in objects}
            if candidate_ids:
                source_result = await self.db.execute(
                    select(WorkspaceObjectModel).where(
                        WorkspaceObjectModel.id.in_(candidate_ids),
                        WorkspaceObjectModel.project_name == project_name,
                    )
                )
                objects.update({item.id: item for item in source_result.scalars()})
                linked_source_result = await self.db.execute(
                    select(WorkspaceObjectModel)
                    .join(WorkspaceObjectProjectLinkModel, WorkspaceObjectProjectLinkModel.object_id == WorkspaceObjectModel.id)
                    .where(
                        WorkspaceObjectModel.project_name.is_(None),
                        WorkspaceObjectModel.object_type.in_({"manual_note", "file_reference", "study_session"}),
                        WorkspaceObjectProjectLinkModel.project_name == project_name,
                        WorkspaceObjectModel.id.in_(candidate_ids - set(objects)),
                    )
                )
                objects.update({item.id: item for item in linked_source_result.scalars()})

            next_expandable: list[str] = []
            for edge in edges:
                source = objects.get(edge.source_object_id)
                # Ignore malformed/dangling cross-project links instead of exposing provenance.
                if source is None:
                    continue
                linked_sources.setdefault(edge.target_object_id, []).append(edge.source_object_id)
                # A bridge records its source links as provenance. Its handoff is
                # composed from the explicitly enabled, user-authored sections;
                # copying complete source objects would bypass that selection.
                if objects[edge.target_object_id].object_type == "context_bridge":
                    continue
                if edge.source_object_id in included:
                    continue
                included.add(source.id)
                if len(included) > MAX_COMPILED_OBJECTS:
                    raise ContextSelectionError(
                        "Selected workspace context expands to too many linked objects. Narrow the selection and try again.",
                        {"project_name": project_name, "object_limit": MAX_COMPILED_OBJECTS},
                    )
                if source.object_type in EXPANDABLE_CONTEXT_OBJECTS:
                    next_expandable.append(source.id)
            expandable = list(dict.fromkeys(next_expandable))

        # Provenance sources contribute privacy metadata and inspectable IDs,
        # but their content is not implicitly included as context. Walk the
        # provenance ancestry so a derived object cannot weaken its sources.
        provenance_sources: dict[str, list[str]] = {}
        provenance_source_ids: set[str] = set()
        provenance_frontier = set(included)
        provenance_visited: set[str] = set()
        while provenance_frontier:
            targets = provenance_frontier - provenance_visited
            if not targets:
                break
            provenance_visited.update(targets)
            provenance_edge_result = await self.db.execute(
                select(WorkspaceEdgeModel)
                .where(
                    WorkspaceEdgeModel.project_name == project_name,
                    WorkspaceEdgeModel.edge_family == "provenance",
                    WorkspaceEdgeModel.target_object_id.in_(targets),
                )
                .order_by(WorkspaceEdgeModel.created_at, WorkspaceEdgeModel.id)
                .limit(MAX_COMPILED_OBJECTS + 1)
            )
            provenance_edges = list(provenance_edge_result.scalars())
            if len(provenance_edges) > MAX_COMPILED_OBJECTS:
                raise ContextSelectionError(
                    "Selected workspace context expands to too many linked objects. Narrow the selection and try again.",
                    {"project_name": project_name, "object_limit": MAX_COMPILED_OBJECTS},
                )
            source_ids = {edge.source_object_id for edge in provenance_edges}
            if len(included | provenance_source_ids | source_ids) > MAX_COMPILED_OBJECTS:
                raise ContextSelectionError(
                    "Selected workspace context expands to too many linked objects. Narrow the selection and try again.",
                    {"project_name": project_name, "object_limit": MAX_COMPILED_OBJECTS},
                )
            missing_provenance_ids = source_ids - set(objects)
            if missing_provenance_ids:
                project_source_result = await self.db.execute(
                    select(WorkspaceObjectModel).where(
                        WorkspaceObjectModel.id.in_(missing_provenance_ids),
                        WorkspaceObjectModel.project_name == project_name,
                    )
                )
                objects.update({item.id: item for item in project_source_result.scalars()})
                linked_source_result = await self.db.execute(
                    select(WorkspaceObjectModel)
                    .join(WorkspaceObjectProjectLinkModel, WorkspaceObjectProjectLinkModel.object_id == WorkspaceObjectModel.id)
                    .where(
                        WorkspaceObjectModel.project_name.is_(None),
                        WorkspaceObjectModel.object_type.in_({"manual_note", "file_reference", "study_session"}),
                        WorkspaceObjectProjectLinkModel.project_name == project_name,
                        WorkspaceObjectModel.id.in_(missing_provenance_ids - set(objects)),
                    )
                )
                objects.update({item.id: item for item in linked_source_result.scalars()})

            next_frontier: set[str] = set()
            for edge in provenance_edges:
                if edge.source_object_id not in objects:
                    continue
                provenance_sources.setdefault(edge.target_object_id, []).append(edge.source_object_id)
                provenance_source_ids.add(edge.source_object_id)
                next_frontier.add(edge.source_object_id)
            if len(included | provenance_source_ids) > MAX_COMPILED_OBJECTS:
                raise ContextSelectionError(
                    "Selected workspace context expands to too many linked objects. Narrow the selection and try again.",
                    {"project_name": project_name, "object_limit": MAX_COMPILED_OBJECTS},
                )
            provenance_frontier = next_frontier - provenance_visited

        # Privacy classifications on selected objects and explicit provenance
        # sources strengthen the route boundary for this turn.
        privacy_requirement: str | None = None
        privacy_sources: list[dict[str, str]] = []
        required_capabilities: set[str] = set()
        capability_flags = {
            "requires_tools": False,
            "requires_vision": False,
            "requires_structured_output": False,
            "requires_long_context": False,
        }
        privacy_object_ids = set(included)
        privacy_object_ids.update(source_id for source_ids in linked_sources.values() for source_id in source_ids)
        privacy_object_ids.update(provenance_source_ids)
        for object_id in sorted(privacy_object_ids):
            workspace_object = objects[object_id]
            metadata = workspace_object.metadata_json or {}
            classification = metadata.get("privacy_policy")
            if classification is None and workspace_object.object_type == "conversation_turn":
                # Legacy transcript objects predate durable per-turn privacy metadata.
                classification = "local_only"
            if classification is not None and (
                not isinstance(classification, str) or classification not in PRIVACY_REQUIREMENT_ORDER
            ):
                raise ContextSelectionError(
                    "Selected workspace context has an unsupported privacy classification.",
                    {"object_id": object_id, "privacy_policy": classification if isinstance(classification, str) else "unknown"},
                )
            if isinstance(classification, str):
                privacy_requirement = stricter_privacy_requirement(privacy_requirement, classification)
                privacy_sources.append({"object_id": object_id, "privacy_policy": classification})
            if object_id not in included:
                continue
            object_capabilities = metadata.get("required_capabilities", [])
            if not isinstance(object_capabilities, list) or any(
                not isinstance(capability, str) or not capability.strip()
                for capability in object_capabilities
            ):
                raise ContextSelectionError(
                    "Selected workspace context has invalid capability requirements.",
                    {"object_id": object_id, "requirement": "required_capabilities"},
                )
            required_capabilities.update(capability.strip() for capability in object_capabilities)
            for key in capability_flags:
                value = metadata.get(key)
                if value is None:
                    continue
                if not isinstance(value, bool):
                    raise ContextSelectionError(
                        "Selected workspace context has invalid capability requirements.",
                        {"object_id": object_id, "requirement": key},
                    )
                capability_flags[key] = capability_flags[key] or value

        # Place explicitly linked sources before the bridges/sets that consume them.
        # Stable timestamp + id ordering resolves unrelated objects deterministically.
        ordered_ids: list[str] = []
        remaining = set(included)
        while remaining:
            ready = [
                object_id for object_id in remaining
                if not (set(linked_sources.get(object_id, [])) & remaining)
            ]
            if not ready:  # Defensive recovery if legacy data contains a context cycle.
                ready = list(remaining)
            ready.sort(key=lambda object_id: (objects[object_id].created_at, object_id))
            ordered_ids.extend(ready)
            remaining.difference_update(ready)
        ordered = [objects[object_id] for object_id in ordered_ids]
        rendered: list[str] = []
        manifest: list[CompiledContextObject] = []
        for item in ordered:
            content = item.content or ""
            section_selection: dict[str, bool] | None = None
            if item.object_type == "context_bridge":
                metadata = item.metadata_json or {}
                options = metadata.get("bridge_options")
                sections = metadata.get("bridge_sections")
                section_selection = (
                    {
                        key: options.get(key) if type(options.get(key)) is bool else None
                        for key in BRIDGE_SECTION_LABELS
                    }
                    if isinstance(options, dict)
                    else None
                )
                if isinstance(options, dict) and isinstance(sections, dict):
                    selected_content = [
                        f"{label}:\n{sections[key]}"
                        for key, label in BRIDGE_SECTION_LABELS.items()
                        if section_selection is not None and section_selection[key] is True
                        and isinstance(sections.get(key), str)
                        and sections[key].strip()
                    ]
                    if selected_content:
                        content = "\n\n".join(part for part in (content, *selected_content) if part)
            rendered.append(
                f"[Workspace object {item.id} | type: {item.object_type} | title: {item.title or '(untitled)'}]\n"
                f"{content}"
            )
            manifest.append(
                CompiledContextObject(
                    object_id=item.id,
                    object_type=item.object_type,
                    selected_by_user=item.id in roots,
                    source_object_ids=sorted(set(
                        linked_sources.get(item.id, []) + provenance_sources.get(item.id, [])
                    )),
                    selected_sections=section_selection,
                )
            )
        prompt_text = "\n\n".join(rendered)
        if len(prompt_text) > self.max_chars:
            raise ContextSelectionError(
                "Selected workspace context exceeds the per-turn size limit. Narrow the selection and try again.",
                {"project_name": project_name, "character_limit": self.max_chars},
            )

        return CompiledWorkspaceContext(
            project_name=project_name,
            objects=manifest,
            estimated_tokens=(len(prompt_text) + 3) // 4,
            prompt_text=prompt_text,
            privacy_requirement=privacy_requirement,
            privacy_sources=privacy_sources,
            required_capabilities=sorted(required_capabilities),
            **capability_flags,
        )
