# AURA V16 — Conversation, Board & Split integration

This note is the implementation handoff for the V16 workspace refinement on the Windows desktop PR branch.

## Integration boundary

The standalone V16 HTML was a visual prototype, not a replacement runtime. The React frontend remains authoritative for navigation, API calls, session state, approvals, execution traces, project objects, and persistence.

Keep the existing product model:
- AURA is the permanent workspace tab.
- Each project reuses one project tab.
- Overview, Chat, Board, Split, and Files remain views inside that project tab.
- Do not add a separate top-level Conversation tab.
- Do not replace the persisted React Flow Board with the prototype's seeded graph.

## V16 interaction direction

- Chat is the primary work surface. Keep the chat thread rail compact, remove unnecessary vertical chrome, and give the message timeline and composer the available height.
- Dropdowns in the main workspace and routing popover use the custom accessible popover control, not browser-native select menus.
- Board remains the existing persisted React Flow workspace graph. Selecting one object opens an Object Inspector with provenance, linked objects, and an Ask AURA action. Following a relationship selects the linked object.
- Split presents the real project Chat and the real project Board simultaneously, with equal visual weight. It is not a summary card or a second chat transcript.

## State and data rules

- Do not introduce the standalone prototype's seeded conversations, decisions, sources, or project cards into production state.
- Keep live chat, approvals, run events, research provenance, memory, and project object APIs unchanged.
- Board relationships are read from the existing workspace graph edges. No new backend schema or persistence behavior is introduced by this UI pass.
- Keep existing Context Lens, Context Bridge, Merge, branching, manual notes, layout persistence, and undo/redo behavior.

## Verification

Add focused component tests for the custom select and Board Object Inspector. The PR's existing backend, frontend, desktop, and Windows packaging workflows remain required; do not weaken CI.
