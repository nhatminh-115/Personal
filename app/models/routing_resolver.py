"""Scope resolution and precedence for AURA routing policies."""

from typing import Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models import SessionModel, ProjectRoutingAssignmentModel, RoutingProfileModel
from app.models.base import RoutingContext, PrivacyPolicy, FallbackPolicy, ReasoningEffort, ReasoningPolicy
from app.models.routing_profile import RoutingProfile, RouteConfig
from app.core.errors import InvalidRoutingProfile

import json


def get_system_balanced_profile() -> RoutingProfile:
    """Returns the code-defined safe fallback 'System Balanced' profile."""
    return RoutingProfile(
        id="system-balanced",
        name="System Balanced",
        version=1,
        global_privacy_policy=PrivacyPolicy.PUBLIC,
        global_fallback_policy=FallbackPolicy.CLOUD_ALLOWED,
        routes={
            "root": RouteConfig(
                reasoning={"policy": ReasoningPolicy.ADAPTIVE, "effort": ReasoningEffort.LOW, "min_effort": ReasoningEffort.LOW, "max_effort": ReasoningEffort.MEDIUM}
            ),
            "research": RouteConfig(
                reasoning={"policy": ReasoningPolicy.ADAPTIVE, "effort": ReasoningEffort.MEDIUM, "min_effort": ReasoningEffort.MEDIUM, "max_effort": ReasoningEffort.HIGH}
            ),
            "coding": RouteConfig(
                reasoning={"policy": ReasoningPolicy.ADAPTIVE, "effort": ReasoningEffort.MEDIUM, "min_effort": ReasoningEffort.MEDIUM, "max_effort": ReasoningEffort.HIGH}
            ),
            "writing": RouteConfig(
                reasoning={"policy": ReasoningPolicy.ADAPTIVE, "effort": ReasoningEffort.LOW, "min_effort": ReasoningEffort.LOW, "max_effort": ReasoningEffort.MEDIUM}
            ),
        }
    )


async def resolve_routing_profile(
    db: AsyncSession,
    session_id: Optional[str] = None,
    project_name: Optional[str] = None,
) -> Tuple[RoutingProfile, str]:
    """
    Resolve the effective Routing Profile based on deterministic precedence:
    session override > project override > default profile > system Balanced.
    
    Returns a tuple of (RoutingProfile, winning_scope).
    """
    
    # 1. Session override
    if session_id:
        result = await db.execute(select(SessionModel).where(SessionModel.id == session_id))
        session_obj = result.scalar_one_or_none()
        if session_obj and session_obj.routing_profile_id:
            profile_res = await db.execute(select(RoutingProfileModel).where(RoutingProfileModel.id == session_obj.routing_profile_id))
            db_profile = profile_res.scalar_one_or_none()
            if db_profile and db_profile.is_active:
                return RoutingProfile(**db_profile.routes_json, id=db_profile.id, name=db_profile.name, version=db_profile.version), "session"

    # 2. Project override
    if project_name:
        result = await db.execute(select(ProjectRoutingAssignmentModel).where(ProjectRoutingAssignmentModel.project_name == project_name))
        assignment = result.scalar_one_or_none()
        if assignment:
            profile_res = await db.execute(select(RoutingProfileModel).where(RoutingProfileModel.id == assignment.routing_profile_id))
            db_profile = profile_res.scalar_one_or_none()
            if db_profile and db_profile.is_active:
                return RoutingProfile(**db_profile.routes_json, id=db_profile.id, name=db_profile.name, version=db_profile.version), "project"

    # 3. Default Profile (if designated, for now we skip to system)
    # TODO: Fetch default profile if a setting for it exists.

    # 4. System Balanced
    return get_system_balanced_profile(), "system"


def apply_routing_profile_to_context(
    profile: RoutingProfile,
    role: str,
    context: RoutingContext,
    winning_scope: str,
    message_override: Optional[str] = None,
) -> RoutingContext:
    """
    Mutate or return a new RoutingContext mapped from the given profile and role.
    Applies message > profile precedence.
    """
    
    context.profile_id = profile.id
    context.profile_version = profile.version
    context.winning_scope = winning_scope
    
    # Message override takes ultimate precedence (STRICT LOCK-ALL)
    # The lock-all state should be tracked to propagate to children.
    if message_override:
        context.explicit_model_override = message_override
        context.winning_scope = "message"
        context.is_lock_all = True
        return context
        
    # If a parent was locked, we inherit lock-all strictly
    if getattr(context, "is_lock_all", False) and context.explicit_model_override:
        return context

    # Otherwise apply profile routing for the specific role (e.g. "root", "research", "coding")
    route_config = profile.routes.get(role) or RouteConfig()
    
    # Merge global policies
    context.privacy_requirement = route_config.privacy_policy or profile.global_privacy_policy
    context.fallback_policy = route_config.fallback_policy or profile.global_fallback_policy
    context.cost_preference = profile.cost_preference
    context.latency_preference = profile.latency_preference
    
    # Apply specific model overrides from the profile if present
    if route_config.model_override and route_config.model_override != "auto":
        context.explicit_model_override = route_config.model_override
    elif route_config.provider_override:
        context.explicit_model_override = route_config.provider_override
    else:
        context.explicit_model_override = None # Auto mode
        
    # Apply reasoning config
    context.reasoning_policy = route_config.reasoning.policy
    context.reasoning_effort = route_config.reasoning.effort
    context.reasoning_effort_min = route_config.reasoning.min_effort
    context.reasoning_effort_max = route_config.reasoning.max_effort

    return context
