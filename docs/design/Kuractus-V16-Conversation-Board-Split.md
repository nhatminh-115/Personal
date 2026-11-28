# Kuractus V16 — React frontend migration

This document records the V16 design integration across Kuractus's production React frontend. The standalone HTML is a visual reference only; it is not shipped, embedded, or used as the source of product data.

## Integration boundary

- React remains authoritative for navigation, API calls, project and thread state, approvals, execution traces, workspace objects, and persistence.
- The Kuractus tab remains permanent. Each project reuses one project tab for Overview, Conversation, Board, Split, and Files.
- The Board remains the persisted React Flow project graph. It is not replaced by the prototype's seeded graph.
- Existing project, library, note, study, automation, and conversation records remain the only data sources. New Home empty states describe absent data and route to the real views.
- No backend schema, persistence, session, credential, database, or Docker-volume behavior changes are part of this visual pass.

## V16 design system

- Near-black layered surfaces, soft violet and lime accents, warm white text, subtle borders, and serif display headings establish one visual language across pages.
- Shared navigation, tab/location chrome, buttons, search fields, menus, dialogs, empty states, and focus rings use consistent spacing, contrast, and motion rules.
- Responsive layouts retain project navigation and actions while compacting the sidebar, project controls, and split panes at narrower widths.
- Reduced-motion preferences are honored. Custom routing selects remain accessible listboxes and are not replaced with native browser menus.

## Page-by-page integration matrix

| Surface | V16 treatment | Existing behavior retained |
| --- | --- | --- |
| Workspace shell | Restyled sidebar, topbar, project mode switch, persistent tabs, location/search bar, inspector, and runtime status | Tab history, keyboard search/location shortcuts, navigation, API access, routing controls, inspector, runtime settings |
| Home | Editorial greeting, real recent project and Library previews, live workspace counts, project/Library actions, and explicit empty states | Opens the selected project, Projects, Library, and files; uses canonical aggregate counts |
| Projects | Consistent card grid and forms | Create, archive, restore, include archived projects, and open the selected project |
| Project Overview | Existing project brief, recent conversation list, object counts, and Board entry point in the V16 palette | Opens existing threads, creates a thread, and navigates to Conversation, Board, Files, and Notes |
| Conversation | Compact thread rail, readable timeline, and larger composer | Live chat APIs, streaming, thread selection, branching, context, approvals, provenance, routing, and execution metadata |
| Board | Dark dotted canvas, tuned real graph nodes, toolbar, Context Lens, and V16 object inspector | Persisted React Flow objects/edges/layout, object provenance and revision, relationship navigation, Ask Kuractus, undo/redo, and layer controls |
| Split | Equal-weight chat and Board panes with legible compact controls | Displays the active project conversation with the same live Board graph |
| Project Files | V16 headings, file rows, search, and link picker | Import, link/unlink Library references, browse local artifacts, search, and pagination |
| Library and connected folders | V16 collection, item, connection, folder, and Research Radar surfaces | Local imports, folder permissions and indexing, external source handling, project links, Research Radar, and paging |
| Notes | V16 two-pane list/editor, privacy controls, project links, and conflict notice | Create/update/delete, pin, privacy classification, project scope, conflict reload, and pagination |
| Study | V16 queue/cards/material layout and readable learning controls | Due reviews, durable sessions, reflections, learning cards, provenance, and pagination |
| Automations | V16 routine cards, status, action controls, and dialogs | Scheduling, editing, archive/duplicate, run history, retries/cancellation, approvals, webhook setup, and run inspection |
| Search and file preview | V16 result rows, empty/error states, and preview chrome | Workspace search, open-in-Board/note/Library/Study destinations, connected files, and original file previews |
| Desktop settings and dialogs | Shared V16 surfaces and field styling | Runtime controls, backup/restore entry points, provider configuration, notifications, shortcut, API access, and credential handling |

Prototype sample projects, conversations, messages, board nodes, and mock actions were not introduced into production state.

## Verification

- `npm test -- --reporter=dot --maxWorkers=1 --minWorkers=1` completed with 55 files and all 349 tests passing. Two Board/navigation tests that were intermittent in the first parallel run also passed in isolation.
- `npm test -- src/test/WorkspaceSummaryCounts.test.tsx --reporter=dot` covers the Home aggregate counts and the new real-route/empty-state interactions.
- Existing focused coverage remains in place for accessible `CustomSelect`, Board Object Inspector provenance/relationships, navigation, project chat, Library, Notes, Study, and Automations.
- `npm run build` type-checks and builds the production web bundle successfully. Vite reports its existing large PDF/Excel chunks; this styling pass adds no runtime dependency.
- Windows desktop packaging CI is required for the PR branch. This change does not merge the PR or launch/install the packaged app.
