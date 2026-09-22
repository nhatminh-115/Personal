import {
  BookOpenText,
  Braces,
  CircleDot,
  FlaskConical,
  GitMerge,
  Lightbulb,
  NotebookPen,
  Sparkles,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { chatMessages, codingExecution } from './mockData';
import type { ChatMessage } from '../types';

export type ProjectStatus = 'active' | 'quiet' | 'warning';

export interface ProjectRecord {
  id: string;
  name: string;
  subtitle: string;
  status: ProjectStatus;
  accent: 'cyan' | 'purple' | 'amber' | 'green';
  updated: string;
  meta: string;
  thesis: string;
  next: string;
}

export const projects: ProjectRecord[] = [
  {
    id: 'stateful',
    name: 'Stateful Architecture',
    subtitle: 'Fixed-size internal state for long-context LLMs',
    status: 'active',
    accent: 'cyan',
    updated: '2h ago',
    meta: '4 chats · 3 branches · 9 files',
    thesis: 'Novelty likely sits in state representation + update rule, not update dynamics alone.',
    next: 'Pressure-test long-range retrieval under a strict fixed-state bottleneck.',
  },
  {
    id: 'aura',
    name: 'AURA',
    subtitle: 'Personal AI workspace and routing studio',
    status: 'active',
    accent: 'purple',
    updated: 'today',
    meta: '3 chats · UX prototype · 6 files',
    thesis: 'The workspace should be object-centric and project-aware rather than chatbot-centric.',
    next: 'Connect files, chats, notes and automations into one coherent personal workspace.',
  },
  {
    id: 'transportability',
    name: 'Transportability Paper',
    subtitle: 'Data quality, transportability and indoor sensing',
    status: 'quiet',
    accent: 'amber',
    updated: 'yesterday',
    meta: '2 chats · drafting · 5 files',
    thesis: 'Transportability failures are often caused by invalid proxies, unfittable calibration and support mismatch.',
    next: 'Tighten discussion around deployment failures and derived gas outputs.',
  },
  {
    id: 'personal-agent',
    name: 'Personal Agent',
    subtitle: 'Portfolio agent with durable context and tools',
    status: 'warning',
    accent: 'green',
    updated: '3 days ago',
    meta: '2 chats · 1 blocked experiment · 4 files',
    thesis: 'Use explicit context manifests and tool traces to make agent behavior inspectable.',
    next: 'Resolve memory compaction regression before extending tool coverage.',
  },
];

export interface OrbitRecord {
  id: string;
  label: string;
  detail: string;
  status: 'active' | 'ready' | 'idle' | 'warning';
  angle: number;
  radius: number;
  ring: 'inner' | 'outer';
  icon: LucideIcon;
  targetNode?: string;
}

export const statefulOrbit: OrbitRecord[] = [
  { id: 'ttt', label: 'TTT overlap', detail: '6 sources', status: 'active', angle: -78, radius: 202, ring: 'inner', icon: BookOpenText, targetNode: 'a-answer' },
  { id: 'memory', label: 'Recurrent memory', detail: '5 sources', status: 'ready', angle: -20, radius: 258, ring: 'outer', icon: FlaskConical, targetNode: 'b-answer' },
  { id: 'prototype', label: 'Toy prototype', detail: 'constant memory', status: 'active', angle: 28, radius: 216, ring: 'inner', icon: Braces, targetNode: 'c-answer' },
  { id: 'benchmark', label: 'Benchmark 16k', detail: 'quality −8%', status: 'warning', angle: 82, radius: 252, ring: 'outer', icon: CircleDot, targetNode: 'benchmark-result' },
  { id: 'bridge', label: 'Context bridge', detail: 'A → C applied', status: 'ready', angle: 142, radius: 218, ring: 'inner', icon: GitMerge, targetNode: 'context-bridge' },
  { id: 'note', label: 'Novelty note', detail: 'manual hypothesis', status: 'ready', angle: 194, radius: 260, ring: 'outer', icon: NotebookPen, targetNode: 'note-ttt' },
  { id: 'question', label: 'Open question', detail: 'retrieval bottleneck', status: 'idle', angle: 238, radius: 204, ring: 'inner', icon: Lightbulb, targetNode: 'root-answer' },
];

export const genericOrbit: OrbitRecord[] = [
  { id: 'thread', label: 'Main thread', detail: 'active context', status: 'active', angle: -82, radius: 206, ring: 'inner', icon: Sparkles },
  { id: 'research', label: 'Research', detail: '4 linked sources', status: 'ready', angle: -18, radius: 254, ring: 'outer', icon: BookOpenText },
  { id: 'experiment', label: 'Experiment', detail: 'latest run', status: 'active', angle: 46, radius: 214, ring: 'inner', icon: FlaskConical },
  { id: 'code', label: 'Code result', detail: 'working artifact', status: 'ready', angle: 108, radius: 254, ring: 'outer', icon: Braces },
  { id: 'notes', label: 'Notes', detail: '3 manual notes', status: 'ready', angle: 170, radius: 214, ring: 'inner', icon: NotebookPen },
  { id: 'question', label: 'Open question', detail: 'needs review', status: 'idle', angle: 232, radius: 254, ring: 'outer', icon: Lightbulb },
];

export type LibraryKind = 'HTML' | 'PDF' | 'MD' | 'CSV' | 'TXT' | 'JSON' | 'IMAGE' | 'FILE';

export interface LibraryItem {
  id: string;
  name: string;
  kind: LibraryKind;
  collection: 'Study' | 'Books' | 'Research' | 'Reference';
  detail: string;
  updated: string;
  tags: string[];
  href?: string;
  projectLinks?: string[];
  source?: 'bundled' | 'imported';
  size?: number;
  mimeType?: string;
  blobKey?: string;
}

export const initialLibraryItems: LibraryItem[] = [
  {
    id: 'toeic-progress',
    name: 'TOEIC Progress',
    kind: 'HTML',
    collection: 'Study',
    detail: 'Listening 97/100 · reading plan · weak-part log',
    updated: 'today',
    tags: ['toeic', 'progress'],
    href: '/mock-files/toeic-progress.html',
    source: 'bundled',
  },
  {
    id: 'german-a1',
    name: 'German A1 Tracker',
    kind: 'HTML',
    collection: 'Study',
    detail: 'Vocabulary, sentence drills and weekly streak',
    updated: 'Sep 19',
    tags: ['german', 'language'],
    href: '/mock-files/german-a1.html',
    source: 'bundled',
  },
  {
    id: 'reading-log',
    name: 'AI Reading Log',
    kind: 'HTML',
    collection: 'Research',
    detail: 'Recent papers, extracted ideas and follow-up questions',
    updated: 'Sep 21',
    tags: ['ai', 'papers'],
    href: '/mock-files/reading-log.html',
    projectLinks: ['stateful', 'aura'],
    source: 'bundled',
  },
  {
    id: 'cog-psych',
    name: 'Cognitive Psychology',
    kind: 'PDF',
    collection: 'Books',
    detail: 'Book · 324 pages · 18 highlights',
    updated: 'Sep 16',
    tags: ['psychology', 'book'],
    projectLinks: ['aura'],
    source: 'bundled',
  },
  {
    id: 'transformer-survey',
    name: 'Transformer Architecture Survey',
    kind: 'PDF',
    collection: 'Reference',
    detail: 'Survey · linked to 2 projects',
    updated: 'Sep 14',
    tags: ['transformer', 'reference'],
    projectLinks: ['stateful', 'personal-agent'],
    source: 'bundled',
  },
  {
    id: 'stateful-ideas',
    name: 'Stateful Architecture Ideas',
    kind: 'MD',
    collection: 'Research',
    detail: 'Scratchpad · 14 notes · 6 backlinks',
    updated: '2h ago',
    tags: ['stateful', 'notes'],
    projectLinks: ['stateful'],
    source: 'bundled',
  },
  {
    id: 'benchmark-csv',
    name: 'Fixed-state Benchmark Runs',
    kind: 'CSV',
    collection: 'Research',
    detail: '12 runs · context 2k–32k · quality/memory metrics',
    updated: 'yesterday',
    tags: ['benchmark', 'data'],
    projectLinks: ['stateful'],
    source: 'bundled',
  },
];

// Backwards-compatible alias for static modules that only need initial mock data.
export const libraryItems = initialLibraryItems;

export interface ProjectArtifact {
  id: string;
  projectId: string;
  name: string;
  kind: LibraryKind | 'CODE' | 'NOTE';
  detail: string;
  updated: string;
  origin: 'project' | 'generated';
  status?: 'ready' | 'running' | 'warning';
  linkedLibraryId?: string;
}

export const projectArtifacts: ProjectArtifact[] = [
  { id: 'stateful-arch-md', projectId: 'stateful', name: 'architecture-notes.md', kind: 'MD', detail: 'Core assumptions, state equations and open design choices', updated: '38m ago', origin: 'project' },
  { id: 'stateful-bench-py', projectId: 'stateful', name: 'bench_fixed_state.py', kind: 'CODE', detail: 'Toy benchmark harness · 42 tests passing', updated: '1h ago', origin: 'project' },
  { id: 'stateful-bench-result', projectId: 'stateful', name: 'benchmark-context-16k', kind: 'FILE', detail: 'Generated result · memory constant · quality −8%', updated: '1h ago', origin: 'generated', status: 'warning' },
  { id: 'stateful-ttt-note', projectId: 'stateful', name: 'TTT overlap synthesis', kind: 'NOTE', detail: 'Generated from Research chat · linked to Branch A', updated: '2h ago', origin: 'generated', linkedLibraryId: 'stateful-ideas' },
  { id: 'aura-spec', projectId: 'aura', name: 'AURA_Model_Routing_and_Reasoning_Studio_Spec.md', kind: 'MD', detail: 'Product and interaction specification', updated: 'today', origin: 'project' },
  { id: 'aura-ui', projectId: 'aura', name: 'prototype-v7', kind: 'CODE', detail: 'React + XYFlow frontend prototype', updated: 'today', origin: 'project', status: 'running' },
  { id: 'transport-draft', projectId: 'transportability', name: 'manuscript-draft.md', kind: 'MD', detail: 'Current paper draft', updated: 'yesterday', origin: 'project' },
  { id: 'transport-table', projectId: 'transportability', name: 'source-domain-screening.csv', kind: 'CSV', detail: 'P1–P3 screening table', updated: 'yesterday', origin: 'project' },
  { id: 'agent-memory', projectId: 'personal-agent', name: 'memory-compaction.ts', kind: 'CODE', detail: 'Blocked experiment · regression under long sessions', updated: '3 days ago', origin: 'project', status: 'warning' },
];

export interface WorkspaceNote {
  id: string;
  title: string;
  body: string;
  updated: string;
  tags: string[];
  projectIds: string[];
  pinned?: boolean;
}

export const initialNotes: WorkspaceNote[] = [
  {
    id: 'note-novelty',
    title: 'Novelty framing',
    body: 'Do not claim novelty at inference-time update alone. Pressure-test fixed-size state representation as the only persistent substrate.',
    updated: '18m ago',
    tags: ['research', 'stateful'],
    projectIds: ['stateful'],
    pinned: true,
  },
  {
    id: 'note-aura-principle',
    title: 'AURA product principle',
    body: 'Project is a context container, not the root of the whole personal workspace. Global files and study artifacts must stay first-class.',
    updated: 'today',
    tags: ['aura', 'ux'],
    projectIds: ['aura'],
    pinned: true,
  },
  {
    id: 'note-paper-discussion',
    title: 'Transportability discussion cleanup',
    body: 'Tie deployment failures, silent sensor baselines and derived outputs back to preconditions rather than presenting them as isolated anecdotes.',
    updated: 'yesterday',
    tags: ['paper'],
    projectIds: ['transportability'],
  },
  {
    id: 'note-personal',
    title: 'This week',
    body: 'Keep TOEIC short sessions, continue German A1, and finish one visible portfolio interaction before adding more backend scope.',
    updated: 'today',
    tags: ['personal'],
    projectIds: [],
  },
];

export interface StudyTrack {
  id: string;
  title: string;
  subtitle: string;
  progress: number;
  streak: string;
  next: string;
  libraryIds: string[];
  sessions: { label: string; value: string }[];
  accent: 'cyan' | 'purple' | 'amber';
}

export const studyTracks: StudyTrack[] = [
  {
    id: 'toeic',
    title: 'TOEIC',
    subtitle: 'Listening + Reading',
    progress: 68,
    streak: '4 sessions this week',
    next: 'Part 3 · 25-minute focus block',
    libraryIds: ['toeic-progress'],
    sessions: [{ label: 'Listening', value: '97/100' }, { label: 'Reading', value: 'planned' }, { label: 'Goal', value: '900+' }],
    accent: 'cyan',
  },
  {
    id: 'german',
    title: 'German A1',
    subtitle: 'Vocabulary + sentence drills',
    progress: 34,
    streak: '3-day streak',
    next: 'Cases + 20 new words',
    libraryIds: ['german-a1'],
    sessions: [{ label: 'Words', value: '142' }, { label: 'Sentences', value: '38' }, { label: 'Level', value: 'A1' }],
    accent: 'purple',
  },
  {
    id: 'ai-reading',
    title: 'AI Reading',
    subtitle: 'Architecture papers and notes',
    progress: 51,
    streak: '6 papers this month',
    next: 'Finish recurrent memory comparison',
    libraryIds: ['reading-log', 'transformer-survey'],
    sessions: [{ label: 'Queue', value: '8' }, { label: 'Read', value: '21' }, { label: 'Notes', value: '47' }],
    accent: 'amber',
  },
];

export type AutomationScope = 'global' | 'project';

export interface AutomationRecord {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  scope: AutomationScope;
  projectId?: string;
  trigger: string;
  actions: string[];
  lastRun: string;
  nextRun: string;
  status: 'ready' | 'running' | 'paused';
}

export const initialAutomations: AutomationRecord[] = [
  {
    id: 'auto-paper-scan',
    name: 'Stateful LLM weekly scan',
    description: 'Find new literature, deduplicate against the project, then save only high-signal papers.',
    enabled: true,
    scope: 'project',
    projectId: 'stateful',
    trigger: 'Every Monday · 08:00',
    actions: ['Search papers', 'Compare existing sources', 'Create research note', 'Notify if high relevance'],
    lastRun: '14 papers · 3 retained',
    nextRun: 'Mon · 08:00',
    status: 'ready',
  },
  {
    id: 'auto-study',
    name: 'Study progress digest',
    description: 'Summarize changed study artifacts and surface the next short session.',
    enabled: true,
    scope: 'global',
    trigger: 'Every evening · 20:30',
    actions: ['Read Study collection', 'Update progress summary', 'Surface next session'],
    lastRun: 'TOEIC + German updated',
    nextRun: 'Today · 20:30',
    status: 'ready',
  },
  {
    id: 'auto-benchmark',
    name: 'Benchmark after code change',
    description: 'Run the toy benchmark after a meaningful implementation change.',
    enabled: false,
    scope: 'project',
    projectId: 'stateful',
    trigger: 'When benchmark files change',
    actions: ['Run tests', 'Run context sweep', 'Compare previous result', 'Create code result'],
    lastRun: 'quality −8% at 16k',
    nextRun: 'Paused',
    status: 'paused',
  },
];

export interface ChatThreadRecord {
  id: string;
  projectId: string;
  title: string;
  summary: string;
  updated: string;
  pinned?: boolean;
  messages: ChatMessage[];
  sessionId?: string;
  source?: 'demo' | 'live';
}

function cloneMessages(messages: ChatMessage[]): ChatMessage[] {
  return messages.map((message) => ({
    ...message,
    execution: message.execution?.map((step) => ({ ...step })),
    provenance: message.provenance?.map((item) => ({ ...item })),
  }));
}

const researchSeed: ChatMessage[] = cloneMessages(chatMessages.slice(0, 4));
const codingSeed: ChatMessage[] = [
  { id: 'code-u1', role: 'user', nodeId: 'c-user', branch: 'C', content: 'Implement toy prototype with a strict fixed-size state and run a context-length sweep.', timestamp: '16:02', status: 'Sent' },
  { id: 'code-a1', role: 'assistant', nodeId: 'c-answer', branch: 'C', content: 'The toy implementation keeps state memory approximately constant, but long-range retrieval degrades as the bottleneck saturates. The 16k run is the first clear failure point in this mock.', timestamp: '16:08', status: 'Benchmark saved', specialist: 'Coding Specialist', executionLabel: 'Coding Specialist · 6 steps', execution: codingExecution },
];
const emptySeed = (project: string, text: string): ChatMessage[] => [
  { id: `${project}-seed-u`, role: 'user', nodeId: 'root-user', branch: 'Root', content: text, timestamp: 'earlier', status: 'Sent' },
];

export const initialChatThreads: ChatThreadRecord[] = [
  { id: 'stateful-main', projectId: 'stateful', title: 'Novelty & architecture', summary: 'Main synthesis across TTT, recurrent memory and latent state.', updated: '18m ago', pinned: true, source: 'demo', messages: cloneMessages(chatMessages) },
  { id: 'stateful-ttt', projectId: 'stateful', title: 'TTT overlap deep-dive', summary: 'Where update dynamics overlap and state representation diverges.', updated: '1h ago', source: 'demo', messages: researchSeed },
  { id: 'stateful-code', projectId: 'stateful', title: 'Toy prototype benchmark', summary: 'Fixed memory, 16k context sweep and retrieval failure.', updated: '2h ago', source: 'demo', messages: codingSeed },
  { id: 'stateful-paper', projectId: 'stateful', title: 'Paper framing', summary: 'Turn evidence into a conservative novelty claim.', updated: 'yesterday', source: 'demo', messages: emptySeed('stateful-paper', 'Help me frame the novelty claim conservatively for a paper.') },
  { id: 'aura-main', projectId: 'aura', title: 'Workspace architecture', summary: 'Global workspace vs project-scoped AI interactions.', updated: 'today', pinned: true, source: 'demo', messages: emptySeed('aura-main', 'Design AURA as a personal AI workspace, not just a chatbot frontend.') },
  { id: 'aura-board', projectId: 'aura', title: 'Conversation Board UX', summary: 'Branching, context bridges, merge and smart edges.', updated: 'today', source: 'demo', messages: emptySeed('aura-board', 'Pressure-test the Conversation Board UX and interaction model.') },
  { id: 'aura-routing', projectId: 'aura', title: 'Routing studio', summary: 'Profiles, model locks, reasoning and inspectability.', updated: 'yesterday', source: 'demo', messages: emptySeed('aura-routing', 'What should a routing studio expose without becoming an admin dashboard?') },
  { id: 'transport-main', projectId: 'transportability', title: 'Discussion rewrite', summary: 'Connect observed failures back to transportability preconditions.', updated: 'yesterday', pinned: true, source: 'demo', messages: emptySeed('transport-main', 'Help tighten the Discussion around P1–P3 and deployment failures.') },
  { id: 'transport-gas', projectId: 'transportability', title: 'Derived gas outputs', summary: 'eCO₂/TVOC misuse and literature screening.', updated: '2 days ago', source: 'demo', messages: emptySeed('transport-gas', 'Explain the derived gas output problem and how to present it carefully.') },
  { id: 'agent-main', projectId: 'personal-agent', title: 'Durable context design', summary: 'Explicit manifests, compaction and tool traces.', updated: '3 days ago', pinned: true, source: 'demo', messages: emptySeed('agent-main', 'Design durable context for a personal agent without hiding what was retained.') },
  { id: 'agent-regression', projectId: 'personal-agent', title: 'Memory regression', summary: 'Compaction quality drop under long sessions.', updated: '3 days ago', source: 'demo', messages: emptySeed('agent-regression', 'Diagnose the memory compaction quality regression.') },
];
