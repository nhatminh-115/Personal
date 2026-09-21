"""Runtime orchestrating execution of delegated specialist tasks."""

import time
import uuid
from typing import Any, Dict, Optional
from langgraph.errors import GraphInterrupt
from langgraph.types import Command, interrupt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import PermissionError, ToolError
from app.core.logging import logger
from app.db.models import DelegationModel, RunModel, RunStatus
from app.delegation.registry import SpecialistRegistry, specialist_registry
from app.delegation.types import DelegationRequest, DelegationResult, SpecialistDefinition
from app.observability.tracer import TraceService
from app.orchestrator.graph import get_compiled_graph
from app.orchestrator.state import AgentState
from app.tools.registry import ToolRegistry, tool_registry
from app.tools.scoped import ScopedToolRegistry


class DelegationRuntime:
    """Manages the lifecycle of specialist child runs delegated by the Root Orchestrator."""

    def __init__(
        self,
        registry: Optional[SpecialistRegistry] = None,
        base_tool_registry: Optional[ToolRegistry] = None,
    ) -> None:
        self.registry = registry or specialist_registry
        self.base_tool_registry = base_tool_registry or tool_registry

    async def delegate(
        self,
        request: DelegationRequest,
        db: AsyncSession,
        services: Optional[Dict[str, Any]] = None,
    ) -> DelegationResult:
        """Execute a specialized sub-task in an isolated, scoped child run."""
        # 1. Lookup specialist definition
        spec = self.registry.get(request.specialist_name)
        if not spec:
            raise ToolError(f"Specialist '{request.specialist_name}' is not registered.")

        # 2. Prevent infinite recursion or unconstrained specialist->specialist swarms
        if request.context.get("is_specialist"):
            raise PermissionError(
                f"Delegation rejected: Agent '{request.context.get('specialist_name', 'specialist')}' "
                "is already a specialist and cannot delegate to other specialists."
            )

        trace_service = services.get("trace_service") if services else TraceService(db)

        # 3. Idempotent check: lookup existing delegation for (parent_run_id, parent_tool_call_id)
        existing_delegation: Optional[DelegationModel] = None
        if request.parent_tool_call_id:
            del_stmt = select(DelegationModel).where(
                DelegationModel.parent_run_id == request.parent_run_id,
                DelegationModel.parent_tool_call_id == request.parent_tool_call_id,
            )
            del_res = await db.execute(del_stmt)
            existing_delegation = del_res.scalar_one_or_none()

        if existing_delegation:
            child_run_id = existing_delegation.child_run_id
            child_run = await db.get(RunModel, child_run_id)
            logger.info(
                f"Reusing existing delegation '{existing_delegation.id}' for child run '{child_run_id}' (status: {existing_delegation.status})",
                extra={"parent_run_id": request.parent_run_id, "child_run_id": child_run_id},
            )
            effective_status = existing_delegation.status
            if child_run and child_run.status in (RunStatus.COMPLETED.value, RunStatus.FAILED.value):
                effective_status = child_run.status
            if effective_status in (RunStatus.COMPLETED.value, RunStatus.FAILED.value):
                summary = (child_run.final_response if child_run and child_run.final_response else existing_delegation.result_summary) or ""
                if trace_service:
                    events = await trace_service.get_run_events(request.parent_run_id)
                    if not any(e.event_type == "delegation_completed" for e in events):
                        await trace_service.record_event(
                            run_id=request.parent_run_id,
                            session_id=request.session_id,
                            event_type="delegation_completed",
                            payload={
                                "child_run_id": child_run_id,
                                "specialist": spec.name,
                                "status": effective_status,
                                "summary": summary,
                                "steps": 0,
                            },
                        )
                return DelegationResult(
                    specialist_name=spec.name,
                    child_run_id=child_run_id,
                    status=effective_status,
                    summary=summary,
                    steps_taken=0,
                )
            created_new = False
        else:
            from app.models.routing_resolver import apply_routing_profile_to_context
            from app.db.models import RoutingProfileModel
            from app.models.routing_profile import RoutingProfile
            from app.models.base import RoutingContext
            
            candidate_child_run_id = str(uuid.uuid4())
            
            # Resolve child routing profile
            profile_id = (request.context or {}).get("profile_id")
            winning_scope = (request.context or {}).get("winning_scope", "system")
            is_lock_all = (request.context or {}).get("is_lock_all", False)
            model_override = (request.context or {}).get("model_override") if is_lock_all else None
            
            child_rc = RoutingContext(
                session_id=request.session_id,
                run_id=candidate_child_run_id,
                is_lock_all=is_lock_all,
            )
            
            profile = None
            if profile_id:
                profile_res = await db.execute(select(RoutingProfileModel).where(RoutingProfileModel.id == profile_id))
                db_profile = profile_res.scalar_one_or_none()
                if db_profile and db_profile.is_active:
                    profile = RoutingProfile(**db_profile.routes_json, id=db_profile.id, name=db_profile.name, version=db_profile.version)
            
            if not profile:
                from app.models.routing_resolver import get_system_balanced_profile
                profile = get_system_balanced_profile()
                winning_scope = "system"
                
            child_rc = apply_routing_profile_to_context(
                profile,
                role=spec.name,
                context=child_rc,
                winning_scope=winning_scope,
                message_override=model_override,
            )
            
            request.context = request.context or {}
            request.context["routing_context_dict"] = child_rc.model_dump()
            
            try:
                async with db.begin_nested():
                    child_run = RunModel(
                        id=candidate_child_run_id,
                        session_id=request.session_id,
                        user_message=f"[Specialist: {spec.name}] {request.task_description}",
                        parent_run_id=request.parent_run_id,
                        status=RunStatus.RUNNING.value,
                        routing_snapshot_json={
                            "profile_id": profile.id,
                            "profile_version": profile.version,
                            "winning_scope": winning_scope,
                            "role": spec.name,
                            "is_lock_all": child_rc.is_lock_all,
                            "privacy_policy": child_rc.privacy_requirement.value,
                            "fallback_policy": child_rc.fallback_policy.value,
                            "explicit_model_override": child_rc.explicit_model_override,
                            "reasoning_policy": child_rc.reasoning_policy.value if child_rc.reasoning_policy else None,
                            "reasoning_effort": child_rc.reasoning_effort.value if child_rc.reasoning_effort else None,
                        }
                    )
                    db.add(child_run)

                    delegation_rec = DelegationModel(
                        parent_run_id=request.parent_run_id,
                        parent_tool_call_id=request.parent_tool_call_id,
                        child_run_id=candidate_child_run_id,
                        specialist_name=spec.name,
                        status=RunStatus.RUNNING.value,
                    )
                    db.add(delegation_rec)
                    await db.flush()
                await db.commit()
                child_run_id = candidate_child_run_id
                created_new = True
                if trace_service:
                    await trace_service.record_event(
                        run_id=candidate_child_run_id,
                        session_id=request.session_id,
                        event_type="routing_profile_resolved",
                        payload=child_run.routing_snapshot_json,
                    )
            except IntegrityError:
                # Concurrent race condition: another caller already inserted the delegation!
                # Savepoint rollback automatically cleaned candidate child_run and delegation_rec.
                logger.info(
                    f"Concurrent race detected on delegation creation for ({request.parent_run_id}, {request.parent_tool_call_id}). Resolving to existing winner."
                )
                del_stmt = select(DelegationModel).where(
                    DelegationModel.parent_run_id == request.parent_run_id,
                    DelegationModel.parent_tool_call_id == request.parent_tool_call_id,
                )
                del_res = await db.execute(del_stmt)
                existing_delegation = del_res.scalar_one_or_none()
                if not existing_delegation:
                    raise
                child_run_id = existing_delegation.child_run_id
                child_run = await db.get(RunModel, child_run_id)
                effective_status = existing_delegation.status
                if child_run and child_run.status in (RunStatus.COMPLETED.value, RunStatus.FAILED.value):
                    effective_status = child_run.status
                if effective_status in (RunStatus.COMPLETED.value, RunStatus.FAILED.value):
                    summary = (child_run.final_response if child_run and child_run.final_response else existing_delegation.result_summary) or ""
                    return DelegationResult(
                        specialist_name=spec.name,
                        child_run_id=child_run_id,
                        status=effective_status,
                        summary=summary,
                        steps_taken=0,
                    )
                created_new = False

        # 4. Trace delegation start EXACTLY ONCE on initial creation
        if created_new and trace_service:
            await trace_service.record_event(
                run_id=request.parent_run_id,
                session_id=request.session_id,
                event_type="delegation_started",
                payload={
                    "specialist": spec.name,
                    "child_run_id": child_run_id,
                    "task": request.task_description,
                },
            )
            await trace_service.record_event(
                run_id=child_run_id,
                session_id=request.session_id,
                event_type="request_received",
                payload={
                    "parent_run_id": request.parent_run_id,
                    "specialist": spec.name,
                    "task": request.task_description,
                },
            )

        # 5. Build Scoped Tool Registry for the specialist
        scoped_tools = ScopedToolRegistry(self.base_tool_registry, spec.allowed_tools)

        # 6. Prepare Child Initial AgentState
        from app.models.base import ChatMessage, ModelRole

        initial_state: AgentState = {
            "session_id": request.session_id,
            "run_id": child_run_id,
            "user_message": request.task_description,
            "retrieved_context": [],
            "messages": [
                ChatMessage(role=ModelRole.SYSTEM, content=spec.system_prompt_template).model_dump(),
                ChatMessage(role=ModelRole.USER, content=request.task_description).model_dump(),
            ],
            "step_number": 0,
            "max_steps": request.max_steps or spec.max_steps,
            "total_tool_calls": 0,
            "max_tool_calls": 25,
            "consecutive_failures": 0,
            "max_consecutive_failures": 3,
            "deadline_seconds": (time.time() + float(request.timeout_seconds or spec.timeout_seconds)) if (request.timeout_seconds or spec.timeout_seconds) else None,
            "start_time": time.time(),
            "delegation_context": {
                "is_specialist": True,
                "specialist_name": spec.name,
                "parent_run_id": request.parent_run_id,
                "task_type": spec.name,
                "model_override": (request.context or {}).get("model_override"),
            },
            "metadata": {
                "task_type": spec.name,
                "required_capabilities": spec.preferred_model_capabilities,
                **(request.context or {}),
            },
            "project_name": request.context.get("project_name") if request.context else None,
            "research_state": {
                "goal": {
                    "goal_id": f"goal_{child_run_id[:8]}",
                    "user_query": request.task_description,
                    "project_name": request.context.get("project_name") if request.context else None,
                },
                "queries": [],
                "sources": {},
                "evidence": {},
                "claims": [],
            } if spec.name == "research" else None,
        }

        # 7. Execute compiled graph with injected scoped registry
        active_research_provider = services.get("research_provider") if services else None
        if spec.name == "research" and not active_research_provider:
            from app.research.factory import create_research_provider
            active_research_provider = create_research_provider()

        graph = await get_compiled_graph()
        child_config = {
            "configurable": {
                "thread_id": child_run_id,
                "db": db,
                "tool_registry": scoped_tools,
                "memory_service": services.get("memory_service") if services else None,
                "approval_service": services.get("approval_service") if services else None,
                "trace_service": trace_service,
                "model_router": services.get("model_router") if services else None,
                "research_provider": active_research_provider,
            }
        }

        try:
            # Check if child graph is already initialized/suspended
            child_snapshot = await graph.aget_state(child_config)
            if child_snapshot.next:
                # Interrupted / paused graph being resumed from durable checkpoint
                final_state = await graph.ainvoke(Command(resume={}), config=child_config)
            else:
                final_state = await graph.ainvoke(initial_state, config=child_config)

            # Check if child graph was suspended for human approval
            post_child_snapshot = await graph.aget_state(child_config)
            if post_child_snapshot.next:
                # Child graph is suspended at an interrupt
                intr_list = post_child_snapshot.tasks[0].interrupts if post_child_snapshot.tasks else []
                interrupt_val = intr_list[0].value if intr_list else {}
                approval_id = interrupt_val.get("approval_id")
                tool_name = interrupt_val.get("tool_name")
                risk_level = interrupt_val.get("risk_level")

                child_run.status = RunStatus.WAITING_FOR_APPROVAL.value
                child_run.final_response = f"Specialist requires approval for '{tool_name}' ({risk_level}). Approval ID: {approval_id}"

                del_stmt = select(DelegationModel).where(DelegationModel.child_run_id == child_run_id)
                del_res = await db.execute(del_stmt)
                del_rec = del_res.scalar_one_or_none()
                if del_rec:
                    del_rec.status = RunStatus.WAITING_FOR_APPROVAL.value
                    del_rec.pending_approval_id = approval_id
                await db.commit()

                # Bubble up interrupt to parent Personal Orchestrator
                parent_resume = interrupt({
                    "approval_id": approval_id,
                    "tool_name": tool_name,
                    "risk_level": risk_level,
                    "specialist_name": spec.name,
                    "child_run_id": child_run_id,
                })

                # Resume child graph with decision only if it is still suspended and not already completed
                child_snap = await graph.aget_state(child_config)
                if child_snap.next and (not parent_resume or parent_resume.get("specialist_status") not in (RunStatus.COMPLETED.value, RunStatus.FAILED.value)):
                    final_state = await graph.ainvoke(Command(resume=parent_resume), config=child_config)
                else:
                    final_state = child_snap.values
            else:
                parent_resume = {}

            status = (parent_resume.get("specialist_status") if (isinstance(parent_resume, dict) and parent_resume.get("specialist_status")) else None) or final_state.get("execution_status", "completed")
            summary = (parent_resume.get("summary") if (isinstance(parent_resume, dict) and parent_resume.get("summary")) else None) or final_state.get("final_response") or "Specialist execution finished."
            error = final_state.get("error_message") or final_state.get("termination_reason")
            steps = final_state.get("step_number", 0)

            artifacts_dict: Dict[str, Any] = {}
            if spec.name == "research" and final_state.get("research_state"):
                from app.research.models import ClaimType, ResearchResult, ResearchState, ResearchStatus, SourceStatus
                from app.research.provenance import CitationValidator, validate_research_state

                r_state = ResearchState.from_dict(final_state["research_state"])
                artifacts_dict["research_state"] = r_state.to_dict()

                # Filter and rank closest valid sources
                valid_sources = [s for s in r_state.sources.values() if s.status != SourceStatus.REJECTED]
                valid_sources.sort(key=lambda s: s.relevance_score, reverse=True)

                # Validate all claims using canonical validate_research_state helper
                citation_eval = validate_research_state(r_state, strict=False)

                # Research status semantics:
                # Factual findings may be verified, but if no validated gap claim exists or corpus is limited fixture,
                # overall research status remains insufficient_evidence.
                has_validated_gap = any(
                    c.verification_status == "verified" and any(w in c.claim_text.lower() for w in ["gap", "novelty", "unaddressed"])
                    for c in r_state.claims
                )
                r_status = ResearchStatus.COMPLETED if (citation_eval["is_valid"] and has_validated_gap) else ResearchStatus.INSUFFICIENT_EVIDENCE
                status = "completed"

                uncertainties = [c.claim_text for c in r_state.claims if c.claim_type == ClaimType.HYPOTHESIS]
                closest_titles = [f"{s.title} ({s.canonical_id})" for s in valid_sources[:3]]
                verified_facts = [c.claim_text for c in r_state.claims if c.claim_type == ClaimType.SOURCE_SUPPORTED_FACT and c.verification_status == "verified"]
                inferences = [c.claim_text for c in r_state.claims if c.claim_type == ClaimType.SPECIALIST_INFERENCE and c.verification_status != "unsupported"]
                hypotheses = [c.claim_text for c in r_state.claims if c.claim_type == ClaimType.HYPOTHESIS and c.verification_status != "unsupported"]

                # Render dynamic synthesis strictly from verified ResearchResult contents
                lines = [
                    "[RESEARCH SPECIALIST - VALIDATED SYNTHESIS]",
                    f"Research Status: {r_status.value}",
                    f"Goal: {r_state.goal.user_query if r_state.goal else request.task_description}",
                    f"Search Iterations: {len(r_state.queries)} queries recorded across {r_state.current_iteration} iteration(s).",
                    f"Inspected Sources: {len(r_state.inspected_source_ids)} source(s) examined in Methods sections.",
                    f"Closest Prior Art: {', '.join(closest_titles) if closest_titles else 'None found'}.",
                    "\nVerified Factual Findings (Backed by Grounded Evidence):",
                ]
                if verified_facts:
                    for idx, vf in enumerate(verified_facts, 1):
                        lines.append(f"  {idx}. {vf}")
                else:
                    lines.append("  (No verified factual claims established)")

                if inferences:
                    lines.append("\nSpecialist Inferences:")
                    for idx, inf in enumerate(inferences, 1):
                        lines.append(f"  {idx}. {inf}")

                if hypotheses:
                    lines.append("\nHypotheses & Next Steps:")
                    for idx, hyp in enumerate(hypotheses, 1):
                        lines.append(f"  {idx}. {hyp}")

                lines.append("\nIdentified Research Gap:")
                gap_claims = [
                    c.claim_text for c in r_state.claims
                    if c.verification_status == "verified" and any(w in c.claim_text.lower() for w in ["gap", "novelty", "unaddressed", "no literature"])
                ]
                if gap_claims:
                    for gc in gap_claims:
                        lines.append(f"- {gc}")
                else:
                    lines.append("No evidence-backed research gap can be established from the current corpus.")

                dynamic_synthesis = "\n".join(lines)

                research_result = ResearchResult(
                    goal=r_state.goal,
                    executive_synthesis=dynamic_synthesis,
                    key_findings=verified_facts,
                    closest_sources=valid_sources[:5],
                    evidence_map=r_state.evidence,
                    claims=r_state.claims,
                    uncertainties=uncertainties,
                    unresolved_questions=[],
                    recommended_next_searches=[],
                    memory_candidates=[{"project_name": r_state.goal.project_name if r_state.goal else None, "claims_count": len(r_state.claims)}] if r_state.claims else [],
                    status=r_status,
                )

                artifacts_dict["research_result"] = research_result.model_dump()
                summary = dynamic_synthesis
            elif final_state.get("research_state"):
                artifacts_dict["research_state"] = final_state["research_state"]

            # Update child run in database
            child_run.status = status
            child_run.final_response = summary
            child_run.error_message = error

            # Update delegation record
            del_stmt = select(DelegationModel).where(DelegationModel.child_run_id == child_run_id)
            del_res = await db.execute(del_stmt)
            del_rec = del_res.scalar_one_or_none()
            if del_rec:
                del_rec.status = status
                del_rec.result_summary = summary
                del_rec.pending_approval_id = None
            await db.commit()

            if trace_service:
                await trace_service.record_event(
                    run_id=request.parent_run_id,
                    session_id=request.session_id,
                    event_type="delegation_completed",
                    payload={
                        "child_run_id": child_run_id,
                        "specialist": spec.name,
                        "status": status,
                        "summary": summary,
                        "steps": steps,
                    },
                )

            return DelegationResult(
                specialist_name=spec.name,
                child_run_id=child_run_id,
                status=status,
                summary=summary,
                artifacts=artifacts_dict,
                steps_taken=steps,
                error=error,
            )

        except GraphInterrupt:
            raise
        except Exception as exc:
            logger.error(f"Specialist child run '{child_run_id}' failed: {exc}", exc_info=True)
            child_run.status = RunStatus.FAILED.value
            child_run.error_message = str(exc)

            del_stmt = select(DelegationModel).where(DelegationModel.child_run_id == child_run_id)
            del_res = await db.execute(del_stmt)
            del_rec = del_res.scalar_one_or_none()
            if del_rec:
                del_rec.status = RunStatus.FAILED.value
                del_rec.result_summary = str(exc)
            await db.commit()

            if trace_service:
                await trace_service.record_event(
                    run_id=request.parent_run_id,
                    session_id=request.session_id,
                    event_type="delegation_failed",
                    payload={
                        "child_run_id": child_run_id,
                        "specialist": spec.name,
                        "error": str(exc),
                    },
                )

            return DelegationResult(
                specialist_name=spec.name,
                child_run_id=child_run_id,
                status="failed",
                summary="Specialist failed due to an execution error.",
                steps_taken=0,
                error=str(exc),
            )


# Global singleton runtime
delegation_runtime = DelegationRuntime()
