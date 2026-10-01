"""Compile explicitly selected workspace graph objects into bounded model context."""

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ContextSelectionError
from app.db.models import WorkspaceEdgeModel, WorkspaceObjectModel


EXPANDABLE_CONTEXT_OBJECTS = {"context_bridge", "context_set", "conversation_branch"}
MAX_COMPILED_CONTEXT_CHARS = 40_000
MAX_COMPILED_OBJECTS = 200
BRIDGE_SECTION_LABELS = {
    "conclusions": "Conclusions",
    "observations": "Important observations",
    "failed": "Failed attempts",
    "artifacts": "Artifacts",
}


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


class WorkspaceContextCompiler:
    """Resolve only requested objects and context-flow ancestry they explicitly include."""

    def __init__(self, db: AsyncSession, max_chars: int = MAX_COMPILED_CONTEXT_CHARS) -> None:
        self.db = db
        self.max_chars = max_chars

    async def compile(self, project_name: str, selected_ids: list[str]) -> CompiledWorkspaceContext:
        roots = list(dict.fromkeys(selected_ids))
        if not roots:
            return CompiledWorkspaceContext(project_name=project_name)

        result = await self.db.execute(
            select(WorkspaceObjectModel).where(
                WorkspaceObjectModel.project_name == project_name,
                WorkspaceObjectModel.id.in_(roots),
            )
        )
        objects = {item.id: item for item in result.scalars()}
        if len(objects) != len(roots):
            raise ContextSelectionError(
                "One or more selected workspace objects were not found in this project.",
                {"project_name": project_name, "requested_count": len(roots)},
            )

        included = set(roots)
        linked_sources: dict[str, list[str]] = {}
        expandable = [object_id for object_id in roots if objects[object_id].object_type in EXPANDABLE_CONTEXT_OBJECTS]
        while expandable:
            edge_result = await self.db.execute(
                select(WorkspaceEdgeModel)
                .where(
                    WorkspaceEdgeModel.project_name == project_name,
                    WorkspaceEdgeModel.edge_family == "context",
                    WorkspaceEdgeModel.target_object_id.in_(expandable),
                )
                .order_by(WorkspaceEdgeModel.created_at, WorkspaceEdgeModel.id)
            )
            edges = list(edge_result.scalars())
            candidate_ids = {edge.source_object_id for edge in edges if edge.source_object_id not in objects}
            if candidate_ids:
                source_result = await self.db.execute(
                    select(WorkspaceObjectModel).where(
                        WorkspaceObjectModel.id.in_(candidate_ids),
                        WorkspaceObjectModel.project_name == project_name,
                    )
                )
                objects.update({item.id: item for item in source_result.scalars()})

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
                    source_object_ids=sorted(set(linked_sources.get(item.id, []))),
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
        )
