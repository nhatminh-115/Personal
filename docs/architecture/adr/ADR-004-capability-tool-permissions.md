# ADR-004: Capability-Based Tool Permissions and Approval Gate

## Status
Accepted

## Context
AI agents equipped with filesystem access or execution capabilities pose severe security risks if allowed to execute unrestricted actions autonomously. Traditional models either grant blanket access to all registered tools or rely on LLM prompts to "be careful", both of which are unacceptable in production.

Conversely, requiring approval for every trivial operation (such as reading a file) creates high friction and degrades user experience.

## Decision
We implement a **Capability-Based Permission Model** coupled with an explicit **Human-in-the-Loop Approval Gate**:
1. **Granular Capabilities:**
   - Tools declare required capabilities from a standardized taxonomy:
     - `filesystem.read`
     - `filesystem.write`
     - `shell.execute`
     - `network.access`
     - `email.read`, `email.send`
     - `git.read`, `git.write`
2. **Permission Policy Engine:**
   - Capabilities are evaluated against a centralized `PermissionPolicy`:
     - Safe, read-only capabilities (e.g., `filesystem.read`) evaluate to `AUTOMATIC`.
     - Mutating or potentially destructive capabilities (e.g., `filesystem.write`, `shell.execute`) evaluate to `REQUIRES_APPROVAL`.
3. **Approval Lifecycle:**
   - If a tool call requires approval, the Orchestrator halts execution, records a pending `Approval` entity in the database, transitions the run status to `waiting_for_approval`, and responds to the client with the pending approval ID.
   - The user inspects the pending action via `GET /v1/approvals/pending` or `GET /v1/approvals/{id}`.
   - The user approves or rejects via `POST /v1/approvals/{id}/decision`.
   - Upon approval, the Orchestrator resumes execution from the approved tool node.

## Consequences
### Positive
- Strict security: State mutation or destructive operations cannot occur without explicit human consent.
- Policy centralization: Tools do not embed ad-hoc permission checks; policy rules are evaluated uniformly by the orchestrator.
- Non-blocking persistence: Suspended approvals survive server restarts.

### Negative / Trade-offs
- Requires asynchronous, multi-turn interaction workflows in client applications to handle the pause-and-resume pattern.
