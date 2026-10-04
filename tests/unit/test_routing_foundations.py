"""Comprehensive unit and integration test suite for AURA Routing Foundations v1."""

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    ModelCapabilityMismatch,
    ModelUnavailable,
    NoEligibleRoute,
    PrivacyBoundaryViolation,
    ReasoningControlUnsupported,
    RoutingConfirmationRequired,
)
from app.db.models import (
    ProjectRoutingAssignmentModel,
    RoutingProfileModel,
    RunEventModel,
    RunModel,
    SessionModel,
    WorkspaceEdgeModel,
    WorkspaceObjectModel,
)
from app.models.base import (
    ChatMessage,
    FallbackPolicy,
    ModelRequest,
    ModelResponse,
    ModelRole,
    PrivacyPolicy,
    ReasoningEffort,
    ReasoningPolicy,
    RoutingContext,
    ToolCallRequest,
)
from app.models.mock_provider import MockModelProvider
from app.models.provider import ModelProvider
from app.models.router import ModelRouter
from app.models.routing_policy import DeterministicRoutingPolicy, ProviderMetadata
from app.models.routing_profile import ReasoningConfig, RouteConfig, RoutingProfile
from app.models.routing_resolver import (
    apply_routing_profile_to_context,
    get_system_balanced_profile,
    inherit_routing_boundaries,
    model_to_routing_profile,
    resolve_routing_profile,
)


class SpyModelProvider(ModelProvider):
    """Spy provider that records calls without executing models."""

    def __init__(self, name: str = "spy-cloud", privacy: str = "cloud"):
        self._name = name
        self.privacy = privacy
        self.generate_call_count = 0
        self.last_request = None

    @property
    def name(self) -> str:
        return self._name

    async def generate(self, request: ModelRequest) -> ModelResponse:
        self.generate_call_count += 1
        self.last_request = request
        return ModelResponse(content="spy-response")

    async def generate_stream(self, request: ModelRequest):
        yield "spy-chunk"


# =============================================================================
# 1. Adaptive Reasoning Bounds & Complexity Clamping (Requirements 3 & 4)
# =============================================================================

def test_adaptive_reasoning_complexity_clamping():
    policy = DeterministicRoutingPolicy()
    metadata = {
        "prov": ProviderMetadata(
            name="prov",
            capabilities=["general", "reasoning"],
            default_model="mod-m",
            models=["mod-m"],
            reasoning_support={"mod-m": "medium"},
        )
    }

    # Low -> Medium bounds + complex task => Target High, clamped to Medium
    ctx1 = RoutingContext(
        complexity="complex",
        reasoning_policy=ReasoningPolicy.ADAPTIVE,
        reasoning_effort_min=ReasoningEffort.LOW,
        reasoning_effort_max=ReasoningEffort.MEDIUM,
    )
    sel1 = policy.select(ctx1, metadata, default_provider="prov")
    assert sel1.reasoning_effort_selected == "medium"

    # Medium -> High bounds + simple task => Target Low, clamped to Medium
    metadata_med = {
        "prov": ProviderMetadata(
            name="prov",
            capabilities=["general", "reasoning"],
            default_model="mod-m",
            models=["mod-m"],
            reasoning_support={"mod-m": "medium"},
        )
    }
    ctx2 = RoutingContext(
        complexity="simple",
        reasoning_policy=ReasoningPolicy.ADAPTIVE,
        reasoning_effort_min=ReasoningEffort.MEDIUM,
        reasoning_effort_max=ReasoningEffort.HIGH,
    )
    sel2 = policy.select(ctx2, metadata_med, default_provider="prov")
    assert sel2.reasoning_effort_selected == "medium"

    # Medium -> High bounds + complex task => Target High, clamped to High
    metadata_high = {
        "prov": ProviderMetadata(
            name="prov",
            capabilities=["general", "reasoning"],
            default_model="mod-h",
            models=["mod-h"],
            reasoning_support={"mod-h": "high"},
        )
    }
    ctx3 = RoutingContext(
        complexity="complex",
        reasoning_policy=ReasoningPolicy.ADAPTIVE,
        reasoning_effort_min=ReasoningEffort.MEDIUM,
        reasoning_effort_max=ReasoningEffort.HIGH,
    )
    sel3 = policy.select(ctx3, metadata_high, default_provider="prov")
    assert sel3.reasoning_effort_selected == "high"


def test_invalid_adaptive_bounds_rejected():
    # min=high, max=low must fail validation
    with pytest.raises(ValueError, match="cannot be greater than max_effort"):
        ReasoningConfig(
            policy=ReasoningPolicy.ADAPTIVE,
            min_effort=ReasoningEffort.HIGH,
            max_effort=ReasoningEffort.LOW,
        )

    # Valid range succeeds
    valid_cfg = ReasoningConfig(
        policy=ReasoningPolicy.ADAPTIVE,
        min_effort=ReasoningEffort.LOW,
        max_effort=ReasoningEffort.HIGH,
    )
    assert valid_cfg.min_effort == ReasoningEffort.LOW
    assert valid_cfg.max_effort == ReasoningEffort.HIGH


# =============================================================================
# 2. Honest Unknown Reasoning Support Handling (Requirement 5)
# =============================================================================

def test_unknown_reasoning_excluded_from_fixed_controllable_request():
    policy = DeterministicRoutingPolicy()
    metadata = {
        "prov": ProviderMetadata(
            name="prov",
            capabilities=["general"],
            default_model="mod-unknown",
            models=["mod-unknown"],
            reasoning_support={"mod-unknown": "unknown"},
        )
    }

    # Hard fixed controllable request for HIGH must NOT assume unknown can do it
    ctx = RoutingContext(
        reasoning_policy=ReasoningPolicy.FIXED,
        reasoning_effort=ReasoningEffort.HIGH,
    )
    with pytest.raises(ReasoningControlUnsupported):
        policy.select(ctx, metadata, default_provider="prov")


def test_adaptive_honest_unknown_and_fixed_by_model_handling():
    policy = DeterministicRoutingPolicy()
    metadata = {
        "prov-unknown": ProviderMetadata(
            name="prov-unknown",
            capabilities=["general"],
            default_model="mod-u",
            models=["mod-u"],
            reasoning_support={"mod-u": "unknown"},
        ),
        "prov-fixed": ProviderMetadata(
            name="prov-fixed",
            capabilities=["general"],
            default_model="mod-f",
            models=["mod-f"],
            reasoning_support={"mod-f": "fixed_by_model"},
        ),
    }

    # Unknown remains eligible under adaptive, but effort is tagged "unknown", not a numeric claim
    ctx_u = RoutingContext(
        reasoning_policy=ReasoningPolicy.ADAPTIVE,
        reasoning_effort_min=ReasoningEffort.LOW,
        reasoning_effort_max=ReasoningEffort.HIGH,
    )
    sel_u = policy.select(ctx_u, {"prov-unknown": metadata["prov-unknown"]}, default_provider="prov-unknown")
    assert sel_u.reasoning_effort_selected == "unknown"

    # Fixed by model remains eligible, effort tagged "fixed_by_model"
    sel_f = policy.select(ctx_u, {"prov-fixed": metadata["prov-fixed"]}, default_provider="prov-fixed")
    assert sel_f.reasoning_effort_selected == "fixed_by_model"


# =============================================================================
# 3. Truthful OpenAI Metadata & Selected Reasoning Wiring (Requirements 6 & 7)
# =============================================================================

def test_openai_metadata_truthful_reasoning():
    router = ModelRouter()
    meta = router._metadata["openai"]
    # Verify metadata does not claim controllable effort without adapter support
    for model_name, support in meta.reasoning_support.items():
        assert support in ("fixed_by_model", "unknown"), f"False controllable claim on {model_name}: {support}"


@pytest.mark.asyncio
async def test_selected_reasoning_independent_propagation():
    spy = SpyModelProvider(name="spy-prop", privacy="local")
    router = ModelRouter(providers={"spy-prop": spy})
    router.register_provider(
        spy,
        ProviderMetadata(
            name="spy-prop",
            capabilities=["general"],
            default_model="prop-model-v1",
            models=["prop-model-v1"],
            reasoning_support={"prop-model-v1": "high"},
        ),
    )

    ctx = RoutingContext(
        reasoning_policy=ReasoningPolicy.FIXED,
        reasoning_effort=ReasoningEffort.HIGH,
    )
    req = ModelRequest(
        messages=[ChatMessage(role=ModelRole.USER, content="hello")],
        routing_context=ctx,
    )

    await router.route(req, routing_context=ctx)

    # Prove selected_model != selected_reasoning and both propagate independently
    assert req.selected_model == "prop-model-v1"
    assert req.selected_reasoning == "high"
    assert req.selected_model != req.selected_reasoning
    assert spy.last_request.selected_model == "prop-model-v1"
    assert spy.last_request.selected_reasoning == "high"


# =============================================================================
# 4. Long Context & Fallback Policy NONE (Requirements 8 & 9)
# =============================================================================

def test_requires_long_context_filter():
    policy = DeterministicRoutingPolicy()
    metadata = {
        "short-prov": ProviderMetadata(
            name="short-prov",
            capabilities=["general"],
            default_model="short-model",
            models=["short-model"],
        ),
        "long-prov": ProviderMetadata(
            name="long-prov",
            capabilities=["general", "long_context"],
            default_model="long-model",
            models=["long-model"],
        ),
    }

    # When requires_long_context=True, short-prov is filtered out
    ctx = RoutingContext(requires_long_context=True)
    sel = policy.select(ctx, metadata, default_provider="short-prov")
    assert sel.provider_name == "long-prov"
    assert sel.model_name == "long-model"

    # If no provider supports long context, ModelCapabilityMismatch is raised
    with pytest.raises(ModelCapabilityMismatch, match="long_context"):
        policy.select(ctx, {"short-prov": metadata["short-prov"]}, default_provider="short-prov")


def test_fallback_policy_none_strict_failure():
    policy = DeterministicRoutingPolicy()
    metadata = {
        "primary": ProviderMetadata(
            name="primary",
            capabilities=["general"],
            privacy_status="cloud",
            default_model="prim-v1",
            models=["prim-v1"],
        ),
        "alt": ProviderMetadata(
            name="alt",
            capabilities=["general"],
            privacy_status="local",
            default_model="alt-v1",
            models=["alt-v1"],
        ),
    }

    # Assigned route primary is unavailable under local_only privacy
    # Under NONE fallback policy, it must strictly fail, not switch to alt!
    ctx = RoutingContext(
        privacy_requirement=PrivacyPolicy.LOCAL_ONLY,
        fallback_policy=FallbackPolicy.NONE,
    )
    with pytest.raises(NoEligibleRoute, match="NONE"):
        policy.select(ctx, metadata, default_provider="primary")


# =============================================================================
# 5. ASK_BEFORE_CLOUD Structured Outcome & Zero Invocation (Requirement 10)
# =============================================================================

@pytest.mark.asyncio
async def test_ask_before_cloud_structured_outcome_and_zero_invocations():
    spy_cloud = SpyModelProvider(name="spy-cloud", privacy="cloud")
    router = ModelRouter(default_provider_name="spy-cloud", providers={"spy-cloud": spy_cloud})
    router.register_provider(
        spy_cloud,
        ProviderMetadata(
            name="spy-cloud",
            capabilities=["general"],
            privacy_status="cloud",
            default_model="cloud-m",
            models=["cloud-m"],
        ),
    )

    ctx = RoutingContext(
        fallback_policy=FallbackPolicy.ASK_BEFORE_CLOUD,
        profile_id="prof-audit-1",
    )

    try:
        router.select_model_for_task(ctx)
        pytest.fail("Expected RoutingConfirmationRequired exception")
    except RoutingConfirmationRequired as err:
        # Assert structured domain outcome fields
        assert err.details["proposed_provider"] == "spy-cloud"
        assert err.details["proposed_model"] == "cloud-m"
        assert err.details["profile_id"] == "prof-audit-1"
        assert err.details["to_privacy"] == "cloud"

    # Critical invariant: cloud provider invocation count == 0 before confirmation!
    assert spy_cloud.generate_call_count == 0


@pytest.mark.asyncio
async def test_explicit_cloud_confirmation_does_not_widen_none_fallback_policy():
    spy_cloud = SpyModelProvider(name="spy-cloud", privacy="cloud")
    router = ModelRouter(default_provider_name="spy-cloud", providers={"spy-cloud": spy_cloud})
    router.register_provider(
        spy_cloud,
        ProviderMetadata(
            name="spy-cloud",
            capabilities=["general"],
            privacy_status="cloud",
            default_model="cloud-m",
            models=["cloud-m"],
        ),
    )

    ctx = RoutingContext(
        fallback_policy=FallbackPolicy.NONE,
        require_cloud_confirmation=True,
    )

    with pytest.raises(RoutingConfirmationRequired):
        router.select_model_for_task(ctx)

    assert spy_cloud.generate_call_count == 0


def test_cloud_confirmation_requirement_is_inherited_by_specialist_without_changing_fallback():
    child = inherit_routing_boundaries(
        RoutingContext(fallback_policy=FallbackPolicy.SAME_PROVIDER_ONLY),
        {
            "fallback_policy": FallbackPolicy.CLOUD_ALLOWED.value,
            "require_cloud_confirmation": True,
        },
    )

    assert child.fallback_policy == FallbackPolicy.SAME_PROVIDER_ONLY
    assert child.require_cloud_confirmation is True


# =============================================================================
# 6. Default Profile Precedence & Task-Route Resolution (Requirements 11 & 14)
# =============================================================================

@pytest.mark.asyncio
async def test_routing_precedence_layers(test_db_session: AsyncSession):
    # 1. System fallback when nothing is in DB
    prof, scope = await resolve_routing_profile(test_db_session)
    assert scope == "system"
    assert prof.id == "system-balanced"

    # 2. Persisted Default Profile (default > system)
    def_prof = RoutingProfileModel(
        id="prof-default",
        name="Global Default Profile",
        version=1,
        is_active=True,
        is_default=True,
        global_privacy_policy="public",
        global_fallback_policy="cloud_allowed",
        cost_preference="normal",
        latency_preference="normal",
        routes_json={"routes": {}},
    )
    test_db_session.add(def_prof)
    await test_db_session.commit()

    prof_def, scope_def = await resolve_routing_profile(test_db_session)
    assert scope_def == "default"
    assert prof_def.id == "prof-default"

    # 3. Project override (project > default)
    proj_prof = RoutingProfileModel(
        id="prof-project",
        name="Project Profile",
        version=1,
        is_active=True,
        is_default=False,
        global_privacy_policy="confidential",
        global_fallback_policy="local_only",
        cost_preference="low",
        latency_preference="normal",
        routes_json={"routes": {}},
    )
    test_db_session.add(proj_prof)
    test_db_session.add(ProjectRoutingAssignmentModel(project_name="Atlas", routing_profile_id="prof-project"))
    await test_db_session.commit()

    prof_proj, scope_proj = await resolve_routing_profile(test_db_session, project_name="Atlas")
    assert scope_proj == "project"
    assert prof_proj.id == "prof-project"

    # 4. Session override (session > project)
    sess_prof = RoutingProfileModel(
        id="prof-session",
        name="Session Profile",
        version=1,
        is_active=True,
        is_default=False,
        global_privacy_policy="local_only",
        global_fallback_policy="none",
        cost_preference="normal",
        latency_preference="low",
        routes_json={"routes": {}},
    )
    test_db_session.add(sess_prof)
    session_id = str(uuid.uuid4())
    test_db_session.add(SessionModel(id=session_id, routing_profile_id="prof-session"))
    await test_db_session.commit()

    prof_sess, scope_sess = await resolve_routing_profile(test_db_session, session_id=session_id, project_name="Atlas")
    assert scope_sess == "session"
    assert prof_sess.id == "prof-session"

    # 5. Message override takes ultimate precedence (message > session)
    ctx = RoutingContext(session_id=session_id)
    ctx = apply_routing_profile_to_context(
        profile=prof_sess,
        role="root",
        context=ctx,
        winning_scope=scope_sess,
        message_override="mock:pinned-model",
    )
    assert ctx.winning_scope == "message"
    assert ctx.explicit_model_override == "mock:pinned-model"
    assert ctx.is_lock_all is True


def test_task_route_resolution_for_writing():
    profile = RoutingProfile(
        id="prof-tasks",
        name="Task Profile",
        routes={
            "root": RouteConfig(model_override="mock:root-model"),
            "writing": RouteConfig(model_override="mock:writing-model"),
            "research": RouteConfig(model_override="mock:research-model"),
            "coding": RouteConfig(model_override="mock:coding-model"),
        },
    )

    # Root + writing task_type -> writing route wins
    ctx_write = RoutingContext(task_type="writing")
    ctx_write = apply_routing_profile_to_context(profile, role="root", context=ctx_write, winning_scope="system")
    assert ctx_write.explicit_model_override == "mock:writing-model"

    # Root without task_type -> root route wins
    ctx_root = RoutingContext()
    ctx_root = apply_routing_profile_to_context(profile, role="root", context=ctx_root, winning_scope="system")
    assert ctx_root.explicit_model_override == "mock:root-model"

    # Specialist roles always win over task types
    ctx_research = RoutingContext(task_type="writing")
    ctx_research = apply_routing_profile_to_context(profile, role="research", context=ctx_research, winning_scope="system")
    assert ctx_research.explicit_model_override == "mock:research-model"

    ctx_coding = RoutingContext(task_type="writing")
    ctx_coding = apply_routing_profile_to_context(profile, role="coding", context=ctx_coding, winning_scope="system")
    assert ctx_coding.explicit_model_override == "mock:coding-model"


def test_lock_all_propagation_parent_to_child():
    profile = RoutingProfile(
        id="prof-p",
        name="Profile P",
        routes={
            "root": RouteConfig(model_override="mock:root-model"),
            "research": RouteConfig(model_override="mock:research-model"),
        },
    )

    # Parent context locked by message override
    parent_ctx = RoutingContext()
    parent_ctx = apply_routing_profile_to_context(
        profile,
        role="root",
        context=parent_ctx,
        winning_scope="system",
        message_override="mock:lock-model",
    )
    assert parent_ctx.is_lock_all is True
    assert parent_ctx.explicit_model_override == "mock:lock-model"

    # Child context inherits lock-all and override
    child_ctx = RoutingContext(
        is_lock_all=parent_ctx.is_lock_all,
        explicit_model_override=parent_ctx.explicit_model_override,
    )
    child_ctx = apply_routing_profile_to_context(
        profile,
        role="research",
        context=child_ctx,
        winning_scope="system",
    )
    assert child_ctx.is_lock_all is True
    assert child_ctx.explicit_model_override == "mock:lock-model"


def test_temporary_model_and_reasoning_overrides_preserve_profile_policy():
    profile = RoutingProfile(
        id="private-profile",
        name="Private",
        global_privacy_policy=PrivacyPolicy.CONFIDENTIAL,
        global_fallback_policy=FallbackPolicy.LOCAL_ONLY,
        cost_preference="low",
        latency_preference="low",
        routes={
            "root": RouteConfig(
                model_override="mock:profile-model",
                reasoning=ReasoningConfig(policy=ReasoningPolicy.ADAPTIVE, min_effort=ReasoningEffort.LOW, max_effort=ReasoningEffort.HIGH),
            ),
            "research": RouteConfig(
                model_override="mock:research-model",
                privacy_policy=PrivacyPolicy.LOCAL_ONLY,
                fallback_policy=FallbackPolicy.NONE,
                reasoning=ReasoningConfig(policy=ReasoningPolicy.ADAPTIVE, min_effort=ReasoningEffort.MEDIUM, max_effort=ReasoningEffort.HIGH),
            ),
        },
    )
    root = apply_routing_profile_to_context(
        profile, "root", RoutingContext(), "project",
        message_override="mock:temporary-model", reasoning_override="medium",
    )
    assert root.explicit_model_override == "mock:temporary-model"
    assert root.privacy_requirement == PrivacyPolicy.CONFIDENTIAL
    assert root.fallback_policy == FallbackPolicy.LOCAL_ONLY
    assert root.cost_preference == "low" and root.latency_preference == "low"
    assert root.reasoning_policy == ReasoningPolicy.FIXED
    assert root.reasoning_effort == ReasoningEffort.MEDIUM
    assert root.winning_scope == "message"

    child = apply_routing_profile_to_context(
        profile, "research",
        RoutingContext(is_lock_all=True, explicit_model_override=root.explicit_model_override),
        "project", reasoning_override="medium",
    )
    assert child.explicit_model_override == "mock:temporary-model"
    assert child.privacy_requirement == PrivacyPolicy.LOCAL_ONLY
    assert child.fallback_policy == FallbackPolicy.NONE
    assert child.reasoning_policy == ReasoningPolicy.FIXED
    assert child.reasoning_effort == ReasoningEffort.MEDIUM


def test_temporary_model_lock_cannot_bypass_hard_privacy_boundary():
    profile = RoutingProfile(
        id="confidential-profile", name="Confidential",
        global_privacy_policy=PrivacyPolicy.CONFIDENTIAL,
        global_fallback_policy=FallbackPolicy.CLOUD_ALLOWED,
        routes={"root": RouteConfig(reasoning=ReasoningConfig(policy=ReasoningPolicy.ADAPTIVE, min_effort=ReasoningEffort.LOW, max_effort=ReasoningEffort.HIGH))},
    )
    context = apply_routing_profile_to_context(
        profile, "root", RoutingContext(), "project", message_override="cloud:model",
    )
    policy = DeterministicRoutingPolicy()
    metadata = {
        "cloud": ProviderMetadata(name="cloud", privacy_status="cloud", default_model="model", models=["model"], reasoning_support={"model": "fixed_by_model"}),
        "local": ProviderMetadata(name="local", privacy_status="local", default_model="model", models=["model"], reasoning_support={"model": "high"}),
    }
    with pytest.raises(PrivacyBoundaryViolation):
        policy.select(context, metadata, default_provider="local")


# =============================================================================
# 7. System Balanced Assignment Integrity & Version Increment (Req 15 & 17)
# =============================================================================

@pytest.mark.asyncio
async def test_system_balanced_assignment_integrity_and_reset(test_db_session: AsyncSession):
    # Assigning a valid profile first
    prof = RoutingProfileModel(id="prof-custom-1", name="Custom", routes_json={})
    test_db_session.add(prof)
    await test_db_session.commit()

    # Create assignment
    test_db_session.add(ProjectRoutingAssignmentModel(project_name="P1", routing_profile_id="prof-custom-1"))
    await test_db_session.commit()

    # Resetting to system-balanced deletes the explicit assignment to prevent FK violation
    from app.api.routes.routing import assign_profile_to_project
    res = await assign_profile_to_project(project_name="P1", profile_id="system-balanced", db=test_db_session)
    assert res["routing_profile_id"] is None

    # Check assignment is deleted from DB
    chk = await test_db_session.execute(select(ProjectRoutingAssignmentModel).where(ProjectRoutingAssignmentModel.project_name == "P1"))
    assert chk.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_profile_version_increment_authoritative(test_db_session: AsyncSession):
    prof = RoutingProfileModel(id="prof-v1", name="Profile V1", version=5, routes_json={})
    test_db_session.add(prof)
    await test_db_session.commit()

    from app.api.routes.routing import update_routing_profile
    # Client sends stale version 1
    stale_update = RoutingProfile(name="Profile V1 Updated", version=1)
    updated = await update_routing_profile(profile_id="prof-v1", profile_update=stale_update, db=test_db_session)

    # Version must increment from stored database version (5 -> 6), ignoring client payload
    assert updated.version == 6


@pytest.mark.asyncio
async def test_profile_global_fields_roundtrip_persistence(test_db_session: AsyncSession):
    profile = RoutingProfile(
        id="prof-rt",
        name="Roundtrip Profile",
        global_privacy_policy=PrivacyPolicy.CONFIDENTIAL,
        global_fallback_policy=FallbackPolicy.LOCAL_ONLY,
        cost_preference="low",
        latency_preference="low",
        routes={"root": RouteConfig(model_override="mock:local-only")},
    )

    from app.api.routes.routing import create_routing_profile, get_routing_profile
    created = await create_routing_profile(profile=profile, db=test_db_session)
    fetched = await get_routing_profile(profile_id="prof-rt", db=test_db_session)

    assert fetched.global_privacy_policy == PrivacyPolicy.CONFIDENTIAL
    assert fetched.global_fallback_policy == FallbackPolicy.LOCAL_ONLY
    assert fetched.cost_preference == "low"
    assert fetched.latency_preference == "low"
    assert fetched.routes["root"].model_override == "mock:local-only"


# =============================================================================
# 8. Complete Routing API Endpoints & Preview Zero Invocation (Requirements 12 & 13)
# =============================================================================

@pytest.mark.asyncio
async def test_routing_api_endpoints_complete(async_client: AsyncClient, test_db_session: AsyncSession):
    # 1. Create profile
    create_resp = await async_client.post(
        "/v1/routing/profiles",
        json={
            "name": "API Test Profile",
            "global_privacy_policy": "public",
            "global_fallback_policy": "cloud_allowed",
            "routes": {
                "root": {
                    "reasoning": {
                        "policy": "adaptive",
                        "min_effort": "low",
                        "max_effort": "medium"
                    }
                }
            }
        },
    )
    assert create_resp.status_code == 201
    created_id = create_resp.json()["id"]

    # 2. Duplicate profile
    dup_resp = await async_client.post(f"/v1/routing/profiles/{created_id}/duplicate")
    assert dup_resp.status_code == 201
    dup_data = dup_resp.json()
    assert dup_data["name"] == "API Test Profile (Copy)"
    assert dup_data["id"] != created_id

    # 3. Validate profile
    val_resp = await async_client.post(f"/v1/routing/profiles/{created_id}/validate")
    assert val_resp.status_code == 200
    assert val_resp.json()["valid"] is True

    # 4. Effective routing lookup
    eff_resp = await async_client.get("/v1/routing/effective")
    assert eff_resp.status_code == 200
    assert "profile" in eff_resp.json()
    assert "winning_scope" in eff_resp.json()

    # 5. Session assignment API
    sess_id = str(uuid.uuid4())
    test_db_session.add(SessionModel(id=sess_id))
    await test_db_session.commit()

    put_sess = await async_client.put(f"/v1/routing/sessions/{sess_id}", json={"profile_id": created_id})
    assert put_sess.status_code == 200
    assert put_sess.json()["routing_profile_id"] == created_id

    get_sess = await async_client.get(f"/v1/routing/sessions/{sess_id}")
    assert get_sess.status_code == 200
    assert get_sess.json()["routing_profile_id"] == created_id

    # Reset session assignment
    reset_sess = await async_client.put(f"/v1/routing/sessions/{sess_id}", json={"profile_id": "system-balanced"})
    assert reset_sess.status_code == 200
    assert reset_sess.json()["routing_profile_id"] is None

    # 6. Delete profile
    del_resp = await async_client.delete(f"/v1/routing/profiles/{created_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted_profile_id"] == created_id


@pytest.mark.asyncio
async def test_default_profile_transitions_keep_exactly_one_or_fall_back_to_system_balanced(
    async_client: AsyncClient,
    test_db_session: AsyncSession,
):
    first = await async_client.post("/v1/routing/profiles", json={
        "name": "First default",
        "is_default": True,
    })
    assert first.status_code == 201
    first_id = first.json()["id"]

    second = await async_client.post("/v1/routing/profiles", json={
        "name": "Second default",
        "is_default": True,
    })
    assert second.status_code == 201
    second_id = second.json()["id"]

    profiles = (await test_db_session.execute(
        select(RoutingProfileModel).where(RoutingProfileModel.is_default.is_(True))
    )).scalars().all()
    assert [profile.id for profile in profiles] == [second_id]
    effective = await async_client.get("/v1/routing/effective")
    assert effective.status_code == 200
    assert effective.json()["profile"]["id"] == second_id
    assert effective.json()["winning_scope"] == "default"

    reset = await async_client.put("/v1/routing/default", json={"profile_id": "system-balanced"})
    assert reset.status_code == 200
    assert reset.json()["routing_profile_id"] is None
    profiles = (await test_db_session.execute(
        select(RoutingProfileModel).where(RoutingProfileModel.is_default.is_(True))
    )).scalars().all()
    assert profiles == []
    effective = await async_client.get("/v1/routing/effective")
    assert effective.status_code == 200
    assert effective.json()["profile"]["id"] == "system-balanced"
    assert effective.json()["winning_scope"] == "system"


@pytest.mark.asyncio
async def test_preview_zero_model_invocation(async_client: AsyncClient):
    spy = SpyModelProvider(name="spy-prev", privacy="local")
    from app.models.router import model_router
    model_router.register_provider(
        spy,
        ProviderMetadata(
            name="spy-prev",
            capabilities=["general"],
            default_model="prev-m",
            models=["prev-m"],
            reasoning_support={"prev-m": "low"},
        ),
    )

    prev_resp = await async_client.post(
        "/v1/routing/preview",
        json={
            "role": "root",
            "message_override": "spy-prev:prev-m",
        },
    )
    assert prev_resp.status_code == 200
    data = prev_resp.json()
    assert data["provider"] == "spy-prev"
    assert data["model"] == "prev-m"
    assert data["profile_name"] == "System Balanced"
    assert data["profile_id"] == "system-balanced"
    assert data["winning_scope"] == "system"
    assert data["role"] == "root"
    assert data["task_route"] == "root"
    assert data["privacy"] == "public"
    assert data["fallback"] == "cloud_allowed"
    assert isinstance(data["warnings"], list)

    # Preview must NOT invoke model provider
    assert spy.generate_call_count == 0


@pytest.mark.asyncio
async def test_unsaved_profile_preview_is_non_persistent(async_client: AsyncClient, test_db_session: AsyncSession):
    preview = await async_client.post("/v1/routing/preview", json={
        "role": "research",
        "profile_draft": {
            "id": "unsaved-preview-only",
            "name": "Unsaved preview",
            "version": 7,
            "is_active": True,
            "is_default": False,
            "global_privacy_policy": "local_only",
            "global_fallback_policy": "none",
            "cost_preference": "low",
            "latency_preference": "normal",
            "routes": {"research": {"model_override": "mock:mock-pro", "reasoning": {"policy": "fixed", "effort": "high"}}},
        },
    })
    assert preview.status_code == 200
    data = preview.json()
    assert data["profile_id"] == "unsaved-preview-only"
    assert data["profile_name"] == "Unsaved preview"
    assert data["profile_version"] == 7
    assert data["winning_scope"] == "draft"
    assert data["privacy"] == "local_only"
    assert data["fallback"] == "none"
    assert data["role"] == "research"
    assert data["task_route"] == "research"
    assert await test_db_session.get(RoutingProfileModel, "unsaved-preview-only") is None


def test_root_vs_research_differential_routes():
    profile = RoutingProfile(
        id="prof-diff",
        name="Differential Profile",
        routes={
            "root": RouteConfig(model_override="mock:root-gemini"),
            "research": RouteConfig(model_override="mock:research-deepseek"),
            "coding": RouteConfig(model_override="mock:coding-claude"),
        },
    )

    ctx_root = apply_routing_profile_to_context(profile, role="root", context=RoutingContext(), winning_scope="system")
    ctx_research = apply_routing_profile_to_context(profile, role="research", context=RoutingContext(), winning_scope="system")
    ctx_coding = apply_routing_profile_to_context(profile, role="coding", context=RoutingContext(), winning_scope="system")

    assert ctx_root.explicit_model_override == "mock:root-gemini"
    assert ctx_research.explicit_model_override == "mock:research-deepseek"
    assert ctx_coding.explicit_model_override == "mock:coding-claude"
    assert ctx_root.explicit_model_override != ctx_research.explicit_model_override


@pytest.mark.asyncio
async def test_parent_and_child_routing_snapshot_lineage(test_db_session: AsyncSession):
    parent_id = str(uuid.uuid4())
    child_id = str(uuid.uuid4())
    sess_id = str(uuid.uuid4())

    parent_snap = {
        "profile_id": "system-balanced",
        "profile_version": 1,
        "winning_scope": "system",
        "role": "root",
        "is_lock_all": False,
        "privacy_policy": "public",
        "fallback_policy": "cloud_allowed",
        "explicit_model_override": None,
    }
    child_snap = {
        "profile_id": "system-balanced",
        "profile_version": 1,
        "winning_scope": "system",
        "role": "coding",
        "is_lock_all": False,
        "privacy_policy": "public",
        "fallback_policy": "cloud_allowed",
        "explicit_model_override": "mock:coding-specialist",
    }

    test_db_session.add(SessionModel(id=sess_id))
    parent_run = RunModel(
        id=parent_id,
        session_id=sess_id,
        user_message="parent run message",
        routing_snapshot_json=parent_snap,
    )
    child_run = RunModel(
        id=child_id,
        session_id=sess_id,
        parent_run_id=parent_id,
        user_message="child run message",
        routing_snapshot_json=child_snap,
    )
    test_db_session.add(parent_run)
    test_db_session.add(child_run)
    await test_db_session.commit()

    # Query back and verify independent snapshots and lineage
    loaded_child = await test_db_session.get(RunModel, child_id)
    assert loaded_child.parent_run_id == parent_id
    assert loaded_child.routing_snapshot_json["role"] == "coding"
    assert loaded_child.routing_snapshot_json["explicit_model_override"] == "mock:coding-specialist"

    loaded_parent = await test_db_session.get(RunModel, parent_id)
    assert loaded_parent.routing_snapshot_json["role"] == "root"
    assert loaded_parent.routing_snapshot_json["explicit_model_override"] is None


@pytest.mark.asyncio
async def test_run_routing_endpoint_returns_persisted_parent_and_child_decisions(test_db_session: AsyncSession, async_client: AsyncClient):
    session_id, parent_id, child_id, pending_child_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    test_db_session.add(SessionModel(id=session_id))
    test_db_session.add(RunModel(id=parent_id, session_id=session_id, user_message="root", routing_snapshot_json={"role": "root", "profile_id": "p", "winning_scope": "project"}))
    test_db_session.add(RunModel(id=child_id, session_id=session_id, parent_run_id=parent_id, user_message="child", routing_snapshot_json={"role": "research", "profile_id": "p", "winning_scope": "project"}))
    test_db_session.add(RunModel(id=pending_child_id, session_id=session_id, parent_run_id=parent_id, user_message="pending child", routing_snapshot_json={"role": "coding", "profile_id": "p", "winning_scope": "project"}))
    test_db_session.add(RunEventModel(run_id=parent_id, event_type="model_selected", payload={"provider": "local", "model": "root-model", "agent_role": "root", "prompt": "private model prompt"}))
    test_db_session.add(RunEventModel(run_id=parent_id, event_type="context_compiled", payload={"estimated_tokens": 64, "prompt_text": "private compiled context", "objects": [{"object_id": "root-note", "object_type": "manual_note", "selected_by_user": True, "content": "private note content"}]}))
    test_db_session.add(RunEventModel(run_id=child_id, event_type="model_selected", payload={"provider": "local", "model": "research-model", "agent_role": "research"}))
    test_db_session.add(RunEventModel(run_id=child_id, event_type="reasoning_effort_selected", payload={"selected_effort": "high"}))
    test_db_session.add(RunEventModel(run_id=child_id, event_type="context_compiled", payload={"estimated_tokens": 128, "objects": [{"object_id": "research-bridge", "object_type": "context_bridge", "selected_by_user": True}]}))
    test_db_session.add(RunEventModel(run_id=child_id, event_type="context_loaded", payload={
        "profile_memory_ids": {"work_style": "child-profile-memory"},
        "project_memory_ids": ["child-project-memory"],
        "semantic_memory_ids": [["child-semantic-memory"]],
        "episode_memory_ids": ["child-episode-memory"],
        "memory_privacy_sources": [{"memory_id": "child-project-memory", "privacy_policy": "confidential"}],
        "memory_text": "private child memory content",
    }))
    test_db_session.add(RunEventModel(run_id=child_id, event_type="fallback_considered", payload={"fallback_policy": "same_provider_only", "primary_provider": "local", "selected_provider": "local", "candidate_model": "local-fallback", "debug_payload": "private fallback detail"}))
    test_db_session.add(RunEventModel(run_id=child_id, event_type="internal_reasoning", payload={"text": "private hidden reasoning"}))
    await test_db_session.commit()

    response = await async_client.get(f"/v1/runs/{parent_id}/routing")
    assert response.status_code == 200
    decisions = response.json()["decisions"]
    assert len(decisions) == 3
    child = next(item for item in decisions if item["run_id"] == child_id)
    assert child["parent_run_id"] == parent_id
    assert child["model_selection"]["model"] == "research-model"
    assert child["reasoning_selection"]["selected_effort"] == "high"
    assert child["context_manifest"]["estimated_tokens"] == 128
    assert child["context_manifest"]["objects"][0]["object_id"] == "research-bridge"
    assert child["memory_ids_by_tier"] == {
        "profile": ["child-profile-memory"],
        "project": ["child-project-memory"],
        "semantic": ["child-semantic-memory"],
        "episode": ["child-episode-memory"],
    }
    assert child["memory_privacy_sources"] == [{"memory_id": "child-project-memory", "privacy_policy": "confidential"}]
    assert child["fallback_events"] == [{
        "event_type": "fallback_considered",
        "payload": {
            "fallback_policy": "same_provider_only",
            "primary_provider": "local",
            "selected_provider": "local",
            "candidate_model": "local-fallback",
        },
    }]
    parent = next(item for item in decisions if item["run_id"] == parent_id)
    assert parent["context_manifest"]["objects"][0]["object_id"] == "root-note"
    assert "prompt" not in parent["model_selection"]
    assert "prompt_text" not in parent["context_manifest"]
    assert "content" not in parent["context_manifest"]["objects"][0]
    assert "private model prompt" not in response.text
    assert "private compiled context" not in response.text
    assert "private note content" not in response.text
    assert "private fallback detail" not in response.text
    assert "private hidden reasoning" not in response.text
    assert "private child memory content" not in response.text
    pending = next(item for item in decisions if item["run_id"] == pending_child_id)
    assert pending["model_selection"] is None
    assert pending["reasoning_selection"] is None
    assert pending["context_manifest"] is None


@pytest.mark.asyncio
async def test_routing_trace_events_persistence(test_db_session: AsyncSession):
    from app.observability.tracer import TraceService
    trace_svc = TraceService(test_db_session)
    run_id = str(uuid.uuid4())
    sess_id = str(uuid.uuid4())

    test_db_session.add(SessionModel(id=sess_id))
    test_db_session.add(RunModel(id=run_id, session_id=sess_id, user_message="test trace"))
    await test_db_session.commit()

    # Record foundation routing trace events
    await trace_svc.record_event(
        run_id=run_id,
        session_id=sess_id,
        event_type="routing_profile_resolved",
        payload={"profile_id": "system-balanced", "winning_scope": "system"},
    )
    await trace_svc.record_event(
        run_id=run_id,
        session_id=sess_id,
        event_type="model_selected",
        payload={
            "agent_role": "root",
            "task_type": "coding",
            "provider": "mock",
            "model": "mock-default",
            "profile_id": "system-balanced",
            "profile_version": 1,
            "winning_scope": "system",
            "selection_reason": "routing_pipeline_matched",
            "privacy": "public",
            "fallback_policy": "cloud_allowed",
        },
    )
    await trace_svc.record_event(
        run_id=run_id,
        session_id=sess_id,
        event_type="reasoning_effort_selected",
        payload={
            "policy_mode": "adaptive",
            "configured_bounds": {"min": "low", "max": "medium"},
            "selected_effort": "medium",
        },
    )
    await trace_svc.record_event(
        run_id=run_id,
        session_id=sess_id,
        event_type="fallback_considered",
        payload={
            "fallback_policy": "cloud_allowed",
            "primary_provider": "mock",
            "selected_provider": "mock",
        },
    )

    # Verify persisted in database
    ev_stmt = select(RunEventModel).where(RunEventModel.run_id == run_id)
    ev_res = await test_db_session.execute(ev_stmt)
    events = {e.event_type: e.payload for e in ev_res.scalars().all()}

    assert "routing_profile_resolved" in events
    assert "model_selected" in events
    assert "reasoning_effort_selected" in events
    assert "fallback_considered" in events

    assert events["model_selected"]["agent_role"] == "root"
    assert events["model_selected"]["model"] == "mock-default"
    assert events["reasoning_effort_selected"]["selected_effort"] == "medium"


@pytest.mark.asyncio
async def test_delegation_runtime_persisted_profile_privacy_and_fallback(test_db_session: AsyncSession, monkeypatch):
    """Verify that a persisted profile's global_privacy_policy and global_fallback_policy
    are truthfully preserved in a real Research specialist child run created via DelegationRuntime.
    """
    from unittest.mock import AsyncMock, MagicMock
    from app.delegation.runtime import DelegationRuntime
    from app.delegation.types import DelegationRequest
    from app.capabilities.registry import NetworkRequirement, PrivacyBoundary
    from app.tools.registry import ToolRegistry

    # This test exercises persisted routing semantics with a local research fixture.
    # Mark the fixture's research provider accordingly so strict privacy permits it.
    base_tool_registry = ToolRegistry()
    research_provider = base_tool_registry.capability_providers.get("aura.research")
    assert research_provider is not None
    base_tool_registry.register_capability_provider(
        research_provider.model_copy(update={
            "privacy_boundary": PrivacyBoundary.LOCAL,
            "network_requirement": NetworkRequirement.NONE,
        }),
        base_tool_registry.capability_providers.get_capability_tools("aura.research"),
    )

    # 1. Create and persist custom profile in DB
    prof_id = "prof-persisted-custom-p1"
    db_profile = RoutingProfileModel(
        id=prof_id,
        name="Permissive Child Profile",
        global_privacy_policy="public",
        global_fallback_policy="cloud_allowed",
        version=3,
        is_active=True,
        routes_json={
            "routes": {
                "root": {"model_override": "mock:root-model"},
                "research": {"model_override": "mock:research-model"},
            }
        },
    )
    test_db_session.add(db_profile)

    sess_id = str(uuid.uuid4())
    parent_id = str(uuid.uuid4())
    test_db_session.add(SessionModel(id=sess_id))
    test_db_session.add(RunModel(id=parent_id, session_id=sess_id, user_message="parent root task"))
    await test_db_session.commit()

    # Mock compiled graph to avoid external LLM invocation while exercising the full delegation lifecycle
    mock_graph = AsyncMock()
    mock_state_snapshot = MagicMock(next=None)
    mock_graph.aget_state.return_value = mock_state_snapshot
    mock_graph.ainvoke.return_value = {"messages": [{"role": "assistant", "content": "research completed"}]}

    monkeypatch.setattr("app.delegation.runtime.get_compiled_graph", AsyncMock(return_value=mock_graph))

    runtime = DelegationRuntime(base_tool_registry=base_tool_registry)
    del_req = DelegationRequest(
        specialist_name="research",
        task_description="Execute local research task",
        parent_run_id=parent_id,
        session_id=sess_id,
        context={
            "profile_id": prof_id,
            "winning_scope": "session",
            "routing_context_dict": {
                "privacy_requirement": "local_only",
                "fallback_policy": "local_only",
            },
        },
    )

    result = await runtime.delegate(del_req, db=test_db_session)
    assert result.specialist_name == "research"

    # Inspect child RunModel in DB
    child_run = await test_db_session.get(RunModel, result.child_run_id)
    assert child_run is not None
    snapshot = child_run.routing_snapshot_json

    # Assert contract preservation
    assert snapshot["privacy_policy"] == "local_only"
    assert snapshot["fallback_policy"] == "local_only"
    assert snapshot["profile_id"] == prof_id
    assert snapshot["profile_version"] == 3
    assert snapshot["role"] == "research"
    assert snapshot["explicit_model_override"] == "mock:research-model"

    # Inspect the child's routing_context_dict
    routing_ctx_dict = del_req.context["routing_context_dict"]
    assert routing_ctx_dict["privacy_requirement"] == "local_only"
    assert routing_ctx_dict["fallback_policy"] == "local_only"
    assert routing_ctx_dict["explicit_model_override"] == "mock:research-model"


@pytest.mark.asyncio
async def test_research_child_completion_projects_artifacts_into_workspace_graph(test_db_session: AsyncSession, monkeypatch):
    from unittest.mock import AsyncMock, MagicMock
    from app.delegation.runtime import DelegationRuntime
    from app.delegation.types import DelegationRequest
    from app.research.models import ClaimType, EvidenceItem, ResearchClaim, ResearchGoal, ResearchSource, ResearchState, SourceStatus

    session_id, parent_id = str(uuid.uuid4()), str(uuid.uuid4())
    test_db_session.add(SessionModel(id=session_id, project_name="Atlas"))
    test_db_session.add(RunModel(id=parent_id, session_id=session_id, user_message="Research the checkpoint design."))
    await test_db_session.commit()

    state = ResearchState(
        goal=ResearchGoal(goal_id="goal-graph", user_query="Research the checkpoint design.", project_name="Atlas"),
        sources={"source-graph": ResearchSource(
            source_id="source-graph", canonical_id="doi:10.1000/graph", title="Checkpointed Workflows",
            abstract="A paper about durable workflows.", status=SourceStatus.INSPECTED,
        )},
        evidence={"evidence-graph": EvidenceItem(
            evidence_id="evidence-graph", source_id="source-graph", source_title="Checkpointed Workflows",
            source_locator="Section 2", extracted_text="Workflow state resumes from a persisted checkpoint.",
        )},
        claims=[ResearchClaim(
            claim_id="claim-graph", claim_text="The paper identifies a research gap in interactive restartability.",
            claim_type=ClaimType.SOURCE_SUPPORTED_FACT, evidence_ids=["evidence-graph"],
            verification_status="verified",
        )],
    )
    mock_graph = AsyncMock()
    mock_graph.aget_state.return_value = MagicMock(next=None, values={})
    mock_graph.ainvoke.return_value = {
        "messages": [{"role": "assistant", "content": "Research completed."}],
        "research_state": state.to_dict(),
        "execution_status": "completed",
    }
    monkeypatch.setattr("app.delegation.runtime.get_compiled_graph", AsyncMock(return_value=mock_graph))

    result = await DelegationRuntime().delegate(DelegationRequest(
        specialist_name="research",
        task_description="Research the checkpoint design.",
        parent_run_id=parent_id,
        session_id=session_id,
        context={"project_name": "Atlas"},
    ), db=test_db_session)

    objects = (await test_db_session.execute(
        select(WorkspaceObjectModel).where(WorkspaceObjectModel.project_name == "Atlas")
    )).scalars().all()
    assert {item.object_type for item in objects} == {"research_source", "research_evidence", "research_claim"}
    assert len(objects) == 3
    assert all(item.metadata_json["research_run_id"] == result.child_run_id for item in objects)
    assert {edge.relation_type for edge in (await test_db_session.execute(
        select(WorkspaceEdgeModel).where(WorkspaceEdgeModel.project_name == "Atlas")
    )).scalars().all()} == {"contains_evidence", "supports_claim"}


@pytest.mark.asyncio
async def test_delegation_runtime_lock_all_child_propagation(test_db_session: AsyncSession, monkeypatch):
    """Verify that lock-all propagation via DelegationRuntime propagates exact model to the Research child."""
    from unittest.mock import AsyncMock, MagicMock
    from app.delegation.runtime import DelegationRuntime
    from app.delegation.types import DelegationRequest

    sess_id = str(uuid.uuid4())
    parent_id = str(uuid.uuid4())
    test_db_session.add(SessionModel(id=sess_id))
    test_db_session.add(RunModel(id=parent_id, session_id=sess_id, user_message="parent root task"))
    await test_db_session.commit()

    mock_graph = AsyncMock()
    mock_graph.aget_state.return_value = MagicMock(next=None)
    mock_graph.ainvoke.return_value = {"messages": [{"role": "assistant", "content": "locked model ran"}]}
    monkeypatch.setattr("app.delegation.runtime.get_compiled_graph", AsyncMock(return_value=mock_graph))

    runtime = DelegationRuntime()
    del_req = DelegationRequest(
        specialist_name="research",
        task_description="Execute lock-all research task",
        parent_run_id=parent_id,
        session_id=sess_id,
        context={
            "is_lock_all": True,
            "model_override": "mock:lock-model-target",
            "reasoning_override": "high",
        },
    )

    result = await runtime.delegate(del_req, db=test_db_session)
    child_run = await test_db_session.get(RunModel, result.child_run_id)
    assert child_run is not None
    snapshot = child_run.routing_snapshot_json

    assert snapshot["is_lock_all"] is True
    assert snapshot["explicit_model_override"] == "mock:lock-model-target"
    assert snapshot["reasoning_policy"] == "fixed"
    assert snapshot["reasoning_effort"] == "high"
    child_state = mock_graph.ainvoke.await_args.args[0]
    child_routing = child_state["metadata"]["routing_context_dict"]
    assert child_routing["explicit_model_override"] == "mock:lock-model-target"
    assert child_routing["reasoning_policy"] == "fixed"
    assert child_routing["reasoning_effort"] == "high"


@pytest.mark.asyncio
async def test_delegation_model_lock_preserves_child_reasoning_route(test_db_session: AsyncSession, monkeypatch):
    """A temporary model lock propagates the model but leaves specialist reasoning policy intact."""
    from unittest.mock import AsyncMock, MagicMock
    from app.delegation.runtime import DelegationRuntime
    from app.delegation.types import DelegationRequest

    sess_id = str(uuid.uuid4())
    parent_id = str(uuid.uuid4())
    test_db_session.add(SessionModel(id=sess_id))
    test_db_session.add(RunModel(id=parent_id, session_id=sess_id, user_message="parent root task"))
    await test_db_session.commit()
    mock_graph = AsyncMock()
    mock_graph.aget_state.return_value = MagicMock(next=None)
    mock_graph.ainvoke.return_value = {"messages": [{"role": "assistant", "content": "done"}]}
    monkeypatch.setattr("app.delegation.runtime.get_compiled_graph", AsyncMock(return_value=mock_graph))

    request = DelegationRequest(
        specialist_name="research",
        task_description="Use model lock without overriding research reasoning",
        parent_run_id=parent_id,
        session_id=sess_id,
        context={"is_lock_all": True, "model_override": "mock:locked"},
    )
    result = await DelegationRuntime().delegate(request, db=test_db_session)
    child = await test_db_session.get(RunModel, result.child_run_id)
    assert child is not None
    assert child.routing_snapshot_json["explicit_model_override"] == "mock:locked"
    assert child.routing_snapshot_json["reasoning_policy"] == "adaptive"
    assert child.routing_snapshot_json["reasoning_effort"] == "medium"
    child_state = mock_graph.ainvoke.await_args.args[0]
    child_routing = child_state["metadata"]["routing_context_dict"]
    assert child_routing["explicit_model_override"] == "mock:locked"
    assert child_routing["reasoning_policy"] == "adaptive"
    assert child_routing["reasoning_effort"] == "medium"


@pytest.mark.asyncio
async def test_custom_default_is_unique_and_system_balanced_clears_defaults(test_db_session: AsyncSession):
    from app.api.routes.routing import set_default_routing_profile, DefaultProfileRequest

    test_db_session.add_all([
        RoutingProfileModel(id="default-a", name="A", is_default=True),
        RoutingProfileModel(id="default-b", name="B", is_default=False),
    ])
    await test_db_session.commit()

    await set_default_routing_profile(DefaultProfileRequest(profile_id="default-b"), test_db_session)
    rows = (await test_db_session.execute(select(RoutingProfileModel).order_by(RoutingProfileModel.id))).scalars().all()
    assert [(row.id, row.is_default) for row in rows] == [("default-a", False), ("default-b", True)]
    profile, scope = await resolve_routing_profile(test_db_session)
    assert (profile.id, scope) == ("default-b", "default")

    await set_default_routing_profile(DefaultProfileRequest(profile_id="system-balanced"), test_db_session)
    assert not any(row.is_default for row in (await test_db_session.execute(select(RoutingProfileModel))).scalars().all())
    profile, scope = await resolve_routing_profile(test_db_session)
    assert (profile.id, scope) == ("system-balanced", "system")


@pytest.mark.asyncio
async def test_profile_create_and_update_enforce_single_custom_default(test_db_session: AsyncSession):
    from app.api.routes.routing import create_routing_profile, update_routing_profile

    first = await create_routing_profile(RoutingProfile(id="created-default-a", name="First", is_default=True), test_db_session)
    second = await create_routing_profile(RoutingProfile(id="created-default-b", name="Second", is_default=True), test_db_session)
    assert first.is_default is True
    assert second.is_default is True
    rows = (await test_db_session.execute(select(RoutingProfileModel).where(RoutingProfileModel.is_default.is_(True)))).scalars().all()
    assert [row.id for row in rows] == ["created-default-b"]

    await update_routing_profile("created-default-a", RoutingProfile(id="created-default-a", name="First active default", is_default=True), test_db_session)
    rows = (await test_db_session.execute(select(RoutingProfileModel).where(RoutingProfileModel.is_default.is_(True)))).scalars().all()
    assert [row.id for row in rows] == ["created-default-a"]

    inactive = RoutingProfileModel(id="inactive-default", name="Inactive", is_active=False, is_default=False)
    test_db_session.add(inactive)
    await test_db_session.commit()
    from fastapi import HTTPException
    from app.api.routes.routing import _set_default_profile
    with pytest.raises(HTTPException) as exc:
        await _set_default_profile(test_db_session, "inactive-default")
    assert "inactive" in exc.value.detail.lower()
    await test_db_session.rollback()


@pytest.mark.asyncio
async def test_deleting_routing_profile_clears_assignments_and_restores_inheritance(
    async_client: AsyncClient,
    test_db_session: AsyncSession,
):
    profile = await async_client.post(
        "/v1/routing/profiles",
        json={"id": "delete-assigned-profile", "name": "Assigned profile", "is_default": True},
    )
    assert profile.status_code == 201
    session_id = str(uuid.uuid4())
    test_db_session.add(SessionModel(id=session_id))
    await test_db_session.commit()

    project_assignment = await async_client.post(
        "/v1/routing/assignments/Deletion%20Project?profile_id=delete-assigned-profile"
    )
    session_assignment = await async_client.put(
        f"/v1/routing/sessions/{session_id}", json={"profile_id": "delete-assigned-profile"}
    )
    assert project_assignment.status_code == session_assignment.status_code == 200

    deleted = await async_client.delete("/v1/routing/profiles/delete-assigned-profile")
    assert deleted.status_code == 200
    assert deleted.json()["deleted_profile_id"] == "delete-assigned-profile"

    project = await async_client.get("/v1/routing/assignments/Deletion%20Project")
    session = await async_client.get(f"/v1/routing/sessions/{session_id}")
    assert project.json()["routing_profile_id"] is None
    assert session.json()["routing_profile_id"] is None

    profile, scope = await resolve_routing_profile(
        test_db_session, session_id=session_id, project_name="Deletion Project"
    )
    assert (profile.id, scope) == ("system-balanced", "system")


@pytest.mark.asyncio
async def test_routing_profile_database_index_rejects_a_second_custom_default(test_db_session: AsyncSession):
    from sqlalchemy.exc import IntegrityError

    test_db_session.add(RoutingProfileModel(id="unique-default-a", name="A", is_default=True))
    await test_db_session.commit()

    test_db_session.add(RoutingProfileModel(id="unique-default-b", name="B", is_default=True))
    with pytest.raises(IntegrityError):
        await test_db_session.commit()
    await test_db_session.rollback()

    rows = (await test_db_session.execute(
        select(RoutingProfileModel).where(RoutingProfileModel.is_default.is_(True))
    )).scalars().all()
    assert [row.id for row in rows] == ["unique-default-a"]


def test_adaptive_reasoning_clamps_to_model_max_support():
    """Verify that adaptive reasoning clamps target effort to model's maximum supported reasoning level."""
    meta = {
        "p_medium": ProviderMetadata(
            name="p_medium",
            capabilities=["reasoning"],
            default_model="m_med",
            models=["m_med"],
            reasoning_support={"m_med": "medium"},
        )
    }
    policy = DeterministicRoutingPolicy()
    # Complex task suggests High effort, bounds are Low->High, model max is Medium
    ctx = RoutingContext(
        reasoning_policy=ReasoningPolicy.ADAPTIVE,
        reasoning_effort_min=ReasoningEffort.LOW,
        reasoning_effort_max=ReasoningEffort.HIGH,
        complexity="complex",
    )
    sel = policy.select(context=ctx, available_metadata=meta, default_provider="p_medium")
    assert sel.reasoning_effort_selected == "medium"


def test_adaptive_reasoning_rejects_model_below_profile_minimum():
    """Verify that if a model's max reasoning level falls below profile's minimum required effort, candidate is ineligible."""
    meta = {
        "p_low": ProviderMetadata(
            name="p_low",
            capabilities=["reasoning"],
            default_model="m_low",
            models=["m_low"],
            reasoning_support={"m_low": "low"},
        )
    }
    policy = DeterministicRoutingPolicy()
    # Profile requires at least Medium effort
    ctx = RoutingContext(
        reasoning_policy=ReasoningPolicy.ADAPTIVE,
        reasoning_effort_min=ReasoningEffort.MEDIUM,
        reasoning_effort_max=ReasoningEffort.HIGH,
        complexity="simple",
    )
    with pytest.raises(ReasoningControlUnsupported):
        policy.select(context=ctx, available_metadata=meta, default_provider="p_low")


def test_fixed_reasoning_accepts_levels_up_to_model_max_and_rejects_greater():
    """Verify max-level semantics for fixed reasoning: levels <= model_max are accepted, > model_max rejected."""
    meta = {
        "p_high": ProviderMetadata(
            name="p_high",
            capabilities=["reasoning"],
            default_model="m_high",
            models=["m_high"],
            reasoning_support={"m_high": "high"},
        )
    }
    policy = DeterministicRoutingPolicy()

    # levels <= high must succeed
    for effort in (ReasoningEffort.INSTANT, ReasoningEffort.LOW, ReasoningEffort.MEDIUM, ReasoningEffort.HIGH):
        ctx = RoutingContext(reasoning_effort=effort)
        sel = policy.select(context=ctx, available_metadata=meta, default_provider="p_high")
        assert sel.reasoning_effort_selected == effort.value

    # level > high (i.e. max) must be rejected
    ctx_max = RoutingContext(reasoning_effort=ReasoningEffort.MAX)
    with pytest.raises(ReasoningControlUnsupported):
        policy.select(context=ctx_max, available_metadata=meta, default_provider="p_high")


def test_explicit_override_rejects_known_capability_mismatches_without_fallback():
    """Verify that explicit lock strictly rejects unsupported capabilities with no fallback."""
    meta = {
        "p_mock": ProviderMetadata(
            name="p_mock",
            capabilities=["general"],
            default_model="m_basic",
            models=["m_basic"],
            vision_support={"m_basic": False},
            structured_output_support={"m_basic": False},
            tool_support={"m_basic": "unsupported"},
        ),
        "p_other": ProviderMetadata(
            name="p_other",
            capabilities=["general", "code", "long_context"],
            default_model="m_capable",
            models=["m_capable"],
            vision_support={"m_capable": True},
            structured_output_support={"m_capable": True},
            tool_support={"m_capable": "supported"},
        ),
    }
    policy = DeterministicRoutingPolicy()

    # 1. Vision mismatch
    ctx_vision = RoutingContext(explicit_model_override="p_mock:m_basic", requires_vision=True)
    with pytest.raises(ModelCapabilityMismatch, match="vision"):
        policy.select(context=ctx_vision, available_metadata=meta, default_provider="p_mock")

    # 2. Structured output mismatch
    ctx_struct = RoutingContext(explicit_model_override="p_mock:m_basic", requires_structured_output=True)
    with pytest.raises(ModelCapabilityMismatch, match="structured output"):
        policy.select(context=ctx_struct, available_metadata=meta, default_provider="p_mock")

    # 3. Long context mismatch
    ctx_long = RoutingContext(explicit_model_override="p_mock:m_basic", requires_long_context=True)
    with pytest.raises(ModelCapabilityMismatch, match="long_context"):
        policy.select(context=ctx_long, available_metadata=meta, default_provider="p_mock")

    # 4. Required capability mismatch
    ctx_caps = RoutingContext(explicit_model_override="p_mock:m_basic", required_capabilities=["code"])
    with pytest.raises(ModelCapabilityMismatch, match="required capabilities"):
        policy.select(context=ctx_caps, available_metadata=meta, default_provider="p_mock")

    # 5. Tools mismatch
    ctx_tool = RoutingContext(explicit_model_override="p_mock:m_basic", requires_tools=True)
    with pytest.raises(ModelCapabilityMismatch, match="tool"):
        policy.select(context=ctx_tool, available_metadata=meta, default_provider="p_mock")


def test_explicit_override_fixed_reasoning_cannot_falsely_claim_controlled_high():
    """Verify that explicit lock cannot claim controlled High if model max is Low or fixed_by_model."""
    meta = {
        "p_mock": ProviderMetadata(
            name="p_mock",
            capabilities=["reasoning"],
            default_model="m_low",
            models=["m_low", "m_fixed", "m_unknown"],
            reasoning_support={
                "m_low": "low",
                "m_fixed": "fixed_by_model",
                "m_unknown": "unknown",
            },
        )
    }
    policy = DeterministicRoutingPolicy()

    # Model max is low -> request High must fail
    ctx_high = RoutingContext(explicit_model_override="p_mock:m_low", reasoning_effort=ReasoningEffort.HIGH)
    with pytest.raises(ReasoningControlUnsupported):
        policy.select(context=ctx_high, available_metadata=meta, default_provider="p_mock")

    # Model is fixed_by_model -> request High must fail
    ctx_fixed = RoutingContext(explicit_model_override="p_mock:m_fixed", reasoning_effort=ReasoningEffort.HIGH)
    with pytest.raises(ReasoningControlUnsupported):
        policy.select(context=ctx_fixed, available_metadata=meta, default_provider="p_mock")

    # Model is unknown -> request High must fail
    ctx_unknown = RoutingContext(explicit_model_override="p_mock:m_unknown", reasoning_effort=ReasoningEffort.HIGH)
    with pytest.raises(ReasoningControlUnsupported):
        policy.select(context=ctx_unknown, available_metadata=meta, default_provider="p_mock")


def test_explicit_override_adaptive_returns_fixed_by_model_and_unknown_truthfully():
    """Verify that explicit lock in adaptive mode truthfully reports fixed_by_model and unknown."""
    meta = {
        "p_mock": ProviderMetadata(
            name="p_mock",
            capabilities=["reasoning"],
            default_model="m_fixed",
            models=["m_fixed", "m_unknown", "m_med"],
            reasoning_support={
                "m_fixed": "fixed_by_model",
                "m_unknown": "unknown",
                "m_med": "medium",
            },
        )
    }
    policy = DeterministicRoutingPolicy()

    # Fixed by model
    ctx1 = RoutingContext(explicit_model_override="p_mock:m_fixed", reasoning_policy=ReasoningPolicy.ADAPTIVE)
    sel1 = policy.select(context=ctx1, available_metadata=meta, default_provider="p_mock")
    assert sel1.reasoning_effort_selected == "fixed_by_model"

    # Unknown
    ctx2 = RoutingContext(explicit_model_override="p_mock:m_unknown", reasoning_policy=ReasoningPolicy.ADAPTIVE)
    sel2 = policy.select(context=ctx2, available_metadata=meta, default_provider="p_mock")
    assert sel2.reasoning_effort_selected == "unknown"

    # Controllable medium clamped
    ctx3 = RoutingContext(
        explicit_model_override="p_mock:m_med",
        reasoning_policy=ReasoningPolicy.ADAPTIVE,
        complexity="complex",
        reasoning_effort_min=ReasoningEffort.LOW,
        reasoning_effort_max=ReasoningEffort.HIGH,
    )
    sel3 = policy.select(context=ctx3, available_metadata=meta, default_provider="p_mock")
    assert sel3.reasoning_effort_selected == "medium"


def test_explicit_override_adaptive_rejects_model_below_profile_minimum():
    """Verify that an explicit model lock in Adaptive mode raises ReasoningControlUnsupported
    without fallback when the model's max reasoning falls below profile's minimum required effort.
    """
    meta = {
        "p_low": ProviderMetadata(
            name="p_low",
            capabilities=["reasoning"],
            default_model="m_low",
            models=["m_low"],
            reasoning_support={"m_low": "low"},
        ),
        "p_high": ProviderMetadata(
            name="p_high",
            capabilities=["reasoning"],
            default_model="m_high",
            models=["m_high"],
            reasoning_support={"m_high": "high"},
        ),
    }
    policy = DeterministicRoutingPolicy()

    # Exact model locked: p_low:m_low, Profile requires Medium -> High
    ctx = RoutingContext(
        explicit_model_override="p_low:m_low",
        reasoning_policy=ReasoningPolicy.ADAPTIVE,
        reasoning_effort_min=ReasoningEffort.MEDIUM,
        reasoning_effort_max=ReasoningEffort.HIGH,
        complexity="complex",
    )

    with pytest.raises(ReasoningControlUnsupported) as exc_info:
        policy.select(context=ctx, available_metadata=meta, default_provider="p_low")

    err_msg = str(exc_info.value)
    assert "m_low" in err_msg
    assert "low" in err_msg
    assert "medium" in err_msg


@pytest.mark.asyncio
async def test_fallback_blocked_event_recorded_on_routing_rejection(test_db_session: AsyncSession):
    """Verify that reason_node emits fallback_blocked event when route selection fails."""
    from app.observability.tracer import TraceService
    from app.orchestrator.nodes import reason_node
    from app.models.router import ModelRouter

    run_id = str(uuid.uuid4())
    sess_id = str(uuid.uuid4())
    test_db_session.add(SessionModel(id=sess_id))
    test_db_session.add(RunModel(id=run_id, session_id=sess_id, user_message="blocked test"))
    await test_db_session.commit()

    trace_svc = TraceService(test_db_session)
    mock_router = ModelRouter()
    mock_router._providers.clear()
    mock_router._metadata.clear()
    # Register only a cloud provider
    mock_router.register_provider(
        SpyModelProvider(name="cloud-p", privacy="cloud"),
        ProviderMetadata(name="cloud-p", capabilities=["general"], default_model="m-cloud", models=["m-cloud"], privacy_status="cloud"),
    )

    state = {
        "run_id": run_id,
        "session_id": sess_id,
        "messages": [{"role": "user", "content": "do local work"}],
        "routing_context_dict": {
            "privacy_requirement": "local_only",
            "fallback_policy": "none",
        },
    }

    with pytest.raises(PrivacyBoundaryViolation):
        await reason_node(state, {"configurable": {"trace_service": trace_svc, "model_router": mock_router}})

    # Assert fallback_blocked event was persisted in database
    ev_stmt = select(RunEventModel).where(RunEventModel.run_id == run_id, RunEventModel.event_type == "fallback_blocked")
    ev_res = await test_db_session.execute(ev_stmt)
    ev = ev_res.scalar_one_or_none()
    assert ev is not None
    assert ev.payload["policy"] == "none"
    assert ev.payload["error_type"] == "PrivacyBoundaryViolation"
    assert ev.payload["privacy_boundary"] == "local_only"


def test_required_context_window_filters_known_short_model_before_selection():
    policy = DeterministicRoutingPolicy()
    metadata = {
        "short": ProviderMetadata(
            name="short",
            models=["small"],
            default_model="small",
            context_window=4096,
        ),
        "long": ProviderMetadata(
            name="long",
            models=["large"],
            default_model="large",
            context_window=32768,
        ),
    }

    selection = policy.select(
        RoutingContext(required_context_window=12_000),
        metadata,
        default_provider="short",
    )

    assert selection.provider_name == "long"
    assert selection.model_name == "large"
    assert selection.context_window == 32_768


def test_required_context_window_preserves_unknown_model_limits():
    policy = DeterministicRoutingPolicy()
    metadata = {
        "short": ProviderMetadata(
            name="short",
            models=["small"],
            default_model="small",
            context_window=4096,
        ),
        "unknown": ProviderMetadata(
            name="unknown",
            models=["undiscovered-limit"],
            default_model="undiscovered-limit",
            context_window=None,
        ),
    }

    selection = policy.select(
        RoutingContext(required_context_window=12_000),
        metadata,
        default_provider="short",
    )

    assert selection.provider_name == "unknown"
    assert selection.context_window is None


def test_exact_model_override_rejects_known_insufficient_context_without_fallback():
    policy = DeterministicRoutingPolicy()
    metadata = {
        "short": ProviderMetadata(
            name="short",
            models=["small"],
            default_model="small",
            context_window=4096,
        ),
        "long": ProviderMetadata(
            name="long",
            models=["large"],
            default_model="large",
            context_window=32768,
        ),
    }

    with pytest.raises(ModelCapabilityMismatch, match="below the required"):
        policy.select(
            RoutingContext(
                explicit_model_override="short:small",
                required_context_window=12_000,
            ),
            metadata,
            default_provider="long",
        )


def test_prompt_token_estimate_includes_tool_call_arguments():
    from app.orchestrator.nodes import _estimate_prompt_tokens

    plain = ChatMessage(role=ModelRole.ASSISTANT, content="tool call follows")
    tool_call = ChatMessage(
        role=ModelRole.ASSISTANT,
        content="tool call follows",
        tool_calls=[
            ToolCallRequest(
                id="call-1",
                name="read_file",
                arguments={"path": "workspace", "payload": "x" * 6000},
            )
        ],
    )

    assert _estimate_prompt_tokens([tool_call], []) > _estimate_prompt_tokens([plain], []) + 1_900
