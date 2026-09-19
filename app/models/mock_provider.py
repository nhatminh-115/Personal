"""Deterministic mock model provider for automated testing and local verification."""

import re
import uuid
from typing import List, Optional
from app.models.base import (
    ChatMessage,
    ModelRequest,
    ModelResponse,
    ModelRole,
    ModelUsage,
    ToolCallRequest,
)
from app.models.provider import ModelProvider


class MockModelProvider(ModelProvider):
    """Deterministic, programmable mock model provider."""

    def __init__(self, default_response: Optional[str] = None) -> None:
        self._name = "mock"
        self._default_response = default_response or "This is a deterministic mock response from AURA."
        self._queued_responses: List[ModelResponse] = []
        self._call_history: List[ModelRequest] = []

    @property
    def name(self) -> str:
        return self._name

    def queue_response(self, response: ModelResponse) -> None:
        """Queue an explicit response to be returned on the next generate() call."""
        self._queued_responses.append(response)

    def clear_queue(self) -> None:
        self._queued_responses.clear()

    @property
    def call_history(self) -> List[ModelRequest]:
        return self._call_history

    async def generate(self, request: ModelRequest) -> ModelResponse:
        self._call_history.append(request)

        # 1. Return queued response if available
        if self._queued_responses:
            return self._queued_responses.pop(0)

        # 2. Inspect the latest message to decide mock behavior
        if not request.messages:
            return ModelResponse(
                content=self._default_response,
                usage=ModelUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20),
                finish_reason="stop",
            )

        latest_msg = request.messages[-1]

        # Check if this request is inside the Coding Specialist sub-agent
        is_coding_specialist = any("Coding Specialist" in m.content for m in request.messages if m.role == ModelRole.SYSTEM)
        if not is_coding_specialist and request.routing_context and request.routing_context.task_type == "coding":
            is_coding_specialist = True

        # Check if this request is inside the Research Specialist sub-agent
        is_research_specialist = any("Research Specialist" in m.content for m in request.messages if m.role == ModelRole.SYSTEM)
        if not is_research_specialist and request.routing_context and request.routing_context.task_type == "research":
            is_research_specialist = True

        tool_msgs = [m for m in request.messages if m.role == ModelRole.TOOL]
        user_msgs = [m for m in request.messages if m.role == ModelRole.USER]
        content = (user_msgs[-1].content if user_msgs else latest_msg.content).strip()

        # Multi-step loop for Research Specialist
        if is_research_specialist and request.tools:
            # Step 1: Issue initial search query
            if len(tool_msgs) == 0:
                return ModelResponse(
                    content="Issuing initial literature search query to discover stateful LLM architecture literature...",
                    tool_calls=[
                        ToolCallRequest(
                            id=f"call_{uuid.uuid4().hex[:8]}",
                            name="research_search",
                            arguments={"query": "stateful LLM execution multi-turn architecture", "search_type": "broad"},
                        )
                    ],
                    finish_reason="tool_calls",
                )
            # Step 2: Inspect methods of closest candidate (Paper 1: src_stateful_graph_2023)
            elif len(tool_msgs) == 1:
                return ModelResponse(
                    content="Discovered candidate sources. Discarding irrelevant attention pruning paper. Inspecting Methods section of closest overlap candidate src_stateful_graph_2023...",
                    tool_calls=[
                        ToolCallRequest(
                            id=f"call_{uuid.uuid4().hex[:8]}",
                            name="read_document_section",
                            arguments={"source_id": "src_stateful_graph_2023", "section_name": "methods"},
                        )
                    ],
                    finish_reason="tool_calls",
                )
            # Step 3: Extract evidence from Paper 1
            elif len(tool_msgs) == 2:
                return ModelResponse(
                    content="Inspected Paper 1 methods. Extracting evidence regarding ephemeral in-memory state and lack of durable checkpointing...",
                    tool_calls=[
                        ToolCallRequest(
                            id=f"call_{uuid.uuid4().hex[:8]}",
                            name="extract_evidence",
                            arguments={
                                "source_id": "src_stateful_graph_2023",
                                "locator": "Section: methods",
                                "extracted_text": "State management is ephemeral: all graph nodes reside purely in memory and do not implement persistent crash-safe database checkpointing or per-tool human approval interruptions.",
                                "summary": "Demonstrates Paper 1 uses in-memory graph but lacks crash-safe persistence and approvals.",
                                "confidence": 0.95,
                            },
                        )
                    ],
                    finish_reason="tool_calls",
                )
            # Step 4: Conduct second search iteration for durable checkpointing
            elif len(tool_msgs) == 3:
                return ModelResponse(
                    content="Identified research gap in Paper 1 (ephemeral memory only). Conducting second search iteration for durable checkpointing architectures...",
                    tool_calls=[
                        ToolCallRequest(
                            id=f"call_{uuid.uuid4().hex[:8]}",
                            name="research_search",
                            arguments={"query": "durable stateful agent checkpointing resume", "search_type": "closest_overlap"},
                        )
                    ],
                    finish_reason="tool_calls",
                )
            # Step 5: Inspect methods of Paper 2 (src_pipeline_checkpoint_2024)
            elif len(tool_msgs) == 4:
                return ModelResponse(
                    content="Discovered candidate Paper 2 with durable checkpointing. Inspecting Methods section of src_pipeline_checkpoint_2024...",
                    tool_calls=[
                        ToolCallRequest(
                            id=f"call_{uuid.uuid4().hex[:8]}",
                            name="read_document_section",
                            arguments={"source_id": "src_pipeline_checkpoint_2024", "section_name": "methods"},
                        )
                    ],
                    finish_reason="tool_calls",
                )
            # Step 6: Extract evidence from Paper 2
            elif len(tool_msgs) == 5:
                return ModelResponse(
                    content="Inspected Paper 2 methods. Extracting evidence regarding batch pipeline write-ahead logs vs interactive approvals...",
                    tool_calls=[
                        ToolCallRequest(
                            id=f"call_{uuid.uuid4().hex[:8]}",
                            name="extract_evidence",
                            arguments={
                                "source_id": "src_pipeline_checkpoint_2024",
                                "locator": "Section: methods",
                                "extracted_text": "The architecture implements transactional write-ahead checkpoints for sequential batch pipelines. Execution state is persisted to a durable datastore at stage boundaries.",
                                "summary": "Paper 2 implements pipeline checkpoints but lacks human approval gates and interactive conversational memory.",
                                "confidence": 0.95,
                            },
                        )
                    ],
                    finish_reason="tool_calls",
                )
            # Step 7: Record research claim
            elif len(tool_msgs) == 6:
                # Dynamically extract all real evidence IDs produced by previous extract_evidence calls
                dynamic_ev_ids = []
                for msg in tool_msgs:
                    for ev_match in re.findall(r"Evidence '(ev_[a-zA-Z0-9]+)'", msg.content):
                        if ev_match not in dynamic_ev_ids:
                            dynamic_ev_ids.append(ev_match)

                return ModelResponse(
                    content="Recording verified factual claim backed by extracted evidence from Paper 1 and Paper 2...",
                    tool_calls=[
                        ToolCallRequest(
                            id=f"call_{uuid.uuid4().hex[:8]}",
                            name="record_research_claim",
                            arguments={
                                "claim_text": "Chen & Davis (2023) maintains graph state in memory but omits persistent checkpointing and interactive approvals, while Mendez & Rostova (2024) provides batch checkpointing without human approval loops.",
                                "claim_type": "source_supported_fact",
                                "evidence_ids": dynamic_ev_ids or ["ev_fallback_fail"],
                            },
                        )
                    ],
                    finish_reason="tool_calls",
                )
            # Step 8: Save research finding to project memory
            elif len(tool_msgs) == 7:
                dynamic_ev_ids = []
                for msg in tool_msgs:
                    for ev_match in re.findall(r"Evidence '(ev_[a-zA-Z0-9]+)'", msg.content):
                        if ev_match not in dynamic_ev_ids:
                            dynamic_ev_ids.append(ev_match)

                return ModelResponse(
                    content="Saving synthesized prior art finding and research gap to project memory Atlas_Architecture...",
                    tool_calls=[
                        ToolCallRequest(
                            id=f"call_{uuid.uuid4().hex[:8]}",
                            name="save_research_finding",
                            arguments={
                                "project_name": "Atlas_Architecture",
                                "key": "prior_art_stateful_execution",
                                "finding_content": "Prior art review: Chen & Davis (2023) provides in-memory state but lacks durable recovery; Mendez & Rostova (2024) provides batch checkpointing without human approval loops. Our proposed architecture occupies a verified research gap combining durable checkpointing with interactive per-tool approvals.",
                                "evidence_ids": dynamic_ev_ids or ["ev_fallback_fail"],
                                "source_references": ["arxiv:2308.1001", "arxiv:2401.5502"],
                            },
                        )
                    ],
                    finish_reason="tool_calls",
                )
            # Step 9: Return final structured synthesis
            else:
                return ModelResponse(
                    content=(
                        "[RESEARCH SPECIALIST - COMPLETED]\n\n"
                        "Executive Synthesis:\n"
                        "Investigated prior art for stateful LLM agent architectures. Identified two closest related works in the literature.\n\n"
                        "Technical Comparison:\n"
                        "1. Chen & Davis (2023) [arxiv:2308.1001]:\n"
                        "   - Mechanism: In-memory execution graphs for multi-turn state.\n"
                        "   - Exact Overlap: Graph-based state container coordinating agent reasoning across sequential turns.\n"
                        "   - Exact Difference: Ephemeral memory only; explicitly lacks durable database checkpointing and per-tool human approval gates.\n"
                        "2. Mendez & Rostova (2024) [arxiv:2401.5502]:\n"
                        "   - Mechanism: Transactional write-ahead log checkpointing for fault-tolerant agents.\n"
                        "   - Exact Overlap: Durable state persistence across process failure and network disruption.\n"
                        "   - Exact Difference: Batch pipeline orientation; lacks interactive human approval loops and conversational context memory.\n\n"
                        "Conclusion & Research Gap:\n"
                        "No identical match found in the searched corpus. The combination of durable per-tool checkpointing with interactive human approval suspension represents an evidence-backed architectural gap."
                    ),
                    finish_reason="stop",
                )

        # Multi-step loop for Coding Specialist
        if is_coding_specialist and request.tools:
            tool_names = {t.name for t in request.tools}
            # Step 1: Run tests first to inspect/reproduce failure
            if len(tool_msgs) == 0:
                target_tool = "sandbox_shell_execute" if "sandbox_shell_execute" in tool_names else "sandbox_python_execute"
                arg = {"command": "pytest"} if target_tool == "sandbox_shell_execute" else {"code": "assert 1 == 1"}
                return ModelResponse(
                    content="Running test suite in isolated sandbox to diagnose issues...",
                    tool_calls=[ToolCallRequest(id=f"call_{uuid.uuid4().hex[:8]}", name=target_tool, arguments=arg)],
                    finish_reason="tool_calls",
                )
            latest_tool = tool_msgs[-1]
            # Step 2: Read source file after observing test failure
            if len(tool_msgs) == 1 and latest_tool.name in {"sandbox_shell_execute", "sandbox_python_execute"}:
                out = latest_tool.content.lower()
                if "not found" in out or "127" in out:
                    return ModelResponse(
                        content=f"Coding Specialist aborted: Environment error executing tests: {latest_tool.content}",
                        finish_reason="stop",
                    )
                return ModelResponse(
                    content="Observed test failure in sandbox. Diagnosing root cause: inspecting source code...",
                    tool_calls=[ToolCallRequest(id=f"call_{uuid.uuid4().hex[:8]}", name="read_workspace_file", arguments={"path": "calculator.py"})],
                    finish_reason="tool_calls",
                )
            # Step 3: Write fix after reading buggy code
            elif len(tool_msgs) == 2 and latest_tool.name == "read_workspace_file":
                return ModelResponse(
                    content="Identified bug in calculator.py: applying code patch...",
                    tool_calls=[ToolCallRequest(
                        id=f"call_{uuid.uuid4().hex[:8]}",
                        name="write_workspace_file",
                        arguments={"path": "calculator.py", "content": "def add(a, b):\n    return a + b\n"},
                    )],
                    finish_reason="tool_calls",
                )
            # Step 4: Re-run tests to verify fix
            elif len(tool_msgs) == 3 and latest_tool.name == "write_workspace_file":
                return ModelResponse(
                    content="Code patch written to workspace. Verifying fix by re-running test suite in sandbox...",
                    tool_calls=[ToolCallRequest(id=f"call_{uuid.uuid4().hex[:8]}", name="sandbox_shell_execute", arguments={"command": "pytest"})],
                    finish_reason="tool_calls",
                )
            # Step 5: Inspect actual validation test result
            else:
                out = latest_tool.content.lower()
                is_passing = ("passed" in out) and ("failed" not in out) and ("error" not in out)
                if is_passing:
                    return ModelResponse(
                        content="Specialist successfully diagnosed and fixed bug in calculator.py. Test suite is now green (1 passed).",
                        finish_reason="stop",
                    )
                else:
                    return ModelResponse(
                        content=f"Specialist validation failed: test did not pass. Output: {latest_tool.content}",
                        finish_reason="stop",
                    )

        # Personal Orchestrator Root Delegation
        if any(t.name == "delegate_task" for t in (request.tools or [])):
            if ("fix" in content.lower() and ("test" in content.lower() or "atlas" in content.lower())) or "delegate to coding" in content.lower():
                if not tool_msgs:
                    return ModelResponse(
                        content="Delegating software diagnosis and repair to Coding Specialist...",
                        tool_calls=[
                            ToolCallRequest(
                                id=f"call_{uuid.uuid4().hex[:8]}",
                                name="delegate_task",
                                arguments={
                                    "specialist_name": "coding",
                                    "task_description": content,
                                    "context": {"project_name": "Atlas"},
                                },
                            )
                        ],
                        finish_reason="tool_calls",
                    )
                else:
                    return ModelResponse(
                        content=f"Personal Orchestrator: {tool_msgs[-1].content}",
                        finish_reason="stop",
                    )
            elif ("research" in content.lower() or "investigate" in content.lower() or "prior work" in content.lower() or "related work" in content.lower() or "closest papers" in content.lower() or "papers" in content.lower()):
                if not tool_msgs:
                    return ModelResponse(
                        content="Delegating literature review and prior art investigation to Research Specialist...",
                        tool_calls=[
                            ToolCallRequest(
                                id=f"call_{uuid.uuid4().hex[:8]}",
                                name="delegate_task",
                                arguments={
                                    "specialist_name": "research",
                                    "task_description": content,
                                    "context": {"project_name": "Atlas_Architecture"},
                                },
                            )
                        ],
                        finish_reason="tool_calls",
                    )
                else:
                    return ModelResponse(
                        content=f"Personal Orchestrator Research Synthesis:\nBased on the Research Specialist investigation:\n{tool_msgs[-1].content}",
                        finish_reason="stop",
                    )

        # If latest message is a TOOL result or contains recent tool outputs, summarize it
        if tool_msgs and latest_msg.role == ModelRole.TOOL:
            combined_tool_output = " | ".join(m.content for m in tool_msgs)
            return ModelResponse(
                content=f"Based on the tool output: {combined_tool_output}",
                usage=ModelUsage(prompt_tokens=25, completion_tokens=15, total_tokens=40),
                finish_reason="stop",
            )

        # Check for tool invocations requested by user query
        # 1. MCP Read Tool: "Read/query metric <name>"
        metric_match = re.search(r"(?:read|query|get)\s+metric\s+([^\s]+)", content, re.IGNORECASE)
        if metric_match and request.tools:
            metric_tool = next((t for t in request.tools if "read_metric" in t.name), None)
            if metric_tool:
                return ModelResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id=f"call_{uuid.uuid4().hex[:8]}",
                            name=metric_tool.name,
                            arguments={"metric_name": metric_match.group(1).strip("\"'")},
                        )
                    ],
                    usage=ModelUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
                    finish_reason="tool_calls",
                )

        # 2. "Read <path>" or "Read file <path>"
        read_match = re.search(r"read\s+(?:file\s+)?(?!metric\b)([^\s]+)", content, re.IGNORECASE)
        if read_match and request.tools and any(t.name == "read_workspace_file" for t in request.tools):
            path = read_match.group(1).strip("\"'")
            return ModelResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id=f"call_{uuid.uuid4().hex[:8]}",
                        name="read_workspace_file",
                        arguments={"path": path},
                    )
                ],
                usage=ModelUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
                finish_reason="tool_calls",
            )

        # 3. "Write <content> to <path>"
        write_match = re.search(r"write\s+(.*?)\s+to\s+([^\s]+)", content, re.IGNORECASE)
        if write_match and request.tools and any(t.name == "write_workspace_file" for t in request.tools):
            text_to_write = write_match.group(1).strip("\"'")
            path = write_match.group(2).strip("\"'")
            return ModelResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id=f"call_{uuid.uuid4().hex[:8]}",
                        name="write_workspace_file",
                        arguments={"path": path, "content": text_to_write},
                    )
                ],
                usage=ModelUsage(prompt_tokens=25, completion_tokens=12, total_tokens=37),
                finish_reason="tool_calls",
            )

        # 4. "List files" or "List directory"
        if re.search(r"list\s+(?:workspace\s+)?files", content, re.IGNORECASE) and request.tools and any(t.name == "list_workspace_files" for t in request.tools):
            return ModelResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id=f"call_{uuid.uuid4().hex[:8]}",
                        name="list_workspace_files",
                        arguments={"subpath": "."},
                    )
                ],
                usage=ModelUsage(prompt_tokens=15, completion_tokens=8, total_tokens=23),
                finish_reason="tool_calls",
            )

        # 5. MCP Mutate Tool: "Mutate/update record <id> to <val>"
        mutate_match = re.search(r"(?:mutate|update)\s+record\s+([^\s]+)\s+to\s+([^\s]+)", content, re.IGNORECASE)
        if mutate_match and request.tools:
            mutate_tool = next((t for t in request.tools if "mutate_record" in t.name), None)
            if mutate_tool:
                return ModelResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id=f"call_{uuid.uuid4().hex[:8]}",
                            name=mutate_tool.name,
                            arguments={
                                "record_id": mutate_match.group(1).strip("\"'"),
                                "new_value": mutate_match.group(2).strip("\"'"),
                            },
                        )
                    ],
                    usage=ModelUsage(prompt_tokens=25, completion_tokens=12, total_tokens=37),
                    finish_reason="tool_calls",
                )

        # 6. Sandbox Execution: "Run code: <code>", "Execute python in sandbox: <code>"
        sandbox_python_match = re.search(r"(?:run|execute)\s+(?:code|python)(?:\s+in\s+sandbox|\s+in\s+docker)?:\s*(.*)", content, re.IGNORECASE | re.DOTALL)
        if sandbox_python_match and request.tools:
            py_tool = next((t for t in request.tools if t.name in {"sandbox_python_execute", "sandbox_run_code"}), None)
            if py_tool:
                code_str = sandbox_python_match.group(1).strip().strip("`")
                return ModelResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id=f"call_{uuid.uuid4().hex[:8]}",
                            name=py_tool.name,
                            arguments={"code": code_str},
                        )
                    ],
                    usage=ModelUsage(prompt_tokens=30, completion_tokens=15, total_tokens=45),
                    finish_reason="tool_calls",
                )

        # 7. Sandbox Shell Execution: "Run shell in sandbox: <command>"
        sandbox_shell_match = re.search(r"(?:run|execute)\s+shell(?:\s+in\s+sandbox|\s+in\s+docker)?:\s*(.*)", content, re.IGNORECASE | re.DOTALL)
        if sandbox_shell_match and request.tools:
            sh_tool = next((t for t in request.tools if t.name == "sandbox_shell_execute"), None)
            if sh_tool:
                cmd_str = sandbox_shell_match.group(1).strip().strip("`")
                return ModelResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id=f"call_{uuid.uuid4().hex[:8]}",
                            name=sh_tool.name,
                            arguments={"command": cmd_str},
                        )
                    ],
                    usage=ModelUsage(prompt_tokens=30, completion_tokens=15, total_tokens=45),
                    finish_reason="tool_calls",
                )

        # If query asks about version/stack and system context contains it, reflect it in response
        if "what" in content.lower() and any(k in content.lower() for k in ["version", "stack", "language"]):
            sys_msgs = [m for m in request.messages if m.role == ModelRole.SYSTEM]
            for sm in sys_msgs:
                if "Python 3.12" in sm.content:
                    return ModelResponse(
                        content="AURA Response: Project uses Python 3.12.",
                        usage=ModelUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
                        finish_reason="stop",
                    )
                if "Python 3.11" in sm.content:
                    return ModelResponse(
                        content="AURA Response: Project uses Python 3.11.",
                        usage=ModelUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
                        finish_reason="stop",
                    )
                if "Go 1.22" in sm.content:
                    return ModelResponse(
                        content="AURA Response: Project uses Go 1.22.",
                        usage=ModelUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
                        finish_reason="stop",
                    )

        # Direct conversational response
        return ModelResponse(
            content=f"AURA Response: Processed '{content}' successfully.",
            usage=ModelUsage(prompt_tokens=15, completion_tokens=10, total_tokens=25),
            finish_reason="stop",
        )
