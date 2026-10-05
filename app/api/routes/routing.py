"""API endpoints for managing routing profiles and policies."""

import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete as sa_delete, select, text, update

from app.api.dependencies import get_db, get_model_router
from app.db.models import RoutingProfileModel, ProjectRoutingAssignmentModel, SessionModel
from app.models.routing_profile import RoutingProfile, RouteConfig, ReasoningConfig
from app.models.routing_resolver import (
    get_system_balanced_profile,
    model_to_routing_profile,
    resolve_routing_profile,
    apply_routing_profile_to_context,
)
from app.models.router import ModelRouter
from app.models.base import RoutingContext

router = APIRouter(prefix="/v1/routing", tags=["Routing"])


class SessionAssignmentRequest(BaseModel):
    profile_id: Optional[str] = None


class DefaultProfileRequest(BaseModel):
    profile_id: Optional[str] = None


class RoutingPreviewRequest(BaseModel):
    context: Optional[RoutingContext] = None
    session_id: Optional[str] = None
    project_name: Optional[str] = None
    role: str = "root"
    message_override: Optional[str] = None
    reasoning_override: Optional[str] = None
    profile_draft: Optional[RoutingProfile] = None


class RoutingPreviewResponse(BaseModel):
    provider: str
    model: str
    reason: str
    reasoning_effort: Optional[str] = None
    profile_id: Optional[str] = None
    profile_name: str
    profile_version: int
    winning_scope: str
    privacy: str
    fallback: str
    role: str
    task_route: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)


async def _set_default_profile(db: AsyncSession, profile_id: Optional[str]) -> None:
    """Set the sole custom default, or clear custom defaults for System Balanced."""
    # Serialize all API default transitions across workers. The partial unique
    # index below the model is the final guard for writes outside this helper.
    if db.get_bind().dialect.name == "postgresql":
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": "aura:routing-profile-default"},
        )
    if profile_id and profile_id != "system-balanced":
        result = await db.execute(select(RoutingProfileModel).where(RoutingProfileModel.id == profile_id))
        profile = result.scalar_one_or_none()
        if profile is None:
            raise HTTPException(status_code=404, detail="Routing profile not found")
        if not profile.is_active:
            raise HTTPException(status_code=400, detail="An inactive routing profile cannot be the default.")
    await db.execute(update(RoutingProfileModel).values(is_default=False))
    if profile_id and profile_id != "system-balanced":
        await db.execute(
            update(RoutingProfileModel)
            .where(RoutingProfileModel.id == profile_id)
            .values(is_default=True)
        )


@router.get("/profiles", response_model=List[RoutingProfile])
async def list_routing_profiles(db: AsyncSession = Depends(get_db)):
    """List all available routing profiles."""
    result = await db.execute(select(RoutingProfileModel).order_by(RoutingProfileModel.name))
    profiles = result.scalars().all()
    
    ret = [get_system_balanced_profile()]
    for p in profiles:
        ret.append(model_to_routing_profile(p))
    return ret


@router.get("/profiles/{profile_id}", response_model=RoutingProfile)
async def get_routing_profile(profile_id: str, db: AsyncSession = Depends(get_db)):
    """Get a specific routing profile by ID."""
    if profile_id == "system-balanced":
        return get_system_balanced_profile()
        
    result = await db.execute(select(RoutingProfileModel).where(RoutingProfileModel.id == profile_id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Routing profile not found")
        
    return model_to_routing_profile(profile)


@router.post("/profiles", response_model=RoutingProfile, status_code=status.HTTP_201_CREATED)
async def create_routing_profile(profile: RoutingProfile, db: AsyncSession = Depends(get_db)):
    """Create a new routing profile (Requirement 18: single source of truth)."""
    if not profile.id:
        profile.id = str(uuid.uuid4())
        
    db_profile = RoutingProfileModel(
        id=profile.id,
        name=profile.name,
        version=profile.version,
        is_active=profile.is_active,
        is_default=False,
        global_privacy_policy=profile.global_privacy_policy.value if hasattr(profile.global_privacy_policy, "value") else str(profile.global_privacy_policy),
        global_fallback_policy=profile.global_fallback_policy.value if hasattr(profile.global_fallback_policy, "value") else str(profile.global_fallback_policy),
        cost_preference=profile.cost_preference,
        latency_preference=profile.latency_preference,
        routes_json={"routes": {k: v.model_dump(mode="json") for k, v in profile.routes.items()}},
    )
    db.add(db_profile)
    if profile.is_default:
        await db.flush()
        await _set_default_profile(db, profile.id)
    await db.commit()
    await db.refresh(db_profile)
    return model_to_routing_profile(db_profile)


@router.put("/profiles/{profile_id}", response_model=RoutingProfile)
async def update_routing_profile(profile_id: str, profile_update: RoutingProfile, db: AsyncSession = Depends(get_db)):
    """Update an existing routing profile (Requirements 17 & 18)."""
    if profile_id == "system-balanced":
        raise HTTPException(status_code=400, detail="Cannot modify the system balanced profile.")
        
    result = await db.execute(select(RoutingProfileModel).where(RoutingProfileModel.id == profile_id))
    db_profile = result.scalar_one_or_none()
    if not db_profile:
        raise HTTPException(status_code=404, detail="Routing profile not found")

    if profile_update.version != db_profile.version:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "RoutingProfileVersionConflict",
                "message": "Routing profile changed since it was loaded.",
                "current_version": db_profile.version,
            },
        )

    # Serialize default transitions before the compare-and-swap. The version
    # predicate below remains the authority for concurrent edits to this row.
    if profile_update.is_default:
        await _set_default_profile(db, profile_id)

    result = await db.execute(
        update(RoutingProfileModel)
        .where(
            RoutingProfileModel.id == profile_id,
            RoutingProfileModel.version == profile_update.version,
        )
        .values(
            version=RoutingProfileModel.version + 1,
            name=profile_update.name,
            is_active=profile_update.is_active,
            is_default=profile_update.is_default,
            global_privacy_policy=(
                profile_update.global_privacy_policy.value
                if hasattr(profile_update.global_privacy_policy, "value")
                else str(profile_update.global_privacy_policy)
            ),
            global_fallback_policy=(
                profile_update.global_fallback_policy.value
                if hasattr(profile_update.global_fallback_policy, "value")
                else str(profile_update.global_fallback_policy)
            ),
            cost_preference=profile_update.cost_preference,
            latency_preference=profile_update.latency_preference,
            routes_json={"routes": {key: value.model_dump(mode="json") for key, value in profile_update.routes.items()}},
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        await db.rollback()
        current_version = await db.scalar(
            select(RoutingProfileModel.version).where(RoutingProfileModel.id == profile_id)
        )
        if current_version is None:
            raise HTTPException(status_code=404, detail="Routing profile not found")
        raise HTTPException(
            status_code=409,
            detail={
                "code": "RoutingProfileVersionConflict",
                "message": "Routing profile changed since it was loaded.",
                "current_version": current_version,
            },
        )

    await db.commit()
    await db.refresh(db_profile)
    return model_to_routing_profile(db_profile)


@router.delete("/profiles/{profile_id}")
async def delete_routing_profile(profile_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a custom routing profile (Requirement 13)."""
    if profile_id == "system-balanced":
        raise HTTPException(status_code=400, detail="Cannot delete the system balanced profile.")
        
    result = await db.execute(select(RoutingProfileModel).where(RoutingProfileModel.id == profile_id))
    db_profile = result.scalar_one_or_none()
    if not db_profile:
        raise HTTPException(status_code=404, detail="Routing profile not found")

    # Assignments intentionally do not use foreign keys so profiles can be
    # portable across stores. Clear every reference in the same transaction
    # before deleting, so callers immediately inherit the next routing scope.
    await db.execute(
        sa_delete(ProjectRoutingAssignmentModel).where(
            ProjectRoutingAssignmentModel.routing_profile_id == profile_id
        )
    )
    await db.execute(
        update(SessionModel)
        .where(SessionModel.routing_profile_id == profile_id)
        .values(routing_profile_id=None)
    )
    await db.delete(db_profile)
    await db.commit()
    return {"status": "success", "deleted_profile_id": profile_id}


@router.post("/profiles/{profile_id}/duplicate", response_model=RoutingProfile, status_code=status.HTTP_201_CREATED)
async def duplicate_routing_profile(profile_id: str, db: AsyncSession = Depends(get_db)):
    """Duplicate a routing profile into a new independent version (Requirement 13)."""
    if profile_id == "system-balanced":
        source_profile = get_system_balanced_profile()
    else:
        result = await db.execute(select(RoutingProfileModel).where(RoutingProfileModel.id == profile_id))
        db_profile = result.scalar_one_or_none()
        if not db_profile:
            raise HTTPException(status_code=404, detail="Routing profile not found")
        source_profile = model_to_routing_profile(db_profile)
        
    new_id = str(uuid.uuid4())
    new_db_profile = RoutingProfileModel(
        id=new_id,
        name=f"{source_profile.name} (Copy)",
        version=1,
        is_active=True,
        is_default=False,
        global_privacy_policy=source_profile.global_privacy_policy.value,
        global_fallback_policy=source_profile.global_fallback_policy.value,
        cost_preference=source_profile.cost_preference,
        latency_preference=source_profile.latency_preference,
        routes_json={"routes": {k: v.model_dump(mode="json") for k, v in source_profile.routes.items()}},
    )
    db.add(new_db_profile)
    await db.commit()
    await db.refresh(new_db_profile)
    return model_to_routing_profile(new_db_profile)


@router.post("/profiles/{profile_id}/validate")
async def validate_routing_profile(profile_id: str, db: AsyncSession = Depends(get_db)):
    """Validate semantic consistency and reasoning bounds of a profile (Requirement 13)."""
    if profile_id == "system-balanced":
        profile = get_system_balanced_profile()
    else:
        result = await db.execute(select(RoutingProfileModel).where(RoutingProfileModel.id == profile_id))
        db_profile = result.scalar_one_or_none()
        if not db_profile:
            raise HTTPException(status_code=404, detail="Routing profile not found")
        try:
            profile = model_to_routing_profile(db_profile)
        except Exception as e:
            return {"valid": False, "profile_id": profile_id, "errors": [str(e)]}

    errors = []
    for r_name, r_cfg in profile.routes.items():
        if r_cfg.reasoning.policy == "adaptive":
            if not r_cfg.reasoning.min_effort or not r_cfg.reasoning.max_effort:
                errors.append(f"Route '{r_name}': adaptive policy requires min_effort and max_effort")

    return {"valid": len(errors) == 0, "profile_id": profile_id, "errors": errors}


@router.put("/default")
async def set_default_routing_profile(req: DefaultProfileRequest, db: AsyncSession = Depends(get_db)):
    """Atomically select the sole custom default or fall back to System Balanced."""
    await _set_default_profile(db, req.profile_id)
    await db.commit()
    return {
        "status": "success",
        "routing_profile_id": None if req.profile_id == "system-balanced" else req.profile_id,
    }


@router.get("/effective")
async def get_effective_routing(
    session_id: Optional[str] = Query(None),
    project_name: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Inspect the effectively resolved routing profile and winning scope (Requirement 13)."""
    profile, winning_scope = await resolve_routing_profile(db, session_id=session_id, project_name=project_name)
    return {
        "profile": profile,
        "winning_scope": winning_scope,
        "session_id": session_id,
        "project_name": project_name,
    }


@router.post("/preview", response_model=RoutingPreviewResponse)
async def preview_routing_decision(
    req: RoutingPreviewRequest,
    db: AsyncSession = Depends(get_db),
    router_instance: ModelRouter = Depends(get_model_router),
):
    """
    Simulate routing resolution using production policy paths without calling any model provider (Requirement 13).
    """
    profile, winning_scope = (
        (req.profile_draft, "draft")
        if req.profile_draft
        else await resolve_routing_profile(db, session_id=req.session_id, project_name=req.project_name)
    )
    ctx = req.context or RoutingContext(session_id=req.session_id)
    ctx = apply_routing_profile_to_context(
        profile=profile,
        role=req.role,
        context=ctx,
        winning_scope=winning_scope,
        message_override=req.message_override,
        reasoning_override=req.reasoning_override,
    )
    # Zero model invocation: select_model_for_task only
    _, selection = router_instance.select_model_for_task(ctx)
    warnings: List[str] = []
    selected_model = selection.model_name
    metadata = router_instance.get_provider_metadata(selection.provider_name)
    if metadata and metadata.reasoning_support.get(selected_model) in (None, "unknown"):
        warnings.append("Reasoning control metadata is unknown for the selected model.")
    return RoutingPreviewResponse(
        provider=selection.provider_name,
        model=selection.model_name,
        reason=selection.reason,
        reasoning_effort=selection.reasoning_effort_selected,
        profile_id=profile.id,
        profile_name=profile.name,
        profile_version=profile.version,
        winning_scope=winning_scope,
        privacy=ctx.privacy_requirement.value,
        fallback=ctx.fallback_policy.value,
        role=req.role,
        task_route=ctx.task_type or req.role,
        warnings=warnings,
    )


@router.post("/assignments/{project_name}")
async def assign_profile_to_project(
    project_name: str, 
    profile_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Assign a specific routing profile to a project (Requirement 15: Clean System Balanced reset)."""
    result = await db.execute(select(ProjectRoutingAssignmentModel).where(ProjectRoutingAssignmentModel.project_name == project_name))
    assignment = result.scalar_one_or_none()

    if profile_id == "system-balanced":
        # Requirement 15: Delete explicit assignment so resolver falls through naturally without DB FK violation
        if assignment:
            await db.delete(assignment)
            await db.commit()
        return {"status": "success", "project_name": project_name, "routing_profile_id": None}

    # Otherwise ensure target profile exists in DB
    prof_res = await db.execute(select(RoutingProfileModel).where(RoutingProfileModel.id == profile_id))
    if not prof_res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Routing profile not found")

    if assignment:
        assignment.routing_profile_id = profile_id
    else:
        assignment = ProjectRoutingAssignmentModel(project_name=project_name, routing_profile_id=profile_id)
        db.add(assignment)
        
    await db.commit()
    return {"status": "success", "project_name": project_name, "routing_profile_id": profile_id}


@router.get("/assignments/{project_name}")
async def get_project_assignment(project_name: str, db: AsyncSession = Depends(get_db)):
    """Get the routing profile assigned to a project."""
    result = await db.execute(select(ProjectRoutingAssignmentModel).where(ProjectRoutingAssignmentModel.project_name == project_name))
    assignment = result.scalar_one_or_none()
    
    if not assignment:
        return {"project_name": project_name, "routing_profile_id": None}
    
    return {"project_name": project_name, "routing_profile_id": assignment.routing_profile_id}


@router.put("/sessions/{session_id}")
async def assign_profile_to_session(
    session_id: str,
    req: SessionAssignmentRequest,
    db: AsyncSession = Depends(get_db)
):
    """Assign or reset a routing profile on a specific session (Requirements 12 & 15)."""
    s_res = await db.execute(select(SessionModel).where(SessionModel.id == session_id))
    session_obj = s_res.scalar_one_or_none()
    if not session_obj:
        raise HTTPException(status_code=404, detail="Session not found")

    if not req.profile_id or req.profile_id == "system-balanced":
        session_obj.routing_profile_id = None
    else:
        prof_res = await db.execute(select(RoutingProfileModel).where(RoutingProfileModel.id == req.profile_id))
        if not prof_res.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Routing profile not found")
        session_obj.routing_profile_id = req.profile_id

    await db.commit()
    return {"status": "success", "session_id": session_id, "routing_profile_id": session_obj.routing_profile_id}


@router.get("/sessions/{session_id}")
async def get_session_assignment(session_id: str, db: AsyncSession = Depends(get_db)):
    """Get the routing profile assigned to a session (Requirement 12)."""
    s_res = await db.execute(select(SessionModel).where(SessionModel.id == session_id))
    session_obj = s_res.scalar_one_or_none()
    if not session_obj:
        raise HTTPException(status_code=404, detail="Session not found")
        
    return {"session_id": session_id, "routing_profile_id": session_obj.routing_profile_id}
