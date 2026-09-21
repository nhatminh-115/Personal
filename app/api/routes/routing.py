"""API endpoints for managing routing profiles and policies."""

import uuid
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.api.dependencies import get_db, get_model_router
from app.db.models import RoutingProfileModel, ProjectRoutingAssignmentModel
from app.models.routing_profile import RoutingProfile
from app.models.router import ModelRouter

router = APIRouter(prefix="/v1/routing", tags=["Routing"])


@router.get("/profiles", response_model=List[RoutingProfile])
async def list_routing_profiles(db: AsyncSession = Depends(get_db)):
    """List all available routing profiles."""
    result = await db.execute(select(RoutingProfileModel).order_by(RoutingProfileModel.name))
    profiles = result.scalars().all()
    
    # Also include the static System Balanced profile
    from app.models.routing_resolver import get_system_balanced_profile
    sys_profile = get_system_balanced_profile()
    
    ret = [sys_profile]
    for p in profiles:
        ret.append(RoutingProfile(**p.routes_json, id=p.id, name=p.name, version=p.version, is_active=p.is_active))
    return ret


@router.get("/profiles/{profile_id}", response_model=RoutingProfile)
async def get_routing_profile(profile_id: str, db: AsyncSession = Depends(get_db)):
    """Get a specific routing profile by ID."""
    if profile_id == "system-balanced":
        from app.models.routing_resolver import get_system_balanced_profile
        return get_system_balanced_profile()
        
    result = await db.execute(select(RoutingProfileModel).where(RoutingProfileModel.id == profile_id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Routing profile not found")
        
    return RoutingProfile(**profile.routes_json, id=profile.id, name=profile.name, version=profile.version, is_active=profile.is_active)


@router.post("/profiles", response_model=RoutingProfile, status_code=status.HTTP_201_CREATED)
async def create_routing_profile(profile: RoutingProfile, db: AsyncSession = Depends(get_db)):
    """Create a new routing profile."""
    if not profile.id:
        profile.id = str(uuid.uuid4())
        
    db_profile = RoutingProfileModel(
        id=profile.id,
        name=profile.name,
        version=profile.version,
        is_active=profile.is_active,
        routes_json=profile.model_dump(exclude={"id", "name", "version", "is_active"})
    )
    db.add(db_profile)
    await db.commit()
    return profile


@router.put("/profiles/{profile_id}", response_model=RoutingProfile)
async def update_routing_profile(profile_id: str, profile_update: RoutingProfile, db: AsyncSession = Depends(get_db)):
    """Update an existing routing profile."""
    if profile_id == "system-balanced":
        raise HTTPException(status_code=400, detail="Cannot modify the system balanced profile.")
        
    result = await db.execute(select(RoutingProfileModel).where(RoutingProfileModel.id == profile_id))
    db_profile = result.scalar_one_or_none()
    if not db_profile:
        raise HTTPException(status_code=404, detail="Routing profile not found")
        
    db_profile.name = profile_update.name
    db_profile.version = profile_update.version + 1
    db_profile.is_active = profile_update.is_active
    db_profile.routes_json = profile_update.model_dump(exclude={"id", "name", "version", "is_active"})
    
    await db.commit()
    
    profile_update.id = profile_id
    profile_update.version = db_profile.version
    return profile_update


@router.post("/assignments/{project_name}")
async def assign_profile_to_project(
    project_name: str, 
    profile_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Assign a specific routing profile to a project."""
    if profile_id != "system-balanced":
        result = await db.execute(select(RoutingProfileModel).where(RoutingProfileModel.id == profile_id))
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Routing profile not found")
            
    # Upsert project assignment
    result = await db.execute(select(ProjectRoutingAssignmentModel).where(ProjectRoutingAssignmentModel.project_name == project_name))
    assignment = result.scalar_one_or_none()
    
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
