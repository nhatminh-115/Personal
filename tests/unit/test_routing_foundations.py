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
    ReasoningControlUnsupported,
    RoutingConfirmationRequired,
)
from app.db.models import (
    ProjectRoutingAssignmentModel,
    RoutingProfileModel,
    RunEventModel,
    RunModel,
    SessionModel,
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
)
from app.models.mock_provider import MockModelProvider
from app.models.provider import ModelProvider
from app.models.router import ModelRouter
from app.models.routing_policy import DeterministicRoutingPolicy, ProviderMetadata
from app.models.routing_profile import ReasoningConfig, RouteConfig, RoutingProfile
from app.models.routing_resolver import (
    apply_routing_profile_to_context,
    get_system_balanced_profile,
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
    assert data["provider_name"] == "spy-prev"
    assert data["model_name"] == "prev-m"

    # Preview must NOT invoke model provider
    assert spy.generate_call_count == 0


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
